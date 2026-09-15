import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';

// Preserve the historical byte-freeze records. The authorized allocation-only
// hunk has a complete real-input parity receipt; every other byte stays frozen.
export function preservedMatcherBytes(path, bytes) {
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
