"""Download one immutable artifact only from the protected release workflow."""
import argparse
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile

from tools.release_candidate import checked_path


class ArtifactUnavailable(ValueError):
    pass


def run_artifacts(run, api, *, repository=None):
    """Collect complete bounded evidence before choosing any run checkpoint."""
    if not re.fullmatch(r'[1-9][0-9]*', str(run)):
        raise ValueError('Invalid release run selector')
    artifacts = []
    for page in range(1, 101):
        value = json.loads(api(f'actions/runs/{run}/artifacts?per_page=100&page={page}'))
        rows = value['artifacts']
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError('Invalid release artifact page')
        artifacts.extend(rows)
        if len(rows) < 100:
            if value.get('total_count', len(artifacts)) > len(artifacts):
                raise ValueError('Release artifact history is incomplete')
            if repository is not None:
                from tools.release_checkpoint_archive import preserved_artifacts
                artifacts = merge_artifacts(artifacts, preserved_artifacts(repository, run, api=api))
            return artifacts
    raise ValueError('Release artifact evidence exceeds bounded lookup')


def merge_artifacts(native, preserved):
    """Keep original identities and never replace conflicting or newer evidence."""
    result = list(native)
    if not preserved:
        return result
    positions = {}
    for index, artifact in enumerate(result):
        if artifact['id'] in positions:
            raise ValueError('Conflicting native artifact identities')
        positions[artifact['id']] = index
    for artifact in preserved:
        index = positions.get(artifact['id'])
        if index is None:
            positions[artifact['id']] = len(result)
            result.append(artifact)
            continue
        previous = result[index]
        if any(previous.get(key) != artifact.get(key) for key in ('name', 'digest', 'workflow_run')):
            raise ValueError('Native and preserved artifact identities disagree')
        if previous.get('expired') is not False:
            result[index] = artifact
    return result


def repository_artifacts(repository, api, *, candidate=None, task_prefix=None):
    """Order native and preserved receipts together before selecting a result."""
    artifacts = []
    for page in range(1, 101):
        value = json.loads(api(f'actions/artifacts?per_page=100&page={page}'))
        rows = value['artifacts']
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError('Invalid repository release artifact page')
        artifacts.extend(rows)
        if len(rows) < 100:
            if value.get('total_count', len(artifacts)) > len(artifacts):
                raise ValueError('Repository release artifact history is incomplete')
            from tools.release_checkpoint_archive import preserved_artifacts
            preserved = preserved_artifacts(repository, candidate=candidate, task_prefix=task_prefix,
                                            inventory=artifacts, api=api)
            return merge_artifacts(artifacts, preserved)
    raise ValueError('Repository release evidence exceeds bounded lookup')


def artifact_bytes(repository, run, artifact, api):
    """Read exact native ZIP bytes or reauthenticate their independent archive."""
    if '_checkpoint_archive' in artifact:
        from tools.release_checkpoint_archive import read_preserved_artifact
        return read_preserved_artifact(repository, run, artifact, api=api)
    return api(f"actions/artifacts/{artifact['id']}/zip")


def reconstruct(repository, run, name, destination, *, root=None):
    """Recover exact public bytes from their protected publication, never a receipt."""
    from tools import release_candidate as c
    if not re.fullmatch(r'candidate-[a-f0-9]{64}', name):
        raise ArtifactUnavailable('Validation/publication receipt unavailable; validate again or restore retained evidence')
    candidate_id = name[len('candidate-'):]
    root = c.ROOT if root is None else Path(root)
    history = c.git(root, 'log', 'origin/main', '--first-parent', '--format=%H', '-100', '--', 'release/candidate-source.json').splitlines()
    for sha in history:
        def read(path):
            return subprocess.check_output(['git', '-C', str(root), 'show', f'{sha}:{path}'])
        pointer = json.loads(read('release/candidate-source.json'))
        if pointer != {'candidate_id': candidate_id, 'artifact_run': str(run)}:
            continue
        manifest = json.loads(read('release/candidate.json'))
        if manifest.get('candidate_id') != candidate_id:
            raise ValueError('Protected candidate pointer/manifest conflict')
        for path, expected in manifest['files'].items():
            content = read(path)
            if c.digest(content) != expected:
                raise ValueError('Protected recovery bytes do not match candidate: ' + path)
            target = checked_path(Path(destination) / 'files', path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        c.write_json(Path(destination) / c.MANIFEST, manifest)
        c.load(destination, candidate_id)
        proof = {'recovered_candidate': candidate_id, 'protected_sha': sha, 'generation_sha': manifest['generation_sha']}
        print(json.dumps(proof))
        return proof
    raise ArtifactUnavailable('Exact candidate unavailable from artifacts or protected history; request a new candidate explicitly')


def fetch(repository, run, name, destination):
    if not re.fullmatch(r'[1-9][0-9]*', str(run)) or not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('Invalid release artifact selector')
    def api(path):
        return subprocess.check_output(['gh', 'api', f'repos/{repository}/{path}'], timeout=60)
    meta = json.loads(api(f'actions/runs/{run}'))
    if meta['head_branch'] != 'main' or meta['path'] != '.github/workflows/refresh-opportunities.yml' or meta['event'] not in ('push', 'schedule', 'workflow_dispatch'):
        raise ValueError('Candidate evidence must originate in the protected release workflow on main')
    artifacts = run_artifacts(run, api, repository=repository)
    matches = [a for a in artifacts if a['name'] == name]
    if not matches and not name.startswith('candidate-'):
        # Reports are append-only across workflow attempts. Select the latest
        # attempt, never overwrite an earlier failed or successful receipt.
        attempts = [a for a in artifacts if re.fullmatch(re.escape(name) + r'-[1-9][0-9]*', a['name'])]
        if attempts:
            latest = max(int(a['name'].rsplit('-', 1)[1]) for a in attempts)
            matches = [a for a in attempts if a['name'] == f'{name}-{latest}']
    if len(matches) > 1:
        raise ValueError('Conflicting artifact identities; do not substitute a cache or regenerate on retry')
    if not matches or matches[0].get('expired') is not False:
        print(json.dumps({'artifact_name': name, 'run': str(run),
                          'artifact_status': 'expired' if matches else 'missing',
                          'next_action': 'verify_exact_protected_reconstruction'}))
        reconstruct(repository, run, name, destination)
        return meta
    with zipfile.ZipFile(io.BytesIO(artifact_bytes(repository, run, matches[0], api))) as archive:
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
