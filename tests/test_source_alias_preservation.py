"""Accepted public identities survive source replacement and later refreshes."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.build_changes import diff_catalogs
from scripts.sources import __main__ as cli
from scripts.sources.merge import integrate, merge_records, reconcile_source_aliases


NUMBER = 'NNH25ZDA001N-SSF'
URL = 'https://solicitation.nasaprs.com/' + NUMBER
NATIVE_ID = 'nasa-roses:25-B.8-c9ad18a888'


def record(ident='364039', **changes):
    return dict(opportunity_id=ident, opportunity_number=NUMBER,
                title='ROSES 2025: B.8 Heliophysics Spaceflight Science Foundations',
                source='Grants.gov', agency='NASA Headquarters', status='posted',
                source_type='Federal', close_date='2027-02-05',
                detail_page='https://www.grants.gov/search-results-detail/' + ident,
                funding_opportunity_url=URL, description='Current scientific text',
                **changes)


def native(**changes):
    result = record(NATIVE_ID)
    result.update(source='NASA ROSES', detail_page=URL,
                  title='ROSES25: B.8 Heliophysics Spaceflight Science Foundations',
                  description='Previous source science must not replace current text',
                  last_updated='2026-10-08', source_last_seen_date='2026-10-08')
    result.update(changes)
    return result


def alias(record):
    return {k: record.get(k) for k in ('opportunity_id', 'opportunity_number',
                                      'source', 'detail_page', 'funding_opportunity_url')}


def catalog(records):
    return {'generated_at': '2026-10-12T16:08:24Z', 'opportunities': records}


class SourceAliasPreservationTests(unittest.TestCase):
    def test_native_promotion_changes_only_aliases_and_preserves_inputs(self):
        current, previous = [record()], [native()]
        originals = deepcopy((current, previous))
        output, stats = reconcile_source_aliases(current, previous)
        self.assertEqual(output, [{**current[0], 'source_aliases': [alias(previous[0])]}])
        self.assertEqual((current, previous), originals)
        self.assertEqual(stats, {'changed_record_ids': ['364039'], 'added_alias_ids': [NATIVE_ID]})

    def test_second_rebuilt_catalog_retains_alias_without_any_native_snapshot(self):
        first, _ = reconcile_source_aliases([record()], [native()])
        second, _ = reconcile_source_aliases([record()], first)
        self.assertEqual(second, first)
        third, stats = reconcile_source_aliases(second, first)
        self.assertEqual(third, second)
        self.assertEqual(stats['added_alias_ids'], [])

    def test_promotion_prevents_false_new_and_closed_events(self):
        current, _ = reconcile_source_aliases([record()], [native()])
        events = diff_catalogs(catalog([native()]), catalog(current), as_of=date(2026, 10, 12))
        self.assertFalse(any(e['type'] in {'new', 'closed_or_removed'} for e in events))

    def test_exact_grants_receipt_alias_survives_without_source_row(self):
        old = record('363829')
        url = 'https://simpler.grants.gov/opportunity/c342c01d-4f34-440f-8bb2-4bdd4d763df0'
        proof = {'version': 1, 'source_url': url,
                 'target_url': 'https://www.grants.gov/search-results-detail/363829',
                 'utf8_sha256': 'a' * 64, 'retrieved_at': '2026-09-17T21:47:43Z',
                 'locator': 'View on Grants.gov / version-history anchor'}
        previous_alias = dict(opportunity_id='vpr-email:old', opportunity_number=None,
                              source='VPR funding digest', detail_page=url,
                              funding_opportunity_url=url, official_identity=proof)
        old['source_aliases'] = [previous_alias]
        current, _ = reconcile_source_aliases([record('363829')], [old])
        self.assertEqual(current[0]['source_aliases'], [previous_alias])

    def test_exact_grants_alias_can_retain_unowned_different_display_number(self):
        old = record()
        old['source_aliases'] = [dict(opportunity_id='vpr-email:old', opportunity_number='WRONG-DIGEST-NUMBER',
                                     source='VPR funding digest', detail_page=old['detail_page'])]
        output, _ = reconcile_source_aliases([record()], [old])
        self.assertEqual(output[0]['source_aliases'], old['source_aliases'])

    def test_historical_nsf_program_receipt_remains_identity_only(self):
        current = record('350230'); current.update(agency='National Science Foundation', opportunity_number='PD-24-1340')
        url = 'https://www.nsf.gov/funding/opportunities/rfe-research-formation-engineers'
        receipt = {'version': 1, 'kind': 'nsf_program_guidelines', 'source_url': url,
                   'final_url': url, 'target_url': url, 'number': 'pd241340',
                   'checked_on': '2026-10-12', 'retrieved_at': '2026-10-12T16:10:09Z',
                   'utf8_sha256': 'b' * 64, 'locator': 'Program guidelines / Apply to PD number'}
        item = {'opportunity_id': 'vpr-email:nsf-program', 'opportunity_number': None,
                'source': 'VPR funding digest', 'detail_page': url,
                'funding_opportunity_url': url, 'official_identity': receipt}
        previous = {**current, 'source_aliases': [item]}
        output, _ = reconcile_source_aliases([current], [previous])
        self.assertEqual(output, [previous])
        self.assertEqual(output[0]['source_aliases'][0]['official_identity']['checked_on'], '2026-10-12')
        bad = deepcopy(previous); bad['source_aliases'][0]['official_identity']['number'] = 'pd249999'
        with self.assertRaisesRegex(ValueError, 'consistent identity proof'):
            reconcile_source_aliases([current], [bad])

    def test_title_or_shared_url_without_full_number_never_proves_identity(self):
        for changes in ({'opportunity_number': None}, {'opportunity_number': 'NNH25ZDA001N'},
                        {'opportunity_number': 'NNH26ZDA001N-SSF'}, {'agency': 'National Science Foundation'},
                        {'agency_authority': 'source_default'}):
            with self.subTest(changes=changes):
                result, stats = reconcile_source_aliases([record()], [native(**changes)])
                self.assertEqual(result, [record()])
                self.assertEqual(stats['added_alias_ids'], [])

    def test_child_scope_does_not_alias_parent_even_with_shared_number(self):
        for scope in ({'parent_id': 'parent'}, {'subtopic_id': 'child'}, {'record_type': 'subtopic'}):
            with self.subTest(scope=scope):
                result, _ = reconcile_source_aliases([record()], [native(**scope)])
                self.assertNotIn('source_aliases', result[0])

    def test_ambiguous_full_number_scope_fails_closed(self):
        other = native(); other['opportunity_id'] = 'nasa-roses:other-scope'
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            reconcile_source_aliases([record()], [native(), other])
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            reconcile_source_aliases([record(), record('364040')], [native()])

    def test_conflicting_official_link_cannot_override_number_match(self):
        old = native(detail_page='https://www.grants.gov/search-results-detail/999999')
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            reconcile_source_aliases([record()], [old])

    def test_existing_prior_alias_cannot_point_to_another_canonical_record(self):
        previous = record(); previous['source_aliases'] = [alias(native())]
        previous['source_aliases'][0]['detail_page'] = 'https://www.grants.gov/search-results-detail/999999'
        with self.assertRaisesRegex(ValueError, 'consistent identity proof'):
            reconcile_source_aliases([record()], [previous])

    def test_live_id_or_another_winners_alias_cannot_be_stolen(self):
        previous = record(); previous['source_aliases'] = [alias(native())]
        with self.assertRaisesRegex(ValueError, 'consistent identity proof'):
            reconcile_source_aliases([record(), native()], [previous])
        another = record('999999'); another['opportunity_number'] = 'OTHER'
        another['source_aliases'] = [alias(native())]
        with self.assertRaisesRegex(ValueError, 'consistent identity proof'):
            reconcile_source_aliases([record(), another], [previous])

    def test_reused_canonical_id_with_changed_number_does_not_inherit_old_aliases(self):
        previous = record(); previous['source_aliases'] = [alias(native())]
        current = record(); current['opportunity_number'] = 'NNH26ZDA001N-SSF'
        output, _ = reconcile_source_aliases([current], [previous])
        self.assertEqual(output, [current])

    def test_alias_overflow_fails_instead_of_silently_losing_public_ids(self):
        previous = record(); previous['source_aliases'] = []
        for i in range(41):
            item = alias(native()); item['opportunity_id'] = f'nasa-roses:{i}'
            previous['source_aliases'].append(item)
        with self.assertRaisesRegex(ValueError, 'bound'):
            reconcile_source_aliases([record()], [previous])

    def test_integration_uses_previous_catalog_after_source_snapshot_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); current = root/'current.js'; previous = root/'previous.js'
            cache = root/'sources.json'
            current.write_text('globalThis.GRANT_CATALOG=' + json.dumps(catalog([record()])) + ';', encoding='utf8')
            previous.write_text('globalThis.GRANT_CATALOG=' + json.dumps(catalog([native()])) + ';', encoding='utf8')
            cache.write_text(json.dumps({'schema_version': 1, 'sources': {}}), encoding='utf8')
            with patch('scripts.sources.merge.collect', return_value=([], [])) as collect, \
                 patch('scripts.sources.merge._resolve_identity_before_selection', return_value={}), \
                 patch('scripts.sources.merge.validate_catalog'), \
                 patch('scripts.sources.merge.augment_records', return_value=0):
                summary = integrate(current, cache, adapters=[], previous_catalog_path=previous,
                                    as_of=date(2026, 10, 12), write=False)
            self.assertEqual(summary['source_alias_preservation']['added_alias_ids'], [NATIVE_ID])
            self.assertFalse(summary['written'])
            self.assertEqual(collect.call_args.kwargs['context']['source_snapshots'], {})
            self.assertNotIn('source_aliases', current.read_text(encoding='utf8'))

    def test_cli_passes_explicit_prior_catalog(self):
        result = {'validation': {'ok': True}, 'sources': [], 'written': False}
        with patch.object(cli, 'integrate', return_value=result) as merge, redirect_stdout(io.StringIO()):
            cli.main(['merge', '--previous-catalog', 'accepted.js'])
        self.assertEqual(merge.call_args.kwargs['previous_catalog_path'], Path('accepted.js'))


class SamSourceAliasPreservationTests(unittest.TestCase):
    def setUp(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/sam_imr_identity_continuity.json').read_text(encoding='utf8'))
        self.previous, self.current = fixture['previous'], fixture['current']

    @staticmethod
    def sam_alias(record):
        return {key: record.get(key) for key in ('opportunity_id', 'opportunity_number', 'source', 'agency',
            'agency_authority', 'sam_organization_id', 'detail_page', 'funding_opportunity_url')}

    def test_real_imr_successor_retains_only_prior_public_identity(self):
        inputs = deepcopy((self.current, self.previous))
        result, stats = reconcile_source_aliases([self.current], [self.previous])
        self.assertEqual(result, [{**self.current, 'source_aliases': [self.sam_alias(self.previous)]}])
        self.assertEqual((self.current, self.previous), inputs)
        self.assertEqual(stats['added_alias_ids'], ['sam-gov:d554d75951a340fcbed17668b1864648'])
        self.assertEqual(result[0]['deadlines'], self.current['deadlines'])
        self.assertFalse(set(result[0]['source_aliases'][0]) & {'description', 'deadlines', 'source_review_after'})

    def test_stable_rebuild_and_next_version_retain_the_identity_chain(self):
        first, _ = reconcile_source_aliases([self.current], [self.previous])
        stable, _ = reconcile_source_aliases([self.current], first)
        self.assertEqual(stable, first)
        later = deepcopy(self.current)
        later['opportunity_id'] = 'sam-gov:' + 'f' * 32
        later['detail_page'] = later['funding_opportunity_url'] = 'https://sam.gov/opp/' + 'f' * 32 + '/view'
        result, _ = reconcile_source_aliases([later], stable)
        self.assertEqual([item['opportunity_id'] for item in result[0]['source_aliases']],
                         [self.current['opportunity_id'], self.previous['opportunity_id']])
        self.assertEqual({key: value for key, value in result[0].items() if key != 'source_aliases'}, later)

    def test_exact_sponsor_full_number_and_organization_are_required(self):
        for changes in ({'sam_organization_id': '500035491'}, {'sam_organization_id': None},
                        {'agency': 'Intelligence Advanced Research Projects Activity'},
                        {'agency_authority': 'source_default'}, {'opportunity_number': 'DARPA-PS-26'},
                        {'opportunity_number': 'DARPA-PS-27-138'}, {'source': 'VPR funding digest'}):
            with self.subTest(changes=changes):
                previous = self.previous | changes
                output, stats = reconcile_source_aliases([self.current], [previous])
                self.assertEqual(output, [self.current]); self.assertEqual(stats['added_alias_ids'], [])
        output, _ = reconcile_source_aliases([self.current], [self.previous | {'title': 'An administrative retitle'}])
        self.assertEqual(output[0]['source_aliases'], [self.sam_alias(self.previous)])

    def test_child_scope_never_becomes_a_sam_parent_alias(self):
        for scope in ({'parent_id': 'parent'}, {'parent_opportunity_id': 'parent'},
                      {'subtopic_id': 'child'}, {'record_type': 'subtopic'}):
            with self.subTest(scope=scope):
                output, _ = reconcile_source_aliases([self.current], [self.previous | scope])
                self.assertEqual(output, [self.current])
                output, _ = reconcile_source_aliases([self.current | scope], [self.previous])
                self.assertEqual(output, [self.current | scope])

    def test_ambiguous_previous_or_current_sam_scope_fails_closed(self):
        another = deepcopy(self.previous); another['opportunity_id'] = 'sam-gov:' + 'f' * 32
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            reconcile_source_aliases([self.current], [self.previous, another])
        another = deepcopy(self.current); another['opportunity_id'] = 'sam-gov:' + 'f' * 32
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            reconcile_source_aliases([self.current, another], [self.previous])

    def test_historical_sam_alias_cannot_change_organization_number_sponsor_or_official_id_url(self):
        previous, _ = reconcile_source_aliases([self.current], [self.previous])
        for changes in ({'sam_organization_id': '123'}, {'opportunity_number': 'OTHER'},
                        {'agency': 'National Science Foundation'}, {'agency_authority': 'source_default'},
                        {'detail_page': 'https://sam.gov/opp/' + 'f' * 32 + '/view'},
                        {'description': 'Old scientific text is not alias metadata'}):
            with self.subTest(changes=changes):
                altered = deepcopy(previous); altered[0]['source_aliases'][0].update(changes)
                with self.assertRaisesRegex(ValueError, 'consistent identity proof'):
                    reconcile_source_aliases([self.current], altered)

    def test_live_or_another_owner_alias_cannot_be_stolen(self):
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            reconcile_source_aliases([self.current, self.previous], [self.previous])
        other = deepcopy(self.current); other.update(opportunity_id='sam-gov:' + 'f' * 32, opportunity_number='OTHER')
        other['source_aliases'] = [self.sam_alias(self.previous)]
        with self.assertRaisesRegex(ValueError, 'consistent identity proof'):
            reconcile_source_aliases([self.current, other], [self.previous])

    def test_sam_alias_bound_never_silently_discards_public_ids(self):
        previous = deepcopy(self.current); previous['source_aliases'] = []
        for number in range(41):
            item = self.sam_alias(self.previous)
            notice = f'{number:032x}'; item['opportunity_id'] = 'sam-gov:' + notice
            item['detail_page'] = item['funding_opportunity_url'] = 'https://sam.gov/opp/' + notice + '/view'
            previous['source_aliases'].append(item)
        with self.assertRaisesRegex(ValueError, 'bound'):
            reconcile_source_aliases([self.current], [previous])
        previous['source_aliases'].pop()
        output, _ = reconcile_source_aliases([self.current], [previous])
        self.assertEqual(len(output[0]['source_aliases']), 40)

    def test_real_successor_is_an_amendment_instead_of_a_new_or_removed_call(self):
        current, _ = reconcile_source_aliases([self.current], [self.previous])
        events = diff_catalogs(catalog([self.previous]), catalog(current), as_of=date(2026, 10, 18))
        self.assertTrue(any(event['type'] == 'amended' for event in events))
        self.assertFalse(any(event['type'] in {'new', 'closed_or_removed'} for event in events))
        self.assertEqual({event['opportunity_id'] for event in events}, {self.current['opportunity_id']})

    def test_existing_identity_proven_digest_alias_survives_sam_continuation(self):
        digest = deepcopy(self.current)
        digest.update(opportunity_id='vpr-email:imr', source='VPR funding digest')
        combined, _ = merge_records([], [self.current, digest])
        self.assertEqual(len(combined), 1)
        vpr_alias = combined[0]['source_aliases'][0]
        current, _ = reconcile_source_aliases(combined, [self.previous])
        self.assertIn(vpr_alias, current[0]['source_aliases'])
        self.assertIn(self.sam_alias(self.previous), current[0]['source_aliases'])
        rebuilt, _ = reconcile_source_aliases([self.current], current)
        self.assertEqual(rebuilt[0]['source_aliases'], current[0]['source_aliases'])
        self.assertEqual({key: value for key, value in rebuilt[0].items() if key != 'source_aliases'}, self.current)


if __name__ == '__main__':
    unittest.main()
