"""
Prompt template for the real LLM call. Defines how ProjectData is
presented to the model and the exact JSON shape it must answer in, so
swapping the deterministic mock detector (detection.py) for a real
model call later doesn't change anything downstream — the mock was
built to return the same shape this prompt asks the LLM for.
"""

from ...context_builder import SYSTEM_PROMPT, build_context_block, build_messages  # noqa: F401
