"""P11 workflow scope and failure-routing contracts."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "refresh-opportunities.yml"


class P11WorkflowTests(unittest.TestCase):
    def workflow(self):
        return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def steps(self):
        return self.workflow()["jobs"]["refresh"]["steps"]

    def test_anthropic_secret_is_exposed_only_to_document_evidence(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(source.count("secrets.ANTHROPIC_API_KEY"), 1)
        document = next(
            step for step in self.steps() if step.get("id") == "document_evidence"
        )
        self.assertEqual(
            document.get("env"),
            {"ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}"},
        )
        for step in self.steps():
            if step.get("id") == "document_evidence":
                continue
            self.assertNotIn("ANTHROPIC_API_KEY", str(step))
        self.assertNotIn("env", self.workflow()["jobs"]["refresh"])

    def test_document_step_enables_topics_with_two_explicit_budgets(self):
        document = next(
            step for step in self.steps() if step.get("id") == "document_evidence"
        )
        command = document["run"]
        self.assertIn("--enable-subtopics", command)
        self.assertIn("--max-documents 45", command)
        self.assertIn("--max-subtopic-documents 45", command)
        self.assertTrue(document["continue-on-error"])

    def test_document_degradation_routes_to_the_existing_degraded_channel(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("steps.document_evidence.outcome == 'failure'", source)
        self.assertIn("steps.additional-sources.outcome == 'failure'", source)
        self.assertIn("document evidence/subtopic classification", source)
        self.assertIn("External funding source refresh degraded", source)
        self.assertIn("if: failure()", source)


if __name__ == "__main__":
    unittest.main()
