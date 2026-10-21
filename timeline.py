"""
timeline.py - the deterministic half of ForensiQ. No model is involved here.

Reads the CSV, checks it, converts every timestamp to one standard format
(UTC, ISO 8601) and sorts the events in time order. Python does this because
it must be right every time; an LLM could silently change or drop evidence.

Anything wrong with the file raises InputRejected. The pipeline turns that
into "exit 2, no model call".
"""

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 200_000          # ~2x the biggest file in the brief (100 KB); far below 1 MB
MAX_EVENTS = 1000            # the brief says 50-500 events per file
REQUIRED_COLUMNS = ("timestamp", "event")
OPTIONAL_COLUMNS = ("user", "source", "details")
ALLOWED_SUFFIX = ".csv"


class InputRejected(Exception):
    """The input is unusable. Raised before any model call."""


@dataclass(frozen=True)
class Event:
    row: int              # line number in the original CSV (header = line 1)
    ts: datetime          # timezone-aware, UTC
    event: str
    user: str
    source: str
    details: str

    @property
    def iso(self) -> str:
        return self.ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp(text: str) -> datetime:
    """ISO 8601 only ("2026-03-14T14:02:11Z", "2026-03-14 14:02:11+05:30").

    A timestamp with no timezone is taken to be UTC. Day-first formats such as
    14/03/2026 are rejected on purpose: 03/04/2026 can mean two different days
    and guessing would silently put evidence in the wrong order.
    """
    s = (text or "").strip()
    if not s:
        raise InputRejected("empty timestamp")
    if s[-1] in "Zz":
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise InputRejected(f"not an ISO 8601 timestamp: {text[:40]!r}") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def load_timeline(path: str) -> list[Event]:
    """Read, validate and sort. Returns the events oldest first."""
    p = Path(path)
    if p.suffix.lower() != ALLOWED_SUFFIX:
        raise InputRejected(f"only {ALLOWED_SUFFIX} files are accepted, not {p.suffix or 'no extension'!r}")
    try:
        size = p.stat().st_size
    except OSError as exc:
        raise InputRejected(f"cannot read the file: {exc.strerror or exc}") from None
    if size == 0:
        raise InputRejected("the file is empty")
    if size > MAX_BYTES:
        raise InputRejected(f"the file is {size:,} bytes; the limit is {MAX_BYTES:,}")

    raw = p.read_bytes()
    if b"\x00" in raw:
        raise InputRejected("the file contains NUL bytes; it is not a text CSV")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputRejected("the file is not valid UTF-8 text") from None

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        header = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
        reader.fieldnames = header
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise InputRejected("missing required column(s): " + ", ".join(missing))
        events = []
        for record in reader:
            line = reader.line_num
            if not any((v or "").strip() for k, v in record.items() if k):
                continue                                    # blank line
            if len(events) >= MAX_EVENTS:
                raise InputRejected(f"more than {MAX_EVENTS} events")
            if not (record.get("event") or "").strip():
                raise InputRejected(f"line {line}: the event is empty")
            try:
                ts = parse_timestamp(record.get("timestamp", ""))
            except InputRejected as exc:
                raise InputRejected(f"line {line}: {exc}") from None
            get = lambda k: (record.get(k) or "").strip()
            events.append(Event(line, ts, get("event"), get("user"), get("source"), get("details")))
    except csv.Error as exc:
        raise InputRejected(f"the CSV is malformed: {exc}") from None

    if not events:
        raise InputRejected("the file has a header but no events")
    events.sort(key=lambda e: e.ts)                        # stable: ties keep file order
    return events
