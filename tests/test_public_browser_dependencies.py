"""Actual browser import closure must survive immutable assembly and Pages staging."""
import json
from pathlib import Path
import re
import unittest
from tools import release_candidate as candidate
from tools.verify_release_live import PUBLIC_BROWSER_IMPORTS, public_path, pages_path

ROOT = Path(__file__).resolve().parents[1]


class PublicBrowserDependencyTests(unittest.TestCase):
    def test_actual_dod_browser_imports_are_packaged_and_served(self):
        seen, pending = set(), ['assets/dod-awards-browser.mjs']
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            if not name.endswith(('.js', '.mjs')):
                continue
            text = (ROOT / name).read_text(encoding='utf-8')
            for relative in re.findall(r'from\s+["\'](\.[^"\']+)["\']', text):
                path = ((ROOT / name).parent / relative.split('?')[0]).resolve()
                pending.append(path.relative_to(ROOT).as_posix())
        external = seen - {'assets/dod-awards-browser.mjs'}
        self.assertEqual(external, PUBLIC_BROWSER_IMPORTS)
        policy = json.loads((ROOT / candidate.POLICY).read_text())
        packaged = set(candidate.paths(ROOT, policy['runtime'] + policy['package']))
        runtime_dependencies = set(candidate.paths(ROOT, policy['dependency_groups']['runtime']['patterns']))
        for name in external:
            with self.subTest(name=name):
                self.assertIn(name, packaged)
                self.assertIn(name, runtime_dependencies)
                self.assertTrue(public_path(name))
                self.assertTrue(pages_path(name))
                candidate.privacy_check(ROOT / name)

    def test_other_worker_and_configuration_files_remain_unpublished(self):
        for name in ['workers/award-api/src/index.js', 'workers/award-api/wrangler.jsonc',
                     'workers/search-voyage-proxy/src/index.js', 'config/offline_ai.json',
                     'config/researcher_registry.json', 'outputs/private-response.json']:
            with self.subTest(name=name):
                self.assertFalse(public_path(name))
                self.assertFalse(pages_path(name))
