# Daily catalog refresh operations

The catalog release workflow requests starts at 10:17, 14:17, 18:17, and 22:17 UTC. GitHub may delay or drop a scheduled event; these are retry opportunities, not four paid refreshes.

A daily window begins at 10:17 UTC. Before that time, the previous window remains active. A scheduled run skips generation only after authenticating the current candidate, its completed publication and live-verification evidence, and its catalog source `generated_at` within that window. Pipeline, assembly, and verification times do not advance source freshness.

The existing coordinated release lock serializes refresh, publication, and live checks. A retained unfinished candidate is recovered with its original artifact and spending owner. An unchanged failed validation is reported without repeating its complete gate. If spending was reserved but no complete candidate remains, the workflow reports the original run and holds: inspect its retained ledger and resume that logical run instead of allocating another allowance.

Daily reporting distinguishes an already-current catalog, work due, recovery, and a hold. Publishing an older candidate does not satisfy the daily freshness check. Incomplete scheduled refreshes update the existing release incident. Email delivery depends on GitHub notification settings. If GitHub delivers none of the scheduled events, no Actions-based check can run or send an incident during that gap.

Team generation remains controlled separately by `config/offline_ai.json`; the schedule does not enable it or change any provider spending limit.

## September 28, 2026 incident

At 17:37 UTC, GitHub had created no September 28 repository workflow runs despite the active 10:17 UTC schedule. The public catalog and current main agreed on the September 27 source timestamp. Cache-busted reads and exact public asset hashes ruled out a stale browser/CDN copy. Previous daily events had arrived several hours late. GitHub reported no current Actions outage; the exact provider-side reason for this missing event was not established.

## Notice-processing time limits

The September 28 scheduled run reached the 75-minute generation cutoff inside notice extraction, before any provider request or candidate was produced. Its retained accounting recorded zero charges. The document wrapper now enforces the existing `max_seconds` budget, reserves time to save results, and limits each parsing/projection unit. Progress reports identify the phase and opportunity ID without logging source text or prompts.

Timed-out work remains explicitly incomplete. It cannot advance source-check timestamps or publish unchecked derived facts or subtopics. Any deadline-exhausted or deferred work blocks vector generation, candidate creation, and the independent publication gate. The completion marker clears only after the full document phase passes existing health checks. Completed evidence checkpoints remain local to the runner; they do not survive a failed runner teardown. The generation run retains its original spending identity and exact-response cache for recovery.

Before retrying, retain the original artifact ZIPs and their authenticated metadata/digests. Use a partial retry: rerun the specific failed generation job when the selected code is unchanged, or rerun the specific plan job and its dependent jobs when main contains a required repair. Avoid rerunning all jobs: during this incident it removed the previous attempt's spending artifacts. Publication readiness is bound to that run's authenticated release-plan artifact, including an inherited earlier plan when only failed jobs are retried. The run's original event SHA does not necessarily identify the code selected by a later plan.

The retained progress log identified NSF CAREER 22-586 (339594): a nested heading expression took longer than the per-notice deadline to reject an uppercase sentence ending with a period. The replacement checks the same heading language in linear time. A bounded diagnostic of the same public notice completed in about 1.3 seconds without provider requests. The IARPA adapter also now sends its truthful source identity and text-format preferences explicitly through the shared downloader; its prior document-oriented request profile returned HTTP 403.


## Retained September 28 program-area correction

The replacement refresh `36480049073` completed source and document work, then
publication review found administrative language classified as program scope.
Its immutable parent is
`85954ae156ca45aea2b6bac4db500f747e9e64725c230716087b085817c0c1de`.
Do not rerun source collection or replace this candidate with an unrelated run.

The protected manual `program-area-revalidation` stage accepts only that exact
`candidate_run` and `candidate_id`. It authenticates the parent artifact and its
original spend evidence, revalidates retained citation excerpts, and keeps the
original source/evidence timestamps and all team outputs. The correction audit
has its own timestamp; it does not claim a new source fetch.

Search passages include program-area labels. A changed corpus therefore needs
one coherent vector pass under the existing builder limits, separately from the
unchanged document-AI ledger. A durable reservation is uploaded before any vector
request. A completed vector checkpoint is uploaded before package assembly and
must be reused on retry. A reservation without a complete verified checkpoint
blocks another pass; a retry must never reset its allowance. No document or team
provider credentials are passed to this job.

The child manifest retains the original generation identity and records typed
`program_area_revalidation` provenance for the affected outputs. Ordinary
validation, exact-head review, protected merge, Pages publication and live
verification still apply. Source collection and ordinary reuse remain unchanged.
Automatic paid work is held while the protected catalog still records the known
old extractor fingerprint; publication of the corrected candidate clears that
specific hold and restores normal daily planning.

## Retained October 8 source correction

Run `36896442720`, attempt 4, retained candidate
`5801e4912b642ad70e4383b0f805adc95aad7d892b85f8b7638aeca958da85e6`.
Its publication was stopped before deployment: the new consolidated DOE portal
marks CMMA Topic Area 1 closed, and the completed publication review found an
NSF digest duplicate. The bounded NSF identity audit found four duplicate digest
entries and one stale-edition conflict. The reviewed evidence is in
`evaluation/catalog_source_withdrawals_20261008.json`. This exact parent is
quarantined by ordinary validation, materialization and publication.

The protected manual `catalog-source-recovery` stage accepts only that run and
candidate ID. It authenticates the candidate ZIP, all 69 retained spending-state
files and the original reservation against pinned GitHub artifact hashes. The
original logical document allowance remains $2/300 requests, with 66 requests
and $0.441023 charged, including the conservative unknown-usage reservation.
The correction stage receives no provider credentials and reserves no allowance.

The derived catalog withdraws exactly the six evidenced records, removes them
from fallback records, preserves all surviving record payloads and source clocks,
and rebuilds indices, counts, metadata, feeds and page references. Historical
source failures remain failures; the correction audit does not claim a complete
source refresh. Closed-call and duplicate-correction events retain prior history.

Search derivation requires the complete original corpus and asset to validate,
then proves the new corpus is the exact ordered surviving subset. It copies
original binary rows, retains canaries and `reuse_permitted=false`, and keeps the
original six-request/$0.005978 vector-build receipt unchanged. Separate typed
provenance records zero new calls and the 1,463 retained passages. The allowlist
keeps the actual previously published generation, never the rejected parent.
Any changed surviving passage fails closed rather than being relabeled or embedded.

The child retains original generation identity with `source_recovery` provenance.
Persist it before ordinary validation, exact-head review and protected publication.
Reruns restore that exact child. Restore the temporarily disabled release workflow
only after this guarded route has merged; dispatch the exact recovery selector,
then confirm publication and normal daily planning before SAM activation.

DOE collection uses the consolidated public `exchange.energy.gov/Default.aspx`
listing with explicit ARPA-E/CMEI partitions and unchanged source IDs. Its measured
complete response was 24,636,245 bytes; a DOE-only 32 MiB limit accommodates that
source without changing the shared 8 MiB limit. A truncated or structurally
incomplete response is never accepted as a complete snapshot. NSF digest identity
requires exact official edition links or a current-day program-guidelines receipt
within the existing shared 20-GET identity budget; supplied conflicting editions
are withheld, not silently rewritten.


## Retained October 12 identity correction

Normal refresh `38275115281`, attempt 1, completed candidate
`75e383c2a4fe48ece7ca2e1afc4fc0a0470dfe9f3133654da9b306aefa8c41ff`.
Its publication review found that NASA solicitation `NNH25ZDA001N-SSF`
changed from a native NASA ID to Grants.gov `364039` without retaining the
previous ID. The resulting new/removed events were false. The same temporal
identity audit found one lost, previously proven VPR alias on Grants.gov `363829`.

Normal source merge now receives the accepted previous catalog as identity-only
input. It carries aliases through a unique sponsor/full-solicitation transition
or the unchanged canonical Grants record, validates existing official identity
proof, and rejects conflicting owners or ambiguous scopes. It never copies
historical science, deadlines, source observations or document evidence. The
next refresh retains these aliases even after the old adapter snapshot is empty.

The protected manual `catalog-identity-correction` selector accepts only the
exact run and candidate above. It authenticates that candidate, its original
spending state and reservation, and the previously published `309e3932...`
candidate against pinned GitHub artifact digests. Only the two reviewed alias
additions and two false-event removals are allowed. All 1,274 records retain their
source timestamps; all 1,476 scientific search passages and vector bytes, team
outputs, and the original six-request/$0.006010 estimated vector receipt remain
unchanged. Document-AI spending remains zero of the existing $2/300 allowance.
The correction receives no provider credentials and creates no new allowance.

The rejected parent is quarantined. Persist the corrected child, then use normal
exact-byte validation, exact-head review, protected publication and live checks.
The existing unfinished-owner safeguard holds competing automatic generation;
the refresh workflow stays enabled. After publication, the child's original
generation identity retires this owner through the ordinary daily generation
floor. Verify same-day no-op and next-window generation using authenticated
publication/live evidence; a policy prediction is not proof of future cron delivery.


## Retained October 12 NYSERDA navigation correction

Publication review of the persisted identity-corrected candidate
`051d6844ea23709628b9c9209f4a947e309d2427928b0dc19e8ffb8eb8f3cfc4`
(run `38280685194`, attempt 1) found malformed NYSERDA links containing
`? SolicitationId=`. Shared URL validation had applied prose sentence spacing
to correct official URLs, inserting the space. A current public HTTP check confirmed that the encoded
space redirects to a login page, whereas `?SolicitationId=` opens the intended
OSWPON26-1 notice. The affected family contains 41 current catalog records.
URL validation now preserves query punctuation without applying prose sentence
formatting. Existing HTML/entity cleanup and HTTP(S) validation remain. Focused
adapter-to-catalog checks cover the notice, deadline and contact paths; old
malformed-URL link-health results cannot match the corrected address.

The protected manual `catalog-url-correction` selector accepts only that exact
parent and run. It authenticates the complete parent candidate and prior identity
receipt, reauthenticates the original generation's spending state/reservation,
and applies a pinned URL-only projection. It corrects navigation fields in the
catalog, source cache and retained feed snapshots without creating new events or
changing event times. Historical document acquisition evidence, signatures and
link-health observations retain their original bytes; they are not relabeled as
successful fetches of corrected URLs. The next normal acquisition can measure
those URLs independently.

The child preserves the alias correction receipt separately, the original
source clock, all 1,476 scientific passages and vectors, scientific teams and all
spending. No provider credentials or replacement allowance enter this stage.
Exact-byte gates, review, protected publication and live verification remain
required. The rejected parent's owner is held until an authenticated protected
URL child completes publication; only its exact failed attempt and artifact
identity may then retire. Keep the normal workflow enabled throughout.
