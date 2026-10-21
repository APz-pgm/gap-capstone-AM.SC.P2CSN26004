"""
main.py - run ForensiQ without the UI.

    python main.py <timeline.csv>

The last line printed is the status: ok, invalid_output, refused or error.
Exit code: 0 for ok, 1 for the other three, 2 when the input is rejected
before any model call (empty, too large, wrong type, malformed CSV).
Messages for the person running it go to stderr; stdout carries only the
validated report (when ok) and the status line.
"""

import json
import sys

from pipeline import InputRejected, run


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python main.py <timeline.csv>", file=sys.stderr)
        return 2
    try:
        result = run(argv[1])
    except InputRejected as exc:
        print(f"Input rejected, no analysis attempted: {exc}", file=sys.stderr)
        print("rejected")
        return 2
    except Exception as exc:                  # never a traceback, never a half answer
        print(f"Unexpected failure: {type(exc).__name__}", file=sys.stderr)
        print("error")
        return 1

    for w in result.warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if result.status != "ok":
        print(result.message, file=sys.stderr)
    else:
        print(json.dumps(result.report(), indent=2, ensure_ascii=False))
    print(result.status)
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
