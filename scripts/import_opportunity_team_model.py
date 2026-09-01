"""Import the reviewed opportunity-team calibration artifacts.

The spreadsheets and offline calibration JSON are import artifacts.  This
module reduces them to a canonical, reviewable repository configuration and a
compact browser projection.  The browser never loads the workbooks or the
larger calibration snapshots.

Usage::

    python -m scripts.import_opportunity_team_model \
      --faculty-model path/to/faculty_evidence_expansion_model.json \
      --gate-model path/to/team_explanation_gate_model.json \
      --config-out config/opportunity_team_model.json \
      --browser-out data/opportunity_teams.js
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata


SCHEMA_VERSION = 1
BROWSER_SCHEMA_VERSION = 1
SOURCE_ROSTER_COUNTS = {"total": 156, "rankable": 145, "unrankable": 11}
POOL_COUNTS = {"main": 118, "standby": 35, "unadmitted": 3}
MAX_BROWSER_BYTES = 220_000
VERSIONED_ASSETS = (
    "assets/app.css",
    "assets/app.js",
    "assets/search-retrieval.js",
    "assets/team-matcher.js",
    "assets/team-researchers.js",
    "assets/opportunity-team.js",
    "assets/opportunity-team-panel.js",
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def _split(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(";") if item.strip()]


def _pool_state(value: str) -> str:
    normalized = str(value or "").lower()
    if normalized.startswith("main pool"):
        return "main"
    if normalized.startswith("standby"):
        return "standby"
    return "unadmitted"


def _coverage_kind(value: str) -> str:
    normalized = str(value or "").lower()
    if normalized.startswith("gap"):
        return "gap"
    if "method transfer" in normalized or "direct/transfer" in normalized:
        return "method_transfer"
    if "adjacent" in normalized and "direct" not in normalized:
        return "adjacent"
    if "adjacent" in normalized:
        return "direct_and_adjacent"
    return "direct"


def _gate_state(value: str) -> str:
    normalized = str(value or "").lower()
    if normalized.startswith("pass"):
        return "pass"
    if normalized.startswith("fail"):
        return "fail"
    return "conditional"


def _faculty_ids(faculty: list[dict]) -> dict[str, str]:
    output: dict[str, str] = {}
    used: set[str] = set()
    for row in faculty:
        name = row["faculty_name"]
        identifier = _slug(name)
        if not identifier or identifier in used:
            raise ValueError(f"Duplicate or invalid faculty identifier for {name!r}")
        used.add(identifier)
        output[name] = identifier
    return output


def _audited_candidates(text: str, names: list[str], coverage: str) -> list[str]:
    if coverage == "gap":
        return []
    lowered = str(text or "").casefold()
    return [name for name in names if name.casefold() in lowered]


def _member_lookup(gate: dict) -> dict[tuple[str, str], dict]:
    return {
        (str(row["record_id"]), row["faculty_name"]): row
        for row in gate["members"]
    }


def _expansion_lookup(faculty_model: dict) -> dict[str, dict]:
    return {
        str(row["record_id"]): row
        for row in faculty_model["opportunities"]
    }


def build_config(faculty_model: dict, gate: dict, source_hashes: dict) -> dict:
    source_contract = faculty_model.get("source_contract") or {}
    summary = faculty_model.get("summary") or {}
    actual_source_counts = {
        "total": int(source_contract.get("faculty_count") or 0),
        "rankable": int(source_contract.get("faculty_count") or 0)
        - int((source_contract.get("claim_audit_status_counts") or {}).get(
            "unrankable — no official interests", 0
        )),
        "unrankable": int((source_contract.get("claim_audit_status_counts") or {}).get(
            "unrankable — no official interests", 0
        )),
    }
    actual_pool_counts = {
        "main": int(summary.get("main_pool_candidates") or 0),
        "standby": int(summary.get("standby") or 0),
        "unadmitted": int(summary.get("unadmitted") or 0),
    }
    if actual_source_counts != SOURCE_ROSTER_COUNTS:
        raise ValueError(f"Roster contract changed: {actual_source_counts}")
    if actual_pool_counts != POOL_COUNTS:
        raise ValueError(f"Pool contract changed: {actual_pool_counts}")

    faculty_ids = _faculty_ids(faculty_model["faculty"])
    term_by_id = {row["term_id"]: row for row in faculty_model["terms"]}
    faculty_rows = []
    for row in faculty_model["faculty"]:
        term_ids = list(row.get("retained_term_ids") or [])
        labels = list(row.get("retained_terms") or [])
        evidence = list(row.get("retained_evidence") or [])
        tiers = list(row.get("evidence_tiers") or [])
        if not (len(term_ids) == len(labels) == len(evidence) == len(tiers)):
            raise ValueError(f"Misaligned faculty evidence for {row['faculty_name']}")
        terms = []
        for term_id, label, phrase, tier in zip(term_ids, labels, evidence, tiers):
            definition = term_by_id.get(term_id) or {}
            if definition and label != definition.get("term"):
                raise ValueError(f"Term label mismatch for {term_id}")
            terms.append({
                "id": term_id,
                "label": label,
                "category": definition.get("category") or "",
                "type": definition.get("term_type") or "",
                "evidence": phrase,
                "evidence_tier": tier,
            })
        sources = list(dict.fromkeys(row.get("source_urls") or []))
        if not sources or not row.get("source_checked_date"):
            raise ValueError(f"Missing source provenance for {row['faculty_name']}")
        faculty_rows.append({
            "id": faculty_ids[row["faculty_name"]],
            "name": row["faculty_name"],
            "home_unit": row.get("home_unit") or "",
            "relationship": row.get("relationship") or "",
            "pool_state": _pool_state(row.get("decision") or ""),
            "claim_status": row.get("claim_audit_status") or "",
            "official_interests": list(row.get("official_interests") or []),
            "terms": terms,
            "source_urls": sources,
            "source_checked_date": row["source_checked_date"],
        })
    faculty_rows.sort(key=lambda item: (item["name"].casefold(), item["id"]))

    by_name = {row["name"]: row for row in faculty_rows}
    faculty_names = list(faculty_ids)
    expansion_by_id = _expansion_lookup(faculty_model)
    member_by_key = _member_lookup(gate)
    roles_by_record: dict[str, list[dict]] = {}
    for row in gate["roles"]:
        record_id = str(row["record_id"])
        coverage = _coverage_kind(row.get("audit_state") or "")
        candidates = _audited_candidates(
            row.get("selected_or_adjacent_faculty") or "",
            faculty_names,
            coverage,
        )
        accepted_terms = _split(row.get("accepted_terms") or "")
        graph_text = str(row.get("graph_candidates") or "").casefold()
        evidence_alternatives = []
        if coverage != "gap":
            for name in faculty_names:
                if name in candidates or name.casefold() not in graph_text:
                    continue
                labels = {term["label"] for term in by_name[name]["terms"]}
                if labels.intersection(accepted_terms):
                    evidence_alternatives.append(name)
        roles_by_record.setdefault(record_id, []).append({
            "id": f"role-{int(row['role_index'])}",
            "label": row["role_label"],
            "coverage": coverage,
            "candidate_ids": [faculty_ids[name] for name in candidates],
            "alternative_ids": [faculty_ids[name] for name in evidence_alternatives],
            "accepted_terms": accepted_terms,
            "rationale": row.get("audit_rationale") or "",
            "source_url": row.get("authoritative_source_url") or "",
        })

    opportunity_rows = []
    for row in gate["opportunities"]:
        record_id = str(row["record_id"])
        expansion = expansion_by_id.get(record_id)
        if not expansion:
            raise ValueError(f"Missing expansion record for {record_id}")
        team_names = _split(row.get("team_members") or "")
        members = []
        for name in team_names:
            faculty = by_name.get(name)
            evidence_row = member_by_key.get((record_id, name))
            if not faculty or not evidence_row:
                raise ValueError(f"Missing selected-member evidence for {record_id}: {name}")
            members.append({
                "faculty_id": faculty["id"],
                "contribution": evidence_row.get("contribution") or "",
                "evidence_term": evidence_row.get("evidence_term") or "",
                "evidence_phrase": evidence_row.get("evidence_phrase") or "",
                "evidence_tier": evidence_row.get("evidence_tier") or "",
                "why_person": evidence_row.get("why_person") or "",
                "source_url": evidence_row.get("faculty_source_url") or faculty["source_urls"][0],
            })
        roles = sorted(
            roles_by_record.get(record_id, []),
            key=lambda item: int(item["id"].split("-")[-1]),
        )
        if len(roles) != 4:
            raise ValueError(f"Expected four audited roles for {record_id}")
        opportunity_rows.append({
            "id": record_id,
            "parent_id": str(expansion.get("base_id") or record_id),
            "opportunity_number": row.get("opportunity_number") or "",
            "scope_label": row["scope_label"],
            "catalog_title": row.get("catalog_title") or "",
            "agency": row.get("agency") or "",
            "archetype": row.get("archetype") or "",
            "record_type": str(row.get("record_type") or "").replace(" ", "_"),
            "objective": row.get("objective") or "",
            "gate_state": _gate_state(row.get("gate_status") or ""),
            "gate_label": row.get("gate_status") or "",
            "why_team": row.get("why_team") or "",
            "source_url": row.get("opportunity_source_url") or expansion.get("source_url") or "",
            "members": members,
            "roles": roles,
            "missing_skills": _split(row.get("missing_skill_summary") or "")
                if not str(row.get("missing_skill_summary") or "").startswith("None")
                else [],
        })
    opportunity_rows.sort(key=lambda item: item["id"])
    if len(opportunity_rows) != 10:
        raise ValueError("The calibrated release must contain exactly ten opportunity scopes")
    if any(len(item["members"]) not in {3, 4} for item in opportunity_rows):
        raise ValueError("Every proposed team must contain three or four people")
    if any(not member["why_person"] for item in opportunity_rows for member in item["members"]):
        raise ValueError("Every proposed person must retain an explanation")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "method_version": "opportunity-team-role-evidence-v1",
        "release_state": "evidence_calibrated_pilot",
        "source_hashes": source_hashes,
        "source_roster_counts": SOURCE_ROSTER_COUNTS,
        "pool_counts": POOL_COUNTS,
        "faculty": faculty_rows,
        "opportunities": opportunity_rows,
        "limitations": [
        "The directory may omit relevant faculty and does not imply availability or eligibility.",
        "Only the listed opportunity scopes have a reviewed role model; broad parent programs never receive a team proposal.",
        "A conditional or failed proposal is an incomplete internal core, not a complete application team.",
        "Replacement choices are source-backed capability alternatives and remain non-covering until role transfer is reviewed.",
    ],
    }
    payload["generation_id"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


def browser_projection(config: dict) -> dict:
    faculty = [{
        "id": row["id"],
        "name": row["name"],
        "home_unit": row["home_unit"],
        "pool_state": row["pool_state"],
        "claim_status": row["claim_status"],
        "terms": [{
            "label": term["label"],
            "evidence": term["evidence"],
            "evidence_tier": term["evidence_tier"],
        } for term in row["terms"]],
        "source_url": row["source_urls"][0],
        "source_checked_date": row["source_checked_date"],
    } for row in config["faculty"]]
    return {
        "schema_version": BROWSER_SCHEMA_VERSION,
        "generation_id": config["generation_id"],
        "method_version": config["method_version"],
        "release_state": config["release_state"],
        "source_hashes": config["source_hashes"],
        "source_roster_counts": config["source_roster_counts"],
        "pool_counts": config["pool_counts"],
        "faculty": faculty,
        "opportunities": config["opportunities"],
        "limitations": config["limitations"],
    }


def write_outputs(config: dict, config_out: Path, browser_out: Path) -> None:
    config_out.parent.mkdir(parents=True, exist_ok=True)
    browser_out.parent.mkdir(parents=True, exist_ok=True)
    config_out.write_text(
        json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    projection = browser_projection(config)
    browser = (
        "/* Generated by scripts/import_opportunity_team_model.py. Do not edit. */\n"
        "globalThis.OPPORTUNITY_TEAM_DATA="
        + _canonical_bytes(projection).decode("utf-8")
        + ";\n"
    )
    encoded = browser.encode("utf-8")
    if len(encoded) > MAX_BROWSER_BYTES:
        raise ValueError(f"Browser team projection exceeds {MAX_BROWSER_BYTES:,} bytes")
    browser_out.write_bytes(encoded)


def update_version_target(path: Path, generation_id: str) -> None:
    source = path.read_text(encoding="utf-8")
    updated, marker_count = re.subn(
        r'(<meta name="opportunity-team-generation" content=")[a-f0-9]{64}("\s*/?>)',
        rf"\g<1>{generation_id}\2",
        source,
    )
    if marker_count != 1:
        raise ValueError(f"Expected one opportunity-team generation marker in {path}")
    for asset in VERSIONED_ASSETS:
        pattern = rf"({re.escape(asset)}\?v=)[^\"']+"
        updated = re.sub(pattern, rf"\g<1>{generation_id}", updated)
    if "assets/opportunity-team.js?v=" not in updated:
        raise ValueError(f"Missing opportunity-team runtime reference in {path}")
    path.write_text(updated, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--faculty-model", type=Path, required=True)
    parser.add_argument("--gate-model", type=Path, required=True)
    parser.add_argument("--config-out", type=Path, default=Path("config/opportunity_team_model.json"))
    parser.add_argument("--browser-out", type=Path, default=Path("data/opportunity_teams.js"))
    parser.add_argument("--version-target", action="append", type=Path, default=[])
    args = parser.parse_args()
    faculty_model = _read_json(args.faculty_model)
    gate = _read_json(args.gate_model)
    source_hashes = {
        "faculty_model": _sha256(args.faculty_model),
        "team_gate_model": _sha256(args.gate_model),
        "faculty_workbook": str(faculty_model.get("faculty_source_workbook_sha256") or ""),
        "benchmark_lock": str(gate.get("meta", {}).get("benchmark_lock") or ""),
        "faculty_expansion_lock": str(gate.get("meta", {}).get("faculty_expansion_lock") or ""),
        "team_gate_lock": str(gate.get("meta", {}).get("gate_lock") or ""),
    }
    config = build_config(faculty_model, gate, source_hashes)
    write_outputs(config, args.config_out, args.browser_out)
    for target in args.version_target:
        update_version_target(target, config["generation_id"])
    print(
        f"Wrote {args.config_out} and {args.browser_out}; "
        f"generation={config['generation_id']} faculty={len(config['faculty'])} "
        f"opportunities={len(config['opportunities'])}"
    )


if __name__ == "__main__":
    main()
