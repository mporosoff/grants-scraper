"""Score the Cov4 prompt variants. Dimensions stay separate; no single accuracy number.

Usage: python tools/score_cov4_prompts.py [--runs evaluation/cov4_prompt_runs.jsonl]

Reports, per variant and per population:

* **TP / FN / TN / FP** as raw counts, never blended;
* **recall** on known-genuine children — the fail-closed constraint Cov4's gate makes
  load-bearing (*zero* false rejection of known genuine children);
* **specificity** — the share of known contaminants rejected;
* **precision** where a denominator exists;
* unresolved cases, excluded from scoring rather than forced;
* classifier/API errors;
* a breakdown by candidate shape, because a variant that passes overall while failing
  every F4 decoy has not earned P7's trust.

Population A has committed labels only for the candidates copied into the challenge
set. Its remaining candidates are reported as a **descriptive accept-rate**, clearly
separated from scored metrics.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

DEFAULT_RUNS = Path("evaluation/cov4_prompt_runs.jsonl")
CHALLENGE = Path("evaluation/cov4_challenge.json")


def score(runs_path=DEFAULT_RUNS, challenge_path=CHALLENGE):
    rows = [json.loads(line) for line in
            Path(runs_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    challenge = json.loads(Path(challenge_path).read_text(encoding="utf-8"))
    labels = {c["candidate_id"]: c for c in challenge["candidates"]}

    out = {}
    for row in rows:
        key = (row["variant"], row["population"])
        bucket = out.setdefault(key, {
            "TP": 0, "FN": 0, "TN": 0, "FP": 0, "unresolved": 0, "errors": 0,
            "unlabelled_accept": 0, "unlabelled_reject": 0,
            "by_shape": collections.defaultdict(lambda: collections.Counter()),
            "false_negatives": [], "false_positives": [],
            "thinking_calls": 0, "calls": 0,
        })
        bucket["calls"] += 1
        if (row.get("thinking_tokens") or 0) > 0:
            bucket["thinking_calls"] += 1
        verdict = row["verdict"]
        if verdict == "error":
            bucket["errors"] += 1
            continue
        meta = labels.get(row["candidate_id"])
        truth = (row.get("truth_label")
                 or (meta or {}).get("truth_label"))
        shape = (meta or {}).get("shape") or row.get("shape") or "production_span"
        if truth == "unresolved":
            bucket["unresolved"] += 1
            bucket["by_shape"][shape]["unresolved"] += 1
            continue
        if truth is None:
            bucket["unlabelled_accept" if verdict == "accept"
                   else "unlabelled_reject"] += 1
            continue
        if truth == "fundable":
            if verdict == "accept":
                bucket["TP"] += 1
                bucket["by_shape"][shape]["TP"] += 1
            else:
                bucket["FN"] += 1
                bucket["by_shape"][shape]["FN"] += 1
                bucket["false_negatives"].append(
                    (row["candidate_id"], row.get("reason", ""))
                )
        else:
            if verdict == "reject":
                bucket["TN"] += 1
                bucket["by_shape"][shape]["TN"] += 1
            else:
                bucket["FP"] += 1
                bucket["by_shape"][shape]["FP"] += 1
                bucket["false_positives"].append(
                    (row["candidate_id"], row.get("reason", ""))
                )
    for bucket in out.values():
        bucket["by_shape"] = {k: dict(v) for k, v in bucket["by_shape"].items()}
    return out


def _rate(numerator, denominator):
    return f"{numerator/denominator:.1%}" if denominator else "n/a"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--challenge", type=Path, default=CHALLENGE)
    args = parser.parse_args(argv)
    result = score(args.runs, args.challenge)

    for (variant, population), b in sorted(result.items()):
        genuine = b["TP"] + b["FN"]
        contaminant = b["TN"] + b["FP"]
        accepted = b["TP"] + b["FP"]
        print(f"\n=== {variant}  |  population {population}  ({b['calls']} calls)")
        print(f"    TP={b['TP']}  FN={b['FN']}  TN={b['TN']}  FP={b['FP']}  "
              f"unresolved={b['unresolved']}  errors={b['errors']}")
        print(f"    recall(genuine kept) = {_rate(b['TP'], genuine)}   "
              f"specificity(contaminants rejected) = {_rate(b['TN'], contaminant)}   "
              f"precision = {_rate(b['TP'], accepted)}")
        if b["unlabelled_accept"] or b["unlabelled_reject"]:
            total = b["unlabelled_accept"] + b["unlabelled_reject"]
            print(f"    [descriptive, unlabelled] accept "
                  f"{b['unlabelled_accept']}/{total} = "
                  f"{_rate(b['unlabelled_accept'], total)}")
        print(f"    thinking-token calls: {b['thinking_calls']}/{b['calls']}")
        if b["false_negatives"]:
            print(f"    FALSE NEGATIVES ({len(b['false_negatives'])}):")
            for cid, reason in b["false_negatives"]:
                print(f"       {cid}: {reason[:100]}")
        if b["false_positives"]:
            print(f"    FALSE POSITIVES ({len(b['false_positives'])}):")
            for cid, reason in b["false_positives"]:
                print(f"       {cid}: {reason[:100]}")
        if population == "B":
            print("    by shape:")
            for shape, counts in sorted(b["by_shape"].items()):
                print(f"       {shape:28} {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
