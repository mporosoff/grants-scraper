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
        fixture = json.loads(Path('tests/fixtures/retained_team_recovery.json').read_bytes())
        cls.model = fixture['model']
        cls.registry = fixture['registry']
        cls.candidates = fixture['candidates']
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
        for change in ('source', 'claim', 'retired_claim', 'eligibility', 'contract', 'graph', 'missing_pipeline', 'never_published'):
            with self.subTest(change=change):
                model, candidates, registry, settings = self.fixture()
                row = model['opportunities'][0]
                if change == 'source':
                    next(c for c in candidates if c['id'] == self.key)['source_fingerprint'] = 'changed'
                elif change in ('claim', 'retired_claim', 'eligibility'):
                    ref = next(ref for role in row['roles'] for ref in role['claim_refs'])
                    person = next(p for p in registry['researchers'] if p['researcher_id'] == ref['researcher_id'])
                    if change == 'claim':
                        next(c for c in person['claims'] if c['claim_id'] == ref['claim_id'])['revision'] += 1
                    elif change == 'retired_claim':
                        next(c for c in person['claims'] if c['claim_id'] == ref['claim_id'])['status'] = 'retired'
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

    def test_reviewed_citation_reprojection_preserves_decisions_and_requires_exact_proofs(self):
        for key in ('363179',):
            for fault in (None, 'before', 'after', 'unknown_role', 'scope', 'decision', 'unreviewed', 'claim'):
                with self.subTest(key=key, fault=fault):
                    model, candidates, registry, settings = (copy.deepcopy(self.model), copy.deepcopy(self.candidates),
                                                           copy.deepcopy(self.registry), config())
                    model['opportunities'] = [r for r in model['opportunities'] if r['id'] == key]
                    row = model['opportunities'][0]
                    review = settings['targeted_team_recovery']['reviewed_source_changes'][key]
                    row['source_fingerprint'] = review['prior_source_fingerprint']
                    row['review_state'] = 'needs_revalidation'
                    updates = review['role_quote_updates']
                    for role in row['roles']:
                        if role['id'] in updates:
                            role['source_quote'] = updates[role['id']]['before']
                    update = next(iter(updates.values()))
                    if fault in ('before', 'after'):
                        update[fault] = 'Unreviewed source quotation.'
                    elif fault == 'unknown_role':
                        updates['role-99'] = copy.deepcopy(update)
                    elif fault == 'scope':
                        next(c for c in candidates if c['id'] == key)['source_fingerprint'] = 'later amendment'
                    elif fault == 'decision':
                        review['reviewed_decision_hash'] = 'different reviewed graph'
                    elif fault == 'unreviewed':
                        review['review_kind'] = 'source_projection_revalidation'
                    elif fault == 'claim':
                        ref = next(ref for role in row['roles'] for ref in role['claim_refs'])
                        person = next(p for p in registry['researchers'] if p['researcher_id'] == ref['researcher_id'])
                        next(c for c in person['claims'] if c['claim_id'] == ref['claim_id'])['revision'] += 1
                    before = copy.deepcopy(model)
                    with patch.object(maintenance, 'config', return_value=settings), \
                            patch('requests.post', side_effect=AssertionError('Citation review needs no provider')):
                        results = maintenance.restore_proven_teams(model, candidates, registry)
                    if fault:
                        self.assertEqual(model, before)
                        self.assertEqual(results[0]['state'], 'pending')
                    else:
                        self.assertEqual(results[0]['state'], 'restored_from_retained_evidence')
                        self.assertEqual(maintenance.retained_decision_hash(row), review['reviewed_decision_hash'])
                        for field in ('objective', 'members', 'variants', 'missing_skills', 'pipeline_hash',
                                      'generator_version', 'claims_generation_at_generation'):
                            self.assertEqual(row[field], before['opportunities'][0][field])
                        for old, new in zip(before['opportunities'][0]['roles'], row['roles']):
                            self.assertEqual({k: v for k, v in old.items() if k != 'source_quote'},
                                             {k: v for k, v in new.items() if k != 'source_quote'})
                        self.assertNotIn(key, teams.invalidate_stale_sources(model, teams.source_fingerprints(model, candidates)))
                        self.assertEqual(maintenance.restore_proven_teams(model, candidates, registry), [])

    def test_generic_trial_objective_does_not_clear_coordination_role_revalidation(self):
        model = copy.deepcopy(self.model)
        model['opportunities'] = [r for r in model['opportunities'] if r['id'] == '357493']
        before = copy.deepcopy(model)
        current = next(c for c in self.candidates if c['id'] == '357493')
        self.assertIn('investigator-initiated mid-phase clinical trials', current['text'])
        self.assertNotIn('357493', config()['targeted_team_recovery']['reviewed_source_changes'])
        with patch('requests.post', side_effect=AssertionError('Withheld evidence needs no provider')):
            results = maintenance.restore_proven_teams(model, self.candidates, self.registry)
        self.assertEqual(model, before)
        self.assertEqual(results[0]['state'], 'pending')

    def test_curated_review_uses_its_own_source_contract_and_preserves_legacy_evidence(self):
        for key in ('363375', 'eere-exchange:DE-TA1-0003589'):
            for change in (None, 'profile', 'source', 'quote', 'unreviewed', 'generated'):
                with self.subTest(key=key, change=change):
                    model, candidates, registry, settings = (copy.deepcopy(self.model), copy.deepcopy(self.candidates),
                                                           copy.deepcopy(self.registry), config())
                    model['opportunities'] = [row for row in model['opportunities'] if row['id'] == key]
                    row = model['opportunities'][0]
                    review = settings['targeted_team_recovery']['reviewed_source_changes'][key]
                    # Reproduce the same historical reviewed row after publication too.
                    row['source_fingerprint'] = review['prior_source_fingerprint']
                    row['review_state'] = 'needs_revalidation'
                    original = copy.deepcopy(row)
                    if change == 'profile':
                        person = next(p for p in registry['researchers'] if p['researcher_id'] == row['members'][0]['faculty_id'])
                        person['auto_proposable'] = False
                    elif change == 'source':
                        review['reviewed_source_fingerprint'] = 'unreviewed amendment'
                    elif change == 'quote':
                        review['role_source_quotes']['role-1'] = 'A quoted method absent from the current bounded scope.'
                    elif change == 'unreviewed':
                        review['review_kind'] = 'not an explicit curated review'
                    elif change == 'generated':
                        row['generator_version'] = 'opportunity-teams-2'
                        settings['targeted_team_recovery']['published_decisions'][key] = maintenance.retained_decision_hash(row)
                    before = copy.deepcopy(model)
                    with patch.object(maintenance, 'config', return_value=settings), \
                            patch('requests.post', side_effect=AssertionError('Curated review needs no provider')):
                        result = maintenance.restore_proven_teams(model, candidates, registry)
                    # These exact old curated hashes covered the old profile
                    # projection. Expanded summaries/domains are new matching
                    # inputs; do not manufacture a replacement review receipt.
                    self.assertEqual(model, before)
                    self.assertEqual(result[0]['state'], 'pending')



if __name__ == '__main__':
    unittest.main()
