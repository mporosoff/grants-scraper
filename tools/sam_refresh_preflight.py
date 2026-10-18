"""Verify bounded reviewed SAM snapshots before generation reserves an allowance."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from scripts.sources.adapters.sam_gov import CONFIG_PATH
from scripts.sources.sam_api import SamError
from scripts.sources.sam_preflight import KIND, MAX_RECEIPT_BYTES, build_receipt, replay_client


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=CONFIG_PATH)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify-only', action='store_true', help='Verify the exact retained receipt without fetching or rewriting it')
    args = parser.parse_args(argv)
    if args.verify_only:
        try:
            checked_at = datetime.now(timezone.utc)
            replay_client(args.output, args.config, checked_at.date(), now=checked_at)
            completed = True
        except (OSError, ValueError, TypeError, KeyError, SamError, subprocess.SubprocessError):
            completed = False
        print(json.dumps({'outcome': 'verified' if completed else 'invalid_preflight',
                          'completed': completed, 'request_count': 0}))
        return 0 if completed else 1
    try:
        checked_at = datetime.now(timezone.utc)
        receipt = build_receipt(args.config, checked_at.date(), checked_at=checked_at)
        serialized = json.dumps(receipt, indent=2, ensure_ascii=False) + '\n'
        if len(serialized.encode('utf8')) > MAX_RECEIPT_BYTES:
            raise ValueError('Oversized preflight receipt')
    except (OSError, ValueError, TypeError, KeyError, SamError, subprocess.SubprocessError):
        # Never serialize exception strings, raw response bodies or credentials.
        receipt = {'schema_version': 1, 'kind': KIND, 'completed': False, 'outcome': 'invalid_preflight'}
        serialized = json.dumps(receipt, indent=2) + '\n'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(serialized, encoding='utf8')
    temporary.replace(args.output)
    print(json.dumps({'outcome': receipt['outcome'], 'completed': receipt['completed'],
                      'request_count': receipt.get('diagnostics', {}).get('request_count')}))
    return 0 if receipt['completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
