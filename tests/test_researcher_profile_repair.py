import copy
import json
from pathlib import Path
import unittest
from scripts.researcher_registry import (load_registry, directory_projection, legacy_faculty_projection, matching_profiles,
    dependency_report, registry_generation, apply_approved_submission, synchronize_opportunity_team_model, validate_opportunity_team_dependencies)
from tools.researcher_source_audit import PageText

class ProfileRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()
        cls.audit = json.loads(Path('docs/team-recommender/profile-repair/person-audit.json').read_bytes())

    def test_every_current_identity_has_an_authored_disposition_and_owned_provenance(self):
        people = {p['researcher_id']: p for p in self.registry['researchers']}
        self.assertEqual(set(people), {p['researcher_id'] for p in self.audit['people']})
        for row in self.audit['people']:
            person = people[row['researcher_id']]
            self.assertIn(row['disposition'], {'corrected', 'reviewed and adequate', 'unresolved'})
            if row['disposition'] == 'unresolved': self.assertTrue(row['limitations'])
            read_urls = {s['url'] for s in row['source_pages'] if s['read_status'] == 'read'}
            self.assertTrue(read_urls)
            self.assertEqual(row['after_summary'], person['research_summary'])
            self.assertEqual(row['before_pool_state'], row['after_pool_state'])
            self.assertTrue(row['auto_proposable_unchanged'])
            self.assertTrue(person['summary_evidence'])
            for c in person['claims']:
                self.assertTrue(c['claim_id'].startswith(person['researcher_id'] + '-c'))
                if c['status'] != 'active': continue
                self.assertTrue(c['evidence_records'])
                for e in c['evidence_records']:
                    self.assertIn(e['url'], read_urls)
                    self.assertIn(e['url'], c['source_urls'])
                    self.assertEqual(e['form'], 'paraphrase')
                    self.assertTrue(e['retrieved_at'])

    def test_canonical_summary_and_active_evidence_survive_every_projection(self):
        directory = {p['id']: p for p in directory_projection(self.registry)['researchers']}
        legacy = {p['id']: p for p in legacy_faculty_projection(self.registry)}
        for p in self.registry['researchers']:
            for projection in (directory[p['researcher_id']], legacy[p['researcher_id']]):
                self.assertEqual(projection['research_summary'], p['research_summary'])
                self.assertEqual(projection['summary_evidence'], p['summary_evidence'])
            terms = legacy[p['researcher_id']]['terms']
            self.assertEqual({t['claim_id'] for t in terms}, {c['claim_id'] for c in p['claims'] if c['status'] == 'active'})
            self.assertTrue(all(t['evidence_records'] for t in terms))
        by_id = {p['researcher_id']: p for p in self.registry['researchers']}
        for p in matching_profiles(self.registry):
            self.assertEqual(p['research_summary'], by_id[p['researcher_id']]['research_summary'])
            self.assertTrue(p['claims'])

    def test_summary_only_change_in_unselected_candidate_invalidates_the_entire_pool(self):
        before = self.registry
        person = next(p for p in before['researchers'] if p['auto_proposable'])
        after = copy.deepcopy(before); target = next(p for p in after['researchers'] if p['researcher_id'] == person['researcher_id'])
        target['research_summary'] += ' Fixture-only changed scientific context.'
        after['registry_generation'] = registry_generation(after)
        model = {'opportunities': [{'id': 'scope-a', 'members': [], 'roles': []}, {'id': 'scope-b', 'members': [], 'roles': []}], 'faculty': legacy_faculty_projection(before), 'researcher_registry_generation': before['registry_generation']}
        model = synchronize_opportunity_team_model(before, Path('unused'), model=model, write=False)
        self.assertEqual({s['scope_id'] for s in dependency_report(before, after, model)['affected_team_scopes']}, {'scope-a', 'scope-b'})
        with self.assertRaisesRegex(ValueError, 'candidate-pool'): validate_opportunity_team_dependencies(after, model)
        changed = synchronize_opportunity_team_model(after, Path('unused'), model=model, write=False)
        self.assertTrue(all(s['review_state'] == 'needs_revalidation' for s in changed['opportunities']))
        again = synchronize_opportunity_team_model(after, Path('unused'), model=changed, write=False)
        self.assertEqual(again['generation_id'], changed['generation_id'])

    def test_later_edits_do_not_reuse_old_wording_receipts_or_drop_history(self):
        person = next(p for p in self.registry['researchers'] if p['auto_proposable'])
        claims = copy.deepcopy(person['claims']); c = next(c for c in claims if c['status'] == 'active'); old = copy.deepcopy(c)
        c['evidence'] += ' Changed fixture context.'
        updated, _ = apply_approved_submission(self.registry, {'schema_version': 1, 'state': 'approved', 'researcher_id': person['researcher_id'], 'approved_profile': {'research_summary': person['research_summary'] + ' Updated.', 'claims': claims}}, self.registry['registry_generation'])
        p = next(p for p in updated['researchers'] if p['researcher_id'] == person['researcher_id']); new = next(c for c in p['claims'] if c['claim_id'] == old['claim_id'])
        self.assertNotIn('summary_evidence', p); self.assertNotIn('source_audit', p)
        self.assertNotIn('evidence_records', new); self.assertEqual(new['history'][-1]['evidence_records'], old['evidence_records'])
        self.assertEqual(new['revision'], old['revision'] + 1)

    def test_source_extractor_retains_headings_and_real_sibling_content(self):
        p = PageText('https://example.edu/person'); p.feed('<header>Research overview</header><main><h2>Research</h2><p>Specific catalysis studies.</p></main><script>bad</script>')
        self.assertIn('Research', p.result()[0]); self.assertNotIn('bad', p.result()[0])
        p = PageText('https://example.edu/person'); p.feed('<div id="main">Menu</div><article>' + 'Scientific overview sentence. ' * 25 + '</article>')
        self.assertTrue(any('Scientific overview' in s for s in p.result()[0]))

if __name__ == '__main__': unittest.main()
