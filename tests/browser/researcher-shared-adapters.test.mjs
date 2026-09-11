import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {context} from '../helpers/shared-team-inputs.mjs';
test('every canonical department/institution profile reaches Team Match with the same summary, claims and shared facets', () => {
  const c = context();
  for (const file of ['data/researcher_directory.js', 'data/faculty_matches.js']) vm.runInContext(fs.readFileSync(file, 'utf8'), c);
  const page = fs.readFileSync('team_match.html', 'utf8');
  vm.runInContext('var faculty = FACULTY_MATCHES.faculty, names = Object.keys(faculty), facultyKeyById = {}; function externalProfile() {return null;}', c);
  for (const name of ['foldedName', 'directoryFacultyKey', 'memberProfile']) vm.runInContext(page.match(new RegExp('  function ' + name + '\\([^]*?\\n  }'))[0], c);
  for (const p of c.RESEARCHER_DIRECTORY.researchers) {
    const key = c.directoryFacultyKey(p), actual = c.memberProfile(key), expected = c.FUNDING_TEAM_MATCHER.normalizeProfile(p);
    for (const field of ['researcher_id', 'research_summary', 'summary_evidence', 'key_terms', 'capability_phrases', 'domains', 'claims']) assert.deepEqual(actual[field], expected[field], `${p.id}: ${field}`);
    assert.equal(c.directoryFacultyKey(p), key, 'canonical identity is stable on repeat normalization');
    assert.equal(actual.researcher_id, p.id);
  }
});
