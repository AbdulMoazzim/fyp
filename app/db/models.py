"""
SQLAlchemy model for agent_results.

evidence and affected_items use JSON, upgraded to JSONB automatically
when running against Postgres (the `with_variant` below), while still
working against SQLite for local/dev testing.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from .session import Base


class AgentResultORM(Base):
    __tablename__ = "agent_results"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent = Column(String, default="scrum_master", nullable=False)
    project_id = Column(String, nullable=False, index=True)
    recommendation_type = Column(String, nullable=False)
    summary = Column(String, nullable=False)
    reasoning = Column(String, nullable=False)
    evidence = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    confidence = Column(Float, nullable=False)
    affected_items = Column(JSON().with_variant(JSONB(), "postgresql"), default=list)
    status = Column(String, default="pending_review", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
