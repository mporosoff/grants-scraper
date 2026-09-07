import unittest
from copy import deepcopy
from datetime import datetime, timezone

from scripts import extract_document_evidence as e
from tools.audit_parsing_corpus import audit


class ParsingCorpusAuditTests(unittest.TestCase):
    def test_estimated_true_is_measured_and_the_existing_false_default_is_equivalent(self):
        from tools.audit_parsing_corpus import fact_value
        fact = {'type': 'deadline', 'date': '2027-05-01'}
        self.assertEqual(fact_value(fact), fact_value({**fact, 'estimated': False}))
        self.assertEqual(fact_value({**fact, 'estimated': True})['estimated'], True)

    def test_recommended_date_qualification_requires_source_review_even_before_it_elapses(self):
        record = {'opportunity_id': 'qualified', 'deadlines': [{'kind': 'application', 'date': '2027-05-01',
                  'date_qualifier': 'recommended', 'confidence': 'official_structured'}]}
        catalog = {'opportunities': [record]}
        baseline = deepcopy(catalog)
        baseline['opportunities'][0]['deadlines'][0].pop('date_qualifier')
        report = audit(catalog, {'records': {}}, baseline, datetime(2026, 9, 7, tzinfo=timezone.utc))
        row = next(r for r in report['decisive_change_ledger'] if r['comparison'] == 'verified_generation')
        self.assertEqual(row['changes']['next_submission_metadata']['after']['date_qualifier'], 'recommended')
        self.assertFalse(report['publication_ready'])

    def test_unchanged_date_cannot_hide_a_changed_clock_or_submission_class(self):
        now = datetime(2026, 9, 7, tzinfo=timezone.utc)
        record = {'opportunity_id': 'clock', 'deadlines': [{'kind': 'application', 'date': '2027-05-01',
            'time': '11:59:59 p.m.', 'timezone': 'Eastern', 'application_class': 'new', 'confidence': 'official_structured'}]}
        catalog = {'opportunities': [record]}
        baseline = deepcopy(catalog)
        baseline['opportunities'][0]['deadlines'][0].update(time='59:59 p.m.', timezone='East', application_class=None)
        report = audit(catalog, {'records': {}}, baseline, now)
        rows = [r for r in report['decisive_change_ledger'] if r['comparison'] == 'verified_generation']
        self.assertEqual(len(rows), 1)
        self.assertEqual(list(rows[0]['changes']), ['next_submission_metadata'])
        self.assertEqual(rows[0]['changes']['next_submission_metadata']['after']['time'], '11:59:59 p.m.')
        self.assertFalse(report['publication_ready'])

    def test_source_correction_requires_review_without_changing_inputs_or_receipt(self):
        now = datetime(2026, 9, 7, tzinfo=timezone.utc)
        record = {'opportunity_id': 'audit', 'primary_document_url': 'https://example.gov/notice.html',
                  'close_date': '2027-05-01', 'award_ceiling': 1000000, 'cost_share_required': False,
                  'deadlines': [{'kind': 'application', 'date': '2027-05-01', 'source': 'Grants.gov'}]}
        source = e.source_for_record(record)
        entry, _ = e.build_document_entry(record, source, {'url': source['url'], 'content_type': 'text/html',
            'content': b'<p>Each award has a maximum of $500,000. Cost sharing is not required.</p>'}, None, now)
        original = e.merge_document_entry(record, entry)
        catalog = {'opportunities': [original]}
        baseline = deepcopy(catalog)
        baseline['opportunities'][0]['document_evidence']['facts'][0]['value']['maximum'] = 900000
        store = {'records': {'audit': entry}}
        frozen = deepcopy((catalog, store, baseline))
        report = audit(catalog, store, baseline, now)
        self.assertEqual((catalog, store, baseline), frozen)
        self.assertEqual(report['violations'], [])
        self.assertEqual(report['counts']['structured_deadlines_unchanged'], 1)
        self.assertEqual(report['counts']['decisive_changes_unreviewed'], 1)
        self.assertFalse(report['publication_ready'])
        row = report['decisive_change_ledger'][0]
        self.assertEqual(row['comparison'], 'verified_generation')
        self.assertEqual(list(row['changes']), ['award_ranges'])
        reviewed = audit(catalog, store, baseline, now, reviews={row['review_key']: {
            'disposition': 'corrected_wrong_fact', 'rationale': 'The explicit per-award maximum is $500,000.',
            'source_receipts': [{'document_url': source['url'], 'sha256': entry['document']['sha256']}]}})
        self.assertTrue(reviewed['publication_ready'])
        self.assertEqual(reviewed['source_requests'], 0)
        self.assertEqual(reviewed['provider_requests'], 0)

    def test_quote_fallback_is_not_reported_as_complete_recovery(self):
        now = datetime(2026, 9, 7, tzinfo=timezone.utc)
        record = {'opportunity_id': 'legacy', 'primary_document_url': 'https://example.gov/notice.html'}
        source = e.source_for_record(record)
        entry, _ = e.build_document_entry(record, source, {'url': source['url'], 'content_type': 'text/html',
            'content': b'<p>Cost sharing is not required.</p>'}, None, now)
        entry['parser_dependencies']['cost_share'] = 'old'
        entry['facts'][0]['value'] = True
        catalog = {'opportunities': [e.merge_document_entry(record, entry)]}
        report = audit(catalog, {'records': {'legacy': entry}}, catalog, now)
        self.assertEqual(report['parser_counters']['pending_records'], 1)
        self.assertTrue(report['dispositions'][0]['parser_pending'])
        self.assertIn('unresolved_source_recovery', report['fact_families']['cost_share']['facts'])
        self.assertIn('recovered_fact_requires_source_review', report['fact_families']['cost_share']['facts'])
        self.assertEqual(report['violations'], [])


if __name__ == '__main__':
    unittest.main()
