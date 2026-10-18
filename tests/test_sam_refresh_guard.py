"""A failed SAM scan cannot become a published deletion of its entire inventory."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from scripts.sources.adapters.sam_gov import SamGovAdapter
from scripts.sources.merge import integrate, save_catalog
from scripts.sources.sam_api import SamError
from scripts.sources import sam_public
from tests.test_sam_reviewed import configuration, payload, resources, NOTICE, OTHER, TODAY
from tools.require_sam_refresh import main, require_complete_refresh

ROOT = Path(__file__).resolve().parents[1]


def receipt():
    return {'written': True, 'validation': {'ok': True}, 'sources': [
        {'slug': 'sam-gov', 'status': 'refreshed', 'healthy': True, 'published': 0,
         'diagnostics': {'reviewed_inventory': True, 'outcome': 'ok',
                         'notice_observations': [{'notice_id': NOTICE, 'reasons': ['entry_closed']}]}}]}


class SamRefreshGuardTests(unittest.TestCase):
    def test_verified_withdrawals_and_unrelated_degradation_are_allowed(self):
        summary = receipt()
        summary['sources'].append({'slug': 'other', 'status': 'failed_kept_last_good', 'healthy': False})
        require_complete_refresh(configuration(), summary)

    def test_incomplete_ambiguous_or_unwritten_receipts_cannot_continue(self):
        cases = [None, {}, [], dict(receipt(), written=False), dict(receipt(), validation={'ok': False})]
        for change in ({'healthy': False}, {'status': 'partial_refresh'}, {'diagnostics': {}},
                       {'diagnostics': {'reviewed_inventory': True, 'outcome': 'ok', 'notice_observations': []}}):
            summary = receipt(); summary['sources'][0].update(change); cases.append(summary)
        summary = receipt(); summary['sources'] *= 2; cases.append(summary)
        summary = receipt(); summary['sources'][0]['diagnostics']['notice_observations'] *= 2; cases.append(summary)
        summary = receipt(); summary['sources'][0]['diagnostics']['notice_observations'][0]['notice_id'] = OTHER; cases.append(summary)
        for summary in cases:
            with self.subTest(summary=summary), self.assertRaises(ValueError):
                require_complete_refresh(configuration(), summary)

    def test_missing_or_malformed_summary_and_invalid_config_fail_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'sam.json'; summary = Path(directory) / 'summary.json'
            config.write_text(json.dumps(configuration()), encoding='utf8')
            args = ['--config', str(config), '--summary', str(summary)]
            for data in (None, 'not-json', '{}'):
                if data is not None: summary.write_text(data, encoding='utf8')
                with self.subTest(data=data), self.assertRaises(SystemExit): main(args)
            config.write_text('{}', encoding='utf8')
            with self.assertRaises((SystemExit, SamError)): main(args)

    def test_disabled_and_legacy_configs_do_not_require_a_v2_receipt(self):
        require_complete_refresh(dict(configuration(), enabled=False), None)
        require_complete_refresh({'schema_version': 1, 'enabled': True}, None)

    def test_real_merge_blocks_missing_or_unreviewed_evidence_but_allows_confirmed_closure(self):
        for mode in ('failed', 'changed', 'closed'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cfg = configuration()
                other = deepcopy(cfg['approved_notices'][0])
                other.update(notice_id=OTHER, solicitation_number='DARPA-TEST-26-02')
                cfg['approved_notices'].append(other)
                config_path = root / 'sam.json'; config_path.write_text(json.dumps(cfg), encoding='utf8')
                observed = sam_public.snapshot(payload(), resources(), NOTICE)
                def client(identifier):
                    if identifier == OTHER:
                        if mode == 'failed':
                            raise SamError('public_notice_unavailable', {
                                'request_count': 2, 'http_status': 503, 'failure_class': 'transient_transport'})
                        # A changed active notice needs review; a verified
                        # cancelled notice may be withdrawn normally.
                        return dict(observed, notice_id=OTHER, latest_notice_id=OTHER,
                                    solicitation_number=other['solicitation_number'],
                                    cancelled=mode == 'closed', review_sha256='0' * 64), {'request_count': 2}
                    return observed, {'request_count': 2}
                catalog = root / 'catalog.js'
                save_catalog({'generated_at': '2026-10-13T12:00:00Z', 'opportunities': []}, catalog)
                adapter = SamGovAdapter(config_path=config_path, reviewed_client=client)
                with patch.dict('os.environ', {'VPR_ENRICH_LINKS': 'false'}):
                    summary = integrate(catalog_path=catalog, cache_path=root / 'cache.json',
                                        adapters=[adapter], as_of=TODAY, write=True)
                if mode != 'closed':
                    with self.assertRaises(ValueError): require_complete_refresh(cfg, summary)
                else:
                    require_complete_refresh(cfg, summary)
                    self.assertEqual(summary['sources'][0]['published'], 1)

    def test_workflow_guard_blocks_paid_work_and_persistence_but_keeps_alerts(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/refresh-opportunities.yml').read_text(encoding='utf8'))
        steps = workflow['jobs']['generate']['steps']
        guard_index = next(i for i, step in enumerate(steps) if step.get('id') == 'sam-health')
        guard = steps[guard_index]
        self.assertEqual(steps[guard_index - 1]['id'], 'additional-sources')
        self.assertEqual(guard['if'], "steps.restore.outputs.candidate_id == ''")
        self.assertNotIn('continue-on-error', guard)
        self.assertIn('tools.require_sam_refresh', guard['run'])
        for identifier in ('document_evidence', 'persist'):
            index = next(i for i, step in enumerate(steps) if step.get('id') == identifier)
            self.assertGreater(index, guard_index)
            self.assertNotIn('always()', steps[index]['if'])
        alert = next(step for step in steps if step.get('name') == 'Alert the project owner about a degraded external source')
        self.assertIn('always()', alert['if'])
        self.assertIn("steps.sam-health.outcome == 'failure'", alert['if'])
        self.assertIn('previously published catalog remains in service', alert['with']['script'])
        retained = next(step for step in steps if step.get('name') == 'Preserve source refresh diagnostics after any outcome')
        self.assertIn('always()', retained['if'])
        dependencies = json.loads((ROOT / 'config/release_dependencies.json').read_text(encoding='utf8'))
        self.assertIn('tools/require_sam_refresh.py', dependencies['generation'])
        self.assertIn('tools/require_sam_refresh.py', dependencies['dependency_groups']['source']['patterns'])


if __name__ == '__main__':
    unittest.main()
