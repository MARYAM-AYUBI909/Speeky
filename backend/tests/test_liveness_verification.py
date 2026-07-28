"""
Unit & Integration Tests for STORY 1 — ACC-US-01: Live Speech Verification (Anti-Playback / Anti-Cheat)
"""

import pytest
from dataclasses import dataclass
from typing import List, Optional

from lib import recording_engine, stt_engine, vad_engine, prosody_engine
from lib.recording_engine import RecordingAnalysis, RejectionReason
from lib.speech_config import load_speech_config
from services import liveness_service

U = "user_test_liveness_101"


@dataclass
class DummyVad:
    has_speech: bool = True
    speech_segments: List[tuple] = None

    def __post_init__(self):
        if self.speech_segments is None:
            self.speech_segments = [(0.0, 3.0)]


@dataclass
class DummyProsody:
    pitch_hz: List[float] = None
    pitch_range_semitones: float = 8.0
    syllable_nuclei_times: List[float] = None

    def __post_init__(self):
        if self.pitch_hz is None:
            self.pitch_hz = [120.0, 125.0, 130.0, 128.0, 122.0, 119.0, 124.0, 126.0, 131.0, 127.0, 121.0]
        if self.syllable_nuclei_times is None:
            self.syllable_nuclei_times = [0.2, 0.5, 0.9, 1.3, 1.7, 2.1, 2.5]


def _mock_analysis(
    noise_floor_dbfs: float = -45.0,
    snr_db: float = 25.0,
    avg_dbfs: float = -20.0,
    duration: float = 3.0,
    flat_pitch: bool = False,
) -> RecordingAnalysis:
    prosody = DummyProsody()
    if flat_pitch:
        prosody.pitch_hz = [120.0] * 20
    return RecordingAnalysis(
        transcript="The quick brown fox jumps over the lazy dog",
        duration_seconds=duration,
        words=[
            stt_engine.WordTiming(word="The", start=0.1, end=0.3, probability=0.95),
            stt_engine.WordTiming(word="quick", start=0.4, end=0.7, probability=0.92),
        ],
        vad=DummyVad(),
        avg_dbfs=avg_dbfs,
        noise_floor_dbfs=noise_floor_dbfs,
        snr_db=snr_db,
        prosody=prosody,
        multiple_voices_detected=False,
        rejection=None,
    )


@pytest.mark.asyncio
async def test_prompt_token_creation_and_single_use_validation():
    """ACC-US-01 E-04: Dynamic runtime prompt token issuance and single-use consumption."""
    item_id = "pas_test_001"
    token = await liveness_service.create_prompt_token(U, item_id)
    assert token.startswith("prm_")

    # Valid first consumption
    valid = await liveness_service.validate_and_consume_prompt_token(U, item_id, token)
    assert valid is True

    # E-04: Second consumption must fail (single-use enforcement)
    reused_valid = await liveness_service.validate_and_consume_prompt_token(U, item_id, token)
    assert reused_valid is False


@pytest.mark.asyncio
async def test_stale_or_invalid_prompt_token_rejection():
    """ACC-US-01 E-04: Non-existent or mismatched prompt token rejection."""
    valid = await liveness_service.validate_and_consume_prompt_token(U, "pas_test_001", "prm_fake_12345")
    assert valid is False


def test_detect_playback_audio_flagging():
    """ACC-US-01: Playback audio signal detection (flat noise floor & SNR anomalies)."""
    config = load_speech_config()

    # Normal live mic reading
    normal_analysis = _mock_analysis(noise_floor_dbfs=-50.0, snr_db=25.0)
    assert recording_engine.detect_playback_audio(normal_analysis, config) is None

    # E-01 Playback audio with flat/absent noise floor (< -75 dBFS)
    playback_flat_noise = _mock_analysis(noise_floor_dbfs=-85.0, snr_db=60.0)
    assert recording_engine.detect_playback_audio(playback_flat_noise, config) == RejectionReason.PLAYBACK_DETECTED

    # E-01 Playback audio with unnatural flat line pitch
    playback_flat_pitch = _mock_analysis(noise_floor_dbfs=-45.0, snr_db=30.0, flat_pitch=True)
    assert recording_engine.detect_playback_audio(playback_flat_pitch, config) == RejectionReason.PLAYBACK_DETECTED


@pytest.mark.asyncio
async def test_consecutive_get_target_passage_returns_different_content():
    """ACC-US-01: Two consecutive calls for the same user return different passage content (not just tokens)."""
    from services.accent_assessment_service import get_target_passage
    p1 = await get_target_passage(user_id="user_rand_check_1")
    p2 = await get_target_passage(user_id="user_rand_check_1")

    # Tokens must be distinct
    assert p1.prompt_token != p2.prompt_token
    # Passage content (passage_id, title, text) must be randomized & non-repeating
    assert p1.passage_id != p2.passage_id
    assert p1.text != p2.text

