"""Unpublished generated projections must not masquerade as input edits."""
import unittest

from tools.release_dependencies import unpublished_input_changes


class UnpublishedInputs(unittest.TestCase):
    def setUp(self):
        self.names = ['README.md', 'PROJECT.md', 'match_explorer.html', 'team_match.html']
        self.manifest = {
            'runtime_baseline': {name: 'protected' for name in self.names[2:]},
            'documentation_baseline': {name: 'protected' for name in self.names[:2]},
            'files': {name: 'generated' for name in self.names},
            'dependency_groups': {'runtime': {'files': {name: 'generated' for name in self.names}}}}
        self.current = {'runtime': {'files': {name: 'protected' for name in self.names}}}
        self.changes = {'runtime': self.names, 'validation': ['tests/new_contract.py']}

    def test_generated_stats_and_asset_versions_recover_before_publication(self):
        self.assertEqual(unpublished_input_changes(self.manifest, self.changes, self.current),
                         {'validation': ['tests/new_contract.py']})
        self.assertEqual(self.changes['runtime'], self.names)

    def test_authored_edits_and_missing_proof_still_hold(self):
        for name in self.names:
            with self.subTest(name=name):
                self.current['runtime']['files'][name] = 'authored-edit'
                result = unpublished_input_changes(self.manifest, self.changes, self.current)
                self.assertEqual(result['runtime'], [name])
                self.current['runtime']['files'][name] = 'protected'
        self.manifest['dependency_groups']['runtime']['files'][self.names[0]] = 'different'
        self.assertEqual(unpublished_input_changes(self.manifest, self.changes, self.current)['runtime'],
                         [self.names[0]])

    def test_source_semantic_and_team_changes_never_disappear(self):
        changes = self.changes | {key: ['changed-input'] for key in ('source', 'semantic', 'teams')}
        result = unpublished_input_changes(self.manifest, changes, self.current)
        self.assertEqual(set(result), {'validation', 'source', 'semantic', 'teams'})

    def test_legacy_manifest_without_projection_proof_keeps_changes(self):
        self.assertEqual(unpublished_input_changes({}, self.changes, self.current), self.changes)


if __name__ == '__main__':
    unittest.main()
