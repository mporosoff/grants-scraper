"""Supported notice contracts, with positive recovery and wrong-subject guards."""
import unittest

from scripts import extract_document_evidence as e


DOCUMENT = {"url": "https://example.gov/official-notice", "sha256": "fixture"}
STAMP = "2026-09-07T12:00:00Z"


def facts(text, html=False):
    containers = e.extract_html_sections(text.encode())[0] if html else [
        {"text": text, "page": 1, "section": None, "anchor": None}]
    return e.extract_document_facts({"opportunity_id": "fixture"}, containers, DOCUMENT, STAMP)


def family(text, kind, **kwargs):
    return [f for f in facts(text, **kwargs) if f["type"] == kind]


class NoticeSemanticsTests(unittest.TestCase):
    def test_explicit_range_and_field_estimates_remain_owned_by_the_award(self):
        import json
        from pathlib import Path
        cases = json.loads((Path(__file__).parent / 'fixtures/parsing/local-money-fields.json').read_bytes())['cases']
        for case in cases:
            if case['opportunity_id'] not in {'363657', '363479', '363446'}:
                continue
            with self.subTest(opportunity_id=case['opportunity_id']):
                awards = [f for prior in case['legacy_facts']
                          for f in family(prior['citation']['quote'], 'award_range')]
                self.assertEqual(len(awards), len(case['expected_awards']))
                self.assertTrue(all(f['estimated'] is True for f in awards))
        text = ('The amount of funding is expected to be between $1 million and $2 million per award for Project Area 1. '
                'Other funding: between $3 million and $4 million per award for Project Area 2.')
        self.assertEqual([f['estimated'] for f in family(text, 'award_range')], [True, False])

    def test_program_budget_estimates_do_not_make_declared_per_award_caps_estimates(self):
        text = ('The Congressionally Directed Medical Research Programs (CDMRP) expects to allot roughly $3.2M '
                'to fund approximately two TrDA applications with total cost caps of $1.5M per award for the single PI option '
                'and $1.7M combined for the CIT Partnership Option.')
        found = family(text, 'award_range')
        self.assertEqual([f['value']['maximum'] for f in found], [1500000,1700000])
        self.assertTrue(all(f['estimated'] is False for f in found))
        estimated = family(text.replace('total cost caps', 'estimated total cost caps'), 'award_range')
        self.assertEqual(len(estimated), 2)
        self.assertTrue(all(f['estimated'] is True for f in estimated))

    def test_real_summary_after_outline_is_not_discarded_with_toc_page(self):
        from scripts.notice_semantics import substantive_spans
        # Native NOAA layout: the outline and substantive first fields share a
        # physical page. Old structure marked every line as TOC.
        text = ('NOAA NOFO Page 1 of 15\nTable of Contents\n'
                'III. Eligibility Information ....................4\n'
                'Executive Summary\nFederal Agency Name\nNOAA\n'
                'Eligible applicants are institutions of higher education.\n')
        start = text.index('Executive Summary')
        container = {'text': text, 'page': 2, 'toc': True,
                     'structure': [{'span': [0, start], 'toc': True}, {'span': [start, len(text)], 'toc': True}]}
        spans = list(substantive_spans(container))
        self.assertEqual(''.join(text[a:b] for a, b in spans), text[start:])
        container['text'] = text.replace('Federal Agency Name', 'Another outline entry')
        self.assertEqual(list(substantive_spans(container)), [])

    def test_adjacent_cdc_award_bounds_share_only_the_explicit_same_period(self):
        import json
        from pathlib import Path
        cases = json.loads((Path(__file__).parent / 'fixtures/parsing/cdc-award-period-bounds.json').read_bytes())['cases']
        for case in cases:
            found = e.extract_document_facts({'opportunity_id': case['opportunity_id']}, [case['container']],
                case['source'], case['source']['retrieved_at'], families={'amounts'})
            self.assertEqual([f['value'] for f in found if f['type'] == 'award_range'], [case['expected']])
            for boundary in ['Track 2:', 'Different awards:', 'Per Year']:
                text = case['container']['text'].replace('Award Floor:', boundary + ' Award Floor:')
                self.assertFalse(any(f['value']['minimum'] and f['value']['maximum'] for f in family(text, 'award_range')))

    def test_recovered_special_education_base_and_optional_administration_support(self):
        import json
        from pathlib import Path
        case = json.loads((Path(__file__).parent / 'fixtures/parsing/363467-funding.json').read_bytes())
        found = e.extract_document_facts({'opportunity_id': '363467'}, case['money_containers'], case['source'],
                                        case['source']['retrieved_at'], families={'amounts'})
        self.assertEqual([{k: f.get(k) for k in case['expected_awards'][0]} for f in found if f['type'] == 'award_range'],
                         case['expected_awards'])

    def test_conditional_ceiling_cannot_borrow_a_track_across_an_independent_field(self):
        base = 'Track 1 projects have a maximum award of $500,000 for up to three years.'
        exception = 'Institutions that have not received NSF funding in the past 5 years are eligible for a maximum of $600,000 for up to four years.'
        owned = family(base + ' ' + exception, 'award_range')
        self.assertEqual([f['value']['maximum'] for f in owned], [500000, 600000])
        self.assertIn('Institutions that have not received NSF funding', owned[1]['display_value'])
        self.assertEqual(e.structured_fact_conflicts({'award_ceiling': 500000}, owned[1]), [])
        for separator in ('\n\n', ' Eligibility requirements: ', ' Track 2: '):
            result = family(base + separator + exception, 'award_range')
            self.assertFalse(any(f.get('applicant_condition') for f in result))
            self.assertFalse(any(f['value']['maximum'] == 600000 for f in result))

    def test_current_pdf_spanning_funding_label_owns_rows_above_its_baseline(self):
        import json
        from copy import deepcopy
        from pathlib import Path
        fixture = json.loads((Path(__file__).parent / 'fixtures/parsing/363766-funding.json').read_bytes())
        document = {'url': fixture['source']['url'], 'sha256': fixture['source']['sha256']}
        def extract(containers):
            return [f for f in e.extract_document_facts({'opportunity_id': '363766'}, containers, document,
                fixture['source']['retrieved_at'], families={'amounts'}) if f['type'] == 'award_range']
        extracted = extract(fixture['containers'])
        self.assertEqual([{'track': f['track'], 'value': f['value']} for f in extracted], fixture['expected'])
        self.assertTrue(all(not f.get('estimate_kind') for f in extracted))
        self.assertTrue(all(f.get('estimated') is False for f in extracted))
        self.assertFalse(any(264123 in f['value'].values() for f in extracted), 'Historical average is a separate field')
        # Without the retained columns, do not guess that preceding prose
        # belongs to a later field. Independently labeled rows still survive.
        plain = deepcopy(fixture['containers'])
        plain[0].pop('layout_rows')
        self.assertEqual([f['track'] for f in extract(plain)],
                         ['Community-Centered Implementation', 'National Implementation', 'Applied Research'])

    def test_reviewed_current_money_fields_fresh_and_legacy_recovery(self):
        import json
        from copy import deepcopy
        from pathlib import Path
        fixture = json.loads((Path(__file__).parent / 'fixtures/parsing/local-money-fields.json').read_bytes())
        for row in fixture['cases']:
            with self.subTest(opportunity_id=row['opportunity_id']):
                source = row['source']
                old = row['legacy_facts']
                record = {'opportunity_id': row['opportunity_id']}
                fresh = []
                for prior in old:
                    citation = prior['citation']
                    fresh.extend(e.extract_document_facts(record, [{'text': citation['quote'],
                        'page': citation.get('page'), 'section': citation.get('section')}],
                        source, citation['extracted_at'], families={'amounts'}))
                entry = {'document': deepcopy(source), 'facts': deepcopy(old), 'checked_at': row['source_checked_at'],
                    'parser_dependencies': {**e.parser_dependencies(), 'amounts': 'legacy'}, 'status': 'current'}
                e.quarantine_legacy_facts(record, {}, entry, None)
                for mode, extracted in [('fresh', fresh), ('legacy', entry['facts'])]:
                    actual = [f for f in extracted if f['type'] == 'award_range']
                    keys = set().union(*(expected.keys() for expected in row['expected_awards']))
                    with self.subTest(mode=mode):
                        self.assertEqual([{k: f.get(k) for k in keys} for f in actual],
                            [{k: f.get(k) for k in keys} for f in row['expected_awards']])
                self.assertEqual(entry['checked_at'], row['source_checked_at'])
                self.assertEqual(entry['document'], source)
                self.assertEqual(entry['parser_pending']['reason'], 'original_source_structure_required')
                for fact in entry['facts']:
                    self.assertIn(fact['citation'], [f['citation'] for f in old])

    def test_native_money_fields_do_not_shift_missing_values_or_absorb_bullet_units(self):
        self.assertEqual(e.parse_money(*e.MONEY_RE.search('$500,000 b. A minimum of 50%').groups()), 500000)
        for raw, expected in [('$1M', 1000000), ('$1 M', 1000000), ('$1 million', 1000000), ('$1.5m', 1500000)]:
            self.assertEqual(e.parse_money(*e.MONEY_RE.search(raw).groups()), expected)
        self.assertEqual(family('Duration Start Date End Date Minimum award Maximum award '
            '2 years September 1, 2026 August 31, 2028 TBD $7.5M', 'award_range'), [])
        component = family('Maximum award amount per budget period: Component A: TBD; Component B: $5,000,000', 'award_range')
        self.assertEqual([(f['track'], f['value'], f['basis']) for f in component],
            [('Component B', {'minimum': None, 'maximum': 5000000}, 'per_budget_period')])
        annual = family('Average One Year Award Amount: $5,000,000', 'award_range')[0]
        self.assertEqual((annual['basis'], annual['estimate_kind']), ('per_year', 'average'))
        self.assertEqual(e.structured_fact_conflicts({'award_ceiling': 10000000}, annual), [])
        budgets = family('Expected total program funding over the performance period: '
            'Component A: $5,000,000; Component B: $25,000,000 '
            'Expected total program funding per budget period: Component A: $1,000,000; Component B: $5,000,000',
            'program_funding')
        self.assertEqual([(f['track'], f['value'], f['basis']) for f in budgets], [
            ('Component A', 5000000, 'program_total'), ('Component B', 25000000, 'program_total'),
            ('Component A', 1000000, 'program_per_budget_period'), ('Component B', 5000000, 'program_per_budget_period')])

    def test_current_doe_funding_sections_keep_equal_caps_in_distinct_topics(self):
        import json
        from pathlib import Path
        fixture = json.loads((Path(__file__).parent / 'fixtures/parsing/363065-funding.json').read_bytes())
        extracted = e.extract_document_facts({'opportunity_id': '363065'}, fixture['containers'],
            {'url': fixture['source']['url'], 'sha256': fixture['source']['sha256']}, fixture['source']['retrieved_at'],
            families={'amounts'})
        amounts = [f for f in extracted if f['type'] == 'award_range']
        self.assertEqual([{'track': f['track'], 'maximum': f['value']['maximum']} for f in amounts], fixture['expected'])
        self.assertTrue(all(f['funding_basis'] == 'federal_share' for f in amounts))
        self.assertTrue(all(f['track'] in f['track_citation']['quote'] for f in amounts))
        self.assertTrue(all(f['track'] in f['display_value'] and 'federal funds' in f['display_value'] for f in amounts))
        self.assertEqual(len({f['id'] for f in amounts}), 4)
        budgets = [f for f in extracted if f['type'] == 'program_funding']
        self.assertEqual([(f.get('track'), f['value']) for f in budgets], [
            (None, 150000000), ('Topic Area 1a', 30000000), ('Topic Area 1b', 36000000),
            ('Topic Area 1c', 60000000), ('Topic Area 2', 24000000)])
        self.assertTrue(all(f['funding_basis'] == 'federal_share' for f in budgets))
        text = ('Topic Area 1: Scientific work\nEach award has a maximum of $1 million.\n\n'
                '2. Separate Funding\nEach award has a maximum of $2 million.')
        separate = family(text, 'award_range')
        self.assertEqual([f['track'] for f in separate], ['Topic Area 1', None])

    def test_program_total_does_not_borrow_per_award_label(self):
        text = ("The program expects to allot roughly $5.6M to fund approximately 10 Idea Award "
                "applications with total cost caps of $0.56M per award. "
                "The maximum period of performance is 2 years.")
        extracted = facts(text)
        award = next(f for f in extracted if f['type'] == 'award_range')
        self.assertEqual(award['value'], {'minimum': None, 'maximum': 560000})
        self.assertEqual((award['subject'], award['basis'], award['cost_basis']), ('award', 'total_project', 'total'))
        self.assertEqual(next(f['value'] for f in extracted if f['type'] == 'program_funding'), 5600000)

    def test_epa_individual_award_retains_its_explicit_federal_funds_basis(self):
        # EPA-OW-OWOW-26-01, official PDF page 4, retrieved September 7, 2026;
        # full source receipt and table excerpt accompany pdf-schedule-rows.json.
        text = ('The amount of funding is expected to be approximately $3.5 million, with individual '
                'awards up to $175,000 in federal funds, depending on Agency funding levels, '
                'the quality of applications received, agency priorities, and other applicable considerations.')
        award = family(text, 'award_range')[0]
        self.assertEqual(award['value'], {'minimum': None, 'maximum': 175000})
        self.assertEqual(award['funding_basis'], 'federal_share')
        self.assertIn('federal funds', award['display_value'])
        other = family(text.replace('in federal funds', 'in total costs'), 'award_range')[0]
        self.assertIsNone(other.get('funding_basis'))

    def test_compliance_threshold_is_not_an_award(self):
        self.assertEqual(family("You must attach the completed Disclosure of Lobbying Activities if your "
            "grant amount exceeds $100,000 and you have lobbying activity to disclose.", 'award_range'), [])

    def test_explicit_lower_and_upper_bounds_recovered(self):
        result = family("The minimum Federal share per grant award is $1,000,000 and the "
            "maximum Federal share per award is $5,000,000.", 'award_range')
        self.assertEqual(result[0]['value'], {'minimum': 1000000, 'maximum': 5000000})

    def test_money_basis_and_track_are_not_collapsed(self):
        result = family("Each award has a maximum of $500,000 per year for the Pilot Track. "
            "Each award has a maximum of $1 million in direct costs for the Expansion Track.", 'award_range')
        self.assertEqual(len(result), 2)
        self.assertEqual([(f['basis'], f['cost_basis'], f['track']) for f in result],
            [('per_year', 'unspecified', 'Pilot Track'), ('total_project', 'direct', 'Expansion Track')])

    def test_cdmrp_two_explicit_track_caps_are_both_recovered(self):
        text = ('The program expects to allot roughly $7.8M to fund approximately 8 Idea Development Award '
                'applications with total cost caps of $900,000 for the IDA or $1.2M for the IDA – Partnering PI Option.')
        result = family(text, 'award_range')
        self.assertEqual([(f['value']['maximum'], f['track']) for f in result],
                         [(900000, 'IDA'), (1200000, 'IDA – Partnering PI Option')])

    def test_budget_period_bounds_do_not_become_track_or_whole_project_amount(self):
        text = ('Expected total program funding: $5,100,000 Total expected awards: 12 '
                'Minimum award amount for the first budget period (award floor): $125,000 '
                'Maximum award amount for the first budget period (award ceiling): $425,000 '
                'We plan to fund a four-year project period. Each project period has four one-year budget periods.')
        result = family(text, 'award_range')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['value'], {'minimum': 125000, 'maximum': 425000})
        self.assertEqual(result[0]['basis'], 'initial_budget_period')
        self.assertIsNone(result[0]['track'])
        self.assertEqual(e.structured_fact_conflicts({'award_ceiling': 1700000}, result[0]), [])

    def test_explicit_award_range_and_recurring_source_language_are_retained(self):
        result = family('Awards are anticipated to range from $150,000 to $600,000 in total costs over three years.', 'award_range')
        self.assertEqual(result[0]['value'], {'minimum': 150000, 'maximum': 600000})
        self.assertEqual(result[0]['cost_basis'], 'total')
        for text in ['This program recurs annually, with an anticipated submission window each autumn.',
                     'Applications are accepted on a continuing basis and reviewed quarterly.']:
            self.assertEqual([f['status_signal'] for f in family(text, 'status_signal')], ['recurring'])

    def test_cost_sharing_obligation_and_negation(self):
        cases = [
            ('Inclusion of voluntary committed cost sharing is prohibited.', False, 'voluntary_committed_prohibited'),
            ('Cost sharing is not an eligibility requirement.', False, 'not_required'),
            ('Cost sharing is optional.', False, 'not_required'),
            ('Cost sharing is not required.', False, 'not_required'),
            ('Cost sharing is required.', True, 'required'),
            ('Cost sharing is required only for commercial applicants.', None, 'conditional'),
            ('Cost Sharing Required?\nYes', True, 'required'),
            ('Cost Sharing Required?\nNo', False, 'not_required'),
        ]
        for text, value, obligation in cases:
            with self.subTest(text=text):
                result = family(text, 'cost_share')
                self.assertEqual(result[0]['value'], value)
                self.assertEqual(result[0]['obligation'], obligation)
        self.assertEqual(family('Cost sharing is discussed in the award policy.', 'cost_share'), [])
        self.assertEqual(family('Cost Sharing Required?\nUnknown', 'cost_share'), [])

    def test_nsf_track_support_keeps_separate_bounds(self):
        result = family('Track 1 proposals may receive support of $100,000-$400,000 for up to two years. '
            'Track 2 proposals may receive support of up to $2,000,000 over four years.', 'award_range')
        self.assertEqual([(f['track'], f['value']) for f in result], [
            ('Track 1', {'minimum': 100000, 'maximum': 400000}),
            ('Track 2', {'minimum': None, 'maximum': 2000000})])
        budgets = family('The anticipated budget for this program solicitation is $15,000,000 in FY 2027 '
            'and $15,000,000 in FY 2028, pending the availability of funds.', 'program_funding')
        self.assertEqual([(f['cycle'], f['value']) for f in budgets], [('FY 2027', 15000000), ('FY 2028', 15000000)])

    def test_structured_conflicts_remain_disclosed_through_projection(self):
        source = {'opportunity_id': 'fixture', 'cost_share_required': False, 'award_ceiling': 1000000}
        extracted = facts('Cost sharing is required. Each award has a maximum of $500,000.')
        entry = {'status': 'current', 'facts': extracted, 'document': DOCUMENT,
                 'extractor_identity': e.EXTRACTOR_IDENTITY}
        once = e.merge_document_entry(source, entry)
        twice = e.merge_document_entry(once, entry)
        self.assertEqual(once, twice)
        self.assertIs(once['cost_share_required'], False)
        self.assertEqual(once['award_ceiling'], 1000000)
        self.assertEqual(sum(q['type'] == 'structured_fact_conflict' for q in once['document_evidence']['review_queue']), 2)
        self.assertTrue(all('differs from structured' in f['display_value'] for f in once['document_evidence']['facts']
                            if f['type'] in {'cost_share', 'award_range'}))
        annual = family('Each award has a maximum of $500,000 per year.', 'award_range')[0]
        self.assertEqual(e.structured_fact_conflicts(source, annual), [])

    def test_substantive_section_survives_toc_rejection(self):
        html = ('<div class="toc">Eligibility ........... 3</div><h2>Eligibility</h2>'
            '<p>Eligible applicants include public and private institutions of higher education.</p>'
            '<h2>Review criteria</h2><p>Reviewers will consider significance, approach, and scientific merit.</p>')
        result = facts(html, html=True)
        self.assertEqual(next(f['value'] for f in result if f['type'] == 'eligibility_excerpt'),
            'Eligible applicants include public and private institutions of higher education.')
        self.assertIn('scientific merit', next(f['value'] for f in result if f['type'] == 'review_criteria'))
        self.assertEqual(family('Table of Contents\nEligibility ............. 3\nReview Criteria ........ 4', 'eligibility_excerpt'), [])

    def test_page_caps_belong_to_components(self):
        text = 'PI resume must not exceed 1 page. The research narrative is limited to 12 pages.'
        self.assertEqual({f['subject']: f['value'] for f in family(text, 'page_limit')},
                         {'PI resume': 1, 'Research narrative': 12})
        self.assertEqual(family('Rating Factor 1: Technical Merit', 'page_limit'), [])
        result = family('White papers must not exceed 5 single-sided pages, excluding cover sheet, references, and PI resume.', 'page_limit')
        self.assertEqual(result[0]['subject'], 'White paper')
        self.assertEqual(result[0]['value'], 5)
        self.assertEqual(result[0]['stage'], 'white_paper')
        self.assertEqual(result[0]['exclusions'], 'excluding cover sheet, references, and PI resume')

    def test_owned_scientific_review_section_does_not_require_modal_words(self):
        text = '<h2>Review criteria</h2><p>Develop heterogeneous catalyst materials. Measure reaction kinetics in laboratory reactors. Investigate zirconia catalysts with mechanistic measurements.</p>'
        result = family(text, 'review_criteria', html=True)
        self.assertEqual(len(result), 1)
        self.assertIn('zirconia', result[0]['value'])

    def test_post_recommendation_component_is_not_initial_requirement(self):
        result = family('Do not submit a Data Management Plan with the application. '
            'It will be requested only after recommendation for funding.', 'application_component')
        self.assertTrue(result)
        self.assertFalse(any(f['obligation'] == 'required' and f['stage'] == 'application' for f in result))
        self.assertTrue(any(f['obligation'] == 'prohibited' for f in result))
        self.assertTrue(any(f['stage'] == 'post_recommendation' and f['obligation'] == 'conditional' for f in result))
        positive = family('The Data Management Plan is required only after recommendation for funding.', 'application_component')
        self.assertEqual(positive[0]['stage'], 'post_recommendation')
        self.assertEqual(positive[0]['obligation'], 'conditional')
        conditional = family('If your effort generates scientific data, you must include a Data Management Plan with your application.', 'application_component')
        self.assertEqual((conditional[0]['stage'], conditional[0]['obligation']), ('application', 'conditional'))
        cap = family('Your Data Management Plan should be two (2) pages or less in length.', 'page_limit')
        self.assertEqual(cap[0]['value'], 2)
        self.assertEqual(family('Your Data Management Plan should be two (3) pages or less.', 'page_limit'), [])

    def test_cdmrp_component_aliases_preserve_both_obligations_after_cache_migration(self):
        import json
        from copy import deepcopy
        from pathlib import Path
        case = json.loads((Path(__file__).parent / 'fixtures/parsing/cdmrp-component-obligations.json').read_bytes())
        old = case['legacy_fact']
        entry = {'document': deepcopy(case['source']), 'facts': [deepcopy(old)],
                 'checked_at': case['source_checked_at'], 'status': 'current',
                 'parser_dependencies': {**e.parser_dependencies(), 'components': 'legacy'}}
        e.quarantine_legacy_facts({'opportunity_id': case['opportunity_id']}, {}, entry, None)
        for extracted in [family(old['citation']['quote'], 'application_component'), entry['facts']]:
            self.assertEqual([{k: f[k] for k in ('stage', 'obligation')} for f in extracted], case['expected'])
            self.assertFalse(any(f.get('obligation') == 'required' for f in extracted))
        self.assertEqual(entry['checked_at'], case['source_checked_at'])
        self.assertTrue(all(f['citation'] == old['citation'] for f in entry['facts']))
        self.assertEqual(len({f['id'] for f in entry['facts']}), 2)
        self.assertEqual(entry['parser_pending']['reason'], 'original_source_structure_required')

        acronym = old['citation']['quote'].replace('National Institutes of Health ', 'National Institutes of Health (NIH) ')
        self.assertEqual([{k: f[k] for k in ('stage', 'obligation')}
                          for f in family(acronym, 'application_component')], case['expected'])

    def test_institution_is_distinct_from_pi_limit_and_team_size(self):
        text = 'Each principal investigator is limited to one proposal. An institution may submit any number.'
        self.assertEqual(family(text, 'limited_submission'), [])
        self.assertEqual(family(text, 'investigator_submission_limit')[0]['value'], 1)
        self.assertEqual(family('The team must include one PI and two co-PIs.', 'limited_submission'), [])
        self.assertEqual(family('Applications are limited to one submission per institution.', 'limited_submission')[0]['value'], 1)
        native = ('<h2>Eligibility</h2><p>Limit on Number of Proposals per Organization:</p>'
                  '<p>There are no restrictions or limits.</p><p>Limit on Number of Proposals per PI or co-PI: 1</p>')
        self.assertEqual(family(native, 'limited_submission', html=True), [])
        self.assertEqual(family(native, 'institutional_submission_policy', html=True)[0]['value'], {'unlimited': True, 'maximum': None})
        self.assertEqual(family(native, 'investigator_submission_limit', html=True)[0]['value'], 1)

    def test_status_is_owned_by_current_notice_and_direction(self):
        for text in ['Proposals may be withdrawn by the applicant at any time before award.',
                     'This notice supersedes the previous notice.',
                     'If this notice is withdrawn, consult the agency website.']:
            with self.subTest(text=text):
                self.assertEqual(family(text, 'status_signal'), [])
        for text, status in [('This notice has been withdrawn.', 'cancelled'),
                             ('This solicitation is superseded by a new notice.', 'superseded'),
                             ('This announcement has been amended.', 'amended')]:
            with self.subTest(text=text):
                result = family(text, 'status_signal')
                self.assertEqual(result[0]['status_signal'], status)
                self.assertEqual(result[0]['subject'], 'current_solicitation')


if __name__ == '__main__':
    unittest.main()
