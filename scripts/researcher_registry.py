"""Canonical researcher-registry validation, migration, and projections.

The repository has exactly one editable researcher source:
``config/researcher_registry.json``.  Browser directory data, the legacy
opportunity-team compatibility model, and forward-match metadata are generated
from that registry.
"""

from __future__ import annotations

import argparse
import copy
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable
import unicodedata


SCHEMA_VERSION = 3
MANIFEST_SCHEMA_VERSION = 1
DIRECTORY_SCHEMA_VERSION = 1
RESEARCHER_ID = re.compile(r"^urh-[0-9]{6}$")
CLAIM_ID = re.compile(r"^urh-[0-9]{6}-c[0-9]{3}$")
ORCID_ID = re.compile(r"^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$")
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
RELATIONSHIPS = {
    "hajim_core_faculty",
    "internal_affiliated_researcher",
    "external_collaborator",
    "reference_only_researcher",
}
VISIBILITIES = {"department", "institution", "approved_collaborator", "reference_only", "hidden"}
STATUSES = {"active", "inactive", "departed"}
CLAIM_STATUSES = {"active", "retired"}
EVIDENCE_LEVELS = {"direct", "corroborated", "administrator_reviewed"}
PUBLIC_DIRECTORY_GLOBAL = "RESEARCHER_DIRECTORY"
PUBLIC_DIRECTORY_PATH = Path("data/researcher_directory.js")
PUBLIC_MANIFEST_PATH = Path("data/researcher_registry_manifest.json")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def material_claim_hash(claim: dict) -> str:
    material = {
        key: claim.get(key)
        for key in ("status", "label", "category", "categories", "type", "evidence", "source_urls", "evidence_level")
    }
    return content_hash(material)


def registry_generation(registry: dict) -> str:
    payload = copy.deepcopy(registry)
    payload.pop("registry_generation", None)
    return content_hash(payload)


def canonical_sort_name(value: object) -> str:
    display_name = str(value or "").strip()
    parts = display_name.split()
    if len(parts) < 2:
        return display_name
    suffix = parts.pop() if re.fullmatch(r"(?:Jr\.?|Sr\.?|II|III|IV)", parts[-1], re.I) else ""
    family = parts.pop()
    return f"{family}, {' '.join(parts)}{' ' + suffix if suffix else ''}"


def _require_text(value: object, label: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{label} must contain 1-{maximum} characters")
    return text


def _validate_urls(values: object, label: str, *, required: bool = True) -> list[str]:
    if not isinstance(values, list) or (required and not values):
        raise ValueError(f"{label} must be a non-empty URL list")
    result: list[str] = []
    for value in values:
        url = str(value or "").strip()
        if len(url) > 500 or not re.match(r"^https://", url, re.I):
            raise ValueError(f"{label} contains an invalid HTTPS URL")
        if url not in result:
            result.append(url)
    return result


def _valid_orcid_checksum(value: str) -> bool:
    compact = value.replace("-", "")
    if not re.fullmatch(r"[0-9]{15}[0-9X]", compact):
        return False
    total = 0
    for character in compact[:15]:
        total = (total + int(character)) * 2
    result = (12 - (total % 11)) % 11
    return compact[-1] == ("X" if result == 10 else str(result))


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return bool(DATE.fullmatch(value))
    except ValueError:
        return False


def validate_registry(registry: dict, *, require_generation: bool = True) -> dict:
    if not isinstance(registry, dict) or registry.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"researcher registry schema_version must be {SCHEMA_VERSION}")
    researchers = registry.get("researchers")
    if not isinstance(researchers, list):
        raise ValueError("researchers must be a list")
    ids: set[str] = set()
    identity_aliases: set[str] = set()
    orcids: set[str] = set()
    claim_ids: set[str] = set()
    legacy_claim_ids: set[str] = set()
    for researcher in researchers:
        if not isinstance(researcher, dict):
            raise ValueError("each researcher must be an object")
        researcher_id = str(researcher.get("researcher_id") or "")
        if not RESEARCHER_ID.fullmatch(researcher_id) or researcher_id in ids:
            raise ValueError(f"duplicate or invalid researcher_id: {researcher_id!r}")
        ids.add(researcher_id)
        _require_text(researcher.get("display_name"), f"{researcher_id}.display_name", 120)
        _require_text(researcher.get("sort_name"), f"{researcher_id}.sort_name", 140)
        _require_text(researcher.get("home_unit"), f"{researcher_id}.home_unit", 180)
        summary = str(researcher.get("research_summary") or "")
        if len(summary) > 1200:
            raise ValueError(f"{researcher_id}.research_summary is too long")
        relationship = researcher.get("relationship")
        visibility = researcher.get("pool_visibility")
        status = researcher.get("status")
        if relationship not in RELATIONSHIPS:
            raise ValueError(f"{researcher_id} has an invalid relationship")
        if visibility not in VISIBILITIES:
            raise ValueError(f"{researcher_id} has an invalid pool_visibility")
        if status not in STATUSES:
            raise ValueError(f"{researcher_id} has an invalid status")
        if not isinstance(researcher.get("auto_proposable"), bool):
            raise ValueError(f"{researcher_id}.auto_proposable must be boolean")
        if researcher["auto_proposable"] and (status != "active" or visibility in {"reference_only", "hidden"}):
            raise ValueError(f"{researcher_id} cannot be automatically proposed")
        aliases = researcher.get("aliases")
        legacy_ids = researcher.get("legacy_ids")
        if not isinstance(aliases, list) or not isinstance(legacy_ids, list) or not legacy_ids:
            raise ValueError(f"{researcher_id} must preserve aliases and at least one legacy ID")
        for alias in aliases:
            _require_text(alias, f"{researcher_id}.aliases", 120)
        for legacy_id in legacy_ids:
            legacy = str(legacy_id or "").strip()
            if not legacy or legacy in identity_aliases or legacy in ids:
                raise ValueError(f"duplicate or invalid legacy ID: {legacy!r}")
            identity_aliases.add(legacy)
        orcid = str(researcher.get("orcid_id") or "")
        if orcid:
            if not ORCID_ID.fullmatch(orcid) or not _valid_orcid_checksum(orcid) or orcid in orcids:
                raise ValueError(f"duplicate or invalid ORCID iD: {orcid!r}")
            orcids.add(orcid)
        _validate_urls(researcher.get("source_urls"), f"{researcher_id}.source_urls")
        checked = str(researcher.get("source_checked_date") or "")
        if not _valid_date(checked):
            raise ValueError(f"{researcher_id}.source_checked_date must be YYYY-MM-DD")
        claims = researcher.get("claims")
        if not isinstance(claims, list):
            raise ValueError(f"{researcher_id}.claims must be a list")
        for claim in claims:
            claim_id = str(claim.get("claim_id") or "")
            if not CLAIM_ID.fullmatch(claim_id) or not claim_id.startswith(f"{researcher_id}-c") or claim_id in claim_ids:
                raise ValueError(f"duplicate, invalid, or misowned claim ID: {claim_id!r}")
            claim_ids.add(claim_id)
            if (
                not isinstance(claim.get("revision"), int)
                or isinstance(claim["revision"], bool)
                or claim["revision"] < 1
            ):
                raise ValueError(f"{claim_id}.revision must be a positive integer")
            if claim.get("status") not in CLAIM_STATUSES:
                raise ValueError(f"{claim_id} has an invalid status")
            for field, maximum in (("label", 180), ("category", 140), ("type", 80), ("evidence", 500)):
                _require_text(claim.get(field), f"{claim_id}.{field}", maximum)
            categories = claim.get("categories")
            if not isinstance(categories, list) or not categories or len(categories) > 12:
                raise ValueError(f"{claim_id}.categories must contain 1-12 values")
            normalized_categories = [_require_text(value, f"{claim_id}.categories", 140) for value in categories]
            if len(set(normalized_categories)) != len(normalized_categories) or claim["category"] not in normalized_categories:
                raise ValueError(f"{claim_id}.categories must be unique and include the primary category")
            _validate_urls(claim.get("source_urls"), f"{claim_id}.source_urls")
            if claim.get("evidence_level") not in EVIDENCE_LEVELS:
                raise ValueError(f"{claim_id} has an invalid evidence_level")
            if not _valid_date(str(claim.get("verified_on") or "")):
                raise ValueError(f"{claim_id}.verified_on must be YYYY-MM-DD")
            legacy_ids = claim.get("legacy_claim_ids")
            if not isinstance(legacy_ids, list) or len(legacy_ids) > 10:
                raise ValueError(f"{claim_id}.legacy_claim_ids must be a list of at most 10 IDs")
            for legacy_id in legacy_ids:
                if not isinstance(legacy_id, str):
                    raise ValueError(f"{claim_id}.legacy_claim_ids must contain only strings")
                normalized = _require_text(legacy_id, f"{claim_id}.legacy_claim_ids", 80)
                identity = normalized.casefold()
                if normalized != legacy_id or identity in legacy_claim_ids:
                    raise ValueError("legacy claim IDs must be globally unique canonical strings")
                legacy_claim_ids.add(identity)
            if claim.get("material_hash") != material_claim_hash(claim):
                raise ValueError(f"{claim_id}.material_hash does not match its material content")
    if ids.intersection(identity_aliases):
        raise ValueError("a legacy ID collides with a stable researcher ID")
    expected = registry_generation(registry)
    if require_generation and registry.get("registry_generation") != expected:
        raise ValueError("registry_generation does not match the canonical researcher content")
    return registry


def load_registry(path: Path | str = Path("config/researcher_registry.json")) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_registry(value)


def pool_state(researcher: dict) -> str:
    if researcher["status"] != "active" or researcher["pool_visibility"] in {"reference_only", "hidden"}:
        return "unadmitted"
    active_claims = [claim for claim in researcher["claims"] if claim["status"] == "active"]
    if researcher["auto_proposable"] and len(active_claims) >= 2:
        return "main"
    if active_claims:
        return "standby"
    return "unadmitted"


def registry_counts(registry: dict) -> dict:
    researchers = registry["researchers"]
    pool_counts = Counter(pool_state(row) for row in researchers)
    relationship_counts = Counter(row["relationship"] for row in researchers)
    visibility_counts = Counter(row["pool_visibility"] for row in researchers)
    status_counts = Counter(row["status"] for row in researchers)
    rankable = sum(bool([claim for claim in row["claims"] if claim["status"] == "active"]) for row in researchers)
    return {
        "total": len(researchers),
        "rankable": rankable,
        "unrankable": len(researchers) - rankable,
        "auto_proposable": sum(row["auto_proposable"] and row["status"] == "active" for row in researchers),
        "pool_counts": {key: pool_counts.get(key, 0) for key in ("main", "standby", "unadmitted")},
        "relationship_counts": dict(sorted(relationship_counts.items())),
        "visibility_counts": dict(sorted(visibility_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
    }


def directory_projection(registry: dict) -> dict:
    return {
        "schema_version": DIRECTORY_SCHEMA_VERSION,
        "registry_generation": registry["registry_generation"],
        "counts": registry_counts(registry),
        "researchers": [{
            "id": row["researcher_id"],
            "legacy_ids": row["legacy_ids"],
            "name": row["display_name"],
            "sort_name": row["sort_name"],
            "aliases": row["aliases"],
            "home_unit": row["home_unit"],
            "relationship": row["relationship"],
            "pool_visibility": row["pool_visibility"],
            "auto_proposable": row["auto_proposable"],
            "status": row["status"],
            "pool_state": pool_state(row),
            "orcid_id": row["orcid_id"],
            "research_summary": row["research_summary"],
            "source_urls": row["source_urls"],
            "source_url": row["source_urls"][0],
            "source_checked_date": row["source_checked_date"],
            "claims": [{
                "claim_id": claim["claim_id"],
                "revision": claim["revision"],
                "status": claim["status"],
                "label": claim["label"],
                "category": claim["category"],
                "categories": claim["categories"],
                "type": claim["type"],
                "evidence": claim["evidence"],
                "source_urls": claim["source_urls"],
                "evidence_level": claim["evidence_level"],
                "legacy_claim_ids": claim.get("legacy_claim_ids", []),
            } for claim in row["claims"]],
        } for row in registry["researchers"]],
    }


def legacy_faculty_projection(registry: dict) -> list[dict]:
    projection = directory_projection(registry)
    return [{
        "id": row["id"],
        "legacy_ids": row["legacy_ids"],
        "name": row["name"],
        "home_unit": row["home_unit"],
        "relationship": row["relationship"],
        "pool_visibility": row["pool_visibility"],
        "auto_proposable": row["auto_proposable"],
        "status": row["status"],
        "pool_state": row["pool_state"],
        "claim_status": "registry-reviewed",
        "official_interests": next(
            source.get("official_interests", [])
            for source in registry["researchers"] if source["researcher_id"] == row["id"]
        ),
        "terms": [{
            "id": (claim.get("legacy_claim_ids") or [claim["claim_id"]])[0],
            "claim_id": claim["claim_id"],
            "claim_revision": claim["revision"],
            "label": claim["label"],
            "category": claim["category"],
            "categories": claim["categories"],
            "type": claim["type"],
            "evidence": claim["evidence"],
            "evidence_tier": claim["evidence_level"],
            "source_urls": claim["source_urls"],
        } for claim in row["claims"] if claim["status"] == "active"],
        "source_urls": row["source_urls"],
        "source_checked_date": row["source_checked_date"],
    } for row in projection["researchers"]]


def matching_profiles(registry: dict, *, visibility: str = "department") -> list[dict]:
    profiles: list[dict] = []
    for row in registry["researchers"]:
        if row["status"] != "active" or row["pool_visibility"] != visibility:
            continue
        claims = [claim for claim in row["claims"] if claim["status"] == "active"]
        # Keep the pre-registry lookup key when a migrated profile has an alias.
        # The canonical name remains available as resolved_name and in the public
        # directory, while existing saved teams and forward-match consumers keep
        # resolving the legacy spelling without creating a duplicate researcher.
        matching_name = (row.get("aliases") or [row["display_name"]])[0]
        profiles.append({
            "researcher_id": row["researcher_id"],
            "legacy_ids": row["legacy_ids"],
            "name": matching_name,
            "resolved_name": row["display_name"],
            "research_summary": row["research_summary"],
            "key_terms": [claim["label"] for claim in claims],
            "domains": sorted({
                category
                for claim in claims
                for category in (claim.get("categories") or [claim["category"]])
                if category
            }),
            "claim_refs": [{"claim_id": claim["claim_id"], "revision": claim["revision"]} for claim in claims],
            "openalex_id": (row.get("external_ids") or {}).get("openalex", ""),
            "works_count": (row.get("metrics") or {}).get("openalex_works_count"),
        })
    return profiles


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def _write_javascript(path: Path, global_name: str, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    source = (
        "/* Generated by scripts/researcher_registry.py. Do not edit. */\n"
        f"globalThis.{global_name}=" + canonical_bytes(value).decode("utf-8") + ";\n"
    )
    path.write_text(source, encoding="utf-8", newline="\n")


def _update_directory_version_target(path: Path, generation: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(data/researcher_directory\.js\?v=)[a-f0-9]+',
        rf'\g<1>{generation}',
        text,
    )
    if count != 1:
        raise ValueError(f"expected one researcher-directory version reference in {path}")
    path.write_text(updated, encoding="utf-8", newline="\n")


def _identity_map(registry: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in registry["researchers"]:
        result[row["researcher_id"]] = row["researcher_id"]
        for legacy in row["legacy_ids"]:
            result[legacy] = row["researcher_id"]
    return result


def _team_profile_changed(previous: dict, current: dict) -> bool:
    fields = (
        "relationship", "pool_visibility", "auto_proposable", "status", "pool_state",
        "official_interests", "source_urls",
    )
    if any(previous.get(field) != current.get(field) for field in fields):
        return True
    term_fields = (
        "claim_id", "claim_revision", "label", "category", "categories", "type",
        "evidence", "evidence_tier",
    )
    previous_terms = [
        {field: term.get(field) for field in term_fields}
        for term in previous.get("terms", [])
    ]
    current_terms = [
        {field: term.get(field) for field in term_fields}
        for term in current.get("terms", [])
    ]
    if previous_terms != current_terms:
        return True
    # Older checked-in projections did not retain claim-level sources. Once a
    # projection contains them, every later publication must preserve or
    # explicitly recalibrate those evidence links.
    if any("source_urls" in term for term in previous.get("terms", [])):
        previous_sources = [term.get("source_urls", []) for term in previous.get("terms", [])]
        current_sources = [term.get("source_urls", []) for term in current.get("terms", [])]
        if previous_sources != current_sources:
            return True
    return False


def validate_opportunity_team_dependencies(registry: dict, model: dict) -> None:
    """Reject registry changes that would silently stale calibrated team evidence."""
    identities = _identity_map(registry)
    researchers = {row["researcher_id"]: row for row in registry["researchers"]}
    projection = {row["id"]: row for row in legacy_faculty_projection(registry)}
    previous_profiles: dict[str, dict] = {}
    for row in model.get("faculty", []):
        for identity in [row.get("id"), *(row.get("legacy_ids") or [])]:
            if identity:
                previous_profiles[str(identity)] = row

    affected: dict[str, set[str]] = {}
    for opportunity in model.get("opportunities", []):
        scope_id = str(opportunity.get("id") or "unknown-scope")
        raw_references = {
            str(member.get("faculty_id") or "")
            for member in opportunity.get("members", [])
        }
        for role in opportunity.get("roles", []):
            raw_references.update(str(value) for value in role.get("candidate_ids", []))
            raw_references.update(str(value) for value in role.get("alternative_ids", []))
        for raw_identity in raw_references:
            if raw_identity not in identities:
                raise ValueError(f"opportunity team references unknown researcher {raw_identity!r}")
            researcher_id = identities[raw_identity]
            current = projection[researcher_id]
            previous = previous_profiles.get(raw_identity) or previous_profiles.get(researcher_id)
            if (
                previous is None
                or current["status"] != "active"
                or not current["auto_proposable"]
                or current["pool_state"] not in {"main", "standby"}
                or _team_profile_changed(previous, current)
            ):
                affected.setdefault(scope_id, set()).add(researcher_id)

        for member in opportunity.get("members", []):
            raw_identity = str(member.get("faculty_id") or "")
            if raw_identity not in identities:
                continue
            researcher_id = identities[raw_identity]
            active_claims = [
                claim for claim in researchers[researcher_id]["claims"]
                if claim["status"] == "active"
            ]
            evidence_term = str(member.get("evidence_term") or "").casefold()
            evidence_phrase = str(member.get("evidence_phrase") or "").casefold()
            source_url = str(member.get("source_url") or "")
            if not any(
                claim["label"].casefold() == evidence_term
                and evidence_phrase in claim["evidence"].casefold()
                and source_url in claim["source_urls"]
                for claim in active_claims
            ):
                affected.setdefault(scope_id, set()).add(researcher_id)

    if affected:
        details = "; ".join(
            f"{scope_id}: {', '.join(sorted(researcher_ids))}"
            for scope_id, researcher_ids in sorted(affected.items())
        )
        raise ValueError(
            "calibrated opportunity-team scopes require recalibration after "
            f"evidence-bearing researcher changes ({details})"
        )


def synchronize_opportunity_team_model(registry: dict, path: Path) -> dict:
    model = json.loads(path.read_text(encoding="utf-8"))
    validate_opportunity_team_dependencies(registry, model)
    identities = _identity_map(registry)
    for opportunity in model.get("opportunities", []):
        for member in opportunity.get("members", []):
            current = str(member.get("faculty_id") or "")
            if current not in identities:
                raise ValueError(f"opportunity member references unknown researcher {current!r}")
            member["faculty_id"] = identities[current]
        for role in opportunity.get("roles", []):
            for field in ("candidate_ids", "alternative_ids"):
                values = []
                for current in role.get(field, []):
                    if current not in identities:
                        raise ValueError(f"opportunity role references unknown researcher {current!r}")
                    values.append(identities[current])
                role[field] = values
    counts = registry_counts(registry)
    model["source_roster_counts"] = {
        "total": counts["total"], "rankable": counts["rankable"], "unrankable": counts["unrankable"]
    }
    model["pool_counts"] = counts["pool_counts"]
    model["researcher_registry_generation"] = registry["registry_generation"]
    model["faculty"] = legacy_faculty_projection(registry)
    model.pop("generation_id", None)
    model["generation_id"] = content_hash(model)
    _write_json(path, model)
    return model


def build_outputs(
    registry_path: Path,
    directory_path: Path = PUBLIC_DIRECTORY_PATH,
    manifest_path: Path = PUBLIC_MANIFEST_PATH,
    team_model_path: Path = Path("config/opportunity_team_model.json"),
    catalog_path: Path = Path("data/opportunities.js"),
    faculty_matches_path: Path = Path("data/faculty_matches.js"),
    version_targets: Iterable[Path] = (),
) -> dict:
    registry = load_registry(registry_path)
    team_model_source = json.loads(team_model_path.read_text(encoding="utf-8"))
    validate_opportunity_team_dependencies(registry, team_model_source)
    projection = directory_projection(registry)
    _write_javascript(directory_path, PUBLIC_DIRECTORY_GLOBAL, projection)
    _write_json(manifest_path, {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "registry_generation": registry["registry_generation"],
        "counts": projection["counts"],
        "researcher_ids": [row["id"] for row in projection["researchers"]],
    })
    team_model = synchronize_opportunity_team_model(registry, team_model_path)
    from scripts.import_opportunity_team_model import update_version_target, write_outputs
    write_outputs(team_model, team_model_path, Path("data/opportunity_teams.js"), Path("data/opportunity_team_index.js"))
    from scripts.faculty_match import match_to_catalog
    match_to_catalog(matching_profiles(registry), str(catalog_path), str(faculty_matches_path), registry_generation=registry["registry_generation"])
    for target in version_targets:
        update_version_target(target, team_model["generation_id"])
    interests_page = Path("faculty_interests.html")
    if interests_page.exists():
        _update_directory_version_target(interests_page, registry["registry_generation"])
    return {"registry": registry, "directory": projection, "team_model": team_model}


def dependency_report(before: dict, after: dict, team_model: dict) -> dict:
    before_by_id = {row["researcher_id"]: row for row in before.get("researchers", [])}
    after_by_id = {row["researcher_id"]: row for row in after.get("researchers", [])}
    changes: list[dict] = []
    affected_researchers: set[str] = set()
    scientific_researchers: set[str] = set()
    for researcher_id in sorted(set(before_by_id) | set(after_by_id)):
        old = before_by_id.get(researcher_id)
        new = after_by_id.get(researcher_id)
        if old == new:
            continue
        affected_researchers.add(researcher_id)
        old_claims = {claim["claim_id"]: claim["material_hash"] for claim in (old or {}).get("claims", [])}
        new_claims = {claim["claim_id"]: claim["material_hash"] for claim in (new or {}).get("claims", [])}
        changed_claims = sorted(claim_id for claim_id in set(old_claims) | set(new_claims) if old_claims.get(claim_id) != new_claims.get(claim_id))
        if changed_claims or not old or not new or any((old or {}).get(key) != (new or {}).get(key) for key in ("status", "auto_proposable", "relationship", "pool_visibility")):
            scientific_researchers.add(researcher_id)
        changes.append({"researcher_id": researcher_id, "changed_claim_ids": changed_claims})
    affected_scopes = []
    for opportunity in team_model.get("opportunities", []):
        references = {member.get("faculty_id") for member in opportunity.get("members", [])}
        for role in opportunity.get("roles", []):
            references.update(role.get("candidate_ids", []))
            references.update(role.get("alternative_ids", []))
        touched = sorted(scientific_researchers.intersection(references))
        if touched:
            affected_scopes.append({"scope_id": opportunity["id"], "researcher_ids": touched})
    return {
        "schema_version": 1,
        "base_registry_generation": before.get("registry_generation", ""),
        "registry_generation": after.get("registry_generation", ""),
        "changes": changes,
        "affected_team_scopes": affected_scopes,
    }


def _normalize_orcid(value: object) -> str:
    compact = re.sub(r"[^0-9X]", "", str(value or "").upper())
    return "-".join(compact[index:index + 4] for index in range(0, 16, 4)) if len(compact) == 16 else ""


def apply_approved_submission(
    registry: dict,
    approved: dict,
    expected_generation: str,
    team_model: dict | None = None,
) -> tuple[dict, dict]:
    validate_registry(registry)
    if registry["registry_generation"] != expected_generation:
        raise ValueError("approved submission is stale and must return to administrator review")
    if approved.get("state") != "approved" or approved.get("schema_version") != 1:
        raise ValueError("publication input must be an approved schema-version 1 submission")
    proposed = approved.get("approved_profile")
    if not isinstance(proposed, dict):
        raise ValueError("approved_profile is required")
    output = copy.deepcopy(registry)
    researcher_id = str(approved.get("researcher_id") or "")
    is_nomination = not researcher_id
    by_id = {row["researcher_id"]: row for row in output["researchers"]}
    if researcher_id:
        if researcher_id not in by_id:
            raise ValueError("approved correction references an unknown researcher")
        target = by_id[researcher_id]
    else:
        numeric = max([int(row["researcher_id"].split("-")[-1]) for row in output["researchers"]] or [0]) + 1
        researcher_id = f"urh-{numeric:06d}"
        target = {
            "researcher_id": researcher_id,
            "display_name": "", "sort_name": "", "aliases": [],
            "legacy_ids": [f"registry-{researcher_id}"], "orcid_id": "", "home_unit": "",
            "relationship": "reference_only_researcher", "pool_visibility": "hidden",
            "auto_proposable": False, "status": "active", "research_summary": "",
            "official_interests": [], "source_urls": [], "source_checked_date": "",
            "external_ids": {}, "metrics": {}, "claims": [],
        }
        output["researchers"].append(target)
    previous_claims = {claim["claim_id"]: copy.deepcopy(claim) for claim in target.get("claims", [])}
    permitted = {
        "display_name", "sort_name", "aliases", "orcid_id", "home_unit", "relationship",
        "pool_visibility", "auto_proposable", "status", "research_summary", "source_urls",
        "source_checked_date", "claims",
    }
    unexpected = set(proposed) - permitted
    if unexpected:
        raise ValueError(f"approved profile contains non-allowlisted fields: {sorted(unexpected)}")
    for key in permitted:
        if key in proposed:
            target[key] = copy.deepcopy(proposed[key])
    target["orcid_id"] = _normalize_orcid(target.get("orcid_id")) if target.get("orcid_id") else ""
    target["source_checked_date"] = target.get("source_checked_date") or approved.get("approved_at", "")[:10]
    submitted_claim_ids = {
        str(claim.get("claim_id") or "")
        for claim in target.get("claims", [])
        if claim.get("claim_id")
    }
    missing_claim_ids = sorted(set(previous_claims) - submitted_claim_ids)
    if missing_claim_ids:
        raise ValueError(
            f"existing claims must remain present and be retired instead of removed: {missing_claim_ids}"
        )
    used_claim_ids = set(previous_claims)
    next_claim_number = max(
        [int(claim_id.rsplit("-c", 1)[-1]) for claim_id in used_claim_ids] or [0]
    ) + 1
    normalized_claims = []
    for claim in target.get("claims", []):
        value = copy.deepcopy(claim)
        requested_claim_id = str(value.get("claim_id") or "")
        if is_nomination and requested_claim_id:
            raise ValueError("nomination claims cannot preassign claim IDs")
        if requested_claim_id and requested_claim_id not in previous_claims:
            raise ValueError("new claims cannot preassign claim IDs")
        requested_revision = value.get("revision")
        if (
            not isinstance(requested_revision, int)
            or isinstance(requested_revision, bool)
            or requested_revision < 1
        ):
            raise ValueError("approved claim revision must be a positive integer")
        if requested_claim_id:
            value["claim_id"] = requested_claim_id
        else:
            while f"{researcher_id}-c{next_claim_number:03d}" in used_claim_ids:
                next_claim_number += 1
            value["claim_id"] = f"{researcher_id}-c{next_claim_number:03d}"
            used_claim_ids.add(value["claim_id"])
            next_claim_number += 1
        value["categories"] = list(dict.fromkeys(value.get("categories") or [value.get("category")]))
        old = previous_claims.get(value["claim_id"])
        if old:
            if value.get("legacy_claim_ids") != old.get("legacy_claim_ids", []):
                raise ValueError("existing legacy claim IDs must remain attached to their original claim")
            value["revision"] = (
                old["revision"] + 1
                if material_claim_hash(value) != old["material_hash"]
                else old["revision"]
            )
        else:
            if value.get("legacy_claim_ids"):
                raise ValueError("new claims cannot assign legacy claim IDs")
            value["revision"] = 1
        value["material_hash"] = material_claim_hash(value)
        normalized_claims.append(value)
    target["claims"] = normalized_claims
    output["researchers"].sort(key=lambda row: (row["sort_name"].casefold(), row["researcher_id"]))
    output.pop("registry_generation", None)
    output["registry_generation"] = registry_generation(output)
    validate_registry(output)
    if team_model is not None:
        validate_opportunity_team_dependencies(output, team_model)
    return output, dependency_report(registry, output, team_model or {"opportunities": []})


def migrate_legacy(team_model_path: Path, faculty_matches_path: Path, output_path: Path) -> dict:
    team_model = json.loads(team_model_path.read_text(encoding="utf-8"))
    if not isinstance(team_model.get("faculty"), list) or not team_model["faculty"]:
        raise ValueError("legacy team model has no embedded faculty directory")
    matches_text = faculty_matches_path.read_text(encoding="utf-8")
    matches = json.loads(matches_text[matches_text.index("{"):].rstrip().rstrip(";"))
    forward = matches.get("faculty") or {}
    def folded_name(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        return re.sub(r"[^a-z0-9]+", " ", normalized.encode("ascii", "ignore").decode("ascii").lower()).strip()
    forward_by_name = {folded_name(name): (name, profile) for name, profile in forward.items()}
    matched_forward_names: set[str] = set()
    researchers = []
    for index, source in enumerate(sorted(team_model["faculty"], key=lambda row: (row["name"].casefold(), row["id"])), start=1):
        researcher_id = f"urh-{index:06d}"
        forward_name, forward_profile = forward_by_name.get(folded_name(source["name"]), ("", {}))
        if forward_name:
            matched_forward_names.add(forward_name)
        source_urls = list(dict.fromkeys(
            str(url).replace("http://", "https://", 1)
            for url in (source.get("source_urls") or [])
        ))
        claims = []
        seen_labels = set()
        legacy_terms = list(source.get("terms") or [])
        legacy_researcher_id = str((source.get("legacy_ids") or [source["id"]])[0])
        for term in legacy_terms:
            label = str(term.get("label") or "").strip()
            if not label or label.casefold() in seen_labels:
                continue
            seen_labels.add(label.casefold())
            claim = {
                "claim_id": f"{researcher_id}-c{len(claims) + 1:03d}",
                "revision": 1,
                "status": "active",
                "label": label,
                "category": term.get("category") or "Interdisciplinary research",
                "categories": [term.get("category") or "Interdisciplinary research"],
                "type": term.get("type") or "Capability",
                "evidence": term.get("evidence") or label,
                "source_urls": source_urls,
                "verified_on": source["source_checked_date"],
                "evidence_level": "direct" if "direct" in str(term.get("evidence_tier") or "").lower() else "corroborated",
                "legacy_claim_ids": [f"{legacy_researcher_id}:{term['id']}"] if term.get("id") else [],
            }
            claim["material_hash"] = material_claim_hash(claim)
            claims.append(claim)
        forward_terms = forward_profile.get("key_terms") or []
        forward_domains = forward_profile.get("domains") or []
        for label in forward_terms:
            if label.casefold() in seen_labels:
                continue
            seen_labels.add(label.casefold())
            claim = {
                "claim_id": f"{researcher_id}-c{len(claims) + 1:03d}",
                "revision": 1,
                "status": "active",
                "label": label,
                "category": (forward_domains or ["Interdisciplinary research"])[0],
                "categories": list(dict.fromkeys(forward_domains or ["Interdisciplinary research"])),
                "type": "Capability",
                "evidence": label,
                "source_urls": source_urls,
                "verified_on": source["source_checked_date"],
                "evidence_level": "administrator_reviewed",
                "legacy_claim_ids": [],
            }
            claim["material_hash"] = material_claim_hash(claim)
            claims.append(claim)
        pool = source.get("pool_state")
        relationship_text = str(source.get("relationship") or "")
        relationship = "hajim_core_faculty" if "primary/core" in relationship_text.lower() else "internal_affiliated_researcher"
        visibility = "department" if forward_name else ("reference_only" if pool == "unadmitted" else "institution")
        interests = list(source.get("official_interests") or [])
        summary = forward_profile.get("research_summary") or (
            "Research interests include " + "; ".join(interests[:6]) + "." if interests else
            "Published research capabilities are listed below."
        )
        display_name = source["name"]
        sort_name = canonical_sort_name(display_name)
        researcher = {
            "researcher_id": researcher_id,
            "display_name": display_name,
            "sort_name": sort_name,
            "aliases": [forward_name] if forward_name and forward_name != display_name else [],
            "legacy_ids": [value for value in dict.fromkeys((source.get("legacy_ids") or []) + [source["id"]]) if value != researcher_id],
            "orcid_id": "",
            "home_unit": source["home_unit"],
            "relationship": relationship,
            "pool_visibility": visibility,
            "auto_proposable": pool in {"main", "standby"},
            "status": "active",
            "research_summary": summary,
            "official_interests": interests,
            "source_urls": source_urls,
            "source_checked_date": source["source_checked_date"],
            "external_ids": {"openalex": forward_profile.get("openalex_id") or ""},
            "metrics": {"openalex_works_count": forward_profile.get("works_count")},
            "claims": claims,
        }
        researchers.append(researcher)
    department_source = "https://www.hajim.rochester.edu/che/people/faculty/"
    for forward_name in sorted(set(forward) - matched_forward_names, key=str.casefold):
        profile = forward[forward_name]
        researcher_id = f"urh-{len(researchers) + 1:06d}"
        claims = []
        for label in profile.get("key_terms") or []:
            claim = {
                "claim_id": f"{researcher_id}-c{len(claims) + 1:03d}", "revision": 1, "status": "active",
                "label": label, "category": (profile.get("domains") or ["Interdisciplinary research"])[0],
                "categories": list(dict.fromkeys(profile.get("domains") or ["Interdisciplinary research"])),
                "type": "Capability", "evidence": label, "source_urls": [department_source],
                "verified_on": "2026-09-03", "evidence_level": "administrator_reviewed", "legacy_claim_ids": [],
            }
            claim["material_hash"] = material_claim_hash(claim)
            claims.append(claim)
        researchers.append({
            "researcher_id": researcher_id, "display_name": forward_name,
            "sort_name": canonical_sort_name(forward_name), "aliases": [],
            "legacy_ids": [re.sub(r"[^a-z0-9]+", "-", folded_name(forward_name)).strip("-")],
            "orcid_id": "", "home_unit": "Chemical & Sustainability Engineering",
            "relationship": "hajim_core_faculty", "pool_visibility": "department",
            "auto_proposable": True, "status": "active",
            "research_summary": profile.get("research_summary") or "",
            "official_interests": list(profile.get("key_terms") or []),
            "source_urls": [department_source], "source_checked_date": "2026-09-03",
            "external_ids": {"openalex": profile.get("openalex_id") or ""},
            "metrics": {"openalex_works_count": profile.get("works_count")},
            "claims": claims,
        })
    registry = {"schema_version": SCHEMA_VERSION, "researchers": researchers}
    registry["registry_generation"] = registry_generation(registry)
    validate_registry(registry)
    _write_json(output_path, registry)
    return registry


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    migrate = sub.add_parser("migrate-legacy")
    migrate.add_argument("--team-model", type=Path, default=Path("config/opportunity_team_model.json"))
    migrate.add_argument("--faculty-matches", type=Path, default=Path("data/faculty_matches.js"))
    migrate.add_argument("--out", type=Path, default=Path("config/researcher_registry.json"))
    validate = sub.add_parser("validate")
    validate.add_argument("--registry", type=Path, default=Path("config/researcher_registry.json"))
    build = sub.add_parser("build")
    build.add_argument("--registry", type=Path, default=Path("config/researcher_registry.json"))
    build.add_argument("--version-target", action="append", type=Path, default=[])
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--registry", type=Path, default=Path("config/researcher_registry.json"))
    apply_parser.add_argument("--submission", type=Path, required=True)
    apply_parser.add_argument("--expected-generation", required=True)
    apply_parser.add_argument("--dependency-report", type=Path, default=Path("outputs/researcher_dependency_report.json"))
    args = parser.parse_args()
    if args.command == "migrate-legacy":
        registry = migrate_legacy(args.team_model, args.faculty_matches, args.out)
        print(f"Wrote {args.out} with {len(registry['researchers'])} researchers; generation={registry['registry_generation']}")
    elif args.command == "validate":
        registry = load_registry(args.registry)
        print(f"Validated {len(registry['researchers'])} researchers; generation={registry['registry_generation']}")
    elif args.command == "build":
        result = build_outputs(args.registry, version_targets=args.version_target)
        print(f"Built researcher projections; generation={result['registry']['registry_generation']}")
    else:
        registry = load_registry(args.registry)
        approved = json.loads(args.submission.read_text(encoding="utf-8"))
        model = json.loads(Path("config/opportunity_team_model.json").read_text(encoding="utf-8"))
        updated, report = apply_approved_submission(
            registry, approved, args.expected_generation, team_model=model
        )
        _write_json(args.registry, updated)
        _write_json(args.dependency_report, report)
        print(f"Applied approved submission; generation={updated['registry_generation']}")


if __name__ == "__main__":
    main()
