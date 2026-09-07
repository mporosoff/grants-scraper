"""Native fields recover supported stages without nearby-date substitution."""
import unittest

from scripts import extract_document_evidence as e, notice_schedule as schedule


def native(html, url='https://grants.nih.gov/grants/guide/rfa-files/test.html'):
    containers, _ = e.extract_html_sections(html.encode())
    return schedule.extract_native(e, 'fixture', containers, {'url': url, 'sha256': 'fixture'}, '2026-09-07T12:00:00Z')


class NoticeScheduleTests(unittest.TestCase):
    def test_fhwa_anticipated_columns_are_preserved_without_claiming_a_confirmed_cutoff(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        from scripts.submission_schedule import next_submission
        case = json.loads((Path(__file__).parent / 'fixtures/parsing/fhwa-anticipated-cycles.json').read_bytes())
        source, stamp = case['source'], case['source_checked_at']
        facts = e.extract_deadlines('348923', deepcopy(case['containers']), source, stamp)
        self.assertEqual([f['date'] for f in facts], case['expected_dates'])
        self.assertEqual([f.get('date_qualifier') for f in facts], case['expected_qualifiers'])
        record = {'opportunity_id': '348923', 'deadlines': [e.citation_deadline(f) for f in facts]}
        self.assertEqual([f['estimated'] for f in record['deadlines']], [False,True,True,True])
        self.assertEqual(next_submission(record, '2026-07-01')['access'], 'verify_stage')
        self.assertEqual(next_submission(record, '2026-09-07')['access'], 'verify_stage')
        self.assertTrue(all(f.get('date_qualifier_citation') for f in facts[1:]))
        damaged = deepcopy(case['containers'])
        for c in damaged:
            c['layout_rows'] = [{**row, 'cells': row.get('cells', [])[:2]} for row in c.get('layout_rows', [])]
        self.assertFalse(schedule._anticipated_cycle_table(e, 'fixture', damaged, source, stamp))

    def test_historical_receipt_fields_survive_limited_quote_migration(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        from scripts.notice_structure_cache import StructureCache
        import tempfile
        cases = json.loads((Path(__file__).parent / 'fixtures/parsing/historical-receipt-fields.json').read_bytes())['cases']
        for case in cases:
            with self.subTest(opportunity=case['opportunity_id']):
                key, source, stamp = case['opportunity_id'], case['source'], case['source_checked_at']
                found = e.extract_deadlines(key, deepcopy(case['containers']), source, stamp)
                self.assertEqual([[f.get(k) for k in ('date','time','timezone','track','cycle')] for f in found], case['expected'])
                old = {'status': 'current', 'document': source, 'facts': deepcopy(case['legacy_facts']), 'checked_at': stamp,
                       'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
                with tempfile.TemporaryDirectory() as directory:
                    e.quarantine_legacy_facts({'opportunity_id': key}, {'url': source['url']}, old, StructureCache(directory))
                self.assertEqual({f['date'] for f in old['facts'] if f['type'] == 'deadline'}, {row[0] for row in case['expected']})
                self.assertEqual(old['checked_at'], stamp)
                self.assertTrue(old['parser_pending'])  # Short quotes are still incomplete source recovery.
                self.assertTrue(all(f['interpretation_basis'] == 'limited_cached_quote' for f in old['facts']))
        for text in ['If applications must be received by May 1, 2027, contact the office.',
                     'Applications for eligibility before May 1, 2027 must be received by June 1, 2027.',
                     'Applications must be received by May 1, 2027 extended to TBD.']:
            self.assertEqual(schedule._owned_submission_sentences(e, 'fixture', [{'page':1,'text':text}], source, stamp), [])

    def test_pdf_explicit_cycles_and_lists_keep_dates_without_project_or_session_leakage(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        from datetime import datetime, timezone
        from scripts.notice_structure_cache import StructureCache, identity
        from scripts.submission_schedule import next_submission
        import tempfile
        cases = json.loads((Path(__file__).parent / 'fixtures/parsing/pdf-cycle-fields.json').read_bytes())['cases']
        for case in cases:
            with self.subTest(opportunity=case['opportunity_id']):
                source, key = case['source'], case['opportunity_id']
                stamp = source['retrieved_at']
                def values(facts):
                    return [[f.get(k) for k in ('deadline_kind', 'date', 'time', 'timezone', 'cycle', 'required')]
                            for f in facts if f['type'] == 'deadline']
                facts = e.extract_deadlines(key, deepcopy(case['containers']), source, stamp)
                self.assertEqual(values(facts), case['expected'])
                record = {'opportunity_id': key}
                old = {'status': 'current', 'document': source, 'facts': [], 'checked_at': stamp,
                       'source_scope_identity': e.source_scope_identity(source['url']),
                       'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
                with tempfile.TemporaryDirectory() as directory:
                    cache = StructureCache(directory)
                    cache.write(identity(source, old['source_scope_identity']), case['containers'], {})
                    rebuilt = e.reparse_from_structure(record, {'url': source['url']}, old,
                        datetime(2026, 9, 8, tzinfo=timezone.utc), cache)
                self.assertEqual(values(rebuilt['facts']), case['expected'])
                self.assertEqual(rebuilt['checked_at'], stamp)
                projected = e.merge_document_entry(record, rebuilt)
                if key == '355044':
                    selected = next_submission(projected, '2027-04-15')
                    self.assertEqual((selected['date'], selected['access']), ('2027-05-14', 'open'))
                elif key == '356231':
                    self.assertEqual(next_submission(projected, '2026-09-07')['access'], 'closed')
                    self.assertFalse(any(f['date'] == '2026-10-01' for f in facts))

    def test_nsf_current_submission_component_preserves_program_windows_and_scope(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        from datetime import datetime, timezone
        from scripts.notice_structure_cache import StructureCache, identity
        import tempfile
        case = json.loads((Path(__file__).parent / 'fixtures/parsing/nsf-submission-component.json').read_bytes())
        source = case['source']; stamp = source['retrieved_at']
        html = '<main><h1>Current program</h1><p>Research support.</p></main>' + case['html'].replace(
            '<aside>', '<aside><p>Related program archived. Application deadline: May 1, 2029.</p>')
        containers, metadata = e.extract_containers(html.encode(), 'text/html', '', source['url'])
        self.assertEqual(metadata['warnings'], [])
        record = {'opportunity_id': 'fixture'}
        facts = e.extract_document_facts(record, deepcopy(containers), source, stamp)
        dates = [f for f in facts if f['type'] == 'deadline']
        self.assertEqual([f['date'] for f in dates], case['expected_dates'])
        self.assertEqual([f.get('window_start') for f in dates], case['expected_window_starts'])
        self.assertTrue(all([f['time'], f['timezone']] == case['expected_clock'] for f in dates))
        self.assertEqual(len({f['track'] for f in dates}), 9)
        self.assertTrue(all(f['track'] in f['track_citation']['quote'] for f in dates))
        rolling = [f for f in facts if f.get('rolling')]
        self.assertEqual(len(rolling), case['expected_rolling_tracks'])
        self.assertIn('Chemistry of Life Processes', rolling[0]['track'])
        self.assertFalse(any(f['type'] == 'status' for f in facts))
        old = {'status': 'current', 'document': source, 'facts': [], 'checked_at': stamp,
               'source_scope_identity': e.source_scope_identity(source['url']),
               'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
        with tempfile.TemporaryDirectory() as directory:
            cache = StructureCache(directory)
            deps = identity(source, old['source_scope_identity'])
            # Structures from the old universal sidebar filter cannot satisfy
            # the new NSF source-specific dependency identity.
            previous = {**deps, 'structure_version': e.STRUCTURE_VERSION}
            cache.write(previous, [], {})
            self.assertIsNone(cache.read(deps))
            cache.write(deps, containers, metadata)
            rebuilt = e.reparse_from_structure(record, {'url': source['url']}, old,
                datetime(2026, 9, 8, tzinfo=timezone.utc), cache)
        self.assertEqual(rebuilt['checked_at'], stamp)
        projected = e.merge_document_entry(record, rebuilt)
        self.assertEqual([f.get('window_start') for f in projected['deadlines']], case['expected_window_starts'])
        self.assertEqual(len(projected['submission_requirements']), 1)
        for bad in [case['html'] * 2, '<nav>' + case['html'] + '</nav>',
                    '<aside><div role="navigation">' + case['html'] + '</div></aside>']:
            with self.subTest(boundary=bad[:50]):
                blocks, _ = e.extract_containers(bad.encode(), 'text/html', '', source['url'])
                self.assertEqual(e.extract_deadlines('fixture', blocks, source, stamp), [])
        # The generic HTML parser and other agencies do not opt into this sidebar.
        self.assertEqual(e.extract_html_sections(case['html'].encode())[0], [])
        self.assertEqual(e.extract_containers(case['html'].encode(), 'text/html', '', 'https://example.gov/')[0], [])

    def test_real_pdf_rounds_and_optional_loi_lists_survive_structure_revalidation(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        from datetime import datetime, timezone
        from scripts.notice_structure_cache import StructureCache, identity
        from scripts.submission_schedule import next_submission
        import tempfile
        cases = json.loads((Path(__file__).parent / 'fixtures/parsing/pdf-recurring-rounds.json').read_bytes())['cases']
        for case in cases:
            with self.subTest(opportunity=case['opportunity_id']):
                source, key = case['source'], case['opportunity_id']
                stamp = source['retrieved_at']
                def upcoming(facts):
                    return [[f.get(k) for k in ('deadline_kind','date','time','timezone','cycle','required')]
                            for f in facts if f.get('date') and f['date'] >= '2026-09-07']
                facts = e.extract_deadlines(key, deepcopy(case['containers']), source, stamp)
                self.assertEqual(upcoming(facts), case['expected_upcoming'])
                record = {'opportunity_id': key, 'close_date': case['expected_upcoming'][-1][1],
                          'deadlines': [{'kind': 'application', 'date': case['expected_upcoming'][-1][1], 'confidence': 'official_structured'}]}
                old = {'status': 'current', 'document': source, 'facts': [], 'checked_at': stamp,
                       'source_scope_identity': e.source_scope_identity(source['url']),
                       'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
                with tempfile.TemporaryDirectory() as directory:
                    cache = StructureCache(directory)
                    cache.write(identity(source, old['source_scope_identity']), case['containers'], {})
                    rebuilt = e.reparse_from_structure(record, {'url': source['url']}, old,
                        datetime(2026, 9, 8, tzinfo=timezone.utc), cache)
                self.assertEqual(upcoming(rebuilt['facts']), case['expected_upcoming'])
                self.assertEqual(rebuilt['checked_at'], stamp)
                projected = e.merge_document_entry(record, rebuilt)
                selected = next_submission(projected, '2026-09-07')
                self.assertEqual((selected['date'], selected['access']), (case['expected_upcoming'][0][1], 'open'))
                if key.startswith('33497'):
                    # Optional historical LOIs cannot close the full cycle.
                    self.assertEqual(next_submission(projected, '2027-01-01')['access'], 'open')

    def test_nih_spanning_headers_recover_receipt_cycles_without_review_dates(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        from datetime import datetime, timezone
        from scripts.notice_structure_cache import StructureCache, identity
        from scripts.submission_schedule import next_submission
        import tempfile
        cases = json.loads((Path(__file__).parent / 'fixtures/parsing/nih-key-date-tables.json').read_bytes())['cases']
        for case in cases:
            with self.subTest(opportunity=case['opportunity_id']):
                source = case['source']; stamp = source['retrieved_at']
                containers, _ = e.extract_containers(case['html'].encode(), 'text/html', '', source['url'])
                facts = e.extract_deadlines(case['opportunity_id'], deepcopy(containers), source, stamp)
                for classification in ('new', 'resubmission'):
                    self.assertEqual([f['date'] for f in facts if f['application_class'] == classification], case['expected_new_dates'])
                self.assertEqual(len(facts), 6)
                self.assertTrue(all(f['time'] == '5:00 PM' and f['timezone'] == 'applicant_local' and f.get('clock_citation') for f in facts))
                record = {'opportunity_id': case['opportunity_id'], 'close_date': case['expected_new_dates'][-1],
                          'deadlines': [{'date': case['expected_new_dates'][-1], 'kind': 'application', 'confidence': 'official_structured'}]}
                entry = {'status': 'current', 'document': source, 'facts': [], 'checked_at': stamp,
                         'source_scope_identity': e.source_scope_identity(source['url']),
                         'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
                with tempfile.TemporaryDirectory() as directory:
                    cache = StructureCache(directory)
                    cache.write(identity(source, entry['source_scope_identity']), containers, {})
                    entry = e.reparse_from_structure(record, {'url': source['url']}, entry,
                        datetime(2026, 9, 8, tzinfo=timezone.utc), cache)
                self.assertEqual(entry['checked_at'], stamp)
                self.assertEqual(next_submission(e.merge_document_entry(record, entry), '2026-09-07')['date'], case['expected_new_dates'][1])
                for damaged in [case['html'].replace('Application Due Dates', 'Scientific Merit Review'),
                                case['html'].replace('colspan="3"', 'colspan="2"', 1)]:
                    broken, _ = e.extract_containers(damaged.encode(), 'text/html', '', source['url'])
                    # The column under Review and Award Cycles cannot supply a
                    # general application date, even when dates look plausible.
                    found = e.extract_deadlines('fixture', broken, source, stamp)
                    self.assertFalse(any(f['date'] not in case['expected_new_dates'] for f in found))

    def test_cover_reader_retains_the_existing_ambiguous_field_safeguards(self):
        source = {'url': 'https://www.energy.gov/notice.pdf', 'sha256': 'fixture'}
        for text in [
            'Application Deadline: May 1, 2027 has been extended to TBD',
            'Application Deadline: May 1, 2027 revised to an unannounced date',
            'Application Deadline: May 1, 2027 (optional]',
            'Letter of Intent Full Application Deadline: May 1, 2027',
            'Application Deadline: May 1, 2027 at 5 p.m. Eastern or 6 p.m. Pacific',
        ]:
            with self.subTest(text=text):
                warnings = []
                self.assertEqual(e.extract_deadlines('fixture', [{'text': text, 'page': 1}], source,
                                                     'original', warnings), [])
                self.assertTrue(any(w['type'] == 'deadline_evidence_withheld' for w in warnings))

    def test_partial_clock_duplicates_cannot_erase_an_owned_zone_or_hide_a_conflict(self):
        source = {'url': 'https://www.energy.gov/notice.pdf', 'sha256': 'fixture'}
        for clock, expected in [('5 pm', ('5 pm', 'Eastern')), ('6 pm', (None, None))]:
            for reverse in (False, True):
                containers = [{'page': 1, 'text': 'Application Deadline: May 1, 2027 at 5 pm Eastern'},
                              {'page': 1, 'text': 'Application Deadline: May 1, 2027 at ' + clock}]
                facts = e.extract_deadlines('fixture', list(reversed(containers)) if reverse else containers,
                                            source, 'original')
                self.assertEqual([(f['time'], f['timezone']) for f in facts], [expected])

    def test_paper_waiver_dates_and_named_submission_periods_remain_independent(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        from scripts.submission_schedule import next_submission
        cases = json.loads((Path(__file__).parent / 'fixtures/parsing/submission-periods-and-waiver.json').read_bytes())['cases']
        for case in cases:
            key = case['opportunity_id']
            with self.subTest(opportunity=key):
                containers = [{'page': f['citation']['page'], 'text': f['citation']['quote']} for f in case['legacy_facts']]
                facts = e.extract_deadlines(key, containers, case['source'], case['source_checked_at'])
                prior = {'status': 'current', 'document': case['source'], 'facts': deepcopy(case['legacy_facts']),
                         'checked_at': case['source_checked_at'], 'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
                e.quarantine_legacy_facts(case['record'], {}, prior, None)
                for source_facts in (facts, prior['facts']):
                    if key == '362364':
                        self.assertEqual({(f['date'], f.get('application_class')) for f in source_facts},
                                         {('2027-05-01', 'paper_waiver'), ('2027-06-09', 'unspecified')})
                    else:
                        self.assertEqual({(f['date'], f.get('cycle')) for f in source_facts},
                                         {('2026-08-26', 'First submission period'), ('2027-08-26', 'Second submission period')})
                output = e.merge_document_entry(case['record'], prior)
                selected = next_submission(output, '2026-09-07')
                self.assertEqual(selected['date'], case['record']['close_date'])
                self.assertEqual(prior['checked_at'], case['source_checked_at'])
                if key == '362364':
                    self.assertEqual(selected['event']['time'], '11:59 p.m.')  # Structured clock retains authority.
                    self.assertEqual(next_submission(output, '2026-09-07', application_class='paper_waiver')['date'], '2027-05-01')
                    paper = next(f for f in prior['facts'] if f['date'] == '2027-05-01')
                    self.assertEqual(paper['obligation'], 'conditional')
                    self.assertEqual(paper['track'], 'Paper submission with waiver')
                else:
                    self.assertEqual(selected['event']['cycle'], 'Second submission period')
                    self.assertEqual(selected['event']['timezone'], 'Mountain Daylight Time')

    def test_numbered_due_date_fields_do_not_lose_a_real_loi_or_borrow_the_full_clock(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        case = json.loads((Path(__file__).parent / 'fixtures/parsing/337086-submission-labels.json').read_bytes())
        containers = [{'page': f['citation']['page'], 'text': f['citation']['quote']} for f in case['legacy_facts']]
        facts = e.extract_deadlines('337086', containers, case['source'], case['source_checked_at'])
        self.assertEqual({(f['deadline_kind'], f['date']) for f in facts},
                         {('letter_of_intent', '2024-09-21'), ('application', '2027-02-11')})
        loi = next(f for f in facts if f['deadline_kind'] == 'letter_of_intent')
        self.assertIsNone(loi['time'])
        self.assertIsNone(loi['required'])
        prior = {'status': 'current', 'document': case['source'], 'facts': deepcopy(case['legacy_facts']),
                 'checked_at': case['source_checked_at'], 'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
        e.quarantine_legacy_facts({'opportunity_id': '337086'}, {}, prior, None)
        self.assertEqual({(f['deadline_kind'], f['date']) for f in prior['facts']},
                         {('letter_of_intent', '2024-09-21'), ('application', '2027-02-11')})
        self.assertEqual(prior['checked_at'], case['source_checked_at'])

    def test_source_lists_named_applicant_groups_phases_and_delivery_deadlines_are_retained(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        from scripts.submission_schedule import next_submission
        cases = json.loads((Path(__file__).parent / 'fixtures/parsing/submission-recovery-fields.json').read_bytes())['cases']
        expected = {
            '345738': {('application', '2023-12-01', None, None), ('application', '2024-10-31', None, None),
                       ('application', '2025-10-31', None, None), ('application', '2026-10-30', None, None),
                       ('letter_of_intent', '2023-11-01', None, None)},
            '361876': {('application', '2026-10-16', '5:00 PM', 'Multi-State Partners to Participating States'),
                       ('application', '2026-12-04', '11:59 PM', 'Participating States and Entities in Nonparticipating States to AMS')},
            '362893': {('preproposal', '2026-07-29', None, None), ('application', '2026-10-14', None, None)},
            '362029': {('application', '2026-06-12', None, 'Phase 1'), ('application', '2026-09-11', None, 'Phase 2'),
                       ('application', '2026-12-31', None, 'Phase 3')},
            '363692': {('preproposal', '2026-10-05', '5:00 p.m.', None), ('application', '2027-01-22', '11:59 pm', None)},
        }
        def values(facts):
            return {(f['deadline_kind'], f.get('date'), f.get('time'), f.get('track')) for f in facts}
        for case in cases:
            key = case['opportunity_id']
            with self.subTest(opportunity=key):
                containers = [{'page': f['citation'].get('page'), 'text': f['citation']['quote']} for f in case['legacy_facts']]
                facts = e.extract_deadlines(key, containers, case['source'], case['source_checked_at'])
                self.assertEqual(values(facts), expected[key])
                prior = {'status': 'current', 'document': case['source'], 'checked_at': case['source_checked_at'],
                         'facts': deepcopy(case['legacy_facts']), 'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
                e.quarantine_legacy_facts(case['record'], {}, prior, None)
                self.assertEqual(values(prior['facts']), expected[key])
                self.assertEqual(prior['checked_at'], case['source_checked_at'])
                selected = next_submission(e.merge_document_entry(case['record'], prior), '2026-09-07')
                self.assertEqual(selected['date'], {'345738': '2026-10-30', '361876': '2026-10-16',
                    '362893': '2026-10-14', '362029': '2026-09-11', '363692': '2026-10-05'}[key])
                if key == '363692':
                    self.assertTrue(selected['event']['required'])
                    self.assertEqual(selected['event']['timezone'], 'Eastern')
                if key == '361876':
                    self.assertEqual(selected['event']['track'], 'Multi-State Partners to Participating States')
                if key == '362893':
                    projected = e.merge_document_entry(case['record'], deepcopy(prior))
                    window = next(d for d in projected['deadlines'] if d['date'] == '2026-12-16')
                    self.assertEqual(window['kind'], 'submission')
                    self.assertEqual(window['note'], case['record']['deadlines'][0]['note'])
                    self.assertEqual(next_submission(projected, '2026-10-15')['access'], 'verify_stage')
                    unproved = deepcopy(case['record'])
                    unproved['deadlines'][0]['note'] = 'Full applications close December 16, 2026.'
                    self.assertEqual(next_submission(e.merge_document_entry(unproved, deepcopy(prior)), '2026-09-07')['date'], '2026-12-16')
        # A labeled list stops before a different event rather than acquiring
        # that event's date. Scope labels containing dates are not pure labels.
        for text in ['Application Due Date(s): May 1, 2027; June 1, 2027; Awards start July 1, 2027',
                     'Application Due Date (Eligibility since July 1, 2027): May 1, 2027']:
            found = e.extract_deadlines('fixture', [{'page': 1, 'text': text}], cases[0]['source'], 'original')
            self.assertFalse(any(f.get('date') == '2027-07-01' for f in found))

    def test_component_submission_deadline_does_not_extend_the_full_application(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        from scripts.submission_schedule import next_submission
        case = json.loads((Path(__file__).parent / 'fixtures/parsing/362866-component-deadline.json').read_bytes())
        containers = [{'page': f['citation']['page'], 'text': f['citation']['quote']} for f in case['legacy_facts']]
        facts = e.extract_deadlines('362866', containers, case['source'], case['source_checked_at'])
        expected = {('letter_of_intent', '2026-10-23'), ('application', '2026-11-06')}
        self.assertEqual({(f['deadline_kind'], f['date']) for f in facts}, expected)
        entry = {'status': 'current', 'document': case['source'], 'facts': deepcopy(case['legacy_facts']),
                 'checked_at': case['source_checked_at'], 'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
        e.quarantine_legacy_facts(case['record'], {}, entry, None)
        self.assertEqual({(f['deadline_kind'], f['date']) for f in entry['facts']}, expected)
        self.assertEqual(entry['checked_at'], case['source_checked_at'])
        projected = e.merge_document_entry(case['record'], entry)
        self.assertEqual(next_submission(projected, '2026-11-07')['access'], 'closed')
        # The same generic field remains supported when it owns the clause.
        found = e.extract_deadlines('fixture', [{'text': 'Submission Deadline: May 1, 2027'}], case['source'], 'original')
        self.assertEqual([f['date'] for f in found], ['2027-05-01'])

    def test_pdf_schedule_columns_keep_actual_event_and_recommended_date_ownership(self):
        import json
        import tempfile
        from datetime import datetime, timezone
        from pathlib import Path
        from copy import deepcopy
        from scripts.notice_structure_cache import StructureCache, identity
        from scripts.submission_schedule import next_submission
        cases = json.loads((Path(__file__).parent / 'fixtures/parsing/pdf-schedule-rows.json').read_bytes())['cases']
        for case in cases:
            with self.subTest(opportunity=case['opportunity_id']):
                key, source = case['opportunity_id'], case['source']
                facts = e.extract_deadlines(key, deepcopy(case['containers']), source, source['retrieved_at'])
                keys = case['expected'][0].keys()
                self.assertEqual([{k: f.get(k) for k in keys} for f in facts], case['expected'])
                previous = {'status': 'current', 'document': source, 'facts': [], 'checked_at': source['retrieved_at'],
                            'source_scope_identity': e.source_scope_identity(source['url']),
                            'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
                with tempfile.TemporaryDirectory() as directory:
                    cache = StructureCache(directory)
                    cache.write(identity(source, previous['source_scope_identity']), case['containers'], {})
                    reparsed = e.reparse_from_structure(case['record'], {'url': source['url']}, previous,
                        datetime(2026, 9, 8, tzinfo=timezone.utc), cache)
                self.assertEqual([{k: f.get(k) for k in keys} for f in reparsed['facts']], case['expected'])
                self.assertEqual(reparsed['checked_at'], previous['checked_at'])
                self.assertFalse(reparsed['parser_migration']['source_retrieved'])
                projected = e.merge_document_entry(case['record'], reparsed)
                selected = next_submission(projected, '2026-09-07')
                self.assertEqual((selected['date'], selected['access']), (case['record']['close_date'], 'open'))
                self.assertEqual(selected['event']['time'], '4 pm' if key == '362836' else '11:59 pm')
                if key == '362836':
                    self.assertEqual(selected['event']['date_qualifier'], 'recommended')
                    self.assertEqual(next_submission(projected, '2026-11-17')['access'], 'verify_stage')
                broken = deepcopy(case['containers'])
                for container in broken:
                    container.pop('layout_rows', None)
                without_rows = e.extract_deadlines(key, broken, source, source['retrieved_at'])
                self.assertFalse(any(f.get('time') for f in without_rows))

    def test_current_optional_loi_listing_stage_and_schedule_header_ownership(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        from scripts.submission_schedule import next_submission
        cases = json.loads((Path(__file__).parent / 'fixtures/parsing/submission-field-boundaries.json').read_bytes())['cases']
        expected = {'361002': ('2026-09-26', 'open', 'letter_of_intent', None, None),
                    '363632': ('2026-10-30', 'open', 'application', '5:00 pm', 'Eastern'),
                    'vpr-email:vpr-ddde5b48dc92bba2': ('2026-10-29', 'open', 'letter_of_intent', '12 p.m.', 'Eastern')}
        for case in cases:
            key = case['opportunity_id']
            with self.subTest(opportunity=key):
                containers = [{'page': f['citation'].get('page'), 'text': f['citation']['quote']} for f in case['legacy_facts']]
                facts = e.extract_deadlines(key, containers, case['source'], case['source_checked_at'])
                entry = {'status': 'current', 'document': case['source'], 'facts': facts,
                         'deadline_extractor_identity': e.DEADLINE_EXTRACTOR_IDENTITY}
                result = next_submission(e.merge_document_entry(case['record'], entry), '2026-09-07')
                actual = (result['date'], result['access'], result['event']['kind'], result['event'].get('time'), result['event'].get('timezone'))
                self.assertEqual(actual, expected[key])
                old = {'status': 'current', 'document': case['source'], 'facts': deepcopy(case['legacy_facts']),
                       'checked_at': case['source_checked_at'], 'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
                e.quarantine_legacy_facts(case['record'], {}, old, None)
                cached = next_submission(e.merge_document_entry(case['record'], old), '2026-09-07')
                self.assertEqual((cached['date'], cached['access'], cached['event']['kind'], cached['event'].get('time'), cached['event'].get('timezone')), expected[key])
                self.assertEqual(old['checked_at'], case['source_checked_at'])
                if key == '361002':
                    self.assertFalse(result['event']['required'])
                    self.assertEqual({f['date'] for f in facts if f['type'] == 'deadline'}, {'2026-09-26', '2026-10-26'})
                    # October 26 remains accessible after this optional LOI.
                    self.assertEqual(next_submission(e.merge_document_entry(case['record'], entry), '2026-09-27')['access'], 'open')

    def test_measured_cdmrp_slash_labels_retain_preproposal_and_full_dates(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        for key, pre, full in [('362252', '2026-07-07', '2026-10-21'), ('362857', '2026-08-18', '2026-11-16')]:
            with self.subTest(opportunity=key):
                case = json.loads((Path(__file__).parent / f'fixtures/parsing/{key}-submission-labels.json').read_bytes())
                containers = [{'page': f['citation']['page'], 'text': f['citation']['quote']} for f in case['legacy_facts']]
                found = e.extract_deadlines(key, containers, case['source'], case['source_checked_at'])
                expected = [('preproposal', pre, '5:00 p.m.', 'Eastern'), ('application', full, '11:59 p.m.', 'ET')]
                self.assertEqual([(f['deadline_kind'], f['date'], f['time'], f['timezone']) for f in found], expected)
                entry = {'status': 'current', 'document': case['source'], 'facts': deepcopy(case['legacy_facts']),
                         'checked_at': case['source_checked_at'], 'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
                e.quarantine_legacy_facts({'opportunity_id': key}, {}, entry, None)
                self.assertEqual([(f['deadline_kind'], f['date'], f['time'], f['timezone']) for f in entry['facts']], expected)
                self.assertEqual(entry['checked_at'], case['source_checked_at'])

    def test_explicit_preapplication_aliases_are_one_stage_without_losing_precision(self):
        from copy import deepcopy
        for alias, kind in [('Preproposal', 'preproposal'), ('Letter of Intent', 'letter_of_intent')]:
            text = ('Pre-Application Due: September 16, 2026\nApplication Due: October 7, 2026\n'
                    f'Pre-Application ({alias}) Submission Deadline: 5:00 p.m. ET, September 16, 2026')
            found = e.extract_deadlines('fixture', [{'page': 1, 'text': text}], {
                'url': 'https://example.gov/notice.pdf', 'sha256': 'same'}, 'original')
            self.assertEqual(sorted((f['deadline_kind'], f['date']) for f in found),
                             sorted([('application', '2026-10-07'), (kind, '2026-09-16')]))
            specific = next(f for f in found if f['deadline_kind'] == kind)
            generic = deepcopy(specific)
            generic.update(deadline_kind='preapplication', time=None, timezone=None)
            generic['citation'].pop('structural_reference', None)
            self.assertEqual(schedule.consolidate_preliminary_aliases([generic, specific]), [specific])
            for field, value in [('time', '4:00 p.m.'), ('required', True), ('cycle', 'FY2027')]:
                different = deepcopy(generic); different[field] = value
                self.assertEqual(len(schedule.consolidate_preliminary_aliases([different, specific])), 2)
            different = deepcopy(generic); different['citation']['sha256'] = 'different'
            self.assertEqual(len(schedule.consolidate_preliminary_aliases([different, specific])), 2)

    def test_explicit_loi_window_refines_only_its_own_estimated_listing_label(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        from scripts.submission_schedule import next_submission
        case = json.loads((Path(__file__).parent / 'fixtures/parsing/363396-loi-window.json').read_bytes())
        containers = [{'page': f['citation']['page'], 'text': f['citation']['quote']} for f in case['legacy_facts']]
        facts = e.extract_deadlines('363396', containers, case['source'], case['source_checked_at'])
        self.assertEqual([(f['deadline_kind'], f['date'], f['time'], f['timezone']) for f in facts],
                         [('letter_of_intent', '2026-10-09', '11:59 a.m.', 'ET')])
        self.assertEqual(facts[0]['window_start'], '2026-09-08')
        entry = {'status': 'current', 'document': case['source'], 'facts': facts,
                 'deadline_extractor_identity': e.DEADLINE_EXTRACTOR_IDENTITY}
        result = e.merge_document_entry(case['record'], deepcopy(entry))
        selected = next_submission(result, '2026-09-07')
        self.assertEqual((selected['date'], selected['access'], selected['event']['kind']),
                         ('2026-10-09', 'open', 'letter_of_intent'))
        self.assertTrue(selected['event']['estimated'])
        self.assertEqual(selected['event']['timezone'], 'Eastern Time')
        old = {'status': 'current', 'document': case['source'], 'facts': deepcopy(case['legacy_facts']),
               'checked_at': case['source_checked_at'], 'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
        e.quarantine_legacy_facts({'opportunity_id': '363396'}, {}, old, None)
        self.assertEqual([(f['deadline_kind'], f['date']) for f in old['facts']], [('letter_of_intent', '2026-10-09')])
        self.assertEqual(old['checked_at'], case['source_checked_at'])
        for confidence, note in [('official_structured', case['record']['deadlines'][0]['note']),
                                 ('official_estimate', 'Full applications close October 9, 2026.')]:
            record = deepcopy(case['record'])
            record['deadlines'][0].update(confidence=confidence, note=note)
            self.assertEqual(e.merge_document_entry(record, deepcopy(entry))['deadlines'][0]['kind'], 'estimated_application')

    def test_related_ies_cover_dates_survive_incomplete_clocks_and_lois_remain_optional(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        from scripts.submission_schedule import next_submission
        cases = json.loads((Path(__file__).parent / 'fixtures/parsing/ies-submission-recovery.json').read_bytes())['cases']
        for case in cases:
            with self.subTest(opportunity=case['opportunity_id']):
                queue = []
                facts = e.extract_deadlines(case['opportunity_id'], deepcopy(case['containers']), case['source'],
                                           case['source']['retrieved_at'], queue)
                self.assertEqual([{k: f.get(k) for k in case['expected'][0]} for f in facts], case['expected'])
                if case['opportunity_id'] != '363467':
                    self.assertTrue(any(item['type'] == 'deadline_evidence_withheld' for item in queue))
                entry = {'status': 'current', 'document': case['source'], 'facts': facts,
                         'deadline_extractor_identity': e.DEADLINE_EXTRACTOR_IDENTITY}
                output = e.merge_document_entry({'opportunity_id': case['opportunity_id'], 'close_date': '2026-10-01'}, entry)
                selected = next_submission(output, '2026-09-07')
                self.assertEqual((selected['date'], selected['access']), ('2026-10-01', 'open'))

    def test_explicit_key_dates_cover_sentence_retains_submission_clock(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        case = json.loads((Path(__file__).parent / 'fixtures/parsing/363724-key-dates.json').read_bytes())
        citation = case['legacy_fact']['citation']
        facts = e.extract_deadlines('363724', [{'page': citation['page'], 'text': citation['quote']}],
                                    case['source'], case['source_checked_at'])
        self.assertEqual([(f['deadline_kind'], f['date'], f['time'], f['timezone']) for f in facts],
                         [('application', '2026-10-09', '4:00 p.m.', 'Eastern')])
        entry = {'status': 'current', 'document': case['source'], 'facts': [deepcopy(case['legacy_fact'])],
                 'checked_at': case['source_checked_at'], 'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
        e.quarantine_legacy_facts({'opportunity_id': '363724'}, {}, entry, None)
        self.assertEqual(entry['facts'][0]['date'], '2026-10-09')
        self.assertEqual(entry['facts'][0]['time'], '4:00 p.m.')
        self.assertEqual(entry['checked_at'], case['source_checked_at'])

    def test_ies_cover_table_preserves_optional_loi_and_second_precision_clock(self):
        import json
        from pathlib import Path
        from scripts.submission_schedule import next_submission
        fixture = json.loads((Path(__file__).parent / 'fixtures/parsing/363466-submission.json').read_bytes())
        source = fixture['source']
        facts = e.extract_document_facts({'opportunity_id': '363466'}, fixture['containers'], source, source['retrieved_at'], families={'deadlines'})
        keys = fixture['expected'][0].keys()
        self.assertEqual([{k:f.get(k) for k in keys} for f in facts], fixture['expected'])
        output = e.merge_document_entry({'opportunity_id': '363466', 'close_date': '2026-10-01'},
            {'facts': facts, 'document': source, 'status': 'current', 'deadline_extractor_identity': e.DEADLINE_EXTRACTOR_IDENTITY})
        selected = next_submission(output, '2026-09-07')
        self.assertEqual((selected['date'], selected['access']), ('2026-10-01', 'open'))
        self.assertEqual(selected['event']['time'], '11:59:59 p.m.')
        money = e.extract_document_facts({'opportunity_id': '363466'}, fixture['money_containers'], source,
                                       source['retrieved_at'], families={'amounts'})
        self.assertEqual([{k:f.get(k) for k in fixture['expected_awards'][0]} for f in money if f['type']=='award_range'], fixture['expected_awards'])
        self.assertFalse(any(f['value'].get('maximum') == 700000 for f in money if f['type']=='award_range'))
        for invalid in ('11:59:99 p.m.', '59:59 p.m.', '111:59 p.m.'):
            self.assertIsNone(e.TIME_RE.search(invalid))
        accepted = e.TIME_RE.search('11:59:59 p.m. Eastern Time')
        self.assertFalse(e.cached_deadline_time_supported({'time':'11:59 p.m.','timezone':'Eastern'}, accepted))
        self.assertTrue(e.cached_deadline_time_supported({'time':'11:59:59 p.m.','timezone':'Eastern'}, accepted))

    def test_required_rolling_white_paper_keeps_its_explicit_source_window(self):
        from scripts.submission_schedule import next_submission
        from copy import deepcopy
        text = ('White Papers are required for both the R&D Project Path and the Investment Fund Path. '
                'White Papers may be submitted at any time via grants.gov.')
        source = {'url': 'https://www.nist.gov/notice', 'sha256': 'source'}
        facts = e.extract_document_facts({'opportunity_id': 'fixture'}, [{'text': text, 'page': 10}], source,
                                       '2026-07-06T12:00:00Z', families={'deadlines'})
        self.assertEqual(len(facts), 1)
        self.assertTrue(facts[0]['rolling'])
        self.assertIn('at any time', facts[0]['rolling_citation']['quote'])
        entry = {'status': 'current', 'facts': facts, 'document': source,
                 'deadline_extractor_identity': e.DEADLINE_EXTRACTOR_IDENTITY, 'checked_at': '2026-07-06T12:00:00Z'}
        output = e.merge_document_entry({'opportunity_id': 'fixture', 'close_date': '2026-09-15'}, deepcopy(entry))
        selected = next_submission(output, '2026-09-07')
        self.assertEqual((selected['date'], selected['access']), ('2026-09-15', 'open'))
        self.assertTrue(selected['prerequisites'][0]['required'])
        # Unrelated applicants' rolling instructions do not fill a white-paper
        # date: the complete matching subject is required.
        unrelated = native('<p>White papers are required. Applications may be submitted at any time.</p>')
        self.assertFalse(any(f.get('rolling') for f in unrelated))

    def test_hypothetical_webinar_guidance_does_not_create_a_submission_stage(self):
        text = ('We typically hold it after the initial NOFO release but before the due date for '
                'concept papers or the application, if concept papers are not required. '
                'Attendance is not mandatory and will not positively or negatively impact the overall review.')
        self.assertEqual(native('<p>' + text + '</p>'), [])
        self.assertEqual([(f['deadline_kind'], f['required']) for f in native(
            '<p>Concept papers are not required.</p><p>' + text + '</p>')], [('concept_paper', False)])

    def test_nsf_related_program_requirements_do_not_enter_the_current_notice(self):
        from copy import deepcopy
        html = ('<h2>Submission requirements</h2><p>A concept paper is required.</p>'
                '<h2>Additional program resources</h2><p>Historically Black Colleges and Universities - '
                'Excellence in Research: Letters of Intent are required and are due by 5 p.m. '
                "submitter's local time on the Second Thursday in July.</p>")
        containers, _ = e.extract_html_sections(html.encode())
        source = {'url': 'https://www.nsf.gov/funding/opportunities/example', 'sha256': 'source'}
        facts = e.extract_document_facts({'opportunity_id': 'fixture'}, containers, source, '2026-07-06T12:00:00Z')
        self.assertEqual([(f['deadline_kind'], f['required']) for f in facts if f['type'] == 'submission_requirement'],
                         [('concept_paper', True)])
        other = containers[-1]
        old = e.make_fact('fixture', 'submission_requirement', 'Letter of intent requirement', None,
            'Submission date not established', e.citation_for(other, source, 0, len(other['text']), '2026-07-06T12:00:00Z'),
            deadline_kind='letter_of_intent', required=True)
        entry = {'status': 'current', 'document': source, 'facts': [old], 'checked_at': '2026-07-06T12:00:00Z',
                 'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
        original = deepcopy(entry)
        e.quarantine_legacy_facts({'opportunity_id': 'fixture'}, {}, entry, None)
        self.assertEqual(entry['facts'], [])
        self.assertEqual(entry['checked_at'], original['checked_at'])

    def test_current_and_pending_support_form_is_not_a_concept_paper_stage(self):
        from copy import deepcopy
        text = ('Every Covered Individual at the applicant and subrecipient levels must submit a CPS Common Form. '
                'Use SciENcv to produce a DOE-compliant PDF version of the CPS Common Form.')
        self.assertEqual(native('<p>' + text + '</p>'), [])
        self.assertIsNone(schedule.stage_for('CPS Common Form'))
        self.assertIsNone(schedule.preliminary_requirement(text, 'concept paper'))
        for subject in ('CP', 'CPs', 'concept paper', 'Concept Papers'):
            found = native(f'<p>{subject} are required.</p>')
            self.assertEqual([(f['deadline_kind'], f['required']) for f in found], [('concept_paper', True)])
        # A version upgrade removes this false legacy prerequisite locally
        # without advancing the old source-check receipt.
        source = {'url': 'https://www.energy.gov/notice', 'sha256': 'source'}
        old = e.make_fact('fixture', 'submission_requirement', 'Concept paper requirement', None,
            'Submission date not established', {'document_url': source['url'], 'sha256': 'source',
            'quote': text, 'extracted_at': '2026-07-06T12:00:00Z'},
            deadline_kind='concept_paper', required=True)
        entry = {'status': 'current', 'document': source, 'facts': [old], 'checked_at': '2026-07-06T12:00:00Z',
                 'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'prior'}}
        original = deepcopy(entry)
        e.quarantine_legacy_facts({'opportunity_id': 'fixture'}, {}, entry, None)
        self.assertEqual(entry['facts'], [])
        self.assertEqual(entry['checked_at'], original['checked_at'])
        self.assertEqual(entry['document'], original['document'])

    def test_current_cover_fields_recover_owned_dates_without_questions_or_webinars(self):
        import json
        from pathlib import Path
        from copy import deepcopy
        from scripts.notice_structure_cache import StructureCache
        import tempfile
        cases = json.loads((Path(__file__).parent / 'fixtures/parsing/local-cover-fields.json').read_bytes())['cases']
        for case in cases:
            with self.subTest(opportunity_id=case['opportunity_id']):
                old = case['legacy_fact']
                citation = old['citation']
                container = {'text': citation['quote'], 'page': citation.get('page'), 'section': citation.get('section')}
                facts = e.extract_deadlines(case['opportunity_id'], [container], case['source'], case['source_checked_at'])
                expected = sorted((r['kind'], r['date'], r['time']) for r in case['expected'])
                self.assertEqual(sorted((f['deadline_kind'], f['date'], f['time']) for f in facts if f['type'] == 'deadline'), expected)
                record = {'opportunity_id': case['opportunity_id']}
                entry = {'document': case['source'], 'checked_at': case['source_checked_at'], 'facts': [deepcopy(old)],
                         'parser_dependencies': {**e.parser_dependencies(), 'deadlines': 'old'}, 'review_queue': []}
                with tempfile.TemporaryDirectory() as directory:
                    e.quarantine_legacy_facts(record, {'url': case['source']['url']}, entry, StructureCache(directory))
                self.assertEqual(sorted((f['deadline_kind'], f['date'], f['time']) for f in entry['facts'] if f['type'] == 'deadline'), expected)
                self.assertEqual(entry['checked_at'], case['source_checked_at'])
                self.assertTrue(entry['parser_pending'])

    def test_synopsis_unknown_is_not_optional_and_other_requirements_do_not_leak(self):
        for text, expected in [('A concept paper is discussed. A budget is required.', None),
                               ('A concept paper is optional.', False),
                               ('Submit the required concept paper.', True),
                               ('You must submit a concept paper.', True)]:
            with self.subTest(text=text):
                self.assertIs(schedule.preliminary_requirement(text, 'concept paper'), expected)

    def test_owned_shared_and_local_clock_conflict_withholds_only_time(self):
        for local, shared, expected in [('5:00 PM ET', '5 PM Eastern Time', '5 PM'),
                                        ('4:00 PM ET', '5 PM Eastern Time', None)]:
            html = ('<h2>Key Dates</h2><div class="heading4" data-element-id="one" data-section-code="KD">Application Due Date(s)</div>'
                '<div data-element-id="one" data-section-code="KD" data-element-has-label="true">'
                f'<p>May 1, 2027 by {local}</p><p>All applications are due by {shared}.</p></div>')
            containers, _ = e.extract_html_sections(html.encode())
            review = []
            facts = schedule.extract_native(e, 'fixture', containers,
                {'url': 'https://grants.nih.gov/notice', 'sha256': 'fixture'}, 'fixed', review)
            self.assertEqual([f['date'] for f in facts], ['2027-05-01'])
            self.assertEqual(facts[0]['time'], expected)
            self.assertEqual(bool(review), expected is None)

    def test_nih_recurring_fields_preserve_application_class_and_clock(self):
        html = '''<h2>Key Dates</h2><div class="heading4" data-element-id="one" data-section-code="KD">Application Due Date(s)</div>
        <div data-element-id="one" data-section-code="KD" data-element-has-label="true">
        <p>October 21, 2025, by 11:59 PM Eastern Time</p><p>October 20, 2026, by 11:59 PM Eastern Time</p>
        <p>October 19, 2027, by 11:59 PM Eastern Time.</p>
        <p>Resubmissions ONLY Application Due Date(s): May 19, 2026; May 18, 2027; May 16, 2028 by 11:59 PM Eastern Time.</p></div>
        <div class="heading4" data-element-id="two" data-section-code="KD">Earliest Start Date</div>
        <div data-element-id="two" data-section-code="KD" data-element-has-label="true"><p>May 1, 2029</p></div>'''
        facts = native(html)
        self.assertEqual([(f['date'], f['application_class']) for f in facts],
            [('2025-10-21', 'new'), ('2026-10-20', 'new'), ('2027-10-19', 'new'),
             ('2026-05-19', 'resubmission'), ('2027-05-18', 'resubmission'), ('2028-05-16', 'resubmission')])
        self.assertTrue(all(f['time'] == '11:59 PM' and f['timezone'] == 'Eastern' for f in facts))

    def test_missing_table_value_does_not_shift_stage_or_requirement(self):
        facts = native('''<h2>Submission deadlines</h2><table><tr><th>Stage</th><th>Required</th><th>Deadline</th></tr>
            <tr><td>CP</td><td>Yes</td><td>TBD</td></tr><tr><td>FA</td><td></td><td>May 1, 2027</td></tr></table>''')
        self.assertEqual([(f['deadline_kind'], f['date'], f['required']) for f in facts],
                         [('concept_paper', None, True), ('application', '2027-05-01', None)])
        self.assertEqual(facts[0]['type'], 'submission_requirement')

    def test_supported_permission_and_optional_whitepaper_are_scoped(self):
        facts = native('<p>Full Proposal Deadline: May 1, 2027</p>'
            '<p>Upload the Concept Outline PO Concurrence email that indicates PO permission to submit a full proposal.</p>'
            '<p>White Paper Submission Deadline: April 1, 2027</p>'
            '<p>Although not required, white papers are strongly encouraged.</p>', 'https://www.nsf.gov/notice')
        self.assertTrue(next(f for f in facts if f['deadline_kind'] == 'application')['invitation_required'])
        self.assertIs(next(f for f in facts if f['deadline_kind'] == 'white_paper')['required'], False)
        self.assertIs(schedule.preliminary_requirement('Although not required, white papers are strongly encouraged.', 'white paper'), False)
        without = native('<p>Full Proposal Deadline: May 1, 2027</p><p>Contact a Program Officer to discuss research.</p>',
                         'https://www.nsf.gov/notice')
        self.assertIsNone(without[0]['invitation_required'])
        undated = native('<p>White Papers are required for both the R&amp;D Project Path and the Investment Fund Path.</p>')
        self.assertEqual([(f['type'], f['deadline_kind'], f['date'], f['required']) for f in undated],
                         [('submission_requirement', 'white_paper', None, True)])

    def test_exchange_notice_submission_section_has_two_owned_stages(self):
        facts = native('''<p>The required Concept Paper due date is 10/09/2026 at 5PM ET. Full Application due date is 12/01/2026 at 5PM ET.</p>
            <h2>Documents</h2><p>Last Updated: September 4, 2026 11:33 AM ET</p>
            <h2>Submission Deadlines</h2><p>Concept Paper Submission Deadline: 10/9/2026 5:00 PM ET</p>
            <p>Full Application Submission Deadline: 12/1/2026 5:00 PM ET</p>''', 'https://eere-exchange.energy.gov/#FoaIdfixture')
        self.assertEqual([(f['deadline_kind'], f['date'], f['time']) for f in facts],
                         [('concept_paper', '2026-10-09', '5:00 PM'), ('application', '2026-12-01', '5:00 PM')])

    def test_cdmrp_clock_precedes_owned_date_and_review_dates_are_excluded(self):
        text = ('Submission and Review Dates and Times\n'
            '• Pre-Application (Preproposal) Submission Deadline: 5:00 p.m. Eastern Time (ET),\nJuly 13, 2026\n'
            '• Invitation to Submit an Application: August 19, 2026\n'
            '• Application Submission Deadline: 11:59 p.m. ET, October 14, 2026\n'
            '• End of Application Verification Period: 5:00 p.m. ET, October 20, 2026')
        facts = schedule.extract_native(e, 'fixture', [{'page': 4, 'text': text}], {'url': 'https://example.gov/notice.pdf', 'sha256': 'fixture'}, 'fixed')
        self.assertEqual([(f['deadline_kind'], f['date']) for f in facts], [('preproposal', '2026-07-13'), ('application', '2026-10-14')])
        self.assertTrue(all(f['time'] and f['timezone'] for f in facts))
        # Public legacy quotations flatten PDF line breaks but retain actual
        # bullets. Those independent fields must keep their owned clocks.
        quoted = schedule.extract_native(e, 'fixture', [{'page': 4, 'text': text.replace('\n', ' ')}],
            {'url': 'https://example.gov/notice.pdf', 'sha256': 'fixture'}, 'fixed')
        self.assertEqual([(f['deadline_kind'], f['date'], f['time']) for f in quoted],
                         [(f['deadline_kind'], f['date'], f['time']) for f in facts])

    def test_cdc_required_loi_and_application_fields_retain_local_clock(self):
        text = ('Submission requirements and deadlines\nRequired letter of intent\nDue on September 15, 2026.\n'
            'You must submit a letter of intent to apply.\nApplication\nDue on November 5, 2026 at 11:59 p.m. ET.')
        facts = schedule.extract_native(e, 'fixture', [{'page': 45, 'text': text}], {'url': 'https://example.gov/notice.pdf', 'sha256': 'fixture'}, 'fixed')
        self.assertEqual([(f['deadline_kind'], f['date'], f['required']) for f in facts],
                         [('letter_of_intent', '2026-09-15', True), ('application', '2026-11-05', None)])
        self.assertIsNone(facts[0]['time'])
        self.assertEqual(facts[1]['time'], '11:59 p.m.')


if __name__ == '__main__':
    unittest.main()
