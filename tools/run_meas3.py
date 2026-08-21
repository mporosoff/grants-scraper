"""MEAS-3 — classifier repeatability over the frozen candidate population.

Usage (the credential must be loaded in the same process; never printed or logged):

    $env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY","User")
    python tools/run_meas3.py --repeats 5 --out evaluation/meas3_runs.jsonl

**What this measures.** Not accuracy. Whether `claude-sonnet-5` gives the *same*
verdict for the *same* frozen input across independent calls, which is the
precondition for Cov4 being a deterministic engineering gate at all (§11 caveat 2:
1 of 62 byte-identical spans flipped, a 1.6% rate whose 95% CI is [0.29%, 8.59%] and
therefore straddles the 0.9% signal it must resolve).

**Every raw verdict is written before anything is aggregated.** Majority-voting
before measuring would hide the quantity being measured.

**Configuration, frozen here and not tuned after seeing results** (§11):

* model `claude-sonnet-5`;
* **`thinking` omitted**, which is adaptive thinking — the measured difference
  between 88% and 54% span-level precision. `usage.output_tokens_details
  .thinking_tokens` is recorded per call so the setting is *verified* rather than
  assumed;
* temperature left at the API default;
* the prompt below, committed before the run.

**§11's own prompt is not in the repository** — that experiment's artifacts were
never committed, which is DEBT-9. This prompt is therefore new, written to the same
question §6.4b poses, and that is one more reason MEAS-3's numbers are not
comparable to §11's.

No dependency is added: the call is one POST through `requests`, which the project
already pins (DEC-15).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MODEL = "claude-sonnet-5"
MAX_TOKENS = 1024

DEFAULT_POPULATION = Path("evaluation/meas3_population.json")
DEFAULT_OUT = Path("evaluation/meas3_runs.jsonl")

#: Frozen before the run. §6.4b's question, per span, with the fail-closed
#: asymmetry stated so the model knows which way to err.
PROMPT = """\
You are judging one candidate heading extracted from a US federal funding notice.

The question is narrow: **is this candidate a fundable subdivision of the parent \
opportunity — something an applicant would actually apply against or select — \
rather than policy text, administrative or reporting requirements, eligibility \
prose, organizational structure, navigation, background material, or a heading \
belonging to a different opportunity?**

Parent opportunity: {parent_title}
Parent number: {parent_number}

Candidate label: {code}
Candidate title: {title}
Candidate excerpt:
\"\"\"
{excerpt}
\"\"\"

Answer with a single JSON object and nothing else:
{{"verdict": "accept" | "reject", "reason": "<one short sentence>"}}

Use "accept" only if it is a fundable subdivision an applicant selects. \
Use "reject" for anything administrative, procedural, organizational, or belonging \
to another opportunity. If the excerpt is too corrupted or truncated to judge the \
titled subject, say so in the reason and answer "reject"."""


def classify_once(candidate, *, session, api_key, timeout=120):
    """One independent call. Returns the raw row; never raises on a bad verdict."""
    body = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        # `thinking` deliberately omitted -> adaptive (§11's configuration).
        "messages": [{
            "role": "user",
            "content": PROMPT.format(
                parent_title=candidate.get("parent_title") or "",
                parent_number=candidate.get("parent_opportunity_number") or "",
                code=candidate.get("subtopic_code") or "",
                title=candidate.get("title") or "",
                excerpt=(candidate.get("excerpt") or "")[:4000],
            ),
        }],
    }
    started = time.monotonic()
    response = session.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        },
        json=body,
        timeout=timeout,
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    row = {
        "candidate_id": candidate["candidate_id"],
        "arm": candidate["arm"],
        "shape": candidate.get("shape"),
        "parent_opportunity_id": candidate["parent_opportunity_id"],
        "model": MODEL,
        "status_code": response.status_code,
        "latency_ms": latency_ms,
    }
    if response.status_code != 200:
        row.update(verdict="error", reason=f"http_{response.status_code}",
                   raw=response.text[:300])
        return row
    payload = response.json()
    text = "".join(
        block.get("text", "") for block in payload.get("content", [])
        if block.get("type") == "text"
    ).strip()
    usage = payload.get("usage") or {}
    row.update(
        usage_input=usage.get("input_tokens"),
        usage_output=usage.get("output_tokens"),
        thinking_tokens=(usage.get("output_tokens_details") or {}).get(
            "thinking_tokens"
        ),
        raw=text[:600],
    )
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        parsed = json.loads(text[start:end])
        verdict = str(parsed.get("verdict", "")).strip().lower()
        row["verdict"] = verdict if verdict in {"accept", "reject"} else "error"
        row["reason"] = str(parsed.get("reason", ""))[:300]
    except Exception:                       # noqa: BLE001 - malformed is a result
        row["verdict"] = "error"
        row["reason"] = "unparseable_response"
    return row


def run(population_path=DEFAULT_POPULATION, out_path=DEFAULT_OUT, repeats=5,
        arms=("A", "B"), limit=None):
    import requests

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set in this process. Load it in the same "
            "PowerShell invocation that launches this script."
        )
    population = json.loads(Path(population_path).read_text(encoding="utf-8"))
    candidates = [c for c in population["candidates"] if c["arm"] in arms]
    if limit:
        candidates = candidates[:limit]

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    written = 0
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for run_index in range(1, repeats + 1):
            for candidate in candidates:
                row = classify_once(candidate, session=session, api_key=api_key)
                row["run_index"] = run_index
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                written += 1
            print(f"  pass {run_index}/{repeats} complete ({written} calls)",
                  flush=True)
    return {"candidates": len(candidates), "repeats": repeats, "calls": written,
            "out": str(out_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run MEAS-3.")
    parser.add_argument("--population", type=Path, default=DEFAULT_POPULATION)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--arm", action="append", dest="arms")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    summary = run(args.population, args.out, args.repeats,
                  tuple(args.arms or ("A", "B")), args.limit)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
