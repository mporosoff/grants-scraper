"""DOE's generic companion cannot replace program-specific evidence."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from scripts import enrich_catalog as enrich, extract_document_evidence as evidence
from scripts import source_documents, subtopic_sources
from scripts.pull_grants import collect_attachments, normalize


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/parsing/doe-primary-notices.json').read_bytes())
NOW = datetime(2026, 11, 1, 23, tzinfo=timezone.utc)


class DoePrimaryNoticeTests(unittest.TestCase):
    def test_official_inventory_is_complete_and_program_part_wins_independent_of_order_or_date(self):
        for case in FIXTURE['cases']:
            with self.subTest(opportunity_id=case['opportunity_id']):
                attachments = collect_attachments(case['detail'])
                self.assertEqual(len(attachments), len(case['attachments']))
                self.assertEqual(attachments[0]['id'], case['expected_primary_id'])
                for rows in (attachments, list(reversed(attachments))):
                    rows = deepcopy(rows)
                    for item in rows:
                        if source_documents.is_doe_companion_document(item):
                            item['created_date'] = 'Nov 01, 2026 12:00:00 PM EST'
                    self.assertEqual(enrich.select_primary_document(rows)['url'],
                                     next(a['download_url'] for a in rows if a['id'] == case['expected_primary_id']))
                normalized = normalize({'id': case['opportunity_id']}, case['detail'])
                self.assertEqual(normalized['nofo_pdf_url'], attachments[0]['download_url'])
                self.assertEqual(len(normalized['all_attachments']), len(case['attachments']))

    def test_companion_only_and_duplicate_routes_do_not_create_a_primary(self):
        companion = next(a for a in FIXTURE['cases'][0]['attachments'] if source_documents.is_doe_companion_document(a))
        self.assertIsNone(enrich.select_primary_document([companion], [companion['download_url']]))
        record = {'primary_document_url': companion['download_url'], 'primary_document_name': companion['file_name'],
                  'document_urls': [companion['download_url']]}
        self.assertEqual(source_documents.document_candidates(record), [])
        self.assertIsNone(evidence.source_for_record(record))

    def test_classifier_preserves_other_agency_scientific_parts_and_doe_part1(self):
        for name in ('NASA_NOFO_Part_II.pdf', 'DARPA_Scientific_Part2.pdf', 'Part2.pdf',
                     'SiC Cladding NOFO Part 1 DE-FOA0003577-0001.pdf', 'DE-FOA-0003665 Part 1.pdf'):
            with self.subTest(name=name):
                self.assertFalse(source_documents.is_doe_companion_document({'name': name}))
        self.assertTrue(source_documents.is_doe_companion_document({'name': 'DE-FOA-0003641_NOFO_Part_II.pdf'}))
        self.assertFalse(source_documents.is_doe_companion_document({'name': 'DE-FOA-0003641_Part1.pdf',
                                                                      'description': 'See generic Part 2'}))

    def test_actual_aspect_exchange_notice_remains_owned_while_root_portal_is_not_a_notice(self):
        self.assertEqual(evidence.source_for_record(FIXTURE['owned_exchange_control']),
            {'url': 'https://exchange.energy.gov/FoaDetails.aspx?FoaId=4d0f9925-93dc-4997-b8f9-652937afbce3',
             'name': None, 'kind': 'agency_notice'})
        self.assertIsNone(evidence.source_for_record({'source': 'Grants.gov',
                                                     'funding_opportunity_url': 'https://exchange.energy.gov/'}))

    def test_unchanged_cached_companion_is_narrowly_refreshed_then_reused(self):
        for case in FIXTURE['cases']:
            with self.subTest(opportunity_id=case['opportunity_id']):
                record = deepcopy(case['record'])
                cached = deepcopy(case['cached_enrichment'])
                self.assertEqual(cached['source_signature'], enrich.record_signature(record))
                catalog = {'generated_at': '2026-11-01T21:07:21Z', 'opportunities': [record]}
                cache = {'schema_version': enrich.CACHE_SCHEMA_VERSION, 'records': {case['opportunity_id']: cached}}
                fetch = Mock(return_value=case['detail'])
                current, cache = enrich.enrich_catalog(catalog, cache, fetcher=fetch, request_delay=0,
                    max_agency_updates=0, now=NOW)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(current['opportunities'][0]['attachment_count'], len(case['attachments']))
                self.assertIn(str(case['expected_primary_id']), current['opportunities'][0]['primary_document_url'])
                # Use the unchanged input signature: this is a selection-policy
                # recovery, not a reason to refetch every ordinary record.
                enrich.enrich_catalog(catalog, cache, fetcher=fetch, request_delay=0, max_agency_updates=0, now=NOW)
                self.assertEqual(fetch.call_count, 1)

    def test_failed_metadata_refresh_cannot_keep_the_wrong_one_click_link(self):
        case = FIXTURE['cases'][0]
        result = enrich.merge_detail(case['record'], case['cached_enrichment'], NOW.date())
        self.assertFalse(result.get('primary_document_url'))
        self.assertEqual(result['cost_share_required'], case['record']['cost_share_required'])

    def test_fresh_and_retained_companion_claims_are_withheld_without_altering_source_authority(self):
        for case in FIXTURE['cases']:
            with self.subTest(opportunity_id=case['opportunity_id']):
                entry = deepcopy(case['cached_evidence']); before = deepcopy(entry)
                row = evidence.merge_document_entry(case['record'], entry)
                self.assertEqual(entry['status'], 'source_changed')
                self.assertEqual(entry['facts'], [])
                self.assertEqual(entry['program_areas'], [])
                self.assertEqual(entry['subtopics'], [])
                self.assertIsNone(row['document_evidence'])
                self.assertIsNone(row['document_search_text'])
                for key in ('close_date', 'cost_share_required', 'award_floor', 'award_ceiling', 'total_program_funding'):
                    self.assertEqual(row.get(key), case['record'].get(key))
                for key in ('document', 'checked_at', 'version_history', 'source_signature'):
                    self.assertEqual(entry.get(key), before.get(key))
                self.assertFalse(entry['primary_document_guard']['source_retrieved'])
                repaired = deepcopy(entry)
                evidence.withhold_doe_companion_entry(entry)
                self.assertEqual(entry, repaired)
                text = 'Program funding is $1 million. Cost sharing is not required. Artificial intelligence and cybersecurity.'
                containers = [{'text': text, 'page': 1}]
                self.assertEqual(evidence.extract_document_facts(case['record'], containers, entry['document'], 'fixture'), [])
                self.assertEqual(evidence.extract_program_areas(containers, entry['document'], 'fixture'), [])
                self.assertEqual(evidence.validated_program_area_hits(before), [])
                self.assertEqual(evidence.subtopic_fields(case['record'], b'', [], entry['document'], 'fixture', True),
                                 {'subtopics': [], 'subtopic_reason': 'doe_generic_companion'})

    def test_secondary_companion_is_never_fetched_or_segmented(self):
        case = FIXTURE['cases'][0]
        sources = subtopic_sources.attachment_sources(case['opportunity_id'],
            detail_fetcher=lambda _: case['detail'], collector=collect_attachments)
        self.assertEqual(len(sources), 1)
        self.assertIn(str(case['expected_primary_id']), sources[0]['url'])
        companion = next(a for a in case['attachments'] if source_documents.is_doe_companion_document(a))
        parser = Mock(side_effect=AssertionError('Generic companion must not be parsed'))
        subtopic_sources.best_segmentation({'opportunity_id': case['opportunity_id']}, b'generic',
            {'url': companion['download_url'], 'name': companion['file_name']}, extract_containers=parser,
            download=Mock(), detail_fetcher=lambda _: {}, collector=lambda _: [])
        parser.assert_not_called()

    def test_non_applicable_cyber_plan_is_not_scope_but_real_genesis_challenges_remain(self):
        controls = FIXTURE['program_context_controls']
        policy = controls['364174:cybersecurity']['citation']
        self.assertEqual(evidence.program_area_context_rejection(policy), 'non_applicable_award_requirement')
        for key in ('364033:cybersecurity', '364033:artificial intelligence', '364174:artificial intelligence'):
            with self.subTest(key=key):
                self.assertIsNone(evidence.program_area_context_rejection(controls[key]['citation']))
        for identifier in ('364174', '364033'):
            hits = [hit for key, hit in controls.items() if key.startswith(identifier + ':')]
            doc = {'name': 'DE-FOA-0003641_Part1.pdf'}
            retained = evidence.validated_program_area_hits({'document': doc, 'program_areas': hits})
            self.assertEqual('cybersecurity' in [h['label'] for h in retained], identifier == '364033')


if __name__ == '__main__':
    unittest.main()
