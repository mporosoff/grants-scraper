"""Publication and consumer contracts for the retained 362893 closing note."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from scripts import extract_document_evidence as e
from scripts.submission_schedule import events, next_submission
from tools.verify_notice_publication import administrative_close_contract, verify


DOCUMENT = 'https://apply07.grants.gov:443/grantsws/rest/opportunity/att/download/353221'
DOCUMENT_SHA = '674074f38f7feae92ad3ce87fb09cf34b29f7f565c07ae725a886928083cc8ff'
NOTE = ('Pre-proposals are due on July 29, 2026, and are submitted outside GrantSolutions.'
    'Important note: The Closing Date for this funding opportunity is December 16, 2026. '
    'However, that is the date that the funding opportunity closes and applications can no longer be accepted. '
    'To give applicants the time for the "back and forth" necessary to fix issues and complete their applications, '
    'the actual due date for Application Submission in GrantSolutions is October 14, 2026.')
AS_OF = '2026-10-19'


def retained_record():
    """Bounded public fields from authenticated failed candidate 6c09712d."""
    facts = []
    for identifier, date, label, field_id, page, quote in (
        ('evidence-362893-8ec7e2973b8a', '2026-10-14',
         'actual due date for Application Submission in \nGrantSolutions is', 'cover:3:1117', 3,
         'the actual due date for Application Submission in GrantSolutions is October 14, 2026.'),
        ('evidence-362893-d73b8a8be959', '2026-12-16', 'Closing Date for Applications', 'cover:15:254', 15,
         'Closing Date for Applications: 12/16/2026'),
    ):
        facts.append({'id': identifier, 'type': 'deadline', 'label': 'Full application deadline',
            'value': date, 'display_value': date, 'deadline_kind': 'application', 'date': date,
            'subject': 'submission', 'stage': 'application', 'application_class': 'unspecified',
            'cycle': None, 'track': None, 'field_authority': 'official_notice_field',
            'confidence': 'machine_extracted_needs_verification',
            'citation': {'document_url': DOCUMENT, 'sha256': DOCUMENT_SHA, 'page': page, 'quote': quote,
                'structural_reference': {'field_label': label, 'field_id': field_id}}})
    record = {'opportunity_id': '362893', 'title': 'F26AS00104 State ANS Management Plan 2026',
        'source': 'Grants.gov', 'status': 'posted', 'close_date': '2026-12-16',
        'primary_document_url': 'https://grants.gov/grantsws/rest/opportunity/att/download/353221',
        'detail_page': 'https://www.grants.gov/search-results-detail/362893',
        'document_evidence_status': 'current',
        'deadlines': [{'kind': 'submission', 'date': '2026-12-16', 'source_field': 'CloseDate',
            'confidence': 'official_structured', 'source': 'Grants.gov XML extract',
            'source_url': 'https://www.grants.gov/search-results-detail/362893', 'note': NOTE},
            *[e.citation_deadline(fact) for fact in facts]],
        'document_evidence': {'schema_version': 1,
            'document': {'url': DOCUMENT, 'sha256': DOCUMENT_SHA}, 'facts': facts}}
    record['next_submission'] = next_submission(record, AS_OF)
    return record


def corrected_record():
    record = retained_record()
    e.refine_administrative_close(record)
    record['next_submission'] = next_submission(record, AS_OF)
    return record


def browser_cases():
    refined = corrected_record()
    return {'retained': retained_record(), 'corrected': refined,
        'administrative_only': {**deepcopy(refined), 'deadlines': [deepcopy(refined['deadlines'][0])]},
        'as_of': AS_OF}


class AdministrativeCloseContract(unittest.TestCase):
    def test_original_retained_record_is_rejected_independently_of_idempotent_replay(self):
        record = retained_record()
        catalog = {'generated_at': '2026-10-19T17:00:00Z', 'opportunities': [record]}
        cache = {'records': {}}
        before = deepcopy((catalog, cache))
        with patch.object(e, 'enrich_document_evidence', return_value=deepcopy((catalog, cache))):
            report = verify(catalog, cache, candidate_id='6c09712d-retained')
        self.assertFalse(report['publication_ready'])
        finding = next(row for row in report['changes'] if row.get('reason'))
        self.assertEqual(finding['opportunity_id'], '362893')
        self.assertIn('next_submission', finding['fields'])
        self.assertIn('submission_events', finding['fields'])
        self.assertTrue(all('before' in row and 'after' in row for row in finding['differences']))
        self.assertLess(len(json.dumps(finding)), 15000)
        self.assertEqual((report['source_requests'], report['provider_requests']), (0, 0))
        self.assertEqual((catalog, cache), before)

    def test_corrected_exact_public_projection_passes_independent_contract(self):
        record = corrected_record()
        self.assertEqual(administrative_close_contract(record, AS_OF), [])
        self.assertEqual(next_submission(record, AS_OF)['access'], 'closed')
        self.assertIsNone(next_submission(record, AS_OF)['date'])
        self.assertEqual([row['date'] for row in events(record)], ['2026-10-14'])
        self.assertEqual(record['close_date'], '2026-12-16')
        self.assertEqual(record['deadlines'][0]['note'], NOTE)
        self.assertEqual(record['document_evidence']['facts'][0]['id'], 'evidence-362893-8ec7e2973b8a')
        self.assertEqual(record['document_evidence']['facts'][1]['citation'],
                         retained_record()['document_evidence']['facts'][1]['citation'])

    def test_partial_or_tampered_qualification_cannot_satisfy_the_gate(self):
        for field in ('source', 'fact', 'derived', 'selection'):
            with self.subTest(field=field):
                record = corrected_record()
                if field == 'source':
                    record['deadlines'][0]['date_qualifier_citation']['actual_application_date'] = '2026-10-15'
                elif field == 'fact':
                    record['document_evidence']['facts'][1]['deadline_kind'] = 'application'
                elif field == 'derived':
                    record['deadlines'][2].pop('date_qualifier')
                else:
                    record['next_submission'] = retained_record()['next_submission']
                self.assertTrue(administrative_close_contract(record, AS_OF))

    def test_legacy_generic_close_is_qualified_without_erasing_source_bytes(self):
        record = retained_record()
        record['deadlines'][0]['kind'] = 'application'
        note = record['deadlines'][0]['note']
        self.assertTrue(e.refine_administrative_close(record))
        self.assertFalse(e.refine_administrative_close(record))
        self.assertEqual(record['deadlines'][0]['kind'], 'submission')
        self.assertEqual(record['deadlines'][0]['date_qualifier'], 'administrative')
        self.assertEqual(record['deadlines'][0]['note'], note)
        self.assertEqual(next_submission(record, AS_OF)['access'], 'closed')

    def test_same_date_and_actual_portal_windows_are_not_removed(self):
        for note in (NOTE.replace('October 14, 2026', 'December 16, 2026'),
                     'The portal accepts application submissions through December 16, 2026. October 14 is recommended.'):
            record = retained_record()
            record['deadlines'][0]['note'] = note
            if 'actual due date' in note:
                record['document_evidence']['facts'][0]['date'] = '2026-12-16'
            before = deepcopy(record)
            self.assertFalse(e.refine_administrative_close(record))
            self.assertEqual(record, before)
            self.assertEqual(administrative_close_contract(record, AS_OF), [])

    def test_ambiguous_or_differently_owned_actual_proof_does_not_reclassify(self):
        for change in ('duplicate', 'scope', 'document', 'estimated', 'multiple-source-owners'):
            with self.subTest(change=change):
                record = retained_record()
                actual = record['document_evidence']['facts'][0]
                if change == 'duplicate':
                    duplicate = deepcopy(actual); duplicate['id'] += '-duplicate'
                    record['document_evidence']['facts'].append(duplicate)
                elif change == 'scope':
                    actual['application_class'] = 'resubmission'
                elif change == 'document':
                    actual['citation']['sha256'] = 'a'*64
                elif change == 'estimated':
                    actual['estimated'] = True
                else:
                    record['deadlines'].append(deepcopy(record['deadlines'][0]))
                before = deepcopy(record)
                self.assertFalse(e.refine_administrative_close(record))
                self.assertEqual(record, before)
                self.assertEqual(administrative_close_contract(record, AS_OF), [])

    def test_distinct_native_application_field_at_same_end_date_remains_actionable(self):
        record = retained_record()
        fact = record['document_evidence']['facts'][1]
        fact['citation']['structural_reference']['field_label'] = 'Application Deadline'
        e.refine_administrative_close(record)
        record['next_submission'] = next_submission(record, AS_OF)
        self.assertEqual(record['document_evidence']['facts'][1]['deadline_kind'], 'application')
        self.assertEqual(next_submission(record, AS_OF)['date'], '2026-12-16')
        self.assertEqual(administrative_close_contract(record, AS_OF), [])

    def test_fresh_and_cached_public_document_paths_apply_the_same_qualification(self):
        record = retained_record()
        record.pop('document_evidence'); record.pop('document_evidence_status'); record.pop('next_submission')
        record['deadlines'] = record['deadlines'][:1]
        document = {'url': DOCUMENT, 'sha256': DOCUMENT_SHA}
        facts = e.extract_document_facts(record, [{'page': 3, 'text': NOTE},
            {'page': 15, 'text': 'Submission Dates and Times Closing Date for Applications: 12/16/2026 '
                'Closing Date Explanation'}], document, '2026-10-19T17:05:45.556389Z', families={'deadlines'})
        entry = {'status': 'current', 'document': document, 'facts': facts,
            'checked_at': '2026-10-19T17:05:45.556389Z', 'deadline_extractor_identity': e.DEADLINE_EXTRACTOR_IDENTITY}
        before = deepcopy(entry)
        fresh = e.merge_document_entry(record, entry)
        cached = e.merge_document_entry(deepcopy(fresh), json.loads(json.dumps(entry)))
        for result in (fresh, cached):
            self.assertEqual(next_submission(result, AS_OF)['access'], 'closed')
            self.assertEqual(administrative_close_contract(result, AS_OF), [])
            self.assertEqual(result['deadlines'][0]['date_qualifier'], 'administrative')
        self.assertEqual(fresh, cached)
        self.assertEqual(entry, before, 'Raw cached native source facts changed')


if __name__ == '__main__':
    unittest.main()
