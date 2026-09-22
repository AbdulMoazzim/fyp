"""
End-to-end smoke test, no external LLM credentials required.

Covers:
1. Ingestion against Arfa's real payload + two enriched samples
2. Context/prompt builder
3. AgentResult evidence-enforcement guard
4. Blocker/risk detection logic (direct call and via LangGraph node —
   must agree)
5. POST /scrum-master/analyze -> persisted -> GET /scrum-master/results
   (the full Day 6 run-through, plus the single-result GET route)
6. Error handling: malformed payload, unknown project_id, missing
   required field, unknown result id — every failure mode should come
   back as a clean HTTP error, never a raw stack trace
"""

import json
from pathlib import Path

from pydantic import ValidationError

from app.agents.scrum_master.agent import run, run_via_graph
from app.context_builder import build_context_block, build_messages
from app.db.models import AgentResultORM
from app.db.session import Base, SessionLocal, engine
from app.ingestion import ingest_project_context
from app.schemas import AgentResult

DATA_DIR = Path(__file__).parent / "data"

# Make sure tables exist for this run (normally handled by `alembic upgrade head`)
Base.metadata.create_all(engine)

print("=" * 70)
print("1. Ingestion + context builder")
print("=" * 70)
for name in ["project_context_from_arfa.json", "sample_healthy.json", "sample_troubled.json"]:
    raw = json.loads((DATA_DIR / name).read_text())
    project_id, data = ingest_project_context(raw)
    block = build_context_block(project_id, data)
    messages = build_messages(project_id, data)
    assert messages[0]["role"] == "system"
    print(f"{name}: OK — project={project_id}, "
          f"has_sprint={data.sprint is not None}, "
          f"{len(data.backlog_items)} backlog items, {len(data.events)} events")

print("\n" + "=" * 70)
print("2. AgentResult evidence-enforcement guard")
print("=" * 70)
try:
    AgentResult(
        recommendation_type="blocker", summary="x", reasoning="x",
        evidence=[], confidence=0.9, affected_items=[],
    )
    print("FAIL: accepted empty evidence")
except ValidationError:
    print("PASS: empty evidence[] correctly rejected")

print("\n" + "=" * 70)
print("3. Blocker/risk detection — direct call vs LangGraph node")
print("=" * 70)
raw = json.loads((DATA_DIR / "sample_troubled.json").read_text())
pid, data = ingest_project_context(raw)
direct = run(pid, data)
via_graph = run_via_graph(pid, data)
assert [r.summary for r in direct] == [r.summary for r in via_graph]
print(f"PASS: {len(direct)} findings, direct call and LangGraph node agree")
for r in direct:
    assert len(r.evidence) > 0, "every finding must carry evidence"
print("PASS: every finding carries non-empty evidence")

raw_healthy = json.loads((DATA_DIR / "sample_healthy.json").read_text())
pid_h, data_h = ingest_project_context(raw_healthy)
healthy_results = run(pid_h, data_h)
blockers = [r for r in healthy_results if r.recommendation_type.value == "blocker"]
assert len(blockers) == 0, "healthy sample should not produce blockers"
print(f"PASS: healthy sample produced {len(healthy_results)} findings, 0 of them blockers")

print("\n" + "=" * 70)
print("4. POST /analyze -> persisted -> GET /results (full run-through)")
print("=" * 70)
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
r = client.get("/health")
assert r.status_code == 200

r = client.post(
    "/scrum-master/analyze", json=raw, params={"project_id": "proj-agiliro-002"}
)
assert r.status_code == 200, r.text
envelope = r.json()
assert envelope["project_id"] == "proj-agiliro-002"
assert envelope["count"] == len(envelope["results"]) == len(direct)
run_id = envelope["run_id"]
print(f"PASS: /analyze returned {envelope['count']} results, run_id={run_id}")

db = SessionLocal()
try:
    count = db.query(AgentResultORM).filter_by(project_id="proj-agiliro-002").count()
finally:
    db.close()
assert count >= envelope["count"], "results should be persisted to agent_results"
print(f"PASS: {count} rows found in agent_results for proj-agiliro-002")

r = client.get("/scrum-master/results", params={"project_id": "proj-agiliro-002"})
assert r.status_code == 200, r.text
page = r.json()
assert page["count"] >= envelope["count"]
assert len(page["results"]) >= envelope["count"]
print(f"PASS: GET /scrum-master/results retrieved {len(page['results'])} persisted rows")

r = client.get(
    "/scrum-master/results",
    params={"project_id": "proj-agiliro-002", "recommendation_type": "blocker"},
)
assert r.status_code == 200
assert all(row["recommendation_type"] == "blocker" for row in r.json()["results"])
print("PASS: GET /scrum-master/results filters by recommendation_type")

first_id = page["results"][0]["id"]
r = client.get(f"/scrum-master/results/{first_id}")
assert r.status_code == 200, r.text
assert r.json()["id"] == first_id
print(f"PASS: GET /scrum-master/results/{{id}} retrieves a single persisted result")

r = client.get("/scrum-master/results/does-not-exist")
assert r.status_code == 404
print("PASS: GET /scrum-master/results/{id} returns 404 for an unknown id")

print("\n" + "=" * 70)
print("5. Error handling — every bad input comes back as a clean HTTP error")
print("=" * 70)

r = client.post("/scrum-master/analyze", json=["not", "a", "dict"])
assert r.status_code == 422, r.text
print("PASS: non-dict payload -> 422, not a 500")

r = client.post("/scrum-master/analyze", json={})
assert r.status_code == 422
print("PASS: empty payload -> 422")

r = client.post(
    "/scrum-master/analyze", json=raw, params={"project_id": "proj-does-not-exist"}
)
assert r.status_code == 422
print("PASS: unknown project_id -> 422 (lists available_project_ids in detail)")

broken = json.loads(json.dumps(raw))
del broken["proj-agiliro-002"]["team_constraints"]
r = client.post("/scrum-master/analyze", json=broken, params={"project_id": "proj-agiliro-002"})
assert r.status_code == 422
print("PASS: missing required field (team_constraints) -> 422, not a 500")

multi = {**raw, "proj-agiliro-001": raw["proj-agiliro-002"]}
r = client.post("/scrum-master/ingest", json=multi)
assert r.status_code == 422
assert set(r.json()["detail"]["available_project_ids"]) == {"proj-agiliro-001", "proj-agiliro-002"}
print("PASS: multi-project payload with no project_id -> 422 listing available ids")

print("\nAll smoke tests passed.")
