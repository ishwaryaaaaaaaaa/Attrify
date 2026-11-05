"""AttriFy config. Override via environment variables.

The paper used gemini-3.5-flash (restate, temp 0) and gemini-3.5-flash-lite
(10 readings, temp 0.9). Here any OpenAI-compatible endpoint works; keep the
roles: a stronger model for restatement, a cheaper one for sampling readings.
"""
import os

# OpenAI-compatible endpoint. OPENAI_API_KEY is read by the openai SDK.
BASE_URL = os.environ.get("ATTRIFY_BASE_URL")  # None = default OpenAI
RESTATE_MODEL = os.environ.get("ATTRIFY_RESTATE_MODEL", "gpt-4o-mini")
INTERPRET_MODEL = os.environ.get("ATTRIFY_INTERPRET_MODEL", "gpt-4o-mini")

RESTATE_TEMP = 0.0
INTERPRET_TEMP = 0.9
N_READINGS = 10
N_RUNS = 3            # average softness over this many runs (paper: 3)
JSON_RETRIES = 3

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Decision policy (paper Table 2)
HIGH_SOFT = 65   # s >= 65: clarify, no function generation
LOW_SOFT = 30    # s <= 30: generate, then suggestion / new topic

DOMAIN = "essays"  # static domain word used in the prompts

# Phase 2: Question Agent (paper: gemini-3.5-flash). Temperature not published.
QUESTION_MODEL = os.environ.get("ATTRIFY_QUESTION_MODEL", "gpt-4o-mini")
QUESTION_TEMP = 0.7

# Phase 7: baseline chat model (paper does not state it; default = same as the question agent)
BASELINE_MODEL = os.environ.get("ATTRIFY_BASELINE_MODEL", QUESTION_MODEL)
BASELINE_TEMP = 0.7

# Phase 3: Function Agent (paper uses a CodeAct service; this is a plain retry loop)
FUNCTION_MODEL = os.environ.get("ATTRIFY_FUNCTION_MODEL", "gpt-4o-mini")
FUNCTION_TEMP = 0.2
