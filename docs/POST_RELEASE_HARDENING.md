# Funding Finder v1.2.1 post-release hardening

Status: release candidate passed; production and protected-refresh closeout in
progress on August 24, 2026.

## Release boundary

This release hardens the accepted v1.2.0 Strong + Potential architecture. It
does not introduce a new provider, model family, scientific ontology,
query-time classifier, vector database, or relevance definition. Phase 4C was
not rerun; its frozen artifacts remain historical evidence for the architecture
at their recorded SHA.

Starting repository SHA:
`505af687c9b3620454371de475ffe7c2adb176d6`. The four implementation checkpoints
are recorded in `evaluation/post_release_hardening_session1.json` through
`evaluation/post_release_hardening_session4.json`.

## Atomic publication lifecycle

The scheduled refresh builds the complete candidate in its workflow workspace:

1. refresh, enrich, and merge the catalog and additional sources;
2. rebuild evidence, subtopics, Team Match data, feeds, changes, and link state;
3. construct the exact public semantic passage corpus;
4. embed every current passage with one production model contract;
5. embed and compare the fixed public model-space canaries;
6. generate the manifest, vector binary, release handshake, and
   current/previous Worker allowlist;
7. run Python, browser, search-quality, package-integrity, and drift gates;
8. deploy and health-check the compatibility Worker;
9. atomically commit all generated release artifacts; and
10. verify the GitHub Pages package and Worker handshake.

Any failed build, gate, deployment, or handshake stops publication and leaves
the prior live package authoritative. A GitHub issue identifies the failed
stage and the live/candidate corpus where possible.

Production rebuilds never reuse passage vectors. The release package admits
only the current and immediately previous corpus, which supports both old and
new browsers while Pages propagates. A third or older generation is rejected.

## Hosted-service controls

The Worker circuit breaker is `ENHANCED_SEARCH_ENABLED`. Production controls
are centralized in `workers/search-voyage-proxy/wrangler.jsonc`:

| Control | Production value |
| --- | ---: |
| Daily embedding-token budget | 50,000 |
| Daily reranking-token budget | 25,000,000 |
| Per-client embed requests | 12 per 60 seconds |
| Per-client rerank requests | 8 per 60 seconds |
| Global Worker requests | 600 per 60 seconds |
| Retry-After | 10 seconds |

Missing or invalid budget configuration disables enhanced search before any
provider call. The Durable Object stores only daily request/token/failure and
latency counters. It does not store queries, candidate passages, IP addresses,
researcher names, profile/CV/ORCID content, or publication text. Rate-limit
bindings use ephemeral request keys; raw identifiers are not persisted by
application code.

## Product contracts

Strong matching remains local. Hosted Potential matching sends the submitted
Funding Finder query with a bounded set of public opportunity passages. Team
Match may send one bounded aggregate of selected keywords and theme labels,
but never names or full publication text. User-connected OpenAI/Anthropic tools
remain a separate explicit path using the key and bounded context the user
chooses.

Query, currentness, and filters determine membership. Sorting changes only the
order within Strong and Potential tiers, with Strong always first. Filter
eligibility is applied before BM25 selection, semantic top-k, fusion, and
reranking. Sort changes reuse the hybrid result; substantive filter changes
create one new bounded hybrid cycle.

Funding Finder distinguishes Potential success, an eligible empty result,
loading, service failure, rate/budget limiting, and a mixed-package failure.
Team Match reports local-order fallback without changing every-researcher fit.

## Catalog and card correctness

- Catalog records take precedence over VPR/Cindy email records after normalized
  solicitation-number, exact-title, and conservative canonical-title checks.
- Allowlisted private-funder pages may fill missing sponsor, synopsis,
  eligibility, deadline, and award fields. Failed or blocked page retrieval
  preserves email fields and does not fail the email source.
- Grants.gov 2076/2099 lifecycle placeholders are removed in the XML, detail
  API, and cached enrichment paths. "Accepted anytime" becomes rolling.
- Long-range dates within the bounded real-date window remain intact.
- Card actions use concise labels and wrap on narrow screens.

Known source limitation: ACS currently serves an Incapsula challenge and Sony
may return HTTP 403 to unattended refreshes. Those records retain parsed email
fields and sponsor identity; other allowlisted public pages enrich when usable.

## Validation evidence

The Session 4 production generation contains 1,659 passages, one
`voyage-4-lite` model/response string, one 1,024-dimensional float16 output
contract, no reused vectors, and model-space fingerprint
`6bdf01ea5729f7d7a770b8ed4f357537207cc13ba3b95385c63c7a144eb437bd`.
The six canaries passed at minimum/mean cosine 1.0.

The 52-query spent/development gate achieved Strong reviewed precision 1.000,
combined Recall@10/20/50 of 0.862/0.908/0.954, and nDCG@10 of 0.774. Cold
first-use latency was 1.103 seconds and warm p50/p95 was 0.636/0.812 seconds.
The release passed 769 live-product Python tests, 214 browser tests, the
37-query historical baseline with zero top-ten churn, and the 50-case P9
invariant byte-for-byte.

## Rollback

Semantic-service rollback does not require reverting fresh catalog data:

1. set `ENHANCED_SEARCH_ENABLED` to `false` in the Worker environment and
   deploy the same package;
2. if needed, clear the browser production proxy/feature flag in application
   configuration;
3. verify Funding Finder shows Strong results and Team Match shows local order.

To restore a known compatible Worker version, from
`workers/search-voyage-proxy/` run:

```powershell
npx --yes wrangler@4.125.0 versions deploy <prior-version-id>@100% -y
```

For a full code rollback, revert only the application/workflow commit, rebuild
the release package, and deploy the matching current/previous Worker allowlist.
Do not pair a catalog with an unrelated passage manifest or vector binary.
Validated current catalog/evidence/feed data should be retained whenever its
release hashes remain compatible.

## Release closeout

The final release record will be
`evaluation/post_release_hardening_closeout.json`. It records the final SHA,
Worker version, live current/previous corpus handshake, protected-branch state,
manual refresh result, live UI smokes, and the exact prior Worker rollback
target.
