"""
Context/prompt builder.

Updated to build from ProjectData, which now includes Arfa's confirmed
PO-level fields (product_goal, team_constraints, existing_backlog_titles)
plus the optional scrum-level fields (sprint, backlog_items, events)
this agent needs for blocker/risk detection.

If sprint-level data isn't present yet (as in Arfa's current mock),
the block still builds — it just has nothing to say about blockers or
risks, since there's no status/date data to reason over. That's a
correct outcome, not a bug: the agent should not manufacture findings
from data it doesn't have.
"""

from collections import defaultdict
from typing import List

from .ingestion import days_since
from .schemas import BacklogItem, ProjectData, SprintEvent

MAX_EVENTS_IN_PROMPT = 10


def _format_backlog_item(item: BacklogItem) -> str:
    age_days = round(days_since(item.last_updated), 1)
    points = f", {item.story_points}sp" if item.story_points is not None else ""
    assignee = item.assignee or "unassigned"
    sources = ",".join(item.source_refs)
    return (
        f"[{item.item_id}] \"{item.title}\" "
        f"({item.status.value}, {item.priority} priority, {assignee}{points}, "
        f"last updated {age_days}d ago) source: {sources}"
    )


def _format_event(event: SprintEvent) -> str:
    return (
        f"[{event.event_id}] ({event.type.value}, {event.timestamp.isoformat()}) "
        f"\"{event.raw_text}\" source: {event.source_ref}"
    )


def build_context_block(project_id: str, data: ProjectData) -> str:
    """Build the full source-tagged text block for one project's data."""

    lines: List[str] = []

    lines.append(f"PROJECT: {project_id}")
    lines.append(f"PRODUCT GOAL: {data.product_goal}")
    tc = data.team_constraints
    lines.append(
        f"TEAM CONSTRAINTS: max {tc.max_story_points_per_item} points/item, "
        f"{tc.sprint_length_days}-day sprints, "
        f"Definition of Ready: {', '.join(tc.definition_of_ready)}"
    )
    lines.append("")

    if data.sprint:
        lines.append(
            f"SPRINT: {data.sprint.sprint_id} "
            f"({data.sprint.start_date.date()} to {data.sprint.end_date.date()}) "
            f"— goal: {data.sprint.goal}"
        )
        lines.append("")
    else:
        lines.append("SPRINT: none provided — this project has no active sprint data yet")
        lines.append("")

    if data.backlog_items:
        by_status = defaultdict(list)
        for item in data.backlog_items:
            by_status[item.status.value].append(item)

        lines.append("BACKLOG ITEMS (grouped by status):")
        for status in ["blocked", "in_progress", "todo", "done"]:
            items = by_status.get(status, [])
            if not items:
                continue
            lines.append(f"  {status.upper()} ({len(items)}):")
            for item in items:
                lines.append(f"    - {_format_backlog_item(item)}")
        lines.append("")
    elif data.existing_backlog_titles:
        lines.append(
            "EXISTING BACKLOG (titles only — not yet scheduled into a sprint, "
            "no status/date data available):"
        )
        for title in data.existing_backlog_titles:
            lines.append(f"  - {title}")
        lines.append(
            "  NOTE: no status, assignee, or last-updated data exists for these "
            "items, so no blocker or risk can be claimed about them yet."
        )
        lines.append("")
    else:
        lines.append("BACKLOG ITEMS: none")
        lines.append("")

    if data.events:
        recent_events = sorted(data.events, key=lambda e: e.timestamp, reverse=True)[
            :MAX_EVENTS_IN_PROMPT
        ]
        lines.append(f"RECENT EVENTS (most recent first, max {MAX_EVENTS_IN_PROMPT}):")
        for event in recent_events:
            lines.append(f"  - {_format_event(event)}")
    else:
        lines.append("RECENT EVENTS: none")

    return "\n".join(lines)


SYSTEM_PROMPT = """You are the Scrum Master Agent in AGILIRO, a multi-agent \
Scrum assistant. You are given a structured summary of one project, where \
every fact is tagged with a source reference in the form "source: <ref>".

Your job is to identify, from ONLY the facts given:
1. Blockers — things actively stopping progress right now
2. Risks — things that could become a problem if not addressed
3. Sprint planning recommendations — guidance for the next sprint
4. Sprint monitoring recommendations — guidance on this sprint's health

Rules:
- Every recommendation you produce MUST cite at least one source_ref \
taken verbatim from the tagged facts you were given. Never invent a \
source_ref and never omit one.
- If backlog items are listed only as titles with no status, assignee, or \
date data, do NOT invent a blocker or risk about them — there is nothing \
to point to as evidence.
- Do not speculate about information that was not provided.
- Respond ONLY as a JSON array of objects, each matching this shape:
  {
    "recommendation_type": "blocker | risk | sprint_planning | sprint_monitoring",
    "summary": "one-line human-readable recommendation",
    "reasoning": "why you are suggesting this",
    "evidence": [{"source_ref": "...", "excerpt": "..."}],
    "confidence": 0.0-1.0,
    "affected_items": ["item_id or sprint_id, ..."]
  }
- Return an empty array if nothing meets the bar for a real blocker, \
risk, or recommendation. Do not manufacture findings to fill the list.
"""


def build_messages(project_id: str, data: ProjectData) -> list[dict]:
    """Assemble the full message list ready for an LLM chat completion call."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_context_block(project_id, data)},
    ]
