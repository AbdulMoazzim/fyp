"""
Context ingestion layer.

Updated for the confirmed ProjectContext shape from Arfa (PO Agent):
the raw payload is a dict keyed by project_id, e.g.
    {"proj-agiliro-001": {...ProjectData fields...}}
rather than a single flat object. ingest_project_context() pulls out
one project's data and validates it.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from pydantic import ValidationError

from .schemas import ProjectData


class IngestionError(Exception):
    """Raised when a ProjectContext payload fails validation or lookup."""

    def __init__(self, message: str, details: Any = None):
        super().__init__(message)
        self.details = details


def ingest_project_context(
    raw: Dict[str, Any], project_id: Optional[str] = None
) -> Tuple[str, ProjectData]:
    """
    Validate and normalize one project's data out of the raw,
    project-id-keyed ProjectContext payload.

    If project_id is omitted and the payload contains exactly one
    project, that project is used. If it contains more than one,
    project_id must be supplied explicitly.
    """
    if not isinstance(raw, dict):
        raise IngestionError(
            "ProjectContext payload must be a JSON object keyed by project_id "
            f"(got {type(raw).__name__})",
            details=None,
        )

    if not raw:
        raise IngestionError("ProjectContext payload is empty", details=None)

    if project_id is None:
        if len(raw) == 1:
            project_id = next(iter(raw))
        else:
            raise IngestionError(
                "Payload contains multiple projects; project_id must be specified",
                details={"available_project_ids": list(raw.keys())},
            )

    if project_id not in raw:
        raise IngestionError(
            f"project_id '{project_id}' not found in payload",
            details={"available_project_ids": list(raw.keys())},
        )

    try:
        data = ProjectData.model_validate(raw[project_id])
    except ValidationError as exc:
        raise IngestionError(
            "ProjectData failed validation", details=exc.errors()
        ) from exc

    return project_id, data


def days_since(dt: datetime, now: datetime | None = None) -> float:
    """Helper used by blocker/risk detection: how many days old is `dt`."""
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 86400
