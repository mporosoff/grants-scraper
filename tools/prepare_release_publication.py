"""Prepare and review an immutable publication before changing serving state."""
import argparse
import os
from pathlib import Path

from tools.publish_release_candidate import prepare
from tools.wait_release_review import ReviewPending
from tools import release_candidate as c


def prepare_or_defer(bundle, receipt, reports, artifact_run):
    """Only missing review is a non-serving checkpoint; all other errors fail."""
    try:
        result = prepare(bundle, receipt, reports, artifact_run, review_timeout=90)
    except ReviewPending as pending:
        manifest = c.load(bundle)
        result = {'schema_version': 1, 'status': 'awaiting_review',
            'candidate_id': manifest['candidate_id'], 'artifact_run': str(artifact_run),
            'head_sha': pending.head, 'pr_number': pending.number,
            'repository': pending.repository, 'production_mutated': False,
            'next_retry_stage': 'publish', 'timestamp': c.timestamp()}
        c.write_json(Path(reports) / 'review-pending.json', result)
        message = (f"Awaiting exact-head review of PR #{pending.number}. No publication or serving change. "
                   f"Retained candidate {manifest['candidate_id']} from run {artifact_run}; resume publish after review.\n")
        print(message)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as out:
                out.write(message)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as out:
            out.write('review_ready=' + ('false' if result.get('status') == 'awaiting_review' else 'true') + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'receipt', 'reports', 'artifact-run'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    prepare_or_defer(args.bundle, args.receipt, args.reports, args.artifact_run)


if __name__ == '__main__':
    main()
