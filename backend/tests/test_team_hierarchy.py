"""
Unit & Integration Tests for ENT-US-03: Department & Team Hierarchy Management

Covers:
  - Test 1: Nested creation & MAX_TEAM_DEPTH limit validation
  - Test 2: Delete-with-members block (E-01) & archive workflow
  - Test 3: Circular nesting rejection (E-02)
  - Test 4: Duplicate team name disambiguation (E-04)
  - Test 5: Mid-quarter employee move data integrity (E-05)
  - Test 6: Bulk reassignment CSV conflict reporting (E-03)
"""

from datetime import datetime, timedelta, timezone
import pytest

from lib import kv_store
from schemas.team_schemas import (
    AssignMemberSchema,
    BulkAssignCSVRequest,
    BulkAssignCSVRow,
    TeamCreateSchema,
    TeamUpdateSchema,
)
from services import team_service
from utils.app_error import AppError


@pytest.fixture(autouse=True)
async def _clean_team_store():
    """Ensure clean isolated in-memory stores per test."""
    await kv_store.store.clear_namespace(team_service.TEAM_STORE_NS)
    await kv_store.store.clear_namespace("user_team_store")
    await kv_store.store.clear_namespace("user_history_store")
    await kv_store.store.clear_namespace("user_email_store")
    await kv_store.store.clear_namespace("test_practice_sessions")
    yield



# ── Test 1: Nested Creation & Depth Limit Validation ─────────────────────────────

@pytest.mark.asyncio
async def test_nested_team_creation_and_depth_limit(monkeypatch):
    """AC 1: Teams support nested structure up to MAX_TEAM_DEPTH; exceeding depth is rejected."""
    monkeypatch.setenv("MAX_TEAM_DEPTH", "3")

    # Depth 1: Root Department
    root = await team_service.create_team(TeamCreateSchema(name="Engineering"))
    assert root["name"] == "Engineering"
    assert root["parentId"] is None

    # Depth 2: Division
    div = await team_service.create_team(
        TeamCreateSchema(name="Backend Division", parent_id=root["id"])
    )
    assert div["parentId"] == root["id"]

    # Depth 3: Sub-team (Max depth allowed)
    sub = await team_service.create_team(
        TeamCreateSchema(name="API Core", parent_id=div["id"])
    )
    assert sub["parentId"] == div["id"]

    # Depth 4: Exceeds MAX_TEAM_DEPTH=3 -> Must be rejected with HTTP 400
    with pytest.raises(AppError) as exc_info:
        await team_service.create_team(
            TeamCreateSchema(name="Microservices", parent_id=sub["id"])
        )
    assert exc_info.value.status_code == 400
    assert "depth limit exceeded" in exc_info.value.message.lower()


# ── Test 2: Delete-With-Members Block (E-01) ────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_non_empty_team_blocked(monkeypatch):
    """E-01: Deleting a team with active members is blocked; archive reassigns members first."""
    team = await team_service.create_team(TeamCreateSchema(name="Sales - APAC"))
    team_id = team["id"]
    user_id = "user_sales_rep_01"

    # Assign member to team
    await team_service.assign_member(
        AssignMemberSchema(user_id=user_id, team_id=team_id, secondary_tags=["APAC"])
    )

    # Attempting to delete non-empty team -> Blocked with HTTP 409 conflict
    with pytest.raises(AppError) as exc_info:
        await team_service.delete_team(team_id)
    assert exc_info.value.status_code == 409
    assert "Cannot delete team" in exc_info.value.message
    assert "active member" in exc_info.value.message

    # Archive team -> Reassigns members and soft-deletes team
    archive_res = await team_service.archive_team(team_id)
    assert archive_res["archived"] is True
    assert archive_res["reassigned_members_count"] == 1

    # Team can now be deleted or remains archived
    del_res = await team_service.delete_team(team_id)
    assert del_res["deleted"] is True


# ── Test 3: Circular Nesting Rejection (E-02) ───────────────────────────────────

@pytest.mark.asyncio
async def test_circular_hierarchy_rejection():
    """E-02: Nesting a parent department under its own sub-team is rejected."""
    # Dept A -> Sub-team B -> Sub-team C
    dept_a = await team_service.create_team(TeamCreateSchema(name="Dept A"))
    dept_b = await team_service.create_team(
        TeamCreateSchema(name="Sub B", parent_id=dept_a["id"])
    )
    dept_c = await team_service.create_team(
        TeamCreateSchema(name="Sub C", parent_id=dept_b["id"])
    )

    # Attempting to set Dept A's parent to Sub C (circular) -> Rejected with 400
    with pytest.raises(AppError) as exc_info:
        await team_service.update_team(
            dept_a["id"], TeamUpdateSchema(parent_id=dept_c["id"])
        )
    assert exc_info.value.status_code == 400
    assert "Circular hierarchy detected" in exc_info.value.message


# ── Test 4: Duplicate Name Disambiguation (E-04) ────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_team_name_disambiguation():
    """E-04: Duplicate team names auto-append disambiguators (e.g. Sales (2))."""
    t1 = await team_service.create_team(TeamCreateSchema(name="Marketing"))
    assert t1["name"] == "Marketing"
    assert t1.get("warning") is None

    t2 = await team_service.create_team(TeamCreateSchema(name="Marketing"))
    assert t2["name"] == "Marketing (2)"
    assert "auto-disambiguated to 'Marketing (2)'" in t2["warning"]

    t3 = await team_service.create_team(TeamCreateSchema(name="Marketing"))
    assert t3["name"] == "Marketing (3)"
    assert "auto-disambiguated to 'Marketing (3)'" in t3["warning"]


# ── Test 5: Mid-Quarter Move Data Integrity (E-05) ──────────────────────────────

@pytest.mark.asyncio
async def test_mid_quarter_move_data_integrity():
    """E-05: Historical practice data stays attributed to old team; future data rolls to new team."""
    team_a = await team_service.create_team(TeamCreateSchema(name="Team Alpha"))
    team_b = await team_service.create_team(TeamCreateSchema(name="Team Beta"))

    user_id = "user_emp_move_101"

    # Step 1: Employee assigned to Team Alpha at t0
    t0 = datetime.now(timezone.utc) - timedelta(days=60)
    # Simulate history start at t0
    await kv_store.store.create(
        "user_history_store",
        user_id,
        [
            {
                "id": "th_1",
                "userId": user_id,
                "teamId": team_a["id"],
                "startDate": t0.isoformat(),
                "endDate": None,
            }
        ],
    )

    # Practice Session 1 while in Team Alpha (at t0 + 10 days)
    t1_session = t0 + timedelta(days=10)
    sessions = [
        {
            "id": "sess_01",
            "completed_at": t1_session.isoformat(),
            "confidence_score": 80.0,
            "fluency_score": 75.0,
            "duration_seconds": 600.0,
        }
    ]
    await kv_store.store.create("test_practice_sessions", user_id, sessions)

    # Step 2: Employee moves mid-quarter to Team Beta (at t0 + 30 days)
    t_move = t0 + timedelta(days=30)
    # Close old history & open new
    histories = await kv_store.store.get("user_history_store", user_id)
    histories[0]["endDate"] = t_move.isoformat()
    histories.append(
        {
            "id": "th_2",
            "userId": user_id,
            "teamId": team_b["id"],
            "startDate": t_move.isoformat(),
            "endDate": None,
        }
    )
    await kv_store.store.create("user_history_store", user_id, histories)

    # Practice Session 2 while in Team Beta (at t0 + 40 days)
    t2_session = t0 + timedelta(days=40)
    sessions.append(
        {
            "id": "sess_02",
            "completed_at": t2_session.isoformat(),
            "confidence_score": 90.0,
            "fluency_score": 85.0,
            "duration_seconds": 1200.0,
        }
    )
    await kv_store.store.create("test_practice_sessions", user_id, sessions)

    # Step 3: Query Team Alpha metrics
    metrics_a = await team_service.get_team_metrics(
        team_id=team_a["id"], start_date=t0, end_date=datetime.now(timezone.utc)
    )
    # Team Alpha has Session 1 (score 80.0, 10 min)
    assert metrics_a["metrics"]["completed_sessions"] == 1
    assert metrics_a["metrics"]["average_confidence_score"] == 80.0
    assert metrics_a["metrics"]["total_practice_time_minutes"] == 10.0

    # Step 4: Query Team Beta metrics
    metrics_b = await team_service.get_team_metrics(
        team_id=team_b["id"], start_date=t0, end_date=datetime.now(timezone.utc)
    )
    # Team Beta has Session 2 (score 90.0, 20 min)
    assert metrics_b["metrics"]["completed_sessions"] == 1
    assert metrics_b["metrics"]["average_confidence_score"] == 90.0
    assert metrics_b["metrics"]["total_practice_time_minutes"] == 20.0


# ── Test 6: Bulk Reassignment CSV Conflicts (E-03) ─────────────────────────────

@pytest.mark.asyncio
async def test_bulk_assign_csv_conflicts_report():
    """E-03: Bulk CSV import flags unmatched team or user rows in an Unresolved Assignments report."""
    target_team = await team_service.create_team(TeamCreateSchema(name="Finance"))

    # Seed known user email
    user_id = "user_valid_csv"
    await kv_store.store.create("user_email_store", "valid@company.com", user_id)

    payload = BulkAssignCSVRequest(
        rows=[
            # Valid row
            BulkAssignCSVRow(user_email="valid@company.com", team_name="Finance"),
            # Conflict row 1: Invalid team name (renamed/deleted)
            BulkAssignCSVRow(user_email="valid@company.com", team_name="Deleted Team"),
            # Conflict row 2: Non-existent employee email
            BulkAssignCSVRow(user_email="missing@company.com", team_name="Finance"),
        ]
    )

    res = await team_service.bulk_assign_csv(payload)

    assert res["total_rows"] == 3
    assert res["assigned_count"] == 1
    assert len(res["unresolved_assignments"]) == 2

    unresolved = res["unresolved_assignments"]
    assert unresolved[0]["email"] == "valid@company.com"
    assert "Deleted Team" in unresolved[0]["reason"]

    assert unresolved[1]["email"] == "missing@company.com"
    assert "missing@company.com" in unresolved[1]["reason"]
