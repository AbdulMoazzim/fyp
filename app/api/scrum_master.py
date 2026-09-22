"""
Scrum Master Agent API routes.

Day 6/7: added result retrieval (GET routes), an auth stub for
inter-agent calls, and hardened error handling around persistence and
agent execution so a bad payload or a DB hiccup returns a clean JSON
error instead of a stack trace.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.exc import SQLAlchemyError

from ..agents.scrum_master.agent import AgentExecutionError
from ..agents.scrum_master.agent import run as agent_run
from ..context_builder import build_context_block
from ..core.security import verify_api_key
from ..db.models import AgentResultORM
from ..db.session import SessionLocal
from ..ingestion import IngestionError, ingest_project_context
from ..schemas import AgentResultRecord, AnalyzeResponse, ResultsPage

router = APIRouter(dependencies=[Depends(verify_api_key)])


def _orm_to_record(row: AgentResultORM) -> AgentResultRecord:
    return AgentResultRecord(
        id=row.id,
        agent=row.agent,
        project_id=row.project_id,
        recommendation_type=row.recommendation_type,
        summary=row.summary,
        reasoning=row.reasoning,
        evidence=row.evidence,
        confidence=row.confidence,
        affected_items=row.affected_items or [],
        status=row.status,
        created_at=row.created_at,
    )


@router.post("/scrum-master/ingest")
def ingest(raw: dict, project_id: Optional[str] = Query(default=None)):
    """Validate and normalize one project's data out of the raw payload."""
    try:
        pid, data = ingest_project_context(raw, project_id)
    except IngestionError as exc:
        raise HTTPException(status_code=422, detail=exc.details or str(exc)) from exc
    return {"project_id": pid, **data.model_dump()}


@router.post("/scrum-master/context-preview", response_class=PlainTextResponse)
def context_preview(raw: dict, project_id: Optional[str] = Query(default=None)):
    """Preview the exact text block that would be sent to the LLM."""
    try:
        pid, data = ingest_project_context(raw, project_id)
    except IngestionError as exc:
        raise HTTPException(status_code=422, detail=exc.details or str(exc)) from exc
    return build_context_block(pid, data)


@router.post("/scrum-master/analyze", response_model=AnalyzeResponse)
def analyze(raw: dict, project_id: Optional[str] = Query(default=None)):
    """
    Validate the ProjectContext, run blocker/risk detection, persist
    every finding to agent_results, and return the results.
    """
    try:
        pid, data = ingest_project_context(raw, project_id)
    except IngestionError as exc:
        raise HTTPException(status_code=422, detail=exc.details or str(exc)) from exc

    try:
        results = agent_run(pid, data)
    except AgentExecutionError as exc:
        # Stands in for LLM failure/timeout handling once detection.py is
        # swapped for a real model call — same shape either way.
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    db = SessionLocal()
    try:
        for r in results:
            db.add(AgentResultORM(
                agent=r.agent,
                project_id=pid,
                recommendation_type=r.recommendation_type.value,
                summary=r.summary,
                reasoning=r.reasoning,
                evidence=[e.model_dump() for e in r.evidence],
                confidence=r.confidence,
                affected_items=r.affected_items,
                status=r.status.value,
            ))
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to persist agent results; nothing was saved for this run.",
        ) from exc
    finally:
        db.close()

    return AnalyzeResponse(project_id=pid, count=len(results), results=results)


@router.get("/scrum-master/results", response_model=ResultsPage)
def list_results(
    project_id: Optional[str] = Query(default=None),
    recommendation_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """
    Retrieve previously persisted results, newest first. This is the
    "retrievable via API" half of the Day 6 full run-through: API
    request -> persisted result -> retrievable via API.
    """
    db = SessionLocal()
    try:
        q = db.query(AgentResultORM)
        if project_id:
            q = q.filter(AgentResultORM.project_id == project_id)
        if recommendation_type:
            q = q.filter(AgentResultORM.recommendation_type == recommendation_type)
        if status:
            q = q.filter(AgentResultORM.status == status)
        total = q.count()
        rows = (
            q.order_by(AgentResultORM.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Failed to read agent_results.") from exc
    finally:
        db.close()

    return ResultsPage(count=total, results=[_orm_to_record(r) for r in rows])


@router.get("/scrum-master/results/{result_id}", response_model=AgentResultRecord)
def get_result(result_id: str):
    """Retrieve a single persisted result by id."""
    db = SessionLocal()
    try:
        row = db.query(AgentResultORM).filter(AgentResultORM.id == result_id).first()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Failed to read agent_results.") from exc
    finally:
        db.close()

    if row is None:
        raise HTTPException(status_code=404, detail=f"No result with id '{result_id}'")
    return _orm_to_record(row)
