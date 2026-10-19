"""Protected orchestration for the retained catalog's program-area correction."""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from tools import release_candidate as release
from tools import program_area_revalidation as recovery


def correction_pending(root):
    """Only the known old extractor projection holds automatic paid work."""
    manifest = release.read_json(Path(root) / "release/candidate.json")
    from tools.release_dependencies import candidate_groups
    source = candidate_groups(root, manifest)["source"]["files"]
    # The public September 27 catalog predates the later budget-wrapper fix;
    # both it and the retained September 28 parent contain the faulty matcher.
    uncorrected = {recovery.PARENT_EXTRACTOR_SHA256,
        "68fa1d7149eae53c27d75ffcc8e168398500cbf663542a5f4faf104ba9788d68"}
    return source.get("scripts/extract_document_evidence.py") in uncorrected


def plan(root, environment):
    expected = {
        "GITHUB_REPOSITORY": "mporosoff/grants-scraper",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_WORKFLOW_REF": "mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main",
    }
    if any(environment.get(k) != v for k, v in expected.items()):
        raise ValueError("Program-area revalidation requires the exact retained candidate and protected manual workflow")
    if any(environment.get(k) for k in ("RECEIPT_RUN", "PUBLICATION_RUN", "PUBLICATION_ATTEMPT")) or environment.get("QUALIFICATION_PILOT") == "true":
        raise ValueError("Program-area revalidation cannot be combined with other recovery or team selectors")
    selector = environment.get("REQUESTED_STAGE") or "program-area-revalidation"
    if selector not in {"program-area-revalidation", "submission-revalidation"}:
        raise ValueError("Cached evidence revalidation requires a named supported projection")
    projection_kind = "administrative_submission" if selector == "submission-revalidation" else "program_area"
    run, identifier = environment.get("CANDIDATE_RUN", ""), environment.get("CANDIDATE_ID", "")
    if (not re.fullmatch(r"[1-9][0-9]*", run) or not re.fullmatch(r"[a-f0-9]{64}", identifier)
            or (run == str(recovery.PARENT_RUN)) != (identifier == recovery.PARENT_CANDIDATE)):
        raise ValueError("Program-area revalidation requires one exact candidate run and identity")
    # The historical policy stays isolated. Modern selectors are authenticated
    # against their native candidate and original budget before any work starts.
    mode = "legacy" if identifier == recovery.PARENT_CANDIDATE else "modern"
    if mode == "legacy" and projection_kind != "program_area":
        raise ValueError("Submission revalidation requires a modern native generation checkpoint")
    return {
        "stage": "program-area-revalidation", "release_sha": release.git(root, "rev-parse", "HEAD"),
        "candidate_run": run, "candidate_id": identifier, "program_area_mode": mode, "projection_kind": projection_kind,
        "openai": "false", "anthropic": "false", "team_mode": "maintenance",
        "reason": ("Correct retained administrative submission dates; preserve source, document and team work, and use only the original vector allowance when required"
            if projection_kind == "administrative_submission" else
            "Correct retained program-area evidence and its coherent vectors; preserve original source, document allowance and team outputs"),
    }


def update_references(root):
    """Bind the current HTML and statistics to retained public data only."""
    root = Path(root)
    subprocess.run([sys.executable, "-m", "scripts.update_catalog_docs"], cwd=root, check=True)
    from scripts.faculty_match import update_version_target as faculty_reference
    from scripts.import_opportunity_team_model import update_version_target as team_reference
    faculty_reference(root / "team_match.html", root / "data/faculty_matches.js")
    model = release.read_json(root / "config/opportunity_team_model.json")
    for name in ("team_match.html", "match_explorer.html"):
        team_reference(root / name, model["generation_id"])


def persist(root, parent_bundle, receipt, bundle, state=None):
    modern = release.read_json(receipt).get('version') == recovery.MODERN_VERSION
    if modern and state is None:
        raise ValueError('Modern program-area correction requires its original budget state')
    previous = os.environ.get('PROGRAM_AREA_VECTOR_STATE')
    try:
        if modern:
            os.environ['PROGRAM_AREA_VECTOR_STATE'] = str(state)
        value = release.create(root, bundle, parent=parent_bundle, program_area_revalidation=receipt)
    finally:
        if modern:
            if previous is None:
                os.environ.pop('PROGRAM_AREA_VECTOR_STATE', None)
            else:
                os.environ['PROGRAM_AREA_VECTOR_STATE'] = previous
    if modern:
        recovery.record_modern_candidate(state, bundle)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf8") as output:
            output.write("candidate_id=" + value["candidate_id"] + "\n")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("persist", "references"), nargs="?", default="persist")
    parser.add_argument("--parent-bundle", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--state", type=Path)
    args = parser.parse_args()
    if args.action == "references":
        update_references(release.ROOT)
    else:
        if not all((args.parent_bundle, args.receipt, args.bundle)):
            parser.error("persist requires --parent-bundle, --receipt and --bundle")
        persist(release.ROOT, args.parent_bundle, args.receipt, args.bundle, args.state)


if __name__ == "__main__":
    main()
