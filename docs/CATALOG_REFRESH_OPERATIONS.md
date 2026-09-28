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
