"""Actual topic-owned periods cannot become one universal project duration."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts import extract_document_evidence as extractor
from scripts import notice_duration


CASES = json.loads((Path(__file__).parent / 'fixtures/parsing/notice-duration.json').read_bytes())


def extract(identifier, text):
    case = CASES[identifier]
    citation = case['fact']['citation']
    return [fact for fact in extractor.extract_document_facts(
        {'opportunity_id': identifier},
        [{'text': text, 'page': citation.get('page'), 'section': citation.get('section')}],
        case['document'], citation['extracted_at'], families={'award_context'})
        if fact['type'] == 'project_duration']


class NoticeDurationTests(unittest.TestCase):
    def test_actual_differing_topic_periods_are_withheld_from_fresh_and_quote_paths(self):
        for identifier in ('364174', '340828'):
            case = CASES[identifier]
            with self.subTest(opportunity_id=identifier):
                self.assertTrue(notice_duration.unscoped_duration(case['fact']))
                self.assertEqual(extract(identifier, case['fact']['citation']['quote']), [])
        self.assertEqual(extract('364174', CASES['364174']['page_text']), [])

    def test_actual_simple_duration_and_amendment_remain_supported(self):
        for identifier in ('364033', '364020'):
            old = CASES[identifier]['fact']
            with self.subTest(opportunity_id=identifier):
                self.assertFalse(notice_duration.unscoped_duration(old))
                facts = extract(identifier, old['citation']['quote'])
                self.assertEqual(len(facts), 1)
                self.assertEqual(facts[0]['value'], old['value'])
                self.assertEqual(facts[0]['display_value'], old['display_value'])

    def test_simple_maximum_keeps_existing_scalar_value_and_explicit_display(self):
        for text in ('Project period: up to 36 months.',
                     'Project duration not to exceed 36 months.',
                     'The maximum period of performance is 36 months.'):
            with self.subTest(text=text):
                facts = extract('364033', text)
                self.assertEqual(facts[0]['value'], {'amount': 36, 'unit': 'months'})
                self.assertEqual(facts[0]['display_value'], 'Up to 36 months')
                self.assertEqual(facts[0]['parser_version'], notice_duration.VERSION)

    def test_guard_does_not_infer_scope_or_change_explicitly_scoped_facts(self):
        old = CASES['340828']['fact']
        scoped = {**deepcopy(old), 'track': 'Track 1'}
        self.assertFalse(notice_duration.unscoped_duration(scoped))
        unrelated = {**deepcopy(old), 'value': {'amount': 12, 'unit': 'months'}}
        self.assertFalse(notice_duration.unscoped_duration(unrelated))
        self.assertFalse(notice_duration.unscoped_duration({**deepcopy(old), 'type': 'expected_awards'}))

    def test_numbered_section_ends_topic_ownership(self):
        text = 'Topic Area 1: Equipment\n1. General award terms\nProject duration: 60 months.'
        self.assertEqual(extract('364033', text)[0]['display_value'], '60 months')


if __name__ == '__main__':
    unittest.main()
