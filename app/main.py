"""
FastAPI app for the Scrum Master Agent.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api.scrum_master import router as scrum_master_router

logger = logging.getLogger("scrum_master_agent")

app = FastAPI(title="Scrum Master Agent", version="0.7.0-day7")

app.include_router(scrum_master_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Last-resort catch-all: anything not already turned into an
    HTTPException by a route (IngestionError -> 422, AgentExecutionError
    -> 502, SQLAlchemyError -> 500) lands here instead of leaking a raw
    stack trace to the caller.
    """
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health")
def health():
    return {"status": "ok"}
