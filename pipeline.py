"""
pipeline.py - the one pipeline. main.py and app.py both call run().

    CSV --load_timeline--> events --guard_rows--> clean rows --LLM--> reply
        --Pydantic--> Analysis --check_output--> Result

Only the middle step (the model call) is not deterministic. Everything before
it is plain Python, and everything after it checks what the model said.

Statuses, as in the labs: ok | invalid_output | refused | error.
Input rejected before any model call raises InputRejected (exit 2 in main.py).
"""

import json
import re
import sys
import time
from dataclasses import dataclass, field

from pydantic import ValidationError

from client import get_client, get_model
from observability import Timer, estimate_tokens, log_call, new_run_id
from prompts import build_messages
from schema import Analysis
from security import check_output, guard_rows, log_event
from timeline import Event, InputRejected, load_timeline

MAX_ATTEMPTS = 2            # one try plus one retry, for errors and bad replies
REQUEST_TIMEOUT = 45        # seconds, per model call
TEXT_FIELDS = ("event", "user", "source", "details")

_REFUSAL = re.compile(
    r"i'?m sorry|i am sorry|i can(?:'|no)t (?:help|assist|comply)|i(?:'m| am) (?:not able|unable) to|"
    r"i (?:won't|will not) (?:help|assist)|cannot (?:help|assist|comply)", re.I)

MESSAGES = {
    "invalid_output": "The model's reply failed validation, so no analysis is shown. Nothing below is an answer.",
    "refused": "The model declined to analyse this timeline. No analysis is shown.",
    "error": "No usable reply: the model call failed. No analysis is shown.",
}


@dataclass
class Result:
    status: str                              # ok | invalid_output | refused | error
    output: Analysis | None = None           # set only when status == "ok"
    warnings: list[str] = field(default_factory=list)   # computed by Python, not the model
    events: list[Event] = field(default_factory=list)   # the sorted timeline
    message: str = ""                        # for the person, never the model's words
    run_id: str = ""

    def report(self) -> dict:
        """What is printed and shown. Only meaningful when status == "ok"."""
        return {
            "events_analyzed": len(self.events),
            "input_warnings": self.warnings,
            "analysis": self.output.model_dump() if self.output else None,
        }


# --------------------------------------------------------------------------

def run(path: str) -> Result:
    """Analyse one timeline CSV. Raises InputRejected before any model call."""
    run_id = new_run_id()

    # 1. Deterministic: read, validate, standardise, sort.
    try:
        events = load_timeline(path)
    except InputRejected:
        log_event("input_rejected", stage="load_timeline")
        raise

    # 2. Input guard: the CSV is untrusted text.
    rows = [{"id": f"E{i:03d}", "row": e.row, "timestamp": e.iso, "event": e.event,
             "user": e.user, "source": e.source, "details": e.details}
            for i, e in enumerate(events, start=1)]
    clean, findings = guard_rows(rows, TEXT_FIELDS)
    warnings = [_warning(f, rows) for f in findings]
    messages = build_messages(clean)
    known = {e.ts for e in events}

    # 3. The model call, with one retry. Each call writes one run_log line.
    result = Result("error", warnings=warnings, events=events, run_id=run_id)
    try:
        client = get_client()
        model = get_model()
    except Exception as exc:                  # e.g. the provider library is missing
        _stderr(f"could not create the model client: {type(exc).__name__}")
        result.message = MESSAGES["error"]
        return result

    for attempt in range(1, MAX_ATTEMPTS + 1):
        status, output, retry_after = _attempt(client, model, messages, known, attempt)
        result.status, result.output = status, output
        if status in ("ok", "refused") or retry_after is None or attempt == MAX_ATTEMPTS:
            break
        time.sleep(retry_after)
    result.message = "" if result.status == "ok" else MESSAGES[result.status]
    return result


# --------------------------------------------------------------------------

def _attempt(client, model: str, messages: list[dict], known: set, attempt: int):
    """One model call. Returns (status, Analysis | None, seconds to wait before a retry | None).

    Logs exactly one run_log line, whatever happens, including a failed call.
    """
    prompt_chars = sum(len(m["content"]) for m in messages)
    text, refused, usage = "", False, None
    status, retry_after = "error", 1.0
    with Timer() as timer:
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0,
                response_format={"type": "json_object"}, timeout=REQUEST_TIMEOUT)
            usage = getattr(resp, "usage", None)
            choice = resp.choices[0]
            text = choice.message.content or ""
            refused = bool(getattr(choice.message, "refusal", None)) or \
                getattr(choice, "finish_reason", "") == "content_filter"
            status = None                                     # decided below
        except Exception as exc:                              # the call itself failed
            _stderr(f"model call failed: {type(exc).__name__}")
            code = getattr(exc, "status_code", None)
            if code in (400, 401, 403, 404):                  # a retry cannot fix these
                retry_after = None
            elif isinstance(getattr(exc, "retry_after", None), (int, float)):
                retry_after = min(float(exc.retry_after), 5.0)

    output = None
    if status is None:                                        # the call returned something
        if refused:
            status, retry_after = "refused", None
        else:
            status, output = _check_reply(text, known)
            retry_after = None if status == "ok" else 0.0

    pt = getattr(usage, "prompt_tokens", None)
    ct = getattr(usage, "completion_tokens", None)
    estimated = not (isinstance(pt, int) and isinstance(ct, int))
    if estimated:
        pt, ct = estimate_tokens("x" * prompt_chars), estimate_tokens(text)
    log_call(model, status, pt, ct, timer.ms, estimated, attempt)
    return status, output, retry_after


def _check_reply(text: str, known: set):
    """Raw reply -> (status, Analysis | None). Nothing is used until it passes."""
    text = (text or "").strip()
    if not text:
        return "invalid_output", None
    candidate = _json_candidate(text)
    if candidate is None:                                     # no JSON at all
        return ("refused" if _REFUSAL.search(text) else "invalid_output"), None
    try:
        data = json.loads(candidate)
        analysis = Analysis.model_validate(data)
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError):
        return "invalid_output", None
    if check_output(analysis.model_dump(), known):            # grounded? no legal claims?
        return "invalid_output", None
    return "ok", analysis


def _json_candidate(text: str):
    """The JSON object in a reply, tolerating ```json fences and a chatty preamble."""
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    return text[start:end + 1]


def _warning(finding: dict, rows: list[dict]) -> str:
    row = next(r for r in rows if r["id"] == finding["id"])
    where = f"{finding['id']} (CSV line {row['row']}), field '{finding['field']}'"
    if finding["kind"] == "instruction":
        return (f"{where}: text that reads like an instruction to an AI was removed before "
                "analysis. This may be tampering or a prompt-injection attempt; check the original file.")
    return f"{where}: longer than the limit and was truncated before analysis."


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)
