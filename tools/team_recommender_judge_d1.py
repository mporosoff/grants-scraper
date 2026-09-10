"""Bounded D1 development questions; data-only, frozen registry, same ledger."""
import json

from tools.offline_ai import request_body
from tools.offline_spend import encoded, Deferred

KINDS = {"source_suitability", "aspect_person", "call_person", "group_usefulness", "comparison", "explanation_audit"}
REASONS = ["specific", "transfer", "interest", "generic", "missing", "irrelevant", "coherent", "broad", "nonresearch", "overlap", "unsupported", "tie"]
PURPOSE_KINDS = {
    "d1-source": {"source_suitability"}, "d1-control": {"source_suitability", "call_person"},
    "d1-aspect": {"aspect_person"}, "d1-call": {"call_person"}, "d1-group": {"group_usefulness"},
    "d1-comparison": {"comparison"}, "d1-swap": {"comparison"}, "d1-explanation": {"explanation_audit"},
}
PURPOSE_KINDS.update({"d2-call": {"call_person"}, "d2-group": {"group_usefulness"},
    "d2-comparison": {"comparison"}, "d2-swap": {"comparison"}, "d2-explanation": {"explanation_audit"}})
PURPOSE_KINDS.update({"d3-call": {"call_person"}, "d3-group": {"group_usefulness"},
    "d3-comparison": {"comparison"}, "d3-swap": {"comparison"}, "d3-explanation": {"explanation_audit"}})


def labels(kind):
    if kind == "source_suitability":
        return {"coherent", "broad-unselected", "nonresearch", "insufficient-information"}
    if kind == "comparison":
        return {"A", "B", "tie", "unresolved"}
    if kind == "explanation_audit":
        return {"faithful", "unsupported", "insufficient-information"}
    return {"strong", "plausible", "unrelated", "insufficient-information"}


def contract(request, settings, *, enforce_dispatch_bound=True):
    from tools import team_recommender_executor as e
    e.exact_keys(request, ["protocol", "scope_id", "purpose", "source_evidence", "aspects", "items"])
    if request["protocol"] not in {"D1", "D1F"} or request["scope_id"] not in settings["development_ids"] or request["purpose"] not in PURPOSE_KINDS:
        raise ValueError("d1_outside_development_authority")
    if request["purpose"].startswith(("d2-", "d3-")) and request["protocol"] != "D1F" and enforce_dispatch_bound:
        raise ValueError("d2_uses_existing_finite_D1F_format")
    source = request["source_evidence"]
    if source["scope_id"] != request["scope_id"]:
        raise ValueError("source_scope_mismatch")
    source_refs = e.source_evidence(source)
    source_text = {p["id"]: p["text"] for p in source["passages"]}
    if any(len(ref)>16 or not ref.isascii() for ref in source_refs):
        raise ValueError("d1_compact_evidence_alias_required")
    aspects = request["aspects"]
    if not isinstance(aspects, list) or len(aspects) > 8:
        raise ValueError("bounded_d1_aspects")
    aspect_ids = set()
    for a in aspects:
        e.exact_keys(a, ["id", "text", "source_ref"])
        e.text(a["id"], 128); e.text(a["text"], 2000)
        if a["id"] in aspect_ids or a["source_ref"] not in source_text or a["text"] not in source_text[a["source_ref"]]:
            raise ValueError("d1_aspect_source_identity")
        aspect_ids.add(a["id"])
    items = request["items"]
    if not isinstance(items, list) or not 1 <= len(items) <= 3:
        raise ValueError("d1_compact_items_required")
    aliases, refs_by_item = {}, {}
    for item in items:
        e.exact_keys(item, ["item_id", "task_type", "profile_evidence", "candidates"], ["target_aspect", "explanation"])
        alias, kind = item["item_id"], item["task_type"]
        if alias not in {"i01", "i02", "i03"} or alias in aliases or kind not in PURPOSE_KINDS[request["purpose"]]:
            raise ValueError("d1_item_or_purpose_identity")
        if kind == "aspect_person":
            if item.get("target_aspect") not in aspect_ids:
                raise ValueError("d1_target_aspect_required")
        elif "target_aspect" in item:
            raise ValueError("d1_incorrect_aspect_target")
        if kind != "source_suitability" and not aspects:
            raise ValueError("d1_scientific_context_required")
        if kind == "explanation_audit":
            e.text(item.get("explanation"), 3500)
        elif "explanation" in item:
            raise ValueError("explanation_in_semantic_judgment")
        rows = item["profile_evidence"]
        if not isinstance(rows, list) or len(rows) > 32:
            raise ValueError("bounded_profile_passages_required")
        stripped = []
        for row in rows:
            e.exact_keys(row, ["id", "person_id", "claim_id", "revision", "text", "source_url", "label", "claim_type", "research_summary"])
            claim = next((c for c in settings["d1_profile_fields"].get(row["person_id"], {}).get("claims", []) if c["id"] == row["claim_id"]), None)
            if claim is None or row["label"] != claim["label"] or row["claim_type"] != claim["claim_type"] or row["research_summary"] != settings["d1_profile_fields"][row["person_id"]]["research_summary"]:
                raise ValueError("d1_existing_registry_fields_changed")
            stripped.append({k:v for k,v in row.items() if k not in {"label", "claim_type", "research_summary"}})
        refs, people = e.profile_evidence(stripped, settings)
        if any(len(ref)>16 or not ref.isascii() for ref in refs):
            raise ValueError("d1_compact_evidence_alias_required")
        if source_refs & refs:
            raise ValueError("d1_source_profile_reference_collision")
        candidates = item["candidates"]
        if kind == "comparison":
            e.exact_keys(candidates, ["A", "B"])
            if len(candidates["A"]) != len(candidates["B"]):
                raise ValueError("unequal_comparison_sizes")
            groups = list(candidates.values())
        else:
            groups = [candidates]
        for group in groups:
            if not isinstance(group, list) or len(group) != len(set(group)) or set(group) - people:
                raise ValueError("candidate_evidence_mismatch")
            lower, upper = (0, 0) if kind == "source_suitability" else ((1, 1) if kind in {"aspect_person", "call_person"} else (2, 4))
            if not lower <= len(group) <= upper:
                raise ValueError("d1_task_candidate_size")
        if people != set().union(*(set(g) for g in groups)):
            raise ValueError("d1_extraneous_candidate_evidence")
        aliases[alias] = kind; refs_by_item[alias] = source_refs | refs
    schema = {"type":"object", "additionalProperties":False, "required":["verdicts"], "properties":{
        "verdicts":{"type":"array", "minItems":len(items), "maxItems":len(items), "items":{
            "type":"object", "additionalProperties":False, "required":["item_id","verdict","evidence_ref","reason"],
            "properties":{"item_id":{"type":"string","enum":sorted(aliases)},
                "verdict":{"type":"string","enum":sorted(set().union(*(labels(k) for k in aliases.values())))},
                "evidence_ref":{"type":"string","enum":sorted(set().union(*refs_by_item.values()))},
                "reason":{"type":"string","minLength":1,"maxLength":60,"description":"Use printable ASCII characters only."}}}}}}
    data = {"source_evidence":source,"aspects":aspects,"items":items}
    prompt = (e.CONFIG/"judge-d1.md").read_text(encoding="utf-8")
    if request["protocol"] == "D1F":
        # Constrained enums survive the provider's schema projection. D1's
        # original free-text contract remains reconstructible for replay guards.
        schema["properties"]["verdicts"]["items"]["properties"]["reason"] = {"type":"string", "enum":REASONS}
        prompt = prompt[:prompt.index("Return exactly one verdict")] + "Return one verdict, one evidence reference and the most specific allowed reason code per item."
    body = request_body({"provider":"anthropic","model":settings["judge_model"]}, {"max_output_tokens":512},
        prompt, data, schema)
    body["thinking"] = {"type":"disabled"}
    bound = len(encoded(body)) + 1024
    if enforce_dispatch_bound and bound > 12000:
        raise Deferred("complete_evidence_exceeds_packet_bound")
    return body, bound, aliases, refs_by_item, schema
