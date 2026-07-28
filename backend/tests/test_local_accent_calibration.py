"""
Unit & Integration Tests for STORY 2 — ACC-US-11: Local Accent Calibration Model Activation
"""

import pytest
from dataclasses import dataclass
from typing import List

from lib.recording_engine import RecordingAnalysis
from lib.text_alignment import WordStatus
from schemas.pronunciation_schemas import WordResultSchema
from services import accent_calibration_service

U_ACCENT = "user_test_accent_202"


@dataclass
class DummyProsody:
    pitch_hz: List[float] = None
    pitch_range_semitones: float = 8.0
    syllable_nuclei_times: List[float] = None

    def __post_init__(self):
        if self.pitch_hz is None:
            self.pitch_hz = [120.0, 125.0, 130.0, 128.0]


def test_accent_preference_toggle_validation():
    """ACC-US-11: Validate model options ('generic_global' vs 'south_asian_pakistani')."""
    assert "generic_global" in accent_calibration_service.VALID_ACCENT_MODELS
    assert "south_asian_pakistani" in accent_calibration_service.VALID_ACCENT_MODELS

    with pytest.raises(ValueError):
        # Invalid accent model must fail
        import asyncio
        asyncio.run(accent_calibration_service.update_user_accent_preference(U_ACCENT, "invalid_model_abc"))


def test_south_asian_stress_and_phonetic_shift_calibration():
    """ACC-US-11: Accept valid South Asian regional stress/phonetic shifts while catching genuine errors."""
    input_results = [
        WordResultSchema(word="computer", target_index=0, status=WordStatus.STRESS_ERROR.value, confidence=0.90),
        WordResultSchema(word="this", target_index=1, status=WordStatus.MISPRONOUNCED.value, confidence=0.75),
        WordResultSchema(word="cat", target_index=2, status=WordStatus.MISPRONOUNCED.value, confidence=0.10),
    ]

    # Under Generic Global: word statuses unchanged
    calibrated_global, _, model_used_g = accent_calibration_service.calibrate_word_results(
        input_results, "generic_global"
    )
    assert model_used_g == "generic_global"
    assert calibrated_global[0].status == WordStatus.STRESS_ERROR.value

    # Under South Asian / Pakistani English calibration:
    calibrated_sa, _, model_used_sa = accent_calibration_service.calibrate_word_results(
        input_results, "south_asian_pakistani"
    )
    assert model_used_sa == "south_asian_pakistani"
    # Regional stress shift on 'computer' accepted as CORRECT
    assert calibrated_sa[0].status == WordStatus.CORRECT.value
    # Regional phonetic shift on 'this' (th -> d/t) accepted as CORRECT
    assert calibrated_sa[1].status == WordStatus.CORRECT.value
    # Genuine mispronunciation on 'cat' (low confidence 0.10) remains MISPRONOUNCED
    assert calibrated_sa[2].status == WordStatus.MISPRONOUNCED.value


def test_stt_breakdown_fallback_to_phonetic_clarity():
    """ACC-US-11 E-01: Extreme dialect distortion STT breakdown falls back to phonetic clarity score with speak-slower prompt."""
    breakdown_analysis = RecordingAnalysis(
        transcript="",  # Empty transcript due to extreme distortion
        duration_seconds=5.0,
        words=[],
        vad=None,
        avg_dbfs=-22.0,
        noise_floor_dbfs=-45.0,
        snr_db=23.0,
        prosody=DummyProsody(),
        multiple_voices_detected=False,
        rejection=None,
    )

    has_breakdown, warning, score = accent_calibration_service.handle_stt_breakdown_fallback(breakdown_analysis)
    assert has_breakdown is True
    assert "speaking a bit slower" in warning.lower() or "speak" in warning.lower()
    assert 30.0 <= score <= 100.0



def test_western_improvement_drill_conflict_warning():
    """ACC-US-11 E-02: Western Accent Improvement drill conflict warning when Local Calibration is ON."""
    warning = accent_calibration_service.check_drill_conflict("western_improvement", "south_asian_pakistani")
    assert warning is not None
    assert "temporarily disable local accent calibration" in warning.lower()

    # No conflict when user has generic_global active
    assert accent_calibration_service.check_drill_conflict("western_improvement", "generic_global") is None


def test_model_loading_failure_fallback_to_generic_global(monkeypatch):
    """ACC-US-11 E-03: Model load failure defaults to generic global with network latency warning."""
    # Simulate local model unavailable
    monkeypatch.setenv("LOCAL_ACCENT_MODEL_AVAILABLE", "false")

    input_results = [
        WordResultSchema(word="test", target_index=0, status=WordStatus.CORRECT.value, confidence=0.90)
    ]
    _, warning, model_used = accent_calibration_service.calibrate_word_results(
        input_results, "south_asian_pakistani"
    )
    assert model_used == "generic_global"
    assert "network latency" in warning.lower()


@pytest.mark.asyncio
async def test_sub_dialect_granularity_happy_path_and_beta_notice():
    """ACC-US-09: Happy path sub-dialect calibration (Punjabi) applying narrower tolerance and beta notice."""
    user_id = "user_sub_dialect_happy_1"
    model, sub, notice = await accent_calibration_service.update_user_accent_preference(
        user_id, preference="south_asian_pakistani", sub_dialect="punjabi"
    )
    assert model == "south_asian_pakistani"
    assert sub == "punjabi"
    assert notice is not None and "[beta refinement]" in notice.lower()

    input_results = [
        WordResultSchema(word="school", target_index=0, status=WordStatus.MISPRONOUNCED.value, confidence=0.80),
        WordResultSchema(word="this", target_index=1, status=WordStatus.MISPRONOUNCED.value, confidence=0.75),
    ]

    calibrated, warning, model_used = accent_calibration_service.calibrate_word_results(
        input_results, accent_preference=model, sub_dialect_preference=sub
    )

    assert model_used == "south_asian_pakistani:punjabi"
    assert warning is not None and "beta" in warning.lower()
    assert calibrated[0].status == WordStatus.CORRECT.value
    assert calibrated[1].status == WordStatus.CORRECT.value


@pytest.mark.asyncio
async def test_sub_dialect_optionality_and_default_behavior():
    """ACC-US-09: Sub-dialect selection is optional; skipping defaults to broad south_asian_pakistani model."""
    user_id = "user_sub_dialect_default_2"
    model, sub, notice = await accent_calibration_service.update_user_accent_preference(
        user_id, preference="south_asian_pakistani", sub_dialect=None
    )
    assert model == "south_asian_pakistani"
    assert sub is None
    assert notice is None

    input_results = [
        WordResultSchema(word="this", target_index=0, status=WordStatus.MISPRONOUNCED.value, confidence=0.85)
    ]
    calibrated, warning, model_used = accent_calibration_service.calibrate_word_results(
        input_results, accent_preference=model, sub_dialect_preference=sub
    )

    assert model_used == "south_asian_pakistani"
    assert warning is None
    assert calibrated[0].status == WordStatus.CORRECT.value


@pytest.mark.asyncio
async def test_sub_dialect_e01_low_confidence_fallback():
    """ACC-US-09 E-01: Low-confidence sub-dialect (Balochi/Kashmiri) falls back to broad regional model with warning."""
    user_id = "user_sub_dialect_low_conf_3"
    model, sub, notice = await accent_calibration_service.update_user_accent_preference(
        user_id, preference="south_asian_pakistani", sub_dialect="balochi"
    )
    assert model == "south_asian_pakistani"
    assert sub == "balochi"
    assert "limited data for this dialect" in notice.lower()

    input_results = [
        WordResultSchema(word="this", target_index=0, status=WordStatus.MISPRONOUNCED.value, confidence=0.80)
    ]
    calibrated, warning, model_used = accent_calibration_service.calibrate_word_results(
        input_results, accent_preference=model, sub_dialect_preference=sub
    )

    assert model_used == "south_asian_pakistani"  # Fallback to broad model
    assert warning is not None and "limited data for this dialect" in warning.lower()
    assert calibrated[0].status == WordStatus.CORRECT.value  # Broad model tolerance applied


@pytest.mark.asyncio
async def test_sub_dialect_e02_mixed_dialect_revert():
    """ACC-US-09 E-02: Mixed-dialect speaker can revert to broad model at any time without losing score history."""
    user_id = "user_sub_dialect_revert_4"
    # First select Pashto
    await accent_calibration_service.update_user_accent_preference(user_id, "south_asian_pakistani", "pashto")
    # Revert to broad model
    model, sub, notice = await accent_calibration_service.update_user_accent_preference(
        user_id, "south_asian_pakistani", None
    )
    assert model == "south_asian_pakistani"
    assert sub is None
    assert notice is None


@pytest.mark.asyncio
async def test_sub_dialect_e03_misclassification_dispute_routing():
    """ACC-US-09 E-03: Route sub-dialect misclassification complaint to dispute mechanism and revert to broad model."""
    user_id = "user_sub_dialect_dispute_5"
    await accent_calibration_service.update_user_accent_preference(user_id, "south_asian_pakistani", "sindhi")

    result = await accent_calibration_service.submit_sub_dialect_dispute(
        user_id, dispute_reason="I do not match Sindhi sub-dialect tolerance rules"
    )

    assert result["status"] == "resolved"
    assert result["sub_dialect_preference"] is None
    assert result["accent_model_preference"] == "south_asian_pakistani"
    assert "dispute logged and resolved" in result["message"].lower()

    # Confirm user preference in state is now reverted to broad model
    model, sub, _ = await accent_calibration_service.get_user_accent_preference(user_id)
    assert model == "south_asian_pakistani"
    assert sub is None

