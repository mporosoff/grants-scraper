from copy import deepcopy
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
        self.evidence = {'schema_version': 1, 'kind': 'url', 'candidate_id': a.PARENT_ID,
                         'candidate_manifest_sha256': a.MANIFEST_SHA, 'original_generated_at': self.stamp,
                         'record_count': 2, 'url_replacements': {self.old: self.new},
                         'preserved_input_hashes': {name: 'a' * 64 for name in a.PRESERVED}, 'payloads': {}}
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
