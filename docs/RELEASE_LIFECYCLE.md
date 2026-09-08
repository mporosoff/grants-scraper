# Funding Finder release checkpoints

`refresh-opportunities.yml` is the production catalog/search/Pages release owner.
It holds `funding-finder-coordinated-release` through generation, persisted
candidate validation, Worker preparation, protected publication, called Pages
deployment and live verification. `pages.yml` accepts only `workflow_call`; it
deploys the artifact already prepared by that owner. There is no independent
committed-search deployment workflow.

## Artifact and receipt identities

Generation creates `candidate-<64-character SHA-256>` before downstream gates.
Its `candidate.json` covers every file in `files/`, original generation SHA and
run/attempt/time, generation dependencies and command configuration, generated
input/output identities, semantic space, team inputs, and Worker input hash.
The candidate ID hashes the canonical manifest excluding the ID itself. Artifact
downloads verify the workflow and protected main provenance, ID and every file.
Artifacts are retained for 90 days. Missing or expired candidate artifacts may
be reconstructed only from the exact protected publication whose candidate
pointer, original artifact run, manifest identity and every committed file hash
match. Missing receipts require validation again; they are never invented.
Authentication failures, conflicting artifacts and corruption fail closed and
never trigger recovery or generation. A cache cannot substitute for an artifact.

Each validation attempt preserves `validation-<candidate>-<attempt>` containing
safe machine-readable diagnostics and, only on success, `validation.json`.
The receipt covers exact file hashes, validator/dependency files, required gate
results, generation SHA and validation SHA. A prior receipt can skip unchanged
gates; changed validation dependencies require validation again. No provider
credentials are exposed to validation. Idempotence tests work on copies and the
candidate hashes are checked after each gate.

Publication retains `publication-<candidate>-<attempt>`, including the actual
serving Worker checkpoint, known-good live package, protected merge SHA and
publication receipt. `live-<candidate>-<attempt>` records exact live hashes and
handshake evidence. Receipts are append-only across attempts. The public
`release/candidate.json`, `release/publication.json` and `pages-release-sha.txt`
identify the serving release. Historical generation provenance is never renamed.

## Dispatch and retry

Use the workflow dispatch `stage` input:

| Stage | Required checkpoint | Work performed |
| --- | --- | --- |
| `auto` | Verified candidate/publication and current protected main | Pin one SHA and choose no-op, validate, reuse, team work or generation from dependency fingerprints |
| `teams` | Current validated candidate | Bounded maintenance on pinned catalog/subtopics/researcher inputs; preserve source and vector bytes |
| `backfill` | Current validated candidate | Manual historical coverage work, at most $5 per logical run; same publication owner |
| `generate` | Current protected main | One complete bounded generation; persist, validate, publish and verify |
| `reuse` | Current `release/candidate-source.json` | Verify generation inputs and data bytes; assemble current runtime around unchanged data, persist a derived candidate and release |
| `validate` | `candidate_run`, full `candidate_id` | Load candidate, run current deterministic gates, retain reports/receipt |
| `publish` | `candidate_run`, full `candidate_id`; optional `receipt_run` | Reuse a matching receipt or validate; prepare Worker, protected merge, Pages and live verification |
| `verify` | `candidate_run`, full `candidate_id`, `receipt_run`, `publication_run` | Verify the expected retained publication receipt, stamped SHA and exact live release; no generation or publication |

Supply `receipt_run` after a downstream failure to reuse passing gates. A failed
validation retains the candidate; correct a validator/release-control defect and
dispatch `validate` or `publish` against the same artifact. A genuine generation
defect requires one consolidated repair and one new `generate`. Workflow reruns
restore an already persisted generation before executing expensive steps.
For live-only retries, `publication_run` selects the expected publication
checkpoint; `publication_attempt` can select an earlier retained attempt
explicitly. An older live receipt for the same candidate does not pass. Failed
job reruns can load receipts retained by an earlier workflow attempt.

If main advances while a generated PR is reviewed, a publication retry waits for
that old-head review to finish, verifies unchanged generation dependencies and
candidate bytes, and rebases the same branch using an exact force-with-lease.
It requests one new exact-head review only if one was not automatically started.
Old approval reactions cannot validate the new head. Publication checks committed
hashes even when a candidate marker is already present on main.

Historical bootstrap: run 34174544563 retained no reusable artifact. Run
34211041411 produced candidate `57924d144bfcc276713789a0ba04736e0b671da95e645b9c11cd5b12f35951f6`,
published at `4011bac6a4877bb57d5e630cce7c0b77178a7fba` and verified by
34224157715. These are historical exact identities, not a substitute for reading
the current candidate and latest retained receipt.

## Dependency boundaries

`config/release_dependencies.json` declares five dependency groups: source/catalog,
researcher/teams, semantic vectors, runtime/package, and validation/publication.
The planner pins main once and all jobs use that SHA. Ordinary pushes do not
implicitly publish: unchanged release identity is a no-op; validator-only changes
validate preserved bytes; runtime/Worker changes assemble a derived package;
source or vector dependencies select generation; team changes select team-only
work. A generated publication commit is recognized by verified content, not its
commit message. Exact named resumes never switch candidates or select generation. Python comments/docstrings are excluded from semantic
fingerprints. Generation command arguments and safe environment configuration
are also hashed, so changing a budget/source parameter in workflow YAML cannot
silently reuse stale data. Secret values, cache keys and orchestration are not
generation inputs. Changing validator, deployment-checkpoint, retry or live
verification code does not invalidate generated data.

Candidate baseline hashes distinguish unchanged source inputs from the exact
candidate already merged. A third generation's data is rejected. Unrelated main
advancement is accepted only after fingerprint verification; changed runtime
requires `reuse` assembly. Source/vector changes require `generate`; team-only
changes preserve catalog/evidence/passages/vectors and rebuild dependent team
projections/package hashes. A derived candidate keeps its original source SHA
and records new team-generation SHA/run/provider provenance separately. Model
routing changes do not make still-valid scientific decisions stale.
UI-only assembly does not run collection, extraction, teams or vectors. The
Worker input fingerprint covers its complete source/config/allowlist; HTML and
CSS do not redeploy a verified equivalent Worker.

Document transport/cache and its shared spending implementation are source
dependencies. Team request/response routing is separate, so a team-only provider
switch does not invalidate catalog evidence. Introducing the document budget
adapter requires one new source candidate; subsequent retries reuse its exact
persisted bytes. A logical workflow rerun first looks for its already completed
candidate. A valid publication receipt plus a successful Pages job from that
exact artifact attempt resumes live verification, including any newly required
validation, without repeating Worker preparation or Pages publication.

Missing, conflicting or mixed serving provenance blocks publication. Health is
only a compatibility handshake, never provenance. Changed Worker inputs deploy
only after validation, with exact serving version captured for normal rollback.
The pre-publication provider smoke and post-Pages provider smoke remain required.
An older unannotated version may be reconciled read-only only when an isolated
pinned build of protected Git inputs matches every authenticated serving module
byte, the download ETag binds those bytes to the inspected version, all declared
runtime/binding/route configuration matches, and the deployment stays unchanged
at 100% traffic. The proof records file hashes, actual version, configuration
fingerprint and protected input SHA. It does not claim that the older version
was originally generated at that SHA. A missing annotation is never replaced by
an assumed historical commit; any absent or mismatched proof blocks publication.
Secrets are neither fetched nor retained. Assigned Durable Object namespace IDs
are distinguished from the declared local class binding. Unknown deployment
configuration is rejected before any local build command runs.
Pages staging re-reads authenticated active deployment/version metadata after the
protected PR wait. Live verification, including a manual `verify` retry, checks
the exact retained `worker-after.json` version, Git checkpoint and complete input
fingerprint; health and provider smoke cannot substitute for that proof. The
check repeats after the live provider smoke and retains `worker-live.json` plus
the observed identity in the live receipt. Missing, malformed, conflicting or
mixed serving provenance fails closed. An unchanged verified serving Worker is
retained; an unexpected serving version requires publication reconciliation.

Review rounds are individually bounded. A new confirmed consequential finding
starts one focused consolidated repair and one exact-head verification, without
another operator authorization. The first clean verification ends review. Only
the same concrete defect surviving two distinct focused repair attempts is a
convergence failure; ordinary review-round exhaustion is not a stop condition.

Approved researcher publication remains an input-producing workflow. It waits
for the release owner without holding the owner's lock and marks the submission
published only after its existing exact profile/live checks pass.

## Privacy and product contracts

Only explicit public assets and existing safe derived evidence enter candidates.
Private notice-structure caches, raw source documents/email, provider caches and
secrets are excluded. Notice diagnostics identify every changed record/field,
with bounded public before/after values and hashes for truncated values.

Team generation retains its upper bound of 60 scopes, three workers and a
20-minute step. The first automatic rollout is only five pilot scopes/$2. Later
maintenance is at most $2; historical backfill remains an explicit manual $5
mode. The spend ledger and complete stage responses are retained before/after
provider work, outside release candidates; reruns never reset the allowance.
An empty maintenance queue makes zero team calls, including Voyage canaries.
Catalog refresh performs deterministic invalidation and never fills spare
maintenance capacity with historical backfill. README/PROJECT authored prose is
not materialized from reused artifacts; only their bounded statistics updater
may change their generated sections. Degraded sources/document evidence retain their established
bounded alert semantics. Compatible vectors may be reused; model-space drift
continues to force incompatible vectors to rebuild. This infrastructure does
not alter scientific parsing, opportunity facts, relevance or browser behavior.
