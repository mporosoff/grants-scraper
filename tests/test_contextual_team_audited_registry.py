import copy
import unittest
from unittest.mock import patch

from scripts import researcher_registry as legacy
from tools import contextual_team_audited_registry as audited


def observation(url='https://example.edu/synthetic-profile'):
    return {'form': 'paraphrase', 'url': url, 'source_type': 'official_profile',
            'response_sha256': 'a' * 64, 'text_sha256': 'b' * 64,
            'locator': 'Synthetic research section', 'reviewed_on': '2026-09-22',
            'retrieved_at': '2026-09-22T12:00:00Z'}


def registry_fixture():
    claims = []
    for number in (1, 2):
        claim = {'claim_id': f'urh-990001-c00{number}', 'revision': number + 1, 'status': 'active',
                 'label': f'Synthetic catalysis method {number}', 'category': 'Chemistry',
                 'categories': ['Chemistry'], 'type': 'method',
                 'evidence': f'Synthetic measured catalytic activity in experiment {number}.',
                 'source_urls': ['https://example.edu/synthetic-profile'], 'evidence_level': 'direct',
                 'verified_on': '2026-09-22', 'legacy_claim_ids': [f'synthetic-claim-{number}'],
                 'evidence_records': [observation()]}
        claim['material_hash'] = audited.material_claim_hash(claim)
        prior = {key: copy.deepcopy(item) for key, item in claim.items() if key != 'evidence_records'}
        prior['revision'] = number
        prior['evidence'] = f'Synthetic earlier evidence for experiment {number}.'
        prior['material_hash'] = audited.material_claim_hash(prior)
        claim['history'] = [prior]
        claims.append(claim)
    person = {'researcher_id': 'urh-990001', 'display_name': 'Synthetic Person',
              'sort_name': 'Person, Synthetic', 'legacy_ids': ['synthetic-person'], 'aliases': [],
              'home_unit': 'Synthetic Chemistry', 'relationship': 'hajim_core_faculty',
              'pool_visibility': 'department', 'status': 'active', 'auto_proposable': True,
              'pool_assignment': 'standby', 'orcid_id': '',
              'research_summary': 'Synthetic measurements of catalytic activity.',
              'summary_evidence': [observation()], 'source_urls': ['https://example.edu/synthetic-profile'],
              'source_checked_date': '2026-09-22', 'official_interests': ['Synthetic catalysis'],
              'claims': claims}
    value = {'schema_version': 3, 'researchers': [person]}
    value['registry_generation'] = legacy.registry_generation(value)
    return value


class AuditedRegistryStageTests(unittest.TestCase):
    def rehash(self, value):
        for person in value['researchers']:
            for claim in person['claims']:
                for prior in claim.get('history', []):
                    prior['material_hash'] = audited.material_claim_hash(prior)
                claim['material_hash'] = audited.material_claim_hash(claim)
        value['registry_generation'] = legacy.registry_generation(value)
        return value

    def extended_fixture(self):
        value = registry_fixture()
        value['researchers'][0].update(
            institution={'name': 'Synthetic University', 'ror_id': ''},
            external_ids={'openalex': ''}, metrics={'openalex_works_count': None},
            source_audit={'version': 'full-profile-repair-v1', 'baseline_material': 'c' * 64,
                          'disposition': 'corrected', 'issues': 'Synthetic source correction', 'limitations': 'Synthetic limitation',
                          'reviewed_on': '2026-09-22'})
        return self.rehash(value)

    def test_rehashed_unknown_fields_reject_across_the_complete_staged_registry_family(self):
        for location in ('registry', 'person', 'claim', 'retired_claim', 'history',
                         'claim_observation', 'summary_observation', 'source_audit',
                         'institution', 'external_ids', 'metrics'):
            for key in ('provider_cache', 'private_note'):
                with self.subTest(location=location, key=key):
                    value = self.extended_fixture(); person = value['researchers'][0]
                    claim = person['claims'][0]
                    if location == 'retired_claim': claim['status'] = 'retired'
                    target = {'registry': value, 'person': person, 'claim': claim, 'retired_claim': claim,
                              'history': claim['history'][0], 'claim_observation': claim['evidence_records'][0],
                              'summary_observation': person['summary_evidence'][0],
                              **{name: person[name] for name in ('source_audit', 'institution', 'external_ids', 'metrics')}}[location]
                    target[key] = {'secret': 'SYNTHETIC_PRIVATE_MARKER'}
                    self.rehash(value); original = legacy.canonical_bytes(value)
                    for operation in (audited.validate, audited.directory, audited.faculty, audited.matching_profiles):
                        with self.assertRaisesRegex(ValueError, 'unsupported fields'):
                            operation(value)
                    self.assertEqual(legacy.canonical_bytes(value), original)

    def test_nested_private_objects_cannot_hide_in_legacy_coerced_text_or_lists(self):
        for location in ('summary', 'alias', 'interest', 'claim_evidence', 'category',
                         'observation_locator', 'history_evidence', 'audit_limitations',
                         'external_id', 'works_count'):
            with self.subTest(location=location):
                value = self.extended_fixture(); person = value['researchers'][0]; claim = person['claims'][0]
                private = {'private_note': 'SYNTHETIC_PRIVATE_MARKER'}
                if location == 'summary': person['research_summary'] = private
                elif location == 'alias': person['aliases'] = [private]
                elif location == 'interest': person['official_interests'] = [private]
                elif location == 'claim_evidence': claim['evidence'] = private
                elif location == 'category': claim['categories'] = ['Chemistry', private]
                elif location == 'observation_locator': claim['evidence_records'][0]['locator'] = private
                elif location == 'history_evidence': claim['history'][0]['evidence'] = private
                elif location == 'audit_limitations': person['source_audit']['limitations'] = private
                elif location == 'external_id': person['external_ids']['openalex'] = private
                else: person['metrics']['openalex_works_count'] = private
                self.rehash(value)
                with self.assertRaises(ValueError): audited.validate(value)

    def test_source_audit_requires_compact_authored_metadata_not_source_bodies(self):
        cases = [('baseline_material', 'Synthetic raw email ' * 60000),
                 ('baseline_material', 'c' * 63), ('version', 'unsupported-audit'),
                 ('disposition', 'approved'), ('reviewed_on', '2026-02-29'),
                 ('reviewed_on', '2026-09-22\n'), ('issues', ''),
                 ('issues', 'x' * 501), ('limitations', 'x' * 501),
                 ('issues', ' ' * 501 + 'Short'), ('limitations', {'private': 'text'})]
        for key, bad in cases:
            with self.subTest(key=key, value_type=type(bad).__name__):
                value = self.extended_fixture()
                value['researchers'][0]['source_audit'][key] = bad
                self.rehash(value); original = legacy.canonical_bytes(value)
                for operation in (audited.validate, audited.directory, audited.faculty, audited.matching_profiles):
                    with self.assertRaises(ValueError): operation(value)
                self.assertEqual(legacy.canonical_bytes(value), original)

    def test_every_history_snapshot_uses_all_ordinary_claim_semantics(self):
        cases = [('status', 'unreviewed'), ('evidence_level', 'inferred'),
                 ('verified_on', '2026-02-29'), ('source_urls', ['http://example.edu/profile']),
                 ('source_urls', ['https://']), ('label', 'x' * 181), ('category', 'x' * 141),
                 ('type', 'x' * 81), ('evidence', 'x' * 501), ('evidence', ' ' * 501 + 'x'),
                 ('categories', []), ('categories', ['Chemistry', 'Chemistry']),
                 ('categories', ['Physics']), ('categories', ['Chemistry'] * 13),
                 ('legacy_claim_ids', ['duplicate', 'DUPLICATE']),
                 ('legacy_claim_ids', ['noncanonical ']), ('legacy_claim_ids', ['x' * 81]),
                 ('retired_on', 'invalid')]
        for key, bad in cases:
            with self.subTest(key=key):
                value = self.extended_fixture()
                value['researchers'][0]['claims'][0]['history'][0][key] = bad
                self.rehash(value); original = legacy.canonical_bytes(value)
                for operation in (audited.validate, audited.directory, audited.faculty, audited.matching_profiles):
                    with self.assertRaises(ValueError): operation(value)
                self.assertEqual(legacy.canonical_bytes(value), original)

    def test_history_revisions_are_older_unique_and_keep_reused_legacy_ids(self):
        good = self.extended_fixture(); claim = good['researchers'][0]['claims'][0]
        claim['revision'] = 4
        prior = copy.deepcopy(claim['history'][0]); prior['revision'] = 3
        claim['history'].append(prior); self.rehash(good)
        original = copy.deepcopy(good)
        self.assertIs(audited.validate(good), good)
        self.assertEqual(good, original)
        for revision in (1, 4, 5):
            value = copy.deepcopy(good)
            value['researchers'][0]['claims'][0]['history'][1]['revision'] = revision
            self.rehash(value)
            with self.assertRaisesRegex(ValueError, 'historical revisions'): audited.validate(value)

    def test_other_exported_scalars_and_lists_are_bounded_and_well_typed(self):
        cases = [('legacy_ids', ['x' * 121]), ('aliases', ['x' * 121]),
                 ('official_interests', ['x' * 501]), ('official_interests', ['x'] * 65),
                 ('source_urls', ['https://example.edu/' + 'x' * 500]),
                 ('source_urls', ['https://example.edu/'] * 65),
                 ('research_summary', ' ' * 1201 + 'Short'),
                 ('external_ids', {'openalex': 'SYNTHETIC_PRIVATE_EMAIL'}),
                 ('external_ids', {'openalex': 'https://unrelated.example/A123'}),
                 ('metrics', {'openalex_works_count': True}),
                 ('metrics', {'openalex_works_count': 2**53}),
                 ('institution', {'name': ' ' * 301, 'ror_id': ''})]
        for key, bad in cases:
            with self.subTest(key=key):
                value = self.extended_fixture(); value['researchers'][0][key] = bad
                self.rehash(value)
                with self.assertRaises(ValueError): audited.validate(value)
        for location in ('current', 'history'):
            for bad in ({'retirement_reason': 'x' * 501},
                        {'retired_on': '2026-02-29', 'retirement_reason': 'Synthetic reason'},
                        {'retired_on': '2026-09-22', 'retirement_reason': ''}):
                with self.subTest(location=location, metadata=tuple(bad)):
                    value = self.extended_fixture(); claim = value['researchers'][0]['claims'][0]
                    target = claim if location == 'current' else claim['history'][0]
                    target.update(status='retired', **bad); self.rehash(value)
                    with self.assertRaises(ValueError): audited.validate(value)

    def test_legitimate_boundary_values_and_historical_observations_stay_exact(self):
        value = self.extended_fixture(); person = value['researchers'][0]
        person['source_audit'].update(issues='x' * 500, limitations='', disposition='unresolved')
        person['official_interests'] = ['x' * 500]
        person['external_ids']['openalex'] = 'https://openalex.org/A1234567890'
        person['metrics']['openalex_works_count'] = 2**53 - 1
        claim = person['claims'][0]
        claim['history'][0].update(evidence='x' * 500, evidence_records=[observation()])
        claim['source_urls'] = ['https://example.edu/synthetic-profile ']
        self.rehash(value); original = copy.deepcopy(value)
        self.assertIs(audited.validate(value), value)
        self.assertEqual(value, original)
        self.assertEqual(audited.matching_profiles(value)[0]['claims'][0]['source_urls'], claim['source_urls'])

    def test_urls_are_real_https_sources_across_all_exported_locations(self):
        for location in ('person', 'claim', 'history', 'claim_observation', 'summary_observation'):
            for bad in ('https://', 'https://@example.edu/', 'https://user:secret@example.edu/',
                        'https://example.edu:99999/', 'https://example.edu/path with space',
                        'https://example.edu\\synthetic'):
                with self.subTest(location=location, url=bad):
                    value = self.extended_fixture(); person = value['researchers'][0]; claim = person['claims'][0]
                    if location == 'person': person['source_urls'] = [bad]
                    elif location == 'claim': claim['source_urls'] = [bad]
                    elif location == 'history': claim['history'][0]['source_urls'] = [bad]
                    elif location == 'claim_observation': claim['evidence_records'][0]['url'] = bad
                    else: person['summary_evidence'][0]['url'] = bad
                    self.rehash(value)
                    with self.assertRaises(ValueError): audited.validate(value)

    def test_revision_identity_cannot_round_when_exported_to_javascript(self):
        value = self.extended_fixture(); claim = value['researchers'][0]['claims'][0]
        claim['revision'] = 2**53 - 1; claim['history'][0]['revision'] = 2**53 - 2
        self.rehash(value); original = copy.deepcopy(value)
        self.assertIs(audited.validate(value), value)
        self.assertEqual(audited.directory(value)['researchers'][0]['claims'][0]['revision'], 2**53 - 1)
        self.assertEqual(value, original)
        for location in ('current', 'history'):
            for bad in (2**53, 2**53 + 1, True):
                with self.subTest(location=location, revision=bad):
                    invalid = copy.deepcopy(value); current = invalid['researchers'][0]['claims'][0]
                    target = current if location == 'current' else current['history'][0]
                    target['revision'] = bad; self.rehash(invalid)
                    with self.assertRaisesRegex(ValueError, 'safe integer'): audited.validate(invalid)

    def test_legitimate_history_retirement_audit_and_summary_are_preserved_not_stripped(self):
        value = self.extended_fixture(); person = value['researchers'][0]
        retired = person['claims'][1]
        retired.update(status='retired', retired_on='2026-09-22', retirement_reason='Synthetic source correction')
        self.rehash(value); original = copy.deepcopy(value)
        self.assertIs(audited.validate(value), value)
        self.assertEqual(value, original)
        profile = audited.matching_profiles(value)[0]
        self.assertEqual(profile['claims'], [{key: item for key, item in person['claims'][0].items() if key != 'history'}])
        self.assertEqual(audited.directory(value)['researchers'][0]['summary_evidence'], person['summary_evidence'])
        self.assertEqual(len(audited.directory(value)['researchers'][0]['claims']), 2)
        self.assertEqual(person['claims'][0]['history'], original['researchers'][0]['claims'][0]['history'])

    def timestamp_fixture(self, location, timestamp):
        value = registry_fixture()
        person = value['researchers'][0]
        records = person['summary_evidence'] if location == 'summary' else person['claims'][0]['evidence_records']
        records[0]['retrieved_at'] = timestamp
        for claim in person['claims']:
            claim['material_hash'] = audited.material_claim_hash(claim)
        value['registry_generation'] = legacy.registry_generation(value)
        return value

    def test_complete_timezone_timestamps_keep_exact_evidence_and_registry_identity(self):
        for location in ('summary', 'claim'):
            for timestamp in ('2026-09-22T12:00:00Z', '2026-09-22T12:00:00+00:00',
                              '2026-09-22T12:00:00.123456+05:30', '2024-02-29T23:59:59.1-04:00'):
                with self.subTest(location=location, timestamp=timestamp):
                    value = self.timestamp_fixture(location, timestamp)
                    original = legacy.canonical_bytes(value)
                    self.assertIs(audited.validate(value), value)
                    directory = audited.directory(value)['researchers'][0]
                    faculty = audited.faculty(value)[0]
                    profile = audited.matching_profiles(value)[0]
                    if location == 'summary':
                        records = [target['summary_evidence'] for target in (directory, faculty, profile)]
                    else:
                        records = [directory['claims'][0]['evidence_records'],
                                   faculty['terms'][0]['evidence_records'], profile['claims'][0]['evidence_records']]
                    self.assertTrue(all(record[0]['retrieved_at'] == timestamp for record in records))
                    self.assertEqual(legacy.canonical_bytes(value), original)

    def test_invalid_retrieval_timestamps_reject_even_with_correct_material_and_generation_hashes(self):
        invalid = ('2026-99-99Tbroken', '2026-02-29T12:00:00Z', '2026-04-31T12:00:00Z',
                   '2026-09-22T24:00:00Z', '2026-09-22T12:60:00Z', '2026-09-22T12:00:60Z',
                   '2026-09-22T12:00:00+24:00', '2026-09-22T12:00:00+01:60',
                   '2026-09-22T12:00:00Ztrailing', '2026-09-22T12:00:00Z\n',
                   '2026-09-22T12:00:00', '2026-09-22T', '', None, 20260922)
        for location in ('summary', 'claim'):
            for timestamp in invalid:
                with self.subTest(location=location, timestamp=timestamp):
                    value = self.timestamp_fixture(location, timestamp)
                    original = legacy.canonical_bytes(value)
                    for operation in (audited.validate, audited.directory, audited.faculty, audited.matching_profiles):
                        with self.assertRaisesRegex(ValueError, 'invalid retrieval timestamp'):
                            operation(value)
                    self.assertEqual(legacy.canonical_bytes(value), original)

    def test_clock_and_offset_bounds_reject_before_a_permissive_datetime_parser(self):
        for location in ('summary', 'claim'):
            for timestamp in ('2026-09-22T24:00:00Z', '2026-09-22T24:00:00.000+00:00',
                              '2026-09-22T12:60:00Z', '2026-09-22T12:00:60Z',
                              '2026-09-22T12:00:00+24:00', '2026-09-22T12:00:00-24:00',
                              '2026-09-22T12:00:00+01:60'):
                with self.subTest(location=location, timestamp=timestamp):
                    value = self.timestamp_fixture(location, timestamp)
                    # Parser normalization rules differ across Python versions.
                    # Application bounds must reject before any parser accepts it.
                    with patch.object(audited, 'datetime') as parser:
                        with self.assertRaisesRegex(ValueError, 'invalid retrieval timestamp'):
                            audited.validate(value)
                        self.assertNotIn(timestamp, [call.args[0] for call in parser.fromisoformat.call_args_list])

    def test_audited_hash_accepts_original_identity_and_leaves_input_untouched(self):
        value = registry_fixture()
        before = copy.deepcopy(value)
        with self.assertRaisesRegex(ValueError, 'material_hash'):
            legacy.validate_registry(value)
        self.assertIs(audited.validate(value), value)
        self.assertEqual(value, before)
        claim = value['researchers'][0]['claims'][0]
        no_records = {key: item for key, item in claim.items() if key != 'evidence_records'}
        self.assertEqual(audited.material_claim_hash(no_records), legacy.material_claim_hash(no_records))

    def test_tampered_observation_claim_revision_and_owner_fail(self):
        for fault in ('material', 'generation', 'owner', 'duplicate', 'revision', 'form', 'url', 'date', 'hash'):
            with self.subTest(fault=fault):
                value = registry_fixture()
                person = value['researchers'][0]
                claim = person['claims'][0]
                if fault == 'material': claim['evidence'] += ' Changed.'
                elif fault == 'generation': person['research_summary'] += ' Changed.'
                elif fault == 'owner': claim['claim_id'] = 'urh-990002-c001'
                elif fault == 'duplicate': person['claims'].append(copy.deepcopy(claim))
                elif fault == 'revision': claim['revision'] = True
                elif fault == 'form': claim['evidence_records'][0]['form'] = 'unattributed'
                elif fault == 'url': claim['evidence_records'][0]['url'] = 'http://invalid.example'
                elif fault == 'date': claim['evidence_records'][0]['reviewed_on'] = '2026-99-99'
                else: claim['evidence_records'][0]['text_sha256'] = 'bad'
                # Independent structural checks must still reject when the outer
                # snapshot identity is correctly recomputed for the bad fixture.
                if fault != 'generation': value['registry_generation'] = legacy.registry_generation(value)
                with self.assertRaises(ValueError): audited.validate(value)

    def test_all_projections_keep_summary_claim_provenance_and_standby(self):
        value = registry_fixture()
        person = value['researchers'][0]
        directory = audited.directory(value)
        faculty = audited.faculty(value)[0]
        forward = audited.matching_profiles(value)[0]
        self.assertEqual(directory['counts']['pool_counts'], {'main': 0, 'standby': 1, 'unadmitted': 0})
        for projected in (directory['researchers'][0], faculty):
            self.assertEqual(projected['pool_state'], 'standby')
            self.assertEqual(projected['summary_evidence'], person['summary_evidence'])
            self.assertEqual(projected['research_summary'], person['research_summary'])
        for source, target in zip(person['claims'], directory['researchers'][0]['claims']):
            for key in ('claim_id', 'revision', 'status', 'evidence', 'evidence_records', 'verified_on'):
                self.assertEqual(target[key], source[key])
        self.assertEqual(faculty['terms'][0]['evidence_records'], person['claims'][0]['evidence_records'])
        self.assertEqual(forward['summary_evidence'], person['summary_evidence'])
        self.assertEqual(len(forward['claims']), 2)
        self.assertNotIn('history', forward['claims'][0])
        self.assertIn('history', person['claims'][0])
        directory['researchers'][0]['claims'][0]['evidence_records'][0]['locator'] = 'caller edit'
        self.assertEqual(person['claims'][0]['evidence_records'][0]['locator'], 'Synthetic research section')

    def test_retirement_and_ineligibility_are_not_upgraded_by_projection(self):
        value = registry_fixture()
        person = value['researchers'][0]
        person['claims'][1]['status'] = 'retired'
        person['claims'][1]['material_hash'] = audited.material_claim_hash(person['claims'][1])
        person.update(status='inactive', auto_proposable=False)
        value['registry_generation'] = legacy.registry_generation(value)
        self.assertEqual(audited.directory(value)['researchers'][0]['pool_state'], 'unadmitted')
        self.assertEqual(len(audited.faculty(value)[0]['terms']), 1)
        self.assertEqual(audited.matching_profiles(value), [])

    def test_forward_matching_retains_exact_evidence_without_changing_scores(self):
        profiles = audited.matching_profiles(registry_fixture())
        matches = {'faculty': {'Synthetic Person': {'researcher_id': 'urh-990001', 'score': 7}},
                   'multi_pi_suggestions': [{'unreviewed_score': 9}]}
        before = copy.deepcopy(matches)
        result = audited.preserve_forward_evidence(matches, profiles)
        self.assertEqual(result['faculty']['Synthetic Person']['score'], 7)
        self.assertEqual(result['faculty']['Synthetic Person']['claims'], profiles[0]['claims'])
        self.assertEqual(result['multi_pi_suggestions'], before['multi_pi_suggestions'])
        self.assertEqual(matches, before)
        matches['faculty']['Synthetic Person']['researcher_id'] = 'urh-990002'
        with self.assertRaises(ValueError): audited.preserve_forward_evidence(matches, profiles)
        with self.assertRaises(ValueError): audited.preserve_forward_evidence({'faculty': {}}, profiles)


if __name__ == '__main__':
    unittest.main()
