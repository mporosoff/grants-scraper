# Repository instructions

## Review convergence and exact-head validation

- Treat every automated PR or code review as an atomic round bound to one commit SHA.
- After a review is requested or automatically triggered, do not edit code, commit, push, or resolve individual review threads while that review is pending. Wait for its terminal completed status and collect all findings from that SHA.
- Consolidate completed-review findings before remediation. Group related findings by their underlying invariant and perform a bounded, read-only audit of the complete affected invariant family before editing.
- Apply all accepted findings from a completed review in one remediation batch where they can be safely combined. Run targeted checks before launching another full protected gate.
- If opening or updating a PR automatically triggers the configured comprehensive review, use that review and do not request a duplicate. If the candidate changes after completed-review remediation, request exactly one exact-head re-review.
- Never describe a candidate, review, test run, or gate as “final” while any required review or check is pending.
- Do not manually duplicate full-suite runs for the same SHA, and never use checks from an earlier SHA to merge a changed candidate.
- If a completed exact-head re-review finds another consequential issue in the same subsystem after one remediation round, do not begin another autonomous fix/review loop. Stop and report the convergence failure, consolidated findings, current SHA, completed evidence, and recommended next action.
