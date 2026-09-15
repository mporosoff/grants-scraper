"""Exercise the actual Funded Awards import closure through the Pages filter."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import urlsplit

from tools import release_candidate as c
from tools.verify_release_live import PUBLIC_BROWSER_IMPORTS, pages_path


class PublicBrowserImports(unittest.TestCase):
    def test_actual_transitive_imports_are_assembled_and_staged_without_other_worker_code(self):
        root = Path(__file__).resolve().parents[1]
        policy = json.loads((root / c.POLICY).read_text(encoding='utf-8'))
        pending, visited = ['assets/dod-awards-browser.mjs'], set()
        while pending:
            name = pending.pop()
            if name in visited:
                continue
            visited.add(name)
            text = (root / name).read_text(encoding='utf-8')
            if name.endswith('.json'):
                json.loads(text)
                continue
            for specifier in re.findall(r'\bfrom\s+[\'"]([^\'"]+)[\'"]', text):
                self.assertTrue(specifier.startswith('.'), specifier)
                target = (root / name).parent / urlsplit(specifier).path
                pending.append(target.resolve().relative_to(root).as_posix())
        self.assertEqual(visited - {'assets/dod-awards-browser.mjs'}, PUBLIC_BROWSER_IMPORTS)
        with tempfile.TemporaryDirectory() as folder:
            staged = Path(folder)
            for name in visited:
                self.assertTrue(pages_path(name), name)
                self.assertTrue(any((root / name) in root.glob(pattern) for pattern in policy['runtime']), name)
                target = staged / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((root / name).read_bytes())
                self.assertEqual(c.digest(target.read_bytes()), c.digest((root / name).read_bytes()))
            for name in ('workers/award-api/src/index.js', 'workers/award-api/wrangler.jsonc',
                         'workers/researcher-intake/src/index.js', 'config/offline_ai.json'):
                self.assertFalse(pages_path(name), name)
                self.assertFalse((staged / name).exists())
