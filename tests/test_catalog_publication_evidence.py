"""Exercise closed notices, official submission proofs, and public feed drift."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_changes import _snapshot
from scripts.build_feeds import build_feeds
from scripts.extract_document_evidence import source_for_record, source_signature
from tools.catalog_publication_evidence import (
    change_snapshot_findings, changed_record_findings, static_feed_findings)


GENERATION = '2026-11-13T17:00:00Z'
AUDIT_DAY = date(2026, 11, 15)
SCALED_URL = 'https://grants.gov/grantsws/rest/opportunity/att/download/355646'
SCALED_DOCUMENT = {
    'url': 'https://apply07.grants.gov:443/grantsws/rest/opportunity/att/download/355646',
    'name': 'DE-FOA-0003641_SCALED_NOFO_Part 1_Modification 000001.pdf',
    'sha256': 'b9c7b8b24273e8fcbbef97ffab0833bc9010c9a11c7c08a7451d0023127e64c4',
}


def catalog(*records):
    return {'generated_at': GENERATION, 'opportunities': list(records)}


def scaled():
    def cite(quote):
        return {'document_url': SCALED_DOCUMENT['url'], 'sha256': SCALED_DOCUMENT['sha256'], 'quote': quote}

    concept = {'kind': 'concept_paper', 'date': '2026-11-20', 'required': True}
    application = {'kind': 'application', 'date': '2027-02-08'}
    record = {'opportunity_id': '364174', 'status': 'posted', 'source': 'Grants.gov',
              'title': 'Grid Supply Chain Alternatives to Lead Energy Dominance (SCALED)',
              'primary_document_url': SCALED_URL, 'primary_document_name': SCALED_DOCUMENT['name'],
              'close_date': application['date'], 'deadlines': [application, concept],
              'next_submission': {'date': concept['date'], 'event': concept}}
    facts = [
        {'type': 'deadline', 'id': 'evidence-364174-262ec8f3e47e', 'deadline_kind': 'concept_paper',
         'date': concept['date'], 'required': True, 'citation': cite('Concept Paper Deadline: November 20, 2026'),
         'requirement_citation': cite('You must submit a concept paper by the specified due date and time to be eligible to submit a full application.')},
        {'type': 'deadline', 'id': 'evidence-364174-7a78f6fe7a74', 'deadline_kind': 'application',
         'date': application['date'], 'citation': cite('Application Due: February 8, 2027, 5:00 PM E.T.')},
    ]
    cache = {'records': {'364174': {
        'status': 'current', 'document': dict(SCALED_DOCUMENT), 'facts': facts,
        'source_signature': source_signature(record, source_for_record(record)),
    }}}
    return record, cache


class CatalogPublicationEvidenceTests(unittest.TestCase):
    def test_verified_closure_cannot_fall_back_to_stale_open_listing(self):
        closed = {'opportunity_id': '363660', 'opportunity_number': 'DFOP0019410', 'agency_code': 'DOS-AF',
                  'status': 'posted', 'close_date': '2027-05-31'}
        same = catalog(closed)
        self.assertEqual(changed_record_findings(same, {}, same, date(2026, 11, 12)), [])
        findings = changed_record_findings(same, {}, same, AUDIT_DAY)
        self.assertEqual([(item['opportunity_id'], item['reason']) for item in findings],
                         [('363660', 'verified_closed_opportunity_still_present')])
        successor = catalog({**closed, 'opportunity_id': '365001'})
        self.assertEqual(changed_record_findings(successor, {}, same, AUDIT_DAY), [])

    def test_closure_or_generic_doe_companion_cannot_be_a_primary_document(self):
        record, cache = scaled()
        self.assertEqual(changed_record_findings(catalog(record), cache, catalog(), AUDIT_DAY), [])
        for name, reason in (
            ('DE-FOA-0003641_SCALED_NOFO_Part 2.pdf', 'doe_generic_companion'),
            ('Annual Program Statement Closed.pdf', 'closure_notice'),
        ):
            with self.subTest(name=name):
                invalid = {**record, 'primary_document_name': None,
                           'document_urls': [{'download_url': SCALED_URL, 'file_name': name}]}
                findings = changed_record_findings(catalog(invalid), cache, catalog(record), AUDIT_DAY)
                self.assertIn(reason, [item['reason'] for item in findings])

    def test_mandatory_stage_and_later_full_date_must_survive_owned_evidence(self):
        record, cache = scaled()
        prior = deepcopy(record)
        early_as_full = {**record['deadlines'][1], 'kind': 'application', 'required': None}
        for incorrect in (
            [record['deadlines'][0], early_as_full],
            [record['deadlines'][0], record['deadlines'][1], early_as_full],
            [record['deadlines'][1]],
        ):
            with self.subTest(incorrect=incorrect):
                record['deadlines'] = incorrect
                record['close_date'] = None
                findings = changed_record_findings(catalog(record), cache, catalog(prior), AUDIT_DAY)
                self.assertEqual([item['reason'] for item in findings], ['official_prerequisite_differs_from_catalog'])
                self.assertEqual(findings[0]['date'], '2026-11-20')
                self.assertEqual(findings[0]['full_dates'], ['2027-02-08'])
        cache['records']['364174']['source_signature'] = 'older notice version'
        self.assertEqual(changed_record_findings(catalog(record), cache, catalog(prior), AUDIT_DAY), [])

    def test_published_funding_fact_uses_its_owned_amount_basis(self):
        fixture = Path(__file__).parent / 'fixtures/parsing/document-fact-guards.json'
        rate = next(case for case in json.loads(fixture.read_bytes())['cases']
                    if case['reason'] == 'personnel_rate_not_program_funding')
        rate_record = {'opportunity_id': rate['opportunity_id'], 'status': 'posted',
                       'document_evidence': {'document': rate['document'], 'facts': [rate['fact']]}}

        document = {'url': 'https://apply07.grants.gov:443/grantsws/rest/opportunity/att/download/354914',
                    'sha256': 'b08835a01ff5e8024fee95f7ace64316eea6e5b6a9043fb4fcbc6161c74e2028'}
        applicant = {'type': 'program_funding', 'id': 'evidence-363763-342ffc4d7db4', 'value': 50000,
                     'citation': {'document_url': document['url'], 'sha256': document['sha256'],
                         'quote': 'The total funding request on the IMLS Budget Form must be between $50,000 - $150,000.'}}
        program = {**applicant, 'id': 'imls-program-total', 'value': 750000,
                   'citation': {**applicant['citation'], 'quote': 'Total program funding is $750,000.'}}
        imls = {'opportunity_id': '363763', 'status': 'posted',
                'document_evidence': {'document': document, 'facts': [applicant, program]}}

        findings = changed_record_findings(catalog(rate_record, imls), {}, catalog(), AUDIT_DAY)
        self.assertEqual([item['reason'] for item in findings],
                         ['personnel_rate_not_program_funding', 'applicant_budget_request_not_program_funding'])
        imls['document_evidence']['facts'] = [program]
        self.assertEqual(changed_record_findings(catalog(imls), {}, catalog(), AUDIT_DAY), [])

    def test_current_change_snapshot_must_keep_the_required_concept_deadline(self):
        record, _ = scaled()
        outdated = _snapshot(record)
        outdated['deadlines'] = [record['deadlines'][0]]
        outdated['next_submission'] = {'date': '2027-02-08', 'event': record['deadlines'][0]}
        event = {'id': 'current', 'changed_at': GENERATION, 'type': 'new',
                 'opportunity_id': '364174', 'record': outdated}
        historical = {**event, 'id': 'historical', 'changed_at': '2026-10-31T00:00:00Z'}
        feed = {'events': [event, historical]}
        findings = change_snapshot_findings(catalog(record), feed)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['event_id'], 'current')
        self.assertEqual(findings[0]['fields'], ['deadlines', 'next_submission'])
        event['record'] = _snapshot(record)
        self.assertEqual(change_snapshot_findings(catalog(record), feed), [])
        self.assertEqual(historical['record'], outdated)

    def test_delayed_publication_rechecks_actual_atom_entries_on_audit_day(self):
        records = (
            {'opportunity_id': '363769', 'close_date': '2026-11-13'},
            {'opportunity_id': '364084', 'close_date': '2026-11-14'},
            {'opportunity_id': 'same-day', 'close_date': '2026-11-15'},
            {'opportunity_id': 'rolling', 'rolling': True},
        )
        candidate = catalog(*({**record, 'status': 'posted', 'source': 'Grants.gov',
                               'topic_areas': ['Arts and culture']} for record in records))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_feeds(candidate, root, as_of=date(2026, 11, 13))
            self.assertEqual(static_feed_findings(candidate, root, date(2026, 11, 13)), [])
            findings = static_feed_findings(candidate, root, AUDIT_DAY)
            self.assertEqual({item['opportunity_id'] for item in findings}, {'363769', '364084'})
            self.assertTrue(all(item['reason'] == 'static_feed_entry_is_not_current' for item in findings))
            self.assertIn('topic/arts-and-culture.xml', {item['feed'] for item in findings})
            build_feeds(candidate, root, as_of=AUDIT_DAY)
            self.assertEqual(static_feed_findings(candidate, root, AUDIT_DAY), [])
            self.assertEqual(candidate['generated_at'], GENERATION)

    def test_delayed_atom_summary_can_stale_before_the_full_deadline(self):
        record, _ = scaled()
        candidate = catalog(record)
        after_concept_paper = date(2026, 11, 21)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_feeds(candidate, root, as_of=AUDIT_DAY)
            findings = static_feed_findings(candidate, root, after_concept_paper)
            self.assertEqual([(item['opportunity_id'], item['reason']) for item in findings],
                             [('364174', 'static_feed_entry_has_stale_submission')])
            build_feeds(candidate, root, as_of=after_concept_paper)
            self.assertEqual(static_feed_findings(candidate, root, after_concept_paper), [])

    def test_already_refreshed_atom_still_requires_audit_day_submission(self):
        # The retained FDA 359816 record stays current through its April portal
        # close. Jan 31 feeds show the March round, which is stale on March 2.
        record = {'opportunity_id': '359816', 'source': 'Grants.gov', 'status': 'posted',
                  'agency': 'Food and Drug Administration', 'close_date': '2027-04-01',
                  'deadlines': [{'kind': 'letter_of_intent', 'date': '2027-01-30'},
                                {'kind': 'application', 'date': '2027-03-01'},
                                {'kind': 'application', 'date': '2027-04-01'}]}
        candidate = catalog(record)
        intermediate = date(2027, 1, 31)
        later = date(2027, 3, 2)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_feeds(candidate, root, as_of=intermediate)
            self.assertIn('Application 2027-03-01', (root / 'all.xml').read_text())
            self.assertEqual(static_feed_findings(candidate, root, intermediate), [])
            findings = static_feed_findings(candidate, root, later)
            self.assertEqual([(item['opportunity_id'], item['reason']) for item in findings],
                             [('359816', 'static_feed_entry_has_stale_submission')])
            build_feeds(candidate, root, as_of=later)
            self.assertIn('Application 2027-04-01', (root / 'all.xml').read_text())
            self.assertEqual(static_feed_findings(candidate, root, later), [])
