"""Verify exact published bytes and Search Worker identity; never generate data."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import time
import requests

from tools import release_candidate as c

SITE = 'https://mporosoff.github.io/grants-scraper/'
WORKER = 'https://funding-finder-voyage-search.urochestercheme.workers.dev/health'
HTTP_PROFILE = 'funding-finder-release-http-1'
HTTP_HEADERS = {
    'Accept': 'application/json',
    'Origin': 'https://mporosoff.github.io',
    'Cache-Control': 'no-cache',
    'User-Agent': 'FundingFinder-ReleaseVerifier/1.0 (+https://github.com/mporosoff/grants-scraper)',
}


class ProbeHTTPError(ValueError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__('Release HTTP probe failed: ' + json.dumps(diagnostic, sort_keys=True))


def http_diagnostic(response, body):
    """Retain protocol identifiers only, never arbitrary response/source text."""
    def header(name):
        return re.sub(r'[^\x20-\x7e]', '', response.headers.get(name, ''))[:160]
    result = {'http_profile': HTTP_PROFILE, 'status': response.status_code,
              'content_type': header('Content-Type'), 'server': header('Server'),
              'cf_ray': header('CF-Ray'), 'response_source': 'unknown'}
    text = body.decode('utf-8', errors='replace')
    match = re.search(r'\berror(?:\s+code)?\s*:?\s*(1\d{3})\b', text, re.I)
    if 'cloudflare' in result['server'].lower() and match:
        result.update(cloudflare_error_code=int(match[1]), response_source='cloudflare_edge',
                      worker_application_response=False)
    elif result['content_type'].startswith('application/json'):
        try:
            code = json.loads(text)['error']['code']
            if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,64}', code):
                result.update(worker_error_code=code, response_source='worker_error_contract',
                              worker_application_response=True)
        except (ValueError, KeyError, TypeError):
            pass
    return result


# Existing public browser imports used by assets/dod-awards-browser.mjs.
# Keep this exact closure bounded; other Worker code/configuration stays private.
PUBLIC_BROWSER_IMPORTS = frozenset(['workers/award-api/src/adapters/dod.js', 'workers/award-api/src/institutions.js', 'workers/award-api/src/ror.js', 'workers/award-api/src/snapshot.js', 'workers/award-api/src/http.js', 'workers/award-api/src/contract.js', 'workers/award-api/src/year-filter.js', 'config/award_institutions.json'])


def public_path(name):
    return name in PUBLIC_BROWSER_IMPORTS or name.endswith('.html') or name.startswith(('assets/', 'data/', 'feeds/'))


def pages_path(name):
    # .nojekyll controls Pages processing but is not an HTTP-served asset.
    # Keep it in the immutable bundle, protected merge and hashed staging tree.
    return name == '.nojekyll' or public_path(name)


def fetch(url):
    # Identify this machine client truthfully; do not inherit urllib's implicit
    # signature or follow a redirect to a different release/security surface.
    with requests.get(url, headers=HTTP_HEADERS.copy(), timeout=45,
                      allow_redirects=False, stream=True) as response:
        if response.status_code != 200:
            body = next(response.iter_content(chunk_size=8192), b'')
            raise ProbeHTTPError(http_diagnostic(response, body))
        return response.content


def worker_check(manifest):
    health = json.loads(fetch(WORKER))
    expected = manifest['release_identity']
    for key, value in {'service': 'available', 'budget_state': 'available',
                       'corpus_sha256': expected['current_corpus_sha256'],
                       'model_space_fingerprint': expected['model_space_fingerprint']}.items():
        if health.get(key) != value:
            raise ValueError(f'Worker handshake mismatch: {key}')
    return {key: health.get(key) for key in ('service', 'budget_state', 'corpus_sha256', 'model_space_fingerprint')}


def verify_worker(bundle, reports, *, attempts=12, sleep=time.sleep):
    manifest = c.load(bundle)
    report = {'candidate_id': manifest['candidate_id'], 'http_profile': HTTP_PROFILE,
              'verified': False, 'failures': [], 'next_retry_stage': 'publish'}
    path = Path(reports) / 'worker-handshake.json'
    for attempt in range(attempts):
        report.update(timestamp=c.timestamp(), attempt=attempt + 1)
        try:
            report['worker'] = worker_check(manifest)
        except Exception as error:
            failure = {'attempt': attempt + 1, 'error': type(error).__name__}
            if isinstance(error, ProbeHTTPError):
                failure['http'] = error.diagnostic
            else:
                failure['detail'] = str(error)[:300]
            report['failures'].append(failure)
            c.write_json(path, report)
            print(json.dumps({'candidate_id': manifest['candidate_id'], **failure}), flush=True)
            if attempt + 1 == attempts:
                raise ValueError('Worker handshake failed; retain candidate and inspect worker-handshake.json') from error
            sleep(5)
        else:
            report.update(verified=True, next_retry_stage=None)
            c.write_json(path, report)
            print(json.dumps(report))
            return report


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
        if pages_path(name):
            target = c.checked_path(output, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(bundle) / 'files' / name, target)
    c.write_json(output / 'release/candidate.json', manifest)
    c.write_json(output / 'release/publication.json', publication)
    (output / 'pages-release-sha.txt').write_text(publication['publication_sha'] + '\n', encoding='utf-8')
    c.verify_files(output, {k: v for k, v in manifest['files'].items() if pages_path(k)})


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
            return {'path': name, 'error': type(error).__name__,
                    **({'http': error.diagnostic} if isinstance(error, ProbeHTTPError) else {})}
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
            if isinstance(error, ProbeHTTPError):
                report.setdefault('http_failures', []).append({'attempt': attempt + 1, **error.diagnostic})
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
        verify_worker(args.bundle, args.reports)
    elif args.command == 'complete':
        complete_live(args.bundle, args.reports, args.asset_outcome, args.provider_outcome)
    else:
        verify(args.bundle, args.reports)


if __name__ == '__main__':
    main()
