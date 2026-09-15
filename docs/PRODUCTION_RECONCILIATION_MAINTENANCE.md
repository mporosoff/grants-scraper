# Bounded production maintenance — September 15, 2026

This patch repairs release review readiness and the existing Funded Awards
browser package. It preserves the public prebuilt-team workflow and all model
routes. No audited-registry replacement or contextual-team activation is included.

Release run 34868137301 (#223) persisted candidate
`f56721d3e6bd4db720604414994614aa471b4d250b241f6e05dcc10fb1b76673`.
Its initial publication created PR249 but never requested a missing review.
The review wait expired after Worker deployment and required smoke; the captured
Worker version was restored and Pages was skipped. On September 15 the first
explicit review completed against `f01aa7c64c7e63c041c6558d28524e2341fa9df1`
with two consequential source-data findings: NSF 24-503/21-595 duplicate rows and
the prose fragment `vpr-email:vpr-7921302c954613de` misclassified as a call.
That immutable candidate remains blocked. This maintenance uses the currently
published catalog, preserving its original generation and limitations.

## Isolated changes

- Include the exact eight transitive public imports of `assets/dod-awards-browser.mjs`
  in candidate assembly, Pages staging and live hash verification. Original fix:
  `1673a0d517f25e80f6ab4efb6389a4e485bd6d12`; experimental ingredient imports excluded.
- Skip the Team Match proximity scan when its only consuming score branch cannot
  execute. Original optimization: `561fbd38fd1a94a11892eb165f8099f3d5365fa5`.
  No scientific gate, evidence output, ranking rule or network path changes.
- Obtain clean exact-head review before Worker changes or paid smoke. Check all
  review surfaces before requesting a missing initial review; never duplicate an
  acknowledged review. A stale publication branch advances without force-pushing,
  preserving both its previous head and current main as parents.
- Recheck candidate/receipt/base/review identity after compatibility checks and
  before protected merge. Preserve ordinary CI, rollback and live verification.
- Decode review JSON explicitly as UTF-8 on Windows. Report existing rerank smoke
  usage without introducing additional calls.

The existing dependency classifier assigns these changes to runtime/validation.
There are no source, semantic or team-generation changes. Acronym preparation
changes are deferred because the existing semantic-generation contract would
invalidate their purchased corpus; the manual vocabulary cache on main already
keys by profile context. The audited-profile consumer/data changes remain in
development because its registry guard invalidates existing legacy proposals.

## Fixed production-smoke authority and bounds

The existing [release lifecycle](RELEASE_LIFECYCLE.md) requires one pre-publication
and one post-Pages smoke. The standing hosted-search controls are documented in
[post-release hardening](POST_RELEASE_HARDENING.md) and were checked against fresh
authenticated serving-version metadata: 50,000 daily embedding tokens and
25,000,000 daily reranking tokens, with atomic Durable Object reservations.
This is the existing production search budget, separate from the frozen experiment.

Each unchanged smoke sends query `catalysis` once to `/embed-query` and one exact
shared public passage to `/rerank` for each of the current and previous corpora.
The invalid-corpus request must be rejected before provider dispatch. Neither
client POSTs nor Worker provider transport automatically retry. Thus the normal
publication uses at most six provider requests: two embeddings and four reranks.
Bounded health reads do not consume provider requests. An unsuccessful publication
is investigated before any additional smoke dispatch; this is not a retry allowance.

[Voyage pricing](https://docs.voyageai.com/docs/pricing), checked September 15,
2026: voyage-4-lite $0.02/million tokens; rerank-2.5 $0.05/million tokens.
Using the models' 32,000-token per-input context limit as a deliberately loose
upper bound gives at most $0.007680 for the six normal smoke requests. Actual
fixed packets are much smaller; report returned usage and do not assume free
credit. No request may debit or modify `on-demand-team-offline-v2-20260909`.

Exact review, CI, assembled-package integration and live results are recorded in
the reconciliation handoff when complete. Historical passes are not checks of
this patch, and this note is not a scientific release qualification.

The September 15 staged-package run executed all 117 configured E2E tests:
115 passed and two exposed test-setup defects. The mobile centering assertion
included the separate, correctly visible catalog-age warning; it now measures
the results area and also requires notices to remain above it. The accessibility
test mocked OpenAI but left the hosted provider selected; it now selects the
provider it mocks. No application bytes, assertions about accessible states,
timeouts or warning visibility were weakened. All 11 tests in the two affected
files then passed, including their accessibility scans. Unaffected observations
from the original run are reused, not counted as a second independent suite.
External DNS was blocked; provider responses were fixtures. Windows test-server
teardown required closing the verified local server before the runner emitted
its receipt. That infrastructure cleanup was not an application timeout fix.
