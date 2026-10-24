"""Require complete SAM accounting before paid work; quarantine stays local."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.sources.adapters.sam_gov import CONFIG_PATH, load_config
from scripts.sources.sam_reviewed import require_reviewed_observations


def require_complete_refresh(config, summary):
    """Accept verified withdrawals, but never mistake missing reads for them."""
    if not config['enabled'] or config['schema_version'] != 2:
        return
    if not isinstance(summary, dict):
        raise ValueError('SAM refresh summary is unavailable')
    sources = summary.get('sources')
    if not isinstance(sources, list):
        raise ValueError('SAM refresh summary is invalid')
    validation = summary.get('validation')
    if not isinstance(validation, dict):
        raise ValueError('SAM refresh validation receipt is invalid')
    sam = [source for source in sources if isinstance(source, dict) and source.get('slug') == 'sam-gov']
    if (len(sam) != 1 or summary.get('written') is not True
            or validation.get('ok') is not True):
        raise ValueError('SAM refresh failed; the current published catalog must remain in service')
    source = sam[0]
    diagnostics = source.get('diagnostics')
    require_reviewed_observations(config, diagnostics)
    degraded = diagnostics.get('outcome') == 'degraded'
    if (source.get('status') != ('partial_refresh' if degraded else 'refreshed')
            or source.get('healthy') is not (not degraded)):
        raise ValueError('SAM source state does not match its complete notice accounting')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=CONFIG_PATH)
    parser.add_argument('--summary', type=Path, required=True)
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if not config['enabled'] or config['schema_version'] != 2:
            return
        summary = json.loads(args.summary.read_text(encoding='utf8'))
        require_complete_refresh(config, summary)
        if args.github_output:
            complete = all(source.get('healthy') is True for source in summary['sources'])
            with args.github_output.open('a', encoding='utf8') as output:
                output.write('source_completeness=' + ('complete' if complete else 'degraded') + '\n')
    except (OSError, ValueError, TypeError, KeyError):
        raise SystemExit('Catalog generation stopped: complete verified SAM accounting is required. '
                         'The published catalog is unchanged; inspect the source refresh summary.') from None
    print('Complete reviewed SAM accounting verified before paid continuation and candidate persistence.')


if __name__ == '__main__':
    main()
