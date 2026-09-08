"""A workflow rerun cannot repeat a completed, persisted expensive generation."""
import json
import os
from pathlib import Path
import subprocess

from tools.fetch_release_artifact import fetch
from tools import release_candidate as c


def main():
    repo, run = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_RUN_ID']
    response = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/actions/runs/{run}/artifacts?per_page=100'], timeout=60))
    artifacts = [a for a in response['artifacts'] if a['name'].startswith('candidate-') and not a['expired']]
    if not artifacts:
        return
    if len(artifacts) != 1:
        raise ValueError('Ambiguous generation checkpoint; select an exact candidate through resume')
    bundle = Path(os.environ['RUNNER_TEMP']) / 'candidate'
    fetch(repo, run, artifacts[0]['name'], bundle)
    manifest = c.load(bundle, artifacts[0]['name'].removeprefix('candidate-'))
    c.verify_dependencies(c.ROOT, manifest)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f"candidate_id={manifest['candidate_id']}\n")
    print(f"Reusing completed generation {manifest['candidate_id']}; source/provider work is skipped")


if __name__ == '__main__':
    main()
