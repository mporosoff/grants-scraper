"""ARPA summary stages proved by retained official excerpts, without retrieval."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from scripts import extract_document_evidence as evidence
from scripts import notice_schedule as schedule
from scripts.submission_schedule import next_submission


# Public excerpts retained in authenticated candidate 484141e95d4f2ffd8e6d96f6
# eabf953b69e587934fc133497df691fa9510bb49 (run38927032149, attempt2).
# These are citation text, not a reconstructed complete page or a fresh check.
STAMP = '2026-10-16T15:54:04.316189Z'
SURPASS_URL = 'https://arpa-h.gov/explore-funding/programs/surpass'
SURPASS_SHA = 'aa874e0da74d436d52451533c2b946a6176c2fbcd1dd078418a93d11e1e11776'
SURPASS_QUOTES = (
    '…ity to learn more about this opportunity, ask questions, and make connections. '
    'Registration required, see Special Notice ARPA-H-SN-26-164 for event details. '
    'Solution Summary Due - November 30, 2026 Submitting a summary is required to move '
    'forward with this opportunity. After submitting a summary, await feedback from '
    'ARPA-H before proceeding. Proposal Due -…',
    '…November 30, 2026 Submitting a summary is required to move forward with this '
    'opportunity. After submitting a summary, await feedback from ARPA-H before '
    'proceeding. Proposal Due - January 22, 2027 Reference solicitation for full '
    'details. Interested in this opportunity? Download the official solicitation '
    'documents which are posted on SAM.gov. The documents o…',
)
UNIQUE_QUOTE = (
    '…and information on how to apply. Key Dates: Dates are estimates and subject to '
    'change. Please reference the solicitation for the most up-to-date information. '
    'Solution Summary Due: October 30, 2026 at 11:59PM ET A summary is required to '
    'submit a full proposal. Full Proposal Due: December 15, 2026 at 11:59PM ET '
    'After submission of a solution summary, propose…'
)


def containers(quotes):
    return [{'text': quote, 'page': None, 'section': 'Solicitation Overview'} for quote in quotes]


def document(url=SURPASS_URL, digest=SURPASS_SHA):
    return {'url': url, 'sha256': digest, 'content_type': 'text/html; charset=utf-8',
            'first_seen_at': STAMP, 'last_seen_at': STAMP, 'version': 1}


def legacy_surpass():
    record = {'opportunity_id': 'arpa-h:surpass', 'source': 'ARPA-H',
              'funding_opportunity_url': SURPASS_URL, 'detail_page': SURPASS_URL,
              'status': 'posted', 'deadlines': [], 'has_preliminary_stage': False}
    doc = document()
    facts = []
    for index, (quote, day) in enumerate(zip(SURPASS_QUOTES, ('2026-11-30', '2027-01-22'))):
        citation = {**doc, 'document_url': SURPASS_URL, 'citation_url': SURPASS_URL,
                    'quote': quote, 'page': None, 'section': 'Solicitation Overview',
                    'extracted_at': STAMP}
        facts.append({'id': f'legacy-surpass-{index}', 'type': 'deadline',
                      'label': 'Full application deadline', 'date': day, 'value': day,
                      'display_value': day, 'deadline_kind': 'application',
                      'time': None, 'timezone': None, 'required': None,
                      'confidence': 'machine_extracted_needs_verification', 'citation': citation})
    facts.append({'id': 'unchanged-component', 'type': 'program_component',
                  'value': 'Scientific scope', 'citation': {'quote': 'Retained scope.'}})
    entry = {'status': 'current', 'document': doc, 'checked_at': STAMP,
             'source_signature': evidence.source_signature(record, evidence.source_for_record(record)),
             'parser_dependencies': evidence.parser_dependencies(),
             'deadline_extractor_identity': evidence.DEADLINE_EXTRACTOR_IDENTITY,
             'extractor_identity': evidence.EXTRACTOR_IDENTITY, 'facts': facts,
             'review_queue': [], 'subtopics': [{'id': 'unchanged-topic'}]}
    return record, entry


class ArpaSummaryStageContracts(unittest.TestCase):
    def test_actual_surpass_excerpts_prove_required_summary_and_later_proposal(self):
        found = evidence.extract_deadlines('arpa-h:surpass', containers(SURPASS_QUOTES), document(), STAMP)
        self.assertEqual([(f['deadline_kind'], f['date'], f['required']) for f in found],
                         [('preapplication', '2026-11-30', True), ('application', '2027-01-22', None)])
        summary, proposal = found
        self.assertEqual(summary['obligation'], 'required')
        self.assertIn('Submitting a summary is required to move forward with this opportunity.',
                      summary['requirement_citation']['quote'])
        self.assertIn('After submitting a summary, await feedback from ARPA-H before proceeding.',
                      proposal['prerequisite_citation']['quote'])
        for fact in found:
            self.assertEqual(fact['citation']['sha256'], SURPASS_SHA)
            self.assertEqual(fact['citation']['document_url'], SURPASS_URL)
            self.assertIsNone(fact['invitation_required'])
            self.assertIsNone(fact['prerequisite'])
        record = {'deadlines': [evidence.citation_deadline(fact) for fact in found]}
        before = next_submission(record, '2026-10-16')
        self.assertEqual((before['event']['kind'], before['date'], before['access']),
                         ('preapplication', '2026-11-30', 'open'))
        after = next_submission(record, '2026-12-01')
        self.assertEqual((after['event']['kind'], after['date'], after['access']),
                         ('application', '2027-01-22', 'prerequisite_closed'))

    def test_fresh_html_uses_the_same_owned_dash_fields(self):
        html = ('<h2>Solicitation Overview</h2><ul>'
                '<li>Solution Summary Due - November 30, 2026 '
                'Submitting a summary is required to move forward with this opportunity.</li>'
                '<li>After submitting a summary, await feedback from ARPA-H before proceeding. '
                'Proposal Due - January 22, 2027</li></ul>')
        sections, _ = evidence.extract_html_sections(html.encode())
        found = evidence.extract_deadlines('arpa-h:surpass', sections, document(), STAMP)
        self.assertEqual([(f['deadline_kind'], f['date'], f['required']) for f in found],
                         [('preapplication', '2026-11-30', True), ('application', '2027-01-22', None)])

    def test_clock_does_not_break_unique_summary_requirement_or_change_source_dates(self):
        doc = document('https://arpa-h.gov/explore-funding/programs/unique')
        found = evidence.extract_deadlines('arpa-h:unique', containers([UNIQUE_QUOTE]), doc, STAMP)
        self.assertEqual([(f['deadline_kind'], f['date'], f['time'], f['timezone'], f['required']) for f in found],
                         [('preapplication', '2026-10-30', '11:59PM', 'ET', True),
                          ('application', '2026-12-15', '11:59PM', 'ET', None)])
        record = {'opportunity_id': 'arpa-h:unique', 'source': 'ARPA-H', 'close_date': '2026-12-15',
                  'close_date_kind': 'submission_window_end', 'deadlines': [
                      {'kind': 'preapplication', 'date': '2026-10-29', 'time': '5:00PM', 'timezone': 'ET',
                       'confidence': 'source_listed', 'source_field': 'notice submission section'}]}
        original = deepcopy(record)
        projected = evidence.merge_document_entry(record, {'status': 'current', 'document': doc,
            'facts': found, 'deadline_extractor_identity': evidence.DEADLINE_EXTRACTOR_IDENTITY})
        self.assertEqual(record, original)
        self.assertEqual(projected['close_date'], '2026-12-15')
        self.assertEqual(projected['deadlines'][0]['date'], '2026-10-29')
        self.assertEqual(projected['deadlines'][0]['time'], '5:00PM')
        self.assertTrue(any(d['date'] == '2026-10-30' and d.get('required') is True
                            for d in projected['deadlines']))

    def test_anaphor_needs_the_adjacent_owned_summary_field(self):
        for text in (
            'Solution Summary Due: November 30, 2026. Reference the solicitation. '
            'Submitting a summary is required to move forward with this opportunity.',
            'Solution Summary Due: November 30, 2026. If selected, '
            'submitting a summary is required to move forward with this opportunity.',
            'Solution Summary Due: November 30, 2026. '
            'Submitting a summary is not required to move forward with this opportunity.',
            'Solution Summary Due: November 30, 2026. '
            'A summary is required to submit a full proposal if selected.',
            'Solution Summary Due: November 30, 2026. Proposal Due: January 22, 2027. '
            'A summary is required to submit a full proposal.',
        ):
            with self.subTest(text=text):
                found = evidence.extract_deadlines('example', containers([text]), document(), STAMP)
                self.assertFalse(any(f.get('required') is True for f in found))
        for url in ('https://other.gov/example', 'https://arpa-h.gov.example/program'):
            found = evidence.extract_deadlines('example', containers(SURPASS_QUOTES), document(url), STAMP)
            self.assertFalse(any(f.get('field_authority') == 'official_notice_field'
                                 and f.get('required') is True for f in found))

    def test_cache_capability_repair_is_local_idempotent_and_retains_receipts(self):
        record, entry = legacy_surpass()
        original = deepcopy(entry)
        with patch.object(evidence, 'download_document', side_effect=AssertionError('No source retrieval')):
            self.assertTrue(schedule.repair_cached_arpa_summary(evidence, record, entry))
            repaired = deepcopy(entry)
            self.assertFalse(schedule.repair_cached_arpa_summary(evidence, record, entry))
        self.assertEqual(entry, repaired)
        self.assertEqual(entry['document'], original['document'])
        self.assertEqual(entry['checked_at'], original['checked_at'])
        self.assertEqual(entry['source_signature'], original['source_signature'])
        self.assertEqual(entry['parser_dependencies'], original['parser_dependencies'])
        self.assertEqual(entry['subtopics'], original['subtopics'])
        self.assertEqual(entry['facts'][-1], original['facts'][-1])
        self.assertEqual([(f['deadline_kind'], f['date'], f['required']) for f in entry['facts'][:-1]],
                         [('preapplication', '2026-11-30', True), ('application', '2027-01-22', None)])
        self.assertEqual(entry['arpa_summary_capability']['basis'], 'limited_cached_quote')
        for fact, old in zip(entry['facts'], original['facts']):
            self.assertEqual(fact['citation']['quote'], old['citation']['quote'])
            if fact['type'] == 'deadline':
                self.assertEqual(fact['citation']['extracted_at'], STAMP)
                self.assertEqual(fact['interpretation_basis'], 'limited_cached_quote')
        self.assertEqual(schedule.SCHEDULE_VERSION, 'submission-fields-21')

    def test_cache_repair_rejects_unbound_quotes_and_changed_source(self):
        for mutation in ('quote_sha', 'quote_url', 'source_signature', 'source_url', 'failed'):
            record, entry = legacy_surpass()
            if mutation == 'quote_sha':
                for fact in entry['facts'][:-1]: fact['citation']['sha256'] = 'c' * 64
            elif mutation == 'quote_url':
                for fact in entry['facts'][:-1]: fact['citation']['document_url'] = SURPASS_URL + '-other'
            elif mutation == 'source_signature': entry['source_signature'] = 'changed'
            elif mutation == 'source_url': record['funding_opportunity_url'] = SURPASS_URL + '-other'
            else: entry['status'] = 'failed'
            before = deepcopy(entry)
            with self.subTest(mutation=mutation):
                self.assertFalse(schedule.repair_cached_arpa_summary(evidence, record, entry))
                self.assertEqual(entry, before)


if __name__ == '__main__':
    unittest.main()
