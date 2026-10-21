"""
observability.py - run_log.jsonl: one line per model call.

Every call to the model (including a retry, and including a call that fails)
writes exactly one JSON line with these nine keys:

    timestamp, run_id, model, status, prompt_tokens, completion_tokens,
    latency_ms, cost_usd, tokens_estimated

plus the extra key "attempt". Never logged: the API key, the user's file, or
full prompts and replies.

All the runs of one call to pipeline.run() share one run_id.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

OUTCOMES = ("ok", "invalid_output", "refused", "error")

# USD per 1,000,000 tokens: (input, output).
# Source: Google AI Studio pricing page for Gemini 2.5 Flash, as reported on
# third-party price trackers in mid-2026. Verify at ai.google.dev/pricing.
# On the free tier you actually pay $0; cost_usd is the LIST-PRICE equivalent.
PRICES = {
    "gpt-oss-120b": (0.15, 0.60),
}

_state = {"run_id": None}


def log_path() -> Path:
    return Path(os.getenv("RUN_LOG_PATH", "run_log.jsonl"))


def new_run_id() -> str:
    """Start a new run. Call once at the top of pipeline.run()."""
    _state["run_id"] = os.getenv("GAP_RUN_ID") or uuid.uuid4().hex[:12]
    return _state["run_id"]


def current_run_id() -> str:
    return _state["run_id"] or new_run_id()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def estimate_tokens(text: str) -> int:
    """Rough estimate (4 characters per token) for when the provider gives none."""
    return max(1, len(text or "") // 4)


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    key = (model or "").split("/")[-1]            # "models/gemini-2.5-flash" -> name
    price = PRICES.get(key)
    if price is None:                              # stubs and unknown models: no price
        return 0.0
    return round((prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000, 6)


class Timer:
    """with Timer() as t: ...; t.ms"""

    def __enter__(self):
        self._t0 = time.perf_counter()
        self.ms = 0
        return self

    def __exit__(self, *exc):
        self.ms = int((time.perf_counter() - self._t0) * 1000)
        return False


def log_call(model: str, status: str, prompt_tokens: int, completion_tokens: int,
             latency_ms: int, tokens_estimated: bool, attempt: int = 1) -> dict:
    """Append one line to run_log.jsonl and return it."""
    if status not in OUTCOMES:
        raise ValueError(f"status must be one of {OUTCOMES}, not {status!r}")
    line = {
        "timestamp": now_iso(),
        "run_id": current_run_id(),
        "model": model,
        "status": status,
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "latency_ms": int(latency_ms),
        "cost_usd": cost_usd(model, prompt_tokens, completion_tokens),
        "tokens_estimated": bool(tokens_estimated),
        "attempt": attempt,
    }
    with open(log_path(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
    return line
