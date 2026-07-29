"""
Unit & Integration Tests for STORY — PDG-US-10: Progress Dashboard Tracking

Covers:
  - Happy Path: Primary Confidence Score metric, trend lines, practice time, streak.
  - E-01 (Data Sync Failure): Fallback to last-known-good snapshot with sync_status="stale".
  - E-02 (Empty State - Day 1): Zero-state payload with motivational prompt for new users.
  - E-03 (Corrupted Session Data): Outliers (> 100 or < 0) dropped from aggregates & flagged.
  - E-04 (Streak Calculation): Rolling 24-48h UTC window calculation resilient to timezone shifts.
"""

from datetime import datetime, timedelta, timezone
import pytest
from lib import kv_store
from services import progress_dashboard_service


# ── Helpers ──────────────────────────────────────────────────────────────────────────────────

async def _seed_test_dashboard_records(user_id: str, records: list):
    """Seed test session records into KV store for isolated offline test runs."""
    await kv_store.store.create("test_dashboard_records", user_id, records)


# ── Happy Path Tests ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_progress_dashboard_happy_path():
    """PDG-US-10 Happy Path: Aggregates metrics, returns top-line Confidence Score & trend lines."""
    user_id = "user_pdg_happy_01"
    now = datetime.now(timezone.utc)
    t1 = now - timedelta(days=2)
    t2 = now - timedelta(days=1)

    records = [
        {
            "source": "coaching",
            "completed_at": t1,
            "confidence_score": 75.0,
            "fluency_score": 70.0,
            "vocabulary_score": 80.0,
            "pronunciation_score": 72.0,
            "duration_seconds": 300.0,
        },
        {
            "source": "public_speaking",
            "completed_at": t2,
            "confidence_score": 88.0,
            "fluency_score": 82.0,
            "vocabulary_score": 85.0,
            "pronunciation_score": 80.0,
            "duration_seconds": 600.0,
        },
    ]
    await _seed_test_dashboard_records(user_id, records)

    res = await progress_dashboard_service.get_progress_dashboard(user_id=user_id)

    assert res["user_id"] == user_id
    assert res["is_empty_state"] is False
    assert res["sync_status"] == "synced"
    assert res["is_stale"] is False

    # Acceptance Criteria 2: Confidence Score as central primary metric
    primary = res["primary_metric"]
    assert primary["name"] == "Confidence Score"
    assert primary["is_primary"] is True
    assert primary["value"] == 88.0  # Latest completed session score

    # Summary metrics
    summary = res["summary_metrics"]
    assert summary["completed_sessions_count"] == 2
    assert summary["total_practice_time_minutes"] == 15.0  # 900 seconds / 60
    assert summary["daily_streak_days"] >= 1

    # Acceptance Criteria 3: Time-series trend lines
    trend = res["trend_lines"]
    assert len(trend) == 2
    assert trend[0]["confidence_score"] == 75.0
    assert trend[1]["confidence_score"] == 88.0


# ── E-01: Data Sync Failure Snapshot Fallback ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_progress_dashboard_e01_sync_failure_stale_fallback(monkeypatch):
    """PDG-US-10 E-01: DB failure returns last-known-good snapshot with sync_status='stale'."""
    user_id = "user_pdg_e01_02"
    now = datetime.now(timezone.utc)

    # 1. First run: seed records, get a good snapshot cached in KV store
    records = [{
        "source": "scenario",
        "completed_at": now - timedelta(hours=5),
        "confidence_score": 82.0,
        "fluency_score": 78.0,
        "vocabulary_score": 80.0,
        "duration_seconds": 400.0,
    }]
    await _seed_test_dashboard_records(user_id, records)
    good_res = await progress_dashboard_service.get_progress_dashboard(user_id=user_id)
    assert good_res["sync_status"] == "synced"

    # 2. Simulate DB sync failure by making both the test-records KV lookup
    #    and the real DB fetch raise an error. Use a fresh user_id that has
    #    NO "test_dashboard_records" entry so the service tries _fetch_completed_records_from_db.
    stale_user_id = "user_pdg_e01_stale_02b"

    # Pre-seed the snapshot in KV under the stale user so it has something to fall back to
    snapshot_key = f"{stale_user_id}"
    await kv_store.store.create(
        progress_dashboard_service.DASHBOARD_SNAPSHOT_NS,
        snapshot_key,
        {
            **good_res,
            "user_id": stale_user_id,
            "primary_metric": good_res["primary_metric"],
        },
    )

    async def mock_fail_db(*args, **kwargs):
        raise ConnectionError("Postgres DB connection timeout")

    monkeypatch.setattr(progress_dashboard_service, "_fetch_completed_records_from_db", mock_fail_db)

    # No test_dashboard_records seeded for stale_user_id → service will try DB → fail → fallback
    stale_res = await progress_dashboard_service.get_progress_dashboard(user_id=stale_user_id)

    # Must return last-known-good data with sync_status: "stale"
    assert stale_res["sync_status"] == "stale"
    assert stale_res["is_stale"] is True
    assert "Syncing recent data" in stale_res["sync_message"]



# ── E-02: Empty State — Day 1 User ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_progress_dashboard_e02_empty_state_day1():
    """PDG-US-10 E-02: Day 1 user with zero completed sessions returns zero-state payload."""
    user_id = "user_pdg_e02_day1_03"
    # No records seeded for this user

    res = await progress_dashboard_service.get_progress_dashboard(user_id=user_id)

    assert res["is_empty_state"] is True
    assert res["empty_state_prompt"] is not None
    assert "Daily Challenge" in res["empty_state_prompt"] or "first session" in res["empty_state_prompt"]

    # Check zeroed primary metric & totals
    assert res["primary_metric"]["value"] == 0.0
    assert res["primary_metric"]["is_primary"] is True
    assert res["summary_metrics"]["completed_sessions_count"] == 0
    assert res["summary_metrics"]["total_practice_time_minutes"] == 0.0
    assert res["summary_metrics"]["daily_streak_days"] == 0
    assert res["trend_lines"] == []


# ── E-03: Corrupted Session Data Outlier Filter ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_progress_dashboard_e03_corrupted_session_outlier_filtered():
    """PDG-US-10 E-03: Outlier scores (> 100 or < 0) are dropped and flagged, not skewing metrics."""
    user_id = "user_pdg_e03_outlier_04"
    now = datetime.now(timezone.utc)

    records = [
        {
            "source": "coaching",
            "completed_at": now - timedelta(days=2),
            "confidence_score": 80.0,
            "fluency_score": 75.0,
            "duration_seconds": 300.0,
        },
        # Corrupted session with impossible score 150.0
        {
            "source": "coaching",
            "completed_at": now - timedelta(days=1),
            "confidence_score": 150.0,  # Corrupted outlier!
            "fluency_score": -20.0,     # Corrupted outlier!
            "duration_seconds": 300.0,
        },
    ]
    await _seed_test_dashboard_records(user_id, records)

    res = await progress_dashboard_service.get_progress_dashboard(user_id=user_id)

    # Outlier should be flagged and dropped
    assert res["flagged_outliers_count"] >= 1
    # Primary confidence score must use valid 80.0, NOT corrupted 150.0
    assert res["primary_metric"]["value"] == 80.0
    assert res["primary_metric"]["value"] <= 100.0


# ── E-04: Streak Calculation (Rolling 24-48h UTC Window) ──────────────────────────────────

def test_progress_dashboard_e04_rolling_streak_calculation():
    """PDG-US-10 E-04: Rolling 24-48h UTC window calculates streaks across timezone boundaries."""
    now = datetime.now(timezone.utc)

    # Session 1: 5 hours ago
    # Session 2: 32 hours ago (across day boundary/timezone shift, but within 48h rolling window)
    records = [
        {"completed_at": now - timedelta(hours=32)},
        {"completed_at": now - timedelta(hours=5)},
    ]

    streak = progress_dashboard_service.calculate_rolling_streak(records)
    # Gap of 27h is within the 48h rolling window -> streak is maintained (2)
    assert streak == 2


def test_progress_dashboard_e04_streak_resets_after_48h_gap():
    """PDG-US-10 E-04: Gap > 48 hours resets streak to 0 or 1."""
    now = datetime.now(timezone.utc)

    # Session 1: 60 hours ago (more than 48 hours ago)
    records = [
        {"completed_at": now - timedelta(hours=60)},
    ]

    streak = progress_dashboard_service.calculate_rolling_streak(records)
    # Inactive for > 48h -> streak is 0
    assert streak == 0
