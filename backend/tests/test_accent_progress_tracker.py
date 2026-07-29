"""
Unit & Integration Tests for STORY 1 — ACC-US-12: Accent Progress Tracker Visualization
"""

import pytest
from lib import kv_store
from services import accent_tracker_service
from schemas.accent_schemas import AccentProgressTrackerSchema


# ── Helpers ──────────────────────────────────────────────────────────────────────────────────

async def _seed_tracker_months(user_id: str, months: dict):
    """Seed KV store with month index data for offline testing."""
    entry = {f"month_{k}": v for k, v in months.items()}
    existing = await kv_store.store.get(accent_tracker_service.ACCENT_TRACKER_NS, user_id)
    if existing:
        await kv_store.store.update(accent_tracker_service.ACCENT_TRACKER_NS, user_id, entry)
    else:
        await kv_store.store.create(accent_tracker_service.ACCENT_TRACKER_NS, user_id, entry)


# ── Happy Path ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_accent_progress_tracker_month_over_month():
    """ACC-US-12 Happy Path: Month 1 vs Month 3 side-by-side metric comparison."""
    user_id = "user_tracker_happy_01"
    await _seed_tracker_months(user_id, {
        1: {"pronunciation": 70.0, "word_stress": 65.0, "intonation": 72.0, "clarity": 78.0},
        3: {"pronunciation": 82.0, "word_stress": 80.0, "intonation": 85.0, "clarity": 90.0},
    })

    result = await accent_tracker_service.get_accent_progress_tracker(user_id=user_id)

    assert isinstance(result, AccentProgressTrackerSchema)
    assert result.is_insufficient_data is False
    assert len(result.months) == 2
    month1 = next(m for m in result.months if m.month == 1)
    month3 = next(m for m in result.months if m.month == 3)
    assert month1.pronunciation == 70.0
    assert month1.is_locked is False
    assert month3.pronunciation == 82.0
    assert month3.clarity == 90.0
    # No regressions in happy path
    assert result.regressed_metrics == []
    assert result.cta_suggestion is None


# ── E-01: Insufficient Historical Data ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_accent_progress_tracker_e01_insufficient_data():
    """ACC-US-12 E-01: User has < 2 months of assessments — future months locked with message."""
    user_id = "user_tracker_e01_02"
    # Only 1 month of data seeded
    await _seed_tracker_months(user_id, {
        1: {"pronunciation": 72.0, "word_stress": 68.0, "intonation": None, "clarity": 75.0},
    })

    result = await accent_tracker_service.get_accent_progress_tracker(user_id=user_id)

    assert result.is_insufficient_data is True
    assert "keep practicing" in result.message.lower()
    assert "check back next month" in result.message.lower()

    # Future months must be locked (is_locked=True), not 0/false
    locked_months = [m for m in result.months if m.is_locked]
    assert len(locked_months) >= 2
    for locked in locked_months:
        assert locked.pronunciation is None
        assert locked.word_stress is None


@pytest.mark.asyncio
async def test_accent_progress_tracker_e01_brand_new_user():
    """ACC-US-12 E-01: Brand-new user with zero data — all future months locked with default baseline."""
    user_id = "user_tracker_e01_new_03"
    # No data seeded for this user

    result = await accent_tracker_service.get_accent_progress_tracker(user_id=user_id)

    assert result.is_insufficient_data is True
    assert result.message is not None
    # All future months locked
    locked_months = [m for m in result.months if m.is_locked]
    assert len(locked_months) >= 2


# ── E-02: Score Regression ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_accent_progress_tracker_e02_score_regression():
    """ACC-US-12 E-02: Month 3 scores lower than Month 1 — flag regression, return non-alarming CTA."""
    user_id = "user_tracker_e02_04"
    await _seed_tracker_months(user_id, {
        1: {"pronunciation": 85.0, "word_stress": 78.0, "intonation": 80.0, "clarity": 88.0},
        3: {"pronunciation": 70.0, "word_stress": 65.0, "intonation": 70.0, "clarity": 75.0},
    })

    result = await accent_tracker_service.get_accent_progress_tracker(user_id=user_id)

    assert result.is_insufficient_data is False
    assert len(result.regressed_metrics) > 0
    # Non-alarming CTA suggestion, not a harsh message
    assert result.cta_suggestion is not None
    assert "targeted exercises" in result.cta_suggestion.lower()
    # Regressed metrics should include the affected ones
    for metric in ["pronunciation", "word_stress", "intonation", "clarity"]:
        assert metric in result.regressed_metrics


# ── E-03: Missing Sub-Metric Data ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_accent_progress_tracker_e03_missing_sub_metric():
    """ACC-US-12 E-03: Missing sub-metric data returns None (not 0) so it doesn't skew the trendline."""
    user_id = "user_tracker_e03_05"
    await _seed_tracker_months(user_id, {
        1: {"pronunciation": 75.0, "word_stress": 70.0, "intonation": None, "clarity": 80.0},
        2: {"pronunciation": 80.0, "word_stress": 75.0, "intonation": None, "clarity": 85.0},
    })

    result = await accent_tracker_service.get_accent_progress_tracker(user_id=user_id)

    assert result.is_insufficient_data is False
    for m in result.months:
        # Intonation must be None, not 0 — must not skew trendline
        assert m.intonation is None, f"Month {m.month} intonation should be None, got {m.intonation}"
        # Other metrics present
        assert m.pronunciation is not None
        assert m.clarity is not None
