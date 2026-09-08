# Repository operating policy

## Bounded reviews and consequential findings

- Bind each automated review to one complete commit SHA. While it is pending, do not edit, commit, push, or resolve individual threads. Collect all terminal findings, then audit the affected invariant family read-only before remediation.
- Begin with one integrated review, consolidate its consequential findings into one remediation batch, then run one exact-head verification review. Review/remediation rounds are bounded individually, not globally.
- If verification identifies new independently confirmed consequential defects in supported paths, automatically start one new bounded round: reproduce, consolidate all accepted findings, minimally repair, run focused affected checks and required gates, then obtain one exact-head verification review. No new user authorization is needed because a previous round was used. Follow-up verification covers the changed subsystem and affected release-safety interfaces, not another comprehensive repository-wide review.
- The first clean exact-head verification ends review. Proceed to the authorized merge/release; do not seek another broad review or theoretical completeness. A genuine convergence failure exists only when the same concrete consequential defect remains unresolved after two distinct focused repair attempts, or a genuine stop condition below applies. Preserve exact evidence and both repair attempts at that checkpoint.
- A finding blocks release only when it demonstrates a reproducible supported-path correctness, data-integrity, security/privacy, release-safety defect, or user-path regression. Identify the violated contract, reachable path, and practical consequence.
- Whitespace, formatting, naming, comment wording, optional refactors, unsupported hypothetical parser grammars, synthetic cases without a reachable supported-path defect, and speculative enhancements do not reopen implementation.
- Use an automatically triggered comprehensive review; never request a duplicate. After remediation request exactly one exact-head verification review if the update did not already trigger it.
- Terminal Codex evidence includes a completed top-level `Codex Review` comment from `chatgpt-codex-connector[bot]` with `Reviewed commit: <sha>`, a submitted review anchored to that SHA, or the configured no-findings reaction when the PR head remained unchanged. Acknowledgements and working messages are not terminal. Inspect complete conversation comments, submitted reviews, inline threads, and reactions before declaring a review missing.
- Normally, after three unchanged observations or 15 minutes after acknowledgement/completed CI, refresh all review surfaces and report a missing review. During an explicitly authorized autonomous release-completion task, continue monitoring that same acknowledged/running review at reduced cadence; do not trigger a duplicate. Terminal failure or an outage remaining after bounded retries may require a checkpoint.
- Merge only with terminal clean exact-head review, required exact-head CI green, unchanged PR head, and no consequential unresolved finding. Do not call evidence final while required reviews or gates are pending.

## Validation authorization

- Ordinary implementation and release validation use focused infrastructure contracts, required Python and Node/browser contracts, package checks, and frozen-query/scoring/no-drift gates.
- Full manual E2E/Playwright may be started only with explicit user authorization. Workflow refactoring without material browser/runtime changes does not require another full manual E2E.
- Authorization for a manual validation run includes starting it, bounded monitoring, reading status/logs/results/artifacts, diagnosing failures, and necessary bounded corrective handling within that validation scope. Never require another approval just to discover whether an authorized run passed.

## Autonomous release completion

- An explicitly authorized autonomous release-completion task includes workflow monitoring, logs/artifacts, required checks, protected merge operations within the approved plan, deployment, publication, normal rollback, and live verification. Do not repeatedly ask for routine approval.
- Use the normal interactive approval flow when required. A user-selected authorization option is authorization; do not request another prose confirmation. A hard platform/security denial must not be bypassed. Stop for missing authority/credentials, unsafe or destructive actions outside existing procedures, irreconcilable release requirements, the same consequential defect surviving two focused repair attempts, unestablishable provenance, or material scope expansion.
- Diagnose security-looking HTTP responses before treating them as an intentional policy boundary. Automatically repair verifier HTTP-client defects (including a 1010 Browser Integrity Check rejection caused by the verifier's own implicit signature) using a complete, truthfully identified request profile. Preserve bounded status/Cloudflare/application diagnostics. Retry transient 403/429/5xx and propagation within existing bounds, retaining the candidate.
- Stop when an intentional Access/WAF denial has no existing authorized route, resolving the failure requires new credentials/permissions or security-policy changes beyond authorized application configuration, or proceeding would circumvent an intended control. Never impersonate a browser or globally disable Browser Integrity Check to pass verification. A security-looking status alone is not proof of that boundary.
- Infrastructure hardening does not authorize broad product/parser redesign. Keep repairs bounded to concrete supported-path failures.

## Immutable release lifecycle and expensive-work reuse

- The authoritative path is GENERATE → PERSIST CANDIDATE → VALIDATE CANDIDATE → PUBLISH CANDIDATE → VERIFY LIVE. The refresh workflow owns the complete catalog/search/Pages boundary and lock; Pages is only a called stage.
- Candidate artifact plus manifest is authoritative candidate identity. Validation and publication receipts are authoritative evidence. Caches/checkpoints are optional performance aids and never substitute for provenance.
- Persist complete safe candidate bytes before downstream gates. Never retain private notice structures, raw private email, secrets, unrestricted extracted text, or provider caches in candidate artifacts.
- Validation operates on copies, uses no source/provider generation, and reports canonical record IDs and bounded before/after field diagnostics. Preserve failed candidates and machine-readable reports.
- Do not repeat completed source collection, enrichment, document extraction, team generation, embeddings, or full E2E merely because a downstream gate/deployment/publication/live check failed. Reuse their preserved outputs unless relevant inputs changed or no complete safe output exists.
- Generation dependency fingerprints determine invalidation. Preserve the original generation SHA forever; validation and publication SHAs are separate. Validator/orchestration/diagnostic/UI-only changes ordinarily reuse generated data. Runtime changes may assemble a derived package from identical generated bytes. Parser/source/team/vector semantic changes invalidate the candidate.
- Preserve bounded/deferred team generation, bounded degraded-source handling, sponsor-scoped solicitation identity, duplicate rejection, and strict embedding/model-space compatibility.
- Publish exact artifact bytes through the normal protected PR mechanism. Verify hashes before and after merge. Establish verified Worker input compatibility before Pages; retain an unchanged verified Worker, and capture the actual serving version for rollback when deployment is necessary.
- Healthy endpoints alone do not prove deployment equivalence. Require verified serving provenance: a valid deployment checkpoint, or an authenticated comparison of every serving module byte and complete declared runtime/binding/route configuration against an isolated build of protected Git inputs. Retain the reconstruction proof and exact serving version; never infer equivalence from a historical SHA. Missing/unmatched proof, conflicting metadata and mixed traffic fail closed.

## Exact evidence

- Record candidate IDs, exact hashes, generation run/attempt, original generation SHA, validation SHA, publication SHA, gate results, and live identity.
- Never claim old tests cover materially changed code, or a receipt covers different candidate bytes. Do not duplicate full-suite runs on unchanged inputs. Preserve manual E2E evidence only for the runtime/package bytes it tested.
- A failed later stage resumes from its latest valid checkpoint. Do not relabel an old generation as a newer commit or regenerate merely because main advanced without generation-relevant changes.
