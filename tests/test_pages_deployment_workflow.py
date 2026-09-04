"""Contracts for the repository-owned, Node 24 GitHub Pages deployment."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"


class PagesDeploymentWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_uses_current_official_node_24_pages_actions(self):
        self.assertIn("actions/checkout@v6", self.workflow)
        self.assertIn("actions/configure-pages@v6", self.workflow)
        self.assertIn("actions/upload-pages-artifact@v5", self.workflow)
        self.assertIn("actions/deploy-pages@v5", self.workflow)
        self.assertNotIn("actions/upload-artifact@v4", self.workflow)

    def test_deploys_main_and_supports_a_manual_recovery_run(self):
        self.assertIn("push:\n    branches:\n      - main", self.workflow)
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertIn("group: pages", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)

    def test_grants_the_minimum_pages_permissions(self):
        self.assertIn("contents: read", self.workflow)
        self.assertIn("pages: write", self.workflow)
        self.assertIn("id-token: write", self.workflow)
        self.assertIn("name: github-pages", self.workflow)

    def test_packages_the_existing_static_site_root(self):
        self.assertIn("actions/upload-pages-artifact@v5", self.workflow)
        self.assertIn("path: .", self.workflow)
        self.assertIn("steps.deployment.outputs.page_url", self.workflow)

    def test_stamps_the_exact_commit_inside_the_published_artifact(self):
        stamp = self.workflow.index("printf '%s\\n' \"$GITHUB_SHA\" > pages-release-sha.txt")
        package = self.workflow.index("actions/upload-pages-artifact@v5")
        deploy = self.workflow.index("actions/deploy-pages@v5")
        self.assertLess(stamp, package)
        self.assertLess(package, deploy)


if __name__ == "__main__":
    unittest.main()
