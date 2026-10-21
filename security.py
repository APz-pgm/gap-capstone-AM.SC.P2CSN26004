"""
security.py - every guardrail ForensiQ has, and security_log.jsonl.

Three guards live here:

  1. guard_rows()    INPUT guard. The CSV is untrusted: any cell can hold text
                     written by an attacker. Every cell is normalised, and a
                     cell that reads like an instruction to the model is
                     replaced by a placeholder BEFORE the model sees it.
  2. check_output()  OUTPUT guard. After the reply passes the Pydantic schema,
                     check it is grounded (every timestamp it cites exists in
                     the input) and that it makes no legal conclusion.
  3. log_event()     Writes security_log.jsonl. Event names:
                         guardrail_input, instruction_ignored,
                         guardrail_output, field_truncated, input_rejected

The log records WHERE something happened (row id, field name, pattern name),
never the content of the user's file.
"""

import json
import re
import unicodedata
from pathlib import Path
import os

from observability import current_run_id, now_iso
from timeline import parse_timestamp, InputRejected

PLACEHOLDER = "[removed: instruction-like text]"
MAX_FIELD_CHARS = 500

# --------------------------------------------------------------------------
# Input guard
# --------------------------------------------------------------------------

# (name, regex). The first five are the phrasings in the course guide; the
# rest are extra ones that an attacker planting text in a forensic log would
# try. Matching is on normalised text, so capitals, spacing, zero-width
# characters and look-alike (full-width) letters do not hide a phrase.
INJECTION_PATTERNS = [
    ("ignore_previous", re.compile(r"ignore\s+(all\s+|any\s+)?(previous|prior|earlier|above)\s+instructions", re.I)),
    ("disregard_above", re.compile(r"disregard\s+(the\s+|all\s+|any\s+)?(above|previous|prior|earlier)", re.I)),
    ("system_note", re.compile(r"(system|assistant|admin)\s*(note|directive|override|message)\s*:", re.I)),
    ("must_append", re.compile(r"you\s+must\s+(now\s+)?append", re.I)),
    ("new_instructions", re.compile(r"new\s+instructions?\s+for\s+the\s+(assistant|model|ai)", re.I)),
    # extras
    ("do_not_report", re.compile(r"do\s+not\s+(report|flag|mention)\s+(any|this|these|the)", re.I)),
    ("report_nothing", re.compile(r"(report|conclude|respond|answer|return)\s+(that\s+)?(there\s+is\s+)?(nothing|no\s+(findings|issues|problems|significant))", re.I)),
    ("mark_as_safe", re.compile(r"mark\s+(this|it|every|all|the)\b.{0,40}\b(low\s+risk|safe|benign|harmless|normal)", re.I)),
    ("you_are_now", re.compile(r"you\s+are\s+now\s+(a|an|the|in)\b", re.I)),
]

_INVISIBLE = dict.fromkeys(
    list(range(0x200B, 0x2010)) + [0x2060, 0x2061, 0x2062, 0x2063, 0xFEFF, 0x00AD], None)


def normalise(text: str) -> str:
    """NFKC, drop zero-width/control characters, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text or "").translate(_INVISIBLE)
    text = "".join(ch if (ch.isprintable() or ch in "\t\r\n") else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def find_instructions(text: str) -> list[str]:
    """Names of the injection patterns found in text."""
    return [name for name, rx in INJECTION_PATTERNS if rx.search(text)]


def guard_rows(rows: list[dict], text_fields: tuple[str, ...]) -> tuple[list[dict], list[dict]]:
    """Clean every text cell of every row.

    rows: dicts that each carry an "id". Returns (clean_rows, findings).
    findings are plain dicts: {"id", "field", "kind": "instruction"|"truncated"}.
    Logs guardrail_input per removed cell, then ONE instruction_ignored per run.
    """
    clean, findings = [], []
    for row in rows:
        new = dict(row)
        for fld in text_fields:
            value = normalise(str(row.get(fld, "")))
            hits = find_instructions(value)
            if hits:
                value = PLACEHOLDER
                findings.append({"id": row["id"], "field": fld, "kind": "instruction"})
                log_event("guardrail_input", row=row["id"], field=fld, patterns=hits)
            elif len(value) > MAX_FIELD_CHARS:
                value = value[:MAX_FIELD_CHARS] + " [truncated]"
                findings.append({"id": row["id"], "field": fld, "kind": "truncated"})
                log_event("field_truncated", row=row["id"], field=fld)
            new[fld] = value
        clean.append(new)
    removed = [f for f in findings if f["kind"] == "instruction"]
    if removed:
        log_event("instruction_ignored", cells=len(removed),
                  action="text treated as data and removed; the model never saw it")
    return clean, findings


# --------------------------------------------------------------------------
# Output guard
# --------------------------------------------------------------------------

# Out of scope in the brief: legal conclusions, attribution, "proven" claims.
OVERCLAIM_PATTERNS = [
    ("legal_conclusion", re.compile(r"\b(is|are|was|were)\s+guilty\b|\bcommitted\s+(a\s+)?(crime|offen[cs]e|theft|fraud)\b|\bbeyond\s+(a\s+)?reasonable\s+doubt\b", re.I)),
    ("claims_proof", re.compile(r"\b(proves?|proven|confirms?|confirmed)\s+(that\s+)?(the\s+)?(user|employee|suspect|data\s+(was|were)\s+(stolen|exfiltrated))", re.I)),
    ("attribution", re.compile(r"\b(the\s+)?(user|employee|suspect|insider)\s+(stole|leaked|exfiltrated|sabotaged)\b", re.I)),
]


def _output_strings(out: dict) -> list[str]:
    strings = [out.get("explanation", ""), out.get("forensic_relevance", "")]
    strings += [str(q) for q in out.get("investigator_questions", [])]
    strings += [str(e.get("description", "")) for e in out.get("significant_events", [])]
    return strings


def check_output(out: dict, known_timestamps: set) -> list[str]:
    """Problems with a reply that already passed the schema. [] means fine.

    1. Grounded: every timestamp in significant_events must be one of the
       events in the input. A model cannot cite an event that does not exist.
    2. No legal conclusion, no 'proof', no naming a person as the culprit.
    3. The reply must not repeat an instruction-like phrase (the input was
       scrubbed of them, so one appearing in the reply is a red flag).
    """
    problems = []
    for ev in out.get("significant_events", []):
        try:
            ts = parse_timestamp(str(ev.get("timestamp", "")))
        except InputRejected:
            problems.append("a cited timestamp is not a valid timestamp")
            continue
        if ts not in known_timestamps:
            problems.append("a cited timestamp does not exist in the input timeline")
    text = " ".join(_output_strings(out))
    problems += [f"reply contains {name}" for name, rx in OVERCLAIM_PATTERNS if rx.search(text)]
    problems += [f"reply repeats an instruction-like phrase ({n})" for n in find_instructions(text)]
    problems = sorted(set(problems))
    if problems:
        log_event("guardrail_output", problems=problems)
    return problems


# --------------------------------------------------------------------------
# security_log.jsonl
# --------------------------------------------------------------------------

def log_event(event: str, **fields) -> dict:
    """Append one line to security_log.jsonl. Never pass file content in fields."""
    line = {"timestamp": now_iso(), "run_id": current_run_id(), "event": event, **fields}
    path = Path(os.getenv("SECURITY_LOG_PATH", "security_log.jsonl"))
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
    return line
