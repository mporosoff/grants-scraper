# Parsing reliability: developer runbook

This repair extends the existing collection, canonical merge, document evidence,
subtopic and team pipelines. It does not add an ingestion service. Scientific
admission, scoring algorithms, public identities and provider limits remain
separate from deterministic fact extraction.

## Writers and consumers

| Boundary | Implementation | Output / consumers |
| --- | --- | --- |
| Collection and structured facts | `build_catalog`, `pull_grants`, `sources.base`, source adapters | Canonical records; authoritative source dates and award fields |
| Sponsor-scoped duplicate merge | `solicitation_identity`, `sources.merge`, `source_documents` | Stable Grants.gov winner, source aliases, retained official document routes |
| Official structure and facts | `extract_document_evidence`, `notice_structure`, `notice_schedule`, `notice_semantics` | Compact evidence, typed submission events, searchable document text, indexes and facets |
| Scientific child bodies | `subtopic_structured`, `subtopic_records`, existing Cov4 gate | Source-owned child bodies, existing child IDs, bounded sidecar search index |
| Team dependencies | Existing `build_opportunity_teams` source fingerprints and claim revisions | Invalidation before provider work; evidence-qualified projections |
| Shared submission selection | `submission_schedule.py`, `assets/submission-schedule.js` | Search/filter/sort, Team Match, saves, CSV/calendar, feeds, changes, alerts and AI payloads |
| Packaging | `import_opportunity_team_model`, `build_search_release_package` | Content-addressed browser assets and coherent current/previous compatibility package |
| Publication | `verify_notice_publication`, existing Pages/search/refresh workflows | A read-only projection boundary before production publication |

## Evidence and recovery contract

Structured authoritative dates, amounts and cost-share values keep authority.
Document facts carry their subject, stage, class, cycle/track, monetary basis,
obligation and source receipt where applicable. Conflicts stay explicit. An
initial budget-period amount is not a whole-project ceiling. Applicant withdrawal
is not notice cancellation. A PI limit is not an institutional limit.

Native NIH/FDA Key Dates, NSF fields, Exchange notice groups and supported PDF
submission blocks retain independently owned values. Narrative fallback supports
bounded explicit clauses. It does not guess stage, replacement date or timezone.
Required undated prerequisites remain represented; a later full date does not
prove unrestricted applicant access. Recurring yearless dates are not expanded
into invented years.

Submission policy version 2 also treats a source-listed internal deadline as an
institutional entry gate unless it is explicitly optional. It respects the same
cycle/track boundaries and preserves unknown or anticipated dates. The reviewed
1,419-record replay changes access for two records on September 7, and four on
September 19, without changing a date, clock, source field or retrieval timestamp.
The acceptance receipt records these four source-backed dispositions separately
from the semantic-extraction ledger.

Parser-only change events require a matching nonempty document hash and unchanged
source-owned submission fields. A fresh listing amendment remains alertable even
when its attachment is unchanged. Saved aliases resolve for membership, toggles
and new watches while existing browser-local notes and pursuit status remain on
their original durable snapshots; ambiguous aliases are not guessed.

`notice_structure_cache` stores normalized original structure privately under
`.cache/notice-structure`. Its identity binds source URL, material hash, structure
version and notice selector. Semantic families have separate versions. A parser
change can reuse full structure without advancing source-check timestamps.
Missing or corrupt structure queues bounded retrieval. A short cached quotation
may prove a retained or corrected local assertion; it never certifies complete
source recovery. Pending facts retain an explicit verification diagnostic.

Quarantine receipts are immutable, content-addressed and bounded to 80 previous
facts and 512 KiB each, with at most 2,000 receipts in the evictable cache.
Normalized entries are capped at 40 MiB and validated on reads. No raw documents
or full normalized containers belong in `data/`, Pages uploads or repository
commits. Existing Actions cache access and eviction apply; no new hosted storage
or credential inheritance is introduced. Cache eviction is safe and recoverable.

The coordinated refresh restores this cache before dependent processing. Its
45-document, 30-topic-document and existing team/provider budgets are unchanged.
HGEO body-parser upgrades invalidate only that scientific family; a pending
repair removes affected published scopes without erasing unrelated children.
The existing code normalizer preserves IDs such as `parent:a-1` for official
code `1A`. Corrected source text changes the existing team source fingerprint.

## Offline validation and measurement

Run `python -m tools.validate_parsing_fixtures --manifest
tests/fixtures/parsing/manifest.json --output .cache/parsing-quality.json`.
The frozen set contains 28 notices, including eight holdouts, with source
receipts and both positive and negative annotations. Full documents and the
handoff bundle stay outside the published tree. Holdout expectations were
annotated before their semantic evaluation and were not changed to match output.

Run `python -m tools.audit_parsing_corpus --baseline <verified-sha> --as-of
<fixed-ISO-time> --output .cache/parsing-audit.json`. The normal projection runs
without network/provider work or maintained-input writes. Keep baseline,
maintained inputs, isolated candidate and actual deployed package distinct.
The report does not call unreviewed decisive changes publication-ready. Review
source receipts for every changed next action, required prerequisite, amount
ceiling, institutional limit and solicitation status. Counts across families
are nonexclusive; lost coverage is not automatically a quality gain.

The decisive ledger separately includes the selected event's clock, timezone
and submission scope. An unchanged calendar date cannot clear a changed time
or a change from new applications to resubmissions. These differences require
source dispositions too.

Funding evidence preserves applicant conditions and separates optional
administrative supplements from base awards. Annual and whole-project limits
remain separate; the reader does not add a supplement to a base award to invent
a universal ceiling. The AI payload carries these qualifiers with the evidence.

Source-native cover tables retain clearly owned clocks including seconds.
Malformed clocks cannot be accepted by matching a valid-looking suffix. An
explicitly rolling required preliminary submission remains a required step,
with the source's anytime rule, rather than an invented dated deadline. NSF's
related-program resources and hypothetical webinar guidance do not establish
requirements for the current opportunity.

ARPA-H's Solution Summary and Solution Video fields retain their preliminary
stage; its explicitly topic-labeled package rows keep separate dates and clocks.
The adapter uses the shared field reader. A generic listing label may be refined
only by a unique named field on the same source at the same date. An estimated
Grants.gov label also needs its own closing-date explanation to establish the
same preliminary window. Source dates, estimate flags and original receipts stay
intact, and the refinement is reversible when evidence becomes unavailable.
IES cover rows retain an explicitly optional LOI; a clock missing AM/PM does not
erase its clearly owned date or acquire an inferred meridiem. Explicit CET and
consistent noon annotations are retained as written.

Required implementation checks remain Python product contracts, Node browser
contracts, frozen query/scoring checks, hermetic fingerprints and release package
integrity. Full Playwright/accessibility runs belong only to the explicitly
authorized integrated manual validation stage. Do not duplicate an unchanged
candidate's complete run or count earlier-SHA evidence for changed code/data.

## Intentional baseline changes

The search ranking expectations and scientific scoring fixtures stay frozen.
Only the directly changed search/save/export/AI functions and Team Match date
consumers receive updated preservation hashes. CSV now carries the complete
submission schedule, access qualification and original source close date.
The existing DARPA fixture is regenerated by its maintained adapter; added
sponsor-authority metadata does not change its opportunity facts.

Hermetic output changes require an artifact-by-artifact review before updating
fingerprints. Typed evidence, parser recovery diagnostics, source-authority
metadata and submission selection are intended differences. Source timestamps,
canonical membership and authoritative values must remain stable. The legacy
fixture's eligibility sentence about foreign subrecipients is not repeated when
its retained source quotation does not contain that assertion; the cited eligible
organization list remains available.

The reviewed frozen build changes 18 of 23 artifacts. The five canonical records,
their authoritative fields and document hashes/check timestamps stay unchanged.
All 12 supported cached facts remain represented with typed values. Metadata
reflects 160 indexed terms instead of 159. Feeds expose the required LOI and
uncertain forecast/prerequisite labels; the XML-only before snapshot gains the
existing detail cache's August 25 LOI and corresponding closing-soon event.
The 37 frozen queries and 50 scoring cases remain unchanged.

## Measured implementation acceptance

The source-reviewed projection at `2026-09-07T16:00:00Z` contains 1,419 records
and preserves 1,360 structured deadlines. Its 610 decisive comparison rows
(305 against each of maintained inputs and the verified generation) have
source dispositions. Counts by field overlap: 116 next submissions, 125 selected
event metadata changes, 98 prerequisite changes, 149 award-range changes,
148 status-signal changes and one institutional-limit change. No structured
deadline, amount or cost-share override or unfetched source-timestamp advance
was observed. These are parsing checks, not release authorization.

The frozen 28-notice set has 90 passing positive and 21 passing negative checks,
including eight holdouts. All seven named audit signatures are absent from the
replayed projection. Positive cohort recovery is 52/52 prohibited voluntary cost
share, 65/67 not-required cost share (the other two explicitly qualify possible
Other Transaction cost sharing), 31/31 award caps and 62/62 post-recommendation
DMP conditions. The 55 administrative-withdrawal cases produce no false notice
cancellation. Five of 66 eligibility and six of 67 review-criteria notices have
substantive recovered excerpts; the remaining overlapping groups of 61 need
original-source recovery. Their cached outlines are withheld, not counted as
positive coverage. This is a bounded acceptance set, not corpus-wide recall.

Usable next dates change from 1,298 to 1,296. One unavailable ACS response is
withheld; one NOAA project-start date is corrected to its actual past submission
date. Nineteen records retain required preliminary events. The parser migration
then had 613 records awaiting original structure. This historical acceptance
measurement is not the current backlog. Current unique-record counts, overlapping
field categories and deltas are computed in `evaluation/release_coverage.json`
and the Actions summary. Missing pending-age/unsupported-source measurements
remain explicitly unknown. The normal source request budget is unchanged.
Archived response replay and these audits make zero provider/source requests.
Source receipts record actual earlier retrievals separately.

The ordinary zero-request document CLI and sidecar writer pass the publication
guard after invalidating obsolete HGEO bodies and an already source-changed
DEPSCoR entry. Other sidecar records remain intact. This safe cold-cache result
does not claim scientific reassessment: the source-body fixtures recover the
12 actual HGEO sections, and the normal team-builder fixture proves qualified
panel/index output and amendment invalidation. Production reassessment remains
inside the bounded coordinated refresh.

## Protected publication boundary and recovery

`python -m tools.verify_notice_publication` compares committed notice projections
with the normal zero-request writer. It also rejects published HGEO bodies lacking
the current scientific-body interpretation. It writes no production assets and
cannot merge or deploy anything. Pending recovery can pass only when the public
projection already reflects its safe, explicitly incomplete interpretation.
This is a necessary consistency check, not a substitute for source review, package
checks or the complete integrated manual suite.

Pages, committed-search and Alerts workflows run this check before production mutation.
Alerts also verifies the exact served catalog and existing HTML surfaces before
D1, signing-secret or Worker changes, with a bounded three-minute wait. A failed
pre-mutation check retains the active Worker. Corrected catalog publication
triggers this path; unchanged compatible Worker inputs retain the existing version.
The refresh detects a mismatched starting projection and automatically uses the
existing manual generated-package checkpoint, including on a code-triggered run.
An explicit false manual input cannot bypass that detected migration. The newly
built projection must pass before the existing Worker compatibility deployment.

This boundary retains the currently served package while code and interpreted
data are temporarily different. It does not disable workflows, cancel jobs,
change branch protection or publish an older blocked generation. Recovery is to
validate and protected-merge the corrected generated package, after which the
ordinary checks admit it. Keep the existing current/previous Worker compatibility
and rollback steps intact. Do not bypass a failed boundary with a manual deploy.

The release receipt must separately record actual merge SHA, tested code/package
identity, generated PR and refresh run, published Pages hashes, compatible Worker
identities and non-destructive live results. This runbook is not a release receipt.

### Worker checkpoint and generated identity gates

Award and Alerts deployment classification reads the latest deployment's fully
serving version through pinned Wrangler `versions view --json`. The upload's
`workers/message` supplies its exact protected-main source checkpoint. A legacy
version can use an exact deployment/rollback message only after its version ID
has been verified. Conflicting checkpoints, unknown ownership, mixed traffic,
or a failed bounded metadata lookup stop before mutation. An unannotated active
Worker no longer silently inherits the historical PR #63 baseline. Recovery
requires verifying that active version's actual source checkpoint; never guess
it from a healthy response or the current repository SHA. Compatible unchanged
Worker inputs retain the existing version and normal Pages checks still run.

The generated catalog gate checks both stable canonical IDs and the builder's
sponsor-aware solicitation identity. Official numbers can coincide across
sponsors or records whose sponsor ownership remains unresolved. Those number
collisions alone are not evidence for merging records. Repeated canonical IDs
or repeated authoritative sponsor/number identities still fail publication.
