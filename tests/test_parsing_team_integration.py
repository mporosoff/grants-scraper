"""Source-owned HGEO bodies through the existing team writers, with provider stubs."""
from contextlib import ExitStack, chdir, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_catalog, build_opportunity_teams as teams
from scripts import subtopic_cov4, subtopic_records, subtopic_structured
from tests.fixtures import phase2_pipeline as fixture


class ParsingTeamIntegration(unittest.TestCase):
    def test_real_scientific_excerpt_reaches_panel_and_source_change_withholds_team(self):
        source = json.loads((fixture.ROOT / 'tests/fixtures/parsing/363302.json').read_bytes())
        content = source['text'].encode()
        # The source receipt identifies the full document; this test's transport
        # contains only the reviewed, bounded excerpt and has its own byte hash.
        document = {'url': source['source']['url'], 'name': 'FundOpp_DE-FOA-0003634.pdf',
                    'sha256': hashlib.sha256(content).hexdigest(), 'source_kind': 'primary_notice'}
        parent = {'opportunity_id': '363302', 'opportunity_number': 'DE-FOA-0003634',
                  'title': 'Hydrocarbons and Geothermal Energy research topics', 'status': 'posted',
                  'agency': 'Department of Energy', 'close_date': '2026-09-22',
                  'primary_document_url': document['url'],
                  'document_evidence': {'dependency_version': 2, 'document': document}}
        outcome = subtopic_structured.first_refusal(parent, content, document,
            detail_fetcher=lambda _: {'data': {}}, collector=lambda _: [],
            download=lambda _: self.fail('Source fixture attempted another download'),
            extract_containers=lambda body, *_: ([{'page': 1, 'text': body.decode()}], {}),
            as_of=fixture.AS_OF.isoformat())
        self.assertEqual(len(outcome.records), 5)
        calls = []
        def classify(candidate, **_):
            calls.append(candidate)
            return {'fundability': 'accept', 'error': None, 'api_request': False}
        children, diagnostics = subtopic_cov4.apply_gate(parent, outcome.records, document, classifier=classify)
        self.assertEqual(diagnostics['published'], 5)
        self.assertEqual(diagnostics['api_requests'], 0)
        roles = [
            {'id': 'role-1', 'label': 'Computational fluid dynamics', 'required': True,
             'quote': 'apply computational approaches (e.g., AI/ML, computational fluid dynamics)'},
            {'id': 'role-2', 'label': 'Experimental catalyst and reactor validation', 'required': True,
             'quote': 'rapidly develop and validate new catalysts, reactor systems, and separation technologies'},
        ]
        provider_inputs = []
        def answer(_provider, prompt, data):
            provider_inputs.append((prompt, deepcopy(data)))
            if prompt == teams.DECOMPOSE:
                specific = all(role['quote'] in data['scope'] for role in roles)
                value = {'specific': specific, 'roles': roles if specific else [],
                         'objective': 'Combine computational modeling and experimental catalyst/reactor validation for hydrocarbon processing.'
                         if specific else 'This deterministic fixture assesses only the laboratory catalyst and reactor scope.'}
            else:
                value = {'edges': [{'role_id': role['id'], 'claim_id': f'urh-99000{i}-c001',
                                   'coverage': 'direct', 'reason': 'The synthetic claim explicitly supports this exact source-owned contribution.'}
                                  for i, role in enumerate(roles, 1)]}
                if prompt == teams.VERIFY:
                    value['suitable_for_team'] = True
            return teams.validate_response(prompt, data, value)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Existing fixture owns isolated assets, registry and model setup.
            fixture.run_pipeline(root)
            with patch.object(fixture, 'ROLES', roles):
                registry = fixture.fixture_registry()
            (root / 'config/researcher_registry.json').write_text(json.dumps(registry), encoding='utf-8')
            model = {'schema_version': 1, 'method_version': 'fixture', 'release_state': 'fixture',
                     'source_hashes': {}, 'limitations': [], 'faculty': [], 'opportunities': []}
            model_path = root / 'config/opportunity_team_model.json'
            model_path.write_text(json.dumps(model), encoding='utf-8')
            build_catalog.write_catalog(build_catalog.build_catalog([parent], fixture.NOW, 'source excerpt fixture', 0),
                                        root / 'data/opportunities.js')
            sidecar = {'records': {'363302': {'subtopics': children}}}
            subtopic_records.write_cache(sidecar, root / 'data/subtopics.js')
            with chdir(root), ExitStack() as stack, redirect_stdout(io.StringIO()):
                stack.enter_context(patch('tools.offline_spend.config', side_effect=fixture.synthetic_offline_settings))
                stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('Fixture attempted live network')))
                stack.enter_context(patch('scripts.currentness.date', fixture.FixedDate))
                stack.enter_context(patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'synthetic'}))
                stack.enter_context(patch.object(teams.Provider, 'json', answer))
                stack.enter_context(patch.object(teams.Provider, 'embed', side_effect=lambda texts, *_: [[1.0, 0.0] for _ in texts]))
                stack.enter_context(patch.object(teams.Provider, 'embed_reusable', side_effect=lambda texts, *_, **kwargs: [[1.0, 0.0] for _ in texts]))
                # The existing cross-parent reservation considers one child
                # per parent in a pass. Resume its persisted pending work to
                # reach the laboratory child; do not bypass that reservation.
                for _ in range(len(children)):
                    with patch.object(sys, 'argv', ['build_opportunity_teams', '--generate', '--mode', 'backfill', '--state', '.spend/fixture', '--write', '--workers', '1']):
                        self.assertEqual(teams.main(), 0)
                    if json.loads(model_path.read_bytes())['opportunities']:
                        break
                generated = json.loads(model_path.read_bytes())
                report = json.loads((root / 'evaluation/opportunity_team_generation.json').read_bytes())
                self.assertEqual([row['id'] for row in generated['opportunities']], ['363302:a-1'], report.get('results'))
                proposed = generated['opportunities'][0]
                self.assertEqual(len(proposed['members']), 2)
                self.assertEqual(proposed['gate_state'], 'pass')
                panel = (root / 'data/opportunity_team_index.js').read_text()
                self.assertIn('363302:a-1', panel)
                self.assertIn(generated['generation_id'], panel)
                scoped = next(data['scope'] for prompt, data in provider_inputs
                              if prompt == teams.DECOMPOSE and roles[0]['quote'] in data['scope'])
                self.assertNotIn('field testing across multiple oil and gas', scoped)
                self.assertNotIn('Hydrocarbon Infrastructure Test Sites', scoped)
                self.assertTrue(all(role['quote'] in scoped for role in roles))
                self.assertNotIn('363302', [row['id'] for row in generated['opportunities']])
                # A material source revision invalidates the generated panel
                # before assessment, including when provider work is disabled.
                revised = deepcopy(sidecar)
                next(c for c in revised['records']['363302']['subtopics']
                     if c['subtopic_id'] == '363302:a-1')['source_document_hash'] = hashlib.sha256(b'amended source fixture').hexdigest()
                subtopic_records.write_cache(revised, root / 'data/subtopics.js')
                count = len(provider_inputs)
                with patch.object(sys, 'argv', ['build_opportunity_teams', '--write']):
                    self.assertEqual(teams.main(), 0)
                self.assertEqual(len(provider_inputs), count)
                invalid = json.loads(model_path.read_bytes())['opportunities'][0]
                self.assertEqual(invalid['review_state'], 'needs_revalidation')


if __name__ == '__main__':
    unittest.main()
