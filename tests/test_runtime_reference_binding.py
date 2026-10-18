"""Retained team data and current HTML form one deterministic runtime package."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.import_opportunity_team_model import CONTENT_HASHED_ASSETS, VERSIONED_ASSETS
from tools.assemble_release_candidate import bind_runtime_references
from tools import release_dependencies as dependencies, release_candidate as candidate


ROOT = Path(__file__).resolve().parents[1]


class RuntimeReferenceBinding(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.generation = 'b' * 64
        for name in (*CONTENT_HASHED_ASSETS, *VERSIONED_ASSETS):
            self.write(name, ('retained data or current runtime: ' + name).encode())
        self.write('assets/opportunity-team.js', (ROOT/'assets/opportunity-team.js').read_bytes())
        self.write('config/opportunity_team_model.json', json.dumps({'generation_id': self.generation}).encode())
        self.write('data/opportunity_team_index.js',
                   ('globalThis.OPPORTUNITY_TEAM_INDEX=' + json.dumps({
                       'schema_version': 1, 'generation_id': self.generation, 'scope_count': 0, 'scopes': []}) + ';').encode())
        for page in ('team_match.html', 'match_explorer.html'):
            self.write(page, ('<meta name="opportunity-team-generation" content="' + 'a'*64 + '">\n' +
                '\n'.join('<script src="' + name + '?v=old"></script>'
                          for name in (*VERSIONED_ASSETS, *CONTENT_HASHED_ASSETS))).encode())

    def write(self, name, raw):
        path = self.root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)

    def files(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def availability(self):
        script = r'''
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=process.argv[1];
const html=fs.readFileSync(path.join(root,'match_explorer.html'),'utf8');
const marker=html.match(/<meta name="opportunity-team-generation" content="([a-f0-9]+)"/)[1];
const context=vm.createContext({document:{querySelector:()=>({getAttribute:()=>marker})}});
for(const file of ['data/opportunity_team_index.js','assets/opportunity-team.js'])
  vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),context);
try{context.OpportunityTeam.availabilityIndex();process.stdout.write('accepted');}
catch(error){process.stdout.write(error.message);}
'''
        return subprocess.check_output(['node', '-e', script, str(self.root)], text=True, timeout=30)

    def test_actual_runtime_rejects_old_marker_then_accepts_retained_generation_without_data_changes(self):
        before = self.files()
        self.assertEqual(self.availability(), 'The opportunity-team availability index is incompatible.')
        bind_runtime_references(self.root)
        self.assertEqual(self.availability(), 'accepted')
        after = self.files()
        self.assertEqual({n: raw for n, raw in after.items() if not n.endswith('.html')},
                         {n: raw for n, raw in before.items() if not n.endswith('.html')})
        for name in ('team_match.html', 'match_explorer.html'):
            html = after[name].decode()
            self.assertIn('content="' + self.generation + '"', html)
            for asset in VERSIONED_ASSETS:
                self.assertIn(asset + '?v=' + self.generation, html)
            for asset in CONTENT_HASHED_ASSETS:
                self.assertIn(asset + '?v=' + hashlib.sha256(after[asset]).hexdigest(), html)
        bind_runtime_references(self.root)
        self.assertEqual(self.files(), after)

    def test_new_faculty_bytes_rebind_without_changing_team_generation_or_other_data(self):
        bind_runtime_references(self.root)
        self.write('data/faculty_matches.js', b'recomputed deterministic faculty matches')
        before = self.files()
        bind_runtime_references(self.root)
        for name in ('team_match.html', 'match_explorer.html'):
            html = (self.root/name).read_text()
            self.assertIn('content="' + self.generation + '"', html)
            self.assertIn('data/faculty_matches.js?v=' + hashlib.sha256(before['data/faculty_matches.js']).hexdigest(), html)
        self.assertEqual({n: raw for n, raw in self.files().items() if not n.endswith('.html')},
                         {n: raw for n, raw in before.items() if not n.endswith('.html')})

    def test_missing_or_duplicate_production_markers_fail_closed(self):
        for page in ('team_match.html', 'match_explorer.html'):
            original = (self.root/page).read_bytes()
            for duplicate in (False, True):
                with self.subTest(page=page, duplicate=duplicate):
                    suffix = original.split(b'\n', 1)[1]
                    one = b'<meta name="opportunity-team-generation" content="' + b'a'*64 + b'">'
                    marker = one + one if duplicate else b''
                    self.write(page, marker + b'\n' + suffix)
                    with self.assertRaisesRegex(ValueError, 'Expected one opportunity-team generation marker'):
                        bind_runtime_references(self.root)
                    self.write(page, original)

    def test_missing_current_runtime_asset_fails_instead_of_skipping_binding(self):
        (self.root/'assets/search-hybrid.js').unlink()
        with self.assertRaises(FileNotFoundError):
            bind_runtime_references(self.root)

    def test_shared_binder_change_is_runtime_assembly_input_without_invalidating_generation(self):
        policy = json.loads((ROOT/candidate.POLICY).read_bytes())
        self.write(candidate.POLICY, json.dumps(policy).encode())
        self.write('.github/workflows/refresh-opportunities.yml', b'jobs: {generate: {steps: []}}')
        name = 'tools/assemble_release_candidate.py'
        self.write(name, b'def bind():\n    return 1\n')
        inventory = '\n'.join((candidate.POLICY, '.github/workflows/refresh-opportunities.yml', name))
        with patch.object(candidate, 'git', return_value=inventory):
            before = dependencies.snapshot(self.root)
            self.write(name, b'def bind():\n    return 2\n')
            changes = dependencies.changed_groups(before, dependencies.snapshot(self.root))
        self.assertIn(name, changes['runtime'])
        self.assertTrue(set(changes).isdisjoint(('source', 'teams', 'semantic')))
        self.assertFalse(any(dependencies.matches(name, pattern) for pattern in policy['runtime']))


if __name__ == '__main__':
    unittest.main()
