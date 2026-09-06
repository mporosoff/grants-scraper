"""Synthetic, offline Phase 2 pipeline; writes only to the caller's temp directory."""
from contextlib import ExitStack, redirect_stdout, chdir
from datetime import date, datetime, timezone
import io
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

from scripts import build_catalog, build_changes, build_feeds, build_opportunity_teams as teams
from scripts import extract_document_evidence as documents, faculty_match, researcher_registry as researchers
from scripts import subtopic_cov4, subtopic_records
from scripts.sources import __main__ as sources_cli, intake
from scripts.sources.base import CanonicalOpportunity
from .minipdf import build_pdf, heading, line

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
AS_OF = NOW.date()
NOTICE = "https://science.example.gov/research.html"
PDF_URL = "https://science.example.gov/topics.pdf"
ROLES = [
    {"id": "role-1", "label": "Heterogeneous catalysis", "required": True, "quote": "Develop heterogeneous catalyst materials."},
    {"id": "role-2", "label": "Reaction kinetics", "required": True, "quote": "Measure reaction kinetics in laboratory reactors."},
]
SCOPE = " ".join(r["quote"] for r in ROLES) + " Investigate zirconia catalysts for carbon dioxide conversion with mechanistic measurements and reproducible experiments."


class FixedDate(date):
    @classmethod
    def today(cls):
        return AS_OF


def manifest_entry(identifier="research", url=NOTICE, title="Bench-scale reaction research", description=None):
    opportunity = {"external_id": identifier, "title": title, "url": url, "agency": "Fixture Science Council",
        "opportunity_number": "FIXTURE-26-" + identifier, "description": description or
            "This notice supports a bounded laboratory investigation with explicit experimental objectives. Consult the official notice for detailed scientific requirements.",
        "status": "posted", "posted_date": "2026-09-01", "close_date": "2026-12-31",
        "award_floor": None, "award_ceiling": None, "total_program_funding": None, "eligibility_text": None}
    citations = {key: {"url": url, "quote": f"Official {key}: {value}."} for key, value in opportunity.items()
                 if value is not None and key not in {"external_id", "url"}}
    return {"kind": "record", "source_name": "Fixture Science Council", "source_type": "Federal",
            "verified_on": "2026-09-06", "review_after": "2026-09-30", "opportunity": opportunity, "citations": citations}


def html_notice(entry, scope=SCOPE):
    metadata = "".join("<p>" + c["quote"] + "</p>" for c in entry["citations"].values())
    return ("<html><body><h1>Official notice</h1>" + metadata + "<h2>Review criteria</h2><p>" + scope +
            "</p><h2>Key dates</h2><p>Full applications are due December 31, 2026. A letter of intent is due November 1, 2026 at 5:00 p.m. Eastern Time.</p>"
            "<h2>Funding</h2><p>The individual award amount range is between $500,000 and $1 million.</p></body></html>").encode()


def pdf_notice(entry):
    titles = ["Topic Area 1 Catalytic conversion", "Topic Area 2 Membrane separations", "Topic Area 3 Optical sensing"]
    bodies = [SCOPE + " Awards support fundamental heterogeneous catalysis studies that connect catalyst structure with measured reaction rates.",
        "Develop selective membranes for aqueous separations. Characterize transport mechanisms in polymer films under controlled laboratory conditions. Awards support experimental membrane fabrication and molecular transport research with independently validated measurements.",
        "Develop integrated optical sensors for trace gas detection. Characterize photon interactions with molecular absorbers through controlled spectroscopy. Awards support bounded photonic device fabrication and optical measurements with independent experimental validation."]
    pages = [[heading("Official notice")] + [line(c["quote"]) for c in entry["citations"].values()]]
    pages += [[heading(t), line(b)] for t, b in zip(titles, bodies)]
    return build_pdf(pages, outline=[(t, i + 1, 0) for i, t in enumerate(titles)])


def fixture_registry():
    rows = []
    for i, role in enumerate(ROLES, 1):
        ident = f"urh-99000{i}"
        claim = {"claim_id": ident + "-c001", "revision": 1, "status": "active", "label": role["label"],
                 "category": "Chemistry", "categories": ["Chemistry"], "type": "method",
                 "evidence": role["quote"], "source_urls": [f"https://faculty.example.edu/fixture-{i}"],
                 "evidence_level": "direct", "verified_on": "2026-09-06", "legacy_claim_ids": []}
        claim["material_hash"] = researchers.material_claim_hash(claim)
        rows.append({"researcher_id": ident, "display_name": f"Fixture Scientist {i}", "sort_name": f"Scientist {i}, Fixture",
            "legacy_ids": [f"fixture-scientist-{i}"], "aliases": [], "home_unit": "Fixture Chemistry",
            "relationship": "hajim_core_faculty", "pool_visibility": "department", "status": "active", "auto_proposable": True,
            "orcid_id": "", "research_summary": claim["evidence"], "source_urls": claim["source_urls"],
            "source_checked_date": "2026-09-06", "claims": [claim]})
    registry = {"schema_version": 3, "researchers": rows}
    registry["registry_generation"] = researchers.registry_generation(registry)
    return researchers.validate_registry(registry)


def provider_response(self, prompt, data):
    if prompt == teams.DECOMPOSE:
        specific = all(r["quote"] in data["scope"] for r in ROLES)
        value = {"specific": specific, "objective": "Investigate catalysts and reaction kinetics" if specific else "Scope lacks complementary supported scientific roles",
                 "roles": ROLES if specific else []}
    else:
        edges = [{"role_id": role["id"], "claim_id": f"urh-99000{i}-c001", "coverage": "direct",
                  "reason": "The cited synthetic researcher claim supports this exact experimental contribution."}
                 for i, role in enumerate(ROLES, 1)]
        value = {"edges": edges}
        if prompt == teams.VERIFY:
            value["suitable_for_team"] = True
    return teams.validate_response(prompt, data, value)


def response(url, content):
    return {"status_code": 200, "url": url, "content": content,
            "content_type": "application/pdf" if url.endswith(".pdf") else "text/html", "etag": '"fixture"', "last_modified": None}


def run_pipeline(directory):
    """Actual intake, merge, extraction, faculty and team command entrypoints."""
    directory = Path(directory).resolve()
    for child in ("data", "config", "assets"):
        (directory / child).mkdir(parents=True, exist_ok=True)
    for asset in (ROOT / "assets").iterdir():
        if asset.is_file():
            shutil.copyfile(asset, directory / "assets" / asset.name)
    for page in ("match_explorer.html", "team_match.html"):
        shutil.copyfile(ROOT / page, directory / page)
    entries = [manifest_entry(), manifest_entry("topics", PDF_URL, "Broad agency announcement for laboratory research"),
               manifest_entry("workshop", "https://science.example.gov/workshop.html", "Scientific workshop logistics",
                              "Organize a scientific workshop, arrange rooms and travel, and provide routine administrative support. This call supports meeting logistics and training services.")]
    duplicate = manifest_entry("duplicate", "https://science.example.gov/duplicate.html")
    entries.append(duplicate)
    payloads = {NOTICE: html_notice(entries[0]), PDF_URL: pdf_notice(entries[1]),
                entries[2]["opportunity"]["url"]: html_notice(entries[2], "Review the proposed meeting schedule, room bookings and participant travel arrangements."),
                duplicate["opportunity"]["url"]: html_notice(duplicate, "This duplicate retains the authoritative Grants.gov structured record.")}
    def fetch(url, headers=None, **kwargs):
        return response(url, payloads[url])
    (directory / "manifest.json").write_text(json.dumps({"schema_version": 1, "entries": entries}), encoding="utf-8")
    registry = fixture_registry()
    (directory / "config/researcher_registry.json").write_text(json.dumps(registry), encoding="utf-8")
    (directory / "data/researcher_directory.js").write_text("globalThis.RESEARCHER_DIRECTORY=" + json.dumps(researchers.directory_projection(registry)) + ";", encoding="utf-8")
    model = {"schema_version": 1, "method_version": "fixture", "release_state": "fixture", "source_hashes": {}, "limitations": [], "faculty": [], "opportunities": []}
    (directory / "config/opportunity_team_model.json").write_text(json.dumps(model), encoding="utf-8")
    gg = CanonicalOpportunity(**duplicate["opportunity"]).to_record(slug="gg", source="Grants.gov", source_type="Federal")
    gg.update(opportunity_id="990001", award_floor=750000, award_ceiling=2000000,
              description="A specific unrelated official structured scope with authoritative Grants.gov award facts and eligibility requirements.")
    catalog = build_catalog.build_catalog([gg], NOW, "synthetic fixture", 0)
    build_catalog.write_catalog(catalog, directory / "data/opportunities.js")
    enrich = documents.enrich_document_evidence
    with chdir(directory), ExitStack() as stack, redirect_stdout(io.StringIO()):
        stack.enter_context(patch("datetime.date", FixedDate))
        stack.enter_context(patch.object(intake, "date", FixedDate))
        stack.enter_context(patch("scripts.currentness.date", FixedDate))
        stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Fixture attempted live network")))
        stack.enter_context(patch.object(documents, "validate_public_url", side_effect=lambda url: url))
        stack.enter_context(patch.object(documents, "download_document", side_effect=fetch))
        stack.enter_context(patch("scripts.pull_grants.fetch_detail", return_value={}))
        stack.enter_context(patch.object(documents, "enrich_document_evidence", side_effect=lambda *a, **k: enrich(*a, **k, fetcher=fetch)))
        stack.enter_context(patch.object(subtopic_cov4, "classify_fundability", return_value={"fundability": "accept", "classifier_owned": True, "reason": "Fixture bounded research", "error": None, "detail": None}))
        args = ["intake", "--manifest", "manifest.json", "--inputs", "config/source_intake.json"]
        sources_cli.main(args)
        assert not Path("config/source_intake.json").exists(), "Dry run wrote maintained input"
        sources_cli.main(args + ["--accept"])
        # The same merge command and default enabled registry used by coordinated
        # refresh; unrelated native adapters use deterministic empty snapshots.
        from scripts.sources.registry import REGISTRY
        for adapter in REGISTRY:
            if adapter.enabled and adapter.slug != "maintained":
                stack.enter_context(patch.object(adapter, "collect", return_value=[]))
                stack.enter_context(patch.object(adapter, "min_records", 0))
        sources_cli.main(["merge", "--write", "--inputs", "config/source_intake.json", "--summary-output", "merge-summary.json"])
        documents.main(["--enable-subtopics", "--subtopic-cache", "data/subtopics.js", "--now", NOW.isoformat(), "--request-delay", "0", "--max-documents", "20"])
        stack.enter_context(patch.object(sys, "argv", ["faculty_match"]))
        faculty_match.main()
        stack.enter_context(patch.object(teams.Provider, "json", provider_response))
        stack.enter_context(patch.object(teams.Provider, "embed", side_effect=lambda texts, kind: [[1.0, 0.0] for _ in texts]))
        stack.enter_context(patch.object(teams.Provider, "embed_reusable", side_effect=lambda texts, kind: [[1.0, 0.0] for _ in texts]))
        with patch.object(sys, "argv", ["build_opportunity_teams", "--generate", "--write", "--workers", "1"]):
            assert teams.main() == 0
        final = documents.read_catalog("data/opportunities.js")
        build_feeds.build_feeds(final, Path("feeds"), as_of=AS_OF)
        events = build_changes.diff_catalogs(catalog, final, as_of=AS_OF)
        Path("events.json").write_text(json.dumps(events), encoding="utf-8")
    return {"catalog": final, "events": events, "registry": registry,
            "cache": documents.read_cache(directory / "data/document_evidence.json"),
            "children": subtopic_records.read_cache(directory / "data/subtopics.js"),
            "report": json.loads((directory / "evaluation/opportunity_team_generation.json").read_text(encoding="utf-8"))}


if __name__ == "__main__":
    run_pipeline(sys.argv[1])
