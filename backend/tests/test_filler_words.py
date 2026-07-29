"""
Unit & Integration Tests for STORY — PSC-US-08: Filler Word Tracking & Visualization

Covers:
  - Happy path: Timeline/waveform markers, frequency counts, actionable tip.
  - E-01 ("Like" as a Valid Word vs. Syntactic Filler): Context-aware NLP filter.
  - E-02 (Heavy Breathing / Mic Pops): Acoustic confidence & spectral decibel filter.
  - E-03 (Zero Filler Words - Perfect Score): "Flawless Delivery" badge indicator.
  - Session endpoint retrieval and error handling (404 for missing session).
"""

import pytest
from lib import kv_store
from services import filler_word_service
from schemas.filler_word_schemas import FillerWordAnalysisSchema
from utils.feature_errors import SessionNotFoundError


# ── Helpers ──────────────────────────────────────────────────────────────────────────────────

async def _seed_session_in_kv(session_id: str, user_id: str, transcript: str, speech_type: str = "business_pitch"):
    entry = {
        "id": session_id,
        "userId": user_id,
        "transcript": transcript,
        "submission": transcript,
        "speechType": speech_type,
        "status": "completed",
    }
    await kv_store.store.create(filler_word_service.FILLER_WORD_NS, session_id, entry)


# ── Happy Path Tests ─────────────────────────────────────────────────────────────────────────

def test_filler_word_analysis_happy_path():
    """PSC-US-08 Happy Path: Detect filler words, frequencies, timeline markers, and actionable tip."""
    text = "Um, hello everyone. Today, uh, I will present, like, our quarterly progress. You know, we worked hard."
    analysis = filler_word_service.analyze_filler_words(text, session_id="sess_happy_01", speech_type="business_pitch")

    assert isinstance(analysis, FillerWordAnalysisSchema)
    assert analysis.total_filler_count >= 3
    assert analysis.flawless_delivery is False
    assert analysis.badge is None

    # Verify frequency counts
    freqs = analysis.filler_frequencies
    assert "um" in freqs or "uh" in freqs
    assert "you know" in freqs

    # Verify timeline markers
    markers = analysis.timeline_markers
    assert len(markers) == analysis.total_filler_count
    for m in markers:
        assert m.word in ["um", "uh", "like", "you know"]
        assert m.start_time is not None
        assert m.end_time is not None
        assert m.confidence > 0.0

    # Verify actionable tip about silence/pausing
    assert "pause" in analysis.actionable_tip.lower() or "silence" in analysis.actionable_tip.lower()


# ── E-01: "Like" as a Valid Word vs Syntactic Filler ─────────────────────────────────────────

def test_filler_word_e01_valid_like_grammatical_contexts():
    """PSC-US-08 E-01: Valid verb/preposition usages of 'like' are NOT tagged as fillers."""
    # "I like this project", "We would like to present", "It looks like an apple"
    text1 = "I like this project and we would like to present our findings."
    analysis1 = filler_word_service.analyze_filler_words(text1)
    assert analysis1.total_filler_count == 0
    assert analysis1.flawless_delivery is True
    assert analysis1.badge == "Flawless Delivery"

    text2 = "It looks like a great opportunity and feels like a good fit."
    analysis2 = filler_word_service.analyze_filler_words(text2)
    assert analysis2.total_filler_count == 0


def test_filler_word_e01_syntactic_filler_like():
    """PSC-US-08 E-01: Syntactic hesitation fillers ('it was, like, hard') ARE tagged as fillers."""
    text = "It was, like, really hard to finish, and so, like, we stopped."
    analysis = filler_word_service.analyze_filler_words(text)
    assert analysis.total_filler_count >= 1
    assert "like" in analysis.filler_frequencies


# ── E-02: Heavy Breathing / Mic Pops ─────────────────────────────────────────────────────────

def test_filler_word_e02_heavy_breathing_mic_pops_discarded():
    """PSC-US-08 E-02: Acoustic features with low confidence or breathing profile are discarded."""
    text = "Ah, welcome to the presentation."
    word_timings = [
        # "ah" with low confidence / breathing flag
        {
            "word": "ah",
            "start": 0.1,
            "end": 0.2,
            "confidence": 0.45,
            "is_breathing": True,
            "avg_db": -50.0,
            "snr_db": 5.0,
        },
        {"word": "welcome", "start": 0.3, "end": 0.7, "confidence": 0.95},
        {"word": "to", "start": 0.7, "end": 0.8, "confidence": 0.95},
        {"word": "the", "start": 0.8, "end": 0.9, "confidence": 0.95},
        {"word": "presentation", "start": 0.9, "end": 1.5, "confidence": 0.95},
    ]

    analysis = filler_word_service.analyze_filler_words(text, word_timings=word_timings)
    # The suspected "ah" breath sound should be discarded
    assert analysis.total_filler_count == 0
    assert analysis.flawless_delivery is True


# ── E-03: Zero Filler Words — Perfect Score ──────────────────────────────────────────────────

def test_filler_word_e03_zero_filler_words_flawless_delivery():
    """PSC-US-08 E-03: Zero filler words returns 'Flawless Delivery' flag and badge."""
    text = "Good morning ladies and gentlemen. Today we present our technical strategy for scaling backend infrastructure."
    analysis = filler_word_service.analyze_filler_words(text)

    assert analysis.total_filler_count == 0
    assert analysis.flawless_delivery is True
    assert analysis.badge == "Flawless Delivery"
    assert "Flawless delivery" in analysis.analysis_summary
    assert "silence" in analysis.actionable_tip.lower() or "pause" in analysis.actionable_tip.lower()


# ── Session Endpoint & Retrieval Tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_filler_words_for_session_from_kv():
    """PSC-US-08: Retrieve filler word analysis for a completed session from KV store."""
    session_id = "sess_kv_filler_01"
    user_id = "user_filler_test_99"
    transcript = "Um, I think, uh, we should proceed with the deployment."
    await _seed_session_in_kv(session_id, user_id, transcript)

    res = await filler_word_service.get_filler_words_for_session(session_id=session_id, user_id=user_id)

    assert res["session_id"] == session_id
    assert res["total_filler_count"] >= 2
    assert "actionable_tip" in res
    assert len(res["timeline_markers"]) >= 2


@pytest.mark.asyncio
async def test_get_filler_words_session_not_found():
    """PSC-US-08: Requesting non-existent session raises SessionNotFoundError (404)."""
    with pytest.raises(SessionNotFoundError) as exc_info:
        await filler_word_service.get_filler_words_for_session(session_id="non_existent_123", user_id="user_any")

    assert "not found" in str(exc_info.value).lower()
