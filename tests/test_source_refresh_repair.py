"""Real catalog regression shapes, synthetic public feed/digest fixtures only."""
from datetime import date
from html import escape
import unittest

from scripts.build_catalog import record_identity
from scripts.sources.adapters.rss import NSFFundingUpcoming, RSSAdapter
from scripts.sources.adapters.vpr_email import extract_opportunities
from scripts.sources.merge import merge_records
from scripts.sources.validate import filter_publishable


INSTRUCTION = ('Applicants are STRONGLY ENCOURAGED to contact the appropriate '
    'Program Officer who is the point of contact for a specific technical area '
    'to discuss their research ideas before submitting a proposal. A list of '
    'most Program Officers and their contact information can be found at')


def feed(url, title='Research Experiences for Teachers'):
    return ('<rss><channel><item><title>' + escape(title) + '</title><link>'
        + escape(url) + '</link><description>Deadline: October 14, 2026. '
        'Official program listing.</description></item></channel></rss>')


def nsf_record(number):
    adapter = NSFFundingUpcoming()
    url = 'https://www.nsf.gov/funding/opportunities/program/' + number
    return list(adapter.parse(feed(url)))[0].to_record(
        slug=adapter.slug, source=adapter.display_name, source_type=adapter.source_type)


class OfficialFeedIdentity(unittest.TestCase):
    def test_confirmed_duplicates_keep_grants_id_source_links_and_conflicts(self):
        for number, stable in (('24-503', '350802'), ('21-595', '334326')):
            external = nsf_record('nsf' + number)
            base = dict(external, opportunity_id=stable, source='Grants.gov',
                agency='U.S. National Science Foundation', agency_code='NSF',
                close_date='2026-11-01', funding_opportunity_url='https://www.grants.gov/search-results-detail/' + stable)
            self.assertEqual(external['agency_authority'], 'source_listed')
            self.assertEqual(record_identity(base), record_identity(external))
            combined, stats = merge_records([base], [external])
            self.assertEqual(len(combined), 1)
            self.assertEqual(combined[0]['opportunity_id'], stable)
            self.assertEqual(combined[0]['close_date'], '2026-11-01')
            self.assertEqual(combined[0]['source_aliases'][0]['opportunity_id'], external['opportunity_id'])
            self.assertTrue(combined[0]['duplicate_source_conflicts'])
            self.assertEqual(stats['external_added'], 0)
            self.assertEqual(merge_records(combined, [external])[0], combined)

    def test_program_codes_successors_and_aggregators_remain_distinct(self):
        records = [nsf_record(v) for v in ('nsf24-110', 'pd24-110z', 'nsf24-503', 'nsf26-503')]
        self.assertEqual(len({record_identity(r) for r in records}), 4)
        aggregator = RSSAdapter().parse_feed(feed('https://www.nsf.gov/funding/opportunities/program/nsf24-503'))[0]
        record = aggregator.to_record(slug='aggregator', source='National Science Foundation', source_type='Federal')
        self.assertEqual(record['agency_authority'], 'source_default')
        self.assertTrue(record_identity(record).startswith('id:'))

    def test_untrusted_or_nonfunding_links_cannot_supply_sponsor_or_number(self):
        for url in ('https://www.nsf.gov.evil.test/funding/opportunities/x/nsf24-503',
                    'https://www.nsf.gov@evil.test/funding/opportunities/x/nsf24-503',
                    'http://www.nsf.gov/funding/opportunities/x/nsf24-503',
                    'https://www.nsf.gov/news/nsf24-503'):
            item = list(NSFFundingUpcoming().parse(feed(url)))[0]
            self.assertIsNone(item.agency)
            self.assertIsNone(item.opportunity_number)


class DigestInstructions(unittest.TestCase):
    def test_bold_prose_stays_inside_its_call_and_does_not_take_its_deadline(self):
        html = ('<p><b>External Funding</b></p><p><b>Naval Research Program</b></p>'
            '<p>Synopsis: Research in naval engineering.</p><p><b>' + INSTRUCTION
            + '</b><a href="https://www.onr.navy.mil/our-research/onr-technology-and-research">contacts</a></p>'
            '<p>Deadline: October 9, 2026</p><p><b>Other Research Award</b></p>'
            '<p>Synopsis: A separate award.</p><p>Deadline: November 1, 2026</p>')
        rows = extract_opportunities(html)
        self.assertEqual([r['title'] for r in rows], ['Naval Research Program', 'Other Research Award'])
        self.assertEqual(rows[0]['close_date'], '2026-10-09')
        self.assertEqual(rows[1]['close_date'], '2026-11-01')

    def test_plain_and_single_announcement_cannot_promote_prose(self):
        for body in (f'External Funding\n{INSTRUCTION}\nDeadline: October 9, 2026',
                     f'Subject: {INSTRUCTION}\nDeadline: October 9, 2026'):
            self.assertEqual(extract_opportunities(body), [])

    def test_cached_false_record_is_filtered_without_dropping_a_real_title(self):
        bad = dict(opportunity_id='vpr-email:vpr-7921302c954613de', title=INSTRUCTION,
            detail_page='https://www.onr.navy.mil/our-research/onr-technology-and-research', close_date='2026-10-09')
        good = dict(bad, opportunity_id='vpr-email:real', title='Research Opportunities for New Applicants')
        kept, dropped = filter_publishable([bad, good], date(2026, 9, 15))
        self.assertEqual(kept, [good])
        self.assertEqual(dropped, [{'opportunity_id': bad['opportunity_id'],
            'reason': 'application_instruction_not_opportunity'}])
