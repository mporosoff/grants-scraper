# Search and automatic proposed teams

Audit baseline: `072d2662f74798c74be6ffa70e227e1668ce10ec`, fetched from main on September 5, 2026. Work is isolated from the older validation checkout. Public team language is **Proposed Team**; routine proposals do not require owner review.

## Findings and changes

Funding Finder and Team Match share the actual Voyage hybrid client: fielded lexical retrieval, `voyage-4-lite` document/query embeddings with 1,024 dimensions, candidate fusion, and `rerank-2.5`. The document builder uses `input_type=document`; the query Worker uses `input_type=query`. The request shapes match [Voyage embeddings](https://docs.voyageai.com/reference/embeddings-api) and [reranking](https://docs.voyageai.com/reference/reranker-api). This audit does not change the models or replace semantic retrieval with keyword scoring.

The deployed Worker smoke passed embedding, current-generation reranking, previous-generation compatibility, and rejection of an unknown corpus. The release's vector and corpus fingerprints were matched. A passing API call verifies transport and contracts, not universal semantic relevance.

Team Match already required evidence for every selected person, including within an individual child topic before parent rollup. Its semantic search nevertheless searched the entire catalog before intersecting with that evidence. The updated coordinator passes the eligible parent IDs to the shared client so unrelated calls cannot consume the retrieval budget. It also passes profile context to the local acronym resolver, includes material profile context and eligibility in its cache identity, and refuses a bounded query that would silently omit a person. Researcher names and publication text are not sent as the hosted search query.

Both local and hosted Team Match now use existing source-supported capability phrases alongside claim labels. These phrases were already in the registry; no scientific expertise was invented. The local vocabulary cache also refreshes when the same profile object changes.

Team Builder previously required exactly ten scopes, four roles, and three or four initial members. Its scope count now follows the generated manifest. New proposals support two to six source-supported planning roles and two to four members, with up to three distinct, nonredundant alternatives. Role coverage and researcher IDs determine alternatives; permutations of the same people are deduplicated. Removing someone keeps that person excluded when switching options. New eligible researchers can appear as possible replacements through their current claims, with unconfirmed role coverage kept visible.

Broad parents still open a specific child-topic selector, as in the DEVCOM example. Programs without published children are screened for a bounded scientific topic before generating anything. Each child receives only its own text; sibling or parent prose cannot establish its role quotes. A second model pass independently checks suitability and claim-to-role attribution. Deterministic validation requires exact quotes, supplied claim IDs, current eligibility, and honest gaps. Model verification cannot upgrade an adjacent claim into covering evidence.

The browser check also found and fixed a DEVCOM navigation defect: matching an unsupported child previously hid the parent’s existing team choices. It now opens the parent topic selector; a supported matched child still opens its own proposal. Equal-coverage teams prioritize direct scientific evidence over method transfer. Both remain available as options, with transfer support explicitly labeled and exact replacement claim evidence displayed.

Profile publication previously rejected an approved scientific change whenever a pilot team used that researcher. The revised build marks affected proposals as needing revalidation while publishing the approved profile and unaffected teams. That state survives subsequent rebuilds. New generated proposals retain exact claim revisions and material hashes; unrelated claim additions do not revoke those exact edges. Changes to the scientific candidate pool queue automatic recomputation. Cosmetic changes do not alter that pool fingerprint.

## Automatic generation

`python -m scripts.build_opportunity_teams --write` performs provider-free invalidation and projection generation. The nightly refresh runs this before a bounded generation step, so provider failure cannot silently keep newly stale proposals active.

`python -m scripts.build_opportunity_teams --generate --max-scopes 10 --write` processes new, changed, or invalidated scopes. It uses the existing Anthropic model configuration to decompose the source before seeing any researcher claims, Voyage document/query embeddings to retrieve current claims, and independent adjudication and verification. Only anonymous claim IDs, public scientific labels/evidence, and public opportunity text go to the model. API keys remain in the process environment. Responses are cached by exact inputs and prompts. Completed negative decisions are recorded so an ineligible first page cannot monopolize every nightly run.

Generated alternatives stay inside their opportunity, so they do not inflate search counts. Existing reviewed pilot conclusions remain the regression benchmark. Public wording does not require visitors or the owner to review every proposed team; missing expertise and unconfirmed replacement coverage remain visible.

The generation queue uses cosine similarity against current researcher claims and admits at most three topics from one parent per run. Scope vectors are cached individually, so each nightly run does not re-embed the unchanged catalog. A 15-minute soft budget and 20-minute workflow limit bound this optional step. Size checks validate both browser projections before overwriting output files.

The initial 100-scope calibration accepted 31 proposals, rejected 61 nonspecific scopes and one unsuitable scope, found insufficient evidence for two, and withheld five invalid model responses. The subsequent 20-scope semantic calibration accepted three proposals, rejected 16 nonspecific scopes, and withheld one invalid JSON response. See `evaluation/proposed_team_catalog_initial_calibration.json` and `evaluation/opportunity_team_generation.json`. The resulting catalog has **44 usable scopes across 12 parent calls**, with **104 stored team combinations**; 32 scopes have multiple stored options. One earlier surveillance proposal remains withheld after failing the independent suitability check. The lazy team projection is approximately 354 KB uncompressed.

## Researcher catalog

The registry has 158 researchers and 432 active claims. There are 34 profiles with one retained claim and three with none. All retained claims contain evidence and source links. Thin profiles are a source-review priority, not evidence that the people lack other expertise. The first improvement is to consume their already retained evidence phrases rather than rely only on broad labels. No mass biography rewrite or automatic claim expansion is justified by claim counts alone.

`python -m tools.audit_researcher_coverage` produces the complete reproducible audit, including thin profiles and source links. `evaluation/team_public_data_verification.json` records the read-only verification that all eligible outgoing scientific claim text matches the publicly published directory.

## Validation boundary

The admin console now prepares catalog removals directly, with retired, departed, and inactive categories. Removal is an eligibility-only patch: research claims, source dates, stable IDs, and history stay unchanged. This avoids copying incomplete public evidence metadata into the registry. Departed and inactive profiles disappear from active matching and directory search; affected proposals are withheld until regenerated. The authenticated flow uses the existing approval, revision, rebase, publication, and recovery checks. D1 migration 0004 prevents duplicate active removals and retains the administrator category in the private audit record. No actual researcher was removed during implementation.

Use focused Python and browser contracts, frozen search canaries, exact generated-asset checks, and the required protected checks for the candidate SHA. Do not run E2E or Playwright suites. Calibration receipts report actual processed scopes and outcomes; rejected or failed generations are not counted as published teams. A local candidate is not evidence of a live deployment.

Manual browser checks exercised the DEVCOM selector, researcher removal and replacement choices, three generated team options, and the handoff into Team Match. The handoff preserved the selected people and successfully applied hosted semantic ordering to their eligible results. Focused contracts cover acronym ambiguity, scientific intent, child boundaries, profile corrections, exact claim revisions, eligible-set cache changes, provider failures, and projection identities. Full protected Python/browser CI and automated review are required on the committed candidate before merging.

The UI preservation fixtures refresh only the explicitly changed team/search functions and their owners; CSV, alerts, source selection, identity, and unrelated AI request snapshots remain unchanged. The selector loads current child publication eligibility before presenting choices, including when no child was initially selected. The frozen flag-off catalog rebuild and artifact-fingerprint comparison passed without changing historical measurement inputs.
