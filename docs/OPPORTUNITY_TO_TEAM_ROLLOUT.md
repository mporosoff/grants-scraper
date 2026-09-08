# Opportunity-to-Team Rollout

## Decision

Funding Finder proposes complementary research teams only for a specific
opportunity, a publication-eligible child topic, or a reviewed source-declared
branch. Broad parent programs are never automatic team units. Generated teams
use two to four people, with honest gaps when the available claims do not cover
all required roles. The original calibration batch is retained alongside
validated automatic proposals; its historical counts do not describe the
current catalog.

## Data boundary

`config/opportunity_team_model.json` is the canonical repository model.
`config/researcher_registry.json` supplies current researcher identities,
publication eligibility, and versioned public claims. Current roster/pool counts
and registry generation are in `data/researcher_registry_manifest.json`.
Current proposal coverage and processing outcomes are recorded by
`scripts/build_opportunity_teams.py` in
`evaluation/opportunity_team_generation.json`; check its run ID, input
generation, generation mode, and completion status before using a receipt.
Counts are diagnostics, not scientific quality gates.

### Targeted recovery of prior availability

The current recovery manifest in `config/offline_ai.json` pins the 96 scopes
available in protected publication `1730af28abd77cd38abf44f56c99bb1bb5231f60`,
including hashes of its canonical/public files and individual scientific graphs.
The prior pipeline is reproduced from protected history. Its relevant
deterministic validators match current code; later prompt changes spelled out
existing schema constraints. This does not authorize blanket flag clearing.

`restore_proven_teams` requires an exact retained graph, compatible scientific
contract, current source fingerprint, eligible current researcher claims and
revisions, valid source quotes, and successful current complementary-team
assembly. It checks an active copy before changing a withheld row, preserves
original generation attribution, and records a separate zero-request recovery
proof. Missing provenance or changed evidence remains withheld.

Before this repair, 15 of those scopes remain available. A read-only assessment
finds 61 additional exact decisions restorable, 19 source-changed scopes needing
reassessment, and one declared branch needing source revalidation. These are
prepublication counts, not a claim that recovery is already live or complete.

Team-only assembly uses `--recovery-only` while this manifest is configured:
paid selection is restricted to previously available scopes, at most five per
batch, within the existing pilot/maintenance spend ceilings. Ordinary source
maintenance and explicitly requested backfill retain their separate selection
contracts. No source collection, document extraction, or semantic vector build
is required for this recovery. Completed work is retained between batches.
The generation report records deterministic restorations separately from new
assessments and pending work. The independent provider comparison does not
gate restoration of already-proven decisions.

Deferred maintenance keeps its queue ownership when the accepted source snapshot
advances, including older failed or backfill attempts that become maintenance
after a source change. Their original decision key, failure state, cooldown, and
provider provenance remain intact. A matching completed generation report can
restore missing queue ownership; historical backfill is never promoted merely
because maintenance has unused capacity. Empty-selection replay includes that
report and proves zero new provider calls against the retained inputs.

The compact browser projection is `data/opportunity_teams.js` and remains lazy.
The eager `data/opportunity_team_index.js` contains scope identifiers, parent
identifiers, and record types; it contains no faculty, role, or explanation
graph. Both assets share an immutable generation identifier: the SHA-256 of the
canonical model payload before the identifier is added. Funding Finder and Team
Match declare that identity in their HTML markers and runtime/cache references.
Runtime validation rejects a mismatched index or projection. The search release
manifest hashes both generated assets and the associated runtime files; Pages
verification checks the published bytes against those hashes.

The original calibration workbooks and larger import artifacts are not browser
assets. Provider caches remain under the ignored `.cache/opportunity-teams/`
directory. Synthetic acceptance fixtures remain under `tests/`.

## Evidence and team contract

Automatic decomposition derives two to six scientific roles from the exact
scope before seeing researcher claims. At least one role must be required; the
roles are planning contributions, not invented sponsor mandates. A role records:

- the role label derived from an authoritative opportunity source;
- a bounded set of accepted controlled capabilities;
- direct, method-transfer, adjacent, or gap status;
- the person or people individually audited for that role;
- evidence-backed alternatives that still require role-transfer review; and
- the role rationale and source URL.

Direct and method-transfer evidence may fill a required role. Adjacent evidence
is displayed as support but does not silently make an incomplete team complete.
An evidence-backed alternative also remains review-required until its role
transfer is audited. Every selected initial member retains a contribution,
source-backed capability phrase, person-level explanation, faculty source, and
source-check date.

Team assembly optimizes complementary role coverage, not pairwise similarity.
The interface explains why the people work together and why each person was
selected. Removing a person recomputes role coverage. Replacement options are
limited to source-backed candidates for the newly missing roles, and an
unreviewed transfer cannot claim completed coverage. When no defensible
internal replacement exists, the interface says so and provides a prominent
manual-collaborator route.

## Runtime eligibility

Generated membership never overrides the live catalog. The reverse-team panel
uses the same browser currentness predicate as ordinary retrieval and Team
Match, evaluated against one clock captured when the panel opens. A record that
has expired, been archived, become stale-undated, or moved to an ineligible
status is rejected even if the generated model still contains it. An explicit
past close date is authoritative even when a record is also labeled rolling;
rolling applies only when no explicit deadline exists. Forecasted records keep
the existing product treatment.

Publication-eligible child topics are rechecked against the current lazy child
catalog. A generated child that is not in that eligible projection is rejected.
Declared branches retain their official branch source. A broad parent with one
or more calibrated branches presents a scope chooser instead of a team.

## User experience

Funding Finder shows the lazy “Build a team” action only on cards whose exact
scope, reviewed child/branch, or parent scope chooser exists in the generated
availability index. The toolbar's separate “Build a team” toggle filters the
current result set, exports, pagination, and chat context to those supported
opportunities without loading the full graph. Card and toolbar availability
also pass the shared runtime currentness predicate, so an archived or newly
expired indexed record is never advertised before the panel rejects it. Only
one team panel may be open.
A result rerender closes the owned panel and clears its trigger state, so
detached nodes cannot block a later activation. Close and Escape restore focus
when the trigger remains connected. A team-data failure is isolated from search
and other card actions.

Team Match adds an accessible local combobox labeled “Search Hajim faculty at
the University of Rochester.” Results show main, standby, or directory-only
status. Directory-only records cannot be admitted without better evidence.
The separate “Add a researcher manually” path preserves saved researchers,
ORCID import, the four-person limit, and device-local storage. A Funding Finder
proposal can be carried into Team Match through public faculty identifiers; no
private research text is put in the URL. Directory selections paint a visible
highlight, move focus to the selected team chip, and announce the matching
refresh before the heavier local matching pass. Saved directory members use
stable public identifiers and load directory identities before restoration. A
transient directory failure defers restoration and history writes, preserves
the saved identities, and blocks incomplete-team matching until a successful
retry restores the team.

## AI boundary

Browsing a published proposal requires no provider call. The offline generator
uses independent decomposition/adjudication/verification routes from
`config/offline_ai.json` to decompose a bounded source, Voyage to
retrieve relevant eligible claims, and separate adjudication and independent
verification calls to assess those exact claims. Verification cannot invent
edges or upgrade proposed coverage. Source quotes, identities, evidence limits,
claim revisions, and currentness remain publication requirements.

## Generation and failure recovery

The coordinated refresh first invalidates source/profile dependencies, restores
the existing public-evidence cache, then runs the bounded generator. The protected workflow reserves a durable logical budget before invoking the
generator. Its maintenance command is:

```sh
python -m scripts.build_opportunity_teams --generate --mode maintenance --state "$RUNNER_TEMP/offline-$GITHUB_RUN_ID" --baseline "$RUNNER_TEMP/accepted-scopes.json" --max-scopes 60 --workers 3 --write
```

Omit `--generate` to perform invalidation and deterministic assembly without
provider work. Omit `--write` to avoid changing canonical team assets; a receipt
is still written. `--report` selects its developer-only location.

Each response must satisfy its complete stage contract, including actual
boolean decision/required flags and valid empty arrays for negative decisions.
Malformed responses and invalid quotes/claims are processing failures, never
scientific evidence that an opportunity is unsuitable. Cache reads are
revalidated; invalid entries are evicted, and only validated replacements are
atomically admitted. Transient transport errors and invalid outputs receive at
most three attempts with bounded backoff. Authentication/configuration errors
stop new requests for that provider in the durable logical run. Safety refusals
are retained under their exact contract and are not retried. Failed calls count
against request/time bounds and the durable dollar allowance. Each concurrent
request reserves its conservative input/output allowance before dispatch, then
reconciles actual provider usage. Unknown usage remains charged at the reservation.
The initial pilot is at most five scopes/$2, normal maintenance $2, and manual
backfill $5; no recurring backfill is enabled. Stage caches live in the durable
spend checkpoint as well as an optional cross-run cache, so a late failure does
not repeat completed earlier stages. `--mode replay` disables new selection and
requires zero team-provider calls. OpenAI Responses uses only the Actions
`OPENAI_API_KEY`; selected Sonnet stages use `ANTHROPIC_API_KEY`; Voyage stays
separate. Publication/validation never receive generation keys. Interactive AI
features are unchanged. See [offline evaluation](OFFLINE_AI_EVALUATION.md).

The versioned attempt contract retains scientific validity separately from
provider routing and raw-cache compatibility. Exact hash-proven legacy Sonnet
teams and negative decisions retain their original provenance. A default model
change does not resubmit them. Unprovable legacy evidence is never relabeled.
Source-only negatives do not depend on unrelated researcher claims. Insufficient
evidence decisions track their retrieved claim revisions and eligible claim
inventory; relevant changes may reopen them. New scopes are measured against the
prior accepted snapshot. Historical untouched scopes remain in manual backfill;
unused maintenance budget never fills that queue. Failed per-scope processing receives a one-hour
cooldown, while changed inputs are immediately eligible. Source or researcher
invalidation always happens before provider work, so an outage cannot republish
unsupported teams. A failed generation exits nonzero after persisting safe
invalidation and a sanitized receipt. Skipped source eligibility, valid broad
scope, insufficient evidence, completed assessments, and deferred work have
separate diagnostics. These appear in the existing generation receipt and
Actions summary, without adding application UI.

Receipts include invocation/run identity, input generation, scope/parent IDs,
stages, reason codes, retry eligibility, cache/retry/network counters, and
elapsed time. A starting or mismatched receipt cannot be reported as a completed
run. Provider error bodies and private text are never copied into diagnostics.

## Verification

Focused contracts live in `tests/test_build_opportunity_teams.py` and
`tests/test_team_provider_contracts.py`. Run them with the required non-E2E
Python and Node gates during implementation. Browser-backed accessibility and
E2E execution require the dedicated authorization described in `AGENTS.md`.

Coverage breadth, faculty similarity, and counts of possible permutations are
diagnostics only. They do not establish team quality.

## Known limitations

- The directory may still omit relevant faculty, including secondary or
  cross-school collaborators.
- Current claim statuses and evidence limitations are recorded in the canonical
  researcher registry; current team gaps remain explicit in each proposal.
- Replacement alternatives with source-backed vocabulary remain visibly
  review-required unless individually audited for the opportunity role.
- Availability, willingness, sponsor eligibility, budget, and institutional
  approvals must be verified outside the tool.
