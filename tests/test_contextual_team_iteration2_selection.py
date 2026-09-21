"""Source-only split, lineage, currentness and historical-identity invariants."""
import hashlib
import json
from pathlib import Path
import unittest

from tools.contextual_team_executor import scope_inputs
from tools.offline_spend import identity

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config/contextual_team'


def read(name):
    return json.loads((CONFIG / name).read_bytes())


def validate_selection(development, confirmation, audit, sources, historical):
    """Fail closed on split leakage or source identity drift, without science."""
    dev = development['scopes']
    confirm = confirmation['scopes']
    if len(dev) != 12 or len({s['id'] for s in dev}) != 12:
        raise ValueError('development_inventory')
    families = {s['research_family'] for s in dev if s['route_state'] != 'needs_scope_selection'}
    if len(families) < 6:
        raise ValueError('development_research_families')
    if len(confirm) != 12 or len({s['parent_id'] for s in confirm}) != 12:
        raise ValueError('confirmation_parent_inventory')
    if any(s['scope_id'] != s['id'] or s['parent_id'] != s['id'] for s in confirm):
        raise ValueError('confirmation_specific_parents')
    if confirmation['seal_sha256'] != identity({k: v for k, v in confirmation.items() if k != 'seal_sha256'}):
        raise ValueError('confirmation_seal')
    if confirmation['scientific_outputs_opened'] is not False or confirmation['source_selection_only'] is not True:
        raise ValueError('confirmation_science_exposure')
    excluded = set(audit['excluded_parent_ids_including_development_and_group_closure'])
    excluded.update(s['parent_id'] for s in dev)
    old = set(audit['historical_exposure_explicit_supplement'])
    for ids in audit['historical_exposure_id_origins'].values():
        old.update(ids)
    if not old <= excluded:
        raise ValueError('historical_exposure_dropped')
    groups = set()
    members = set()
    for s in confirm:
        group = s['related_group']
        own = set(s['related_parent_ids_reserved'])
        if group in groups or s['id'] not in own or own & (excluded | members):
            raise ValueError('confirmation_lineage_overlap')
        if own != set(audit['confirmation_related_group_members'][group]):
            raise ValueError('confirmation_lineage_unbound')
        if s['scientific_output_status'] != 'sealed: not opened, generated, scored, or used for tuning':
            raise ValueError('confirmation_output_exposed')
        groups.add(group)
        members.update(own)
    forbidden = {'people', 'candidates', 'recommendations', 'verdicts', 'interpretation',
                 'assessment', 'assessment_output', 'graph', 'team', 'feasible', 'quality_score'}
    def check_metadata(value):
        if isinstance(value, dict):
            if forbidden & set(value):
                raise ValueError('confirmation_scientific_content')
            for child in value.values():
                check_metadata(child)
        elif isinstance(value, list):
            for child in value:
                check_metadata(child)
    check_metadata(confirmation)
    replacement = confirmation['replacement_policy']
    queue = replacement['reserve_scope_ids']
    seed = replacement['queue_seed']
    if (len(queue) != len(set(queue)) or set(queue) & (excluded | members)
            or queue != sorted(queue, key=lambda sid: hashlib.sha256((seed + '|' + sid).encode()).hexdigest())):
        raise ValueError('replacement_order_or_exposure')
    if any(trigger in replacement['allowed_triggers'] for trigger in replacement['forbidden_triggers']):
        raise ValueError('result_driven_replacement')
    if set(replacement['forbidden_triggers']) != {'unfavorable scientific label', 'weak recommendation',
            'no useful team', 'model disagreement', 'latency failure'}:
        raise ValueError('replacement_protections')
    current = {s['id']: s for s in sources['scopes']}
    if set(current) != {s['id'] for s in dev}:
        raise ValueError('source_inventory')
    for s in current.values():
        if s['source_id'] != identity(scope_inputs(s)):
            raise ValueError('scientific_source_identity')
    for prior in historical['scopes']:
        s = current[prior['id']]
        if scope_inputs(s) != scope_inputs(prior) or s['source_id'] != prior['source_id']:
            raise ValueError('historical_scientific_identity')
    deadline_fields = ('deadlines', 'close_date', 'rolling', 'deadline_source')
    for prior in historical['scopes']:
        active = current[prior['id']]['currentness']
        for part in ('record', 'parent'):
            if any(active[part].get(k) != prior['currentness'][part].get(k) for k in deadline_fields):
                raise ValueError('governing_currentness_changed')
            guard = active['catalog_status_guard'][part]
            if any(k in guard for k in ('deadlines', 'close_date', 'rolling')):
                raise ValueError('catalog_guard_overrides_official_dates')
            if active[part].get('status') != guard.get('status'):
                raise ValueError('catalog_status_guard_missing')
    doe = current['363302:a-1']['currentness']
    if doe.get('not_after') != '2026-09-22T21:00:00Z':
        raise ValueError('official_doe_instant_cutoff')
    if not any(d.get('date') == '2026-09-22' and d.get('time') == '17:00'
               and d.get('timezone') == 'America/New_York' for d in doe['parent']['deadlines']):
        raise ValueError('official_doe_deadline_provenance')
    math = current['341997']['currentness']['parent']
    if math['rolling'] is not True or math['close_date'] is not None:
        raise ValueError('mathbio_target_is_not_close')
    if (sources['registry_generation'], sources['roster_id']) != (historical['registry_generation'], historical['roster_id']):
        raise ValueError('audited_people_identity')
    action = [s for s in current.values() if s['action_current']]
    forecast = [s for s in current.values() if s['current_eligibility']['catalog_status'] == 'forecasted']
    broad = [s for s in current.values() if s['state'] == 'needs_scope_selection']
    if len(action) != 8 or len(forecast) != 3 or len(broad) != 1:
        raise ValueError('currentness_denominators')
    if any(s['action_current'] or s['state'] != 'action_blocked' for s in forecast):
        raise ValueError('forecasted_actionability')
    if broad[0]['id'] != '344592' or broad[0]['action_current']:
        raise ValueError('broad_parent_gate')
    return {'development': len(dev), 'confirmation': len(confirm), 'families': len(families),
            'action_current': len(action), 'forecasted': len(forecast), 'broad_parent': len(broad)}


class Iteration2SelectionTests(unittest.TestCase):
    def setUp(self):
        self.development = read('iteration2-development-v1.json')
        self.confirmation = read('iteration2-confirmation-seal-v1.json')
        self.audit = read('iteration2-source-selection-v1.json')
        self.sources = read('iteration2-source-inputs-v1.json')
        self.historical = read('phase2-source-inputs-v2.json')

    def validate(self):
        return validate_selection(self.development, self.confirmation, self.audit, self.sources, self.historical)

    def reseal(self):
        self.confirmation['seal_sha256'] = identity({k:v for k,v in self.confirmation.items() if k != 'seal_sha256'})

    def test_real_frozen_inventory_lineage_currentness_and_sources(self):
        self.assertEqual(self.validate(), {'development':12, 'confirmation':12, 'families':9,
                                          'action_current':8, 'forecasted':3, 'broad_parent':1})
        self.assertEqual(self.development['source_inputs_sha256'], hashlib.sha256((CONFIG/'iteration2-source-inputs-v1.json').read_bytes()).hexdigest())
        self.assertEqual(self.confirmation['development_manifest_sha256'], hashlib.sha256((CONFIG/'iteration2-development-v1.json').read_bytes()).hexdigest())
        self.assertEqual(self.confirmation['source_selection_audit_sha256'], hashlib.sha256((CONFIG/'iteration2-source-selection-v1.json').read_bytes()).hexdigest())
        self.assertEqual(self.audit['checks']['confirmation_scientific_outputs_opened'], 0)
        self.assertEqual(self.audit['checks']['paid_calls'], 0)

    def test_alias_into_historical_exposure_rejected(self):
        self.confirmation['scopes'][0]['related_parent_ids_reserved'].append('351715')
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'lineage_overlap'):
            self.validate()

    def test_duplicate_confirmation_parent_rejected(self):
        self.confirmation['scopes'][1]['parent_id'] = self.confirmation['scopes'][0]['parent_id']
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'parent_inventory'):
            self.validate()

    def test_scientific_output_in_confirmation_rejected(self):
        self.confirmation['scopes'][0]['verdicts'] = []
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'scientific_content'):
            self.validate()

    def test_result_driven_or_reordered_replacements_rejected(self):
        self.confirmation['replacement_policy']['reserve_scope_ids'].reverse()
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'replacement_order'):
            self.validate()
        self.setUp()
        self.confirmation['replacement_policy']['allowed_triggers'].append('weak recommendation')
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'result_driven'):
            self.validate()

    def test_rehashed_historical_source_edit_rejected(self):
        source = next(s for s in self.sources['scopes'] if s['id'] == '351715')
        source['science']['description'] += ' Changed.'
        source['source_id'] = identity(scope_inputs(source))
        with self.assertRaisesRegex(ValueError, 'historical_scientific_identity'):
            self.validate()

    def test_governing_deadlines_survive_fresh_catalog_metadata(self):
        current = {s['id']: s for s in self.sources['scopes']}
        self.assertEqual(current['363302:a-1']['currentness']['not_after'], '2026-09-22T21:00:00Z')
        self.assertEqual(current['341997']['current_eligibility']['conditions']['close_date'], '2026-10-14')
        self.assertIsNone(current['341997']['currentness']['parent']['close_date'])
        self.assertTrue(current['341997']['currentness']['parent']['rolling'])
        self.assertTrue(any('receiving NSF program' in text for text in current['351715']['current_eligibility']['limitations']))
        current['341997']['currentness']['parent']['close_date'] = '2026-10-14'
        with self.assertRaisesRegex(ValueError, 'governing_currentness_changed'):
            self.validate()
        self.setUp()
        next(s for s in self.sources['scopes'] if s['id'] == '363302:a-1')['currentness']['not_after'] = '2026-09-23T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'official_doe_instant_cutoff'):
            self.validate()

    def test_forecasted_and_broad_gates_cannot_be_marked_actionable(self):
        next(s for s in self.sources['scopes'] if s['id'] == '361207')['action_current'] = True
        with self.assertRaisesRegex(ValueError, 'currentness_denominators'):
            self.validate()
        self.setUp()
        next(s for s in self.sources['scopes'] if s['id'] == '344592')['action_current'] = True
        with self.assertRaisesRegex(ValueError, 'currentness_denominators'):
            self.validate()


if __name__ == '__main__':
    unittest.main()
