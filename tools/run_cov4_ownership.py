"""Run O1, and score O1/O2/O3 plus the combined Cov4 gate.

Usage:
    $env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY","User")
    python tools/run_cov4_ownership.py

Only **O1** makes API calls; O2 is deterministic and O3 consults the classifier only
for `unestablished` candidates. The semantic prompt is **V1_propose_against**, selected
per the committed prompt-experiment result: V1 and V3 tie on every gate figure
(23 TP / 0 FN / 10 TN / 2 FP, 100% recall on both populations), so the simpler of the
two is taken. Model, R=1, sampling and output schema are unchanged; the only
experimental variable is ownership handling.

`source_kind` for challenge-set rows is assigned by a stated rule, not guessed: every
row copied from the frozen MEAS-3 population came from its parent's pinned **primary
notice**, and the one aggregating-page row is Cov1's `subtopic_agency_notice` (BUG-9).
Hand-built rows quote their parent's own attachment.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.cov4_ownership import (                       # noqa: E402
    CONFLICT, OWNED, UNESTABLISHED, ownership_o2, render_o1, strategy_o3,
)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MODEL = "claude-sonnet-5"

OWNERSHIP = Path("evaluation/cov4_ownership.json")
CHALLENGE = Path("evaluation/cov4_challenge.json")
PROMPT_RUNS = Path("evaluation/cov4_prompt_runs.jsonl")
DEFAULT_OUT = Path("evaluation/cov4_ownership_runs.jsonl")

SEMANTIC_VARIANT = "V1_propose_against"
AGENCY_PAGE_ROWS = {"363594:x-other-foa-topic"}


def challenge_source_kind(candidate):
    if candidate["candidate_id"] in AGENCY_PAGE_ROWS:
        return "subtopic_agency_notice"
    return "primary_notice"


def _call_o1(candidate, *, session, api_key):
    started = time.monotonic()
    response = session.post(
        API_URL,
        headers={"x-api-key": api_key, "anthropic-version": API_VERSION,
                 "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": 1024,
              "messages": [{"role": "user", "content": render_o1(candidate)}]},
        timeout=120,
    )
    row = {"candidate_id": candidate["candidate_id"],
           "status_code": response.status_code,
           "latency_ms": int((time.monotonic() - started) * 1000)}
    if response.status_code != 200:
        row.update(owned="error", fundable="error",
                   reason=f"http_{response.status_code}")
        return row
    payload = response.json()
    text = "".join(b.get("text", "") for b in payload.get("content", [])
                   if b.get("type") == "text").strip()
    usage = payload.get("usage") or {}
    row.update(usage_input=usage.get("input_tokens"),
               usage_output=usage.get("output_tokens"),
               thinking_tokens=(usage.get("output_tokens_details") or {}).get(
                   "thinking_tokens"),
               raw=text[:400])
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        parsed = json.loads(text[start:end])
        row["owned"] = str(parsed.get("owned", "")).strip().lower()
        row["fundable"] = str(parsed.get("fundable", "")).strip().lower()
        row["reason"] = str(parsed.get("reason", ""))[:300]
    except Exception:                       # noqa: BLE001
        row.update(owned="error", fundable="error", reason="unparseable_response")
    return row


def load_candidates():
    """Ownership cases plus the challenge set, each carrying a source_kind."""
    ownership = json.loads(OWNERSHIP.read_text(encoding="utf-8"))["candidates"]
    challenge = json.loads(CHALLENGE.read_text(encoding="utf-8"))["candidates"]
    rows = [dict(candidate, set_name="ownership") for candidate in ownership]
    for candidate in challenge:
        rows.append(dict(
            candidate,
            set_name="challenge",
            source_kind=challenge_source_kind(candidate),
            owned=("no" if candidate["candidate_id"] in AGENCY_PAGE_ROWS else "yes"),
            fundable={"fundable": "yes", "contaminant": "no",
                      "unresolved": "unresolved"}[candidate["truth_label"]],
        ))
    return rows


def run(out_path=DEFAULT_OUT):
    import requests

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is not set in this process.")
    candidates = load_candidates()
    session = requests.Session()
    out_path = Path(out_path)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for candidate in candidates:
            row = _call_o1(candidate, session=session, api_key=api_key)
            row["set_name"] = candidate["set_name"]
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
    print(f"O1: {len(candidates)} calls -> {out_path}")
    return candidates


def semantic_verdicts():
    """V1's fundability verdicts from the committed prompt-experiment run."""
    verdicts = {}
    for line in PROMPT_RUNS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["variant"] == SEMANTIC_VARIANT and row["population"] == "B":
            verdicts[row["candidate_id"]] = row["verdict"]
    return verdicts


def _o1_ownership(o1_row):
    return {"yes": OWNED, "no": CONFLICT}.get((o1_row or {}).get("owned"),
                                              UNESTABLISHED)


def score(out_path=DEFAULT_OUT):
    candidates = {c["candidate_id"]: c for c in load_candidates()}
    o1_rows = {}
    for line in Path(out_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            o1_rows[row["candidate_id"]] = row
    v1 = semantic_verdicts()

    stats = {name: collections.Counter() for name in ("O1", "O2", "O3")}
    misses = {name: [] for name in ("O1", "O2", "O3")}
    for cid, candidate in candidates.items():
        o1 = o1_rows.get(cid, {})
        predictions = {
            "O1": _o1_ownership(o1),
            "O2": ownership_o2(candidate)["ownership"],
            "O3": strategy_o3(candidate,
                              classifier_owned=(o1.get("owned") == "yes")
                              if o1 else None)["ownership"],
        }
        truth = candidate["owned"]
        for name, predicted in predictions.items():
            label = {OWNED: "yes", CONFLICT: "no", UNESTABLISHED: "unresolved"}[
                predicted]
            if truth == "unresolved":
                stats[name]["ambiguous_truth"] += 1
                continue
            if truth == "yes":
                stats[name]["true_owned_accepted" if label == "yes"
                            else "true_owned_rejected"] += 1
                if label != "yes":
                    misses[name].append((cid, "true owned rejected", label))
            else:
                stats[name]["cross_opportunity_rejected" if label == "no"
                            else "cross_opportunity_accepted"] += 1
                if label != "no":
                    misses[name].append((cid, "cross-opportunity ACCEPTED", label))

    print("\n=============== OWNERSHIP, by strategy ===============")
    for name in ("O1", "O2", "O3"):
        s = stats[name]
        print(f"  {name}: true-owned accepted {s['true_owned_accepted']}, "
              f"rejected {s['true_owned_rejected']} | "
              f"cross-opportunity rejected {s['cross_opportunity_rejected']}, "
              f"accepted {s['cross_opportunity_accepted']} | "
              f"ambiguous {s['ambiguous_truth']}")
        for cid, what, got in misses[name]:
            print(f"       MISS {cid}: {what} (predicted {got})")

    print("\n=============== FUNDABILITY ===============")
    for label, getter in (
        ("V1 semantic prompt", lambda c: v1.get(c)),
        ("O1 combined call", lambda c: {"yes": "accept", "no": "reject"}.get(
            (o1_rows.get(c) or {}).get("fundable"))),
    ):
        tp = fn = tn = fp = unres = 0
        for cid, candidate in candidates.items():
            verdict = getter(cid)
            if verdict is None:
                continue
            truth = candidate["fundable"]
            if truth == "unresolved":
                unres += 1
            elif truth == "yes":
                tp += verdict == "accept"
                fn += verdict != "accept"
            else:
                tn += verdict == "reject"
                fp += verdict != "reject"
        print(f"  {label:20} TP={tp} FN={fn} TN={tn} FP={fp} unresolved={unres}")

    print("\n=============== COMBINED GATE (ownership AND fundability) ===============")
    for name in ("O1", "O2", "O3"):
        right = fabrications = lost = skipped = 0
        for cid, candidate in candidates.items():
            o1 = o1_rows.get(cid, {})
            if name == "O1":
                own = _o1_ownership(o1)
                fund = {"yes": "accept", "no": "reject"}.get(o1.get("fundable"))
            else:
                own = (ownership_o2(candidate)["ownership"] if name == "O2"
                       else strategy_o3(
                           candidate,
                           classifier_owned=(o1.get("owned") == "yes") if o1 else None,
                       )["ownership"])
                fund = v1.get(cid)
            if fund is None or "unresolved" in (candidate["owned"],
                                                candidate["fundable"]):
                skipped += 1
                continue
            publishes = own == OWNED and fund == "accept"
            should = candidate["owned"] == "yes" and candidate["fundable"] == "yes"
            if publishes and not should:
                fabrications += 1
            elif not publishes and should:
                lost += 1
            elif publishes:
                right += 1
        print(f"  {name}: published correctly {right} | "
              f"FABRICATIONS {fabrications} | GENUINE CHILDREN LOST {lost} | "
              f"skipped(unresolved/no-verdict) {skipped}")
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.score_only:
        run(args.out)
    score(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
