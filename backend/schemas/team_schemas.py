"""
Pydantic Schemas for ENT-US-03: Department & Team Hierarchy Management.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class TeamCreateSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=150, description="Department/Team name")
    description: Optional[str] = Field(None, max_length=500, description="Team description")
    parent_id: Optional[str] = Field(None, description="Parent team ID for nested hierarchy")
    manager_id: Optional[str] = Field(None, description="Sub-manager user ID assigned to the team")


class TeamUpdateSchema(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=500)
    parent_id: Optional[str] = Field(None)
    manager_id: Optional[str] = Field(None)


class AssignMemberSchema(BaseModel):
    user_id: str = Field(..., description="ID of employee user to assign")
    team_id: str = Field(..., description="Target team ID")
    secondary_tags: List[str] = Field(default_factory=list, description="Secondary tags for cross-functional reporting")


class BulkAssignCSVRow(BaseModel):
    user_email: str = Field(..., description="Employee email address")
    team_name: str = Field(..., description="Target department or team name")
    secondary_tags: List[str] = Field(default_factory=list, description="Optional secondary tags")


class BulkAssignCSVRequest(BaseModel):
    rows: List[BulkAssignCSVRow]
