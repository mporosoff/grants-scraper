"""Build and verify MEAS-8's outcome-blind frozen selection frame.

This module intentionally performs no network access and no source-text
inspection.  It applies DEBT-11 before MEAS-8 outcomes are read: the statistical
Arm A draw and the purposive Arm B questions are enumerable from committed
inputs, and Arm B is never included in Arm A's denominator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import p7_frame


ROOT = Path(__file__).resolve().parents[1]
FRAME_PATH = ROOT / "evaluation" / "meas8_frame.json"
CATALOG_COMMIT = "a2fdd2b1a7db10a0b435dc6a56ee13f54c34374c"
SELECTION_SEED = "MEAS-8:2026-08-20:arm-a:v1"

PRIOR_READ_ARTIFACTS = (
    "evaluation/p7_residual.json",
    "evaluation/p7_closeout.json",
    "evaluation/fm2_gate_frame.json",
    "evaluation/cov7_stratum_d.json",
    "evaluation/meas3_population.json",
    "evaluation/cov4_dec11_cases.json",
    "evaluation/cov4_challenge.json",
)

PRIOR_READ_DOCS = (
    "docs/COVERAGE_SURVEY.md",
    "docs/FAMILY_TAXONOMY.md",
    "docs/CORPUS_CENSUS.md",
    "docs/SOURCE_REACHABILITY_SWEEP.md",
    "docs/ROSES_SOURCE_INSPECTION.md",
    "docs/DOE_SOURCE_INSPECTION.md",
    "docs/DOD_MEAS7_INSPECTION.md",
)

STRATA = (
    "biomedical_health",
    "nsf",
    "dod",
    "doe_energy",
    "nasa_space",
    "agriculture_environment",
    "other_research_funders",
)

# The named prior-read reports cover 11 of 12 NASA records, so NASA's residual
# eligible stratum is a one-record census.  The three unused equal-allocation
# places go to the large residual "other" stratum; this allocation is fixed
# before outcomes and rates remain population-weighted.
TARGET_BY_STRATUM = {
    "biomedical_health": 4,
    "nsf": 4,
    "dod": 4,
    "doe_energy": 4,
    "nasa_space": 1,
    "agriculture_environment": 4,
    "other_research_funders": 7,
}


def _agency_text(record):
    return " ".join(
        str(record.get(field) or "")
        for field in ("agency", "agency_code", "title", "source")
    ).lower()


def stratum_for(record):
    text = _agency_text(record)
    if "national science foundation" in text or re.search(r"\bnsf\b", text):
        return "nsf"
    if "nasa" in text or "space administration" in text:
        return "nasa_space"
    if any(token in text for token in (
        "department of defense", "dept of the army", "army", "naval",
        "navy", "air force", "darpa", "dtra", "defense health",
        "washington headquarters services", "national geospatial",
        "engineer research and development center", "acc apg",
    )):
        return "dod"
    if any(token in text for token in (
        "office of science", "department of energy", "energy technology",
        "advanced research projects agency energy", "idaho field office",
        "nyserda", "eere", "energy efficiency and renewable",
    )):
        return "doe_energy"
    if any(token in text for token in (
        "national institutes of health", "centers for disease", "health resources",
        "food and drug administration", "indian health service", "health and human",
        "mental health", "biomedical", "healthcare research", "substance abuse",
    )):
        return "biomedical_health"
    if any(token in text for token in (
        "agriculture", "food and agriculture", "forest service", "rural business",
        "rural utilities", "natural resources conservation", "noaa", "oceanic",
        "geological survey", "fish and wildlife", "bureau of land management",
        "environmental protection agency",
    )):
        return "agriculture_environment"
    return "other_research_funders"


def _walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def prior_read_ids(catalog_ids):
    """Return catalog ids named by committed prior-read artifacts and reports."""
    found = set()
    for relative in PRIOR_READ_ARTIFACTS:
        payload = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        for value in _walk_strings(payload):
            if value in catalog_ids:
                found.add(value)
            for token in value.split():
                if token in catalog_ids:
                    found.add(token)
    for relative in PRIOR_READ_DOCS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for record_id in catalog_ids:
            pattern = rf"(?<![A-Za-z0-9:._-]){re.escape(record_id)}(?![A-Za-z0-9:._-])"
            if re.search(pattern, text):
                found.add(record_id)
    return found


def _rank(record_id, stratum):
    raw = f"{SELECTION_SEED}\0{stratum}\0{record_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _known_surface(record, attachments):
    return p7_frame.has_text_surface(record, attachments)


def _source_routes(record, attachments):
    routes = []
    designated = p7_frame.source_for_record(record)
    fallback = p7_frame.subtopic_sources.subtopic_only_primary(record)
    if designated:
        routes.append({"route": "source_for_record", **designated})
    elif fallback:
        routes.append({"route": "subtopic_only_primary", **fallback})
    for attachment in p7_frame.fetchable(attachments):
        routes.append({
            "route": "attachment_sources",
            "url": attachment.get("download_url"),
            "name": attachment.get("file_name"),
            "kind": "grants_gov_attachment",
        })
    return routes


def _record_frame_row(record, attachments):
    evidence = record.get("document_evidence") or {}
    document = evidence.get("document") or {}
    return {
        "opportunity_id": str(record["opportunity_id"]),
        "opportunity_number": record.get("opportunity_number"),
        "title": record.get("title"),
        "agency": record.get("agency"),
        "source": record.get("source"),
        "source_type": record.get("source_type"),
        "document_surface_at_selection": [r["route"] for r in _source_routes(record, attachments)],
        "source_urls_known_at_selection": _source_routes(record, attachments),
        "frozen_source_hash": document.get("sha256"),
        "prior_read_status": "not_named_in_committed_prior-read artifacts or reports",
        "reason_for_inclusion": "deterministic hash-ranked draw within agency stratum",
    }


def arm_a_frame(catalog=None, census=None):
    catalog = catalog or p7_frame.load_catalog()
    census = census if census is not None else p7_frame.load_attachment_census()
    records = catalog["opportunities"]
    catalog_ids = {str(record["opportunity_id"]) for record in records}
    excluded = prior_read_ids(catalog_ids)

    eligible = {name: [] for name in STRATA}
    for record in records:
        rid = str(record["opportunity_id"])
        attachments = census.get(rid, [])
        if record.get("status") != "posted" or rid in excluded:
            continue
        if not _known_surface(record, attachments):
            continue
        eligible[stratum_for(record)].append(record)

    strata = []
    all_selected = []
    for name in STRATA:
        ordered = sorted(
            eligible[name], key=lambda row: (_rank(str(row["opportunity_id"]), name), str(row["opportunity_id"]))
        )
        target = TARGET_BY_STRATUM[name]
        selected = ordered[:target]
        if len(selected) != target:
            raise RuntimeError(f"stratum {name} has only {len(selected)} eligible records")
        rows = [
            _record_frame_row(row, census.get(str(row["opportunity_id"]), []))
            for row in selected
        ]
        all_selected.extend(rows)
        strata.append({
            "name": name,
            "eligible_population": len(ordered),
            "sample_size": len(rows),
            "selection_weight_per_record": len(ordered) / len(rows),
            "records": rows,
        })

    return {
        "design": (
            "disproportionate stratified probability sample; four per stratum, the one-record NASA "
            "residual as a census, and the three released places assigned to the large residual other stratum; "
            "rates use eligible-population weights"
        ),
        "eligibility": (
            "committed catalog record with status=posted, at least one text surface under the existing "
            "production source-selection contract, and not named in the committed prior-read artifacts or reports"
        ),
        "seed": SELECTION_SEED,
        "selection_rule": (
            "ascending sha256(seed + NUL + stratum + NUL + opportunity_id), taking the frozen "
            "TARGET_BY_STRATUM allocation (4/4/4/4/1/4/7)"
        ),
        "sample_size": len(all_selected),
        "eligible_population": sum(len(rows) for rows in eligible.values()),
        "prior_read_exclusion_count": len(excluded),
        "prior_read_exclusion_sources": list(PRIOR_READ_ARTIFACTS + PRIOR_READ_DOCS),
        "prior_read_limitation": (
            "The legacy 40-record survey and 50-record taxonomy draws were never fully enumerated; "
            "named IDs in their reports are excluded, but DEBT-11 makes the exclusion set necessarily imperfect. "
            "No outcome-driven replacement is allowed."
        ),
        "rate_rule": (
            "Arm A record rates use stratum eligible_population/sample_size weights; unreachable, unsupported, "
            "moved, or changed sources remain separate unmeasurable states and are never converted to zero."
        ),
        "strata": strata,
    }


ARM_B_CASES = (
    {
        "hierarchy": "DOE Office of Science continuation solicitation / BES and sibling offices",
        "case_id": "doe-office-science",
        "selected_parent_ids": ["360678"],
        "expected_routes": [
            "catalog and current Grants.gov detail/attachments for DE-FOA-0003600",
            "https://science.osti.gov/grants/FOAs/FOAs/2026/DE-FOA-0003600",
            "https://science.osti.gov/bes/Research",
        ],
        "discoverability_queries": ["catalysis", "plasma physics", "isotope research"],
    },
    {
        "hierarchy": "DOE Genesis Mission challenge areas and workbook focus areas",
        "case_id": "doe-genesis",
        "selected_parent_ids": ["361526"],
        "expected_routes": ["catalog and current Grants.gov detail/attachments for DE-FOA-0003612"],
        "discoverability_queries": ["autonomous laboratories", "quantum algorithms", "subsurface strategic energy"],
    },
    {
        "hierarchy": "DOE ARPA-E eXCHANGE",
        "case_id": "doe-arpa-e",
        "selected_parent_ids": ["356623", "362036"],
        "expected_routes": ["https://arpa-e-foa.energy.gov/", "catalog and Grants.gov reconciliation"],
        "discoverability_queries": ["SCALEUP energy technology", "energy innovators"],
    },
    {
        "hierarchy": "DOE EERE Exchange",
        "case_id": "doe-eere",
        "selected_parent_ids": [],
        "expected_routes": ["https://eere-exchange.energy.gov/", "catalog and Grants.gov reconciliation"],
        "discoverability_queries": ["industrial decarbonization", "vehicle technologies", "renewable energy"],
    },
    {
        "hierarchy": "DOE HGEO / former FECM / NETL funding",
        "case_id": "doe-netl-hgeo",
        "selected_parent_ids": ["363065"],
        "expected_routes": [
            "catalog and current Grants.gov detail/attachments for DE-FOA-0003627",
            "current official DOE/NETL funding-opportunity and eXCHANGE surfaces",
        ],
        "discoverability_queries": ["carbon storage", "geothermal", "hydrocarbons"],
    },
    {
        "hierarchy": "DOE current critical-minerals organization and funding surface",
        "case_id": "doe-critical-minerals",
        "selected_parent_ids": [],
        "expected_routes": ["current official DOE organization/program pages", "catalog and Grants.gov"],
        "discoverability_queries": ["critical minerals processing", "critical minerals recycling"],
    },
    {
        "hierarchy": "DOE Office of Electricity",
        "case_id": "doe-office-electricity",
        "selected_parent_ids": [],
        "expected_routes": ["current official Office of Electricity funding page", "catalog and Grants.gov"],
        "discoverability_queries": ["grid resilience", "energy storage"],
    },
    {
        "hierarchy": "DOE Office of Nuclear Energy",
        "case_id": "doe-nuclear-energy",
        "selected_parent_ids": ["358100"],
        "expected_routes": ["current official Office of Nuclear Energy funding page", "catalog and Grants.gov"],
        "discoverability_queries": ["advanced reactor licensing", "nuclear energy research"],
    },
    {
        "hierarchy": "ARPA-H mission-office / ISO funding structure",
        "case_id": "arpa-h",
        "selected_parent_ids": [],
        "expected_routes": ["current official ARPA-H funding opportunities", "catalog and Grants.gov"],
        "discoverability_queries": [
            "derive up to three exact technical queries from the current authoritative ISO/program titles before catalog retrieval"
        ],
    },
    {
        "hierarchy": "NASA ROSES native Table 3 path",
        "case_id": "nasa-roses",
        "selected_parent_ids": [],
        "expected_routes": [
            "https://science.nasa.gov/researchers/sara/grant-solicitations/",
            "discovered current solicitation.nasaprs.com ROSES Table 3",
            "catalog and Grants.gov reconciliation",
        ],
        "discoverability_queries": ["derive exact program-element-title queries from the frozen current Table 3 rows"],
    },
    {
        "hierarchy": "NASA NSPIRES open-solicitations list residual",
        "case_id": "nasa-nspires-open-list",
        "selected_parent_ids": [],
        "expected_routes": ["https://nspires.nasaprs.com/external/solicitations/solicitations!init.do", "catalog"],
        "discoverability_queries": ["not applicable unless a verifiable net-new actionable parent is established"],
    },
    {
        "hierarchy": "DoD Army MURI / DEVCOM ARL foundational BAA",
        "case_id": "dod-muri",
        "selected_parent_ids": ["344592"],
        "expected_routes": ["catalog and current Grants.gov detail/attachments for W911NF-23-S-0001", "official ARL BAA page"],
        "discoverability_queries": ["multidisciplinary university research initiative", "quantum sensing", "energetic materials"],
    },
    {
        "hierarchy": "DoD Army TDAC referenced topics",
        "case_id": "dod-army-tdac",
        "selected_parent_ids": ["345241"],
        "expected_routes": ["catalog and Grants.gov", "https://www.army.mil/article/261533"],
        "discoverability_queries": ["derive exact applicant-selectable TDAC topic titles from the authoritative page"],
    },
    {
        "hierarchy": "DoD ONR long-range BAA",
        "case_id": "dod-onr",
        "selected_parent_ids": ["356605"],
        "expected_routes": ["catalog and Grants.gov", "https://www.onr.navy.mil/work-with-us/funding-opportunities"],
        "discoverability_queries": ["catalyst design", "quantum sensing", "power and energy"],
    },
    {
        "hierarchy": "DoD DARPA office-wide / multi-focus BAA",
        "case_id": "dod-darpa",
        "selected_parent_ids": ["362859"],
        "expected_routes": ["catalog and current Grants.gov detail/attachments for HR001126S0013"],
        "discoverability_queries": ["derive exact focus-area-title queries from the authoritative notice"],
    },
    {
        "hierarchy": "DoD AFOSR research-interest BAA",
        "case_id": "dod-afosr",
        "selected_parent_ids": ["362681"],
        "expected_routes": ["catalog and current Grants.gov detail/attachments for FA955026S0001"],
        "discoverability_queries": ["derive exact portfolio-title queries from the authoritative notice"],
    },
    {
        "hierarchy": "NOAA multi-office FY2024-2026 BAAs",
        "case_id": "noaa-baas",
        "selected_parent_ids": ["355705", "356127", "356002", "355706", "356669"],
        "expected_routes": ["catalog and Grants.gov", "current official NOAA office/funding pages"],
        "discoverability_queries": ["weather radar", "satellite remote sensing", "fisheries science"],
    },
)


def build_frame(catalog=None, census=None):
    catalog = catalog or p7_frame.load_catalog()
    return {
        "schema_version": 1,
        "purpose": "MEAS-8 outcome-blind frozen selection frame; Arm A and Arm B are separate denominators",
        "frozen_at": "2026-08-20",
        "catalog_commit": CATALOG_COMMIT,
        "catalog_date": catalog.get("generated_at"),
        "catalog_extract": (catalog.get("source") or {}).get("extract_file"),
        "catalog_record_count": len(catalog["opportunities"]),
        "outcome_blindness": (
            "Generated without network access or source-text inspection. Selected records and named hierarchy "
            "questions may not be replaced after outcomes are known."
        ),
        "arm_a": arm_a_frame(catalog, census),
        "arm_b": {
            "design": "purposive named hierarchy/discoverability sanity audit; no prevalence or confidence interval",
            "questions": {
                "B1": "Is the current actionable parent captured, deduplicated, and current?",
                "B2": "Are genuine fundable subject subdivisions recovered usefully by final production?",
                "B3": "Can current catalog/discoverability text surface an opaque parent for source-grounded technical queries?",
            },
            "additional_case_rule": (
                "Add no case after source inspection. A second additive frame commit is allowed only for an "
                "authoritative successor redirect or for a catalog-evidenced umbrella satisfying the prompt's "
                "pre-frozen inclusion conditions; record the reason and keep the original case."
            ),
            "cases": list(ARM_B_CASES),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    payload = build_frame()
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.write:
        FRAME_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    if args.check:
        if FRAME_PATH.read_text(encoding="utf-8") != rendered:
            raise SystemExit("evaluation/meas8_frame.json does not match the deterministic frame")
    if not args.write and not args.check:
        print(rendered, end="")


if __name__ == "__main__":
    main()
