"""P11 workflow scope and failure-routing contracts."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "refresh-opportunities.yml"
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


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

    def test_push_ci_uses_the_same_live_product_measurement_boundary(self):
        source = TEST_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python -m tools.run_refresh_validation", source)
        self.assertNotIn("unittest discover", source)

    def test_document_degradation_routes_to_the_existing_degraded_channel(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("steps.document_evidence.outcome == 'failure'", source)
        self.assertIn("steps.additional-sources.outcome == 'failure'", source)
        self.assertIn("document evidence/subtopic classification", source)
        self.assertIn("External funding source refresh degraded", source)
        self.assertIn("if: failure()", source)


if __name__ == "__main__":
    unittest.main()
