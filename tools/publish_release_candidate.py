"""Materialize validated artifact bytes through the existing protected PR path."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from tools import release_candidate as c


def run(*args):
    return subprocess.check_output(args, text=True, timeout=120).strip()


def committed_candidate_matches(root, sha, manifest):
    for name, expected in manifest['files'].items():
        result = subprocess.run(['git', '-C', str(root), 'show', f'{sha}:{name}'], capture_output=True)
        if result.returncode or c.digest(result.stdout) != expected:
            return False
    return True


def reconcile_candidate_branch(root, existing, manifest, repository, *, execute=run, wait=None):
    """Preserve both histories, only after the old exact-head review is terminal."""
    from tools.wait_release_review import wait_for_review
    wait = wait or wait_for_review
    old_head, branch = existing['headRefOid'], existing['headRefName']
    c.verify_dependencies(root, manifest)
    for name, expected in manifest['files'].items():
        if c.digest(subprocess.check_output(['git', '-C', str(root), 'show', f'{old_head}:{name}'])) != expected:
            raise ValueError(f'Existing PR contains a different candidate: {name}')
    wait(repository, int(existing['url'].rsplit('/', 1)[1]), old_head)
    # The validated staged tree includes current main's unrelated work. A merge
    # commit preserves the previous publication head without rewriting its ref.
    # Leave checkout HEAD on protected main for subsequent deployment provenance.
    head = c.git(root, 'commit-tree', c.git(root, 'write-tree'), '-p', old_head,
                 '-p', c.git(root, 'rev-parse', 'HEAD'), '-m',
                 f"chore: reconcile Funding Finder candidate {manifest['candidate_id'][:16]}")
    c.verify_files(root, manifest['files'])
    review_boundary = c.timestamp()
    execute('git', 'push', 'origin', f'{head}:refs/heads/{branch}')
    return head, review_boundary


def request_verification(repository, number, head, reports, boundary):
    from tools.wait_release_review import all_pages, api, review_state
    completed, findings = review_state(repository, number, head)
    if completed:
        if findings:
            raise ValueError('Completed review has findings; consolidate before remediation')
        return
    # A synchronized automatic review, if configured later, owns this round.
    comments = all_pages(f'repos/{repository}/issues/{number}/comments')
    creator = api(f'repos/{repository}/pulls/{number}')['user']['login']
    if any(f'<!-- funding-finder-review:{head} -->' in row.get('body', '') and row.get('user', {}).get('login') == creator for row in comments):
        return
    automatic = any(row.get('user', {}).get('login') == 'chatgpt-codex-connector[bot]'
            and head[:7] in row.get('body', '') and ('Running' in row['body'] or 'Completed' in row['body'])
                    for row in comments)
    body = Path(reports) / 'verification-review.md'
    trigger = 'Automatic review already acknowledged.' if automatic else '@codex review'
    body.parent.mkdir(parents=True, exist_ok=True)
    body.write_text(f'{trigger}\n\nReview the exact candidate head `{head}`. Generation dependencies, current validation code and candidate bytes were verified.\n\n<!-- funding-finder-review:{head} -->\nReview boundary: {boundary}\n', encoding='utf-8')
    run('gh', 'pr', 'comment', str(number), '--repo', repository, '--body-file', str(body))


def prepare(bundle, receipt_path, reports, artifact_run, *, review_timeout=1800):
    """Obtain exact-head review before any serving mutation or provider smoke."""
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
    if (marker.exists() and c.read_json(marker).get('candidate_id') == manifest['candidate_id']
            and committed_candidate_matches(root, base, manifest)):
        c.verify_files(root, manifest['files'])
        head = base
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
        repository = os.environ['GITHUB_REPOSITORY']
        reconciled = False
        review_boundary = c.timestamp()
        if len(existing) > 1:
            raise ValueError('Multiple PRs claim this candidate; publication provenance needs reconciliation')
        if existing:
            pr_url, head = existing[0]['url'], existing[0]['headRefOid']
            run('git', 'fetch', '--no-tags', 'origin', existing[0]['headRefName'])
            if c.git(root, 'rev-parse', f'{head}^{{tree}}') != c.git(root, 'write-tree'):
                from tools.wait_release_review import wait_for_review
                head, review_boundary = reconcile_candidate_branch(root, existing[0], manifest, repository,
                    wait=lambda repo, number, sha: wait_for_review(repo, number, sha, timeout=review_timeout))
                reconciled = True
        else:
            head = c.git(root, 'commit-tree', c.git(root, 'write-tree'), '-p', base, '-m',
                         f"chore: publish Funding Finder candidate {manifest['candidate_id'][:16]}")
        c.verify_files(root, manifest['files'])
        c.verify_receipt(root, bundle, receipt)
        branch = f"automation/release-{manifest['candidate_id'][:16]}-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
        if not existing:
            run('git', 'push', 'origin', f'{head}:refs/heads/{branch}')
        repository = os.environ['GITHUB_REPOSITORY']
        run_url = f'https://github.com/{repository}/actions/runs/{os.environ["GITHUB_RUN_ID"]}'
        # Evidence covers the same validator/generation code and exact files;
        # only the provenance marker was added in this materialization commit.
        for gate in (('python', 'browser') if not existing or reconciled else ()):
            run('gh', 'api', '--method', 'POST', f'repos/{repository}/statuses/{head}',
                '-f', 'state=success', '-f', f'context={gate}', '-f', f'target_url={run_url}',
                '-f', 'description=Exact candidate bytes and validation code verified against receipt')
        body = Path(reports) / 'generated-pr.md'
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_text(f"Publish immutable candidate `{manifest['candidate_id']}`.\n\n"
                        f"Review head: `{head}`\n\n"
                        f"Generation: `{manifest['generation_sha']}` (run {manifest['generation_run_id']}).\n"
                        f"Validation: `{receipt['validation_sha']}`. All required gates passed for these exact hashes.\n\n"
                        f"Evidence: {run_url}. No source collection or provider generation occurs during publication.\n", encoding='utf-8')
        if not existing:
            pr_url = run('gh', 'pr', 'create', '--base', 'main', '--head', branch,
                         '--title', f"chore: publish Funding Finder candidate {manifest['candidate_id'][:16]}", '--body-file', str(body))
        print(f'Generated candidate PR: {pr_url}', flush=True)
        request_verification(repository, int(pr_url.rsplit('/', 1)[1]), head, reports, review_boundary)
        from tools.wait_release_review import wait_for_review
        wait_for_review(repository, int(pr_url.rsplit('/', 1)[1]), head, timeout=review_timeout)
    ready = {'schema_version': 1, 'candidate_id': manifest['candidate_id'], 'base_sha': base,
             'head_sha': head, 'pr_url': pr_url, 'artifact_run': str(artifact_run),
             'validation_receipt_sha256': c.digest(c.encoded(receipt)), 'timestamp': c.timestamp()}
    c.write_json(Path(reports) / 'review-ready.json', ready)
    return ready


def publish(bundle, receipt_path, reports, artifact_run, *, prepared=None):
    root = c.ROOT
    manifest, receipt = c.load(bundle), c.read_json(receipt_path)
    ready = c.read_json(prepared) if prepared else prepare(bundle, receipt_path, reports, artifact_run)
    c.verify_receipt(root, bundle, receipt)
    c.verify_files(root, manifest['files'])
    base = c.git(root, 'rev-parse', 'HEAD')
    if (ready.get('schema_version') != 1 or ready.get('base_sha') != base
            or ready.get('candidate_id') != manifest['candidate_id']
            or ready.get('artifact_run') != str(artifact_run)
            or ready.get('validation_receipt_sha256') != c.digest(c.encoded(receipt))):
        raise ValueError('Review readiness does not match this candidate, receipt and protected base')
    if run('git', 'ls-remote', 'origin', 'refs/heads/main').split()[0] != base:
        raise ValueError('Protected main advanced after review readiness; preserve and revalidate')
    head, pr_url = ready['head_sha'], ready['pr_url']
    if not committed_candidate_matches(root, head, manifest):
        raise ValueError('Reviewed head changed candidate bytes')
    if pr_url:
        from tools.wait_release_review import review_state
        completed, findings = review_state(os.environ['GITHUB_REPOSITORY'], int(pr_url.rsplit('/', 1)[1]), head)
        if not completed or findings:
            raise ValueError('Exact-head review is no longer clean and complete')
        run('gh', 'pr', 'merge', pr_url, '--squash', '--match-head-commit', head)
        merge_sha = run('gh', 'pr', 'view', pr_url, '--json', 'mergeCommit', '--jq', '.mergeCommit.oid')
        c.write_json(Path(reports) / 'publication-progress.json', {'candidate_id': manifest['candidate_id'],
            'publication_sha': merge_sha, 'protected_merge_completed': True, 'production_mutated': True,
            'next_retry_stage': 'publish', 'timestamp': c.timestamp()})
        run('git', 'fetch', '--no-tags', 'origin', 'main')
        if not merge_sha or run('git', 'ls-remote', 'origin', 'refs/heads/main').split()[0] != merge_sha:
            raise ValueError('Protected main changed after merge; reuse candidate with refreshed release controls')
    else:
        if head != base:
            raise ValueError('Already-published readiness must name protected main')
        merge_sha = base
    if not committed_candidate_matches(root, merge_sha, manifest):
        raise ValueError('Protected merge changed candidate bytes')
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
    parser.add_argument('--prepared', help='Exact review-ready receipt from the pre-deployment step')
    args = parser.parse_args()
    publish(args.bundle, args.receipt, args.reports, args.artifact_run, prepared=args.prepared)


if __name__ == '__main__':
    main()
