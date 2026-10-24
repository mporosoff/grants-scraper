"""Reviewed October 24 SAM amendments preserve actual application routes."""
from datetime import date
import json
from pathlib import Path
import unittest

from scripts.sources import sam_reviewed
from scripts.submission_schedule import project


ROOT = Path(__file__).resolve().parents[1]
FAA = '897e1427461540d792897c599373758b'
NGA = '854d837d8dc842719d9fec95764d8ceb'
FRA = '7b28c18c42cf4d44b6b65709148ec8e0'


class ReviewedOctober24Amendments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = sam_reviewed.validate_config(json.loads(
            (ROOT / 'config/sam_gov.json').read_text(encoding='utf8')))
        cls.approvals = {item['notice_id']: item for item in config['approved_notices']}
        cls.snapshots = json.loads((ROOT / 'tests/fixtures/sam_amendments_reviewed_20261024.json')
                                   .read_text(encoding='utf8'))

    def record(self, identifier, as_of=date(2026, 10, 24)):
        (record, reasons), _ = sam_reviewed.reconcile_notice(
            self.snapshots[identifier], self.approvals[identifier], as_of)
        return record, reasons

    def test_new_reviews_bind_exact_current_versions_without_duplicate_old_approvals(self):
        self.assertEqual(set(self.snapshots), {FAA, NGA, FRA})
        self.assertEqual(len(self.approvals), 42)
        for old in ('e3d96ffd4a0a48b080e09dd5af732cc8',
                    '4984511e4bbc4d01a21df55b30a88f02',
                    '45850d5326944be1b187cece69fe7790'):
            self.assertNotIn(old, self.approvals)
        for identifier in (FAA, NGA, FRA):
            with self.subTest(identifier=identifier):
                approval = self.approvals[identifier]
                self.assertEqual(approval['verified_on'], '2026-10-24')
                self.assertEqual(approval['reviewed_snapshot'], self.snapshots[identifier])
                record, reasons = self.record(identifier)
                self.assertEqual(reasons, [])
                self.assertEqual(record['status'], 'posted')
                self.assertEqual(record['opportunity_id'], 'sam-gov:' + identifier)
                self.assertEqual(record['sam_review_reconciliation']['reviewed_on'], '2026-10-24')

    def test_faa_qa_confirms_brief_deadline_without_opening_invited_proposal_route(self):
        record, _ = self.record(FAA)
        selected = project(record, date(2026, 10, 24))['next_submission']
        self.assertEqual((selected['date'], selected['event']['time'], selected['event']['timezone']),
                         ('2026-11-02', '18:00', 'America/New_York'))
        self.assertEqual(selected['event']['kind'], 'concept_paper')
        self.assertTrue(selected['event']['required'])
        self.assertTrue(record['deadlines'][1]['invitation_required'])
        self.assertIsNone(record['deadlines'][1]['date'])
        self.assertIn('no required cost sharing', record['description'])
        self.assertIn('unrestricted teaming', record['description'])
        expired, reasons = self.record(FAA, date(2026, 11, 3))
        self.assertIn('entry_closed', reasons)
        self.assertEqual(expired['status'], 'expired')

    def test_nga_qa_keeps_required_abstract_and_does_not_offer_december_as_new_entry(self):
        record, reasons = self.record(NGA)
        self.assertEqual(reasons, [])
        self.assertEqual([event['date'] for event in record['deadlines']],
                         ['2026-10-28', '2026-12-21'])
        self.assertTrue(record['deadlines'][0]['required'])
        self.assertEqual(record['deadlines'][0]['timezone'], 'Etc/GMT+5')
        self.assertFalse(record['deadlines'][1]['invitation_required'])
        self.assertIn('Foreign nationals require written approval before performing work', record['description'])
        self.assertIn('no new field collection', record['description'])
        self.assertIn('conflicting budget figure', record['description'])
        expired, reasons = self.record(NGA, date(2026, 10, 29))
        self.assertIn('entry_closed', reasons)
        self.assertEqual(expired['status'], 'expired')

    def test_fra_second_amendment_excludes_six_closed_topics_and_preserves_remaining_call(self):
        record, reasons = self.record(FRA)
        self.assertEqual(reasons, [])
        selected = project(record, date(2026, 10, 24))['next_submission']
        self.assertEqual((selected['date'], selected['event']['kind']),
                         ('2027-09-30', 'concept_paper'))
        self.assertTrue(record['deadlines'][1]['invitation_required'])
        for topic in ('003', '004', '005', '006', '007', '009'):
            self.assertIn('FRA-TR-' + topic, record['deadlines'][0]['note'])
        self.assertIn('these six topics are excluded', record['description'])
        self.assertIn('Remaining track topics are FRA-TR-001, FRA-TR-002, FRA-TR-008, and FRA-TR-010',
                      record['description'])
        self.assertIn('universities or institutions of higher education', record['eligibility_text'])


if __name__ == '__main__':
    unittest.main()
