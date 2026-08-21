"""Run the pre-registered Cov4 prompt variants over both populations at R=1.

Usage (credential loaded in the same invocation; never printed or persisted):

    $env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY","User")
    python tools/run_cov4_prompts.py --out evaluation/cov4_prompt_runs.jsonl

**R = 1 is licensed by MEAS-3**, which measured per-span instability at 0.95% and
pooled per-call disagreement at 0.190% [0.034%, 1.071%]. Repeats would buy nothing
here: the failures MEAS-3 found were *stable*.

Populations:

* **A** — `evaluation/meas3_population.json`, the 105 candidates production emits
  today. Descriptive accept-rate; scored only where a committed truth label exists.
* **B** — `evaluation/cov4_challenge.json`, the balanced challenge set whose labels
  were committed **before** any variant ran.

Raw rows are written before any scoring, one per call, exactly as MEAS-3 did.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.cov4_prompts import VARIANTS, render          # noqa: E402

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MODEL = "claude-sonnet-5"
MAX_TOKENS = 1024

POP_A = Path("evaluation/meas3_population.json")
POP_B = Path("evaluation/cov4_challenge.json")
DEFAULT_OUT = Path("evaluation/cov4_prompt_runs.jsonl")


def _call(prompt, *, session, api_key, timeout=120):
    started = time.monotonic()
    response = session.post(
        API_URL,
        headers={"x-api-key": api_key, "anthropic-version": API_VERSION,
                 "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": MAX_TOKENS,
              # `thinking` omitted -> adaptive, same as MEAS-3.
              "messages": [{"role": "user", "content": prompt}]},
        timeout=timeout,
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code != 200:
        return {"status_code": response.status_code, "verdict": "error",
                "reason": f"http_{response.status_code}", "latency_ms": latency_ms}
    payload = response.json()
    text = "".join(b.get("text", "") for b in payload.get("content", [])
                   if b.get("type") == "text").strip()
    usage = payload.get("usage") or {}
    row = {
        "status_code": 200,
        "latency_ms": latency_ms,
        "usage_input": usage.get("input_tokens"),
        "usage_output": usage.get("output_tokens"),
        "thinking_tokens": (usage.get("output_tokens_details") or {}).get(
            "thinking_tokens"),
        "raw": text[:400],
    }
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


def run(out_path=DEFAULT_OUT, variants=None, populations=("A", "B")):
    import requests

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is not set in this process.")
    variants = list(variants or VARIANTS)
    pops = {}
    if "A" in populations:
        pops["A"] = json.loads(POP_A.read_text(encoding="utf-8"))["candidates"]
    if "B" in populations:
        pops["B"] = json.loads(POP_B.read_text(encoding="utf-8"))["candidates"]

    session = requests.Session()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for variant in variants:
            for population, candidates in pops.items():
                for candidate in candidates:
                    row = _call(render(variant, candidate),
                                session=session, api_key=api_key)
                    row.update(
                        variant=variant,
                        population=population,
                        candidate_id=candidate["candidate_id"],
                        parent_opportunity_id=candidate["parent_opportunity_id"],
                        shape=candidate.get("shape"),
                        truth_label=candidate.get("truth_label"),
                    )
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    written += 1
                print(f"  {variant} / population {population}: "
                      f"{len(candidates)} calls done ({written} total)", flush=True)
    return {"calls": written, "variants": variants, "out": str(out_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--variant", action="append", dest="variants")
    parser.add_argument("--population", action="append", dest="populations")
    args = parser.parse_args(argv)
    summary = run(args.out, args.variants, tuple(args.populations or ("A", "B")))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
