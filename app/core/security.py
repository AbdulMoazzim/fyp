"""
Auth stub for inter-agent calls (Day 6 integration plumbing).

Real auth (service accounts / JWTs between AGILIRO agents) hasn't been
decided by the team yet, so this is deliberately minimal: if
AGENT_API_KEY is unset (the default for local/dev), every request is
allowed through unchanged — nothing breaks for local work or the
existing smoke tests. Once the team picks a real scheme, only this
file and the env var need to change; routes already depend on
`verify_api_key` and won't need touching again.

Usage from another agent (PO Agent / Knowledge Agent) once a key is
set:
    curl -H "X-API-Key: <key>" ...
"""

from fastapi import Header, HTTPException

from .config import AGENT_API_KEY


def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not AGENT_API_KEY:
        # No key configured -> auth disabled (local/dev default).
        return
    if x_api_key != AGENT_API_KEY:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")
