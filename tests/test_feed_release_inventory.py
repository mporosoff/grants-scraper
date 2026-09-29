"""Complete static feed packages and their obsolete-file publication boundary."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.build_feeds import build_feeds, FEEDS_BASE
from tests import test_release_candidate as fixtures
from tools import release_candidate as c, publish_release_candidate as publisher, verify_release_live as live
from tools.validate_release_candidate import validate


class FeedReleaseInventoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CandidateLifecycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.bundle, self.reports = self.fixture.root, self.fixture.bundle, self.fixture.reports
        self.fixture.policy['generated'] += ['feeds/*', *c.FACET_FEED_PATTERNS]
        c.write_json(self.root / c.POLICY, self.fixture.policy)
        self.changes = b'<feed>Preserved change history</feed>\n'
        (self.root / 'feeds').mkdir()
        (self.root / 'feeds/changes.xml').write_bytes(self.changes)
        (self.root / 'feeds/changes.json').write_bytes(b'{"changes": []}\n')
        self.catalog = {'generated_at': '2026-09-28T10:17:00Z', 'opportunities': [{
            'opportunity_id': '1', 'title': 'Research opportunity', 'status': 'posted',
            'close_date': '2027-01-01', 'source_type': 'Federal', 'topic_areas': ['Retired topic']}]}
        build_feeds(self.catalog, self.root / 'feeds')
        self.fixture.commit()
        self.fixture.source_sha = c.git(self.root, 'rev-parse', 'HEAD')
        self.catalog['opportunities'][0]['topic_areas'] = ['Energy']
        build_feeds(self.catalog, self.root / 'feeds')

    def create(self):
        return self.fixture.create()

    def rewrite_manifest(self, manifest):
        manifest['candidate_id'] = c.digest(c.encoded({k: v for k, v in manifest.items() if k != 'candidate_id'}))
        c.write_json(self.bundle / c.MANIFEST, manifest)

    def test_policy_and_candidate_include_every_indexed_facet_feed(self):
        policy = c.read_json(c.ROOT / c.POLICY)
        self.assertTrue(set(c.FACET_FEED_PATTERNS) <= set(policy['generated']))
        manifest = self.create()
        expected = ['feeds/source-type/federal.xml', 'feeds/topic/energy.xml']
        self.assertEqual(manifest['feed_inventory'], {'version': 1, 'paths': expected})
        for name in expected:
            self.assertIn(name, manifest['files'])
            self.assertIn(name, manifest['generation_files'])
            self.assertEqual((self.bundle / 'files' / name).read_bytes(), (self.root / name).read_bytes())
        self.assertNotIn('feeds/topic/retired-topic.xml', manifest['files'])
        self.assertEqual(c.load(self.bundle), manifest)

    def test_constructor_rejects_missing_selected_extra_or_foreign_index_feeds(self):
        for change in ('old_policy', 'missing', 'extra', 'foreign'):
            with self.subTest(change=change):
                build_feeds(self.catalog, self.root / 'feeds')
                policy = deepcopy(self.fixture.policy)
                if change == 'old_policy':
                    policy['generated'] = [p for p in policy['generated'] if p not in c.FACET_FEED_PATTERNS]
                elif change == 'missing':
                    (self.root / 'feeds/topic/energy.xml').unlink()
                elif change == 'extra':
                    (self.root / 'feeds/topic/obsolete.xml').write_text('<feed/>', encoding='utf-8')
                else:
                    index = c.read_json(self.root / 'feeds/index.json')
                    index['feeds'][0]['url'] = 'https://foreign.example/all.xml'
                    c.write_json(self.root / 'feeds/index.json', index)
                c.write_json(self.root / c.POLICY, policy)
                with self.assertRaisesRegex(ValueError, '[Ff]eed|[Ff]acet'):
                    c.create(self.root, self.bundle, run_id='123', attempt='1')
        c.write_json(self.root / c.POLICY, self.fixture.policy)

    def test_load_rejects_an_index_target_omitted_from_new_manifest(self):
        manifest = self.create()
        name = 'feeds/topic/energy.xml'
        manifest['files'].pop(name)
        manifest['generation_files'].pop(name)
        (self.bundle / 'files' / name).unlink()
        self.rewrite_manifest(manifest)
        with self.assertRaisesRegex(ValueError, 'Feed index target omitted'):
            c.load(self.bundle)

    def test_legacy_partial_artifact_remains_readable_but_cannot_bypass_complete_policy(self):
        manifest = self.create()
        for name in manifest.pop('feed_inventory')['paths']:
            manifest['files'].pop(name)
            manifest['generation_files'].pop(name)
            (self.bundle / 'files' / name).unlink()
        self.rewrite_manifest(manifest)
        self.assertEqual(c.load(self.bundle), manifest)
        with self.assertRaisesRegex(ValueError, 'Legacy candidate omits complete facet feeds'):
            c.verify_dependencies(self.root, manifest)
        # Historical authentication must not delete anything from the checkout.
        (self.root / 'feeds/topic/old.xml').write_text('old', encoding='utf-8')
        c.prune_obsolete_feeds(self.root, manifest)
        self.assertTrue((self.root / 'feeds/topic/old.xml').exists())

    def test_materialization_retires_only_obsolete_managed_xml_and_preserves_changes(self):
        manifest = self.create()
        c.git(self.root, 'restore', '--', 'feeds')
        note = self.root / 'feeds/topic/README.txt'
        note.write_text('Unrelated documentation', encoding='utf-8')
        c.materialize(self.root, self.bundle)
        self.assertFalse((self.root / 'feeds/topic/retired-topic.xml').exists())
        self.assertTrue((self.root / 'feeds/topic/energy.xml').exists())
        self.assertTrue(note.exists())
        self.assertEqual((self.root / 'feeds/changes.xml').read_bytes(), self.changes)
        c.verify_feed_inventory(self.root, manifest)
        self.assertIn('feeds/topic/retired-topic.xml', c.publication_paths(self.root, manifest))
        self.assertNotIn('feeds/topic/README.txt', c.publication_paths(self.root, manifest))

    def test_runtime_assembly_prunes_old_facets_before_copying_the_saved_inventory(self):
        from tools.assemble_release_candidate import assemble
        manifest = self.create()
        c.git(self.root, 'restore', '--', 'feeds')
        with patch('scripts.faculty_match.update_version_target'), \
                patch('scripts.import_opportunity_team_model.update_version_target'):
            assemble(self.root, self.bundle)
        self.assertFalse((self.root / 'feeds/topic/retired-topic.xml').exists())
        c.verify_feed_inventory(self.root, manifest)
        c.verify_files(self.root, manifest['generation_files'])

    def test_empty_facet_inventory_explicitly_retires_previous_facets(self):
        self.catalog['opportunities'] = []
        build_feeds(self.catalog, self.root / 'feeds')
        manifest = self.create()
        self.assertEqual(manifest['feed_inventory']['paths'], [])
        c.git(self.root, 'restore', '--', 'feeds')
        c.materialize(self.root, self.bundle)
        self.assertEqual(c.facet_feed_names(self.root), set())
        self.assertEqual((self.root / 'feeds/changes.xml').read_bytes(), self.changes)

    def test_committed_inventory_rejects_obsolete_files_even_when_every_present_hash_matches(self):
        manifest = self.create()
        # The historical publication command staged only present manifest files.
        c.git(self.root, 'add', '--', *manifest['files'])
        stale = c.git(self.root, 'commit-tree', c.git(self.root, 'write-tree'), '-p', self.fixture.source_sha, '-m', 'stale fixture')
        self.assertFalse(publisher.committed_candidate_matches(self.root, stale, manifest))
        c.git(self.root, 'add', '--', *c.publication_paths(self.root, manifest))
        complete = c.git(self.root, 'commit-tree', c.git(self.root, 'write-tree'), '-p', self.fixture.source_sha, '-m', 'complete fixture')
        self.assertTrue(publisher.committed_candidate_matches(self.root, complete, manifest))

    def test_publication_stages_facet_deletion_and_pages_copies_all_nested_feeds(self):
        manifest = self.create()
        receipt = validate(self.root, self.bundle, self.reports, execute=self.fixture.execute([]))
        def run(*args):
            if args[:2] == ('git', 'ls-remote'):
                return self.fixture.source_sha + '\trefs/heads/main'
            if args[:3] == ('gh', 'pr', 'list'):
                return '[]'
            if args[:3] == ('gh', 'pr', 'create'):
                return 'https://github.com/owner/repo/pull/1'
            if args[:2] in (('git', 'config'), ('git', 'add')):
                return c.git(self.root, *args[1:])
            return ''
        with patch.object(c, 'ROOT', self.root), patch.object(publisher, 'run', side_effect=run), \
                patch.object(publisher, 'request_verification'), patch('tools.wait_release_review.wait_for_review'), \
                patch.dict(os.environ, {'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}):
            ready = publisher.prepare(self.bundle, self.reports / 'validation.json', self.reports, '123')
        self.assertTrue(publisher.committed_candidate_matches(self.root, ready['head_sha'], manifest))
        tree = c.git(self.root, 'ls-tree', '-r', '--name-only', ready['head_sha'])
        self.assertNotIn('feeds/topic/retired-topic.xml', tree)
        publication = {'schema_version': 1, 'candidate_id': manifest['candidate_id'], 'candidate_hashes': manifest['files'],
            'generation_sha': manifest['generation_sha'], 'generation_run_id': manifest['generation_run_id'],
            'validation_sha': receipt['validation_sha'], 'publication_sha': ready['head_sha'], 'release_code_sha': self.fixture.source_sha,
            'validation_receipt_sha256': c.digest(c.encoded(receipt)), 'timestamp': '2026-09-28T10:17:00Z'}
        c.write_json(self.reports / 'publication.json', publication)
        output = Path(self.fixture.temp.name) / 'site'
        with patch.object(live, 'worker_provenance', return_value={'verified': True}):
            live.stage_site(self.bundle, self.reports, output)
        for name in manifest['feed_inventory']['paths']:
            self.assertEqual((output / name).read_bytes(), (self.bundle / 'files' / name).read_bytes())
        self.assertFalse((output / 'feeds/topic/retired-topic.xml').exists())

    def test_pruning_rejects_a_junction_at_the_feed_parent_before_deleting(self):
        manifest = self.create()
        old = self.root / 'feeds/topic/obsolete.xml'
        old.write_text('Do not delete through a junction', encoding='utf-8')
        with patch.object(Path, 'is_junction', return_value=True, create=True):
            with self.assertRaisesRegex(ValueError, 'junction'):
                c.prune_obsolete_feeds(self.root, manifest)
        self.assertTrue(old.exists())


if __name__ == '__main__':
    unittest.main()
