"""
Pydantic models for ProjectContext.

IMPORTANT (Day 4/5 update): Arfa (PO Agent) sent the actual shared
ProjectContext shape, and it is keyed by project_id at the top level,
containing product_goal / team_constraints / existing_backlog_titles.
That shape has NO sprint, backlog item status/assignee/dates, or event
data — which is exactly what blocker/risk detection depends on.

Rather than block on this, we treat her shape as the confirmed
"product-level" section of ProjectContext, and keep our sprint/backlog
item/event fields as an additional "scrum-level" section on the same
project object. This should be raised with Arfa/Taha explicitly: either
the sprint-level fields get added upstream, or the Scrum Master Agent's
input is a merge of two sources (PO Agent's ProjectContext + a separate
sprint/backlog-status feed). For now we model both together so nothing
is blocked.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Arfa's confirmed shape (PO Agent side)
# ---------------------------------------------------------------------------

class TeamConstraints(BaseModel):
    definition_of_ready: List[str]
    max_story_points_per_item: int
    sprint_length_days: int


# ---------------------------------------------------------------------------
# Scrum-level shape (what blocker/risk detection actually needs).
# Optional for now since Arfa's mock doesn't populate it yet.
# ---------------------------------------------------------------------------

class BacklogStatus(str, Enum):
    todo = "todo"
    in_progress = "in_progress"
    blocked = "blocked"
    done = "done"


class EventType(str, Enum):
    meeting_summary = "meeting_summary"
    status_update = "status_update"
    chat_update = "chat_update"
    manual_edit = "manual_edit"


class BacklogItem(BaseModel):
    item_id: str
    title: str
    status: BacklogStatus
    assignee: Optional[str] = None
    priority: str
    story_points: Optional[int] = None
    last_updated: datetime
    source_refs: List[str] = Field(default_factory=list)

    @field_validator("source_refs")
    @classmethod
    def warn_if_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError(
                "source_refs must not be empty — use ['self'] if the item "
                "is evidence for itself (e.g. its own status field)"
            )
        return v


class SprintEvent(BaseModel):
    event_id: str
    type: EventType
    timestamp: datetime
    raw_text: str
    source_ref: str


class Sprint(BaseModel):
    sprint_id: str
    start_date: datetime
    end_date: datetime
    goal: str


# ---------------------------------------------------------------------------
# ProjectData — one project's full context: Arfa's confirmed fields plus
# the optional scrum-level fields this agent needs.
# ---------------------------------------------------------------------------

class ProjectData(BaseModel):
    # confirmed, from Arfa
    product_goal: str
    team_constraints: TeamConstraints
    existing_backlog_titles: List[str] = Field(default_factory=list)

    # not yet in Arfa's mock — optional so her payload validates as-is
    sprint: Optional[Sprint] = None
    backlog_items: List[BacklogItem] = Field(default_factory=list)
    events: List[SprintEvent] = Field(default_factory=list)


# Top-level payload is a dict keyed by project_id, e.g.
# {"proj-agiliro-001": {...ProjectData...}}
ProjectContextRoot = Dict[str, ProjectData]


# ---------------------------------------------------------------------------
# AgentResult — unchanged, still a working assumption pending the team's
# confirmed spec.
# ---------------------------------------------------------------------------

class RecommendationType(str, Enum):
    blocker = "blocker"
    risk = "risk"
    sprint_planning = "sprint_planning"
    sprint_monitoring = "sprint_monitoring"


class ReviewStatus(str, Enum):
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"


class Evidence(BaseModel):
    source_ref: str
    excerpt: str


class AgentResult(BaseModel):
    agent: str = "scrum_master"
    recommendation_type: RecommendationType
    summary: str
    reasoning: str
    evidence: List[Evidence]
    confidence: float = Field(ge=0.0, le=1.0)
    affected_items: List[str] = Field(default_factory=list)
    status: ReviewStatus = ReviewStatus.pending_review

    @field_validator("evidence")
    @classmethod
    def evidence_must_not_be_empty(cls, v: List[Evidence]) -> List[Evidence]:
        if not v:
            raise ValueError(
                "AgentResult.evidence must not be empty — every "
                "recommendation must cite a source_ref"
            )
        return v


# ---------------------------------------------------------------------------
# API envelope shapes (Day 6/7) — the shared request/response contract other
# agents (PO Agent, Knowledge Agent) integrate against. Wrapping the bare
# list of AgentResult in a small envelope gives callers a run_id to log/
# correlate against, and a place to add pagination metadata later without
# another breaking shape change.
# ---------------------------------------------------------------------------

class AnalyzeResponse(BaseModel):
    agent: str = "scrum_master"
    project_id: str
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    count: int
    results: List[AgentResult]


class AgentResultRecord(AgentResult):
    """An AgentResult as persisted and returned from the results store."""
    id: str
    project_id: str
    created_at: datetime


class ResultsPage(BaseModel):
    count: int
    results: List[AgentResultRecord]
