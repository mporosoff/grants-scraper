import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';

// Preserve the historical byte-freeze records. The authorized allocation-only
// hunk has a complete real-input parity receipt; every other byte stays frozen.
export function preservedMatcherBytes(path, bytes) {
  if (path === 'assets/search-retrieval.js') {
    const sourceReview = '    const reviewAfter = record.source_review_after;\n'
      + '    if (reviewAfter && (typeof reviewAfter !== "string" || !/^\\d{4}-\\d{2}-\\d{2}$/.test(reviewAfter)\n'
      + '      || !Number.isFinite(Date.parse(`${reviewAfter}T00:00:00Z`))\n'
      + '      || new Date(`${reviewAfter}T00:00:00Z`).toISOString().slice(0, 10) !== reviewAfter\n'
      + '      || reviewAfter < today)) return false;\n';
    const currentSource = bytes.toString('utf8');
    assert.equal(currentSource.split(sourceReview).length, 2,
      'The bounded source-review expiry correction must appear exactly once');
    const source = currentSource.replace(sourceReview, '');
    assert.equal(createHash('sha256').update(source).digest('hex'),
      '26d8f814b7f6a21d5c14272da28565d4513b2b1b632d8c68968245ca58ed732d',
      'Every byte outside the exact source-review expiry correction remains preserved');
    const currentness = '    const schedule = globalThis.FUNDING_SUBMISSION_SCHEDULE;\n'
      + '    if (typeof schedule?.administrativeSubmissionClosed === "function") {\n'
      + '      if (schedule.administrativeSubmissionClosed(record, today)) return false;\n'
      + '    } else if ([...(record.deadlines || []), ...(record.submission_requirements || [])]\n'
      + '      .some(event => event?.date_qualifier === "administrative")) {\n'
      + '      throw new Error("Funding currentness requires the shared administrative submission schedule.");\n'
      + '    }\n';
    assert.equal(source.split(currentness).length, 2);
    return Buffer.from(source.replace(currentness, ''));
  }
  if (path !== 'assets/team-matcher.js') return bytes;
  assert.equal(createHash('sha256').update(bytes).digest('hex'),
    '4bcfb19d7399f72cd1fff32f2aa58f54b5e7a64d45695c564867b39b1259c020',
    'Only the exact allocation optimization in matcher-allocation-parity-20260915.json is admitted');
  const optimized = '      // Proximity is only consulted when the minimum group coverage is met.\n'
    + '      for (let start = 0; matchedGroups >= needed && !proximity && start < prepared.tokens.length; start += 1) {';
  const original = '      for (let start = 0; !proximity && start < prepared.tokens.length; start += 1) {';
  const source = bytes.toString('utf8');
  assert.equal(source.split(optimized).length, 2);
  return Buffer.from(source.replace(optimized, original));
}
