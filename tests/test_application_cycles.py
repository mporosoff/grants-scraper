from copy import deepcopy
from datetime import date
import unittest

from scripts import extract_document_evidence as evidence, notice_schedule
from scripts.currentness import record_is_current
from scripts.submission_schedule import application_cycle_end, next_submission


URL = 'https://apply07.grants.gov:443/grantsws/rest/opportunity/att/download/355662'
PRIMARY_URL = 'https://grants.gov/grantsws/rest/opportunity/att/download/355662'
DIGEST = 'f555ee710c592974672fbd9b715eda046305afdf3d7a99d9994384c5215cc371'
STAMP = '2026-11-17T20:03:56.200457Z'
QUOTE = ('1 Notice of Funding Opportunity Research Facilities Act Program '
    'FUNDING YEAR: Fiscal Year (FY) 2027 and 2028 APPLICATION DEADLINE: '
    'FY 2027 March 15, 2027 FY 2028 March 15, 2028 '
    'ANTICIPATED PROGRAM FUNDING: FY 2027 $121,127,200 FY 2028 $121,127,200')


def retained_record():
    """The bounded retained public schedule that stopped publication PR 422."""
    document = {'url': URL, 'sha256': DIGEST, 'name': 'FY27-RFAP-NOFO-P.pdf',
                'source_kind': 'primary_notice', 'content_type': 'application/pdf'}
    citation = {'document_url': URL, 'citation_url': URL + '#page=1',
        'document_name': document['name'], 'sha256': DIGEST, 'page': 1, 'section': None,
        'location': 'page 1', 'quote': QUOTE, 'extracted_at': STAMP,
        'structural_reference': {'block_id': 'pdf-1-19', 'kind': 'line'}}
    fact = evidence.make_fact('364271', 'deadline', 'Full application deadline',
        '2027-03-15', '2027-03-15', citation, deadline_kind='application',
        date='2027-03-15', time=None, timezone=None, required=None)
    fact['id'] = 'evidence-364271-7b3f46ac976f'
    record = {'opportunity_id': '364271', 'opportunity_number': 'USDA-NIFA-OP-012541',
        'title': 'Research Facilities Act Program', 'agency_code': 'USDA-NIFA',
        'source': 'Grants.gov', 'status': 'posted', 'close_date': '2027-03-15',
        'archive_date': '2027-04-14', 'last_updated': '2026-11-16', 'version': '1',
        'primary_document_url': PRIMARY_URL, 'document_evidence_status': 'current',
        'document_evidence_checked_at': STAMP,
        'document_evidence': {'schema_version': evidence.EVIDENCE_SCHEMA_VERSION,
            'document': document, 'facts': [fact], 'review_queue': [], 'extraction': {}},
        'deadlines': [{'kind': 'application', 'date': '2027-03-15',
            'confidence': 'official_structured', 'source_field': 'CloseDate',
            'source': 'Grants.gov XML extract', 'estimated': False,
            'document_evidence_id': fact['id'], 'document_confidence': fact['confidence']}]}
    record['document_search_text'] = evidence.clean_text(' '.join(
        str(value) for value in (fact['label'], fact['display_value'], citation['quote'])))
    return record


def corrected_record():
    record = retained_record()
    assert evidence.refine_application_cycles(record)
    return record


class ApplicationCyclesTests(unittest.TestCase):
    def test_qualified_or_nonapplication_native_fields_do_not_become_firm_new_cycles(self):
        for label in ('ANTICIPATED APPLICATION DEADLINE:', 'RECOMMENDED APPLICATION DEADLINE:',
                      'RESUBMISSION APPLICATION DEADLINE:', 'PRE-APPLICATION DEADLINE:'):
            quote = QUOTE.replace('APPLICATION DEADLINE:', label)
            self.assertEqual(notice_schedule.application_cycle_fields(quote), [])
            record = retained_record()
            record['document_evidence']['facts'][0]['citation']['quote'] = quote
            self.assertFalse(evidence.refine_application_cycles(record))

    def test_actual_retained_primary_field_restores_both_annual_cycles(self):
        record = retained_record()
        before = deepcopy(record)
        self.assertFalse(record_is_current(record, date(2027, 3, 16))[0])
        self.assertTrue(evidence.refine_application_cycles(record))
        self.assertEqual(application_cycle_end(record), '2028-03-15')
        self.assertEqual(record['close_date'], before['close_date'])
        self.assertEqual(record['archive_date'], before['archive_date'])
        self.assertEqual(record['document_evidence_checked_at'], STAMP)
        self.assertEqual(record['document_evidence']['facts'][0]['id'], before['document_evidence']['facts'][0]['id'])
        self.assertEqual([(fact['cycle'], fact['date']) for fact in record['document_evidence']['facts']],
                         [('FY2027', '2027-03-15'), ('FY2028', '2028-03-15')])
        self.assertTrue(all(fact['application_class'] == 'unspecified'
                            for fact in record['document_evidence']['facts']))
        for as_of, expected in [('2027-03-16', True), ('2027-04-15', True),
                                ('2028-03-15', True), ('2028-03-16', False)]:
            with self.subTest(as_of=as_of):
                self.assertEqual(record_is_current(record, date.fromisoformat(as_of))[0], expected)
        self.assertEqual(next_submission(record, '2027-03-16')['date'], '2028-03-15')
        self.assertEqual(next_submission(record, '2028-03-16')['access'], 'closed')
        again = deepcopy(record)
        self.assertFalse(evidence.refine_application_cycles(record))
        self.assertEqual(record, again)

    def test_source_owned_application_class_and_track_are_not_reinterpreted(self):
        for field, value in [('application_class', 'resubmission'), ('track', 'B'), ('estimated', True)]:
            record = retained_record()
            record['deadlines'][0][field] = value
            before = deepcopy(record)
            self.assertFalse(evidence.refine_application_cycles(record))
            self.assertEqual(record, before)

    def test_ordinary_fresh_and_cached_projection_preserve_the_same_cycles(self):
        base = retained_record()
        document = base['document_evidence']['document']
        facts = evidence.extract_document_facts(base, [{'text': QUOTE, 'page': 1}], document, STAMP,
                                                families={'deadlines'})
        native = [fact for fact in facts if fact.get('parser_version') == notice_schedule.APPLICATION_CYCLES_VERSION]
        self.assertEqual([(fact['cycle'], fact['date']) for fact in native],
                         [('FY2027', '2027-03-15'), ('FY2028', '2028-03-15')])
        entry = {'status': 'current', 'document': document, 'facts': facts, 'checked_at': STAMP,
                 'deadline_extractor_identity': evidence.DEADLINE_EXTRACTOR_IDENTITY}
        first = evidence.merge_document_entry(base, deepcopy(entry))
        self.assertEqual(application_cycle_end(first), '2028-03-15')
        self.assertEqual(len(first['deadlines']), 2)
        second = evidence.merge_document_entry(first, deepcopy(entry))
        self.assertEqual(second, first)
        self.assertFalse(evidence.refine_application_cycles(first))

    def test_unowned_or_nonapplication_fields_cannot_extend_record_lifetime(self):
        original = corrected_record()
        variants = []
        for key, value in [('document_evidence_status', 'failed'), ('primary_document_url', 'https://example.org/other.pdf')]:
            variants.append(original | {key: value})
        for url in ('https://grants.gov/grantsws/rest/opportunity/att/download/355663',
                    PRIMARY_URL + '?alternate=1', PRIMARY_URL + '#other',
                    PRIMARY_URL.replace('grants.gov', 'grants.gov.example.org'),
                    PRIMARY_URL.replace('grants.gov', 'user@grants.gov'),
                    PRIMARY_URL.replace('grants.gov', 'grants.gov:444')):
            variants.append(original | {'primary_document_url': url})
        for field, value in [('document_url', 'https://example.org/other.pdf'), ('sha256', '0' * 64), ('page', 2)]:
            row = deepcopy(original)
            row['document_evidence']['facts'][1]['cycle_citation'][field] = value
            variants.append(row)
        for field, value in [('deadline_kind', 'concept_paper'), ('estimated', True),
                             ('date_qualifier', 'anticipated'), ('application_class', 'resubmission'), ('track', 'B')]:
            row = deepcopy(original)
            row['document_evidence']['facts'][1][field] = value
            variants.append(row)
        row = deepcopy(original)
        row['document_evidence']['facts'][1]['cycle_citation']['quote'] = (
            'Applicants may expect a second opportunity on March 15, 2028.')
        variants.append(row)
        row = deepcopy(original)
        row['deadlines'][0]['document_evidence_id'] = 'different-fact'
        variants.append(row)
        row = deepcopy(original)
        row['deadlines'][1]['evidence_id'] = 'different-fact'
        variants.append(row)
        for record in variants:
            with self.subTest(record=record):
                self.assertIsNone(application_cycle_end(record))
                self.assertFalse(record_is_current(record, date(2027, 3, 16))[0])

    def test_explicit_terminal_status_and_source_review_expiry_still_close_the_call(self):
        record = corrected_record()
        for status in ('closed', 'archived', 'cancelled', 'withdrawn'):
            self.assertFalse(record_is_current(record | {'status': status}, date(2027, 4, 15))[0])
        self.assertFalse(record_is_current(record | {'source_review_after': '2027-04-14'}, date(2027, 4, 15))[0])
        self.assertFalse(record_is_current(record | {'source_review_after': 'invalid'}, date(2027, 4, 15))[0])


if __name__ == '__main__':
    unittest.main()
