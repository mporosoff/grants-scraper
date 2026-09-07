"""Isolated regressions for live refresh findings; never production inputs."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import requests

from scripts import build_opportunity_teams as teams
from scripts.build_changes import diff_catalogs
from scripts.extract_document_evidence import (
    build_document_entry, extract_containers, merge_document_entry,
    enrich_document_evidence, empty_cache, source_for_record,
)
from scripts.sources.registry import collect
from scripts.sources.merge import resolve_live_records, rebuild_catalog
from tests.test_darpa_iarpa_adapter import adapter, with_iarpa, records, AS_OF, DARPA_LIST, IARPA_LIST
from tests.test_document_evidence import base_record
from tests.test_team_provider_contracts import response
from tests import test_build_opportunity_teams as team_fixtures


class IndependentSources(unittest.TestCase):
    def collect_partition_failure(self, failed):
        data = with_iarpa()
        pages = {DARPA_LIST: json.dumps(data['darpa']), IARPA_LIST: data['iarpa'], **data['pages']}
        def get(url):
            if url in failed:
                raise requests.HTTPError('403 Forbidden for official inventory')
            return pages[url]
        instance = adapter()
        with patch.object(instance._client, 'get_text', side_effect=get):
            return collect([instance])

    def test_each_unavailable_sponsor_preserves_only_independently_verified_calls(self):
        prior = records(with_iarpa())
        for failed, prefix, count in [({IARPA_LIST}, 'darpa', 4), ({DARPA_LIST}, 'iarpa', 1)]:
            with self.subTest(failed=failed):
                published, results = self.collect_partition_failure(failed)
                self.assertFalse(results[0].ok, 'partial collection must remain visibly degraded')
                cache = {'sources': {'darpa-iarpa': {'fetched_at': '2026-09-04', 'records': prior}}}
                live, cache, summary = resolve_live_records(results, cache, AS_OF)
                self.assertEqual(len(live), count)
                self.assertTrue(all(r['opportunity_id'].startswith('darpa-iarpa:' + prefix + '-') for r in live))
                self.assertEqual(summary[0]['status'], 'partial_refresh')
                self.assertEqual(summary[0]['last_successful_refresh_at'], '2026-09-04')
                self.assertEqual(summary[0]['publication_decision'], 'published_independently_verified_records')
                current = rebuild_catalog({}, live, results, summary)
                events = diff_catalogs({'opportunities': prior}, current, as_of=AS_OF)
                self.assertFalse(any(e['type'] == 'closed_or_removed' for e in events))

    def test_verified_darpa_removal_still_closes_while_iarpa_is_unavailable(self):
        published, results = self.collect_partition_failure({IARPA_LIST})
        removed = published.pop()
        results[0].records = published
        live, _, summary = resolve_live_records(results, {'sources': {}}, AS_OF)
        current = rebuild_catalog({}, live, results, summary)
        events = diff_catalogs({'opportunities': records(with_iarpa())}, current, as_of=AS_OF)
        self.assertEqual([e['opportunity_id'] for e in events if e['type'] == 'closed_or_removed'], [removed['opportunity_id']])

    def test_both_unavailable_keep_fail_closed_policy_without_false_closure(self):
        _, results = self.collect_partition_failure({DARPA_LIST, IARPA_LIST})
        prior = records(with_iarpa())
        live, _, summary = resolve_live_records(results, {'sources': {'darpa-iarpa': {'records': prior}}}, AS_OF)
        self.assertEqual(live, [])
        self.assertEqual(summary[0]['status'], 'failed_no_fallback')
        current = rebuild_catalog({}, live, results, summary)
        self.assertFalse(any(e['type'] == 'closed_or_removed' for e in diff_catalogs({'opportunities': prior}, current, as_of=AS_OF)))


NOTICE = b'''<html><body><article class="o-detail"><h1>Synthetic bounded notice</h1>
<p>Application Deadline October 29, 2099</p>
<p>Office hours except designated holidays:</p><p>December 24, 2099-January 1, 2100</p>
<p>Deadline for Letter of Intent (LOI) submission: October 29, 2099, at 12 p.m. (noon) Eastern time.</p>
<h2>Application process</h2><p>Notification of the status of the LOI will be sent by January 1, 2099.</p>
<p>A request for a full proposal will be due by February 25, 2099, at 12 p.m. Eastern time.</p>
<p>Individual award amount: up to $2 million.</p></article>
<article class="m-post"><h2>Unrelated sibling award</h2><p>Full applications are due December 1, 2099.
The individual award amount is $99 million.</p></article></body></html>'''


class DeadlineOwnership(unittest.TestCase):
    def entry(self):
        record = base_record() | {'primary_document_url': 'https://www.simonsfoundation.org/grant/synthetic-contract/',
                                 'close_date': '2099-10-29', 'deadlines': []}
        source = source_for_record(record)
        response_data = {'content': NOTICE, 'content_type': 'text/html', 'url': source['url']}
        entry, _ = build_document_entry(record, source, response_data, None, datetime(2099, 9, 1, tzinfo=timezone.utc))
        return record, entry

    def test_only_owned_submission_stage_is_published_with_its_timezone(self):
        record, entry = self.entry()
        deadlines = [f for f in entry['facts'] if f['type'] == 'deadline']
        self.assertEqual([(f['deadline_kind'], f['date'], f['timezone']) for f in deadlines],
                         [('letter_of_intent', '2099-10-29', 'Eastern')])
        self.assertTrue(any(q['type'] == 'deadline_stage_order_conflict' for q in entry['review_queue']))
        published = merge_document_entry(record, entry)
        republished = merge_document_entry(published, entry)
        warnings = [q for q in republished['document_evidence']['review_queue'] if q['type'] == 'deadline_stage_order_conflict']
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all(q['label'] and q['status'] == 'needs_review' for q in warnings))
        self.assertEqual(published['document_evidence']['review_queue'], republished['document_evidence']['review_queue'])
        containers, _ = extract_containers(NOTICE, 'text/html', '', record['primary_document_url'])
        self.assertNotIn('Unrelated sibling', ' '.join(c['text'] for c in containers))
        self.assertNotIn('99 million', json.dumps(entry['facts']))

    def test_cache_cleanup_does_not_claim_a_new_fetch_or_modify_other_evidence(self):
        record, entry = self.entry()
        good = copy.deepcopy(entry['facts'])
        holiday = copy.deepcopy(next(f for f in good if f['type'] == 'deadline'))
        holiday.update(id='synthetic-stale-holiday', date='2099-12-24', value='2099-12-24')
        holiday['citation']['quote'] = 'Office hours except designated holidays December 24, 2099. Applications are due October 29, 2099.'
        entry['facts'].append(holiday)
        entry.pop('deadline_extractor_identity')
        entry['review_queue'].append({'type': 'deadline_conflict', 'evidence_ids': [holiday['id']]})
        timestamp, digest = entry['checked_at'], entry['document']['sha256']
        result = merge_document_entry(record, entry)
        self.assertEqual(entry['facts'], good)
        self.assertEqual((entry['checked_at'], entry['document']['sha256']), (timestamp, digest))
        self.assertEqual(result['document_evidence_checked_at'], timestamp)
        self.assertNotIn('2099-12-24', [d['date'] for d in result['deadlines']])
        self.assertFalse(any(holiday['id'] in q.get('evidence_ids', []) for q in entry['review_queue']))
        self.assertTrue(any(q['type'] == 'deadline_evidence_withheld' and q['label'] for q in result['document_evidence']['review_queue']))

    def test_ambiguous_article_markup_fails_and_old_unbounded_quotes_are_withheld(self):
        record, entry = self.entry()
        with self.assertRaisesRegex(ValueError, 'bounded article'):
            extract_containers(NOTICE.replace(b'class="m-post"', b'class="o-detail"'), 'text/html', '', record['primary_document_url'])
        entry.pop('source_scope_identity')
        cache = empty_cache(); cache['records'][record['opportunity_id']] = entry
        output, _ = enrich_document_evidence({'opportunities': [record]}, cache, max_documents=0,
            now=datetime(2099, 9, 2, tzinfo=timezone.utc))
        self.assertIsNone(output['opportunities'][0]['document_evidence'])

    def test_scope_upgrade_requires_a_body_even_when_prior_bytes_match(self):
        record, entry = self.entry()
        entry.pop('source_scope_identity')
        entry['document']['etag'] = 'prior-etag'
        cache = empty_cache(); cache['records'][record['opportunity_id']] = entry
        def not_modified(url, headers):
            self.assertEqual(headers, {}, 'old extraction boundaries cannot be validated by HTTP metadata')
            return {'status_code': 304, 'url': url}
        output, _ = enrich_document_evidence({'opportunities': [record]}, cache, fetcher=not_modified,
            request_delay=0, now=datetime(2099, 9, 2, tzinfo=timezone.utc))
        self.assertIsNone(output['opportunities'][0]['document_evidence'])
        self.assertEqual(entry['status'], 'failed')
        rebuilt, extracted = build_document_entry(record, source_for_record(record),
            {'content': NOTICE, 'content_type': 'text/html', 'url': record['primary_document_url']},
            entry, datetime(2099, 9, 2, tzinfo=timezone.utc))
        self.assertTrue(extracted)
        self.assertEqual(rebuilt['source_scope_identity'], 'simons-grant-article-1')


class NegativeResponseDiagnostics(unittest.TestCase):
    setUp = team_fixtures.ProposedTeamTests.setUp

    def test_live_style_empty_negative_stays_retryable_with_a_safe_reason(self):
        with TemporaryDirectory() as directory, patch.object(teams.time, 'sleep'):
            provider = teams.Provider(directory)
            with patch.object(provider, 'post', return_value=response({'specific': False, 'objective': '', 'roles': []})) as post:
                result, proposal = teams.generate_scope(self.scope, provider, self.claims, [], 'registry', float('inf'))
            self.assertEqual(post.call_count, 3)
            self.assertIsNone(proposal)
            self.assertTrue(result['retry_eligible'])
            self.assertEqual(result['validation_reason'], 'invalid_scientific_objective')
            self.assertEqual(provider.counters['invalid_output:invalid_scientific_objective'], 3)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(teams.validation_reason(ValueError('sensitive provider body')), 'invalid_response_structure')


if __name__ == '__main__':
    unittest.main()
