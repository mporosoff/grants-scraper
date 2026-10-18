"""Retain one protected publication's rolling feed across source recovery.

The MARAD event is a bounded public projection from candidate a10 (artifact
12150451884). It models a *prospective* later S1 publication, not an assertion
that a10 was published. The actual older 17cab feed is already contained in
the original 633 feed; its full zero-loss comparison is retained as incident
evidence rather than copied into this fixture.
"""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from scripts.build_changes import diff_catalogs, merge_history, write_change_feed
from scripts.sources.merge import load_catalog, save_catalog
from tools import catalog_reconcile as repair
from tools import release_candidate as c


AS_OF = date(2026, 10, 18)
MARAD = {
    'opportunity_id': 'sam-gov:7d63d061eb82403c8b6b4afb9afca040',
    'opportunity_number': '693JF726R000016',
    'title': 'A Study on Vessel Design Challenge',
    'agency': 'U.S. Department of Transportation - Maritime Administration (MARAD)',
    'source': 'SAM.gov', 'source_type': 'Federal', 'status': 'posted',
    'posted_date': '2026-10-16', 'close_date': '2027-01-10',
    'last_updated': '2026-10-16', 'version': None,
    'detail_page': 'https://sam.gov/opp/7d63d061eb82403c8b6b4afb9afca040/view',
    'funding_opportunity_url': 'https://sam.gov/opp/7d63d061eb82403c8b6b4afb9afca040/view',
}
PUBLISHED_EVENT = {
    'id': 'f7b752fb7efc97fa5484', 'type': 'new', 'label': 'New opportunity',
    'changed_at': '2026-10-17T13:49:40.046164Z',
    'opportunity_id': MARAD['opportunity_id'],
    'detail': 'First appeared in the public catalog', 'record': MARAD,
}


def feed(events):
    return {'schema_version': 1, 'generated_at': '2026-10-17T13:53:39Z',
            'retention_days': 90, 'events': deepcopy(events)}


class PublishedFeedRecovery(unittest.TestCase):
    """Real temporary Git publications; no mocked hash or reference verifier."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='feed-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'
        self.root.mkdir()
        self.state = Path(self.temp.name) / 'state'
        self.state.mkdir()
        self.checkpoint = self.state / ('source-' + 'c' * 64)
        self.catalog = {'generated_at': '2026-10-17T13:49:40.046164Z',
                        'opportunities': [deepcopy(MARAD)]}
        self.git('init', '-q')
        self.git('config', 'user.email', 'feed-contract@example.invalid')
        self.git('config', 'user.name', 'Feed contract')
        self.git('config', 'core.autocrlf', 'false')
        self.publication = self.publish(feed([PUBLISHED_EVENT]))

    def git(self, *args):
        return subprocess.check_output(
            ['git', '-C', str(self.root), *args], stderr=subprocess.PIPE,
        ).decode('utf8').strip()

    def publish(self, history, *, invalid_bytes=None):
        (self.root / 'data').mkdir(exist_ok=True)
        (self.root / 'feeds').mkdir(exist_ok=True)
        (self.root / 'release').mkdir(exist_ok=True)
        save_catalog(self.catalog, self.root / 'data/opportunities.js')
        raw = c.encoded(history) if invalid_bytes is None else invalid_bytes
        (self.root / 'feeds/changes.json').write_bytes(raw)
        manifest = {'schema_version': 1, 'candidate_format': c.VERSION,
                    'files': c.file_hashes(self.root, sorted(repair.PUBLISHED_FILES))}
        manifest['candidate_id'] = c.digest(c.encoded(manifest))
        c.write_json(self.root / 'release/candidate.json', manifest)
        c.write_json(self.root / 'release/candidate-source.json',
                     {'candidate_id': manifest['candidate_id']})
        self.git('add', 'data', 'feeds', 'release')
        self.git('commit', '--allow-empty', '-qm', 'Protected public feed fixture')
        return self.git('rev-parse', 'HEAD')

    def capture(self):
        return repair.capture_published_predecessor(self.root, self.checkpoint)

    def older_parent(self, *, source_checkpoint=True):
        """A valid source checkpoint whose selected parent lacks S1's event."""
        parent = Path(self.temp.name) / 'parent'
        files = parent / 'files'
        (files / 'data').mkdir(parents=True, exist_ok=True)
        (files / 'config').mkdir(exist_ok=True)
        (files / 'feeds').mkdir(exist_ok=True)
        save_catalog(self.catalog, files / 'data/opportunities.js')
        c.write_json(files / 'data/source_records.json', {
            'schema_version': 1, 'sources': {'sam-gov': {'records': [deepcopy(MARAD)]}}})
        c.write_json(files / 'data/document_evidence.json', {'records': {}, 'subtopic_only': {}})
        c.write_json(files / 'config/opportunity_team_model.json', {'opportunities': []})
        c.write_json(files / 'feeds/changes.json', feed([]))
        manifest = {'candidate_id': 'b' * 64, 'generation_files': c.file_hashes(files, [
            'data/opportunities.js', 'data/source_records.json', 'data/document_evidence.json',
            'config/opportunity_team_model.json', 'feeds/changes.json'])}
        c.write_json(parent / 'candidate.json', manifest)
        c.write_json(self.state / 'reconciliation.json', {'operation_sha256': 'c' * 64})
        if not source_checkpoint:
            return parent, manifest
        metadata = self.capture()
        summary = {'operation_sha256': 'c' * 64, 'published_predecessor': metadata,
                   'active_sam_ids': [MARAD['opportunity_id']], 'files': {}}
        for name in ('data/opportunities.js', 'data/source_records.json', 'data/document_evidence.json'):
            target = self.checkpoint / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(files / name, target)
            summary['files'][name] = c.digest(target.read_bytes())
        c.write_json(self.checkpoint / 'summary.json', summary)
        return parent, manifest

    def resume(self, parent, manifest):
        with patch.object(c, 'load', return_value=manifest), \
                patch.object(repair, 'verify_source_delta'), \
                patch('scripts.sources.registry.collect', side_effect=AssertionError('source repeated')) as collect, \
                patch.object(c, 'create', side_effect=AssertionError('candidate created')) as create, \
                patch('tools.catalog_reconcile_spend.reserve', side_effect=AssertionError('provider reservation')) as reserve:
            try:
                return repair.reconcile(self.root, parent, self.state)
            finally:
                collect.assert_not_called()
                create.assert_not_called()
                reserve.assert_not_called()

    def test_later_source_round_keeps_event_that_unchanged_catalog_cannot_regenerate(self):
        fresh = diff_catalogs(self.catalog, self.catalog, as_of=AS_OF)
        self.assertNotIn(PUBLISHED_EVENT['id'], {event['id'] for event in fresh})
        self.assertNotIn(PUBLISHED_EVENT['id'], {event['id'] for event in merge_history([], fresh, as_of=AS_OF)})
        metadata = self.capture()
        # Original generation restoration has replaced the live feed first.
        c.write_json(self.root / 'feeds/changes.json', feed([]))
        repair.restore_published_predecessor(self.root, self.state, self.checkpoint, metadata)
        result = write_change_feed(load_catalog(self.state / 'published-predecessor.js'),
                                   self.catalog, self.root / 'feeds', as_of=AS_OF)
        history = c.read_json(self.root / 'feeds/changes.json')
        self.assertEqual(result, {'new_event_count': 0, 'retained_event_count': 1})
        self.assertEqual(history['events'], [PUBLISHED_EVENT])

    def test_cold_reconcile_restores_frozen_history_after_parent_and_head_advance(self):
        parent, manifest = self.older_parent()
        frozen = (self.checkpoint / 'published-changes.json').read_bytes()
        advanced = deepcopy(PUBLISHED_EVENT)
        advanced.update(id='head-only-event', changed_at='2026-10-18T14:00:00Z')
        self.publish(feed([advanced]))
        first = self.resume(parent, manifest)
        self.assertEqual((self.root / 'feeds/changes.json').read_bytes(), frozen)
        self.assertEqual(first['published_predecessor']['ref'], self.publication)
        # A second cold retry must override the original empty parent seed again.
        c.write_json(self.root / 'feeds/changes.json', feed([]))
        self.resume(parent, manifest)
        self.assertEqual((self.root / 'feeds/changes.json').read_bytes(), frozen)
        self.assertEqual(load_catalog(self.state / 'published-predecessor.js'), self.catalog)

    def test_invalid_checkpoint_cannot_recollect_reserve_or_create_a_candidate(self):
        for problem in ('missing', 'tampered', 'mixed-publication'):
            with self.subTest(problem=problem):
                parent, manifest = self.older_parent()
                saved = self.checkpoint / 'published-changes.json'
                if problem == 'missing':
                    saved.unlink()
                elif problem == 'tampered':
                    saved.write_bytes(saved.read_bytes() + b' ')
                else:
                    metadata = c.read_json(self.checkpoint / 'summary.json')
                    metadata['published_predecessor']['files']['feeds/changes.json'] = 'f' * 64
                    c.write_json(self.checkpoint / 'summary.json', metadata)
                with self.assertRaises(ValueError):
                    self.resume(parent, manifest)

    def test_restore_validates_every_frozen_member_before_writing_outputs(self):
        metadata = self.capture()
        sentinel = b'original parent feed'
        for name in ('published-predecessor.js', 'published-changes.json'):
            with self.subTest(name=name):
                saved = self.checkpoint / name
                good = saved.read_bytes()
                saved.write_bytes(good + b' ')
                (self.root / 'feeds/changes.json').write_bytes(sentinel)
                with self.assertRaisesRegex(ValueError, 'published_predecessor_bytes'):
                    repair.restore_published_predecessor(self.root, self.state, self.checkpoint, metadata)
                self.assertEqual((self.root / 'feeds/changes.json').read_bytes(), sentinel)
                self.assertFalse((self.state / 'published-predecessor.js').exists())
                saved.write_bytes(good)

    def test_missing_or_malformed_published_json_refuses_before_source_collection(self):
        parent, manifest = self.older_parent(source_checkpoint=False)
        for raw in (b'{not-json', c.encoded({'events': {}}), c.encoded({'schema_version': 1})):
            with self.subTest(raw=raw):
                self.publish(None, invalid_bytes=raw)
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    self.resume(parent, manifest)
        (self.root / 'feeds/changes.json').unlink()
        self.git('add', '-u')
        self.git('commit', '-qm', 'Missing protected feed fixture')
        with self.assertRaises(subprocess.CalledProcessError):
            self.resume(parent, manifest)

    def test_mixed_catalog_history_manifest_and_changed_pointer_refuse(self):
        for problem in ('feed-hash', 'pointer'):
            with self.subTest(problem=problem):
                self.publish(feed([PUBLISHED_EVENT]))
                if problem == 'feed-hash':
                    c.write_json(self.root / 'feeds/changes.json', feed([]))
                else:
                    c.write_json(self.root / 'release/candidate-source.json', {'candidate_id': 'f' * 64})
                self.git('add', 'feeds', 'release')
                self.git('commit', '-qm', 'Mixed publication fixture')
                with self.assertRaisesRegex(ValueError, 'published_'):
                    self.capture()

    def test_normal_ninety_day_expiry_and_xml_rebuild_use_restored_json(self):
        boundary = deepcopy(PUBLISHED_EVENT)
        boundary.update(id='retention-boundary', changed_at='2026-07-20T00:00:00Z')
        expired = deepcopy(PUBLISHED_EVENT)
        expired.update(id='expired-event', changed_at='2026-07-19T23:59:59Z')
        self.publish(feed([PUBLISHED_EVENT, boundary, expired]))
        metadata = self.capture()
        (self.root / 'feeds/changes.xml').write_text('<stale-original-parent/>', encoding='utf8')
        c.write_json(self.root / 'feeds/changes.json', feed([]))
        repair.restore_published_predecessor(self.root, self.state, self.checkpoint, metadata)
        write_change_feed(self.catalog, self.catalog, self.root / 'feeds', as_of=AS_OF)
        history = c.read_json(self.root / 'feeds/changes.json')
        self.assertEqual(history['retention_days'], 90)
        self.assertEqual({event['id'] for event in history['events']}, {PUBLISHED_EVENT['id'], boundary['id']})
        atom = ElementTree.parse(self.root / 'feeds/changes.xml')
        ids = [entry.text.rsplit(':', 1)[-1] for entry in atom.findall('{http://www.w3.org/2005/Atom}entry/{http://www.w3.org/2005/Atom}id')]
        self.assertEqual(ids, [event['id'] for event in history['events']])
        self.assertNotIn('stale-original-parent', (self.root / 'feeds/changes.xml').read_text(encoding='utf8'))


if __name__ == '__main__':
    unittest.main()
