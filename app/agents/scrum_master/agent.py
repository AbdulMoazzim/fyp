"""
Wraps detect_blockers_and_risks as a LangGraph node inside the agent's
state graph, so calling it directly (run()) and calling it through the
graph (run_via_graph()) give identical output — this is what lets
sprint-planning/monitoring logic be composed as additional nodes later
without touching this one.
"""

from typing import List, TypedDict

from langgraph.graph import END, StateGraph

from ...schemas import AgentResult, ProjectData
from .detection import detect_blockers_and_risks


class AgentExecutionError(Exception):
    """
    Raised when the agent's node fails to produce results.

    Today `detect_blockers_and_risks` is a deterministic function, so
    this mostly guards against unexpected data-shape bugs. It's named
    and placed here so that when the real LLM call replaces
    `detect_blockers_and_risks`, timeouts/API failures/malformed model
    output all raise this same type and the API layer's error handling
    (app/api/scrum_master.py) doesn't need to change.
    """


class AgentState(TypedDict):
    project_id: str
    data: ProjectData
    results: List[AgentResult]


def _detect_node(state: AgentState) -> AgentState:
    results = detect_blockers_and_risks(state["project_id"], state["data"])
    return {**state, "results": results}


def _build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("detect", _detect_node)
    graph.set_entry_point("detect")
    graph.add_edge("detect", END)
    return graph.compile()


_compiled_graph = _build_graph()


def run(project_id: str, data: ProjectData) -> List[AgentResult]:
    """Direct function call path — used by the API route today."""
    try:
        return detect_blockers_and_risks(project_id, data)
    except Exception as exc:  # noqa: BLE001 — deliberately broad, see AgentExecutionError
        raise AgentExecutionError(
            f"scrum_master agent failed for project '{project_id}': {exc}"
        ) from exc


def run_via_graph(project_id: str, data: ProjectData) -> List[AgentResult]:
    """Same logic via the LangGraph state graph — proves the two paths agree."""
    final_state = _compiled_graph.invoke(
        {"project_id": project_id, "data": data, "results": []}
    )
    return final_state["results"]
