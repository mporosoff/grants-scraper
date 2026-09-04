"""P11 workflow scope and failure-routing contracts."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "refresh-opportunities.yml"
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
MANUAL_E2E_WORKFLOW = ROOT / ".github" / "workflows" / "e2e-manual.yml"


class P11WorkflowTests(unittest.TestCase):
    def steps(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        return [
            "      - name:" + block
            for block in source.split("      - name:")[1:]
        ]

    def document_step(self):
        return next(step for step in self.steps() if "id: document_evidence" in step)

    def test_anthropic_secret_is_exposed_only_to_document_evidence(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(source.count("secrets.ANTHROPIC_API_KEY"), 1)
        document = self.document_step()
        self.assertIn(
            "        env:\n          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}",
            document,
        )
        for step in self.steps():
            if "id: document_evidence" in step:
                continue
            self.assertNotIn("ANTHROPIC_API_KEY", step)
        job_preamble = source.split("      - name:", 1)[0]
        self.assertNotIn("ANTHROPIC_API_KEY", job_preamble)

    def test_document_step_enables_topics_with_two_explicit_budgets(self):
        document = self.document_step()
        self.assertIn("--enable-subtopics", document)
        self.assertIn("--max-documents 45", document)
        self.assertIn("--max-subtopic-documents 30", document)
        self.assertIn("continue-on-error: true", document)

    def test_post_refresh_gate_preserves_closed_measurement_frames(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(
            source.count("python -m tools.run_refresh_validation"),
            2,
        )
        self.assertNotIn("unittest discover", source)
        self.assertIn('"tools/run_refresh_validation.py"', source)

    def test_protected_ci_uses_the_same_live_product_measurement_boundary(self):
        source = TEST_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python -m tools.run_refresh_validation", source)
        self.assertNotIn("unittest discover", source)

    def test_tests_workflow_runs_once_per_pr_head_and_again_on_main(self):
        source = TEST_WORKFLOW.read_text(encoding="utf-8")
        manual_e2e = MANUAL_E2E_WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(
            source,
            re.compile(
                r"^on:\n  pull_request:\n  push:\n    branches:\n      - main$",
                re.MULTILINE,
            ),
        )
        self.assertIn(
            "concurrency:\n"
            "  group: tests-${{ github.event.pull_request.number || github.ref }}\n"
            "  cancel-in-progress: true",
            source,
        )
        for job in ("python", "browser"):
            self.assertRegex(source, rf"(?m)^  {job}:$")
        for command in (
            "python -m tools.run_refresh_validation",
            "bash tools/verify_no_drift.sh",
            "node --test tests/browser/*.test.mjs",
            "node tools/query_baseline.mjs --check",
            "node tools/p9_scoring_probe.mjs --check",
        ):
            self.assertIn(command, source)
        self.assertNotRegex(source, r"(?m)^  e2e:$")
        self.assertNotIn("playwright", source.lower())
        self.assertNotIn("pnpm test:e2e", source)
        self.assertRegex(manual_e2e, r"(?m)^on:\n  workflow_dispatch:$")
        self.assertNotIn("pull_request:", manual_e2e)
        self.assertNotRegex(manual_e2e, r"(?m)^  push:$")
        self.assertRegex(manual_e2e, r"(?m)^  e2e:$")
        self.assertIn("pnpm exec playwright install --with-deps chromium", manual_e2e)
        self.assertIn("pnpm test:e2e", manual_e2e)

    def test_document_degradation_routes_to_the_existing_degraded_channel(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("steps.document_evidence.outcome == 'failure'", source)
        self.assertIn("steps.additional-sources.outcome == 'failure'", source)
        self.assertIn("document evidence/subtopic classification", source)
        self.assertIn("External funding source refresh degraded", source)
        self.assertIn("if: failure()", source)


if __name__ == "__main__":
    unittest.main()
