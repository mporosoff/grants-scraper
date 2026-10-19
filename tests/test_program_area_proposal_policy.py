"""Proposal-use AI policy must not become the call's scientific scope."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from scripts.extract_document_evidence import (
    extract_program_areas,
    merge_document_entry,
    program_area_context_rejection,
    revalidate_program_areas_only,
    validated_program_area_hits,
)


class ProposalAiPolicyContracts(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parent / 'fixtures/sam_marad_proposal_ai_policy_20261019.json'
        self.fixture = json.loads(path.read_text(encoding='utf8'))
        self.entry = self.fixture['evidence']
        self.record = self.fixture['record']
        self.hit = next(hit for hit in self.entry['program_areas'] if hit['label'] == 'artificial intelligence')

    def fresh(self, text, *, section='Official notice'):
        return extract_program_areas([{'text': text, 'section': section}],
            self.entry['document'], self.entry['checked_at'])

    def test_real_marad_paragraph_rejected_for_both_fresh_and_retained_hits(self):
        before = deepcopy(self.entry)
        self.assertEqual(self.fixture['provenance']['candidate_id'],
                         'e5bf737b3e9e577acbf356ae11315dd04d794ef3c6244d4b112c7aa688034b5e')
        self.assertEqual(self.fixture['source_record']['topic_areas'], ['Energy'])
        self.assertEqual(program_area_context_rejection(self.hit['citation']), 'proposal_preparation_policy')
        self.assertEqual(self.fresh(self.hit['citation']['quote']), [])
        self.assertEqual([hit['label'] for hit in validated_program_area_hits(self.entry)], ['energy storage'])
        self.assertEqual(self.entry, before)

    def test_each_real_screening_and_proposal_content_sentence_is_sufficient(self):
        paragraph = self.hit['citation']['quote']
        sentences = ('Proposals will be screened for use of Artificial Intelligence (AI) tools.',
                     'Any use of AI tools in generating content for the proposal must be clearly identified and justified.')
        for sentence in sentences:
            with self.subTest(sentence=sentence):
                self.assertIn(sentence, paragraph)
                self.assertEqual(self.fresh(sentence), [])
                citation = self.hit['citation'] | {'quote': sentence}
                self.assertEqual(program_area_context_rejection(citation), 'proposal_preparation_policy')

    def test_actual_marad_reprojection_changes_only_three_discoverability_fields(self):
        before = deepcopy((self.record, self.entry))
        projected = merge_document_entry(self.record, deepcopy(self.entry))
        self.assertEqual(projected['topic_areas'], ['Energy'])
        self.assertEqual(projected['document_program_areas'], ['energy storage'])
        self.assertNotIn('artificial intelligence', projected['document_search_text'].lower())
        changed = {key for key in projected.keys() | self.record.keys()
                   if projected.get(key) != self.record.get(key)}
        self.assertEqual(changed, {'topic_areas', 'document_program_areas', 'document_search_text'})
        self.assertEqual((self.record, self.entry), before)

    def test_actual_seven_retained_sam_ai_citations_drop_only_marad(self):
        self.assertEqual(self.fixture['provenance']['sam_record_count'], 41)
        controls = self.fixture['sam_ai_citations']
        self.assertEqual(len(controls), 7)
        dropped = []
        for control in controls:
            with self.subTest(opportunity_id=control['opportunity_id']):
                hit = control['hit']
                cached = validated_program_area_hits({'program_areas': [hit]})
                fresh = self.fresh(hit['citation']['quote'])
                retained = any(value['label'] == 'artificial intelligence' for value in fresh)
                self.assertEqual(bool(cached), retained)
                if not cached:
                    dropped.append(control['opportunity_id'])
        self.assertEqual(dropped, [self.record['opportunity_id']])

    def test_policy_paragraph_does_not_hide_later_authentic_scientific_ai(self):
        control = next(value for value in self.fixture['sam_ai_citations']
                       if value['opportunity_id'] == 'sam-gov:b9d86f57c8a348238b5322eda840c54e')
        policy, science = self.hit['citation']['quote'], control['hit']['citation']['quote']
        text = policy + '\n' + science
        containers = [{'text': text, 'section': 'Official notice', 'structure': [
            {'span': [0, len(policy)], 'kind': 'paragraph', 'block_id': 'policy'},
            {'span': [len(policy) + 1, len(text)], 'kind': 'paragraph', 'block_id': 'science'}]}]
        hits = extract_program_areas(containers, self.entry['document'], self.entry['checked_at'])
        ai = next(hit for hit in hits if hit['label'] == 'artificial intelligence')
        self.assertEqual(ai['citation']['quote'], science)
        self.assertEqual(ai['citation']['structural_reference']['block_id'], 'science')
        self.assertEqual(validated_program_area_hits({'program_areas': [ai]}), [ai])

    def test_legitimate_ai_proposal_research_is_not_a_blanket_keyword_exclusion(self):
        for text in ('The program supports proposals for artificial intelligence research in vessel hydrodynamics.',
                     'Research methods must identify bias in Artificial Intelligence (AI) in Education.'):
            with self.subTest(text=text):
                hits = self.fresh(text)
                self.assertEqual([hit['label'] for hit in hits], ['artificial intelligence'])
                self.assertEqual(validated_program_area_hits({'program_areas': hits}), hits)

    def test_cached_zero_fetch_revalidation_removes_only_the_false_derived_hit(self):
        identifier = self.record['opportunity_id']
        catalog = {'opportunities': [deepcopy(self.record)], 'generated_at': '2026-10-19T01:19:04Z'}
        cache = {'records': {identifier: deepcopy(self.entry)}, 'generated_at': self.entry['checked_at']}
        rebuilt, updated, changed = revalidate_program_areas_only(catalog, cache,
            now=datetime(2026, 10, 19, tzinfo=timezone.utc))
        self.assertEqual(changed, [identifier])
        self.assertEqual(rebuilt['opportunities'][0]['topic_areas'], ['Energy'])
        self.assertEqual(rebuilt['opportunities'][0]['deadlines'], self.record['deadlines'])
        self.assertEqual(rebuilt['opportunities'][0]['document_evidence'], self.record['document_evidence'])
        expected = deepcopy(self.entry)
        expected['program_areas'] = [hit for hit in expected['program_areas'] if hit['label'] != 'artificial intelligence']
        self.assertEqual(updated['records'][identifier], expected)
        again, stable, changed = revalidate_program_areas_only(rebuilt, updated,
            now=datetime(2026, 10, 19, tzinfo=timezone.utc))
        self.assertEqual(changed, [])
        self.assertEqual(again['opportunities'], rebuilt['opportunities'])
        self.assertEqual(stable['records'], updated['records'])


if __name__ == '__main__':
    unittest.main()
