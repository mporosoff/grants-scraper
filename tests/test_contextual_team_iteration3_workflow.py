"""Prospective workflow control with synthetic science, never provider traffic."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import contextual_team_iteration3 as workflow
from tools import contextual_team_iteration2_contract as science
from tools import contextual_team_iteration3_integrity as integrity
from tools.offline_spend import identity
from tools.contextual_team_executor import RecoveryRequired
from test_contextual_team_iteration3_integrity import setup, wire
from test_contextual_team_iteration2_contract import assessment, verified_wire


class Iteration3Workflow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        data,_,_=setup()
        self.data=data;self.scope=deepcopy(data['scope'])|{'source_id':identity({'scope':data['scope']})}
        self.a=assessment(data,'method_transfer');self.v=science.verifier_resolve(verified_wire(data,self.a),data,self.a)
        self.config=workflow.configuration()
        # The reusable source fixture has its own immutable source references.
        # Only this isolated control-flow test substitutes its admission list;
        # the separate policy contracts exercise the real finite I3 inventory.
        self.config['iteration3']['build_scope_ids']=[self.scope['id']]
        self.retrieval={'eligible':155,'shortlist':[p['person_id'] for p in data['people']],
            'per_contribution':[],'unassessed':143,'maximum_shortlist':12}
        for item in (patch('socket.socket.connect',side_effect=AssertionError('no_network')),
            patch('tools.contextual_team_executor.ExperimentLedger'),
            patch.object(workflow.policy,'history'),patch.object(workflow.policy,'check_counts',return_value=[]),
            patch.object(workflow.policy,'plan',return_value=self.config['iteration3']),
            patch.object(workflow,'retained_inputs',return_value=(self.config,self.scope,self.data,self.retrieval,
                {'decomposition':'a'*64},[{'key':'b'*64,'request_id':'retained-vector','cache_hit':True}])),
            patch.object(workflow,'_cached',side_effect=lambda state,scope,stage,*args:self.a if stage=='assess' else self.v)):
            item.start();self.addCleanup(item.stop)

    def runner(self):
        runner=workflow.Iteration3Runner(Path(self.tmp.name),self.config,read_only=True)
        runner.ledger=Mock();runner.ledger.read.return_value={'requests':[]}
        return runner

    def test_complete_verifier_abstentions_remain_independently_evaluable_without_integrity(self):
        for state in ('unsuitable','insufficient_source','needs_scope_selection'):
            raw=verified_wire(self.data,self.a);raw['state']=state
            for row in raw['answers']:row.update(coverage='insufficient_information',central=False,claims=[])
            self.v=science.verifier_resolve(raw,self.data,self.a)
            runner=self.runner();runner.scientific=Mock(side_effect=AssertionError('no_new_integrity_for_abstention'))
            actual=runner.reconstruct(self.scope)
            graph=actual['graph']
            self.assertEqual(graph['state'],state);self.assertEqual(graph['version'],'contextual-audited-graph-v3')
            self.assertNotIn('integrity',graph);self.assertEqual(graph['retrieval'],self.retrieval)
            self.assertEqual(sum(len(p['decisions']) for p in graph['pair_decisions']),24)
            self.assertEqual(graph['graph_id'],identity({k:v for k,v in graph.items() if k not in ('requests','graph_id')}))
            self.assertEqual(actual['assessment'],self.a);self.assertEqual(actual['verified'],self.v)

    def test_new_graph_and_integrity_packet_stay_identical_across_cache_observations(self):
        first=self.runner();first.used=[{'cache_hit':False,'observed_only':'first process'}]
        second=self.runner();second.used=[{'cache_hit':True,'observed_only':'later process'}]
        one=first.reconstruct(self.scope,'verify');two=second.reconstruct(self.scope,'verify')
        self.assertEqual(one['graph'],two['graph'])
        eligible=[p['person_id'] for p in self.config['people']]
        self.assertEqual(integrity.body(self.data,one['graph'],eligible),integrity.body(self.data,two['graph'],eligible))
        value=integrity.resolve(wire(self.data,one['graph'],eligible,'insufficient_information'),self.data,one['graph'],eligible)
        first.scientific=Mock(return_value=value)
        result=first.reconstruct(self.scope)['graph']
        self.assertEqual(result['pair_decisions'],one['graph']['pair_decisions'])
        self.assertEqual(result['edges'],one['graph']['edges'])
        self.assertEqual(result['state'],'no_supported_group_in_checked_candidates')

    def test_missing_old_vectors_and_readonly_new_cache_cannot_purchase_or_count(self):
        reader=workflow._VectorsOnly(Path(self.tmp.name),self.config,post=Mock(side_effect=AssertionError('provider')))
        with self.assertRaisesRegex(RecoveryRequired,'no_purchase'):reader.request('cb-query',[],{},None)
        reader.post.assert_not_called()
        runner=self.runner();runner.post=Mock(side_effect=AssertionError('provider'));runner.counter=Mock()
        body=workflow.references.assessment_body(self.data)[1]
        with self.assertRaisesRegex(RecoveryRequired,'successful_cache'):
            runner.request(workflow.policy.operation('363268','assess'),['test'],body,Mock())
        runner.post.assert_not_called();runner.counter.count.assert_not_called()

    def test_actual_candidate_inventory_controls_generation_marker_without_changing_science(self):
        runner=self.runner();before=runner.reconstruct(self.scope,'verify')['graph']
        with patch.object(workflow.existing,'checkpoint'):
            result=runner.run_stage(self.scope,'verify')
        self.assertEqual(result,{'state':'stage_complete','stage':'verify','scope_id':self.scope['id']})
        self.assertTrue(runner.integrity_generation_required)
        self.assertEqual(runner.reconstruct(self.scope,'verify')['graph'],before)
        # Coherent all-negative pair decisions require no integrity generation,
        # but still produce the complete deterministic v4 empty-candidate result.
        raw=verified_wire(self.data,self.a)
        for row in raw['answers']:row.update(coverage='insufficient_information',central=False,claims=[])
        self.v=science.verifier_resolve(raw,self.data,self.a)
        runner=self.runner();runner.scientific=Mock(side_effect=AssertionError('no new inference'))
        runner.post=Mock(side_effect=AssertionError('no provider'));runner.counter=Mock()
        with patch.object(workflow.existing,'checkpoint'):
            result=runner.run_stage(self.scope,'verify')
            self.assertEqual(result['state'],'stage_complete');self.assertFalse(runner.integrity_generation_required)
            graph=runner.run_stage(self.scope,'integrity')
        self.assertEqual(graph['version'],'contextual-audited-graph-v4')
        self.assertEqual(graph['integrity']['candidate_groups'],[])
        self.assertEqual(graph['integrity']['disposition'],'not_applicable_no_candidates')
        self.assertEqual(graph['state'],'no_supported_group_in_assessed_set')
        runner.scientific.assert_not_called();runner.post.assert_not_called();runner.counter.count.assert_not_called()


if __name__=='__main__':unittest.main()
