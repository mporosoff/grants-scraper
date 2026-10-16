"""Retain public document recovery inputs inside the same logical spend state.

This is a cache checkpoint, never a candidate or a publication-health receipt.
The document extractor must still revalidate and project every restored input.
"""
import os
from pathlib import Path
import re
import subprocess
import uuid

from tools import release_candidate as release
from tools.offline_spend import atomic_json

FILES = ('data/document_evidence.json', 'data/subtopics.js')
DIRECTORY = 'document-checkpoint'
MANIFEST = 'checkpoint.json'
FIELDS = {'schema_version', 'run_id', 'run_attempt', 'generation_sha', 'baseline_files', 'files'}


def _owner(state, run, attempt):
    if not re.fullmatch('[1-9][0-9]*', str(run)) or not re.fullmatch('[1-9][0-9]*', str(attempt)):
        raise ValueError('Document checkpoint requires its exact Actions run and attempt')
    ledger = release.read_json(Path(state) / 'ledger.json')
    if ledger.get('logical_id') != 'offline-' + str(run):
        raise ValueError('Document checkpoint does not match the original generation ledger')


def _baseline(root):
    return {name: release.digest(subprocess.check_output(
        ['git', '-C', str(root), 'show', 'HEAD:' + name])) for name in FILES}


def _atomic_bytes(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def capture(root, state, run, attempt):
    """Publish a complete checkpoint last, retaining the prior one on error."""
    root, state = Path(root), Path(state)
    _owner(state, run, attempt)
    payloads = {name: release.checked_path(root, name).read_bytes() for name in FILES}
    manifest = {'schema_version': 1, 'run_id': str(run), 'run_attempt': str(attempt),
                'generation_sha': release.git(root, 'rev-parse', 'HEAD'),
                'baseline_files': _baseline(root),
                'files': {name: release.digest(raw) for name, raw in payloads.items()}}
    checkpoint = release.checked_path(state, DIRECTORY)
    # Content-addressed blobs keep the prior manifest valid if this capture is
    # interrupted between files. No private structures or provider data enter.
    for name, raw in payloads.items():
        _atomic_bytes(release.checked_path(checkpoint, 'blobs/' + manifest['files'][name]), raw)
    atomic_json(release.checked_path(checkpoint, MANIFEST), manifest)
    return manifest


def restore(root, state, run, attempt):
    """Validate all retained bytes before replacing either extraction input."""
    root, state = Path(root), Path(state)
    _owner(state, run, attempt)
    checkpoint = release.checked_path(state, DIRECTORY)
    manifest_path = release.checked_path(checkpoint, MANIFEST)
    if not manifest_path.exists():
        return False  # Older failed runs did not retain these public outputs.
    manifest = release.read_json(manifest_path)
    if (not isinstance(manifest, dict) or set(manifest) != FIELDS
            or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1
            or manifest.get('run_id') != str(run)
            or not re.fullmatch('[1-9][0-9]*', str(manifest.get('run_attempt', '')))
            or int(manifest['run_attempt']) >= int(attempt)
            or not re.fullmatch('[a-f0-9]{40}', str(manifest.get('generation_sha', '')))
            or not isinstance(manifest.get('files'), dict) or set(manifest['files']) != set(FILES)
            or not isinstance(manifest.get('baseline_files'), dict)
            or set(manifest['baseline_files']) != set(FILES)
            or any(not re.fullmatch('[a-f0-9]{64}', str(value))
                   for key in ('files', 'baseline_files') for value in manifest[key].values())):
        raise ValueError('Document checkpoint identity is invalid; preserve the original run for recovery')
    if manifest['generation_sha'] not in release.git(root, 'rev-list', '--first-parent', 'HEAD').splitlines():
        raise ValueError('Document checkpoint generation is outside protected history')
    if manifest['baseline_files'] != _baseline(root):
        raise ValueError('Protected document inputs changed; preserve the original checkpoint for named recovery')
    payloads = {}
    for name, digest in manifest['files'].items():
        raw = release.checked_path(checkpoint, 'blobs/' + digest).read_bytes()
        if release.digest(raw) != digest:
            raise ValueError('Document checkpoint bytes changed; preserve the original run for recovery')
        payloads[name] = raw
    destinations = {name: release.checked_path(root, name) for name in FILES}
    previous = {name: path.read_bytes() for name, path in destinations.items()}
    replaced = []
    try:
        for name, path in destinations.items():
            _atomic_bytes(path, payloads[name])
            replaced.append(name)
    except BaseException:
        for name in replaced:
            _atomic_bytes(destinations[name], previous[name])
        raise
    print(f'Restored public document recovery inputs from original run {run}, attempt {manifest["run_attempt"]}; extraction health must pass again')
    return True
