"""Claim retirement may remove evidence, never create new scientific support."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import team_maintenance as maintenance
from tools.offline_ai import config


class ClaimRetirementRecovery(unittest.TestCase):
    def fixture(self):
        value = json.loads(Path('tests/fixtures/claim_retirement_recovery.json').read_bytes())
        return value['model'], value['candidates'], value['registry'], value['recovery']

    def test_only_reviewed_subgraphs_restore_and_original_provenance_remains(self):
        model, candidates, registry, recovery = self.fixture()
        before = copy.deepcopy(model)
        with patch('requests.post', side_effect=AssertionError('No provider during evidence recovery')):
            results = maintenance.restore_after_claim_retirement(model, candidates, registry, recovery)
        self.assertEqual(sum(r['state'] == 'restored_from_retained_evidence' for r in results), 3)
        self.assertEqual(sum(r['state'] == 'withheld_after_claim_retirement' for r in results), 1)
        for row, original in zip(model['opportunities'], before['opportunities']):
            if row['id'] == '357433':
                self.assertEqual(row, original)
                continue
            self.assertEqual(row['review_state'], 'proposed')
            for field in ('pipeline_hash', 'generator_version', 'registry_generation_at_generation',
                          'claims_generation_at_generation', 'recovery_proof', 'objective'):
                self.assertEqual(row.get(field), original.get(field))
            old_edges = {(role['id'], ref['claim_id']): ref
                         for role in original['roles'] for ref in role['claim_refs']}
            retired = set(row['claim_retirement_proof']['removed_claim_ids'])
            for role in row['roles']:
                for ref in role['claim_refs']:
                    self.assertNotIn(ref['claim_id'], retired)
                    self.assertEqual(ref, old_edges[(role['id'], ref['claim_id'])])
            self.assertEqual(row['claim_retirement_proof']['provider_requests'], 0)
            self.assertEqual(maintenance.retained_decision_hash(row),
                             recovery['claim_retirement_recovery']['decisions'][row['id']]['reassembled_decision_hash'])
        changed_team = next(r for r in model['opportunities'] if r['id'] == '363095')
        self.assertEqual([m['faculty_id'] for m in changed_team['members']], ['urh-000025', 'urh-000111'])
        self.assertTrue(changed_team['missing_skills'])
        once = copy.deepcopy(model)
        maintenance.restore_after_claim_retirement(model, candidates, registry, recovery)
        self.assertEqual(model, once)

    def test_changed_evidence_or_unreviewed_deletion_fails_closed(self):
        faults = ('source', 'quote', 'remaining_revision', 'remaining_hash', 'remaining_eligibility',
                  'retired_now_active', 'unknown_removal', 'omitted_removal', 'registry', 'graph',
                  'science', 'pipeline', 'result_hash', 'missing_review')
        for fault in faults:
            with self.subTest(fault=fault):
                model, candidates, registry, recovery = self.fixture()
                model['opportunities'] = [r for r in model['opportunities'] if r['id'] == '344592:ab-0013']
                row = model['opportunities'][0]
                review = recovery['claim_retirement_recovery']['decisions'][row['id']]
                scope = next(s for s in candidates if s['id'] == row['id'])
                ref = next(ref for role in row['roles'] for ref in role['claim_refs']
                           if ref['claim_id'] not in review['removed_claim_ids'])
                person = next(p for p in registry['researchers'] if p['researcher_id'] == ref['researcher_id'])
                claim = next(c for c in person['claims'] if c['claim_id'] == ref['claim_id'])
                if fault == 'source': scope['source_fingerprint'] = 'later source'
                elif fault == 'quote': scope['text'] = 'No original role quote remains.'
                elif fault == 'remaining_revision': claim['revision'] += 1
                elif fault == 'remaining_hash': claim['material_hash'] = 'different claim'
                elif fault == 'remaining_eligibility': person['auto_proposable'] = False
                elif fault == 'retired_now_active':
                    for p in registry['researchers']:
                        for c in p['claims']:
                            if c['claim_id'] in review['removed_claim_ids']: c['status'] = 'active'
                elif fault == 'unknown_removal': review['removed_claim_ids'].append('nonexistent')
                elif fault == 'omitted_removal': review['removed_claim_ids'] = []
                elif fault == 'registry': registry['registry_generation'] = 'different generation'
                elif fault == 'graph': row['roles'][0]['claim_refs'][0]['coverage'] = 'adjacent'
                elif fault == 'science': recovery['scientific_contract'] = 'different contract'
                elif fault == 'pipeline': row['pipeline_hash'] = 'unverified model'
                elif fault == 'result_hash': review['reassembled_decision_hash'] = 'unreviewed team'
                elif fault == 'missing_review': recovery['claim_retirement_recovery']['decisions'].clear()
                before = copy.deepcopy(model)
                maintenance.restore_after_claim_retirement(model, candidates, registry, recovery)
                self.assertEqual(model, before)

    def test_expected_team_cannot_be_silently_replaced_by_an_insufficient_result(self):
        model, candidates, registry, recovery = self.fixture()
        model['opportunities'] = [r for r in model['opportunities'] if r['id'] == '357433']
        recovery['claim_retirement_recovery']['decisions']['357433']['reassembled_decision_hash'] = 'expected team'
        before = copy.deepcopy(model)
        results = maintenance.restore_after_claim_retirement(model, candidates, registry, recovery)
        self.assertEqual(results[0]['state'], 'pending')
        self.assertEqual(model, before)

    def test_existing_recovery_entrypoint_includes_retirement_results_without_duplicates(self):
        model, candidates, registry, recovery = self.fixture()
        settings = config()
        settings['targeted_team_recovery']['claim_retirement_recovery'] = recovery['claim_retirement_recovery']
        with patch.object(maintenance, 'config', return_value=settings):
            results = maintenance.restore_proven_teams(model, candidates, registry)
        self.assertEqual(len(results), 4)
        self.assertEqual(sum(r['state'] == 'restored_from_retained_evidence' for r in results), 3)
        self.assertEqual(next(r for r in results if r['scope_id'] == '357433')['state'], 'withheld_after_claim_retirement')


if __name__ == '__main__':
    unittest.main()
