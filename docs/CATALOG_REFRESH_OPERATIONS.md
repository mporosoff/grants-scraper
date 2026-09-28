# Daily catalog refresh operations

The catalog release workflow requests starts at 10:17, 14:17, 18:17, and 22:17 UTC. GitHub may delay or drop a scheduled event; these are retry opportunities, not four paid refreshes.

A daily window begins at 10:17 UTC. Before that time, the previous window remains active. A scheduled run skips generation only after authenticating the current candidate, its completed publication and live-verification evidence, and its catalog source `generated_at` within that window. Pipeline, assembly, and verification times do not advance source freshness.

The existing coordinated release lock serializes refresh, publication, and live checks. A retained unfinished candidate is recovered with its original artifact and spending owner. An unchanged failed validation is reported without repeating its complete gate. If spending was reserved but no complete candidate remains, the workflow reports the original run and holds: inspect its retained ledger and resume that logical run instead of allocating another allowance.

Daily reporting distinguishes an already-current catalog, work due, recovery, and a hold. Publishing an older candidate does not satisfy the daily freshness check. Incomplete scheduled refreshes update the existing release incident. Email delivery depends on GitHub notification settings. If GitHub delivers none of the scheduled events, no Actions-based check can run or send an incident during that gap.

Team generation remains controlled separately by `config/offline_ai.json`; the schedule does not enable it or change any provider spending limit.

## September 28, 2026 incident

At 17:37 UTC, GitHub had created no September 28 repository workflow runs despite the active 10:17 UTC schedule. The public catalog and current main agreed on the September 27 source timestamp. Cache-busted reads and exact public asset hashes ruled out a stale browser/CDN copy. Previous daily events had arrived several hours late. GitHub reported no current Actions outage; the exact provider-side reason for this missing event was not established.
