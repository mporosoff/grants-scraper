import copy
import unittest

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
        claim = {'claim_id': f'urh-990001-c00{number}', 'revision': number, 'status': 'active',
                 'label': f'Synthetic catalysis method {number}', 'category': 'Chemistry',
                 'categories': ['Chemistry'], 'type': 'method',
                 'evidence': f'Synthetic measured catalytic activity in experiment {number}.',
                 'source_urls': ['https://example.edu/synthetic-profile'], 'evidence_level': 'direct',
                 'verified_on': '2026-09-22', 'legacy_claim_ids': [f'synthetic-claim-{number}'],
                 'evidence_records': [observation()], 'history': [{'retained': 'synthetic earlier wording'}]}
        claim['material_hash'] = audited.material_claim_hash(claim)
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
