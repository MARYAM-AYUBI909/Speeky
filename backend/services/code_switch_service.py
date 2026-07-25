"""
CSC-US-01: Code-Switch Coaching & Correction — the personalized-list + NER side.

Detection/feedback (isolating the non-English word, suggesting the English equivalent) is
already produced as `code_switch` flags by Workplace Coaching (services/coaching_service.py
+ lib/prompts.WORKPLACE_FEEDBACK_PROMPT). This module adds the two pieces that story asks
for on top of that:

  * E-01 proper-noun guard: a local name/place (e.g. "Lahore") must NOT be flagged as
    code-switching. There's no NER dependency in this backend, so the guard is a curated
    proper-noun list plus a casing heuristic (a mid-sentence Capitalized token reads as a
    proper noun). Conservative by design — better to miss a flag than to scold "Lahore".
  * Logging: every genuinely code-switched word is upserted into the learner's
    "common code-switch words" list (CodeSwitchWord) for targeted practice (TC-003).
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from fastapi import Depends

from lib.prisma_client import db
from middlewares.auth_middleware import require_auth

logger = logging.getLogger(__name__)

# Curated proper nouns that also read as ordinary lowercased tokens elsewhere — the casing
# heuristic below catches most Capitalized names, this backstops the common South-Asian
# places/names a learner is likely to mention (E-01 / TC-002). Lowercased for matching.
_PROPER_NOUNS = {
    "lahore", "karachi", "islamabad", "rawalpindi", "peshawar", "quetta", "multan",
    "faisalabad", "hyderabad", "delhi", "mumbai", "kolkata", "dhaka", "punjab", "sindh",
    "pakistan", "india", "bangladesh",
}


def _capitalized_midsentence(word: str, submission: str) -> bool:
    """True if `word` appears Capitalized somewhere that isn't sentence-initial — the
    signal that it's a proper noun rather than a code-switched common word. Sentence-initial
    capitals are ambiguous (every sentence starts capitalized), so they don't count."""
    for m in re.finditer(r"\b(\w+)\b", submission):
        token = m.group(1)
        if token.lower() != word.lower():
            continue
        preceding = submission[: m.start()].rstrip()
        sentence_initial = preceding == "" or preceding[-1] in ".!?"
        if token[:1].isupper() and not sentence_initial:
            return True
    return False


def is_proper_noun(word: str, submission: str) -> bool:
    return word.lower() in _PROPER_NOUNS or _capitalized_midsentence(word, submission)


def filter_and_extract(flags: List[Dict], submission: str) -> Tuple[List[Dict], List[Dict]]:
    """Drop code_switch flags that are proper nouns (E-01) and return
    (kept_flags, code_switch_words) where each word is {"word", "suggestion"} for logging.

    Non-code_switch flags pass through untouched.
    """
    kept: List[Dict] = []
    words: List[Dict] = []
    for flag in flags:
        if flag.get("type") != "code_switch":
            kept.append(flag)
            continue
        phrase = (flag.get("phrase") or "").strip()
        if not phrase or is_proper_noun(phrase, submission):
            # Proper noun / empty — do not flag, do not log (accepts the sentence, TC-002).
            continue
        kept.append(flag)
        words.append({"word": phrase.lower(), "suggestion": (flag.get("suggestion") or "").strip()})
    return kept, words


async def record_words(user_id: str, code_switch_words: List[Dict]) -> None:
    """Upsert each code-switched word into the learner's practice list (count++ on repeat).
    Best-effort: a logging failure must never break the coaching submission that called it."""
    now = datetime.now(timezone.utc)
    for entry in code_switch_words:
        word = entry["word"]
        if not word:
            continue
        try:
            existing = await db.codeswitchword.find_unique(
                where={"userId_word": {"userId": user_id, "word": word}}
            )
            if existing:
                await db.codeswitchword.update(
                    where={"id": existing.id},
                    data={
                        "count": existing.count + 1,
                        "lastSeenAt": now,
                        "suggestion": entry["suggestion"] or existing.suggestion,
                    },
                )
            else:
                await db.codeswitchword.create(
                    data={
                        "userId": user_id,
                        "word": word,
                        "suggestion": entry["suggestion"],
                    }
                )
        except Exception:
            logger.exception("Failed to log code-switch word %r for user %s", word, user_id)


async def track_from_flags(user_id: str, flags: List[Dict], submission: str) -> List[Dict]:
    """Combined entry point for coaching_service: filter proper nouns out of `flags`,
    persist the real code-switched words, and return the cleaned flag list to store/show."""
    kept, words = filter_and_extract(flags, submission)
    if words:
        await record_words(user_id, words)
    return kept


# ── Controllers ────────────────────────────────────────────────────────────────
async def list_code_switch_words(user_id: str = Depends(require_auth)):
    """The learner's personalized code-switch practice tracker, most-frequent first."""
    rows = await db.codeswitchword.find_many(
        where={"userId": user_id}, order=[{"count": "desc"}, {"lastSeenAt": "desc"}]
    )
    return {
        "words": [
            {
                "id": r.id,
                "word": r.word,
                "suggestion": r.suggestion,
                "count": r.count,
                "last_seen_at": r.lastSeenAt.isoformat(),
            }
            for r in rows
        ],
        "total": len(rows),
    }


async def delete_code_switch_word(word_id: str, user_id: str = Depends(require_auth)):
    """Remove a word once the learner has mastered it (practice tracker cleanup)."""
    from fastapi.responses import JSONResponse

    row = await db.codeswitchword.find_unique(where={"id": word_id})
    if not row or row.userId != user_id:
        return JSONResponse(status_code=404, content={"error": "Word not found"})
    await db.codeswitchword.delete(where={"id": word_id})
    return {"id": word_id, "deleted": True}
