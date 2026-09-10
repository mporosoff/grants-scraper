import hashlib
import unittest
from tools.team_recommender_group_audit import audit, DOC

class SourceGroupAuditTests(unittest.TestCase):
    def test_source_only_overlay_preserves_reservations_and_seals_relations(self):
        paths=[DOC/'manifests'/n for n in ('development.json','holdout.json','source-groups.json','rollout.json')]
        before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        a=audit();b=audit()
        self.assertEqual(a,b)
        self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
        self.assertEqual((len(a['development_scopes']),len(a['holdout_scopes']),len(a['development_controls']),len(a['holdout_controls'])),(90,90,30,30))
        self.assertFalse({s['group_id'] for s in a['development_scopes']}&{s['group_id'] for s in a['holdout_scopes']})
        self.assertFalse(a['selection_uses_recommendations'])
        nsf=next(s for s in a['development_scopes'] if s['id'].endswith('/nsf22-600'))
        self.assertEqual(a['source_group_map']['340828'],nsf['group_id'])
        self.assertTrue(any(r['original']['id']=='340828' for r in a['dispositions']))
        self.assertEqual(a['source_group_map']['361207'],a['source_group_map']['361208'])
        self.assertEqual(a['source_group_map']['358114'],a['source_group_map']['362597'])

if __name__=='__main__':unittest.main()
