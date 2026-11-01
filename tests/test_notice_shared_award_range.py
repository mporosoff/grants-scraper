"""Genesis's owned award field shares a trailing magnitude across its range."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts import extract_document_evidence as evidence


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/parsing/364033-shared-award-range.json').read_bytes())
STAMP = '2026-11-01T22:00:00Z'


def awards(container):
    return [fact for fact in evidence.extract_document_facts(
        {'opportunity_id': FIXTURE['opportunity_id']}, [container], FIXTURE['source'], STAMP,
        families={'amounts'}) if fact['type'] == 'award_range']


class SharedAwardRangeTests(unittest.TestCase):
    def test_saved_genesis_field_preserves_both_endpoints_and_their_scale(self):
        found = awards(FIXTURE['container'])
        self.assertEqual([fact['value'] for fact in found], [FIXTURE['expected']])
        self.assertEqual(found[0]['display_value'], '$12,000,000–$25,000,000')
        self.assertTrue(found[0]['estimated'])
        self.assertEqual(found[0]['field_authority'], 'official_notice_field')
        self.assertEqual(found[0]['citation']['page'], 5)
        self.assertEqual(found[0]['citation']['sha256'], FIXTURE['source']['sha256'])
        self.assertIn('$12–25 million', found[0]['citation']['quote'])

    def test_complete_currency_endpoints_keep_the_existing_range(self):
        container = deepcopy(FIXTURE['container'])
        container['text'] = container['text'].replace('$12–25 million', '$12 million–$25 million')
        self.assertEqual([fact['value'] for fact in awards(container)], [FIXTURE['expected']])

    def test_unowned_range_does_not_become_an_award(self):
        container = deepcopy(FIXTURE['container'])
        container['text'] = 'Illustrative expenses: $12–25 million'
        self.assertEqual(awards(container), [])


if __name__ == '__main__':
    unittest.main()
