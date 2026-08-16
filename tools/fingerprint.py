"""Timestamp-normalized fingerprints for hermetic build artifacts.

Usage: python tools/fingerprint.py <dir>

Prints ``<sha256>  <relative path>`` per artifact, sorted by path, so two runs
of ``tools/hermetic_build.sh`` can be compared byte for byte.

Why timestamps are normalized
-----------------------------
Four catalog fields plus several cache and feed fields carry the wall-clock
time of the run. They change every time by design and carry no behavioral
signal, so they are replaced with a constant before hashing. This keeps the
gate installable with **zero production-code changes**, which matters for a
safety net that has to exist before any behavior-affecting change.

Normalization replaces every ISO-8601 *datetime* literal. Date-only values such
as ``2026-09-30`` are untouched, so close dates, archive dates and every other
currentness input remain fingerprinted. Entry-level ``<updated>`` values in the
Atom feeds are derived from record dates that are themselves fingerprinted
inside ``opportunities.js``, so nothing is lost from the gate as a whole.

A literal regex over the file text is used rather than a JSON-aware pass
because the artifacts are a mix of minified JSON, indented JSON, Atom XML, a
JavaScript assignment, and HTML with a bare timestamp in prose.

See docs/TOPIC_LAYER_PLAN.md §8.4.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import sys


# 2026-08-16T12:15:56Z and 2026-08-16T12:15:56.770421Z, with or without offset.
TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
)
FROZEN_TIMESTAMP = "FROZEN-TIMESTAMP"


def normalize(data: bytes) -> bytes:
    """Replace every ISO-8601 datetime literal with a constant."""
    text = data.decode("utf-8", errors="surrogateescape")
    return TIMESTAMP_RE.sub(FROZEN_TIMESTAMP, text).encode(
        "utf-8", errors="surrogateescape"
    )


def artifacts(root: Path):
    """Every file under root, excluding dot-directories such as .work/."""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        yield relative, path


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python tools/fingerprint.py <dir>", file=sys.stderr)
        return 2
    root = Path(argv[0])
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    # The baseline is committed and diffed, and .gitattributes normalizes the
    # repository to LF. Emit LF on every platform so a Windows regeneration
    # does not report every line as changed.
    sys.stdout.reconfigure(newline="\n")
    for relative, path in artifacts(root):
        digest = hashlib.sha256(normalize(path.read_bytes())).hexdigest()
        print(f"{digest}  {relative.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
