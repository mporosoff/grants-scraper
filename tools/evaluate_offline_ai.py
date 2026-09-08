"""Finite protected evaluation. Never mutates production config or catalog."""
import argparse
import inspect
import json
import os
from pathlib import Path
import time
from unittest.mock import patch
import requests

from tools.offline_ai import Client, Ledger, Deferred, ConfigurationFailure, Refusal, atomic_json, config, identity
from tools.offline_team_contract import schemas

TASK = "economical-ai-20260908"


def evaluation_contract():
    from scripts import build_opportunity_teams as t
    settings = config()
    return identity({"routes": settings["routes"], "stages": settings["stages"],
        "prompts": [t.DECOMPOSE, t.ADJUDICATE, t.VERIFY],
        "validators": [inspect.getsource(f) for f in (t.validate_roles, t.validate_edges, t.validate_response, t.assemble)],
        "schemas": schemas(), "frozen": json.loads(Path("evaluation/offline_team_frozen.json").read_bytes())})


def team_case(client, route_name, case):
    from scripts import build_opportunity_teams as t
    settings = config()
    route = settings["routes"][route_name if route_name != "luna-sonnet-verifier" else "luna"]
    scope = case["scope"]
    claims = {r["claim_id"]: r for r in case["claims"]}
    output = {"scope_id": scope["id"], "holdout": case["holdout"], "state": "unassessed", "stages": {}}
    def stage(name, prompt, data):
        actual = settings["routes"]["sonnet"] if route_name == "luna-sonnet-verifier" and name == "verification" else route
        stage_config = settings["stages"][name]
        # The baseline preserves its prior 8k ceiling; it is a ceiling, not billed usage.
        if actual["provider"] == "anthropic":
            stage_config = stage_config | {"max_output_tokens": 8000}
        value = client.json(actual, name, prompt, data, schemas()[name],
                            lambda value: t.validate_response(prompt, data, value), stage_config=stage_config)
        output["stages"][name] = value
        return value
    try:
        decomposition = stage("decomposition", t.DECOMPOSE, {"scope": scope["text"],
            "record_type": scope["record_type"], "source_fingerprint": scope["source_fingerprint"]})
        if not decomposition["specific"]:
            output["state"] = "not_specific"
        else:
            # The retrieval snapshot is frozen and identical across all models.
            payload = {"scope": scope["text"], "source_fingerprint": scope["source_fingerprint"],
                "objective": decomposition["objective"], "roles": decomposition["roles"],
                "claims": [{k: row[k] for k in ("claim_id", "revision", "material_hash", "researcher_id",
                                             "label", "evidence", "source_url")} for row in claims.values()]}
            adjudication = stage("adjudication", t.ADJUDICATE, payload)
            verification = stage("verification", t.VERIFY, payload | {"proposed_edges": adjudication["edges"]})
            proposal = t.assemble(scope, decomposition, verification["edges"], claims, "frozen-evaluation") if verification["suitable_for_team"] else None
            output["state"] = "unsuitable_scope" if not verification["suitable_for_team"] else "proposed" if proposal else "insufficient_evidence"
            output["proposal"] = proposal
    except (ValueError, RuntimeError, KeyError, TypeError, requests.RequestException) as error:
        output.update(state="deferred" if isinstance(error, Deferred) else "provider_refusal" if isinstance(error, Refusal) else "invalid_or_failed",
                      error_type=type(error).__name__)
    return output


def teams(client, destination, route):
    frozen = json.loads(Path("evaluation/offline_team_frozen.json").read_bytes())
    rows = []
    for case in frozen["cases"]:
        path = destination / f"team-{route}-{identity(case)}.json"
        if path.exists():
            row = json.loads(path.read_bytes())
            if (row.get("case_hash") != identity(case) or row.get("route") != route
                    or row.get("evaluation_contract") != evaluation_contract()):
                raise ValueError("evaluation_checkpoint_mismatch")
        else:
            row = team_case(client, route, case) | {"case_hash": identity(case), "route": route,
                                                    "evaluation_contract": evaluation_contract()}
            atomic_json(path, row)
        rows.append(row)
    completed = [r for r in rows if r["state"] in {"proposed", "insufficient_evidence", "not_specific", "unsuitable_scope"}]
    scope_correct = sum((r["state"] in {"not_specific", "unsuitable_scope"}) == (c["annotations"]["expected_scope"] == "reject")
                        for r, c in zip(rows, frozen["cases"]) if r in completed)
    summary = {"route": route, "frozen_sha256": identity(frozen), "total": len(rows), "completed": len(completed),
        "scope_correct": scope_correct, "proposed": sum(r["state"] == "proposed" for r in rows),
        "decision": "pending_independent_evidence_review", "acceptance": frozen["acceptance"],
        "limitation": frozen["retrieval_contract"]}
    atomic_json(destination / f"team-{route}-summary.json", summary)
    return summary


def cov4(client, destination):
    from scripts import subtopic_cov4 as gate
    from tools import run_cov4_validation as harness
    from tools.run_cov4_ownership import load_candidates
    population = load_candidates()
    frozen = json.loads(Path("evaluation/offline_cov4_frozen.json").read_bytes())
    if identity(population) != frozen["population_hash"] or identity(gate.PROMPT) != frozen["prompt_hash"]:
        raise ValueError("frozen_cov4_dependencies_changed")
    route = config()["routes"]["luna"]
    def classify(candidate, **_):
        try:
            def validate(value):
                if (not isinstance(value, dict) or set(value) != {"fundable", "owned", "reason"}
                        or value["fundable"] not in {"yes", "no"} or value["owned"] not in {"yes", "no", "unresolved"}
                        or not isinstance(value["reason"], str)):
                    raise ValueError("invalid_cov4_shape")
                return value
            value = client.json(route, "cov4", gate.render_prompt(candidate), {}, schemas()["cov4"], validate)
            return {"fundability": gate.ACCEPT if value["fundable"] == "yes" else gate.REJECT,
                "classifier_owned": value["owned"], "reason": value["reason"], "error": None,
                "detail": None, "api_request": True, "usage_reported": False, "usage": {}}
        except (ValueError, RuntimeError, TypeError, KeyError, requests.RequestException) as error:
            return gate._unresolved(type(error).__name__)
    # Same production ownership/provenance guards, only the classifier transport
    # is injected. Frozen historical result files are never overwritten.
    with patch.object(gate, "classify_fundability", classify):
        report = harness.run(destination / "cov4-luna-rows.jsonl", live=False, candidates=population)
    report.update(model=route["model"], provider=route["provider"], reasoning=route["reasoning"],
                  classifier_transport="offline-ai-1", live=True)
    atomic_json(destination / "cov4-luna-summary.json", {"result": report, "frozen": frozen,
                "decision": "pending_independent_evidence_review"})
    return report


def preflight(client):
    def validate(value):
        if value != {"ready": True} or type(value.get("ready")) is not bool:
            raise ValueError("preflight_schema_mismatch")
        return value
    return client.json(config()["routes"]["luna"], "preflight", "Return the requested readiness object.",
                       {"ready": True}, schemas()["preflight"], validate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["preflight", "teams-sonnet", "teams-luna", "teams-luna-sonnet-verifier", "teams-mini", "cov4", "stability", "replay"])
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    args.state.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(args.state / "ledger.json", TASK, config()["budgets_usd"]["evaluation"], max_requests=config()["max_requests"])
    client = Client(ledger, args.state / "cache", deadline=time.monotonic() + 2400)
    marker = args.state / (args.phase + "-completed.json")
    contract = evaluation_contract()
    result = None
    try:
        if marker.exists():
            result = json.loads(marker.read_bytes())
            if result.get("evaluation_contract") != contract:
                raise ValueError("evaluation_contract_changed; retained evidence is historical")
            result = result["result"]
        elif args.phase == "preflight":
            try:
                result = {"phase": args.phase, "result": preflight(client), "status": "supported"}
            except (ValueError, RuntimeError, requests.RequestException) as error:
                result = {"phase": args.phase, "status": "unavailable_or_invalid", "error_type": type(error).__name__}
        elif args.phase.startswith("teams-"):
            result = teams(client, args.state, args.phase[6:])
        elif args.phase == "cov4":
            result = cov4(client, args.state)
        elif args.phase == "stability":
            frozen = json.loads(Path("evaluation/offline_team_frozen.json").read_bytes())
            repeated = Client(ledger, args.state / "stability-cache", deadline=client.deadline)
            result = {route: [team_case(repeated, route, case) for case in frozen["cases"]
                             if case["scope"]["id"] in frozen["stability_scope_ids"]]
                      for route in ("sonnet", "luna")}
        else:
            # Only previously completed paid stage keys; selection is disabled.
            before = len(ledger.read()["requests"])
            def forbidden(*a, **kw):
                raise AssertionError("warm replay attempted a provider request")
            client.post = forbidden
            for path in sorted(args.state.glob("team-*-*.json")):
                if path.name.endswith("summary.json"):
                    continue
                row = json.loads(path.read_bytes())
                if row["state"] not in {"proposed", "not_specific", "unsuitable_scope", "insufficient_evidence"}:
                    continue
                frozen = json.loads(Path("evaluation/offline_team_frozen.json").read_bytes())
                case = next(c for c in frozen["cases"] if identity(c) == row["case_hash"])
                replay = team_case(client, row["route"], case)
                if replay["state"] != row["state"] or replay["stages"] != row["stages"]:
                    raise ValueError("warm_replay_changed_completed_decision")
            result = {"phase": args.phase, "new_provider_requests": len(ledger.read()["requests"]) - before}
        result = {"evaluation_contract": contract, "result": result}
        atomic_json(marker, result)
    finally:
        atomic_json(args.state / "usage-summary.json", ledger.summary())
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
                out.write("\n```json\n" + json.dumps({"result": result, "usage": ledger.summary()}, indent=2) + "\n```\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
