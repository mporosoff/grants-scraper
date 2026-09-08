"""Prove an empty-selection maintenance replay makes zero provider calls."""
from contextlib import chdir
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

from tools import release_candidate as c


def replay(root):
    from scripts import build_opportunity_teams as t
    with tempfile.TemporaryDirectory() as directory:
        destination = Path(directory)
        names = ['config/opportunity_team_model.json', 'config/researcher_registry.json', 'data/opportunities.js',
                 'data/subtopics.js', 'data/opportunity_teams.js', 'data/opportunity_team_index.js', 'match_explorer.html', 'team_match.html']
        original_hashes = c.file_hashes(root, names)
        for name in names:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(root) / name, target)
        with chdir(destination), patch('sys.argv', ['teams', '--mode', 'replay']), patch.object(t.requests, 'post', side_effect=AssertionError('Warm replay attempted provider request')) as post:
            t.main()
            result = c.read_json(destination / 'evaluation/opportunity_team_generation.json')
        if post.call_count or result['provider_requests'] or result['due_scopes']:
            raise ValueError('Empty-selection replay performed provider work')
        c.verify_files(root, original_hashes)
        return {'mode': 'replay', 'new_selection_enabled': False, 'provider_requests': 0,
                'remaining_maintenance': result['queue_counts']['maintenance'], 'remaining_backfill': result['queue_counts']['backfill']}


def main():
    receipt = c.read_json(c.ROOT / 'evaluation/opportunity_team_generation.json')
    if (receipt.get('run_id') != os.environ['GITHUB_RUN_ID'] or receipt.get('run_attempt') != os.environ['GITHUB_RUN_ATTEMPT']
            or receipt.get('status') != 'completed' or receipt.get('generation_requested') is not True):
        raise ValueError('Team stage lacks a complete current-run bounded receipt; retain spend state and repair before publication')
    value = replay(c.ROOT)
    c.write_json(Path(os.environ['RUNNER_TEMP']) / f"offline-{os.environ['GITHUB_RUN_ID']}" / 'warm-replay.json', value)
    print(json.dumps(value))


if __name__ == '__main__':
    main()
