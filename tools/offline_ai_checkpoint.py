"""Restore protected evaluation accounting; never treat a cache as spending truth."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import zipfile

from tools.offline_ai import atomic_json, config, identity
from tools.evaluate_offline_ai import TASK
from tools.release_candidate import checked_path
from tools.fetch_release_artifact import artifact_bytes, repository_artifacts

WORKFLOW = ".github/workflows/offline-ai-evaluation.yml"
PILOT_WORKFLOW = ".github/workflows/refresh-opportunities.yml"
PREFIX = "offline-ai-" + TASK


def api(repository, path):
    return subprocess.check_output(["gh", "api", f"repos/{repository}/{path}"], timeout=60)


def prepare(repository, destination, reservation):
    # A pilot's newest task allowance may survive only in the independent
    # release archive. Select by original artifact ID across both transports
    # before restoring, or an older native task ledger could erase its charges.
    artifacts = [item for item in repository_artifacts(repository, lambda path: api(repository, path), task_prefix=PREFIX)
                 if item['name'].startswith(PREFIX + '-')]
    reservations = sorted((a for a in artifacts if "-reservation-" in a["name"]), key=lambda a: a["id"])
    if not reservations:
        if artifacts:
            raise ValueError("evaluation_spend_checkpoint_missing_reservation; retained task evidence cannot reset its allowance")
        prior = json.loads(api(repository, "actions/workflows/offline-ai-evaluation.yml/runs?event=workflow_dispatch&branch=main&per_page=100"))["workflow_runs"]
        if any(str(run["id"]) != os.environ["GITHUB_RUN_ID"] for run in prior):
            raise ValueError("prior_evaluation_has_no_spend_evidence; budget cannot be reset")
    if reservations:
        latest = reservations[-1]
        expected = latest["name"].replace("-reservation-", "-state-")
        states = [a for a in artifacts if a["name"] == expected]
        if len(states) != 1 or states[0]["expired"]:
            raise ValueError("evaluation_spend_checkpoint_missing_or_expired; remaining budget is conservatively unavailable")
        task_states = [a for a in artifacts if a['name'].startswith(PREFIX + '-state-')]
        if max(task_states, key=lambda a: a['id'])['name'] != expected:
            raise ValueError("evaluation_spend_checkpoint_unpaired_latest_state; older accounting cannot replace newer task evidence")
        selected = states[0]
        run = json.loads(api(repository, f"actions/runs/{selected['workflow_run']['id']}"))
        if run["path"] not in (WORKFLOW, PILOT_WORKFLOW) or run["head_branch"] != "main" or run["event"] != "workflow_dispatch":
            raise ValueError("untrusted_evaluation_checkpoint")
        with zipfile.ZipFile(io.BytesIO(artifact_bytes(repository, str(run['id']), selected,
                                                     lambda path: api(repository, path)))) as archive:
            for item in archive.infolist():
                if not item.is_dir():
                    target = checked_path(destination, item.filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(item))
        if not (destination / "ledger.json").is_file():
            raise ValueError("missing_spend_ledger")
    reservation_value = {"task": TASK, "run_id": os.environ["GITHUB_RUN_ID"],
        "attempt": os.environ["GITHUB_RUN_ATTEMPT"], "sha": os.environ["GITHUB_SHA"],
        "maximum_logical_spend_usd": json.loads(Path('config/sonnet_production_qualification.json').read_bytes())['authorization']['cumulative_usd'],
        "prior_state_hash": identity(json.loads((destination / "ledger.json").read_bytes())) if (destination / "ledger.json").exists() else None}
    atomic_json(reservation, reservation_value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--reservation", type=Path, required=True)
    args = parser.parse_args()
    prepare(os.environ["GITHUB_REPOSITORY"], args.state, args.reservation)


if __name__ == "__main__":
    main()
