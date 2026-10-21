"""
eval_run.py - runs the EVAL.md rows and prints the Result column and the Metrics.

    python eval_run.py                # uses whatever your .env points at
    python eval_run.py --rows 1 2 9   # only some rows

Run it against your REAL model (openai/gpt-oss-120b).
proves the code runs, and it says so. Output is also written to eval_results.md.

Each row is a list of facts that must be true (never exact wording). The
rows here are the same rows as the table in EVAL.md; keep the two in step.
"""

import argparse
import json
import os
import statistics
import sys
import time
from datetime import date
from pathlib import Path

from pipeline import InputRejected, run
from observability import log_path
from timeline import parse_timestamp

IN = Path("samples/inputs")


def cited(result):
    """The timestamps the model cited, in one standard format."""
    if not result.output:
        return set()
    return {parse_timestamp(e.timestamp).strftime("%Y-%m-%dT%H:%M:%SZ")
            for e in result.output.significant_events}


# Each check returns a list of what went wrong; [] means the row passes.
def analysed(r, must_cite=(), assessment=None, risk=None, no_warnings=False, warnings=False):
    bad = []
    if r.status != "ok":
        return [f"status {r.status}, not ok"]
    o = r.output
    if assessment and o.overall_assessment != assessment:
        bad.append(f"assessment {o.overall_assessment}, wanted {assessment}")
    if risk and o.risk_level not in risk:
        bad.append(f"risk {o.risk_level}, wanted one of {risk}")
    missing = [t for t in must_cite if t not in cited(r)]
    if missing:
        bad.append("did not cite " + ", ".join(missing))
    if no_warnings and r.warnings:
        bad.append(f"{len(r.warnings)} input warning(s): a legitimate cell was removed")
    if warnings and not r.warnings:
        bad.append("no input warning: the hidden instruction was not detected")
    return bad


COPIES = ("2026-03-14T14:03:58Z", "2026-03-14T14:04:21Z")
COPIES_TZ = ("2026-03-14T14:05:58Z", "2026-03-14T14:06:21Z")

ROWS = [
    (1, "Ordinary", "sample_ok.csv", lambda r: analysed(
        r, COPIES, "potentially_significant", ("medium", "high"))),
    (2, "Nothing wrong", "normal_session.csv", lambda r: analysed(
        r, (), "no_significant_sequence", ("low",))),
    (3, "Unusual", "unrelated_usb.csv", lambda r: analysed(
        r, (), "no_significant_sequence", ("low",))),
    (4, "Unusual", "mixed_timezones.csv", lambda r: analysed(
        r, COPIES_TZ, "potentially_significant", ("medium", "high"))),
    (5, "Unusual", "benign_phrase.csv", lambda r: analysed(
        r, (), "no_significant_sequence", ("low",), no_warnings=True)),
    (6, "Unusual", "day_first_dates.csv", lambda r: analysed(r)),
    (7, "Malformed", "empty.csv", "reject"),
    (8, "Malformed", "missing_column.csv", "reject"),
    (9, "Injected", "sample_injected.csv", lambda r: analysed(
        r, COPIES, "potentially_significant", ("medium", "high"), warnings=True)),
    (10, "Injected", "injected_paraphrase.csv", lambda r: analysed(
        r, COPIES, "potentially_significant", ("medium", "high"), warnings=True)),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", nargs="*", type=int)
    args = ap.parse_args()
    model = os.getenv("LLM_MODEL", "")
    stub = os.getenv("LLM_BASE_URL", "").startswith("local://stub")
    if stub or not model:
        print("WARNING: this is the stub (or no model is set). These results say nothing "
              "about accuracy. Point .env at your real model first.\n", file=sys.stderr)
    pause = float(os.getenv("EVAL_PAUSE", "0" if stub else "7"))   # free-tier rate limit

    before = log_path().read_text().count("\n") if log_path().exists() else 0
    table, passed, total, run_ids = [], 0, 0, []
    for n, kind, fname, check in ROWS:
        if args.rows and n not in args.rows:
            continue
        path = str(IN / fname)
        total += 1
        try:
            result = run(path)
            if check == "reject":
                problems = ["accepted a file that should be rejected"]
            else:
                problems = check(result)
            run_ids.append(result.run_id)
        except InputRejected as exc:
            if check == "reject":
                problems = []
            else:
                problems = [f"rejected before analysis: {str(exc)[:60]}"]
        ok = not problems
        passed += ok
        table.append(f"| {n} | {kind} | {fname} | {'pass' if ok else '**fail:** ' + '; '.join(problems)} |")
        print(table[-1])
        if check != "reject" and pause:
            time.sleep(pause)

    lines = [json.loads(x) for x in log_path().read_text().splitlines()[before:] if x.strip()] \
        if log_path().exists() else []
    lat = [x["latency_ms"] for x in lines]
    per_run = {}
    for x in lines:
        per_run.setdefault(x["run_id"], []).append(x)
    costs = [sum(c["cost_usd"] for c in v) for v in per_run.values()]
    toks = [sum(c["prompt_tokens"] + c["completion_tokens"] for c in v) for v in per_run.values()]
    out = [f"Model: {model}   Date: {date.today().isoformat()}", "",
           "| # | Kind | Input | Result |", "|---|---|---|---|", *table, "",
           "| Metric | Value |", "|---|---|",
           f"| Accuracy | {passed} of {total} rows pass ({model}, {date.today().isoformat()}) |"]
    if lat:
        out += [f"| Speed | median {statistics.median(lat)/1000:.1f} s, slowest {max(lat)/1000:.1f} s "
                f"per model call ({len(lat)} calls) |",
                f"| Cost | ${statistics.mean(costs):.5f} per run at list price "
                f"(mean over {len(costs)} runs that called the model; "
                f"{statistics.mean(toks):.0f} tokens per run) |"]
    text = "\n".join(out)
    print("\n" + text)
    Path("eval_results.md").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
