"""Timestamp-normalized fingerprints for hermetic build artifacts.

Usage: python tools/fingerprint.py <dir>

Prints ``<sha256>  <relative path>`` per artifact, sorted by path, so two runs
of ``tools/hermetic_build.sh`` can be compared byte for byte.

What is normalized, and why
---------------------------
Two things vary between runs without any change in behavior:

1. **Wall-clock timestamps.** Four catalog fields plus several cache and feed
   fields carry the time of the run.
2. **Line endings.** The pipeline writes through two different APIs, one of
   which takes the platform default, so 16 of the 20 artifacts are CRLF on
   Windows and LF on Linux. See :func:`normalize`.

Both are replaced before hashing. This keeps the gate installable with **zero
production-code changes**, which matters for a safety net that has to exist
before any behavior-affecting change.

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

# The metadata sidecar derives its cache-busting asset identity from the same
# pipeline timestamp, but uses the compact
# ``catalog-YYYYMMDDTHHMMSSffffffZ`` shape required in browser URLs. The
# fractional digits prevent two same-second publications from reusing cached
# metadata and catalog URLs. Normalize both the current and former shapes for
# the same reason as the ISO literal above; record contents and every non-time
# identity input remain fingerprinted.
CATALOG_ASSET_VERSION_RE = re.compile(
    r"catalog-\d{8}T\d{6}(?:\d{6})?Z"
)
FROZEN_CATALOG_ASSET_VERSION = "catalog-FROZEN-TIMESTAMP"

# A DATE-ONLY volatile field, normalized by name rather than by shape.
#
# `source_first_seen_date` records the day this build first saw a record, so it
# is "today" on every run. It is date-only, so TIMESTAMP_RE deliberately does
# not touch it -- that regex leaves bare dates alone precisely so close dates,
# archive dates and every other currentness input stay fingerprinted.
#
# The consequence went unnoticed until it bit: the gate was green at 23:59 UTC
# and failed at 01:04 UTC the next day, with no code change, because the field
# rolled over. §17.6 rule 2 asks for two builds separated by a delay, and 78
# seconds satisfies that while never crossing midnight. **Date rollover is a
# third axis, alongside time and platform**, and the baseline had only ever
# been varied along two.
#
# Normalizing one named field keeps every other bare date fingerprinted, which
# is what §8.4 wants, and keeps the fix in the gate's tooling rather than in
# production code -- `sources merge` has no `--as-of` to pin, and adding one
# would be production surface added for a test.
DATE_FIELD_RE = re.compile(
    r'("source_first_seen_date"\s*:\s*")\d{4}-\d{2}-\d{2}(")'
)
FROZEN_DATE = r"\1FROZEN-DATE\2"


def normalize(data: bytes) -> bytes:
    """Canonicalize line endings, then replace every ISO-8601 datetime.

    Line endings are normalized because the pipeline writes its artifacts
    through two different APIs. ``build_catalog``, ``enrich_catalog``,
    ``extract_document_evidence`` and ``sources/merge`` write through
    ``tempfile.NamedTemporaryFile(..., newline="\\n")``, which is LF on every
    platform. ``check_links``, ``build_changes`` and ``build_feeds`` write
    through ``Path.write_text()`` with no ``newline`` argument, which takes the
    platform default -- CRLF on Windows, LF on Linux.

    A baseline recorded on Windows therefore disagrees with a CI run on Linux
    for those artifacts and no others, which is a property of the developer's
    operating system rather than of the code under test. Normalizing here keeps
    the three downstream scripts untouched, so the nightly build goes on
    emitting exactly the bytes it emits today.
    """
    text = data.decode("utf-8", errors="surrogateescape")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = TIMESTAMP_RE.sub(FROZEN_TIMESTAMP, text)
    text = CATALOG_ASSET_VERSION_RE.sub(FROZEN_CATALOG_ASSET_VERSION, text)
    text = DATE_FIELD_RE.sub(FROZEN_DATE, text)
    return text.encode("utf-8", errors="surrogateescape")


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
