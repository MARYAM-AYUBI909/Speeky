"""
FastAPI Router for ENT-US-03: Department & Team Hierarchy Management.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, Response

from middlewares.auth_middleware import require_admin, require_auth
from schemas.team_schemas import (
    AssignMemberSchema,
    BulkAssignCSVRequest,
    TeamCreateSchema,
    TeamUpdateSchema,
)
from services.team_service import (
    archive_team,
    assign_member,
    bulk_assign_csv,
    create_team,
    delete_team,
    get_team_metrics,
    list_teams,
    update_team,
)

router = APIRouter()


@router.post("/", summary="Create a department/team (Admin)")
async def create_team_endpoint(
    payload: TeamCreateSchema,
    _admin_id: str = Depends(require_admin),
):
    return await create_team(payload)


@router.get("/", summary="List teams or tree hierarchy")
async def list_teams_endpoint(
    tree: bool = Query(True, description="Return hierarchical tree structure if True"),
    include_archived: bool = Query(False, description="Include archived teams"),
    _user_id: str = Depends(require_auth),
):
    return await list_teams(tree=tree, include_archived=include_archived)


@router.patch("/{team_id}", summary="Update team details (Admin)")
async def update_team_endpoint(
    team_id: str,
    payload: TeamUpdateSchema,
    _admin_id: str = Depends(require_admin),
):
    return await update_team(team_id, payload)


@router.delete("/{team_id}", summary="Delete team (Admin - blocks if non-empty, E-01)")
async def delete_team_endpoint(
    team_id: str,
    _admin_id: str = Depends(require_admin),
):
    return await delete_team(team_id)


@router.post("/{team_id}/archive", summary="Archive team and reassign members (Admin)")
async def archive_team_endpoint(
    team_id: str,
    _admin_id: str = Depends(require_admin),
):
    return await archive_team(team_id)


@router.post("/assign-member", summary="Assign single employee to team (Admin)")
async def assign_member_endpoint(
    payload: AssignMemberSchema,
    _admin_id: str = Depends(require_admin),
):
    return await assign_member(payload)


@router.post("/bulk-assign-csv", summary="Bulk assign employees via CSV with conflict report (Admin - E-03)")
async def bulk_assign_csv_endpoint(
    payload: BulkAssignCSVRequest,
    _admin_id: str = Depends(require_admin),
):
    return await bulk_assign_csv(payload)


@router.get("/{team_id}/metrics", summary="Get aggregated team hierarchy metrics (E-05)")
async def get_team_metrics_endpoint(
    team_id: str,
    _user_id: str = Depends(require_auth),
):
    return await get_team_metrics(team_id=team_id)
