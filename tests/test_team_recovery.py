"""Previously published scientific decisions require exact evidence before restoration."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import build_opportunity_teams as teams
from tools import team_maintenance as maintenance
from tools.offline_ai import config


class RetainedTeamRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = json.loads(Path('config/opportunity_team_model.json').read_bytes())
        cls.registry = teams.load_registry()
        cls.candidates = teams.scopes()
        cls.key = '344592:ab-0013'

    def fixture(self):
        model = copy.deepcopy(self.model)
        model['opportunities'] = [row for row in model['opportunities'] if row['id'] == self.key]
        # Tests remain meaningful after the restored candidate is committed.
        row = model['opportunities'][0]
        row['review_state'] = 'needs_revalidation'
        row['revalidation_reason'] = 'The retained scientific decision contract cannot be established.'
        settings = config()
        settings['targeted_team_recovery']['published_decisions'][self.key] = maintenance.retained_decision_hash(row)
        return model, copy.deepcopy(self.candidates), copy.deepcopy(self.registry), settings

    def test_exact_published_graph_restores_without_provider_and_preserves_generation_provenance(self):
        model, candidates, registry, settings = self.fixture()
        original = copy.deepcopy(model['opportunities'][0])
        with patch.object(maintenance, 'config', return_value=settings), \
                patch('requests.post', side_effect=AssertionError('No provider generation during restoration')):
            result = maintenance.restore_proven_teams(model, candidates, registry)
            self.assertEqual(result[0]['state'], 'restored_from_retained_evidence')
            row = model['opportunities'][0]
            self.assertEqual(row['review_state'], 'proposed')
            self.assertNotIn('revalidation_reason', row)
            for field in ('pipeline_hash', 'generator_version', 'registry_generation_at_generation',
                          'claims_generation_at_generation', 'source_fingerprint'):
                self.assertEqual(row.get(field), original.get(field))
            self.assertEqual(row['recovery_proof']['provider_requests'], 0)
            before = copy.deepcopy(model)
            self.assertEqual(maintenance.restore_proven_teams(model, candidates, registry), [])
            self.assertEqual(model, before)

    def test_stale_source_claim_or_contract_never_clears_flags(self):
        for change in ('source', 'claim', 'eligibility', 'contract', 'graph', 'missing_pipeline', 'never_published'):
            with self.subTest(change=change):
                model, candidates, registry, settings = self.fixture()
                row = model['opportunities'][0]
                if change == 'source':
                    next(c for c in candidates if c['id'] == self.key)['source_fingerprint'] = 'changed'
                elif change in ('claim', 'eligibility'):
                    ref = next(ref for role in row['roles'] for ref in role['claim_refs'])
                    person = next(p for p in registry['researchers'] if p['researcher_id'] == ref['researcher_id'])
                    if change == 'claim':
                        next(c for c in person['claims'] if c['claim_id'] == ref['claim_id'])['revision'] += 1
                    else:
                        person['auto_proposable'] = False
                elif change == 'contract':
                    settings['targeted_team_recovery']['scientific_contract'] = 'different'
                elif change == 'graph':
                    row['objective'] += ' Unsupported change.'
                elif change == 'missing_pipeline':
                    row.pop('pipeline_hash')
                else:
                    del settings['targeted_team_recovery']['published_decisions'][self.key]
                before = copy.deepcopy(model)
                with patch.object(maintenance, 'config', return_value=settings):
                    results = maintenance.restore_proven_teams(model, candidates, registry)
                self.assertFalse(any(r['state'] == 'restored_from_retained_evidence' for r in results))
                self.assertEqual(model, before)

    def test_explicit_source_review_binds_both_snapshots_and_still_checks_claims_and_quotes(self):
        for change in (None, 'prior_snapshot', 'current_snapshot', 'claim', 'quote'):
            with self.subTest(change=change):
                model, candidates, registry, settings = self.fixture()
                row = model['opportunities'][0]
                current = next(c for c in candidates if c['id'] == self.key)
                old_fingerprint = row['source_fingerprint']
                row['source_fingerprint'] = '0' * 64
                proof = settings['targeted_team_recovery']
                proof['published_decisions'][self.key] = maintenance.retained_decision_hash(row)
                reviewed = {'prior_source_fingerprint': row['source_fingerprint'],
                            'reviewed_source_fingerprint': current['source_fingerprint'],
                            'review_kind': 'source_projection_revalidation'}
                proof['reviewed_source_changes'] = {self.key: reviewed}
                if change == 'prior_snapshot':
                    reviewed['prior_source_fingerprint'] = 'wrong historical source'
                elif change == 'current_snapshot':
                    current['source_fingerprint'] = 'another amendment'
                elif change == 'claim':
                    ref = next(ref for role in row['roles'] for ref in role['claim_refs'])
                    person = next(p for p in registry['researchers'] if p['researcher_id'] == ref['researcher_id'])
                    next(c for c in person['claims'] if c['claim_id'] == ref['claim_id'])['revision'] += 1
                elif change == 'quote':
                    current['text'] = 'The retained quotes no longer occur in this exact official scope.'
                before = copy.deepcopy(model)
                with patch.object(maintenance, 'config', return_value=settings), \
                        patch('requests.post', side_effect=AssertionError('Restoration is provider-free')):
                    results = maintenance.restore_proven_teams(model, candidates, registry)
                if change:
                    self.assertEqual(model, before)
                    self.assertFalse(any(r['state'] == 'restored_from_retained_evidence' for r in results))
                else:
                    self.assertEqual(row['source_fingerprint'], old_fingerprint)
                    self.assertEqual(row['recovery_proof']['source_revalidation']['prior_source_fingerprint'], '0' * 64)
                    self.assertEqual(row['recovery_proof']['source_revalidation'], reviewed)
                    for field in ('pipeline_hash', 'generator_version', 'claims_generation_at_generation'):
                        self.assertEqual(row.get(field), before['opportunities'][0].get(field))


if __name__ == '__main__':
    unittest.main()
