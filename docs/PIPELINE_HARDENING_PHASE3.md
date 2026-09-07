# Incremental processing contracts

The coordinated refresh still collects and normalizes sources, merges canonical
identities, reconciles supported structured details, extracts shared documents and
eligible topics, then builds searchable fields and researcher/team projections.
The developer intake commands in `scripts/sources/README.md` enter that same path.
Accepted inputs live in `config/source_intake.json`; fixtures live only in temporary
test workspaces. No consumer has an intake-specific opportunity ID.

## Passage vectors and release compatibility

`node tools/build_search_v2_voyage_vectors.mjs --production --write` validates the
entire previous manifest, binary length/hash, finite nonzero vectors, row order,
passage ownership, and canary artifact before considering reuse. Reusable rows
require exact text and ownership plus the complete configuration in
`tools/embedding_contract.mjs`: endpoint, model, dimensions, input mode,
truncation, preprocessing source hash, chunking, normalization, and encoding.

The production API does not supply an immutable provider revision in its documented
[embedding response](https://docs.voyageai.com/reference/embeddings-api).
The builder therefore records an **observed embedding-space identity**, using all
unrounded values of the six established public canaries and the complete
configuration. Matching an alias or passing the existing cosine gates alone never
authorizes reuse. Fresh batches include the same anchors and must match exactly
before their rows can be combined with prior cached rows. Small drift forces a
homogeneous rebuild. Independent floating outputs in an entirely fresh build may
vary within the unchanged gross-discontinuity gates, but that generation is marked
`reuse_permitted: false` and can never supply reusable rows. A mixed-generation
identity failure or a gross discontinuity blocks publication. The
existing minimum/mean cosine gates remain 0.95/0.98.

Legacy packages remain readable and deployable, but lack the new reuse proof and
are cold. `--force` explicitly rebuilds every current passage. Unchanged rows keep
their exact float16 bytes; removed passages disappear. Known misses share the
canary preflight request where possible. The request ceiling remains the prior
full-build allowance, `ceil(current_passages / 256) + 1`, with a corresponding
overall deadline. Exhaustion retains the committed/deployed release.

The receipt separates reused/missing/deleted passages, corpus requests, dedicated
canary-only requests, canary inputs (including anchors inside mixed requests),
tokens, and total requests. Counts for corpus and canary-bearing requests can
overlap when one request serves both purposes.

Writers stage the complete generation under an exclusive build lock and replace
the manifest last. A replacement failure restores prior files. A crashed process
leaves `.cache/semantic-build.lock` for developer inspection; after confirming
that no builder is active, restore the committed package and remove that lock.
Do not publish a partially written package: release integrity checks must pass.

The Worker allowlist selects by **corpus hash and space fingerprint** together.
It retains the immediately previous identity even when catalog text is unchanged
but the space changes. Existing public request fields and routes are preserved.

## Teams, dependencies, and bounded work

`python -m scripts.build_opportunity_teams --generate --write` withholds invalid
source and researcher dependencies before provider calls. Source decomposition
is keyed only by its source text/type/fingerprint, prompt, and model contract.
Assessment and verification include the exact retrieved claim IDs, revisions,
material hashes, owners, evidence, and source fingerprint. Assembly remains a
separate deterministic stage, checked against the current registry and publication
state. Compatible teams do not become urgent repairs merely because an unrelated
claim was added. New evidence reopens prior negative decisions through a bounded
discovery queue.

Claims and scope vectors use individual cache entries with configuration/space
identity and validated value hashes. Claim entries additionally bind ownership,
revision, and material hash. Document and query canaries establish a fresh exact
identity only when work is due; subsequent batches carry anchors. A changed space
cannot combine cached and new vectors. If a completely fresh run encounters
unrounded variation within the gross-discontinuity gates, it proceeds homogeneously
and writes a configuration-specific cache policy that disables persistent vector
reuse. Subsequent due work remains homogeneous; source/assessment JSON caches are
still independent and reusable. Cache eviction or an explicit configuration change
requires establishing compatibility again. If cached vectors were already admitted,
variation stops that run and the next invocation uses the homogeneous policy. Reads validate shape, finiteness and
magnitude; writes remain atomic. Already normalized values are preserved to avoid
warm-cache numerical drift. A genuinely empty due queue makes zero provider calls;
pending work still needs identity checks even when all vectors are cached.

Ranking considers at most twice `--max-scopes` per invocation. The existing model's
`discovery_queue` stores a sequence and last-scheduled positions, pruning removed
scopes and recovering malformed queue metadata. Repair and recent-call reservations
and cross-parent diversity remain. Only up to `--workers` assessments are submitted
at once; completed work is collected before a budget stop. Negative decisions,
cooldowns, and unfinished work remain distinguishable and resumable.

The existing 300-request limit includes canaries, retrieval embeddings, assessment,
verification, retries, and concurrent requests. Ranking/cache work checks the same
deadline, with five seconds reserved for canonical output/checkpoint persistence.
Expected exhaustion records deferred work without a false provider-failure result.
Actual provider/configuration/output failures remain visible failures, while healthy
compatible teams survive. Diagnostics remain in the existing developer receipt and
Actions artifacts; there is no public progress UI.
Concurrent JSON reads share the writer's local lock. Transient cross-process
cache read/eviction failures are counted and recover as validated cold misses;
they never become evidence or delete a healthy entry after a failed read. The
concurrency contract exercises the production reader and still requires complete
values, with a separate deterministic transient-lock recovery regression.

## Validation

`tests/browser/incremental-vectors-contract.test.mjs` exercises the production
generation function with deterministic providers, including clean/incremental
equivalence, exact bytes/layout, new/amended/deleted passages, complete configuration
and space drift, corruption, request/time exhaustion, failed writes and concurrency.
Worker contracts cover both space identities for an unchanged corpus.

`tests/test_incremental_teams.py` runs the actual team command and artifact writers
over the isolated Phase 2 intake/enrichment fixture. It covers cold/warm/pending
work, new calls, document amendments/expiration, corrected/added/retired claims,
clean-build graph equivalence, assembly reuse, corruption/eviction/concurrency,
provider failures, bounded ranking, partial scheduling and resumable exhaustion.
The Phase 1 strict-response and Phase 2 source/export/index contracts still run.

The Node contract job now installs the repository's Python requirements because
Phase 2's cross-language acceptance fixture invokes the Python pipeline. This
does not enable browser automation. Repository-wide E2E policy is unchanged:
complete manual Playwright/accessibility validation belongs to the explicitly
authorized final release convergence after implementation and non-E2E acceptance.

The first live refresh (`34070203169`) exposed nonidentical unrounded anchors in
both corpus and claim embedding batches. The release was retained. The correction
adds the required homogeneous fallback without relaxing any cache-mixing test or
canary threshold, and adds regressions for independent floating outputs, persisted
non-reuse policy, mixed-generation rejection and gross-discontinuity rejection.

## Refresh remediation

Review of generated PR #159 found that an IARPA inventory failure suppressed
independently healthy DARPA calls, and that a Simons page supplied holiday,
notification, previous-cycle and related-grant dates as submission evidence.
The combined adapter now reports sponsor partitions separately. Fresh records
from a verified partition enter the existing canonical merge while the failed
partition retains its established fail-closed policy. Closure events require
the affected partition to be verified. Partial refresh remains visibly degraded
in developer diagnostics and does not advance the whole source's last-success
timestamp.

Simons grant evidence is bounded to its one official grant article. A changed
boundary invalidates old evidence and requires document bytes, including when
an ETag or unchanged content hash might otherwise permit reuse. Submission dates
stay within their HTML block and sentence. Non-submission dates and contradictory
stage sequences are withheld with review disclosures. Old deadline citations are
rechecked locally without advancing retrieval timestamps or invalidating unrelated
evidence. Removed facts cannot leave dangling review references.
Container ownership counts matching outer tags, allowing valid omitted list-item
and paragraph end tags while rejecting missing/duplicate notice containers. This
was checked against the saved official Simons HTML as well as synthetic fixtures;
the projection retains its October 29 LOI with Eastern time and publishes warnings
for inconsistent full-application dates, without holiday or sibling deadlines.
Shared submission cues survive semicolon-separated annual date lists. Project
start dates do not become deadlines, and a later precise repetition can supply
the same deadline's time/timezone when its first listing omitted them. The
reported NOAA multi-year schedule has a fresh-extraction and cached-projection
regression; Alaska time and every submission year remain supported.
Semicolons that introduce a separately labeled deadline instead start a new
clause, and time expressions bind to the nearest date span. Regressions cover
shared lists, independent stages, different timezones, and times before/after
their dates through fresh extraction and cached catalog projection.
Explicit deadline headings also separate adjacent PDF fields before punctuation
is interpreted. Comma-attached times remain with their own date; unknown times
cannot inherit another item's value. Preliminary labels exclude their embedded
generic application/proposal word, and independently labeled phases do not impose
one another's stage order. Cached stage/time values require support in their own
date's quotation, allowing equivalent 12/24-hour and canonical regional timezone
representations without accepting partial or conflicting zones. Unsupported
legacy facts are withheld with the existing review warning and no new source-check
timestamp. The regression matrix includes the adjacent fields reported in 361526.
Date ownership includes explicit labels after a date and phase qualifiers before
a label. Postfix labels cannot become a later field's cue, and a phase qualifier
stays attached for ordering checks. Same-phase contradictions remain withheld.
Backward label ownership requires explicit linking syntax; an empty or TBD
deadline field cannot borrow an earlier issue date.
Balanced parenthesized/bracketed postfix labels are explicit links; unclosed,
nested, unvalued, or separately dated groups cannot assign a label backward.
Value expressions after a grouped heading are checked through the closing
delimiter and their linking words. Explicit phase, round, cycle, year and fiscal
year qualifiers constrain stage ordering; every applicable preliminary stage must
precede the application, while distinct declared rounds remain independent.
Replacement values require a complete linking phrase, including supported modal
modifiers. Dates and statuses inside applicant, eligibility or project-scope
annotations cannot replace the actual deadline or become submission evidence.
The predicate grammar evaluates every candidate, treats date-internal commas as
part of dates, and requires the predicate to resume after an incidental clause.
Only proved values and their own clocks reach semantic deadline context; original
source quotations are preserved. Replacement lists retain their independently
owned values, and unknown/unannounced replacements withhold superseded dates.
The regression matrix checks direct/moved/changed/revised/extended replacements,
modal forms, multiple incidental dates before/after the value, absent replacements,
unknown statuses, time and zone ownership, both postfix delimiters and neighboring
field boundaries through fresh extraction and legacy-cache publication. Local
revalidation never advances the source-check timestamp or document hash.
Direct, abbreviated and modal forms now use one ordered value sequence. Unknown
items carry list ownership without producing dates; explicit subsequent revisions
supersede earlier values. A proved `from` value is historical, and its clock cannot
leak into the replacement. The same complete clock-cue rule handles postfix and
replacement values, including `due at`, `closes at` and `must be received by`.
Postfix scope prose cannot reuse a deadline's cue for incidental later dates.
Prefix headings use the same value ownership, preserving explicit required and
optional markers while excluding historical and incidental dates.
Complete, balanced requirement markers remain attached across value lists and
revisions, including markers before or after an owned clock. Scope annotations
are not normalized as markers. Clock predicates may name their submission
subject; they still require a complete due/receipt/closing predicate and cannot
borrow a clock from a different submission stage.
An owned value's explicit required/optional marker overrides inherited metadata
and receipt/clock wording. Lists propagate only the latest effective marker.
Legacy flags that contradict an explicit source marker are withheld through the
existing warning and reference-cleanup path, without advancing source timestamps.
Field metadata before/after the separator and contiguous requirement/stage
prefixes share that ownership. Historical `from` values retain their effective
metadata through a revision. Explicit fields require a complete value predicate;
eligibility dates cannot use an otherwise empty field's heading as their cue.
Complete submission predicates and matching redundant timezone abbreviations
remain supported by the common value/clock grammar.

The same refresh exposed responses with empty objectives for negative decisions.
The prompts now state the existing validator's bounds for both positive and
negative responses. Validation and retries remain strict; diagnostics identify
the failed contract using an allowlisted reason, without copying provider bodies.
The outage contract's isolated prior model uses the current prompt dependency so
it continues testing preservation of compatible teams instead of assuming that
the committed production model was generated with the current code.

The corrective change preserves PR #159's newer generated baseline. An interim
committed rollback was rejected in review because it also restored expired calls
and removed unrelated new records. Pages remains on its known-good deployment
while the repaired writers and existing bounded caches produce a replacement.
No individual opportunity fact or team membership is edited. Extraction warnings
also survive the rebuilt catalog review queue, using the existing UI label/status
contract and without dangling references to withheld facts.

The existing refresh workflow has an optional `manual_release_validation` input.
It creates the generated PR normally, then waits up to 30 minutes for the operator
to review/test its exact head and merge through protection before Pages publication
continues. The read-only checkpoint pins the generated head, protected main base,
and tested tree. It rejects retargeted/advanced bases, changed heads, closure,
missing merge identity, a different merged parent/tree, and persistent API errors.
It does not request reviews, set checks, or
merge; ordinary refresh behavior and automated browser-testing policy are unchanged.
Failure rollback cannot overwrite a later protected main generation. With this
input, the refresh's Pages publication follows validation and protected merge of
the generated replacement.

Package construction now captures the release actually served by Pages and
retains that exact corpus/embedding identity from the existing validated current
or previous compatibility history. This handles a Pages rollback that differs
from main without importing arbitrary historical passage rows. Unknown or
malformed published identities block publication. A second bounded fetch and
no-write package check immediately before Worker deployment rejects a changed
Pages generation; it does not repeat provider work or rebuild the package.

`tests/test_pipeline_release_repairs.py` covers independent sponsor failure and
verified withdrawal, owned submission stages/timezones, sibling exclusion, cached
fact/reference cleanup, boundary-change revalidation and strict negative-output
diagnostics. The current correction passed 130 focused source/document tests,
1006 required Python tests and 713 Node contracts, with unchanged hermetic,
frozen-query and scoring expectations and a valid release package. A
bounded live diagnostic returned four verified DARPA calls despite IARPA's 403;
one provider request returned a valid exact-quote decomposition with zero retries.
