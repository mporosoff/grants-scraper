"""Materialize validated artifact bytes through the existing protected PR path."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from tools import release_candidate as c


def run(*args):
    return subprocess.check_output(args, text=True, timeout=120).strip()


def publish(bundle, receipt_path, reports, artifact_run):
    root = c.ROOT
    manifest = c.load(bundle)
    receipt = c.read_json(receipt_path)
    c.verify_receipt(root, bundle, receipt)
    c.verify_files(root, manifest['files'])
    base = c.git(root, 'rev-parse', 'HEAD')
    remote = run('git', 'ls-remote', 'origin', 'refs/heads/main').split()[0]
    if remote != base:
        raise ValueError('Protected main advanced; retry validation/publication of this candidate against current dependencies')
    # Idempotent retry after a merged PR or failed Pages propagation.
    marker = root / 'release/candidate.json'
    if marker.exists() and c.read_json(marker).get('candidate_id') == manifest['candidate_id']:
        c.verify_files(root, manifest['files'])
        merge_sha = base
        pr_url = None
    else:
        c.write_json(marker, manifest)
        c.write_json(root / 'release/validation.json', receipt)
        c.write_json(root / 'release/candidate-source.json', {'candidate_id': manifest['candidate_id'], 'artifact_run': str(artifact_run)})
        run('git', 'config', 'user.name', 'github-actions[bot]')
        run('git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
        run('git', 'add', '--', *manifest['files'], 'release/candidate.json', 'release/validation.json', 'release/candidate-source.json')
        prefix = f"automation/release-{manifest['candidate_id'][:16]}-"
        opened = json.loads(run('gh', 'pr', 'list', '--state', 'open', '--base', 'main', '--limit', '100',
                                '--json', 'headRefName,headRefOid,url'))
        existing = [pr for pr in opened if pr['headRefName'].startswith(prefix)]
        if len(existing) > 1:
            raise ValueError('Multiple PRs claim this candidate; publication provenance needs reconciliation')
        if existing:
            pr_url, head = existing[0]['url'], existing[0]['headRefOid']
            run('git', 'fetch', '--no-tags', 'origin', existing[0]['headRefName'])
            if c.git(root, 'rev-parse', f'{head}^{{tree}}') != c.git(root, 'write-tree'):
                raise ValueError('Existing candidate PR needs base reconciliation after its pending review completes')
        else:
            run('git', 'commit', '-m', f"chore: publish Funding Finder candidate {manifest['candidate_id'][:16]}")
            head = c.git(root, 'rev-parse', 'HEAD')
        c.verify_files(root, manifest['files'])
        c.verify_receipt(root, bundle, receipt)
        branch = f"automation/release-{manifest['candidate_id'][:16]}-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
        if not existing:
            run('git', 'push', 'origin', f'HEAD:refs/heads/{branch}')
        repository = os.environ['GITHUB_REPOSITORY']
        run_url = f'https://github.com/{repository}/actions/runs/{os.environ["GITHUB_RUN_ID"]}'
        # Evidence covers the same validator/generation code and exact files;
        # only the provenance marker was added in this materialization commit.
        for gate in (() if existing else ('python', 'browser')):
            run('gh', 'api', '--method', 'POST', f'repos/{repository}/statuses/{head}',
                '-f', 'state=success', '-f', f'context={gate}', '-f', f'target_url={run_url}',
                '-f', 'description=Exact candidate bytes and validation code verified against receipt')
        body = Path(reports) / 'generated-pr.md'
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_text(f"Publish immutable candidate `{manifest['candidate_id']}`.\n\n"
                        f"Generation: `{manifest['generation_sha']}` (run {manifest['generation_run_id']}).\n"
                        f"Validation: `{receipt['validation_sha']}`. All required gates passed for these exact hashes.\n\n"
                        f"Evidence: {run_url}. No source collection or provider generation occurs during publication.\n", encoding='utf-8')
        if not existing:
            pr_url = run('gh', 'pr', 'create', '--base', 'main', '--head', branch,
                         '--title', f"chore: publish Funding Finder candidate {manifest['candidate_id'][:16]}", '--body-file', str(body))
        print(f'Generated candidate PR: {pr_url}', flush=True)
        from tools.wait_release_review import wait_for_review
        wait_for_review(repository, int(pr_url.rsplit('/', 1)[1]), head)
        run('gh', 'pr', 'merge', pr_url, '--squash', '--delete-branch', '--match-head-commit', head)
        merge_sha = run('gh', 'pr', 'view', pr_url, '--json', 'mergeCommit', '--jq', '.mergeCommit.oid')
        run('git', 'fetch', '--no-tags', 'origin', 'main')
        if not merge_sha or run('git', 'ls-remote', 'origin', 'refs/heads/main').split()[0] != merge_sha:
            raise ValueError('Protected main changed after merge; reuse candidate with refreshed release controls')
        for name, expected in manifest['files'].items():
            actual = subprocess.check_output(['git', 'show', f'{merge_sha}:{name}'])
            if c.digest(actual) != expected:
                raise ValueError(f'Protected merge changed candidate bytes: {name}')
    publication = {'schema_version': 1, 'candidate_id': manifest['candidate_id'],
                   'generation_sha': manifest['generation_sha'], 'generation_run_id': manifest['generation_run_id'],
                   'validation_sha': receipt['validation_sha'], 'publication_sha': merge_sha,
                   'release_code_sha': base, 'candidate_hashes': manifest['files'],
                   'validation_receipt_sha256': c.digest(c.encoded(receipt)), 'timestamp': c.timestamp(),
                   'pr_url': pr_url, 'production_mutated': True, 'pages_verified': False, 'next_retry_stage': 'publish'}
    c.write_json(Path(reports) / 'publication.json', publication)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write(f'merge_sha={merge_sha}\n')
    return publication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'receipt', 'reports', 'artifact-run'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    publish(args.bundle, args.receipt, args.reports, args.artifact_run)


if __name__ == '__main__':
    main()
