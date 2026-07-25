"""
Pronunciation Coach — US-74 (engine outage/timeout fallback), US-75 (cross-
session trouble words + spaced repetition), US-76 (accessibility safeguard),
US-79 (word-level highlighting). All four share ONE scoring call — no logic
is forked per story, matching how lib/pronunciation_coach/ itself is built:
one PronunciationPipeline run, wrapped by the reliability manager (US-74),
using the accessibility-aware entry point (US-76), whose per-word ColorTier
results feed the trouble-words bank (US-75) and are returned for highlighting
(US-79). Accent selection (US-82) is threaded in too via
pipeline.resolve_config_for_user(), so a user's target accent genuinely
affects this scoring, not a second copy of it.

Where the real data comes from:
This app has no dedicated "read this target sentence aloud" recording flow —
the only place real per-word ASR timing data exists is an AUDIO-mode turn in
AI Conversation Practice (conversation_service.py), whose word_timings are
now persisted on the turn (see that file's _send_message change). There is
no fixed "target sentence" in free-form conversation, so the turn's own
transcript is used as both the target and the ASR output being aligned
against it — asr_adapter.word_timings_to_attempts() still runs for real,
producing one WordAttempt per word with its real STT timing.

Honest limitation (flagged, not hidden): Faster-Whisper does not emit
per-word confidence (see asr_adapter.py's own docstring), so every
WordAttempt's confidence defaults to the same 0.5 constant. Real code runs
on real timing data, but the resulting tier classification will look
uniform across a turn until the STT layer supplies genuine per-word
confidence. Likewise, `predicted_phonemes`/`target_phonemes` and
`repetitions` are never populated by this ASR path, so the phoneme-pair
regional-variant check and the accessibility stutter-exemption both fall
back to their pre-existing default behavior (documented in
pronunciation_pipeline.py / accessibility_profile.py already).

Persistence: AccessibilityProfileStore, TroubleWordsBank, and the
reliability manager's pending-attempt/results queues are the SAME in-memory
classes lib/pronunciation_coach/ already ships ("no DB layer exists in this
module set" — their own docstrings). Kept in-memory here too (module-level
singletons) rather than bolted onto kv_store, since that would mean
re-implementing their internal (set/dataclass-based) state as JSON on every
call without changing what the feature does — a real conversion, not a
"wiring" change. They reset on backend restart; flagged in the final
summary. Scored turn results ARE persisted for real, via kv_store, since
that's a plain JSON blob with no such conflict.
"""

import logging
from typing import Dict, Optional

from fastapi import Depends
from fastapi.responses import JSONResponse

from lib import kv_store
from lib.accent_assessment.target_accent_selection import TargetAccentSelectionService
from lib.pronunciation_coach.accessibility_profile import (
    AccessibilityProfileStore,
    score_with_accessibility,
)
from lib.pronunciation_coach.asr_adapter import word_timings_to_attempts
from lib.pronunciation_coach.pronunciation_pipeline import (
    AccentPronunciationConfigRegistry,
    ColorTier,
    PronunciationPipeline,
    SentenceScoreResult,
    WordScoreResult,
)
from lib.pronunciation_coach.pronunciation_reliability import (
    PendingResultsBoard,
    PronunciationSubmissionManager,
    ScoringServiceError,
)
from lib.pronunciation_coach.trouble_words import TroubleWordsBank
from middlewares.auth_middleware import require_auth
from schemas.pronunciation_coach_schemas import AccessibilityProfileUpdateSchema

logger = logging.getLogger(__name__)

TURN_SCORE_NAMESPACE = "pronunciation_coach_turn_scores"

# Module-level singletons. `_pipeline` is shared by every request (config
# lookups are per-call via config_override, so this is safe to reuse
# concurrently — see pronunciation_pipeline.py's own docstring on this).
_pipeline = PronunciationPipeline(
    accent_registry=AccentPronunciationConfigRegistry(),
    accent_selection_service=TargetAccentSelectionService(),
)
_accessibility_store = AccessibilityProfileStore()
_trouble_bank = TroubleWordsBank()
_submission_manager = PronunciationSubmissionManager(results_board=PendingResultsBoard())


def _turn_score_key(session_id: str, turn_index: int) -> str:
    return f"{session_id}:{turn_index}"


async def _get_owned_turn(user_id: str, session_id: str, turn_index: int):
    """Loads the conversation turn this pronunciation score is for. Returns
    (session, turn) or an (error) JSONResponse."""
    from services import conversation_service

    session = await kv_store.store.get(conversation_service.NAMESPACE, session_id)
    if session is None or session["user_id"] != user_id:
        return JSONResponse(status_code=404, content={"error": f"Conversation session {session_id} not found"})
    turns = session["turns"]
    if turn_index < 0 or turn_index >= len(turns):
        return JSONResponse(status_code=404, content={"error": f"Turn {turn_index} not found on this session"})
    turn = turns[turn_index]
    if turn["role"] != "user" or turn.get("input_mode") != "audio":
        return JSONResponse(status_code=422, content={
            "error": "This turn has no spoken audio to score pronunciation on.",
        })
    if not turn.get("word_timings"):
        return JSONResponse(status_code=422, content={
            "error": "No word-level timing data was captured for this turn — nothing to score.",
        })
    return session, turn


def _result_to_dict(result: SentenceScoreResult) -> Dict:
    return {
        "target_sentence": result.target_sentence,
        "fluency_score": result.fluency_score,
        "scoring_profile": result.scoring_profile,
        "retry_recommended": result.retry_recommended,
        "words": [_word_to_dict(w) for w in result.words],
    }


def _word_to_dict(w: WordScoreResult) -> Dict:
    return {
        "index": w.index,
        "target_word": w.target_word,
        "tier": w.tier.value,
        "strikethrough": w.strikethrough,
        "final_score": w.final_score,
        "raw_confidence_pct": w.raw_confidence_pct,
        "note": w.note,
    }


async def score_turn(user_id: str, session_id: str, turn_index: int) -> Dict:
    """
    US-74 + US-79 (+ threads US-76/US-82). Scores one audio turn through the
    shared pipeline, wrapped in the reliability manager so a transient
    failure retries/queues instead of surfacing raw errors (US-74), and
    records RED/GRAY words into the trouble-words bank (US-75).
    """
    owned = await _get_owned_turn(user_id, session_id, turn_index)
    if isinstance(owned, JSONResponse):
        return owned
    session, turn = owned

    target_sentence = turn["content"]
    attempts = word_timings_to_attempts(turn["word_timings"], target_sentence)
    profile = _accessibility_store.get(user_id)
    config = await _pipeline.resolve_config_for_user(user_id)

    async def _run_scoring() -> SentenceScoreResult:
        try:
            return score_with_accessibility(
                _pipeline, target_sentence, attempts, profile,
                accent_calibration=True, config_override=config,
            )
        except Exception as exc:  # local scoring failure -> reliability layer's hard-failure path
            raise ScoringServiceError(str(exc)) from exc

    attempt_id = _turn_score_key(session_id, turn_index)
    outcome = await _submission_manager.submit(user_id, attempt_id, audio_ref=session_id, score_callable=_run_scoring)

    response: Dict = {"status": outcome.status.value, "message": outcome.message}
    if outcome.result is not None:
        result_dict = _result_to_dict(outcome.result)
        response["result"] = result_dict
        to_store = {"user_id": user_id, **result_dict}
        if await kv_store.store.get(TURN_SCORE_NAMESPACE, attempt_id) is None:
            await kv_store.store.create(TURN_SCORE_NAMESPACE, attempt_id, to_store)
        else:
            await kv_store.store.update(TURN_SCORE_NAMESPACE, attempt_id, to_store)

        # US-75: feed RED/GRAY words into the cross-session trouble-words bank.
        for word in outcome.result.words:
            if word.tier in (ColorTier.RED, ColorTier.GRAY):
                _trouble_bank.record_word_result(user_id, session_id, word.target_word, word.tier)

    return response


async def get_turn_score(user_id: str, session_id: str, turn_index: int):
    owned = await _get_owned_turn(user_id, session_id, turn_index)
    if isinstance(owned, JSONResponse):
        return owned
    cached = await kv_store.store.get(TURN_SCORE_NAMESPACE, _turn_score_key(session_id, turn_index))
    if cached is None or cached.get("user_id") != user_id:
        return JSONResponse(status_code=404, content={
            "error": "This turn hasn't been scored yet. POST to this URL first.",
        })
    cached.pop("user_id", None)
    return cached


async def get_pending_outcomes(user_id: str) -> Dict:
    """US-74 E-05: badge/notification for scoring that finished in the background
    after the user navigated away."""
    outcomes = _submission_manager.results_board.get_and_clear(user_id)
    return {"outcomes": [
        {"attempt_id": o.attempt_id, "status": o.status.value, "message": o.message,
         "result": _result_to_dict(o.result) if o.result else None}
        for o in outcomes
    ]}


# ── US-76: accessibility profile ────────────────────────────────────────────
async def get_accessibility_profile(user_id: str) -> Dict:
    profile = _accessibility_store.get(user_id)
    return {"opted_in": profile.opted_in, "disclosed_condition": profile.disclosed_condition}


async def update_accessibility_profile(user_id: str, payload: AccessibilityProfileUpdateSchema) -> Dict:
    profile = _accessibility_store.set_opt_in(user_id, payload.opted_in, payload.disclosed_condition)
    return {"opted_in": profile.opted_in, "disclosed_condition": profile.disclosed_condition}


# ── US-75: trouble words bank ───────────────────────────────────────────────
def _entry_to_dict(e) -> Dict:
    return {
        "pattern_key": e.pattern_key,
        "display_word": e.display_word,
        "fail_session_count": e.fail_session_count,
        "correct_session_count": len(e.correct_sessions),
        "related_words": sorted(e.related_words),
        "status": e.status,
        "manually_dismissed": e.manually_dismissed,
        "last_updated": e.last_updated.isoformat(),
    }


async def get_active_trouble_words(user_id: str) -> Dict:
    return {"words": [_entry_to_dict(e) for e in _trouble_bank.get_active_bank(user_id)]}


async def get_trouble_words_archive(user_id: str) -> Dict:
    return {"words": [_entry_to_dict(e) for e in _trouble_bank.get_archive(user_id)]}


async def get_next_review_word(user_id: str) -> Dict:
    entry = _trouble_bank.get_next_review_word(user_id)
    return {"word": _entry_to_dict(entry) if entry else None}


async def dismiss_trouble_word(user_id: str, pattern_key: str) -> Dict:
    _trouble_bank.dismiss_word(user_id, pattern_key)
    return {"pattern_key": pattern_key, "dismissed": True}


# ═══════════════════════════════════════════════════════════════════════════
# FastAPI controllers
# ═══════════════════════════════════════════════════════════════════════════
async def score_turn_endpoint(session_id: str, turn_index: int, user_id: str = Depends(require_auth)):
    return await score_turn(user_id, session_id, turn_index)


async def get_turn_score_endpoint(session_id: str, turn_index: int, user_id: str = Depends(require_auth)):
    return await get_turn_score(user_id, session_id, turn_index)


async def get_pending_outcomes_endpoint(user_id: str = Depends(require_auth)):
    return await get_pending_outcomes(user_id)


async def get_accessibility_profile_endpoint(user_id: str = Depends(require_auth)):
    return await get_accessibility_profile(user_id)


async def update_accessibility_profile_endpoint(
    payload: AccessibilityProfileUpdateSchema, user_id: str = Depends(require_auth)
):
    return await update_accessibility_profile(user_id, payload)


async def get_active_trouble_words_endpoint(user_id: str = Depends(require_auth)):
    return await get_active_trouble_words(user_id)


async def get_trouble_words_archive_endpoint(user_id: str = Depends(require_auth)):
    return await get_trouble_words_archive(user_id)


async def get_next_review_word_endpoint(user_id: str = Depends(require_auth)):
    return await get_next_review_word(user_id)


async def dismiss_trouble_word_endpoint(pattern_key: str, user_id: str = Depends(require_auth)):
    return await dismiss_trouble_word(user_id, pattern_key)
