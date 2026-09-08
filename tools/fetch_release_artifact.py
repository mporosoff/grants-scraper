"""Download one immutable artifact only from the protected release workflow."""
import argparse
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile

from tools.release_candidate import checked_path


def fetch(repository, run, name, destination):
    if not re.fullmatch(r'[1-9][0-9]*', str(run)) or not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('Invalid release artifact selector')
    def api(path):
        return subprocess.check_output(['gh', 'api', f'repos/{repository}/{path}'], timeout=60)
    meta = json.loads(api(f'actions/runs/{run}'))
    if meta['head_branch'] != 'main' or meta['path'] != '.github/workflows/refresh-opportunities.yml' or meta['event'] not in ('push', 'schedule', 'workflow_dispatch'):
        raise ValueError('Candidate evidence must originate in the protected release workflow on main')
    artifacts = json.loads(api(f'actions/runs/{run}/artifacts?per_page=100'))['artifacts']
    matches = [a for a in artifacts if a['name'] == name and not a['expired']]
    if not matches and not name.startswith('candidate-'):
        # Reports are append-only across workflow attempts. Select the latest
        # attempt, never overwrite an earlier failed or successful receipt.
        attempts = [a for a in artifacts if re.fullmatch(re.escape(name) + r'-[1-9][0-9]*', a['name']) and not a['expired']]
        if attempts:
            latest = max(int(a['name'].rsplit('-', 1)[1]) for a in attempts)
            matches = [a for a in attempts if a['name'] == f'{name}-{latest}']
    if len(matches) != 1:
        raise ValueError('No unique retained artifact; do not substitute a cache or regenerate on retry')
    with zipfile.ZipFile(io.BytesIO(api(f"actions/artifacts/{matches[0]['id']}/zip"))) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            target = checked_path(destination, item.filename)
            if target.exists():
                raise ValueError('Artifact destination must be empty')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repository', 'run', 'name', 'destination'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    fetch(args.repository, args.run, args.name, Path(args.destination))


if __name__ == '__main__':
    main()
