"""The release owner alone supplies the validated Pages artifact."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class PagesDeploymentWorkflowTests(unittest.TestCase):
    def test_pages_has_only_a_called_entrypoint_and_no_checkout(self):
        pages = (ROOT / '.github/workflows/pages.yml').read_text()
        self.assertIn('workflow_call:', pages)
        self.assertNotIn('  push:', pages)
        self.assertNotIn('  workflow_dispatch:', pages)
        self.assertNotIn('actions/checkout', pages)
        self.assertIn('actions/deploy-pages@v5', pages)
        self.assertIn('name: github-pages', pages)
        for permission in ('contents: read', 'pages: write', 'id-token: write'):
            self.assertIn(permission, pages)

    def test_owner_packages_exact_candidate_only_after_validation_worker_and_protected_merge(self):
        workflow = (ROOT / '.github/workflows/refresh-opportunities.yml').read_text()
        ordered = ['tools.validate_release_candidate', 'Deploy changed Worker inputs',
                   'tools.publish_release_candidate', 'tools.verify_release_live stage',
                   'actions/upload-pages-artifact@v5', 'uses: ./.github/workflows/pages.yml']
        positions = [workflow.index(value) for value in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('group: funding-finder-coordinated-release', workflow)
        self.assertIn('path: ${{ runner.temp }}/site', workflow)
        staging = (ROOT / 'tools/verify_release_live.py').read_text()
        self.assertIn("publication['publication_sha']", staging)
        self.assertIn('pages-release-sha.txt', staging)
        self.assertIn('c.verify_files(output,', staging)
