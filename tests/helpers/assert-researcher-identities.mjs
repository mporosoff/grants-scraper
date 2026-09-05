import assert from "node:assert/strict";

// Profile content and new identities may change through reviewed publication;
// existing identities must remain addressable by saved handoffs and claim refs.
export function assertResearcherIdentities(registry, baseline) {
  const researchers = new Map(registry.researchers.map(row => [row.researcher_id, row]));
  for (const prior of baseline.researchers) {
    const current = researchers.get(prior.researcher_id);
    assert.ok(current, `Missing stable researcher ${prior.researcher_id}`);
    for (const legacy of prior.legacy_ids) {
      assert.ok(current.legacy_ids.includes(legacy), `Reassigned legacy researcher ${legacy}`);
    }
    const claims = new Map(current.claims.map(claim => [claim.claim_id, claim]));
    for (const oldClaim of prior.claims) {
      const claim = claims.get(oldClaim.claim_id);
      assert.ok(claim, `Missing stable claim ${oldClaim.claim_id}`);
      assert.deepEqual(claim.legacy_claim_ids, oldClaim.legacy_claim_ids, `Reassigned legacy claim ${oldClaim.claim_id}`);
      assert.ok(claim.revision >= oldClaim.revision, `Regressed revision ${oldClaim.claim_id}`);
      if (claim.revision === oldClaim.revision) {
        assert.equal(claim.material_hash, oldClaim.material_hash, `Unversioned change ${oldClaim.claim_id}`);
      }
    }
  }
}
