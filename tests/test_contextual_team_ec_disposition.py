"""Exact identity and no-replay contracts for an existing, not newly added, hold."""
import copy
import unittest
from unittest.mock import patch

from test_contextual_team_ec_recovery import Fixture
from tools import contextual_team_ec_disposition as disposition
from tools import contextual_team_iteration2_policy as historical
from tools import contextual_team_iteration3_policy as original
from tools.offline_spend import ConfigurationFailure, Deferred, identity


class FixedECIdentity(unittest.TestCase):
    def test_checked_in_plan_pins_actual_owner_and_has_no_second_allowance(self):
        plan=disposition.plan()
        self.assertEqual(identity(plan),disposition.PLAN_SHA256)
        self.assertEqual((plan['source']['requests'],plan['source']['events'],plan['source']['native_counts']),(725,65,206))
        self.assertEqual(plan['source']['request_id'],disposition.REQUEST_ID)
        self.assertEqual(plan['source']['run']['id'],35868713542)
        self.assertIs(plan['no_second_allowance'],True)
        self.assertEqual(plan['additional_allowance'],0)

    def test_historical_state_without_event_does_not_require_new_prefix(self):
        self.assertFalse(disposition.validate({'events':[]}))
        self.assertEqual(disposition.allowed_unknown_ids({'events':[]}),frozenset())


class ECDisposition(Fixture):
    def test_only_exact_unknown_is_exempt_and_same_request_cannot_rekey(self):
        state=self.restore().read()
        self.assertEqual(disposition.allowed_unknown_ids(state),frozenset((disposition.REQUEST_ID,)))
        for row in ({'id':'f'*32,'purpose':disposition.CLOSED_PURPOSE,'key':'f'*64},
                    {'id':'f'*32,'purpose':'cb-fc-i3c-ec_check','key':self.p['source']['request_key']}):
            changed=copy.deepcopy(state);changed['requests'].append(row)
            with self.assertRaisesRegex(ConfigurationFailure,'replayed'):disposition.validate(changed)

    def test_native_prefix_immutable_and_closed_purpose_has_no_new_count(self):
        state=self.restore().read();counts=copy.deepcopy(self.budget.counts)
        disposition.validate_counts(state,counts)
        counts.append({'id':disposition.CLOSED_PURPOSE})
        with self.assertRaises(ConfigurationFailure):disposition.validate_counts(state,counts)
        counts=copy.deepcopy(self.budget.counts);counts[0]['input_tokens']+=1
        with self.assertRaises(ConfigurationFailure):disposition.validate_counts(state,counts)

    def test_historical_reads_exempt_only_exact_disposed_unknown_and_old_reservation_closed(self):
        state=self.restore().read();p=copy.deepcopy(historical.plan())
        p['starting_checkpoint'].update(requests=len(self.prior['requests']),requests_sha256=identity(self.prior['requests']),
            events=len(self.prior['events']),events_sha256=identity(self.prior['events']))
        with patch.object(historical,'plan',return_value=p):
            historical.history(state,require_authority=False)
            changed=copy.deepcopy(state);changed['requests'].append({'id':'f'*32,'status':'reserved_unknown'})
            with self.assertRaisesRegex(Deferred,'new_uncertainty'):historical.history(changed,require_authority=False)
        for policy in (historical,original):
            with self.assertRaisesRegex(Deferred,'paid_inventory_superseded'):
                policy.check_reservation(state,'anthropic',{},1,1,1)
