from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.build_catalog import catalog_javascript_bytes
from tools import catalog_url_projection as a, release_candidate as c


class UrlProjectionTests(unittest.TestCase):
    def setUp(self):
        self.old = 'https://portal.nyserda.ny.gov/CORE_Solicitation_Detail_Page? SolicitationId=a0rcr00001NP7i5AAD'
        self.new = self.old.replace('? ', '?')
        self.stamp = '2026-10-12T16:08:24.355794Z'
        self.audit = '2026-10-12T19:00:00Z'
        def record(url):
            return {'opportunity_id': 'nyserda:OSWPON26-1', 'title': 'Offshore wind research',
                    'agency': 'NYSERDA', 'source': 'NYSERDA', 'source_type': 'State', 'status': 'posted',
                    'close_date': '2027-02-05', 'description': 'Retain source quote: ' + self.old,
                    'detail_page': url, 'funding_opportunity_url': url, 'topic_areas': ['energy'],
                    'deadlines': [{'kind': 'application', 'date': '2027-02-05', 'source_url': url}],
                    'contacts': [{'name': 'Public office', 'source_url': url}],
                    'next_submission': {'as_of': '2026-10-12', 'access': 'open', 'date': '2027-02-05',
                                        'event': {'source_url': url}}}
        other = {'opportunity_id': '363829', 'title': 'Retained alias', 'source_aliases': [{'opportunity_id': 'vpr:old'}]}
        def data(url):
            return {a.PAYLOADS[0]: {'generated_at': self.stamp, 'record_count': 2,
                        'opportunities': [record(url), deepcopy(other)], 'diagnostics': {'source_checked_at': self.stamp}},
                    a.PAYLOADS[1]: {'sources': {'nyserda': {'fetched_at': self.stamp, 'records': [record(url)]},
                                               'other': {'records': [deepcopy(other)]}}},
                    a.PAYLOADS[2]: {'generated_at': self.stamp, 'retention_days': 90, 'events': [
                        {'id': 'original-event', 'type': 'new', 'opportunity_id': 'nyserda:OSWPON26-1',
                         'changed_at': self.stamp, 'record': record(url)},
                        {'id': 'other-event', 'type': 'amended', 'changed_at': self.stamp, 'record': deepcopy(other)}]}}
        self.before, self.after = data(self.old), data(self.new)
        counts = dict.fromkeys(a.EVIDENCE_COUNTS, 0)
        self.historical_metrics = {'refreshed_count': 33, 'not_modified_count': 2, 'failed_request_count': 10,
            'failures': [{'opportunity_id': 'other', 'error': 'HTTPError'}], 'remaining_update_count': 586,
            'archived_cache_count': 0, 'parser_recovery': {'source_requests': 45, 'reparsed_from_structure': 7,
                'pending_records': 473, 'withheld_facts': 39, 'structure_cache': {'hits': 8, 'writes': 33}},
            'subtopics': {'subtopic_record_count': 401, 'classifier_run': {'api_requests': 0}},
            'processing': {'status': 'complete', 'deferred_count': 0}}
        for values in (self.before, self.after):
            values[a.PAYLOADS[0]]['diagnostics']['document_evidence'] = counts | deepcopy(self.historical_metrics)
        self.evidence = {'schema_version': 1, 'kind': 'url', 'candidate_id': a.PARENT_ID,
                         'candidate_manifest_sha256': a.MANIFEST_SHA, 'original_generated_at': self.stamp,
                         'record_count': 2, 'url_replacements': {self.old: self.new}, 'evidence_invalidations': {},
                         'preserved_input_hashes': {name: 'a' * 64 for name in a.PRESERVED}, 'payloads': {},
                         'evidence_diagnostics': {'before': dict(counts), 'after': dict(counts)}}
        for name in a.PAYLOADS:
            if name == a.PAYLOADS[0]: old, new, ident = self.before[name]['opportunities'][0], self.after[name]['opportunities'][0], 'nyserda:OSWPON26-1'
            elif name == a.PAYLOADS[1]: old, new, ident = self.before[name]['sources']['nyserda']['records'][0], self.after[name]['sources']['nyserda']['records'][0], 'nyserda:OSWPON26-1'
            else: old, new, ident = self.before[name]['events'][0], self.after[name]['events'][0], 'original-event'
            self.evidence['payloads'][name] = {'before_sha256': a.value_hash(self.before[name]),
                'after_sha256': a.value_hash(self.after[name]), 'affected_items': {ident: {
                    'before_sha256': a.value_hash(old), 'after_sha256': a.value_hash(new), 'url_leaf_count': 5}}}

    def test_exact_url_leaves_only_across_catalog_cache_and_retained_events(self):
        original = deepcopy(self.before)
        for name in a.PAYLOADS:
            after, proof = a.corrected_payload(name, self.before[name], self.evidence)
            self.assertEqual(after, self.after[name])
            self.assertEqual(proof, self.evidence['payloads'][name]['affected_items'])
        self.assertEqual(self.before, original)
        self.assertIn(self.old, self.after[a.PAYLOADS[0]]['opportunities'][0]['description'])

    def test_changed_source_value_or_rewritten_event_is_not_a_url_correction(self):
        for name, mutate in [(a.PAYLOADS[0], lambda v: v['opportunities'][0].update(close_date='2028-02-05')),
                             (a.PAYLOADS[1], lambda v: v['sources']['nyserda'].update(fetched_at=self.audit)),
                             (a.PAYLOADS[2], lambda v: v['events'][0].update(type='amended'))]:
            before = deepcopy(self.before[name]); mutate(before)
            with self.assertRaisesRegex(ValueError, 'exact_payload'):
                a.corrected_payload(name, before, self.evidence)

    def test_wrong_host_id_scheme_or_broad_text_replacement_is_rejected(self):
        for replacement in (self.new.replace('nyserda.ny.gov', 'example.org'), self.new + '&extra=1',
                            self.new.replace('a0rcr00001NP7i5AAD', 'a0rcr00001NP7i5AAE'), self.new.replace('https:', 'http:')):
            evidence = deepcopy(self.evidence); evidence['url_replacements'][self.old] = replacement
            with self.assertRaisesRegex(ValueError, 'exact_url_normalization'):
                a.corrected_payload(a.PAYLOADS[0], self.before[a.PAYLOADS[0]], evidence)
        evidence = deepcopy(self.evidence); evidence['payloads'][a.PAYLOADS[0]]['after_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'exact_url_only_projection'):
            a.corrected_payload(a.PAYLOADS[0], self.before[a.PAYLOADS[0]], evidence)

    def test_missing_leaf_or_unexpected_duplicate_cannot_be_silently_accepted(self):
        evidence = deepcopy(self.evidence)
        evidence['payloads'][a.PAYLOADS[0]]['affected_items']['nyserda:OSWPON26-1']['url_leaf_count'] = 4
        with self.assertRaisesRegex(ValueError, 'exact_url_only_projection'):
            a.corrected_payload(a.PAYLOADS[0], self.before[a.PAYLOADS[0]], evidence)
        before = deepcopy(self.before[a.PAYLOADS[0]]); before['opportunities'].append(before['opportunities'][0])
        with self.assertRaisesRegex(ValueError, 'unique_payload_membership'):
            a.payload_projection(a.PAYLOADS[0], before, self.evidence['url_replacements'])

    def evidence_case(self):
        from scripts.submission_schedule import project
        identifier = 'nyserda:OSWPON26-1'
        old = project(self.before[a.PAYLOADS[0]]['opportunities'][0], date(2026, 10, 12))
        url_corrected = project(self.after[a.PAYLOADS[0]]['opportunities'][0], date(2026, 10, 12))
        for row in (old, url_corrected):
            row.update(document_evidence_status='current', document_evidence_checked_at=self.stamp,
                       document_evidence={'facts': [], 'review_queue': [{'type': 'parser_pending'}, {'type': 'parser_pending'}],
                                          'document': {'url': 'https://portal.nyserda.ny.gov/PortalLoginPage',
                                                                    'sha256': 'b' * 64}},
                       document_search_text=None, submission_requirements=[], document_status_signals=[])
        expected = deepcopy(url_corrected)
        expected['document_evidence_status'] = 'source_changed'
        expected['document_evidence'] = None
        for key in ('document_evidence_checked_at', 'submission_requirements', 'document_status_signals'):
            expected.pop(key)
        self.before[a.PAYLOADS[0]]['diagnostics']['document_evidence'].update(document_current_count=1, review_queue_count=2)
        self.evidence['evidence_diagnostics']['before'].update(document_current_count=1, review_queue_count=2)
        self.before[a.PAYLOADS[0]]['opportunities'][0] = old
        self.after[a.PAYLOADS[0]]['opportunities'][0] = expected
        pin = {'before_sha256': a.value_hash(url_corrected), 'after_sha256': a.value_hash(expected),
               'changed_fields': list(a.INVALIDATED_FIELDS)}
        self.evidence['evidence_invalidations'] = {identifier: pin}
        self.evidence['payloads'][a.PAYLOADS[0]].update(before_sha256=a.value_hash(self.before[a.PAYLOADS[0]]),
            after_sha256=a.value_hash(self.after[a.PAYLOADS[0]]), affected_items={identifier: {
                'before_sha256': a.value_hash(old), 'after_sha256': a.value_hash(expected), 'url_leaf_count': 5}})
        cache = {'records': {identifier: {'source_url': self.old, 'source_signature': self.old + '|||||',
            'status': 'current', 'checked_at': self.stamp, 'facts': [], 'program_areas': [], 'subtopics': []}}}
        return identifier, url_corrected, cache

    def test_changed_source_withholds_only_pinned_public_evidence_and_preserves_store(self):
        identifier, url_corrected, cache = self.evidence_case()
        retained = deepcopy(cache)
        actual, _ = a.corrected_payload(a.PAYLOADS[0], self.before[a.PAYLOADS[0]], self.evidence, cache=cache)
        self.assertEqual(actual, self.after[a.PAYLOADS[0]])
        self.assertEqual(cache, retained)
        self.assertEqual(actual['generated_at'], self.stamp)
        self.assertEqual(actual['opportunities'][1], self.before[a.PAYLOADS[0]]['opportunities'][1])
        self.assertEqual(actual['opportunities'][0]['next_submission'], url_corrected['next_submission'])
        self.assertEqual(cache['records'][identifier]['status'], 'current')
        self.assertEqual(cache['records'][identifier]['source_signature'], self.old + '|||||')
        for name in a.PAYLOADS[1:]:
            value, _ = a.corrected_payload(name, self.before[name], self.evidence, cache=cache)
            self.assertEqual(value, self.after[name])

    def test_invalidation_requires_exact_changed_empty_acquisition(self):
        identifier, row, cache = self.evidence_case()
        entry = cache['records'][identifier]
        mutations = [lambda v: v.update(source_url=self.new), lambda v: v.update(source_url='https://example.org/old'),
                     lambda v: v.update(status='failed'), lambda v: v.update(facts=[{'id': 'real-fact'}]),
                     lambda v: v.update(program_areas=['Real program']), lambda v: v.update(subtopics=[{'id': 'science'}])]
        for mutate in mutations:
            changed = deepcopy(entry); mutate(changed)
            with self.assertRaisesRegex(ValueError, 'changed_empty_acquisition'):
                a.invalidate_public_evidence(row, changed, self.evidence['evidence_invalidations'][identifier],
                                             self.evidence['url_replacements'])
        with self.assertRaisesRegex(ValueError, 'changed_empty_acquisition'):
            a.corrected_payload(a.PAYLOADS[0], self.before[a.PAYLOADS[0]], self.evidence)

    def test_unpinned_record_or_hidden_scientific_derived_data_cannot_be_withheld(self):
        identifier, row, cache = self.evidence_case()
        pin = self.evidence['evidence_invalidations'][identifier]
        changed = deepcopy(row); changed['title'] += ' changed'
        with self.assertRaisesRegex(ValueError, 'exact_evidence_record'):
            a.invalidate_public_evidence(changed, cache['records'][identifier], pin, self.evidence['url_replacements'])
        for key, value in [('document_search_text', 'Real science'), ('document_program_areas', ['Real area']),
                           ('submission_requirements', [{'kind': 'required'}]), ('document_status_signals', ['closed']),
                           ('document_evidence_status', 'failed')]:
            changed = deepcopy(row); changed[key] = value
            adjusted = dict(pin, before_sha256=a.value_hash(changed))
            with self.assertRaisesRegex(ValueError, 'empty_public_evidence'):
                a.invalidate_public_evidence(changed, cache['records'][identifier], adjusted, self.evidence['url_replacements'])

    def test_wrong_invalidation_pin_missing_membership_or_extra_field_scope_fails(self):
        identifier, row, cache = self.evidence_case()
        evidence = deepcopy(self.evidence)
        evidence['evidence_invalidations'][identifier]['after_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'exact_evidence_invalidation'):
            a.corrected_payload(a.PAYLOADS[0], self.before[a.PAYLOADS[0]], evidence, cache=cache)
        evidence = deepcopy(self.evidence)
        evidence['evidence_invalidations']['nyserda:missing'] = evidence['evidence_invalidations'].pop(identifier)
        with self.assertRaisesRegex(ValueError, 'complete_evidence_invalidations'):
            a.corrected_payload(a.PAYLOADS[0], self.before[a.PAYLOADS[0]], evidence, cache=cache)
        evidence = deepcopy(self.evidence)
        evidence['evidence_invalidations'][identifier]['changed_fields'].append('description')
        with self.assertRaisesRegex(ValueError, 'fixed_evidence_invalidations'):
            a.corrected_payload(a.PAYLOADS[0], self.before[a.PAYLOADS[0]], evidence, cache=cache)

    def test_normal_projection_cannot_restore_unrelated_source_fields_or_advance_clock(self):
        identifier, row, cache = self.evidence_case()
        changed = deepcopy(row)
        changed['document_evidence']['source_fields'] = {'topic_areas': {'present': True, 'value': ['Changed science']}}
        pin = dict(self.evidence['evidence_invalidations'][identifier], before_sha256=a.value_hash(changed))
        with self.assertRaisesRegex(ValueError, 'exact_evidence_invalidation'):
            a.invalidate_public_evidence(changed, cache['records'][identifier], pin, self.evidence['url_replacements'])
        changed = deepcopy(row); changed['next_submission']['as_of'] = '2028-01-01'
        pin['before_sha256'] = a.value_hash(changed)
        with self.assertRaisesRegex(ValueError, 'exact_evidence_invalidation'):
            a.invalidate_public_evidence(changed, cache['records'][identifier], pin, self.evidence['url_replacements'])

    def test_all_current_summary_counts_match_records_without_rewriting_run_history(self):
        _, _, cache = self.evidence_case()
        before = deepcopy(self.before[a.PAYLOADS[0]])
        actual, _ = a.corrected_payload(a.PAYLOADS[0], before, self.evidence, cache=cache)
        metrics = actual['diagnostics']['document_evidence']
        self.assertEqual({key: metrics[key] for key in a.EVIDENCE_COUNTS}, dict.fromkeys(a.EVIDENCE_COUNTS, 0))
        self.assertEqual({key: value for key, value in metrics.items() if key not in a.EVIDENCE_COUNTS}, self.historical_metrics)
        self.assertEqual({key for key in metrics if metrics[key] != before['diagnostics']['document_evidence'][key]},
                         {'document_current_count', 'review_queue_count'})
        self.assertEqual(actual['generated_at'], before['generated_at'])
        self.assertEqual(actual['diagnostics']['source_checked_at'], self.stamp)
        self.assertEqual(before, self.before[a.PAYLOADS[0]])

    def test_stale_original_summary_and_wrong_recount_pins_fail_closed(self):
        _, _, cache = self.evidence_case()
        for key in ('document_current_count', 'review_queue_count', 'citation_fact_count'):
            before = deepcopy(self.before[a.PAYLOADS[0]])
            before['diagnostics']['document_evidence'][key] += 1
            evidence = deepcopy(self.evidence)
            evidence['payloads'][a.PAYLOADS[0]]['before_sha256'] = a.value_hash(before)
            with self.assertRaisesRegex(ValueError, 'exact_evidence_diagnostics'):
                a.corrected_payload(a.PAYLOADS[0], before, evidence, cache=cache)
        for phase in ('before', 'after'):
            evidence = deepcopy(self.evidence); evidence['evidence_diagnostics'][phase]['document_failed_count'] = 1
            with self.assertRaisesRegex(ValueError, 'exact_evidence_diagnostics'):
                a.corrected_payload(a.PAYLOADS[0], self.before[a.PAYLOADS[0]], evidence, cache=cache)

    def test_summary_policy_requires_complete_eight_current_counters_only(self):
        for mutate in (lambda value: value.pop('changed_document_count'),
                       lambda value: value.update(refreshed_count=0),
                       lambda value: value.update(document_current_count=True)):
            evidence = deepcopy(self.evidence); mutate(evidence['evidence_diagnostics']['after'])
            with self.assertRaisesRegex(ValueError, 'fixed_evidence_diagnostics'):
                a.corrected_payload(a.PAYLOADS[0], self.before[a.PAYLOADS[0]], evidence)

    def fixture(self, directory):
        parent = Path(directory) / 'files'
        c.write_json(parent.parent / 'candidate.json', {'candidate_id': a.PARENT_ID})
        (parent / 'data').mkdir(parents=True)
        (parent / a.PAYLOADS[0]).write_bytes(catalog_javascript_bytes(self.before[a.PAYLOADS[0]]))
        for name in a.PAYLOADS[1:]: c.write_json(parent / name, self.before[name])
        for name in a.PRESERVED:
            c.write_json(parent / name, {'historical_source_url': self.old, 'source_signature': self.old + '|||||'})
        evidence = deepcopy(self.evidence)
        evidence['candidate_manifest_sha256'] = c.digest((parent.parent / 'candidate.json').read_bytes())
        evidence['input_hashes'] = {n: c.digest((parent / n).read_bytes()) for n in a.PAYLOADS}
        evidence['preserved_input_hashes'] = {n: c.digest((parent / n).read_bytes()) for n in a.PRESERVED}
        return parent, evidence

    def test_projection_retains_acquisition_evidence_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            parent, evidence = self.fixture(directory)
            saved = {p.relative_to(parent).as_posix(): p.read_bytes() for p in parent.rglob('*') if p.is_file()}
            with patch.object(a, 'MANIFEST_SHA', evidence['candidate_manifest_sha256']), patch.object(a, 'policy', return_value=evidence):
                first = a.projection(parent, self.audit)
                self.assertEqual(first, a.projection(parent, self.audit))
            outputs, proof = first
            self.assertFalse(set(a.PRESERVED) & set(outputs))
            self.assertEqual(json.loads(outputs[a.PAYLOADS[2]]), self.after[a.PAYLOADS[2]])
            self.assertEqual(proof['source_requests'], 0); self.assertEqual(proof['provider_requests'], 0)
            self.assertEqual(saved, {p.relative_to(parent).as_posix(): p.read_bytes() for p in parent.rglob('*') if p.is_file()})

    def test_all_original_inputs_including_acquisition_hashes_are_authenticated(self):
        for name in a.PAYLOADS + a.PRESERVED:
            with tempfile.TemporaryDirectory() as directory:
                parent, evidence = self.fixture(directory)
                path = parent / name; path.write_bytes(path.read_bytes() + b' ')
                with patch.object(a, 'MANIFEST_SHA', evidence['candidate_manifest_sha256']), patch.object(a, 'policy', return_value=evidence):
                    with self.assertRaisesRegex(ValueError, 'exact_inputs'):
                        a.projection(parent, self.audit)


if __name__ == '__main__':
    unittest.main()
