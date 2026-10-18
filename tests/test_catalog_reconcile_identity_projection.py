"""SAM-only recovery preserves accepted owners without importing new science."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import unittest

from scripts.build_changes import diff_catalogs
from scripts.sources.merge import merge_records, merge_sam_identity_projection, reconcile_source_aliases


class SamIdentityProjectionContracts(unittest.TestCase):
    def setUp(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/sam_imr_identity_continuity.json').read_text(encoding='utf8'))
        self.old, self.fresh = fixture['previous'], fixture['current']
        owner = deepcopy(self.old)
        owner.update(opportunity_id='900001', source='Grants.gov',
            detail_page='https://www.grants.gov/search-results-detail/900001',
            funding_opportunity_url='https://www.grants.gov/search-results-detail/900001')
        owner.pop('sam_organization_id', None)
        self.owner = merge_records([owner], [])[0][0]

    def published(self, owner=None):
        return merge_records([deepcopy(owner or self.owner)], [deepcopy(self.old)])[0]

    @staticmethod
    def aliases(row):
        return {item['opportunity_id'] for item in row.get('source_aliases') or []}

    @staticmethod
    def without_aliases(row):
        return {key: value for key, value in row.items() if key != 'source_aliases'}

    def test_actual_successor_promoted_to_grants_keeps_only_identity_delta(self):
        # Ordinary merge carries document/conflict evidence. A source-only
        # recovery must not modify those fields on its retained Grants owner.
        fresh = deepcopy(self.fresh)
        fresh.update(close_date='2027-01-01', description='New source wording')
        normal = merge_records([deepcopy(self.owner)], [deepcopy(fresh)])[0][0]
        changed = {key for key in normal.keys() | self.owner.keys()
                   if normal.get(key) != self.owner.get(key)}
        self.assertTrue({'source_aliases', 'official_document_candidates', 'duplicate_source_conflicts'} <= changed)
        before = deepcopy(([self.owner], [fresh], self.published()))
        output, stats = merge_sam_identity_projection(*before)
        self.assertEqual(len(output), 1)
        self.assertEqual(self.without_aliases(output[0]), self.without_aliases(self.owner))
        self.assertEqual(self.aliases(output[0]), {self.old['opportunity_id'], fresh['opportunity_id']})
        self.assertEqual(before, ([self.owner], [fresh], self.published()))
        self.assertIn(self.old['opportunity_id'], stats['source_alias_preservation']['added_alias_ids'])

    def test_second_refresh_and_cache_replay_keep_the_promoted_alias_chain(self):
        first, _ = merge_sam_identity_projection([self.owner], [self.fresh], self.published())
        second, _ = merge_sam_identity_projection([self.owner], [self.fresh], first)
        stable, _ = merge_sam_identity_projection(first, [self.fresh], second)
        self.assertEqual(second, first)
        self.assertEqual(stable, first)
        absent, _ = merge_sam_identity_projection([self.owner], [], first)
        self.assertEqual(absent, first)

    def test_direct_native_successor_stays_current_and_aliases_only_old_identity(self):
        output, _ = merge_sam_identity_projection([], [self.fresh], [self.old])
        expected, _ = reconcile_source_aliases(merge_records([], [self.fresh])[0], [self.old])
        self.assertEqual(output, expected)
        self.assertEqual(self.aliases(output[0]), {self.old['opportunity_id']})
        self.assertEqual(output[0]['deadlines'], self.fresh['deadlines'])
        self.assertNotIn('description', output[0]['source_aliases'][0])

    def test_unchanged_other_source_owner_keeps_accepted_sam_aliases(self):
        owner = deepcopy(self.owner)
        owner.update(opportunity_id='darpa-iarpa:imr', source='DARPA / IARPA',
                     detail_page='https://www.darpa.mil/research/programs/imr',
                     funding_opportunity_url='https://www.darpa.mil/research/programs/imr')
        published = self.published(owner)
        self.assertEqual(self.aliases(published[0]), {self.old['opportunity_id']})
        current, _ = merge_sam_identity_projection([owner], [self.fresh], published)
        self.assertEqual(self.without_aliases(current[0]), self.without_aliases(owner))
        self.assertEqual(self.aliases(current[0]), {self.old['opportunity_id'], self.fresh['opportunity_id']})
        replay, _ = merge_sam_identity_projection([owner], [], current)
        self.assertEqual(replay, current)

    def test_unrelated_parent_aliases_are_byte_exact_and_new_foreign_aliases_not_imported(self):
        parent = deepcopy(self.owner)
        kept = dict(opportunity_id='vpr-email:accepted', opportunity_number=parent['opportunity_number'],
                    source='VPR funding digest', detail_page='https://www.darpa.mil/accepted',
                    funding_opportunity_url=None)
        parent['source_aliases'] = [kept]
        published = self.published(parent)
        extra = dict(kept, opportunity_id='vpr-email:later')
        published[0]['source_aliases'].append(extra)
        fresh = deepcopy(self.fresh)
        fresh['source_aliases'] = [dict(kept, opportunity_id='vpr-email:fresh')]
        output, _ = merge_sam_identity_projection([parent], [fresh], published)
        self.assertEqual(output[0]['source_aliases'][0], kept)
        self.assertEqual([row for row in output[0]['source_aliases'] if row['source'] != 'SAM.gov'], [kept])
        self.assertEqual(self.without_aliases(output[0]), self.without_aliases(parent))

    def test_unrelated_historical_alias_ambiguity_cannot_block_sam_only_recovery(self):
        nasa = deepcopy(self.owner)
        nasa.update(opportunity_id='900002', agency='NASA Headquarters', opportunity_number='NNH25ZDA001N-SSF')
        unrelated = [dict(nasa, opportunity_id='nasa-roses:first', source='NASA ROSES'),
                     dict(nasa, opportunity_id='nasa-roses:second', source='NASA ROSES')]
        # The ordinary all-source promotion correctly requires unique scope.
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            reconcile_source_aliases([nasa], unrelated)
        output, _ = merge_sam_identity_projection([self.owner, nasa], [self.fresh], self.published() + unrelated)
        self.assertEqual(next(row for row in output if row['opportunity_id'] == nasa['opportunity_id']), nasa)
        imr = next(row for row in output if row['opportunity_id'] == self.owner['opportunity_id'])
        self.assertEqual(self.aliases(imr), {self.old['opportunity_id'], self.fresh['opportunity_id']})

    def test_changed_owner_sponsor_number_source_or_child_scope_cannot_inherit_old_alias(self):
        for changes in ({'agency': 'National Science Foundation'}, {'opportunity_number': 'DARPA-PS-26'},
                        {'opportunity_number': 'DARPA-PS-27-138'}, {'parent_id': 'another-call'}):
            with self.subTest(changes=changes):
                owner = self.owner | changes
                output, _ = merge_sam_identity_projection([owner], [], self.published())
                self.assertEqual(output, [owner])
        other = self.owner | {'source': 'DARPA / IARPA'}
        output, _ = merge_sam_identity_projection([other], [], self.published())
        self.assertEqual(output, [other])

    def test_native_alias_proof_is_checked_before_promoting_sam_into_grants(self):
        continued, _ = reconcile_source_aliases([self.fresh], [self.old])
        for changes in ({'sam_organization_id': '123'}, {'agency': 'National Science Foundation'},
                        {'opportunity_number': 'OTHER'}, {'description': 'Not public identity metadata'}):
            with self.subTest(changes=changes):
                fresh = deepcopy(continued[0]); fresh['source_aliases'][0].update(changes)
                with self.assertRaisesRegex(ValueError, 'consistent identity proof'):
                    merge_sam_identity_projection([self.owner], [fresh], [])
        fresh = deepcopy(continued[0]); fresh.pop('sam_organization_id')
        with self.assertRaisesRegex(ValueError, 'organization proof'):
            merge_sam_identity_projection([self.owner], [fresh], [])

    def test_alias_cannot_steal_a_live_owner_or_overflow_the_public_bound(self):
        competing = deepcopy(self.owner)
        competing.update(opportunity_id=self.old['opportunity_id'], source='SAM.gov',
                         opportunity_number='OTHER')
        with self.assertRaisesRegex(ValueError, 'exact parent owners'):
            merge_sam_identity_projection([self.owner, competing], [self.fresh], self.published())
        other = deepcopy(self.owner); other.update(opportunity_id='900002', opportunity_number='OTHER')
        other['source_aliases'] = self.published()[0]['source_aliases']
        with self.assertRaisesRegex(ValueError, 'consistent identity proof'):
            merge_sam_identity_projection([self.owner, other], [self.fresh], self.published())
        parent = deepcopy(self.owner)
        parent['source_aliases'] = [dict(opportunity_id=f'vpr-email:{index}', opportunity_number=parent['opportunity_number'],
            source='VPR funding digest', detail_page='https://www.darpa.mil/accepted',
            funding_opportunity_url=None) for index in range(40)]
        with self.assertRaisesRegex(ValueError, 'bound'):
            merge_sam_identity_projection([parent], [self.fresh], [])

    def test_invalid_active_inventory_fails_instead_of_projecting_unrelated_sources(self):
        for parents, active in (([self.owner, self.owner], [self.fresh]),
                                ([self.owner], [self.fresh, self.fresh]),
                                ([self.owner], [self.owner]), ([self.fresh], [])):
            with self.subTest(parents=parents, active=active), self.assertRaises(ValueError):
                merge_sam_identity_projection(parents, active, [])

    def test_promoted_successor_changefeed_has_no_false_new_or_removed_record(self):
        previous = self.published()
        current, _ = merge_sam_identity_projection([self.owner], [self.fresh], previous)
        events = diff_catalogs({'opportunities': previous}, {'opportunities': current}, as_of=date(2026, 10, 18))
        self.assertFalse(any(event['type'] in {'new', 'closed_or_removed'} for event in events))
        self.assertTrue(all(event['opportunity_id'] == self.owner['opportunity_id'] for event in events))


if __name__ == '__main__':
    unittest.main()
