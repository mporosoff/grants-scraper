"""Explicit deadline replay cannot enter source or paid-generation routes."""
from pathlib import Path
import os
import unittest
from unittest.mock import patch

import yaml

from tools import program_area_release as bridge, release_candidate as c


class AdministrativeSubmissionRelease(unittest.TestCase):
    def environment(self, **changes):
        return {"GITHUB_REPOSITORY": "mporosoff/grants-scraper",
            "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_WORKFLOW_REF": "mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main",
            "REQUESTED_STAGE": "submission-revalidation", "CANDIDATE_RUN": "123456",
            "CANDIDATE_ID": "a" * 64, **changes}

    def test_named_original_and_projection_survive_routing_without_provider_authority(self):
        with patch.object(c, "git", return_value="b" * 40):
            value = bridge.plan(Path("."), self.environment())
        self.assertEqual((value["candidate_run"], value["candidate_id"]), ("123456", "a" * 64))
        self.assertEqual((value["stage"], value["program_area_mode"], value["projection_kind"]),
            ("program-area-revalidation", "modern", "administrative_submission"))
        self.assertEqual((value["openai"], value["anthropic"]), ("false", "false"))

    def test_unknown_mixed_or_legacy_selectors_fail_before_checkout(self):
        cases = [dict(REQUESTED_STAGE="unsupported"), dict(QUALIFICATION_PILOT="true"),
            dict(RECEIPT_RUN="9"), dict(PUBLICATION_RUN="9"), dict(PUBLICATION_ATTEMPT="2"),
            dict(GITHUB_EVENT_NAME="schedule"), dict(CANDIDATE_RUN=""), dict(CANDIDATE_ID="a" * 63),
            dict(CANDIDATE_RUN=str(bridge.recovery.PARENT_RUN), CANDIDATE_ID=bridge.recovery.PARENT_CANDIDATE)]
        for change in cases:
            with self.subTest(change=change), patch.object(c, "git") as git:
                with self.assertRaises(ValueError): bridge.plan(Path("."), self.environment(**change))
                git.assert_not_called()

    def test_existing_program_area_selector_keeps_its_original_projection(self):
        with patch.object(c, "git", return_value="b" * 40):
            result = bridge.plan(Path("."), self.environment(REQUESTED_STAGE="program-area-revalidation"))
        self.assertEqual(result["projection_kind"], "program_area")

    def test_bridge_cannot_route_explicit_replay_into_ordinary_auto_generation(self):
        from tools import catalog_correction_release as existing
        environment = self.environment(RUNNER_TEMP=".")
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(bridge, "plan", return_value={"stage": "program-area-revalidation", "projection_kind": "administrative_submission"}) as explicit, \
                patch.object(existing, "atomic_json") as write, patch.object(existing, "output"), \
                patch("tools.plan_release.main") as ordinary:
            existing.plan()
        explicit.assert_called_once_with(existing.ROOT, environment)
        write.assert_called_once()
        ordinary.assert_not_called()

    def test_workflow_binds_the_selected_projection_and_reuses_only_budgeted_vector_route(self):
        workflow = yaml.safe_load((c.ROOT / ".github/workflows/refresh-opportunities.yml").read_text(encoding="utf-8"))
        events = workflow.get("on", workflow.get(True))
        self.assertIn("submission-revalidation", events["workflow_dispatch"]["inputs"]["stage"]["options"])
        plan = workflow["jobs"]["plan"]
        self.assertEqual(plan["outputs"]["projection_kind"], "${{ steps.plan.outputs.projection_kind }}")
        job = workflow["jobs"]["program-area-revalidation"]
        steps = {step["id"]: step for step in job["steps"] if step.get("id")}
        self.assertEqual(steps["prepare"]["env"]["EVIDENCE_PROJECTION_KIND"], "${{ needs.plan.outputs.projection_kind }}")
        self.assertIn('--projection-kind "$EVIDENCE_PROJECTION_KIND"', steps["prepare"]["run"])
        self.assertNotIn("needs.plan.outputs.projection_kind", steps["modern-vectors"]["if"])
        self.assertIn("steps.prepare.outputs.vector_reused != 'true'", steps["modern-vectors"]["if"])
        self.assertIn("steps.modern-reservation-upload.outcome == 'success'", steps["modern-vectors"]["if"])
        self.assertEqual([step["id"] for step in job["steps"] if "VOYAGE_API_KEY" in step.get("env", {})], ["vectors", "modern-vectors"])
        self.assertIn("steps.prepare.outputs.modern != 'true'", steps["vectors"]["if"])
        self.assertTrue(steps["modern-state-upload"]["with"]["include-hidden-files"])


if __name__ == "__main__":
    unittest.main()
