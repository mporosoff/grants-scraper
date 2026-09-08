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
Artifacts are retained for 90 days; expired artifacts fail closed. Download or
extend retention through existing GitHub controls before expiry when longer
retention is needed. An expired artifact is never replaced with a cache.

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
| `generate` | Current protected main | One complete bounded generation; persist, validate, publish and verify |
| `reuse` | Current `release/candidate-source.json` | Verify generation inputs and data bytes; assemble current runtime around unchanged data, persist a derived candidate and release |
| `validate` | `candidate_run`, full `candidate_id` | Load candidate, run current deterministic gates, retain reports/receipt |
| `publish` | `candidate_run`, full `candidate_id`; optional `receipt_run` | Reuse a matching receipt or validate; prepare Worker, protected merge, Pages and live verification |
| `verify` | `candidate_run`, full `candidate_id`, `receipt_run` | Verify existing receipt and exact live release; no generation or publication |

Supply `receipt_run` after a downstream failure to reuse passing gates. A failed
validation retains the candidate; correct a validator/release-control defect and
dispatch `validate` or `publish` against the same artifact. A genuine generation
defect requires one consolidated repair and one new `generate`. Workflow reruns
restore an already persisted generation before executing expensive steps.

The original failed run 34174544563 retained no artifacts, so it cannot be
replayed. The first production candidate under this lifecycle requires a new
generation after the infrastructure merge. This is also the bootstrap for the
committed candidate pointer; an earlier UI push cannot manufacture provenance.

## Dependency boundaries

`config/release_dependencies.json` declares generation, output, runtime, Worker
and validation inputs. Python comments/docstrings are excluded from semantic
fingerprints. Generation command arguments and safe environment configuration
are also hashed, so changing a budget/source parameter in workflow YAML cannot
silently reuse stale data. Secret values, cache keys and orchestration are not
generation inputs. Changing validator, deployment-checkpoint, retry or live
verification code does not invalidate generated data.

Candidate baseline hashes distinguish unchanged source inputs from the exact
candidate already merged. A third generation's data is rejected. Unrelated main
advancement is accepted only after fingerprint verification; changed runtime
requires `reuse` assembly, and generation-relevant changes require `generate`.
UI-only assembly does not run collection, extraction, teams or vectors. The
Worker input fingerprint covers its complete source/config/allowlist; HTML and
CSS do not redeploy a verified equivalent Worker.

Missing, conflicting or mixed serving provenance blocks publication. Health is
only a compatibility handshake, never provenance. Changed Worker inputs deploy
only after validation, with exact serving version captured for normal rollback.
The pre-publication provider smoke and post-Pages provider smoke remain required.

Approved researcher publication remains an input-producing workflow. It waits
for the release owner without holding the owner's lock and marks the submission
published only after its existing exact profile/live checks pass.

## Privacy and product contracts

Only explicit public assets and existing safe derived evidence enter candidates.
Private notice-structure caches, raw source documents/email, provider caches and
secrets are excluded. Notice diagnostics identify every changed record/field,
with bounded public before/after values and hashes for truncated values.

Team generation retains 60 scopes, three workers and its 20-minute bounded,
deferred contract. Degraded sources/document evidence retain their established
bounded alert semantics. Compatible vectors may be reused; model-space drift
continues to force incompatible vectors to rebuild. This infrastructure does
not alter scientific parsing, opportunity facts, relevance or browser behavior.
