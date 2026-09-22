"""
Blocker and risk detection.

This is a deterministic, rule-based detector — it stands in for the
real LLM call so the agent is testable end to end without needing any
API credentials. It reads the exact same ProjectData a real LLM call
would see (via the source-tagged context in prompts.py) and returns
the exact same AgentResult shape the LLM is instructed to return, so
swapping this for a real model call later changes nothing downstream.

Rules implemented:
- A backlog item with status=blocked -> a blocker finding
- An unassigned high/medium priority item that isn't done -> a risk
- A backlog item whose story_points exceeds the team's
  max_story_points_per_item constraint -> a sprint_planning finding
  (violates Definition of Ready, should be split)
- An event whose text mentions being blocked/stuck/delayed -> a
  blocker finding, evidenced by the event itself
- An event whose text reports a velocity drop -> a sprint_monitoring
  finding
- Backlog titles that exist in existing_backlog_titles but have no
  matching scheduled backlog item -> a sprint_planning suggestion to
  schedule them
- If the sprint is more than half elapsed and less than a third of
  items are done -> a sprint_monitoring pace warning
"""

import re
from datetime import datetime, timezone
from typing import List

from ...ingestion import days_since
from ...schemas import AgentResult, BacklogStatus, Evidence, ProjectData

BLOCKED_KEYWORDS = re.compile(r"\b(blocked|stuck|delay|delayed|waiting on)\b", re.IGNORECASE)
VELOCITY_DROP_KEYWORDS = re.compile(r"\bvelocity\b.*\b(down|dip|decrease|dropped)\b", re.IGNORECASE)


def detect_blockers_and_risks(project_id: str, data: ProjectData) -> List[AgentResult]:
    results: List[AgentResult] = []

    # --- backlog item rules ---
    for item in data.backlog_items:
        source = item.source_refs[0] if item.source_refs else "self"

        if item.status == BacklogStatus.blocked:
            age = round(days_since(item.last_updated), 1)
            results.append(AgentResult(
                recommendation_type="blocker",
                summary=f'"{item.title}" ({item.item_id}) is blocked, no movement in {age} days',
                reasoning=(
                    f"Item {item.item_id} has status=blocked and its last_updated "
                    f"timestamp is {age} days old, indicating it is actively stuck."
                ),
                evidence=[Evidence(
                    source_ref=source,
                    excerpt=f'{item.title} — status: blocked, last_updated {item.last_updated.isoformat()}',
                )],
                confidence=0.9,
                affected_items=[item.item_id],
            ))

        if (
            item.assignee is None
            and item.status != BacklogStatus.done
            and item.priority in ("high", "medium")
        ):
            results.append(AgentResult(
                recommendation_type="risk",
                summary=f'"{item.title}" ({item.item_id}) is {item.priority} priority with no assignee',
                reasoning=(
                    f"Item {item.item_id} is {item.priority} priority and still "
                    f"{item.status.value}, but has no assignee — risk of it being "
                    f"missed or picked up too late in the sprint."
                ),
                evidence=[Evidence(
                    source_ref=source,
                    excerpt=f'{item.title} — priority: {item.priority}, assignee: none',
                )],
                confidence=0.7,
                affected_items=[item.item_id],
            ))

        if (
            item.story_points is not None
            and item.story_points > data.team_constraints.max_story_points_per_item
        ):
            results.append(AgentResult(
                recommendation_type="sprint_planning",
                summary=f'"{item.title}" ({item.item_id}) exceeds the {data.team_constraints.max_story_points_per_item}-point item limit',
                reasoning=(
                    f"Item {item.item_id} is estimated at {item.story_points} points, "
                    f"above the team's max_story_points_per_item constraint of "
                    f"{data.team_constraints.max_story_points_per_item}. Consider "
                    f"splitting it before it's pulled into a sprint."
                ),
                evidence=[Evidence(
                    source_ref=source,
                    excerpt=f'{item.title} — story_points: {item.story_points}',
                )],
                confidence=0.85,
                affected_items=[item.item_id],
            ))

    # --- event rules ---
    for event in data.events:
        if BLOCKED_KEYWORDS.search(event.raw_text):
            results.append(AgentResult(
                recommendation_type="blocker",
                summary="Recent event reports a blocker in progress",
                reasoning=(
                    f"Event {event.event_id} ({event.type.value}) explicitly "
                    f"describes work being blocked, stuck, or delayed."
                ),
                evidence=[Evidence(source_ref=event.source_ref, excerpt=event.raw_text)],
                confidence=0.75,
                affected_items=[],
            ))

        if VELOCITY_DROP_KEYWORDS.search(event.raw_text):
            results.append(AgentResult(
                recommendation_type="sprint_monitoring",
                summary="Team velocity is trending down",
                reasoning=(
                    f"Event {event.event_id} reports a velocity decrease versus "
                    f"prior sprints — worth flagging before committing to the same "
                    f"scope next sprint."
                ),
                evidence=[Evidence(source_ref=event.source_ref, excerpt=event.raw_text)],
                confidence=0.7,
                affected_items=[],
            ))

    # --- unscheduled backlog titles ---
    scheduled_titles = {item.title for item in data.backlog_items}
    for idx, title in enumerate(data.existing_backlog_titles):
        if title not in scheduled_titles:
            results.append(AgentResult(
                recommendation_type="sprint_planning",
                summary=f'"{title}" exists in the backlog but is not scheduled into a sprint',
                reasoning=(
                    "This title appears in existing_backlog_titles but has no "
                    "matching scheduled backlog item with status/assignee data — "
                    "worth reviewing for the next sprint."
                ),
                evidence=[Evidence(
                    source_ref=f"existing_backlog_titles[{idx}]",
                    excerpt=title,
                )],
                confidence=0.5,
                affected_items=[],
            ))

    # --- sprint pace check ---
    if data.sprint and data.backlog_items:
        now = datetime.now(timezone.utc)
        start, end = data.sprint.start_date, data.sprint.end_date
        total_span = (end - start).total_seconds()
        if total_span > 0:
            elapsed_fraction = max(0.0, min(1.0, (now - start).total_seconds() / total_span))
            done_fraction = sum(
                1 for i in data.backlog_items if i.status == BacklogStatus.done
            ) / len(data.backlog_items)

            if elapsed_fraction > 0.5 and done_fraction < (1 / 3):
                results.append(AgentResult(
                    recommendation_type="sprint_monitoring",
                    summary=(
                        f"Sprint {data.sprint.sprint_id} is "
                        f"{round(elapsed_fraction * 100)}% through its time but only "
                        f"{round(done_fraction * 100)}% of items are done"
                    ),
                    reasoning=(
                        "Time elapsed is outpacing completion rate — the sprint "
                        "may not finish its committed scope at the current pace."
                    ),
                    evidence=[Evidence(
                        source_ref="self",
                        excerpt=(
                            f"sprint {data.sprint.sprint_id}: {start.date()} to "
                            f"{end.date()}, {len(data.backlog_items)} items"
                        ),
                    )],
                    confidence=0.6,
                    affected_items=[data.sprint.sprint_id],
                ))

    return results
