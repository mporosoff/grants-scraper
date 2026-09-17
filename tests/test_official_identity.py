from copy import deepcopy
import unittest
from unittest.mock import Mock

from scripts.sources import official_identity as identity
from scripts.sources.merge import merge_records

URL = 'https://simpler.grants.gov/opportunity/c342c01d-4f34-440f-8bb2-4bdd4d763df0'
TARGET = 'https://www.grants.gov/search-results-detail/363829'
HTML = '<a href="' + TARGET + '"><span>View on Grants.gov</span></a>'


class OfficialIdentity(unittest.TestCase):
    def record(self, **changes):
        return dict(opportunity_id='vpr-email:fixture', source='VPR digest',
            agency='VPR digest', agency_authority='source_default', title='A research call',
            detail_page=URL, funding_opportunity_url=URL, close_date='2026-10-09', **changes)

    def client(self, html=HTML):
        return Mock(get_text=Mock(return_value=html), last_url=URL)

    def test_official_link_preserves_deadline_stages_alias_and_conflict(self):
        external = self.record(); cache = {}
        identity.resolve([external], cache, client=self.client())
        base = dict(opportunity_id='363829', source='Grants.gov', agency='AFOSR',
            title='A research call', opportunity_number='FA955026S0003', close_date='2026-12-04',
            deadlines=[{'kind':'white_paper','date':'2026-10-09','required':True},
                       {'kind':'application','date':'2026-12-04'}],
            next_submission={'access':'verify_prerequisite','date':'2026-12-04'})
        before=deepcopy(base)
        result, _=merge_records([base], [external])
        self.assertEqual(base,before)
        self.assertEqual(len(result),1)
        for field in ('opportunity_id','close_date','deadlines','next_submission'):
            self.assertEqual(result[0][field],base[field])
        self.assertEqual(result[0]['source_aliases'][0]['official_identity'], cache[URL])
        self.assertEqual(result[0]['duplicate_source_conflicts'][0]['alternate_value'],'2026-10-09')
        self.assertEqual(merge_records(result,[external])[0],result)

    def test_exact_cached_mapping_reuses_original_date_and_never_refetches(self):
        r=self.record();cache={};client=self.client()
        identity.resolve([r,r],cache,client=client)
        before=deepcopy(cache)
        client.get_text.assert_called_once_with(URL)
        client.get_text.side_effect=AssertionError('no network')
        stats=identity.resolve([self.record()],cache,client=client)
        self.assertEqual(stats,dict(attempted=0,reused=1,resolved=1,unresolved=0))
        self.assertEqual(cache,before)

    def test_same_title_number_and_generic_links_do_not_prove_identity(self):
        r=self.record(opportunity_number='FA955026S0003')
        base=dict(r,opportunity_id='363829',source='Grants.gov',agency='AFOSR',agency_authority='official')
        for url in ('https://simpler.grants.gov/search','https://www.grants.gov/',URL):
            external=dict(r,detail_page=url,funding_opportunity_url=url)
            self.assertEqual(len(merge_records([base],[external])[0]),2)

    def test_direct_native_id_crosslinks_need_no_provider_or_page_fetch(self):
        base=dict(opportunity_id='363829',source='Grants.gov',agency='AFOSR',title='Call')
        r=dict(self.record(),detail_page=TARGET,funding_opportunity_url=TARGET)
        self.assertEqual(merge_records([base],[r])[0][0]['opportunity_id'],'363829')
        self.assertEqual(len(merge_records([base],[r])[0]),1)
        r['detail_page']=TARGET.replace('363829','363632')
        self.assertEqual(len(merge_records([base],[r])[0]),2)

    def test_untrusted_urls_redirects_wrong_anchors_and_conflicts_fail_closed(self):
        for url in ('http://www.grants.gov/search-results-detail/363829',
            'https://www.grants.gov.evil.test/search-results-detail/363829',
            'https://evil@www.grants.gov/search-results-detail/363829',
            TARGET+'?opportunityId=123', TARGET+'#123', '\n'+TARGET, TARGET+'/other'):
            self.assertIsNone(identity.grants_id(url),url)
        for html in ('<a href="'+TARGET+'">Some other reference</a>',
                     HTML+'<a href="'+TARGET.replace('363829','123')+'">View on Grants.gov</a>'):
            cache={};r=self.record()
            self.assertEqual(identity.resolve([r],cache,client=self.client(html))['unresolved'],1)
            self.assertNotIn('official_identity',r)
        client=self.client();client.last_url='https://example.org/redirect'
        with self.assertRaisesRegex(ValueError,'redirected'):
            identity.resolve([self.record()],{},client=client)
        base=dict(opportunity_id='363829',source='Grants.gov',agency='NSF',
            opportunity_number='26-500',title='Call')
        r=dict(self.record(),detail_page=TARGET,funding_opportunity_url=TARGET,
            agency='AFOSR',agency_authority='official',opportunity_number='FA955026S0003')
        with self.assertRaisesRegex(ValueError,'conflicts'):
            merge_records([base],[r])

    def test_wrong_source_or_old_parser_receipt_cannot_alias_a_new_record(self):
        r=self.record();cache={};identity.resolve([r],cache,client=self.client())
        for field,value in [('version',0),('source_url',URL.replace('c342c01d','a342c01d')),
                             ('target_url','https://evil.test/363829')]:
            modified=deepcopy(r);modified['official_identity'][field]=value
            self.assertIsNone(identity.record_grants_id(modified))
        limited=identity.resolve([self.record()],{},client=self.client(),limit=0)
        self.assertEqual(limited,dict(attempted=0,reused=0,resolved=0,unresolved=1))


if __name__=='__main__': unittest.main()
