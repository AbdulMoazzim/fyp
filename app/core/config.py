"""
Core config — environment-driven settings.

DATABASE_URL defaults to a local SQLite file for dev/testing without a
Postgres server running. In deployment (e.g. Neon Postgres) this is set
via a .env file or real env var; no application code changes needed.
"""

import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./scrum_master.db")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")

# Auth stub for calls from other AGILIRO agents (see core/security.py).
# Unset by default -> auth disabled for local/dev and the smoke tests.
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "")
