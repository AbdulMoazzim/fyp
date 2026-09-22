"""
Day 7 demo script — proves the prototype is runnable end to end.

    sample ProjectContext -> POST /scrum-master/analyze
                           -> Agent Result (blockers, risks, sprint
                              planning/monitoring, each with evidence)
                           -> persisted to agent_results
                           -> GET /scrum-master/results (retrieved back)

No LLM credentials needed — detection.py is a deterministic stand-in
for the real model call (see README "What's stubbed vs real").

Run:
    python demo.py
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

DATA_DIR = Path(__file__).parent / "data"
client = TestClient(app)

ICONS = {
    "blocker": "🔴",
    "risk": "🟠",
    "sprint_planning": "🔵",
    "sprint_monitoring": "🟣",
}


def show_result(r: dict) -> None:
    icon = ICONS.get(r["recommendation_type"], "•")
    print(f"\n{icon} [{r['recommendation_type'].upper()}]  {r['summary']}")
    print(f"   confidence: {r['confidence']}   affected: {r['affected_items'] or '—'}")
    print(f"   reasoning: {r['reasoning']}")
    for e in r["evidence"]:
        print(f"   evidence [{e['source_ref']}]: \"{e['excerpt']}\"")


def run_demo(sample_file: str, project_id: str) -> None:
    raw = json.loads((DATA_DIR / sample_file).read_text())

    print("=" * 78)
    print(f"INPUT: {sample_file}  (project_id={project_id})")
    print("=" * 78)

    r = client.post(
        "/scrum-master/analyze", json=raw, params={"project_id": project_id}
    )
    r.raise_for_status()
    envelope = r.json()

    print(f"\n-> POST /scrum-master/analyze  ::  HTTP {r.status_code}")
    print(f"   run_id: {envelope['run_id']}")
    print(f"   {envelope['count']} finding(s) for {envelope['project_id']}")

    if envelope["count"] == 0:
        print("\n   (no findings — data looks healthy, nothing manufactured)")
    for result in envelope["results"]:
        show_result(result)

    # Prove persistence: pull the same run back out via the read API.
    r = client.get("/scrum-master/results", params={"project_id": project_id})
    r.raise_for_status()
    page = r.json()
    print(
        f"\n-> GET /scrum-master/results?project_id={project_id}  ::  "
        f"HTTP {r.status_code}  ->  {page['count']} row(s) retrieved from the DB"
    )


if __name__ == "__main__":
    run_demo("sample_troubled.json", "proj-agiliro-002")
    print("\n")
    run_demo("sample_healthy.json", "proj-agiliro-001")

    print("\n" + "=" * 78)
    print("Prototype demo complete: API request -> Agent Result -> persisted ->")
    print("retrievable via API, for both a troubled and a healthy project.")
    print("=" * 78)
