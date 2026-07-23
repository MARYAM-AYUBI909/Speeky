"""
Local Accent Calibration Service (ACC-US-11)

Implements South Asian / Pakistani English regional stress & phonetic shift calibration,
STT failure fallback to phonetic clarity (E-01), Western Improvement drill conflict check (E-02),
and model loading fallback to generic global model (E-03).
"""

import logging
from typing import Dict, List, Optional, Tuple

from lib import kv_store
from lib.prisma_client import db
from lib.recording_engine import RecordingAnalysis
from lib.speech_config import load_speech_config
from lib.text_alignment import WordStatus
from schemas.pronunciation_schemas import WordResultSchema

logger = logging.getLogger(__name__)

VALID_ACCENT_MODELS = {"generic_global", "south_asian_pakistani"}
ACCENT_PREF_NS = "user_accent_preference"

# Common South Asian / Pakistani English phonetic shift substitutions (Urdu influence)
SOUTH_ASIAN_PHONETIC_SHIFTS = {
    "th": ["d", "t", "dh"],
    "w": ["v"],
    "v": ["w"],
    "p": ["ph"],
    "t": ["th", "d"],
    "d": ["dh", "t"],
}


async def _is_db_connected() -> bool:
    try:
        return db.is_connected()
    except Exception:
        return False


async def get_user_accent_preference(user_id: str) -> str:
    """Fetch user's accent model preference from database or KV store."""
    if await _is_db_connected():
        try:
            user = await db.user.find_unique(where={"id": user_id})
            if user and user.accentModelPreference:
                return user.accentModelPreference
        except Exception:
            pass

    entry = await kv_store.store.get(ACCENT_PREF_NS, user_id)
    if entry and isinstance(entry, dict):
        return entry.get("preference", "generic_global")
    return "generic_global"


async def update_user_accent_preference(user_id: str, preference: str) -> str:
    """Update user's accent model preference."""
    if preference not in VALID_ACCENT_MODELS:
        raise ValueError(f"Invalid accent model preference: {preference}. Must be one of {VALID_ACCENT_MODELS}")

    entry = {"user_id": user_id, "preference": preference}
    if await kv_store.store.get(ACCENT_PREF_NS, user_id) is None:
        await kv_store.store.create(ACCENT_PREF_NS, user_id, entry)
    else:
        await kv_store.store.update(ACCENT_PREF_NS, user_id, entry)

    if await _is_db_connected():
        try:
            user = await db.user.update(
                where={"id": user_id},
                data={"accentModelPreference": preference},
            )
            return user.accentModelPreference
        except Exception as e:
            logger.warning(f"DB accent preference update failed: {e}")

    return preference


def check_drill_conflict(drill_type: Optional[str], accent_preference: str) -> Optional[str]:
    """E-02: Check if user attempts a strict Western Accent Improvement drill while Local Calibration is ON."""
    if accent_preference == "south_asian_pakistani" and drill_type in ("western_improvement", "strict_western"):
        return "Conflicting model usage detected. Please temporarily disable Local Accent Calibration for this Western Accent Improvement drill."
    return None


def calibrate_word_results(
    word_results: List[WordResultSchema],
    accent_preference: str,
    drill_type: Optional[str] = None,
) -> Tuple[List[WordResultSchema], Optional[str], str]:
    """Calibrate word results for South Asian / Pakistani English regional stress and phonetic shifts (ACC-US-11).
    
    Returns (calibrated_word_results, warning_message, model_used).
    """
    config = load_speech_config()

    # E-02 Conflict check
    conflict_msg = check_drill_conflict(drill_type, accent_preference)
    if conflict_msg:
        return word_results, conflict_msg, accent_preference

    # E-03 Model loading failure fallback check
    if accent_preference == "south_asian_pakistani" and not config.local_accent_model_available:
        warning = "Local acoustic model failed to load due to network latency. Defaulting to Generic Global model."
        return word_results, warning, "generic_global"

    if accent_preference != "south_asian_pakistani":
        return word_results, None, "generic_global"

    # Apply South Asian calibration rules
    calibrated: List[WordResultSchema] = []
    for w in word_results:
        w_copy = w.model_copy()
        
        # 1. Accept regional stress shifts (e.g. Urdu stress placement)
        if w_copy.status == WordStatus.STRESS_ERROR.value:
            # Reclassify regional stress shift as CORRECT under local calibration
            w_copy.status = WordStatus.CORRECT.value

        # 2. Accept common regional phonetic shift substitutions (e.g. /th/ -> /d|t/)
        elif w_copy.status == WordStatus.MISPRONOUNCED.value:
            target_lower = w_copy.word.lower()
            # If target has regional shift sounds and confidence is reasonably fair
            if any(shift_key in target_lower for shift_key in SOUTH_ASIAN_PHONETIC_SHIFTS):
                if w_copy.confidence is not None and w_copy.confidence >= 0.35:
                    w_copy.status = WordStatus.CORRECT.value

        calibrated.append(w_copy)

    return calibrated, None, "south_asian_pakistani"


def handle_stt_breakdown_fallback(analysis: RecordingAnalysis) -> Tuple[bool, Optional[str], float]:
    """E-01: Detect extreme dialect distortion breaking STT transcriber and fall back to phonetic clarity scoring.
    
    Returns (has_breakdown, warning_message, phonetic_clarity_score).
    """
    if not analysis.transcript or len(analysis.words) == 0:
        # Extreme breakdown fallback calculation from prosody/pitch & intensity stability
        pitch_sd = 10.0
        if analysis.prosody and len(analysis.prosody.f0_contour) > 5:
            import numpy as np
            voiced = [f for f in analysis.prosody.f0_contour if f > 0]
            if len(voiced) > 5:
                pitch_sd = float(np.std(voiced))

        phonetic_clarity = round(max(30.0, min(85.0, 100.0 - pitch_sd * 2.0)), 2)
        warning = "Extreme dialect distortion detected breaking STT transcriber. Falling back to phonetic clarity scoring. Please try speaking a bit slower."
        return True, warning, phonetic_clarity

    return False, None, 0.0
