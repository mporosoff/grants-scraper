"""Write a copy of a catalog whose top-level ``generated_at`` is pinned.

Usage: python tools/pin_generated_at.py <catalog-in> <catalog-out> <timestamp>

Gate tooling only. Nothing in ``scripts/`` imports this, and production output is
unaffected: the nightly goes on stamping the real wall clock.

Why this exists
---------------
``scripts/build_changes.py`` derives every event's ``changed_at`` from the
*current* catalog's ``generated_at``, and ``_event_id`` seeds its SHA-1 with
``changed_at[:10]`` -- the **UTC calendar date**. So every event id turns over at
midnight UTC. ``--as-of`` does not reach that value: it controls currentness
evaluation and retention, not the stamp the catalog was built with.

That made the hermetic no-drift gate (§8.4) green only on the day its baseline was
frozen, which is §15 debt D7. ``tools/fingerprint.py`` cannot fix it downstream --
an id is an opaque hash and normalizing hashes would blind the gate to real
content changes, which is the opposite of what it is for.

The fix is to pin the *input* instead: ``tools/hermetic_build.sh`` writes this
pinned copy into ``.work/`` and hands it to ``build_changes`` as ``--current``, so
``changed_at`` and every event id are deterministic. ``.work/`` is excluded from
fingerprinting, so the pinned copy is never itself an artifact, and
``opportunities.js`` -- the real artifact -- is untouched.

The substitution is textual and replaces exactly one field, so every other byte of
the catalog reaches ``build_changes`` as the pipeline produced it. It refuses to
guess: no match, or more than one, is an error rather than a silent pass.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

# `"generated_at":` only. The catalog also carries
# `detail_enrichment_generated_at`, `document_evidence_generated_at` and
# `link_health_generated_at`, and the leading quote is what excludes them.
GENERATED_AT_RE = re.compile(r'"generated_at"(\s*):(\s*)"[^"]*"')

# Must match tools/fingerprint.py's TIMESTAMP_RE, or the pinned value would be
# left in the artifacts un-normalized and the gate would compare wall clocks.
TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)


def pin(text: str, timestamp: str) -> str:
    """Return `text` with its one top-level `generated_at` set to `timestamp`."""
    if not TIMESTAMP_RE.match(timestamp):
        raise ValueError(
            f"{timestamp!r} is not an ISO-8601 datetime literal; "
            "tools/fingerprint.py would not normalize it"
        )
    matches = GENERATED_AT_RE.findall(text)
    if len(matches) != 1:
        raise ValueError(
            f'expected exactly one "generated_at" field, found {len(matches)}'
        )

    def replace(match: re.Match) -> str:
        return f'"generated_at"{match.group(1)}:{match.group(2)}"{timestamp}"'

    return GENERATED_AT_RE.sub(replace, text, count=1)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        print(
            "usage: python tools/pin_generated_at.py "
            "<catalog-in> <catalog-out> <timestamp>",
            file=sys.stderr,
        )
        return 2
    source, destination, timestamp = argv
    text = Path(source).read_text(encoding="utf-8")
    try:
        pinned = pin(text, timestamp)
    except ValueError as error:
        print(f"pin_generated_at: {error}", file=sys.stderr)
        return 1
    Path(destination).write_text(pinned, encoding="utf-8", newline="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
