"""Verify exact published bytes and Search Worker identity; never generate data."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.request import Request, urlopen

from tools import release_candidate as c

SITE = 'https://mporosoff.github.io/grants-scraper/'
WORKER = 'https://funding-finder-voyage-search.urochestercheme.workers.dev/health'


def public_path(name):
    return name == '.nojekyll' or name.endswith('.html') or name.startswith(('assets/', 'data/', 'feeds/'))


def fetch(url):
    with urlopen(Request(url, headers={'Origin': 'https://mporosoff.github.io', 'Cache-Control': 'no-cache'}), timeout=45) as response:
        return response.read()


def worker_check(manifest):
    health = json.loads(fetch(WORKER))
    expected = manifest['release_identity']
    for key, value in {'service': 'available', 'budget_state': 'available',
                       'corpus_sha256': expected['current_corpus_sha256'],
                       'model_space_fingerprint': expected['model_space_fingerprint']}.items():
        if health.get(key) != value:
            raise ValueError(f'Worker handshake mismatch: {key}')
    return {key: health.get(key) for key in ('service', 'budget_state', 'corpus_sha256', 'model_space_fingerprint')}


def worker_provenance(bundle, reports):
    """Read authenticated serving metadata now, never accept a cached live observation."""
    output = Path(reports) / 'worker-live.json'
    result = subprocess.run(['node', str(c.ROOT / 'tools/search_worker_checkpoint.mjs'), '--verify-live',
                             str(bundle), str(Path(reports) / 'worker-after.json'), str(output)],
                            capture_output=True, text=True, timeout=600)
    state = c.read_json(output) if output.exists() else {}
    if result.returncode or state.get('verified') is not True:
        raise ValueError('Worker provenance verification failed: ' + str(state.get('error', 'metadata unavailable'))[:300])
    return state


def stage_site(bundle, reports, output):
    manifest = c.load(bundle)
    publication = c.read_json(Path(reports) / 'publication.json')
    validate_publication(manifest, publication, c.read_json(Path(reports) / 'validation.json'))
    worker_provenance(bundle, reports)
    output = Path(output)
    if output.exists():
        raise ValueError('Pages staging directory must be new')
    import shutil
    for name in manifest['files']:
        if public_path(name):
            target = c.checked_path(output, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(bundle) / 'files' / name, target)
    c.write_json(output / 'release/candidate.json', manifest)
    c.write_json(output / 'release/publication.json', publication)
    (output / 'pages-release-sha.txt').write_text(publication['publication_sha'] + '\n', encoding='utf-8')
    c.verify_files(output, {k: v for k, v in manifest['files'].items() if public_path(k)})


def validate_publication(manifest, publication, validation):
    if (publication.get('schema_version') != 1
            or publication.get('candidate_id') != manifest['candidate_id']
            or publication.get('candidate_hashes') != manifest['files']
            or publication.get('generation_sha') != manifest['generation_sha']
            or publication.get('generation_run_id') != manifest['generation_run_id']
            or publication.get('validation_sha') != validation.get('validation_sha')
            or publication.get('validation_receipt_sha256') != c.digest(c.encoded(validation))
            or validation.get('candidate_id') != manifest['candidate_id']
            or validation.get('identity', {}).get('candidate_hashes') != manifest['files']
            or validation.get('gates') != {gate: 'passed' for gate in c.GATES}
            or any(not re.fullmatch(r'[a-f0-9]{40}', publication.get(key, ''))
                   for key in ('publication_sha', 'release_code_sha', 'validation_sha'))):
        raise ValueError('Publication receipt does not cover this exact candidate and validation checkpoint')


def verify(bundle, reports, *, attempts=18, sleep=time.sleep):
    manifest = c.load(bundle)
    expected_publication = c.read_json(Path(reports) / 'publication.json')
    validate_publication(manifest, expected_publication, c.read_json(Path(reports) / 'validation.json'))
    publication_query = '?publication=' + c.digest(c.encoded(expected_publication))
    paths = {name: value for name, value in manifest['files'].items() if public_path(name)}
    def check(item):
        name, expected = item
        try:
            actual = c.digest(fetch(f'{SITE}{name}?candidate={manifest["candidate_id"]}'))
            return None if actual == expected else {'path': name, 'expected': expected, 'actual': actual}
        except Exception as error:
            return {'path': name, 'error': type(error).__name__}
    report = {'candidate_id': manifest['candidate_id'], 'timestamp': c.timestamp(), 'next_retry_stage': 'verify', 'production_mutated': False, 'verified': False}
    for attempt in range(attempts):
        with ThreadPoolExecutor(max_workers=8) as executor:
            differences = [x for x in executor.map(check, paths.items()) if x]
        report['differences'] = differences
        try:
            live_manifest = json.loads(fetch(SITE + 'release/candidate.json' + publication_query))
            live_publication = json.loads(fetch(SITE + 'release/publication.json' + publication_query))
            stamp = fetch(SITE + 'pages-release-sha.txt' + publication_query).decode('utf-8')
            if (live_manifest != manifest or live_publication != expected_publication
                    or stamp != expected_publication['publication_sha'] + '\n'):
                raise ValueError('Live release identity mismatch')
            report['publication_sha'] = expected_publication['publication_sha']
            report['publication_receipt_sha256'] = c.digest(c.encoded(expected_publication))
            report['worker'] = worker_check(manifest)
            if not differences:
                report['worker_provenance'] = worker_provenance(bundle, reports)
            report.pop('handshake_error', None)
        except Exception as error:
            report['handshake_error'] = str(error)[:300]
        c.write_json(Path(reports) / 'live-verification.json', report)
        if not differences and 'handshake_error' not in report:
            report.update(verified=True, next_retry_stage=None, live_release_identity=manifest['release_identity'])
            c.write_json(Path(reports) / 'live-verification.json', report)
            print(json.dumps(report))
            return report
        print(f'Candidate {manifest["candidate_id"]}: propagation attempt {attempt + 1}/{attempts}, {len(differences)} byte mismatches', flush=True)
        if attempt + 1 < attempts:
            sleep(10)
    raise ValueError('Live verification failed; retry verify/publication using the same candidate')


def complete_live(bundle, reports, asset_outcome, provider_outcome):
    """Close the provider-smoke interval with a fresh authenticated serving check."""
    path = Path(reports) / 'live-verification.json'
    report = c.read_json(path) if path.exists() else {'candidate_id': c.load(bundle)['candidate_id']}
    ready = report.get('verified') is True and asset_outcome == provider_outcome == 'success'
    report.update(verified=False, asset_verification=asset_outcome, provider_smoke=provider_outcome,
                  next_retry_stage='verify', completed_at=c.timestamp())
    c.write_json(path, report)
    try:
        if ready:
            report['worker_provenance'] = worker_provenance(bundle, reports)
            report.update(verified=True, next_retry_stage=None)
    except Exception as error:
        report['worker_provenance_error'] = str(error)[:400]
    c.write_json(path, report)
    if not report['verified']:
        raise ValueError('Complete live verification failed; retain candidate and retry verify')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['stage', 'worker', 'verify', 'complete'])
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--reports', type=Path, default=Path('release-reports'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--asset-outcome')
    parser.add_argument('--provider-outcome')
    args = parser.parse_args()
    if args.command == 'stage':
        stage_site(args.bundle, args.reports, args.output)
    elif args.command == 'worker':
        for attempt in range(12):
            try:
                print(json.dumps(worker_check(c.load(args.bundle))))
                return
            except Exception:
                if attempt == 11:
                    raise
                time.sleep(5)
    elif args.command == 'complete':
        complete_live(args.bundle, args.reports, args.asset_outcome, args.provider_outcome)
    else:
        verify(args.bundle, args.reports)


if __name__ == '__main__':
    main()
