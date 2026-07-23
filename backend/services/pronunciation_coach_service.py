"""
Pronunciation Coach (US-95): read-a-sentence-aloud, get word-level pronunciation
feedback. Built entirely on top of lib/recording_engine.py (Story #1) — this module
adds only the word-status classification, scoring, and persistence that are specific
to this feature.
"""

import base64
import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from prisma import Json

from lib import kv_store, prosody_engine, recording_engine, text_alignment, tts_client
from lib.audio_io import AudioDecodeError
from lib.prisma_client import db
from lib.recording_engine import RejectionReason
from lib.speech_config import load_speech_config
from lib.text_alignment import WordStatus
from middlewares.auth_middleware import require_auth
from schemas.pronunciation_schemas import (
    PronunciationResultSchema,
    RecordingRejectedSchema,
    TargetSentenceSchema,
    WordResultSchema,
)
from services import accent_calibration_service, liveness_service
from utils.feature_errors import (
    InvalidSubmissionError,
    SentenceNotFoundError,
    UnreadableAudioError,
    UploadTooLargeError,
)

logger = logging.getLogger(__name__)


_STATUS_POINTS = {
    WordStatus.CORRECT: 100.0,
    WordStatus.STRESS_ERROR: 70.0,
    WordStatus.MISPRONOUNCED: 30.0,
    WordStatus.SKIPPED: 0.0,
}

# ── PRN-US-10 / PRN-US-11: "hear correct pronunciation" playback ────────────────
_TTS_CACHE_NS = "pronunciation_tts_cache"
_VALID_SPEEDS = ("normal", "slow")


class SentenceBank:
    def __init__(self):
        path = Path(__file__).parent.parent / "data" / "pronunciation_sentences.json"
        with open(path, "r", encoding="utf-8") as f:
            raw: Dict[str, List[dict]] = json.load(f)
        self._by_id = {s["sentence_id"]: s for sentences in raw.values() for s in sentences}
        self._all = list(self._by_id.values())

    def get_by_id(self, sentence_id: str) -> Optional[dict]:
        return self._by_id.get(sentence_id)

    def all(self) -> List[dict]:
        return self._all

    def random(self, difficulty: Optional[str] = None) -> dict:
        pool = [s for s in self._all if s["difficulty"] == difficulty] if difficulty else self._all
        return random.choice(pool or self._all)


_sentence_bank = SentenceBank()


# ── Local Accent Calibration hook (US-90 — not built yet) ────────────────────────────
def apply_accent_calibration(
    word_results: List[WordResultSchema], accent_profile: Optional[str]
) -> List[WordResultSchema]:
    """Stub: once US-90's calibration model exists, this is where accent-specific
    thresholds/expected pronunciation variants get applied before scoring is finalized.
    No-op today so `accent_profile` can be threaded through the API now without another
    interface change once the real model lands."""
    return word_results


def _classify_word(
    aligned: text_alignment.AlignedWord,
    transcript_words,
    prosody: prosody_engine.ProsodyData,
    config,
) -> WordResultSchema:
    timing = transcript_words[aligned.transcript_index] if aligned.transcript_word is not None else None
    status = recording_engine.classify_word_status(aligned.target_word, timing, prosody, config)
    return WordResultSchema(
        word=aligned.target_word,
        target_index=aligned.target_index,
        status=status.value,
        confidence=round(timing.probability, 3) if timing is not None else None,
    )


def _overall_score(word_results: List[WordResultSchema]) -> float:
    if not word_results:
        return 0.0
    points = [_STATUS_POINTS[WordStatus(w.status)] for w in word_results]
    return round(sum(points) / len(points), 2)


async def get_target_sentence(
    sentence_id: Optional[str] = None,
    difficulty: Optional[str] = None,
    user_id: str = Depends(require_auth),
):
    if sentence_id:
        sentence = _sentence_bank.get_by_id(sentence_id)
        if not sentence:
            raise SentenceNotFoundError(f"Unknown sentence_id: {sentence_id}")
    else:
        last = await kv_store.store.get("last_user_sentence", user_id)
        exclude_id = last.get("sentence_id") if (last and isinstance(last, dict)) else None
        sentence = _sentence_bank.random(difficulty, exclude_id=exclude_id)
        entry = {"sentence_id": sentence["sentence_id"]}
        if not last:
            await kv_store.store.create("last_user_sentence", user_id, entry)
        else:
            await kv_store.store.update("last_user_sentence", user_id, entry)

    prompt_token = await liveness_service.create_prompt_token(user_id, sentence["sentence_id"])
    return TargetSentenceSchema(**sentence, prompt_token=prompt_token)


async def submit_pronunciation_attempt(
    sentence_id: str,
    audio: UploadFile = File(...),
    accent_profile: Optional[str] = Form(None),
    prompt_token: Optional[str] = Form(None),
    drill_type: Optional[str] = Form(None),
    user_id: str = Depends(require_auth),
):
    # ACC-US-01 E-03: Account suspension check
    if await liveness_service.check_user_suspended(user_id):
        return JSONResponse(
            status_code=403,
            content={"error": "Accent assessment access temporarily suspended due to repeated playback flags (3+). Account routed to support review."},
        )

    # ACC-US-01 E-04: Prompt token validation (if provided)
    if prompt_token is not None:
        valid_token = await liveness_service.validate_and_consume_prompt_token(user_id, sentence_id, prompt_token)
        if not valid_token:
            return JSONResponse(
                status_code=422,
                content={"error": "Stale, missing, or reused prompt session token. Please fetch a fresh sentence."},
            )

    sentence = _sentence_bank.get_by_id(sentence_id)
    if not sentence:
        raise SentenceNotFoundError(f"Unknown sentence_id: {sentence_id}")

    config = load_speech_config()
    audio_bytes = await audio.read()
    max_bytes = config.pronunciation_max_upload_mb * 1024 * 1024
    if len(audio_bytes) > max_bytes:
        raise UploadTooLargeError(f"Recording exceeds the {config.pronunciation_max_upload_mb}MB limit")

    try:
        analysis = recording_engine.analyze_recording(audio_bytes, config)
    except AudioDecodeError as e:
        raise UnreadableAudioError(str(e))

    # ACC-US-01 E-01: Playback audio signal check
    playback_reason = recording_engine.detect_playback_audio(analysis, config)
    if playback_reason is not None:
        flag_info = await liveness_service.record_liveness_flag(
            user_id=user_id,
            item_id=sentence_id,
            prompt_token=prompt_token,
            reason=playback_reason.value,
        )
        return JSONResponse(
            status_code=422,
            content=RecordingRejectedSchema(
                reason=playback_reason.value,
                message="Detected playback audio. Live speech required.",
                appeal_token=flag_info["appeal_token"],
                appeal_prompt=flag_info["appeal_prompt"],
            ).model_dump(),
        )

    # ACC-US-11 E-01: Check STT breakdown fallback
    has_breakdown, breakdown_warning, clarity_fallback = accent_calibration_service.handle_stt_breakdown_fallback(analysis)

    if analysis.rejection is not None and not has_breakdown:
        return JSONResponse(
            status_code=422,
            content=RecordingRejectedSchema(
                reason=analysis.rejection.value,
                message=_rejection_message(analysis.rejection),
            ).model_dump(),
        )

    user_pref = accent_profile or await accent_calibration_service.get_user_accent_preference(user_id)
    conflict_msg = accent_calibration_service.check_drill_conflict(drill_type, user_pref)
    if conflict_msg:
        return JSONResponse(
            status_code=400,
            content={"warning": conflict_msg, "error": conflict_msg},
        )

    aligned_words = recording_engine.align_to_sentence(analysis, sentence["text"])
    word_results = [_classify_word(a, analysis.words, analysis.prosody, config) for a in aligned_words]

    # ACC-US-11: Calibrate word results for South Asian accent model
    word_results, calibration_warning, model_used = accent_calibration_service.calibrate_word_results(
        word_results, user_pref, drill_type=drill_type
    )

    disfluency_detected = recording_engine.detect_disfluency(analysis, config)
    overall_score = _overall_score(word_results) if not has_breakdown else clarity_fallback

    existing = await db.pronunciationattempt.find_unique(
        where={"userId_sentenceId": {"userId": user_id, "sentenceId": sentence_id}}
    )
    data = {
        "targetText": sentence["text"],
        "transcript": analysis.transcript or "Phonetic clarity fallback",
        "wordResults": Json([w.model_dump() for w in word_results]),
        "overallScore": overall_score,
        "accentProfileTag": model_used,
        "backgroundVoiceDetected": analysis.multiple_voices_detected,
        "disfluencyDetected": disfluency_detected,
    }

    if existing:
        attempt = await db.pronunciationattempt.update(
            where={"id": existing.id},
            data={**data, "attemptCount": existing.attemptCount + 1},
        )
    else:
        attempt = await db.pronunciationattempt.create(
            data={"userId": user_id, "sentenceId": sentence_id, "attemptCount": 1, **data}
        )

    warning_notice = breakdown_warning or calibration_warning
    return PronunciationResultSchema(
        attempt_id=attempt.id,
        sentence_id=sentence_id,
        target_text=sentence["text"],
        transcript=analysis.transcript or "Phonetic clarity fallback",
        overall_score=overall_score,
        word_results=word_results,
        attempt_count=attempt.attemptCount,
        background_voice_detected=analysis.multiple_voices_detected,
        disfluency_detected=disfluency_detected,
        accent_profile=model_used,
        warning=warning_notice,
        model_used=model_used,
    )



def _tts_cache_key(word: str, speed: str) -> str:
    return f"{word.strip().lower()}::{speed}"


async def _get_cached_audio(word: str, speed: str, ttl_seconds: int) -> Optional[bytes]:
    entry = await kv_store.store.get(_TTS_CACHE_NS, _tts_cache_key(word, speed))
    if entry is None:
        return None
    cached_at: datetime = entry["cached_at"]
    age = (datetime.now(timezone.utc) - cached_at).total_seconds()
    if age > ttl_seconds:
        return None
    return base64.b64decode(entry["audio_b64"])


async def _store_cached_audio(word: str, speed: str, audio: bytes) -> None:
    key = _tts_cache_key(word, speed)
    value = {"audio_b64": base64.b64encode(audio).decode("ascii"), "cached_at": datetime.now(timezone.utc)}
    if await kv_store.store.get(_TTS_CACHE_NS, key) is None:
        await kv_store.store.create(_TTS_CACHE_NS, key, value)
    else:
        await kv_store.store.update(_TTS_CACHE_NS, key, value)


async def get_word_pronunciation_audio(word: str, speed: str = "normal", user_id: str = Depends(require_auth)):
    """Correct-pronunciation playback for a single word/short phrase — fires when the
    user taps a mispronounced word (PRN-US-10, speed=normal) or when the retry loop
    hits PRN-US-11's E-01 exception and offers a slow breakdown instead (speed=slow).
    `word` is reused as-is from a WordResultSchema.word the client already has; no
    server-side retry-streak tracking is added here, that stays a frontend concern."""
    if speed not in _VALID_SPEEDS:
        raise InvalidSubmissionError(f"speed must be one of {_VALID_SPEEDS}")

    config = load_speech_config()
    cached = await _get_cached_audio(word, speed, config.pronunciation_tts_cache_ttl_seconds)
    if cached is not None:
        return Response(content=cached, media_type="audio/wav")

    if not tts_client.is_configured():
        return JSONResponse(status_code=503, content={
            "error": "TTS engine unavailable. Fall back to your device's native text-to-speech.",
        })

    length_scale = 1.0 if speed == "normal" else config.pronunciation_tts_slow_length_scale
    try:
        audio = tts_client.synthesize(word, length_scale=length_scale)
    except tts_client.TTSError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    await _store_cached_audio(word, speed, audio)
    return Response(content=audio, media_type="audio/wav")


def _rejection_message(reason: RejectionReason) -> str:
    return {
        RejectionReason.NO_SPEECH_DETECTED: "No speech was detected in the recording. Please try again.",
        RejectionReason.AUDIO_TOO_QUIET: "The recording is too quiet to analyze. Please move closer to the microphone.",
        RejectionReason.BACKGROUND_NOISE_TOO_HIGH: "Background noise is too high to analyze. Please try again in a quieter environment.",
        RejectionReason.INCOMPLETE_RECORDING: "The recording appears to be incomplete.",
        RejectionReason.MULTIPLE_VOICES_DETECTED: "Multiple voices were detected in the recording.",
    }[reason]
