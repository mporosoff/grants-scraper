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
    DATE_RE, parse_document_date,
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
    def assert_replacement_projection(self, text, expected):
        """Exercise real fresh extraction and a legacy receipt with incidental dates."""
        record, entry = self.entry()
        facts = extract_deadlines(record['opportunity_id'], [{'text': text}], entry['document'], entry['checked_at'])
        self.assertEqual([(f['date'], f['time'], f['timezone']) for f in facts], expected)
        expected_dates = {date for date, _, _ in expected}
        invalid = []
        for match in DATE_RE.finditer(text):
            if parse_document_date(match.group(0)) in expected_dates:
                continue
            seeded = extract_deadlines(record['opportunity_id'], [{'text': 'Application Deadline ' + match.group(0)}],
                entry['document'], entry['checked_at'])
            for fact in seeded:
                fact['citation']['quote'] = text
            invalid.extend(seeded)
        entry['facts'] = facts + invalid
        entry.pop('deadline_extractor_identity', None)
        stamp, digest = entry['checked_at'], entry['document']['sha256']
        published = merge_document_entry(record, entry)
        self.assertEqual([(d['date'], d.get('time'), d.get('timezone')) for d in published['deadlines'] if d.get('evidence_id')], expected)
        self.assertEqual((entry['checked_at'], entry['document']['sha256']), (stamp, digest))
        if invalid:
            self.assertTrue(any(q['type'] == 'deadline_evidence_withheld' and q['status'] == 'needs_review'
                                for q in published['document_evidence']['review_queue']))

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
        self.assertEqual(len(warnings), 1)
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

    # Precision boundary: these representative fixtures replace the former
    # expanding English-grammar matrix. Unsupported narrative loses coverage;
    # authoritative source fields and unrelated evidence remain intact.
    def test_supported_local_fields_fresh_and_legacy(self):
        for text in [
            'Application deadline: May 1, 2027',
            'Applications due May 1, 2027',
            'Applications are due May 1, 2027',
            'Applications must be received no later than May 1, 2027',
            'Deadline extended to May 1, 2027',
            'Deadline extended until May 1, 2027',
            'Application Deadline has been extended until May 1, 2027',
            'Application Deadline moved to May 1, 2027',
            'Application Deadline changed to May 1, 2027',
            'Application Deadline revised to May 1, 2027',
            'May 1, 2027 (Application Deadline)',
            'May 1, 2027 [Application Deadline]',
        ]:
            with self.subTest(text=text):
                self.assert_replacement_projection(text, [('2027-05-01', None, None)])

    def test_unsupported_ownership_is_withheld_fresh_and_legacy(self):
        for text in [
            'Application deadline March 1, 2027 has been extended until April 1, 2027',
            'Revised the Application due date from October 05, 2026, to September 08, 2026.',
            'Application Deadline: for applicants appointed March 1, 2027, May 1, 2027',
            'Application deadline May 1, 2027 for projects starting June 1, 2027',
            'Applications have annual due dates of June 22, 2026; May 3, 2027; May 1, 2028.',
            'Applications Due on or after January 25, 2027',
            'Implementation Changes for Plans Included with Applications Due May 1, 2027',
            'Application Deadline May 1, 2027 has been extended to TBD',
            'Application Deadline May 1, 2027 revised to an unannounced date',
            'Application Deadline May 1, 2027 (optional] ',
            'Letter of Intent Full Application Deadline May 1, 2027',
            'May 1, 2027 (Application Deadline) changed to June 1, 2027',
            'Eligibility requires appointment before May 1, 2027',
        ]:
            with self.subTest(text=text):
                self.assert_replacement_projection(text, [])

    def test_corpus_pdf_fields_and_html_boundaries(self):
        record, entry = self.entry()
        for separator in [' • ', '; ', '. ', '\n']:
            text = separator.join([
                'Pre-Application (Letter of Intent) Submission Deadline: 5:00 p.m. Eastern Time (ET), September 14, 2026',
                'Full Application Submission Deadline: 11:59 p.m. ET, September 28, 2026',
                'End of Application Verification Period: 5:00 p.m. ET, October 5, 2026',
            ])
            with self.subTest(separator=separator):
                facts = extract_deadlines(record['opportunity_id'], [{'text': text}], entry['document'], entry['checked_at'])
                self.assertEqual([(f['date'], f['time'], f['timezone']) for f in facts],
                    [('2026-09-14', '5:00 p.m.', 'Eastern'), ('2026-09-28', '11:59 p.m.', 'ET')])
        html = b'<p>Application deadline May 1, 2027</p><p>Project start June 1, 2027</p>'
        containers, _ = extract_containers(html, 'text/html', '', 'https://www.nsf.gov/example')
        self.assertEqual([f['date'] for f in extract_deadlines(record['opportunity_id'], containers,
            entry['document'], entry['checked_at'])], ['2027-05-01'])

    def test_only_clear_requirement_and_clock_components_are_retained(self):
        record, entry = self.entry()
        for text, required, clock, zone in [
            ('May 1, 2027 (Application Deadline) required', True, None, None),
            ('May 1, 2027 [Application Deadline] optional', False, None, None),
            ('Applications must be received by May 1, 2027 at 5 p.m. Eastern Time', True, '5 p.m.', 'Eastern'),
            ('A concept paper is required and must be submitted by May 1, 2027', True, None, None),
            ('Application deadline May 1, 2027 at 5 p.m. Eastern Standard Time (EST)', None, '5 p.m.', 'EST'),
            ('Application deadline May 1, 2027 at 5 p.m. Eastern Standard Time (EDT)', None, None, None),
            ('Application deadline May 1, 2027 at 5 p.m. Eastern or 6 p.m. Pacific', None, None, None),
        ]:
            with self.subTest(text=text):
                facts = extract_deadlines(record['opportunity_id'], [{'text': text}], entry['document'], entry['checked_at'])
                if ' or ' in text:
                    self.assertEqual(facts, [])  # Competing clocks: the field is unsupported.
                else:
                    self.assertEqual([(f['date'], f['required'], f['time'], f['timezone']) for f in facts],
                        [('2027-05-01', required, clock, zone)])
        self.assert_replacement_projection('Application deadline (required) May 1, 2027 (optional)', [])

    def test_cached_unproved_metadata_is_withheld_without_changing_structured_deadline(self):
        record, entry = self.entry()
        structured = {'kind': 'application', 'date': '2027-05-01', 'time': '17:00',
                      'timezone': 'America/New_York', 'confidence': 'official_structured', 'required': True}
        record.update(close_date='2027-05-01', deadlines=[structured])
        for text, updates in [
            ('Application deadline May 1, 2027', {'required': False}),
            ('Application deadline May 1, 2027 at 5 p.m. Eastern Standard Time (EDT)',
             {'time': '5 p.m.', 'timezone': 'Eastern'}),
        ]:
            with self.subTest(text=text):
                entry['facts'] = extract_deadlines(record['opportunity_id'], [{'text': text}], entry['document'], entry['checked_at'])
                entry['facts'][0].update(updates)
                entry.pop('deadline_extractor_identity', None)
                stamp, digest = entry['checked_at'], entry['document']['sha256']
                result = merge_document_entry(record, entry)
                self.assertEqual(result['close_date'], record['close_date'])
                self.assertEqual([{k: v for k, v in d.items() if k not in
                    {'document_evidence_id', 'document_confidence', 'citation'}} for d in result['deadlines']], [structured])
                self.assertTrue(all(f.get('required') is None for f in result['document_evidence']['facts']))
                self.assertEqual((entry['checked_at'], entry['document']['sha256']), (stamp, digest))
                self.assertTrue(any(q['type'] == 'deadline_evidence_withheld' for q in result['document_evidence']['review_queue']))

    def test_application_must_follow_every_applicable_preliminary_stage(self):
        record, entry = self.entry()
        for application_date, other_phase, expected in [('April 1', 'I', False), ('June 1', 'I', True),
                                                         ('April 1', 'II', True)]:
            for order in [(0, 1, 2), (2, 1, 0), (1, 0, 2)]:
                with self.subTest(application_date=application_date, other_phase=other_phase, order=order):
                    texts = ['Phase I Letter of Intent Deadline: March 1, 2027',
                             f'Phase I Full Application Deadline: {application_date}, 2027',
                             f'Phase {other_phase} Pre-Application Deadline: May 1, 2027']
                    warnings = []
                    facts = extract_deadlines(record['opportunity_id'], [{'text': texts[i]} for i in order],
                        entry['document'], entry['checked_at'], warnings)
                    self.assertEqual(any(f['deadline_kind'] == 'application' for f in facts), expected)
                    self.assertEqual(any(q['type'] == 'deadline_stage_order_conflict' for q in warnings), not expected)
                    # Revalidate a legacy receipt that admitted all three facts.
                    legacy = [f for text in texts for f in extract_deadlines(record['opportunity_id'],
                        [{'text': text}], entry['document'], entry['checked_at'])]
                    entry['facts'] = legacy
                    entry.pop('deadline_extractor_identity', None)
                    published = merge_document_entry(record, entry)
                    self.assertEqual(any(d.get('evidence_id') and d['kind'] == 'application' for d in published['deadlines']), expected)

    def test_explicit_round_cycle_and_year_groups_keep_their_own_stage_order(self):
        record, entry = self.entry()
        for first, second in [('Phase I Round 1', 'Phase I Round 2'), ('Phase I Cycle I', 'Phase I Cycle II'),
                              ('Phase I Year 2027', 'Phase I Year 2028'), ('FY27 Phase I', 'FY2028 Phase I')]:
            with self.subTest(first=first, second=second):
                texts = [f'{first} Letter of Intent Deadline: January 1, 2027',
                         f'{first} Full Application Deadline: February 1, 2027',
                         f'{second} Letter of Intent Deadline: March 1, 2027',
                         f'{second} Full Application Deadline: April 1, 2027']
                warnings = []
                facts = extract_deadlines(record['opportunity_id'], [{'text': '; '.join(texts)}],
                    entry['document'], entry['checked_at'], warnings)
                self.assertEqual([f['date'] for f in facts], ['2027-01-01', '2027-02-01', '2027-03-01', '2027-04-01'])
                self.assertEqual(warnings, [])
                entry['facts'] = facts
                entry.pop('deadline_extractor_identity', None)
                result = merge_document_entry(record, entry)
                self.assertEqual(len([d for d in result['deadlines'] if d.get('evidence_id')]), 4)
        for first, second in [('Round I', 'Round 1'), ('Cycle Two', 'Cycle II'), ('FY27', 'FY2027')]:
            texts = [f'Phase I {first} Letter of Intent Deadline: March 1, 2027',
                     f'Phase I {second} Full Application Deadline: February 1, 2027']
            facts = extract_deadlines(record['opportunity_id'], [{'text': '; '.join(texts)}], entry['document'], entry['checked_at'])
            self.assertEqual([f['deadline_kind'] for f in facts], ['letter_of_intent'])

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
