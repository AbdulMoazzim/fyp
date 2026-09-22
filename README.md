# Scrum Master Agent — AGILIRO

One of three agents in AGILIRO (with Product Owner Agent & Knowledge Agent). Takes project/sprint/backlog data and produces evidence-linked recommendations for blockers, risks, sprint planning, and sprint monitoring. Every recommendation cites its source and requires human approval before affecting any artifact.

## Status (Day 7 — runnable prototype)

Everything below is real, tested code — not just described:

- ✅ ProjectContext confirmed against Arfa's (PO Agent) actual schema — validated as-is, with optional sprint/backlog-status fields layered on top
- ✅ `agent_results` table — real Alembic migration, applied and verified (SQLite for local dev, Postgres-ready via `DATABASE_URL`)
- ✅ Deterministic blocker/risk/sprint-planning/sprint-monitoring detection — rule-based, evidence-cited, no LLM credentials required
- ✅ Detection wrapped as a LangGraph node — direct call and graph call verified to produce identical output
- ✅ `POST /scrum-master/analyze` — runs detection, persists every result, returns them in a versioned envelope (`run_id`, `count`, `results`)
- ✅ `GET /scrum-master/results` and `GET /scrum-master/results/{id}` — persisted results are retrievable via API, filterable by `project_id` / `recommendation_type` / `status`, paginated
- ✅ Full run-through verified: API request with mock ProjectContext → persisted result → retrievable via API (`smoke_test.py` §4)
- ✅ Auth stub (`X-API-Key` header, `AGENT_API_KEY` env var) so the PO Agent / Knowledge Agent have a real header to call with once the team picks a real inter-agent auth scheme
- ✅ Error handling hardened: malformed/non-dict payloads, missing required fields, unknown `project_id`, unknown result `id`, and DB write failures all return a clean HTTP status + JSON detail (422/404/500/502) instead of a stack trace — covered by `smoke_test.py` §5
- ✅ `demo.py` — runs a troubled and a healthy sample project through the full pipeline and prints each finding with its evidence
- ⏳ Real LLM call (swap-in for the deterministic detector) — not yet started; `agent.py`'s `AgentExecutionError` and the `/analyze` route's 502 handling are already wired for it (see "What's stubbed vs real" below)

**Known gap (unchanged from Day 5):** Arfa's ProjectContext has no sprint/backlog-status/event data — that's layered on as optional fields for now. Needs a team decision: added upstream, or merged from a second source.

## Setup

```bash
pip install -r requirements.txt
alembic upgrade head           # creates agent_results (SQLite by default)
python smoke_test.py           # full end-to-end check: detection, API, persistence, GET retrieval, error handling
python demo.py                 # human-readable walkthrough: sample input -> findings -> persisted -> retrieved
uvicorn app.main:app --reload
```

## Try it

```bash
# Run analysis and persist
curl -X POST "http://127.0.0.1:8000/scrum-master/analyze?project_id=proj-agiliro-002" \
  -H "Content-Type: application/json" \
  -d @data/sample_troubled.json

# Retrieve what was just persisted
curl "http://127.0.0.1:8000/scrum-master/results?project_id=proj-agiliro-002"

# Retrieve one result by id
curl "http://127.0.0.1:8000/scrum-master/results/<id-from-above>"
```

`/analyze` returns real findings (blockers, risks, sprint pace warnings), each with cited evidence, wrapped in `{agent, project_id, run_id, count, results}`. If `AGENT_API_KEY` is set in the environment, all `/scrum-master/*` routes require a matching `X-API-Key` header (401 otherwise); unset (the default), auth is a no-op.

## What's stubbed vs. real

| Piece | Status |
|---|---|
| ProjectContext validation, ingestion, context/prompt builder | Real |
| Blocker/risk/sprint-planning/sprint-monitoring logic | Real, but **rule-based**, not an LLM — deliberately built to return the exact `AgentResult` shape the LLM prompt (`context_builder.SYSTEM_PROMPT`) asks a real model for, so swapping it later shouldn't change the API or DB layer |
| Persistence (`agent_results` table, Alembic migration) | Real |
| Result retrieval API (list + get-by-id, filters, pagination) | Real |
| Error handling (bad payloads, unknown ids, DB failures) | Real |
| Auth on `/scrum-master/*` | **Stub** — single shared API key via env var, off by default. Not a real per-agent identity/JWT scheme; that's a team decision still pending |
| LLM call itself (Groq) | **Not implemented.** `LLM_PROVIDER`/`GROQ_API_KEY` env vars and the prompt exist; no network call is made anywhere in this repo yet |
| Integration with PO Agent / Knowledge Agent | **Contract-level only.** Request/response shapes are stable and documented here; no live call between agents has been wired up |

## What's needed from the final dataset later

- Real sprint / backlog-item status / event data in the shape `schemas.Sprint` / `BacklogItem` / `SprintEvent` expect (see "Known gap" above) — Arfa's current PO Agent payload only has `product_goal`, `team_constraints`, `existing_backlog_titles`
- A decision on whether that data comes from the PO Agent's payload directly or a second feed this agent merges in
- A real auth scheme for agent-to-agent calls, to replace the `AGENT_API_KEY` stub
- Confirmation from the team that the `AgentResult` shape (`recommendation_type`, `summary`, `reasoning`, `evidence`, `confidence`, `affected_items`, `status`) is final, since the Knowledge Agent and any UI will consume it as-is

## Structure

```
app/
  main.py                         # FastAPI app + global exception handler
  api/scrum_master.py             # /ingest, /context-preview, /analyze, /results, /results/{id}
  core/config.py                  # env vars (DATABASE_URL, LLM_PROVIDER, AGENT_API_KEY)
  core/security.py                # X-API-Key auth stub
  db/models.py, session.py        # SQLAlchemy: AgentResultORM
  schemas.py                      # ProjectData + AgentResult + API envelopes (AnalyzeResponse, ResultsPage)
  ingestion.py, context_builder.py
  agents/scrum_master/
    schemas.py, prompts.py        # re-export canonical schemas/prompt
    detection.py                  # rule-based blocker/risk/planning/monitoring logic
    agent.py                      # LangGraph node wrapping detection.py + AgentExecutionError
alembic/                          # migrations
data/
  project_context_from_arfa.json  # her payload, unmodified
  sample_healthy.json, sample_troubled.json
smoke_test.py                     # full pipeline + error-handling test
demo.py                           # human-readable demo walkthrough
```

## Stack

Python · FastAPI · PostgreSQL (SQLAlchemy + Alembic) · LangGraph · Groq (planned)

## Day 6/7 split

- **Moazzam:** API layer (`/analyze`), persistence (`agent_results` + Alembic), Day 7 stability/bug fixes in the workflow + API (non-dict payload handling, DB rollback on write failure, global exception handler)
- **Taha:** Integration plumbing (`/results` retrieval routes as the shared contract other agents call, `X-API-Key` auth stub, `AnalyzeResponse`/`ResultsPage` as the consistent request/response shape), end-to-end pipeline testing, `demo.py`, README, evidence-traceability review

## Contributors

Abdul Moazzim · Taha Naqvi · Arfa Tariq (PO Agent — ProjectContext schema)
