"""Manual protected-main executor for hashed public experiment data only.

No recommender imports, runtime publication, source retrieval or arbitrary route.
The outer workflow persists a crash reservation before this module can dispatch.
"""
import argparse
from decimal import Decimal, ROUND_CEILING
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import time
import zipfile
import sys

import requests
from tools.offline_ai import request_body, response_value, validate_schema
from tools.offline_spend import atomic_json, encoded, identity, Deferred, ConfigurationFailure
from tools.team_recommender_budget import ExperimentLedger, AUTHORIZATION_ID

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/team_recommender_executor"
WORKFLOW = ".github/workflows/team-recommender-offline.yml"
REPOSITORY = "mporosoff/grants-scraper"
PREFIX = AUTHORIZATION_ID
PACKET_LIMIT = 8 * 1024 * 1024
STATE_LIMIT = 128 * 1024 * 1024
PURPOSES = {"source": 90, "individual": 90, "group": 90, "control": 30, "explanation": 30, "order-swap": 10}
# A later paid envelope never grants the legacy packet format new authority.
GENERIC_JUDGE_PURPOSES = frozenset(PURPOSES)
PURPOSES.update({"d1-source":12,"d1-call":130,"d1-aspect":20,"d1-group":40,
                 "d1-comparison":40,"d1-explanation":12,"d1-control":30,"d1-swap":4})
PURPOSES.update({"d2-call":80,"d2-group":70,"d2-comparison":20,"d2-explanation":6,"d2-swap":4})
PURPOSES.update({"d3-call":100,"d3-group":70,"d3-comparison":25,"d3-explanation":8,"d3-swap":4})
PURPOSES.update({"s3-primary":134,"s3-alternative":12,"s3-explanation":6,"s3-swap":6,"s3-control":6})
PURPOSES["post-audit"] = 34
KINDS = {"individual", "group", "comparison", "source_control", "explanation_audit"}
SCIENCE_LABELS = {"strong", "plausible", "unrelated", "insufficient-information"}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def policy():
    value = json.loads((CONFIG / "policy.json").read_bytes())
    for name, key in (("judge-prompt.md", "judge_prompt_sha256"), ("judge-output-schema.json", "judge_schema_sha256"),
                      ("initial-ledger.json", "initial_ledger_sha256"), ("judge-d1.md", "judge_d1_sha256"),
                      ("profile-fields-d1.json", "profile_fields_d1_sha256")):
        if sha((CONFIG / name).read_bytes()) != value[key]:
            raise ValueError("trusted_configuration_hash_mismatch")
    if value["authorization_id"] != AUTHORIZATION_ID or value["approved_stage"] != 2:
        raise ValueError("unapproved_experiment_stage")
    fields = json.loads((CONFIG / "profile-fields-d1.json").read_bytes())
    if fields["registry_generation"] != value["registry_generation"]:
        raise ValueError("d1_registry_generation_mismatch")
    value["d1_profile_fields"] = fields["people"]
    if 'stage3_inputs_sha256' in value:
        from tools.team_recommender_stage3_executor import inputs
        inputs(value)
    return value


def trusted_environment(*, contextual_job=None):
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    permitted_event = event_name == "workflow_dispatch"
    if event_name == "repository_dispatch" and contextual_job is not None:
        # Only the contextual entry points can opt into the existing Worker
        # credential's repository-dispatch route. Legacy packets/checks cannot.
        try:
            raw = Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes()
            if len(raw) > 128 * 1024:
                raise ValueError("event_envelope_bound")
            event = json.loads(raw)
            payload = event["client_payload"]
            supplied = payload["contextual_job"]
            permitted_event = (event.get("action") == "contextual-team-validation"
                and set(payload) == {"contextual_job"} and isinstance(supplied, str)
                and len(supplied.encode()) <= 1024 and json.loads(supplied) == contextual_job)
        except (KeyError, TypeError, ValueError, OSError):
            permitted_event = False
    if (os.environ.get("GITHUB_REPOSITORY") != REPOSITORY or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or not permitted_event
            or os.environ.get("GITHUB_WORKFLOW_REF") != REPOSITORY + "/" + WORKFLOW + "@refs/heads/main"
            or not re.fullmatch(r"[a-f0-9]{40}", os.environ.get("GITHUB_SHA", ""))
            or not re.fullmatch(r"[1-9][0-9]*", os.environ.get("GITHUB_RUN_ID", ""))
            or not re.fullmatch(r"[1-9][0-9]*", os.environ.get("GITHUB_RUN_ATTEMPT", ""))):
        raise ConfigurationFailure("protected_main_manual_execution_required")


def api(path):
    return subprocess.check_output(["gh", "api", "repos/" + REPOSITORY + "/" + path], timeout=60)


def bounded_response(response, maximum):
    if response.status_code != 200:
        response.close()
        raise ConfigurationFailure("http_" + str(response.status_code))
    try:
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > maximum:
                raise ValueError("bounded_response_exceeded")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        response.close()


def exact_keys(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError("unexpected_or_missing_packet_fields")


def text(value, maximum=12000):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > maximum:
        raise ValueError("invalid_bounded_text")
    return value


def source_evidence(value):
    exact_keys(value, ["scope_id", "passages", "limitations"])
    text(value["limitations"], 2000)
    if not isinstance(value["passages"], list) or not 1 <= len(value["passages"]) <= 10:
        raise ValueError("bounded_source_passages_required")
    refs = set()
    for passage in value["passages"]:
        exact_keys(passage, ["id", "text", "url", "locator", "sha256"])
        text(passage["id"], 128); text(passage["locator"], 500)
        if not re.fullmatch(r"https://[^\s/?#]+(?:[^\s]*)", passage["url"]):
            raise ValueError("public_https_source_required")
        if sha(text(passage["text"]).encode()) != passage["sha256"] or passage["id"] in refs:
            raise ValueError("source_span_identity_mismatch")
        refs.add(passage["id"])
    return refs


def profile_evidence(rows, settings):
    if not isinstance(rows, list) or len(rows) > 32:
        raise ValueError("bounded_profile_passages_required")
    refs, people = set(), set()
    for row in rows:
        exact_keys(row, ["id", "person_id", "claim_id", "revision", "text", "source_url"])
        text(row["id"], 128)
        claims = settings["profile_claims"].get(row["person_id"], [])
        if not any(c["claim_id"] == row["claim_id"] and c["revision"] == row["revision"]
                   and c["text"] == row["text"] and row["source_url"] in c["source_urls"] for c in claims):
            raise ValueError("profile_evidence_not_in_public_snapshot")
        if row["id"] in refs:
            raise ValueError("duplicate_evidence_reference")
        refs.add(row["id"]); people.add(row["person_id"])
    return refs, people


def judge_contract(request, settings):
    from tools.team_recommender_post_audit_executor import PROTOCOL as POST, contract as post_contract
    if request.get("protocol") == POST:
        return post_contract(request, settings)
    from tools.team_recommender_stage3_executor import PROTOCOL, judge_contract as stage3_contract
    if request.get('protocol') == PROTOCOL:
        return stage3_contract(request, settings)
    if request.get("protocol") in {"D1", "D1F"}:
        from tools.team_recommender_judge_d1 import contract
        return contract(request, settings)
    exact_keys(request, ["scope_id", "purpose", "source_evidence", "items"])
    if request["scope_id"] not in settings["development_ids"] or request["purpose"] not in GENERIC_JUDGE_PURPOSES:
        raise ValueError("judge_outside_development_authority")
    if request["source_evidence"]["scope_id"] != request["scope_id"]:
        raise ValueError("source_scope_mismatch")
    source_refs = source_evidence(request["source_evidence"])
    items = request["items"]
    if not isinstance(items, list) or not 1 <= len(items) <= 10:
        raise ValueError("bounded_judge_items_required")
    aliases, refs_by_item = {}, {}
    for item in items:
        exact_keys(item, ["item_id", "task_type", "profile_evidence", "candidates"], ["explanation"])
        alias, kind = item["item_id"], item["task_type"]
        if not re.fullmatch(r"i[0-9]{2}", alias) or alias in aliases or kind not in KINDS:
            raise ValueError("judge_item_identity")
        refs, people = profile_evidence(item["profile_evidence"], settings)
        aliases[alias] = kind; refs_by_item[alias] = source_refs | refs
        if kind == "explanation_audit":
            text(item.get("explanation"), 3500)
        elif "explanation" in item:
            raise ValueError("explanation_in_semantic_judgment")
        groups = list(item["candidates"].values()) if kind == "comparison" else [item["candidates"]]
        if kind == "comparison":
            exact_keys(item["candidates"], ["A", "B"])
            if len(groups[0]) != len(groups[1]):
                raise ValueError("unequal_comparison_sizes")
        for group in groups:
            if not isinstance(group, list) or len(group) > 4 or len(group) != len(set(group)) or set(group) - people:
                raise ValueError("candidate_evidence_mismatch")
            if kind != "source_control" and not group:
                raise ValueError("empty_candidate_is_not_a_judgment")
        if kind == "individual" and len(item["candidates"]) != 1:
            raise ValueError("individual_item_size")
    if ("explanation_audit" in aliases.values()) != (request["purpose"] == "explanation") or (
            request["purpose"] == "explanation" and set(aliases.values()) != {"explanation_audit"}):
        raise ValueError("separate_explanation_packet_required")
    prompt = (CONFIG / "judge-prompt.md").read_text(encoding="utf-8")
    schema = json.loads((CONFIG / "judge-output-schema.json").read_bytes())
    # Bind response IDs before generation; retain the independent response checks.
    props = schema["properties"]["verdicts"]["items"]["properties"]
    props["item_id"]["enum"] = sorted(aliases)
    props["evidence_ref"]["enum"] = sorted(set().union(*refs_by_item.values()))
    labels = set()
    for kind in aliases.values():
        labels.update({"A", "B", "tie", "unresolved"} if kind == "comparison" else (
            {"faithful", "unsupported", "insufficient-information"} if kind == "explanation_audit" else SCIENCE_LABELS))
    props["verdict"]["enum"] = sorted(labels)
    schema["properties"]["verdicts"].update(minItems=len(items), maxItems=len(items))
    data = {"source_evidence": request["source_evidence"], "items": items}
    body = request_body({"provider": "anthropic", "model": settings["judge_model"]}, {"max_output_tokens": 512}, prompt, data, schema)
    # Sonnet 5 otherwise spends the compact answer allowance on adaptive thinking.
    body["thinking"] = {"type": "disabled"}
    bound = len(encoded(body)) + 1024
    if bound > 12000:
        raise Deferred("complete_evidence_exceeds_packet_bound")
    return body, bound, aliases, refs_by_item, schema


def legacy_judge_key(request, settings):
    """Recognize paid pre-fix requests, never turn them into another attempt."""
    from tools.team_recommender_stage3_executor import PROTOCOL
    if request.get('protocol') in {PROTOCOL, 'post-audit-complete-v1'}:
        return None  # Complete held-out evidence is a distinct, fixed question.
    # D1 has substantively different trusted questions, fields and schema.
    # Its body identity is still irreversible in the SAME durable ledger.
    if request.get("protocol") in {"D1", "D1F"}:
        from tools.team_recommender_judge_d1 import contract
        counterpart = "D1" if request["protocol"] == "D1F" else "D1F"
        # This body is hashed for recovery detection, never dispatched. Only
        # the active format's contract decides whether its request fits.
        body = contract(dict(request, protocol=counterpart), settings, enforce_dispatch_bound=False)[0]
        return identity([AUTHORIZATION_ID, "development-judge", body])
    body = request_body({"provider": "anthropic", "model": settings["judge_model"]}, {"max_output_tokens": 512},
        (CONFIG / "judge-prompt.md").read_text(encoding="utf-8"),
        {"source_evidence": request["source_evidence"], "items": request["items"]},
        json.loads((CONFIG / "judge-output-schema.json").read_bytes()))
    return identity([AUTHORIZATION_ID, "development-judge", body])


def embedding_contract(request, settings):
    from tools.team_recommender_stage3_executor import REPRESENTATION, embedding_contract as stage3_contract
    if request.get('representation') == REPRESENTATION:
        return stage3_contract(request,settings)
    from tools.team_recommender_embeddings_d3 import is_d3, contract
    if is_d3(request):
        return contract(request, settings)
    exact_keys(request, ["input_role", "rows"], ["representation"])
    role, rows = request["input_role"], request["rows"]
    if role not in ("query", "document") or not isinstance(rows, list) or not 1 <= len(rows) <= 128:
        raise ValueError("bounded_embedding_batch_required")
    contextual = "representation" in request
    if contextual:
        from tools.team_recommender_context_d2 import VERSION, context_inventory
        if request["representation"] != VERSION or role != "document":
            raise ValueError("unapproved_context_representation")
        allowed_context = context_inventory(settings)
    ids = set()
    for row in rows:
        exact_keys(row, ["id", "owner", "text"])
        if sha(text(row["text"]).encode()) != row["id"] or row["id"] in ids:
            raise ValueError("embedding_text_identity")
        ids.add(row["id"])
        if role == "query" and row["owner"] not in settings["preparation_ids"]:
            raise ValueError("source_outside_preparation_scope")
        if contextual and allowed_context.get(row["owner"], {}).get(row["id"]) != row["text"]:
            raise ValueError("context_not_constructed_from_trusted_frozen_registry")
        if role == "document" and not contextual and not any(c["text"] == row["text"] for c in settings["profile_claims"].get(row["owner"], [])):
            raise ValueError("embedding_not_public_claim")
    body = {"model": settings["embedding_model"], "input": [r["text"] for r in rows],
            "input_type": role, "output_dimension": settings["dimension"], "output_dtype": "float", "truncation": False}
    return body, len(encoded(body)) + 1024


def embedding_items(request):
    from tools.team_recommender_embeddings_d3 import is_d3, paid_items
    if is_d3(request):
        return paid_items(request)
    return [request['input_role'] + ':' + row['id'] for row in request['rows']]


def validate_packet(packet, settings):
    exact_keys(packet, ["schema_version", "authorization_id", "registry_generation", "operation", "requests"])
    from tools.team_recommender_post_audit_executor import PROTOCOL as POST, REGISTRY
    post = packet['operation'] == 'development-judge' and isinstance(packet['requests'], list) and bool(packet['requests']) and all(isinstance(r, dict) and r.get('protocol') == POST for r in packet['requests'])
    registry = REGISTRY if post else settings['registry_generation']
    if packet["schema_version"] != 1 or packet["authorization_id"] != AUTHORIZATION_ID or packet["registry_generation"] != registry:
        raise ValueError("packet_authorization_or_registry_mismatch")
    if packet["operation"] not in ("embeddings", "development-judge") or not isinstance(packet["requests"], list):
        raise ValueError("unapproved_operation")
    maximum = 80 if packet["operation"] == "embeddings" else 350
    if not 1 <= len(packet["requests"]) <= maximum:
        raise ValueError("bounded_request_inventory_required")
    seen = set()
    for request in packet["requests"]:
        (embedding_contract if packet["operation"] == "embeddings" else judge_contract)(request, settings)
        key = identity(request)
        if key in seen:
            raise ValueError("duplicate_request_inventory")
        seen.add(key)


def unpack_state(raw, destination):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = [info for info in archive.infolist() if not info.is_dir()]
        if len(files) > 1500 or sum(info.file_size for info in files) > STATE_LIMIT:
            raise ValueError("checkpoint_size_exceeded")
        seen = set()
        for info in files:
            name = info.filename
            if (not re.fullmatch(r"(ledger|checkpoint)\.json|cache/[a-f0-9]{64}\.json|receipts/[a-f0-9]{32}\.json", name)
                    or name in seen or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError("unsafe_checkpoint_member")
            seen.add(name)
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
    checkpoint = json.loads((destination / "checkpoint.json").read_bytes())
    if checkpoint["authorization_id"] != AUTHORIZATION_ID:
        raise ValueError("checkpoint_authorization_mismatch")
    actual = {p.relative_to(destination).as_posix(): sha(p.read_bytes()) for p in destination.rglob("*.json") if p.name != "checkpoint.json"}
    if actual != checkpoint["files"]:
        raise ValueError("checkpoint_content_hash_mismatch")
    ExperimentLedger(destination / "ledger.json")


def restore(destination, settings, api_call=api):
    artifacts = []
    for page in range(1, 101):
        rows = json.loads(api_call(f"actions/artifacts?per_page=100&page={page}"))["artifacts"]
        artifacts.extend(a for a in rows if a["name"].startswith(PREFIX + "-"))
        if len(rows) < 100:
            break
    else:
        raise Deferred("checkpoint_history_bound")
    from tools.team_recommender_checkpoint import latest_reservation, recover_known_charge
    reservations = [a for a in artifacts if "-reservation-" in a["name"]]
    if reservations:
        latest = latest_reservation(reservations)
        states = [a for a in artifacts if a["name"] == latest["name"].replace("-reservation-", "-state-")]
        if len(states) != 1 or states[0]["expired"]:
            raise Deferred("latest_authoritative_checkpoint_missing")
        run = json.loads(api_call("actions/runs/" + str(states[0]["workflow_run"]["id"])))
        if (run["path"] != WORKFLOW or run["head_branch"] != "main"
                or run["event"] not in {"workflow_dispatch", "repository_dispatch"}):
            raise ValueError("untrusted_checkpoint_run")
        raw = api_call("actions/artifacts/" + str(states[0]["id"]) + "/zip")
        if len(raw) > STATE_LIMIT:
            raise ValueError("checkpoint_archive_too_large")
        unpack_state(raw, destination)
        recover_known_charge(destination, latest, artifacts, api_call, sys.modules[__name__])
    else:
        runs = json.loads(api_call("actions/workflows/team-recommender-offline.yml/runs?branch=main&per_page=100"))["workflow_runs"]
        if any(str(run["id"]) != os.environ["GITHUB_RUN_ID"] for run in runs):
            raise Deferred("prior_run_without_spend_checkpoint")
        # This is the exact existing empty ledger, never a newly granted allowance.
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "ledger.json").write_bytes((CONFIG / "initial-ledger.json").read_bytes())
    return ExperimentLedger(destination / "ledger.json")


def checkpoint(destination):
    files = {p.relative_to(destination).as_posix(): sha(p.read_bytes()) for p in destination.rglob("*.json") if p.name != "checkpoint.json"}
    atomic_json(destination / "checkpoint.json", {"authorization_id": AUTHORIZATION_ID, "run_id": os.environ["GITHUB_RUN_ID"],
                "attempt": os.environ["GITHUB_RUN_ATTEMPT"], "code_sha": os.environ["GITHUB_SHA"], "files": files})


def prepare(destination, packet_path, reservation, commit, packet_hash):
    trusted_environment(); settings = policy()
    if not re.fullmatch(r"[a-f0-9]{40}", commit) or not re.fullmatch(r"[a-f0-9]{64}", packet_hash):
        raise ValueError("invalid_packet_pointer")
    url = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/docs/team-recommender/packets/{packet_hash}.json"
    raw = bounded_response(requests.get(url, timeout=60, stream=True, allow_redirects=False), PACKET_LIMIT)
    if sha(raw) != packet_hash:
        raise ValueError("packet_hash_mismatch")
    packet = json.loads(raw); validate_packet(packet, settings)
    ledger = restore(destination, settings)
    packet_path.write_bytes(raw)
    checkpoint(destination)
    atomic_json(reservation, {"authorization_id": AUTHORIZATION_ID, "run_id": os.environ["GITHUB_RUN_ID"],
                "attempt": os.environ["GITHUB_RUN_ATTEMPT"], "code_sha": os.environ["GITHUB_SHA"],
                "packet_commit": commit, "packet_sha256": packet_hash, "prior_ledger_sha256": sha(ledger.path.read_bytes()),
                "maximum_logical_spend_usd": 10, "stage2_cumulative_usd": 6})
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write("operation=" + packet["operation"] + "\n")
    print(json.dumps({"operation": packet["operation"], "requests": len(packet["requests"]),
                      "charged_microusd": sum(r["charged_microusd"] for r in ledger.read()["requests"])}))


def result_value(operation, payload, request, contract, settings):
    if payload.get("model") != contract[0]["model"]:
        raise ConfigurationFailure("unexpected_returned_model")
    from tools.team_recommender_embeddings_d3 import is_d3, result
    if operation == 'embeddings' and is_d3(request):
        return result(payload, request)
    if operation == "development-judge":
        _, _, aliases, refs, schema = contract
        value = validate_schema(response_value("anthropic", payload), schema)
        if len(value["verdicts"]) != len(aliases) or {v["item_id"] for v in value["verdicts"]} != set(aliases):
            raise ValueError("incomplete_or_duplicate_verdicts")
        for verdict in value["verdicts"]:
            kind = aliases[verdict["item_id"]]
            if request.get("protocol") in {"D1", "D1F", "S3-E2-complete-v1", "post-audit-complete-v1"}:
                from tools.team_recommender_judge_d1 import labels as d1_labels
                labels = d1_labels(kind)
                if not re.fullmatch(r"[ -~]{1,60}", verdict["reason"]):
                    raise ValueError("d1_reason_outside_compact_contract")
            else:
                labels = {"A", "B", "tie", "unresolved"} if kind == "comparison" else (
                    {"faithful", "unsupported", "insufficient-information"} if kind == "explanation_audit" else SCIENCE_LABELS)
            if verdict["verdict"] not in labels or verdict["evidence_ref"] not in refs[verdict["item_id"]]:
                raise ValueError("verdict_or_evidence_ref_mismatch")
        return value
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) != len(request["rows"]):
        raise ValueError("embedding_response_count")
    if sorted(r.get("index") for r in rows) != list(range(len(rows))):
        raise ValueError("embedding_response_indices")
    output = []
    for row in sorted(rows, key=lambda r: r["index"]):
        vector = row.get("embedding")
        if not isinstance(vector, list) or len(vector) != 1024 or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
            raise ValueError("embedding_response_shape_or_finite")
        if sum(v*v for v in vector) <= 0:
            raise ValueError("zero_embedding")
        output.append({"id": request["rows"][row["index"]]["id"], "embedding": vector})
    return {"input_role": request["input_role"], "rows": output}


def usage_cost(operation, payload, model='voyage-4-lite'):
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("missing_usage_receipt")
    fields = ["total_tokens"] if operation == "embeddings" else ["input_tokens", "output_tokens"]
    if any(type(usage.get(k)) is not int or usage[k] < 0 for k in fields):
        raise ValueError("invalid_usage_receipt")
    if operation == "embeddings":
        rate = {"voyage-4-lite": ".02", "voyage-4-large": ".12", "voyage-context-4": ".12"}.get(model)
        if rate is None:
            raise ConfigurationFailure('unpriced_embedding_model')
        charge = Decimal(usage["total_tokens"]) * Decimal(rate)
    else:
        optional = [usage.get("cache_read_input_tokens", 0), usage.get("cache_creation_input_tokens", 0)]
        if any(type(n) is not int or n < 0 for n in optional):
            raise ValueError("invalid_cache_usage")
        charge = Decimal(usage["input_tokens"])*2 + Decimal(usage["output_tokens"])*10 + Decimal(optional[0])*Decimal(".2") + Decimal(optional[1])*Decimal("2.5")
    return usage, int(charge.to_integral_value(rounding=ROUND_CEILING))


def execute(destination, packet_path, packet_hash, post=requests.post):
    trusted_environment(); settings = policy()
    raw = packet_path.read_bytes()
    if sha(raw) != packet_hash:
        raise ValueError("dispatch_packet_changed")
    packet = json.loads(raw); validate_packet(packet, settings)
    operation = packet["operation"]; provider = "voyage" if operation == "embeddings" else "anthropic"
    model = settings["embedding_model" if provider == "voyage" else "judge_model"]
    secret = os.environ.get("VOYAGE_API_KEY" if provider == "voyage" else "ANTHROPIC_API_KEY")
    ledger = ExperimentLedger(destination / "ledger.json")
    # Inspect the whole restored packet before any new reservation. A legacy
    # recovery item at the end must not permit earlier new paid dispatches.
    if operation == "development-judge":
        restored_keys = {row["key"] for row in ledger.read()["requests"]}
        if any(legacy_judge_key(request, settings) in restored_keys for request in packet["requests"]):
            raise Deferred("prior_judge_protocol_request_requires_recovery_not_replay")
    if not secret:
        raise ConfigurationFailure("missing_provider_step_credential")
    from tools.team_recommender_items import preflight, judge_items
    preflight(packet, settings, ledger)
    deadline = time.monotonic() + 2700
    for request in packet["requests"]:
        if time.monotonic() >= deadline:
            raise Deferred("bounded_run_deadline")
        contract = (embedding_contract if provider == "voyage" else judge_contract)(request, settings)
        body, bound = contract[:2]
        model = body['model']
        key = identity([AUTHORIZATION_ID, operation, body])
        if operation == "development-judge":
            previous_key = legacy_judge_key(request, settings)
            if any(r["key"] == previous_key for r in ledger.read()["requests"]):
                raise Deferred("prior_judge_protocol_request_requires_recovery_not_replay")
        cache = destination / "cache" / (key + ".json")
        if cache.exists():
            retained = json.loads(cache.read_bytes())
            exact_keys(retained, ["key", "body_sha256", "model", "value", "request_id"])
            if retained["key"] != key or retained["body_sha256"] != identity(body) or retained["model"] != model:
                raise ValueError("exact_cache_identity_mismatch")
            prior = [r for r in ledger.read()["requests"] if r["key"] == key]
            if len(prior) != 1 or prior[0]["id"] != retained["request_id"] or prior[0]["status"] != "valid":
                raise Deferred("cache_without_exact_valid_reconciliation_requires_recovery")
            value = retained["value"]
            if operation == "embeddings":
                from tools.team_recommender_embeddings_d3 import is_d3, validate_value
                if is_d3(request):
                    validate_value(value, request)
                    ledger.event(kind="exact_cache_hit", key=key)
                    continue
                exact_keys(value, ["input_role", "rows"])
                if value["input_role"] != request["input_role"] or len(value["rows"]) != len(request["rows"]):
                    raise ValueError("cached_embedding_contract_mismatch")
                data = []
                for index, row in enumerate(value["rows"]):
                    exact_keys(row, ["id", "embedding"])
                    if row["id"] != request["rows"][index]["id"]:
                        raise ValueError("cached_embedding_identity_mismatch")
                    data.append({"index": index, "embedding": row["embedding"]})
                payload = {"model": model, "data": data}
            else:
                payload = {"model": model, "stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(value)}]}
            result_value(operation, payload, request, contract, settings)
            ledger.event(kind="exact_cache_hit", key=key)
            continue
        prior = [r for r in ledger.read()["requests"] if r["key"] == key]
        if prior:
            raise Deferred("cacheless_completed_or_uncertain_request_requires_recovery")
        attempt = 1
        row_inputs = embedding_items(request) if provider == "voyage" else []
        amount = ((bound*3+24)//25 if model in {'voyage-4-large','voyage-context-4'} else (bound+49)//50) if provider == "voyage" else (bound*5+1)//2 + 5120
        from tools.team_recommender_embeddings_d3 import is_d3, endpoint
        embedding_purpose = ('d3-query-format' if 'query_format' in request else 'd3-embedding') if is_d3(request) else ('d2-context' if request.get('representation') == 'D2-context-v1' else 'embedding')
        from tools.team_recommender_stage3_executor import is_stage3
        stage = 3 if is_stage3(request) else 2
        if stage == 3 and provider == 'voyage': embedding_purpose = 's3-embedding'
        token = ledger.reserve_experiment(provider, model, stage, key, amount, attempt, trusted_route=True, approved_stage=stage,
                    input_tokens=bound, output_tokens=0 if provider == "voyage" else 512,
                    execution_metadata={"packet_sha256": packet_hash, "body_sha256": identity(body),
                        "purpose": request.get("purpose", embedding_purpose), "code_sha": os.environ["GITHUB_SHA"], "row_inputs": row_inputs,
                        "judge_items": judge_items(request) if provider == "anthropic" else []},
                    purpose_limit=PURPOSES[request["purpose"]] if provider == "anthropic" else None)
        receipt = {"request_id": token, "key": key, "model": model, "reserved_microusd": amount,
                   "packet_sha256": packet_hash, "attempt": attempt, "code_sha": os.environ["GITHUB_SHA"]}
        try:
            url = "https://api.voyageai.com/v1/embeddings" if provider == "voyage" else "https://api.anthropic.com/v1/messages"
            if provider == 'voyage' and is_d3(request):
                url = endpoint(request)
            headers = {"Content-Type": "application/json", "User-Agent": "FundingFinder-TeamExperiment/1.0"}
            headers.update({"Authorization": "Bearer " + secret} if provider == "voyage" else {"x-api-key": secret, "anthropic-version": "2023-06-01"})
            response = post(url, headers=headers, json=body, timeout=120, allow_redirects=False, stream=True)
            receipt["http_status"] = response.status_code
            payload = json.loads(bounded_response(response, PACKET_LIMIT))
            usage, charge = usage_cost(operation, payload, model)
            receipt.update(usage=usage, charged_microusd=charge, returned_model=payload.get("model"))
            value = result_value(operation, payload, request, contract, settings)
            ledger.reconcile(token, cost_usd=Decimal(charge)/1000000, usage=usage, status="valid")
            atomic_json(cache, {"key": key, "body_sha256": identity(body), "model": model, "value": value, "request_id": token})
            receipt["status"] = "valid"
        except (ValueError, KeyError, TypeError, requests.RequestException, Deferred) as error:
            receipt.update(status="failed", error_type=type(error).__name__)
            current_row = next(r for r in ledger.read()["requests"] if r["id"] == token)
            if "charged_microusd" in receipt and current_row["status"] == "reserved_unknown":
                ledger.reconcile(token, cost_usd=Decimal(receipt["charged_microusd"])/1000000, usage=receipt["usage"], status="failed")
            if isinstance(error, ConfigurationFailure):
                ledger.block(provider, "provider_configuration_stop")
            # No automatic semantic/format rerun; failed receipts and uncertainty survive.
            with ledger.locked():
                state = ledger.read(); row = next(r for r in state["requests"] if r["id"] == token)
                row["terminal"] = True; atomic_json(ledger.path, state)
            raise
        finally:
            atomic_json(destination / "receipts" / (token + ".json"), receipt)
            checkpoint(destination)
    checkpoint(destination)
    print(json.dumps({"status": "complete", "requests": len(packet["requests"]),
                      "cumulative_microusd": sum(r["charged_microusd"] for r in ledger.read()["requests"])}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "execute"])
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--packet-sha256", required=True)
    parser.add_argument("--packet-commit")
    parser.add_argument("--reservation", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.state, args.packet, args.reservation, args.packet_commit, args.packet_sha256)
    else:
        execute(args.state, args.packet, args.packet_sha256)


if __name__ == "__main__":
    main()
