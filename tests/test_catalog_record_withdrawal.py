"""Withdrawal preserves source facts, search indices, fallback safety and history."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from tools import catalog_record_withdrawal as w, release_candidate as c


class WithdrawalTests(unittest.TestCase):
    def setUp(self):
        def record(identifier, source):
            return {'opportunity_id': identifier, 'title': identifier + ' research',
                'agency': source, 'source': source, 'status': 'posted', 'close_date': '2027-01-01',
                'topic_areas': ['energy'], 'description': 'Immutable evidence ' + identifier}
        removed = [record(i, 'DOE EERE Exchange' if i.startswith('eere') else 'VPR') for i in sorted(w.REMOVED)]
        retained = [record(str(i), 'National Science Foundation') for i in range(5)]
        self.rows = removed + retained
        evidence = []
        position = 0
        for row in removed:
            item = {'opportunity_id': row['opportunity_id'], 'record_sha256': w.record_hash(row),
                'official_evidence_url': 'https://www.nsf.gov/funding/opportunities/example'}
            if row['opportunity_id'].startswith('eere'):
                item.update(reason='officially_closed', official_status='Closed')
            else:
                winner = retained[position]; position += 1
                item.update(reason='stale_edition_conflict' if row['opportunity_id'].endswith('NSF25-544') else 'duplicate',
                    retained_id=winner['opportunity_id'], retained_record_sha256=w.record_hash(winner))
            evidence.append(item)
        self.evidence = {'removals': evidence}
        self.before = {'generated_at': '2026-10-08T19:00:00Z', 'record_count': 11,
            'opportunities': self.rows, 'detail_enrichment_generated_at': '2026-10-08T19:01:00Z',
            'diagnostics': {'additional_sources': {'merged_at': '2026-10-08T19:01:00Z',
                'adapters': [{'slug': 'eere-exchange', 'ok': False}], 'lifecycle': [{'healthy': False}]}}}
        self.audit = '2026-10-08T19:45:00+00:00'

    def test_surviving_facts_and_original_clocks_are_unchanged(self):
        original = deepcopy(self.before)
        result = w.corrected_catalog(self.before, self.evidence, self.audit)
        self.assertEqual(self.before, original)
        self.assertEqual(result['opportunities'], self.rows[6:])
        self.assertEqual(result['record_count'], 5)
        self.assertEqual(result['search_index']['document_count'], 5)
        for postings in result['search_index']['postings'].values():
            self.assertTrue(all(0 <= index < 5 for index in postings[::2]))
        for key in ('generated_at', 'detail_enrichment_generated_at'):
            self.assertEqual(result[key], self.before[key])
        for key in ('adapters', 'lifecycle', 'merged_at'):
            self.assertEqual(result['diagnostics']['additional_sources'][key],
                self.before['diagnostics']['additional_sources'][key])

    def test_changed_removed_or_retained_evidence_fails_closed(self):
        for index in (0, 6):
            changed = deepcopy(self.before)
            changed['opportunities'][index]['description'] = 'changed source facts'
            with self.assertRaisesRegex(ValueError, 'exact_'):
                w.corrected_catalog(changed, self.evidence, self.audit)

    def test_no_new_or_partial_withdrawal_set(self):
        changed = deepcopy(self.evidence)
        changed['removals'].pop()
        with self.assertRaisesRegex(ValueError, 'fixed_withdrawal_set'):
            w.corrected_catalog(self.before, changed, self.audit)

    def test_open_cmma_is_not_terminal_evidence(self):
        changed = deepcopy(self.evidence)
        next(r for r in changed['removals'] if r['opportunity_id'].startswith('eere'))['official_status'] = 'Open'
        with self.assertRaisesRegex(ValueError, 'official_terminal_evidence'):
            w.corrected_catalog(self.before, changed, self.audit)

    def test_fallback_cannot_resurrect_withdrawals(self):
        before = {'official_identities': {'historical': True}, 'sources': {'vpr-email': {
            'records': deepcopy(self.rows), 'record_count': 11, 'fetched_at': '2026-10-01T00:00:00Z'}}}
        result = w.corrected_cache(before, self.evidence, self.audit)
        self.assertEqual(result['sources']['vpr-email']['records'], self.rows[6:])
        self.assertEqual(result['sources']['vpr-email']['fetched_at'], before['sources']['vpr-email']['fetched_at'])
        self.assertEqual(result['official_identities'], before['official_identities'])
        self.assertEqual(len(before['sources']['vpr-email']['records']), 11)

    def test_missing_cache_evidence_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'all_withdrawals'):
            w.corrected_cache({'sources': {}}, self.evidence, self.audit)

    def test_correction_feed_preserves_history_without_claiming_duplicates_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            old = {'id': 'old', 'type': 'new', 'changed_at': '2026-09-30T00:00:00Z',
                'opportunity_id': 'historic', 'record': {'title': 'Past event'}, 'detail': 'Historical evidence'}
            c.write_json(parent/'feeds/changes.json', {'schema_version': 1, 'events': [old]})
            after = w.corrected_catalog(self.before, self.evidence, self.audit)
            result = w.change_projection(parent, self.before, after, self.evidence, self.audit)
            import json
            events = json.loads(result['feeds/changes.json'])['events']
            self.assertEqual(next(e for e in events if e['id'] == 'old'), old)
            self.assertEqual(sum(e['type'] == 'closed_or_removed' for e in events), 1)
            self.assertEqual(sum(e['type'] == 'source_correction' for e in events), 5)


if __name__ == '__main__':
    unittest.main()
