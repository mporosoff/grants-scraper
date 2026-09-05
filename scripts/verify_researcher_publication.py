"""Verify a published researcher against the exact generated directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


def read_directory(path: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    return json.loads(source[source.index("{"):].rstrip().rstrip(";"))


def verify_profile(expected: dict, live: dict, generation: str, researcher_id: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{64}", generation):
        raise ValueError("A valid expected registry generation is required")
    if not re.fullmatch(r"urh-[0-9]{6}", researcher_id):
        raise ValueError("A stable researcher ID is required")
    for directory in (expected, live):
        if directory.get("registry_generation") != generation:
            raise ValueError("Researcher directory generation does not match the approved publication")
    expected_rows = [row for row in expected["researchers"] if row["id"] == researcher_id]
    live_rows = [row for row in live["researchers"] if row["id"] == researcher_id]
    if len(expected_rows) != 1 or len(live_rows) != 1:
        raise ValueError("The published researcher must resolve to exactly one stable identity")
    if live_rows[0] != expected_rows[0]:
        raise ValueError("The published profile does not match its generated identity, evidence, and eligibility")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-directory", type=Path, default=Path("data/researcher_directory.js"))
    parser.add_argument("--live-directory", type=Path, required=True)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--researcher-id", required=True)
    args = parser.parse_args()
    verify_profile(read_directory(args.expected_directory), read_directory(args.live_directory),
                   args.generation, args.researcher_id)


if __name__ == "__main__":
    main()
