"""Read-only validation of an already persisted release, with durable reports."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

from tools import release_candidate as candidate


def final_integration(root, bundle, reports, previous=None, *, execute=subprocess.run):
    """Explicit manual browser validation of the already assembled candidate."""
    root, bundle, reports = Path(root), Path(bundle), Path(reports)
    ordinary = candidate.read_json(reports / 'validation.json')
    manifest = candidate.verify_receipt(root, bundle, ordinary, require_final=False)
    identity = candidate.final_integration_identity(root, manifest)
    # Persist the requested gate before any browser work. A failed/interrupted
    # invocation must not leave a receipt accepted by publication on retry.
    ordinary['final_integration'] = {'identity': identity, 'passed': False}
    candidate.write_json(reports / 'validation.json', ordinary)
    if previous and Path(previous).exists():
        prior = candidate.read_json(previous)
        if prior.get('identity') == identity and prior.get('passed') is True:
            candidate.write_json(reports / 'final-integration.json', prior)
            ordinary['final_integration']['passed'] = True
            candidate.write_json(reports / 'validation.json', ordinary)
            return prior
    candidate.materialize(root, bundle)
    report = {'identity': identity, 'passed': False, 'new_generation_calls': 0,
              'validation_sha': candidate.git(root, 'rev-parse', 'HEAD'), 'timestamp': candidate.timestamp()}
    try:
        execute(['pnpm', 'exec', 'playwright', 'install', '--with-deps', 'chromium'], cwd=root, timeout=600, check=True)
        result = execute(['pnpm', 'test:e2e'], cwd=root, timeout=2100, check=False)
        stats = candidate.read_json(root / 'test-results/playwright-results.json').get('stats', {})
        report['stats'] = stats
        candidate.verify_files(root, manifest['files'])
        report['passed'] = result.returncode == 0 and stats.get('expected', 0) > 0 and stats.get('unexpected') == 0
    finally:
        if (root / 'test-results').exists():
            shutil.copytree(root / 'test-results', reports / 'browser-results', dirs_exist_ok=True)
        candidate.write_json(reports / 'final-integration.json', report)
    if not report['passed']:
        raise ValueError('Final browser integration failed; retain the exact candidate and test evidence')
    ordinary['final_integration']['passed'] = True
    candidate.write_json(reports / 'validation.json', ordinary)
    return report


def validate(root, bundle, reports, previous=None, *, execute=subprocess.run, require_final_integration=False):
    root, bundle, reports = Path(root), Path(bundle), Path(reports)
    manifest = candidate.load(bundle)
    candidate.verify_dependencies(root, manifest)
    if previous and Path(previous).exists():
        receipt = candidate.read_json(previous)
        try:
            candidate.verify_receipt(root, bundle, receipt, require_final=False)
        except ValueError:
            pass
        else:
            if require_final_integration:
                receipt.setdefault('final_integration', {'passed': False})
            candidate.write_json(reports / 'validation.json', receipt)
            print('Reusing exact candidate validation receipt; no gates or generation repeated')
            return receipt
    candidate.materialize(root, bundle)
    identity = candidate.validation_identity(root, manifest)
    commands = {
        'package-integrity': ['node', 'tools/build_search_release_package.mjs', '--check'],
        'python': ['python', '-m', 'tools.run_refresh_validation'],
        'browser': ['node', '--test', *sorted(str(p.relative_to(root)) for p in (root / 'tests/browser').glob('*.test.mjs'))],
        'frozen-query': ['node', 'tools/query_baseline.mjs', '--check'],
        'scoring': ['node', 'tools/p9_scoring_probe.mjs', '--check'],
        'no-drift': ['bash', 'tools/verify_no_drift.sh'],
        'notice-projection': ['python', '-m', 'tools.verify_notice_publication', '--candidate-id', manifest['candidate_id'],
                              '--output', str(reports.resolve() / 'notice-projection.json')],
    }
    report = {'candidate_id': manifest['candidate_id'], 'generation_sha': manifest['generation_sha'],
              'validation_sha': candidate.git(root, 'rev-parse', 'HEAD'), 'timestamp': candidate.timestamp(),
              'identity': identity, 'gates': {}, 'production_mutated': False, 'next_retry_stage': 'validate'}
    if require_final_integration or (previous and Path(previous).exists()
            and candidate.read_json(previous).get('candidate_id') == manifest['candidate_id']
            and 'final_integration' in candidate.read_json(previous)):
        report['final_integration'] = {'passed': False}
    reports.mkdir(parents=True, exist_ok=True)
    # Run every deterministic gate once and retain all findings in one report.
    # No provider credentials are present in this job. Subprocess output remains
    # in Actions logs; only structured safe diagnostics enter report artifacts.
    try:
        for name, command in commands.items():
            print(f"candidate {manifest['candidate_id']} -> check {name}", flush=True)
            result = execute(command, cwd=root, timeout=1200, check=False)
            report['gates'][name] = 'passed' if result.returncode == 0 else 'failed'
            candidate.load(bundle)  # Never trust a validator to preserve bytes.
            candidate.verify_files(root, manifest['files'])
            candidate.write_json(reports / 'validation-report.json', report)
    finally:
        candidate.write_json(reports / 'validation-report.json', report)
        candidate.load(bundle)
    if report['gates'] != {name: 'passed' for name in candidate.GATES}:
        raise ValueError('Candidate validation failed; retain this artifact and retry validate')
    report['next_retry_stage'] = 'publish'
    candidate.write_json(reports / 'validation.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--final-integration', action='store_true', help='Explicit manual E2E/accessibility on the already validated package')
    parser.add_argument('--require-final-integration', action='store_true',
                        default=os.environ.get('FINAL_INTEGRATION_REQUIRED') == 'true')
    args = parser.parse_args()
    try:
        if args.final_integration:
            final_integration(candidate.ROOT, args.bundle, args.reports, args.previous)
        else:
            validate(candidate.ROOT, args.bundle, args.reports, args.previous,
                     require_final_integration=args.require_final_integration)
    except Exception as error:
        # Dependency/provenance failures also need retained evidence even when
        # they precede the first gate. No provider credentials exist here.
        candidate.write_json(args.reports / 'failure.json', {
            'stage': 'validate', 'check': type(error).__name__, 'diagnostic': str(error)[:2000],
            'candidate_id': os.environ.get('CANDIDATE_ID', 'unresolved'),
            'validation_sha': candidate.git(candidate.ROOT, 'rev-parse', 'HEAD'),
            'timestamp': candidate.timestamp(), 'production_mutated': False,
            'next_retry_stage': 'generate' if 'Generation dependencies changed' in str(error) or 'Generation data input changed' in str(error) else 'validate'})
        raise


if __name__ == '__main__':
    main()
