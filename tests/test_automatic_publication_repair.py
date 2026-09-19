"""Real publication failures and their bounded invariant families; no network."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import extract_document_evidence as e, notice_schedule
from scripts.submission_schedule import next_submission
from tools import prepare_release_publication as preparation, wait_release_review as review


FIXTURE = Path(__file__).parent / 'fixtures/parsing/doe-conditional-requirements.json'


class RequirementsRepair(unittest.TestCase):
    def extract(self, text):
        return e.extract_document_facts({'opportunity_id': 'fixture'},
            [{'text': text, 'page': 1}], {'url': 'https://example.gov/notice', 'sha256': 'fixture'},
            '2026-09-18T14:34:23.114218Z')

    def test_conditional_guidance_cannot_create_a_call_prerequisite(self):
        for condition in ('If required,', 'When applicable,', 'If selected,', 'Unless waived,'):
            with self.subTest(condition=condition):
                text = condition + ' you must submit a letter of intent to be eligible to submit an application.'
                self.assertFalse(any(f.get('stage') == 'letter_of_intent' for f in self.extract(text)))
                self.assertIsNone(notice_schedule.preliminary_requirement(text, 'letter of intent'))
        facts = self.extract('If required, you must submit a letter of intent. Letters of intent are required.')
        self.assertEqual([(f['required'], f['obligation']) for f in facts
                         if f.get('stage') == 'letter_of_intent'], [(True, 'required')])

    def test_owned_cost_share_field_answer_precedes_label_keyword(self):
        for term in ('cost share', 'cost sharing'):
            for answer, expected in (('No cost share for this project', False), ('None', False),
                                     ('Not required', False), ('Yes', True), ('20%', True),
                                     ('No less than 20%', True), ('No information available', None),
                                     ('See eligibility section', None)):
                with self.subTest(term=term, answer=answer):
                    found = [f for f in self.extract(f'Minimum {term} required: {answer}.')
                             if f['type'] == 'cost_share']
                    self.assertEqual([f['value'] for f in found], [] if expected is None else [expected])
            found = [f for f in self.extract(f'No {term} is required.') if f['type'] == 'cost_share']
            self.assertEqual([f['value'] for f in found], [False])

    def test_actual_doe_quotes_and_retained_receipts_reproject_without_requests(self):
        original = json.loads(FIXTURE.read_text(encoding='utf-8'))
        entry = deepcopy(original['entry'])
        for fact in entry['facts']:
            if fact['type'] not in {'cost_share', 'submission_requirement'}:
                continue
            extracted = self.extract(fact['citation']['quote'])
            self.assertFalse(any(f.get('stage') == 'letter_of_intent' for f in extracted))
            self.assertFalse(any(f['type'] == 'cost_share' and f['value'] is True for f in extracted))
        e.quarantine_legacy_facts(original['record'], {}, entry, None)
        merged = e.merge_document_entry(original['record'], entry)
        self.assertFalse(merged.get('submission_requirements'))
        self.assertEqual(next_submission(merged, '2026-09-18')['access'], 'open')
        cost = [f for f in entry['facts'] if f['type'] == 'cost_share']
        self.assertTrue(cost)
        self.assertTrue(all(f['value'] is False for f in cost))
        self.assertFalse(any(q['type'] == 'structured_fact_conflict'
                             for q in merged['document_evidence'].get('review_queue', [])))
        self.assertEqual(entry['checked_at'], original['entry']['checked_at'])
        self.assertEqual(entry['document'], original['entry']['document'])
        self.assertTrue(entry['parser_pending'])
        once = deepcopy(entry)
        e.quarantine_legacy_facts(original['record'], {}, entry, None)
        self.assertEqual(entry, once)


class AutomaticReviewRepair(unittest.TestCase):
    def test_bot_findings_with_exact_blob_links_are_terminal_and_fail_closed(self):
        head = 'a' * 40
        comment = {'user': {'login': review.BOT}, 'body':
            f'### Codex Review\nhttps://github.com/owner/repo/blob/{head}/feeds/changes.json#L148\n[P2] Conditional LOI'}
        with patch.object(review, 'api', return_value={'head': {'sha': head}, 'base': {'ref': 'main'}}), \
             patch.object(review, 'all_pages', side_effect=lambda p: [comment] if '/issues/' in p and p.endswith('/comments') else []), \
             patch.object(review, 'all_threads', return_value=[]):
            complete, findings = review.review_state('owner/repo', 1, head, '2026-09-18')
            self.assertTrue(complete)
            self.assertEqual(findings, [comment])
            with self.assertRaisesRegex(ValueError, 'findings'):
                review.wait_for_review('owner/repo', 1, head)
            comment['user']['login'] = 'someone-else'
            self.assertEqual(review.review_state('owner/repo', 1, head, '2026-09-18'), (False, []))

    def test_blob_review_identity_never_accepts_other_heads_repositories_or_acknowledgements(self):
        head = 'a' * 40
        for body in ('Codex Review Running', 'Codex Review Completed `aaaaaaa`',
                     f'Codex Review Running https://github.com/owner/repo/blob/{head}/x',
                     f'https://github.com/other/repo/blob/{head}/x',
                     f'https://github.com/owner/repo/blob/{"b" * 40}/x',
                     f'https://github.com/owner/repo/blob/{head}/x\nhttps://github.com/owner/repo/blob/{"b" * 40}/y'):
            with self.subTest(body=body):
                self.assertFalse(review.reviewed_head('owner/repo', body, head))

    def test_normal_review_gets_bounded_time_inside_existing_publication_timeout(self):
        with patch.object(preparation, 'prepare', return_value={'head_sha': 'a' * 40}) as prepare:
            with patch.dict('os.environ', {}, clear=True):
                preparation.prepare_or_defer('bundle', 'receipt', 'reports', '123')
        self.assertEqual(prepare.call_args.kwargs['review_timeout'], 1800)


if __name__ == '__main__':
    unittest.main()
