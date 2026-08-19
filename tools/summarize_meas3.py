"""Summarize a MEAS-3 run: per-span stability, never a single accuracy number.

Usage: python tools/summarize_meas3.py [--runs evaluation/meas3_runs.jsonl]

Reads the raw per-call rows and derives the four-way classification the package
requires — **stable accept · stable reject · unstable · classifier error** — plus the
pooled per-call flip behaviour. Aggregation happens *here*, after every raw verdict
has already been written, so the disagreement being measured is never voted away
before it is recorded.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
from pathlib import Path

DEFAULT_RUNS = Path("evaluation/meas3_runs.jsonl")
DEFAULT_POPULATION = Path("evaluation/meas3_population.json")


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def classify(verdicts):
    """Four-way, from the raw list of verdicts for one candidate."""
    if any(v == "error" for v in verdicts):
        return "classifier_error"
    unique = set(verdicts)
    if len(unique) > 1:
        return "unstable"
    return "stable_accept" if unique == {"accept"} else "stable_reject"


def summarize(runs_path=DEFAULT_RUNS, population_path=DEFAULT_POPULATION):
    rows = [json.loads(line) for line in
            Path(runs_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    population = json.loads(Path(population_path).read_text(encoding="utf-8"))
    meta = {c["candidate_id"]: c for c in population["candidates"]}

    by_candidate = collections.defaultdict(list)
    for row in rows:
        by_candidate[row["candidate_id"]].append(row)

    per_candidate = {}
    for candidate_id, candidate_rows in by_candidate.items():
        ordered = sorted(candidate_rows, key=lambda r: r["run_index"])
        verdicts = [r["verdict"] for r in ordered]
        per_candidate[candidate_id] = {
            "arm": ordered[0]["arm"],
            "parent": ordered[0]["parent_opportunity_id"],
            "verdicts": verdicts,
            "reasons": [r.get("reason", "") for r in ordered],
            "classification": classify(verdicts),
            "title": (meta.get(candidate_id) or {}).get("title"),
        }

    arms = collections.defaultdict(lambda: collections.Counter())
    for entry in per_candidate.values():
        arms[entry["arm"]][entry["classification"]] += 1

    # Pooled per-call disagreement: a call is a "flip" when it differs from its
    # candidate's modal verdict. This is descriptive, not a vote.
    flips = calls = 0
    for entry in per_candidate.values():
        verdicts = entry["verdicts"]
        if not verdicts:
            continue
        modal = collections.Counter(verdicts).most_common(1)[0][0]
        flips += sum(1 for v in verdicts if v != modal)
        calls += len(verdicts)

    unstable = {
        candidate_id: entry for candidate_id, entry in per_candidate.items()
        if entry["classification"] in {"unstable", "classifier_error"}
    }
    low, high = wilson(flips, calls)
    usage_in = sum(r.get("usage_input") or 0 for r in rows)
    usage_out = sum(r.get("usage_output") or 0 for r in rows)
    thinking = sum(r.get("thinking_tokens") or 0 for r in rows)
    return {
        "calls": len(rows),
        "candidates": len(per_candidate),
        "repeats": max((r["run_index"] for r in rows), default=0),
        "by_arm": {arm: dict(counter) for arm, counter in arms.items()},
        "pooled_flip_calls": flips,
        "pooled_calls": calls,
        "pooled_flip_rate": (flips / calls) if calls else 0.0,
        "pooled_flip_wilson95": [low, high],
        "unstable": unstable,
        "usage": {"input_tokens": usage_in, "output_tokens": usage_out,
                  "thinking_tokens": thinking},
        "per_candidate": per_candidate,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--population", type=Path, default=DEFAULT_POPULATION)
    args = parser.parse_args(argv)
    result = summarize(args.runs, args.population)

    print(f"calls={result['calls']}  candidates={result['candidates']}  "
          f"repeats={result['repeats']}")
    for arm, counts in sorted(result["by_arm"].items()):
        print(f"  arm {arm}: {counts}")
    low, high = result["pooled_flip_wilson95"]
    print(f"pooled per-call disagreement: {result['pooled_flip_calls']}"
          f"/{result['pooled_calls']} = {result['pooled_flip_rate']:.3%}  "
          f"Wilson95 [{low:.3%}, {high:.3%}]")
    print(f"usage: {result['usage']}")
    if result["unstable"]:
        print(f"\nUNSTABLE / ERROR candidates ({len(result['unstable'])}):")
        for candidate_id, entry in sorted(result["unstable"].items()):
            print(f"  {candidate_id}  [{entry['classification']}]  "
                  f"{entry['verdicts']}")
            print(f"      title: {entry['title']}")
            for index, reason in enumerate(entry["reasons"], start=1):
                print(f"      run {index}: {reason[:120]}")
    else:
        print("\nUNSTABLE / ERROR candidates: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
