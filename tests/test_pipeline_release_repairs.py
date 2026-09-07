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
    enrich_document_evidence, empty_cache, source_for_record, scoped_html, extract_deadlines,
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

    def test_optional_html_end_tags_do_not_leak_sibling_notices(self):
        record, _ = self.entry()
        notice = NOTICE.replace(b'<h1>Synthetic bounded notice</h1>',
            b'<h1>Synthetic bounded notice</h1><ul><li>First contact<li>Second contact</ul><p>Optional paragraph<div>Closed block</div>')
        containers, _ = extract_containers(notice, 'text/html', '', record['primary_document_url'])
        text = ' '.join(container['text'] for container in containers)
        self.assertIn(b'Second contact', scoped_html(notice, record['primary_document_url']))
        self.assertIn('October 29, 2099', text)
        self.assertNotIn('Unrelated sibling', text)
        with self.assertRaisesRegex(ValueError, 'bounded article'):
            extract_containers(notice.replace(b'</article>', b'', 1), 'text/html', '', record['primary_document_url'])
        with self.assertRaisesRegex(ValueError, 'bounded article'):
            extract_containers(notice.replace(b'<h1>', b'<article class="o-detail"></article><h1>', 1),
                               'text/html', '', record['primary_document_url'])

    def test_shared_due_dates_survive_semicolons_and_keep_later_precise_times(self):
        record, entry = self.entry()
        text = ('Applications have annual due dates of June 22, 2026; May 3, 2027; and May 1, 2028. '
                'Applications for projects starting no earlier than September 1, 2026, must be received '
                'by 7:59 p.m. Alaska Standard Time on June 22, 2026. '
                'Applications must be received by 7:59 p.m. AKST on May 3, 2027, for projects starting '
                'no earlier than September 1, 2027, and May 1, 2028, for projects starting no earlier than September 1, 2028.')
        facts = extract_deadlines(record['opportunity_id'], [{'text': text}], entry['document'], entry['checked_at'])
        self.assertEqual([f['date'] for f in facts], ['2026-06-22', '2027-05-03', '2028-05-01'])
        self.assertTrue(all(f['time'] == '7:59 p.m.' for f in facts))
        self.assertEqual([f['timezone'] for f in facts], ['Alaska', 'AKST', 'AKST'])
        entry['facts'] = facts
        entry.pop('deadline_extractor_identity')
        result = merge_document_entry(record, entry)
        self.assertTrue({'2026-06-22', '2027-05-03', '2028-05-01'} <= {d['date'] for d in result['deadlines']})

    def test_explicit_submission_labels_survive_local_context_validation(self):
        record, entry = self.entry()
        for text, kind in [
            ('Application Deadlines: May 11, 2026, and December 15, 2026.', 'application'),
            ('Submissions must be submitted by December 15, 2026 (11:59 pm ET).', 'application'),
            ('Solution Summary Due: December 15, 2026 (4:00PM ET).', 'application'),
            ('The application period will close December 15, 2026.', 'application'),
            ('Closing Date for this opportunity is December 15, 2026.', 'application'),
            ('Following notification of funding amount: Full proposals will be submitted. Submission Dates and Times Closing Date for Applications: December 15, 2026.', 'application'),
            ('Letters of Interest must be submitted by December 15, 2026.', 'letter_of_intent'),
        ]:
            with self.subTest(text=text):
                facts = extract_deadlines(record['opportunity_id'], [{'text': text}], entry['document'], entry['checked_at'])
                self.assertIn(('2026-12-15', kind), [(f['date'], f['deadline_kind']) for f in facts])

    def test_independently_timed_clauses_keep_their_own_stage_and_timezone(self):
        record, entry = self.entry()
        for text, kinds in [
            ('Application Deadline March 1, 2027 at 5:00 p.m. Eastern Time; Application Deadline April 1, 2027 at 6:00 p.m. Pacific Time', ['application', 'application']),
            ('Letter of Intent Deadline March 1, 2027 at 5:00 p.m. Eastern Time; full application deadline April 1, 2027 at 6:00 p.m. Pacific Time', ['letter_of_intent', 'application']),
            ('Application due dates: March 1, 2027 at 5:00 p.m. Eastern Time; April 1, 2027 at 6:00 p.m. Pacific Time', ['application', 'application']),
            ('Application Deadline at 5:00 p.m. Eastern Time on March 1, 2027; Application Deadline at 6:00 p.m. Pacific Time on April 1, 2027', ['application', 'application']),
            ('Application Deadline March 1, 2027 at 5:00 p.m. Eastern Time, Application Deadline April 1, 2027 at 6:00 p.m. Pacific Time', ['application', 'application']),
        ]:
            with self.subTest(text=text):
                facts = extract_deadlines(record['opportunity_id'], [{'text': text}], entry['document'], entry['checked_at'])
                self.assertEqual([(f['date'], f['time'], f['timezone']) for f in facts],
                    [('2027-03-01', '5:00 p.m.', 'Eastern'), ('2027-04-01', '6:00 p.m.', 'Pacific')])
                self.assertEqual([f['deadline_kind'] for f in facts], kinds)
                entry['facts'] = facts
                entry.pop('deadline_extractor_identity', None)
                published = merge_document_entry(record, entry)
                self.assertEqual([(d['date'], d['time'], d['timezone']) for d in published['deadlines'] if d.get('evidence_id')],
                    [('2027-03-01', '5:00 p.m.', 'Eastern'), ('2027-04-01', '6:00 p.m.', 'Pacific')])

    def test_a_list_item_time_does_not_fill_another_item_with_unknown_time(self):
        record, entry = self.entry()
        for text, times in [
            ('Application due dates March 1, 2027; April 1, 2027 at 6:00 p.m. Pacific Time', [None, '6:00 p.m.']),
            ('Application due dates at 5:00 p.m. Eastern Time on March 1, 2027; April 1, 2027', ['5:00 p.m.', '5:00 p.m.']),
        ]:
            with self.subTest(text=text):
                facts = extract_deadlines(record['opportunity_id'], [{'text': text}], entry['document'], entry['checked_at'])
                self.assertEqual([f['time'] for f in facts], times)

    def test_missing_times_stay_unknown_across_all_list_clause_boundaries(self):
        record, entry = self.entry()
        for separator in ['; ', ', ', ', and ', ' and ', ' or ', ' • ', ' | ']:
            for labeled in [False, True]:
                for timed_first in [False, True]:
                    for time_before in [False, True]:
                        with self.subTest(separator=separator, labeled=labeled,
                                          timed_first=timed_first, time_before=time_before):
                            items = []
                            for index, date in enumerate(['March 1, 2027', 'April 1, 2027']):
                                label = 'Application Deadline ' if labeled else ''
                                timed = (index == 0) == timed_first
                                time = '6:00 p.m. Pacific Time'
                                items.append(label + ((f'at {time} on {date}' if time_before else f'{date} at {time}') if timed else date))
                            text = ('' if labeled else 'Application due dates: ') + separator.join(items)
                            facts = extract_deadlines(record['opportunity_id'], [{'text': text}], entry['document'], entry['checked_at'])
                            # An explicitly introductory time governs an unlabeled shared list.
                            expected = ['6:00 p.m.' if (index == 0) == timed_first or
                                        (not labeled and timed_first and time_before) else None for index in range(2)]
                            self.assertEqual([f['time'] for f in facts], expected)
                            self.assertEqual([f['timezone'] for f in facts], ['Pacific' if time else None for time in expected])
                            entry['facts'] = facts
                            entry.pop('deadline_extractor_identity', None)
                            published = merge_document_entry(record, entry)
                            self.assertEqual([d['time'] for d in published['deadlines'] if d.get('evidence_id')], expected)

    def test_comma_attached_time_and_date_internal_comma_keep_their_owners(self):
        record, entry = self.entry()
        text = 'Application due dates: March 1, 2027, at 5:00 p.m. Eastern Time, April 1, 2027, May 1, 2027 at 6:00 p.m. Pacific Time'
        facts = extract_deadlines(record['opportunity_id'], [{'text': text}], entry['document'], entry['checked_at'])
        self.assertEqual([(f['date'], f['time'], f['timezone']) for f in facts],
            [('2027-03-01', '5:00 p.m.', 'Eastern'), ('2027-04-01', None, None), ('2027-05-01', '6:00 p.m.', 'Pacific')])

    def test_pdf_field_bullets_do_not_publish_administrative_dates(self):
        record, entry = self.entry()
        text = ('Pre-Application Submission Deadline: 5:00 p.m. Eastern Time (ET), March 1, 2027 '
                '• Invitation to Submit an Application: April 1, 2027 '
                '• Application Submission Deadline: 11:59 p.m. ET, May 1, 2027 '
                '• End of Application Verification Period: 5:00 p.m. ET, June 1, 2027')
        facts = extract_deadlines(record['opportunity_id'], [{'text': text}], entry['document'], entry['checked_at'])
        self.assertEqual([(f['date'], f['time'], f['timezone']) for f in facts],
            [('2027-03-01', '5:00 p.m.', 'Eastern'), ('2027-05-01', '11:59 p.m.', 'ET')])

    def test_legacy_cached_time_requires_its_own_quote_support(self):
        record, entry = self.entry()
        text = 'Application Deadline March 1, 2027, Application Deadline April 1, 2027 at 6:00 p.m. Pacific Time'
        facts = extract_deadlines(record['opportunity_id'], [{'text': text}], entry['document'], entry['checked_at'])
        facts[0].update(time='6:00 p.m.', timezone='Pacific')
        entry['facts'] = facts
        entry.pop('deadline_extractor_identity')
        stamp, digest = entry['checked_at'], entry['document']['sha256']
        result = merge_document_entry(record, entry)
        self.assertEqual([d['date'] for d in result['deadlines'] if d.get('evidence_id')], ['2027-04-01'])
        self.assertEqual((entry['checked_at'], entry['document']['sha256']), (stamp, digest))
        self.assertTrue(any(q['type'] == 'deadline_evidence_withheld' for q in result['document_evidence']['review_queue']))

    def test_cached_clock_and_canonical_zone_equivalence_is_precise(self):
        record, original = self.entry()
        for quoted, stored, zone, kept in [
            ('5:00 PM Eastern Time', '17:00', 'America/New_York', True),
            ('12 a.m. Eastern Time', '00:00', 'ET', True),
            ('12 p.m. Eastern Time', '12:00', 'Eastern', True),
            ('5 p.m. Eastern Time', '17:00', 'Pacific', False),
            ('5 p.m. Eastern Time', '17:00', 'East', False),
            ('5 p.m. Eastern Time', '05:00', 'Eastern', False),
            ('5 p.m. Eastern Time', '17:00', 'EST', False),
        ]:
            with self.subTest(quoted=quoted, stored=stored, zone=zone):
                entry = copy.deepcopy(original)
                entry['facts'] = extract_deadlines(record['opportunity_id'],
                    [{'text': f'Applications are due March 1, 2027 at {quoted}.'}], entry['document'], entry['checked_at'])
                entry['facts'][0].update(time=stored, timezone=zone)
                entry.pop('deadline_extractor_identity')
                result = merge_document_entry(record, entry)
                self.assertEqual(any(d.get('evidence_id') for d in result['deadlines']), kept)


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
