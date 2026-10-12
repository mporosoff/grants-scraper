"""NSF identity is owned by official edition links, never digest title/defaults."""
import copy
from datetime import date, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.build_catalog import record_identity
from scripts.sources import nsf_identity as nsf, official_identity
from scripts.sources.merge import integrate, load_catalog, merge_records, rebuild_catalog, save_catalog
from scripts.sources.validate import record_is_publishable
from scripts.solicitation_identity import sponsor_identity
from tests.test_vpr_window_retention import cache, observed, row

DAY = date(2026, 10, 8)
PROGRAM = 'https://www.nsf.gov/funding/opportunities/example-program'
EDITION = PROGRAM + '/nsf26-510/solicitation'


def digest(number='NSF26-510', url=PROGRAM, **fields):
    return row(number or 'numberless', close_date='2026-11-04', opportunity_number=number,
        title='Digest title need not match', detail_page=url, funding_opportunity_url=url,
        **fields)


def canonical(number='26-510', ident='123456', source='Grants.gov'):
    return dict(digest(number, EDITION), opportunity_id=ident, source=source,
        agency='U.S. National Science Foundation', agency_authority='source_listed',
        title='Official research title', description='Unchanged official scientific scope')


def html(number='26-510'):
    return '<h1>Program</h1><h2>View guidelines</h2><a href="' + PROGRAM + '/nsf' + number + '/solicitation">NSF ' + number + '</a><h2>Synopsis</h2>'


def receipt(text=None, url=PROGRAM, final=PROGRAM, day=DAY):
    return nsf.receipt_for(text or html(), url, final, checked_on=day.isoformat(),
                           retrieved_at=day.isoformat() + 'T12:00:00Z')


class Client:
    def __init__(self, text=None, final=None):
        self.text = text or html(); self.final = final; self.calls = []

    def get_text(self, url):
        self.calls.append(url); self.last_url = self.final or url
        return self.text


class NSFIdentityTests(unittest.TestCase):
    def test_three_confirmed_number_forms_merge_to_canonical_without_scope_changes(self):
        for number in ('26-510', '26-512', '26-514'):
            with self.subTest(number=number):
                record = digest('NSF' + number)
                official_identity.resolve([record], {}, client=Client(html(number)), as_of=DAY)
                official = canonical(number)
                self.assertIsNone(sponsor_identity(record))
                self.assertEqual(record_identity(record), record_identity(official))
                merged, _ = merge_records([official], [record])
                self.assertEqual(len(merged), 1)
                self.assertEqual(merged[0]['description'], official['description'])
                self.assertEqual(merged[0]['title'], official['title'])
                self.assertEqual(merged[0]['source_aliases'][0]['opportunity_id'], record['opportunity_id'])
                self.assertEqual(merge_records(merged, [record])[0], merged)

    def test_direct_edition_and_publication_links_need_no_request_or_global_sponsor_promotion(self):
        for url in (EDITION, EDITION.removesuffix('/solicitation'),
                    'https://www.nsf.gov/publications/pub_summ.jsp?ods_key=nsf26510'):
            record = digest(url=url)
            with patch('scripts.sources.http.PoliteClient', side_effect=AssertionError('No request')):
                self.assertEqual(official_identity.resolve([record], {}, as_of=DAY)['attempted'], 0)
            self.assertEqual(record_identity(record), 'solicitation:nsf:26510')
            self.assertIsNone(sponsor_identity(record))
        for url in ('https://nsf.gov/', 'https://example.gov/nsf26-510'):
            self.assertTrue(record_identity(digest(url=url)).startswith('id:'))
        self.assertTrue(record_identity(digest(url='https://example.gov', agency='NSF')).startswith('id:'))

    def test_edition_links_are_strict_and_do_not_accept_lookalikes_or_credentials(self):
        for url in (EDITION.replace('www.nsf.gov', 'www.nsf.gov.evil.test'),
                    EDITION.replace('https://', 'http://'), EDITION + '?x=1', EDITION + '#x',
                    EDITION.replace('www.nsf.gov', 'user@www.nsf.gov'),
                    EDITION.replace('www.nsf.gov', 'www.nsf.gov:444'),
                    'https://www.nsf.gov/publications/pub_summ.jsp?ods_key=nsf26510&ods_key=nsf26512'):
            self.assertIsNone(nsf.edition_key(url))

    def test_only_owned_guidelines_not_scientific_cross_references_identify_a_program(self):
        outside = '<h1>Program</h1><h2>Synopsis</h2><a href="' + EDITION + '">NSF 26-510</a>'
        self.assertIsNone(receipt(outside))
        wrong_program = html().replace('/example-program/nsf', '/another-program/nsf')
        self.assertIsNone(receipt(wrong_program))
        wrong_label = html().replace('>NSF 26-510<', '>NSF 25-544<')
        self.assertIsNone(receipt(wrong_label))
        self.assertIsNone(receipt('<script>' + html() + '</script>'))
        multiple = html().removesuffix('<h2>Synopsis</h2>') + html('26-512')
        self.assertIsNone(receipt(multiple))

    def test_numberless_rfe_guidelines_do_not_collapse_other_formation_programs(self):
        text = '<h1>RFE</h1><h2>Synopsis</h2>Apply to PD 26-1341 as follows:' \
            '<h2>Program guidelines</h2><p>Apply to <b>PD 24-1340</b> as follows:</p><h2>Share</h2>'
        record = digest(None)
        official_identity.resolve([record], {}, client=Client(text), as_of=DAY)
        self.assertEqual(record_identity(record), 'solicitation:nsf:pd241340')
        self.assertIsNone(record['opportunity_number'])
        merged, _ = merge_records([canonical('PD-24-1340', '350230'),
                                    canonical('PD-26-1341', '361952')], [record])
        self.assertEqual({r['opportunity_id'] for r in merged}, {'350230', '361952'})

    def test_mismatched_old_edition_is_withheld_never_rewritten_or_aliased(self):
        record = digest('NSF25-544')
        official_identity.resolve([record], {}, client=Client(html('26-509')), as_of=DAY)
        self.assertEqual(record['opportunity_number'], 'NSF25-544')
        self.assertEqual(record_is_publishable(record, DAY), (False, 'nsf_identity_conflict'))
        with self.assertRaisesRegex(ValueError, 'NSF official guidelines conflict'):
            merge_records([canonical('26-509')], [record])
        for fields in ({'agency': 'DOE', 'agency_authority': 'source_listed'},
                       {'funding_opportunity_url': EDITION.replace('26-510', '26-512')}):
            other = digest(url=EDITION); other.update(fields)
            self.assertEqual(record_is_publishable(other, DAY), (False, 'nsf_identity_conflict'))

    def test_mutable_program_receipt_expires_and_cannot_be_reused_next_day(self):
        record = digest(); state = {PROGRAM: receipt()}
        client = Client()
        official_identity.resolve([record], state, client=client, as_of=DAY)
        self.assertEqual(client.calls, [])
        self.assertEqual(record_is_publishable(record, DAY + timedelta(days=1)), (False, 'nsf_identity_unresolved'))
        official_identity.resolve([record], state, client=client, limit=0, as_of=DAY + timedelta(days=1))
        self.assertNotIn('official_identity', record)
        official_identity.resolve([record], state, client=client, as_of=DAY + timedelta(days=1))
        self.assertEqual(client.calls, [PROGRAM])
        self.assertTrue(record_is_publishable(record, DAY + timedelta(days=1))[0])

    def test_bad_receipt_redirect_or_conflicting_owned_guidelines_do_not_resolve(self):
        for field, value in (('locator', 'any mention'), ('number', '26512'),
                             ('target_url', EDITION.replace('example-program', 'other-program')),
                             ('checked_on', 'yesterday'), ('utf8_sha256', 'bad'),
                             ('final_url', 'https://evil.test/program')):
            item = receipt(); item[field] = value
            self.assertFalse(nsf.valid_receipt(item, PROGRAM, DAY))
        with self.assertRaisesRegex(ValueError, 'redirected outside'):
            official_identity.resolve([digest()], {}, client=Client(final='https://example.org/'), as_of=DAY)

    def test_source_order_and_selective_refresh_cannot_let_digest_displace_official_record(self):
        record = digest(url=EDITION)
        official = canonical(ident='nsf-funding:edition', source='NSF Funding')
        for base, external in (([], [record, official]), ([], [official, record]),
                               ([record], [official]), ([official, record], [])):
            with self.subTest(base=bool(base)):
                merged, stats = merge_records(base, external)
                self.assertEqual([r['opportunity_id'] for r in merged], ['nsf-funding:edition'])
                self.assertEqual(merged[0]['description'], official['description'])
                self.assertEqual(stats['external_considered'], len(external))
        merged, stats = merge_records([record], [])
        self.assertEqual(stats['external_added'], 0)
        self.assertEqual(stats['base_count'], 1)

    def test_one_shared_lookup_budget_deduplicates_fresh_and_retained_urls(self):
        records = [digest(str(i), PROGRAM.replace('example-program', 'program-' + str(i))) for i in range(21)]
        client = Client()
        result = official_identity.resolve(records + copy.deepcopy(records), {}, client=client, as_of=DAY)
        self.assertEqual(len(client.calls), 20)
        self.assertEqual(result['attempted'], 20)


class NSFIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.catalog = self.root / 'catalog.js'; self.snapshot = self.root / 'cache.json'
        self.client = Client()

    def seed(self, records, state):
        save_catalog(rebuild_catalog({'generated_at': DAY.isoformat() + 'T12:00:00Z'}, records, [], []), self.catalog)
        self.snapshot.write_text(json.dumps(state), encoding='utf8')

    def run_window(self, result, enabled=True, day=DAY, adapters=None):
        with patch.dict(os.environ, {'VPR_ENRICH_LINKS': 'true' if enabled else 'false'}), \
             patch('scripts.sources.merge.collect', return_value=([], [copy.deepcopy(result)])), \
             patch('scripts.sources.http.PoliteClient', return_value=self.client):
            summary = integrate(self.catalog, self.snapshot, as_of=day, write=True, adapters=adapters)
        return summary, load_catalog(self.catalog), json.loads(self.snapshot.read_bytes())

    def test_fresh_and_retained_observations_use_same_proof_before_canonical_merge(self):
        old = digest(source_last_seen_date='2026-09-28')
        self.seed([canonical()], cache(old))
        summary, catalog, state = self.run_window(observed(row('other', close_date='2026-11-05')))
        self.assertEqual(self.client.calls, [PROGRAM])
        self.assertNotIn(old['opportunity_id'], {r['opportunity_id'] for r in catalog['opportunities']})
        retained = next(r for r in state['sources']['vpr-email']['records'] if r['opportunity_id'] == old['opportunity_id'])
        self.assertEqual(retained['source_last_seen_date'], '2026-09-28')
        self.assertEqual(retained['official_identity']['checked_on'], DAY.isoformat())
        self.client.calls.clear()
        _, catalog, state = self.run_window(observed(row('other', close_date='2026-11-05')), day=DAY + timedelta(days=1))
        self.assertEqual(self.client.calls, [PROGRAM])
        self.assertNotIn(old['opportunity_id'], {r['opportunity_id'] for r in catalog['opportunities']})

    def test_disabled_lookup_holds_unverified_program_identity_without_guessing(self):
        self.seed([canonical()], cache())
        summary, catalog, state = self.run_window(observed(digest()), enabled=False)
        self.assertEqual(self.client.calls, [])
        self.assertEqual([r['opportunity_id'] for r in catalog['opportunities']], ['123456'])
        self.assertIn(digest()['opportunity_id'], summary['sources'][0]['withheld_ids'])

    def test_conflicting_old_edition_does_not_reappear_from_retained_cache(self):
        old = digest('NSF25-544'); self.seed([canonical('26-509')], cache(old))
        self.client.text = html('26-509')
        summary, catalog, state = self.run_window(observed(old, row('other', close_date='2026-11-05')))
        self.assertNotIn(old['opportunity_id'], {r['opportunity_id'] for r in catalog['opportunities']})
        self.assertIn(old['opportunity_id'], summary['sources'][0]['withheld_ids'])
        official = next(r for r in catalog['opportunities'] if r['opportunity_id'] == '123456')
        self.assertNotIn('source_aliases', official)
        self.assertEqual(summary['sources'][0]['observed_terminal_records'], [])

    def test_selective_refresh_resolves_existing_digest_before_official_record_arrives(self):
        from scripts.sources.adapters.rss import NSFFundingUpcoming
        old = digest()
        self.seed([old], cache(old))
        official = canonical(ident='nsf-funding:edition', source='NSF Funding')
        result = observed(official); result.slug = 'nsf-funding'; result.snapshot_complete = True
        summary, catalog, state = self.run_window(result, adapters=[NSFFundingUpcoming()])
        self.assertTrue(summary['written'])
        self.assertEqual(self.client.calls, [PROGRAM])
        self.assertEqual([r['opportunity_id'] for r in catalog['opportunities']], ['nsf-funding:edition'])
        self.assertEqual(catalog['opportunities'][0]['description'], official['description'])

    def test_selective_refresh_deduplicates_carried_pair_without_failing_base_count_gate(self):
        self.seed([canonical(), digest()], cache())
        result = observed(row('other', close_date='2026-11-05'))
        # No selected adapter owns either of the carried rows.
        summary, catalog, _ = self.run_window(result, adapters=[])
        self.assertTrue(summary['written'])
        self.assertEqual(summary['stats']['dropped_base_nsf_duplicates'], 1)
        self.assertNotIn(digest()['opportunity_id'], {r['opportunity_id'] for r in catalog['opportunities']})

    def test_historical_program_alias_resolves_without_erasing_collision_witnesses(self):
        a = digest(); b = digest(url=EDITION); b['title'] = 'Corrected digest heading'
        self.seed([], cache())
        _, catalog, saved = self.run_window(observed(a, b), enabled=False)
        self.assertEqual(catalog['opportunities'], [])
        original = copy.deepcopy(saved['sources']['vpr-email']['identity_witnesses']['observations'])
        summary, catalog, saved = self.run_window(observed(b))
        self.assertEqual(self.client.calls, [PROGRAM])
        self.assertEqual(len(catalog['opportunities']), 1)
        self.assertEqual(summary['sources'][0]['identity_collision_ids'], [])
        witnesses = saved['sources']['vpr-email']['identity_witnesses']['observations']
        self.assertTrue(all(item in witnesses for item in original))

    def test_request_failure_leaves_catalog_and_cache_unchanged(self):
        self.seed([canonical()], cache())
        before = [p.read_bytes() for p in (self.catalog, self.snapshot)]
        self.client.get_text = lambda _: (_ for _ in ()).throw(ValueError('NSF unavailable'))
        with self.assertRaisesRegex(ValueError, 'NSF unavailable'):
            self.run_window(observed(digest()))
        self.assertEqual([p.read_bytes() for p in (self.catalog, self.snapshot)], before)


if __name__ == '__main__':
    unittest.main()
