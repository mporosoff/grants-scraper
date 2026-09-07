import hashlib
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from scripts import extract_document_evidence as e
from scripts.notice_structure_cache import StructureCache, cache_key, identity


class NoticeStructureCacheTests(unittest.TestCase):
    def fixture(self):
        record = {'opportunity_id': 'fixture', 'title': 'Supported official notice',
                  'primary_document_url': 'https://example.gov/notice.html'}
        source = e.source_for_record(record)
        response = {'content': b'<h2>Cost Sharing</h2><p>Cost sharing is optional.</p>',
                    'content_type': 'text/html', 'url': source['url'], 'etag': 'version-one'}
        return record, source, response, datetime(2026, 9, 7, tzinfo=timezone.utc)

    def test_changed_scientific_body_parser_withholds_only_affected_scopes_before_fetch(self):
        from scripts import subtopic_segmentation, subtopic_structured
        record, source, response, now = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            cache = StructureCache(directory)
            prior, _ = e.build_document_entry(record, source, response, None, now, structure_cache=cache)
            child = {"subtopic_id": "fixture:a-1", "opportunity_id": "fixture:a-1",
                     "parent_id": "fixture", "summary": "Old title plus template", "subtopic_code": "1A"}
            prior.update(subtopics=[child], subtopic_method="hgeo_declared_topics",
                         subtopic_extractor_version=subtopic_segmentation.extractor_version())
            healthy_record = {**record, "opportunity_id": "healthy"}
            healthy = deepcopy(prior)
            healthy.update(subtopic_method="agency_declared_other")
            healthy['subtopics'] = [{**child, "subtopic_id": "healthy:a-1", "opportunity_id": "healthy:a-1", "parent_id": "healthy"}]
            output, store = e.enrich_document_evidence({'opportunities': [record, healthy_record]},
                {'records': {'fixture': prior, 'healthy': healthy}}, now=now + timedelta(days=1),
                max_documents=0, max_subtopic_documents=0, enable_subtopics=True,
                structure_cache=cache, fetcher=lambda *_: self.fail('Exhausted budget fetched'))
            self.assertEqual(store['records']['fixture']['subtopics'], [])
            self.assertEqual(store['records']['healthy']['subtopics'], healthy['subtopics'])
            self.assertEqual(prior['checked_at'], e.iso_utc(now))
            self.assertTrue(e.needs_subtopics(prior, True))
            sidecar = e.merge_subtopic_sidecar({}, list(store['records'].items()), {'fixture', 'healthy'}, as_of=now.date().isoformat())
            self.assertEqual(sidecar['records']['fixture']['subtopics'], [])
            self.assertEqual(len(sidecar['records']['healthy']['subtopics']), 1)
            self.assertEqual(output['diagnostics']['document_evidence']['parser_recovery']['source_requests'], 0)
            repaired = {'subtopics': [{**child, 'summary': 'Source-owned scientific body'}],
                        'subtopic_method': 'hgeo_declared_topics',
                        'subtopic_extractor_version': subtopic_segmentation.extractor_version(),
                        'subtopic_structured': {'body_parser_version': subtopic_structured.HGEO_BODY_VERSION}}
            with patch.object(e, 'subtopic_fields', return_value=repaired) as parse:
                refreshed, extracted = e.build_document_entry(record, source, response, prior, now + timedelta(days=1),
                    enable_subtopics=True, backfill_subtopics=True, structure_cache=cache)
            self.assertFalse(extracted)
            parse.assert_called_once()
            self.assertFalse(e.needs_subtopics(refreshed, True))
            self.assertNotIn('subtopic_revalidation', refreshed)
            self.assertEqual(refreshed['subtopics'][0]['opportunity_id'], 'fixture:a-1')

    def test_legacy_owned_preliminary_date_recovers_correct_stage(self):
        record, source, response, now = self.fixture()
        text = '• Pre-Application (Letter of Intent) Submission Deadline: 5:00 p.m. ET, September 8, 2026 • Application Submission Deadline: 11:59 p.m. ET, September 22, 2026'
        response['content'] = ('<p>' + text + '</p>').encode()
        entry, _ = e.build_document_entry(record, source, response, None, now)
        citation = {'quote': text, 'document_url': entry['document']['url'], 'sha256': entry['document']['sha256'],
                    'page': 4, 'extracted_at': entry['checked_at']}
        old = e.make_fact('fixture', 'deadline', 'Application deadline', '2026-09-08', 'September 8, 2026', citation,
                         date='2026-09-08', deadline_kind='application', time=None, timezone=None)
        entry['facts'] = [old]
        entry['parser_dependencies']['deadlines'] = 'old'
        with tempfile.TemporaryDirectory() as directory:
            e.quarantine_legacy_facts(record, source, entry, StructureCache(directory))
        self.assertEqual([(f['date'], f['deadline_kind']) for f in entry['facts']], [('2026-09-08', 'letter_of_intent'), ('2026-09-22', 'application')])
        self.assertEqual(entry['facts'][0]['time'], '5:00 p.m.')
        self.assertEqual(entry['facts'][0]['citation']['extracted_at'], e.iso_utc(now))
        self.assertTrue(entry['parser_pending'])

    def test_legacy_frozen_positive_facts_recover_without_new_source_claims(self):
        fixture = json.loads(Path('tests/fixtures/frozen/document_evidence.json').read_bytes())
        from scripts.enrich_catalog import read_catalog
        record = {'opportunity_id': '1001', 'primary_document_url': fixture['records']['1001']['document']['url']}
        entry = fixture['records']['1001']
        stamp = entry['checked_at']
        with tempfile.TemporaryDirectory() as directory:
            e.quarantine_legacy_facts(record, e.source_for_record(record), entry, StructureCache(directory))
        self.assertEqual({f['date'] for f in entry['facts'] if f['type'] == 'deadline'}, {'2026-09-02', '2026-09-30'})
        self.assertTrue(any(f['type'] == 'eligibility_excerpt' and 'institutions of higher education' in f['value'] for f in entry['facts']))
        self.assertTrue(any(f['type'] == 'review_criteria' and 'scientific merit' in f['value'] for f in entry['facts']))
        self.assertEqual(entry['checked_at'], stamp)

    def test_normal_entrypoint_recovers_changed_family_without_refreshing_source_clock(self):
        record, source, response, now = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            cache = StructureCache(directory)
            entry, _ = e.build_document_entry(record, source, response, None, now, structure_cache=cache)
            entry['parser_dependencies']['cost_share'] = 'old'
            entry['facts'][0]['value'] = True
            store = {'records': {'fixture': entry}}
            output, store = e.enrich_document_evidence({'opportunities': [record]}, store,
                now=now + timedelta(days=1), structure_cache=cache,
                fetcher=lambda *_: self.fail('Parser-only migration fetched a source'))
            self.assertFalse(output['opportunities'][0]['document_evidence']['facts'][0]['value'])
            self.assertEqual(store['records']['fixture']['checked_at'], e.iso_utc(now))
            counters = output['diagnostics']['document_evidence']['parser_recovery']
            self.assertEqual((counters['reparsed_from_structure'], counters['source_requests']), (1, 0))
            again, _ = e.enrich_document_evidence(output, store, now=now + timedelta(days=1), structure_cache=cache,
                fetcher=lambda *_: self.fail('Unchanged warm record fetched'))
            self.assertEqual(again['diagnostics']['document_evidence']['parser_recovery']['reparsed_from_structure'], 0)

    def test_pending_legacy_facts_are_quarantined_without_erasing_structured_deadline(self):
        record, source, response, now = self.fixture()
        record['deadlines'] = [{'kind': 'application', 'date': '2027-05-01', 'source': 'Grants.gov'}]
        with tempfile.TemporaryDirectory() as directory:
            cache = StructureCache(directory)
            entry, _ = e.build_document_entry(record, source, response, None, now)
            entry['parser_dependencies']['cost_share'] = 'old'
            entry['facts'][0]['value'] = True
            entry['facts'].append({'id': 'unaffected', 'type': 'review_criteria', 'value': 'scientific merit', 'citation': {}})
            output, store = e.enrich_document_evidence({'opportunities': [record]}, {'records': {'fixture': entry}},
                max_documents=0, now=now + timedelta(days=1), structure_cache=cache,
                fetcher=lambda *_: self.fail('Exhausted budget fetched'))
            result = output['opportunities'][0]
            self.assertEqual(result['deadlines'], record['deadlines'])
            restored = result['document_evidence']['facts']
            self.assertIn('unaffected', [f['id'] for f in restored])
            correction = next(f for f in restored if f['type'] == 'cost_share')
            self.assertIs(correction['value'], False)
            self.assertEqual(correction['interpretation_basis'], 'limited_cached_quote')
            self.assertEqual(correction['replaces_evidence_id'], entry['facts'][0]['id'])
            self.assertEqual(result['document_evidence_checked_at'], e.iso_utc(now))
            pending = store['records']['fixture']['parser_pending']
            self.assertEqual(pending['withheld_count'], 1)
            self.assertEqual(len(list((Path(directory) / 'quarantine').glob('*.json'))), 1)
            self.assertTrue(e.due_for_check(store['records']['fixture'], e.source_signature(record, source), now, 14))

    def test_parser_upgrade_cache_miss_requires_body_and_recovers_same_bytes(self):
        record, source, response, now = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            cache = StructureCache(directory)
            entry, _ = e.build_document_entry(record, source, response, None, now)
            entry['parser_dependencies']['cost_share'] = 'old'
            entry['facts'][0]['value'] = True
            requests = []
            def fetch(url, headers):
                requests.append(headers)
                return response
            output, store = e.enrich_document_evidence({'opportunities': [record]}, {'records': {'fixture': entry}},
                now=now + timedelta(days=1), request_delay=0, structure_cache=cache, fetcher=fetch)
            self.assertEqual(requests, [{}])
            result = store['records']['fixture']
            self.assertFalse(result['facts'][0]['value'])
            self.assertFalse(result['document']['changed_since_previous'])
            self.assertEqual(result['document']['version'], 1)
            self.assertEqual(result['document']['first_seen_at'], e.iso_utc(now))
            self.assertEqual(result['checked_at'], e.iso_utc(now + timedelta(days=1)))
            self.assertIsNotNone(cache.read(result['structure_identity']))

    def test_due_http_304_after_local_reparse_preserves_interpretation_and_counts_request(self):
        record, source, response, now = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            cache = StructureCache(directory)
            entry, _ = e.build_document_entry(record, source, response, None, now, structure_cache=cache)
            entry['parser_dependencies']['cost_share'] = 'old'
            entry['facts'][0]['value'] = True
            def fetch(url, headers):
                self.assertEqual(headers, {'If-None-Match': 'version-one'})
                return {'status_code': 304, 'url': url}
            output, store = e.enrich_document_evidence({'opportunities': [record]}, {'records': {'fixture': entry}},
                now=now + timedelta(days=15), request_delay=0, structure_cache=cache, fetcher=fetch)
            result = store['records']['fixture']
            self.assertFalse(result['facts'][0]['value'])
            self.assertEqual(result['document']['first_seen_at'], e.iso_utc(now))
            self.assertEqual(result['checked_at'], e.iso_utc(now + timedelta(days=15)))
            counters = output['diagnostics']['document_evidence']['parser_recovery']
            self.assertEqual((counters['reparsed_from_structure'], counters['source_requests']), (1, 1))

    def test_failure_keeps_original_source_receipt_and_does_not_retry_inside_backoff(self):
        record, source, response, now = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            cache = StructureCache(directory)
            entry, _ = e.build_document_entry(record, source, response, None, now)
            entry['parser_dependencies']['cost_share'] = 'old'
            def fail(*_):
                raise RuntimeError('Unavailable official source')
            output, store = e.enrich_document_evidence({'opportunities': [record]}, {'records': {'fixture': entry}},
                now=now + timedelta(days=1), request_delay=0, structure_cache=cache, fetcher=fail)
            self.assertEqual(store['records']['fixture']['checked_at'], e.iso_utc(now))
            self.assertIsNone(output['opportunities'][0]['document_evidence'])
            self.assertNotIn('cancelled', output['opportunities'][0].get('document_status_signals', []))
            again, _ = e.enrich_document_evidence(output, store, now=now + timedelta(days=1, hours=1),
                structure_cache=cache, fetcher=lambda *_: self.fail('Retry backoff bypassed'))
            self.assertEqual(again['diagnostics']['document_evidence']['parser_recovery']['source_requests'], 0)
            self.assertFalse(e.due_for_check(store['records']['fixture'], e.source_signature(record, source),
                now + timedelta(days=1, hours=1), 14, needs_subtopics=True))

    def test_parser_upgrade_reuses_original_structure_and_preserves_source_receipts(self):
        record = {'opportunity_id': 'fixture', 'primary_document_url': 'https://example.gov/notice.html'}
        source = {'url': record['primary_document_url'], 'name': 'notice.html', 'kind': 'primary_notice'}
        response = {'content': b'<h2>Cost Sharing</h2><p>Cost sharing is optional.</p>', 'content_type': 'text/html', 'url': source['url']}
        checked = datetime(2026, 9, 7, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            cache = StructureCache(directory)
            previous, _ = e.build_document_entry(record, source, response, None, checked, structure_cache=cache)
            previous['parser_dependencies']['cost_share'] = 'previous-contract'
            previous['facts'][0]['value'] = True
            with patch.object(e.notice_semantics, 'amount_facts', side_effect=AssertionError('Unchanged amount stage repeated')):
                result = e.reparse_from_structure(record, source, previous, checked + timedelta(days=1), cache)
            self.assertFalse(result['facts'][0]['value'])
            self.assertEqual(result['checked_at'], previous['checked_at'])
            self.assertEqual(result['document'], previous['document'])
            self.assertEqual(result['parser_migration']['changed_families'], ['cost_share'])
            self.assertNotEqual(result['interpreted_at'], previous['interpreted_at'])
            self.assertIsNone(e.reparse_from_structure(record, source, result, checked + timedelta(days=2), cache))

    def test_scoped_portal_selector_survives_http_fragment_omission(self):
        guid = '00000000-0000-0000-0000-000000000001'
        source = {'url': 'https://eere-exchange.energy.gov/#FoaId' + guid, 'name': None, 'kind': 'agency_notice'}
        content = f'<div class="foaGroup"><h2><a name="FoaId{guid}">Official notice</a></h2><p>Concept Paper Submission Deadline: October 9, 2026</p></div>'.encode()
        result, _ = e.build_document_entry({'opportunity_id': 'fixture'}, source,
            {'url': 'https://eere-exchange.energy.gov/', 'content_type': 'text/html', 'content': content},
            None, datetime(2026, 9, 7, tzinfo=timezone.utc))
        self.assertEqual(result['document']['url'], source['url'])
        self.assertTrue(any(f.get('deadline_kind') == 'concept_paper' for f in result['facts']))

    def test_source_hash_scope_route_and_structure_identity_are_independent(self):
        containers, extraction = e.extract_html_sections(b'<h2>Deadline</h2><p>May 1, 2027</p>')
        dependencies = identity({'sha256': 'a' * 64, 'url': 'https://example.gov/notice'}, 'scope-one')
        with tempfile.TemporaryDirectory() as directory:
            cache = StructureCache(directory)
            self.assertTrue(cache.write(dependencies, containers, extraction))
            self.assertEqual(cache.read(dependencies)[0][0]['text'], containers[0]['text'])
            for key in dependencies:
                with self.subTest(key=key):
                    self.assertIsNone(cache.read({**dependencies, key: 'different'}))

    def test_corruption_eviction_and_invalid_ownership_are_misses(self):
        containers, extraction = e.extract_html_sections(b'<h2>Deadline</h2><p>May 1, 2027</p>')
        dependencies = identity({'sha256': 'b' * 64, 'url': 'https://example.gov/notice'}, None)
        with tempfile.TemporaryDirectory() as directory:
            cache = StructureCache(directory)
            cache.write(dependencies, containers, extraction)
            path = Path(directory) / (cache_key(dependencies) + '.json')
            path.write_bytes(b'{broken')
            self.assertIsNone(cache.read(dependencies))
            path.unlink()
            self.assertIsNone(cache.read(dependencies))
            containers[0]['structure'][0]['span'] = (0, 100000)
            self.assertFalse(cache.write(dependencies, containers, extraction))

    def test_concurrent_writes_publish_only_complete_valid_entries(self):
        containers, extraction = e.extract_html_sections(b'<h2>Funding</h2><p>Award Ceiling: $560,000</p>')
        dependencies = identity({'sha256': 'c' * 64, 'url': 'https://example.gov/notice'}, None)
        with tempfile.TemporaryDirectory() as directory:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: StructureCache(directory).write(dependencies, containers, extraction), range(12)))
            self.assertTrue(all(results))
            self.assertIsNotNone(StructureCache(directory).read(dependencies))
            self.assertEqual(len(list(Path(directory).glob('*.json'))), 1)
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
