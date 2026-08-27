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
- A convergence stop is a checkpoint, not a permanent block. After that checkpoint has been reported, a new explicit user instruction to resume the named work starts one new bounded remediation round. Preserve the candidate and completed evidence, address the consolidated finding in one batch, and repeat exact-head validation. During an explicitly authorized autonomous completion run, do not pause for routine test, review, merge, migration, deployment, or verification approval; stop only for a genuinely unsafe/destructive action, missing authority or credentials, or another condition that cannot be resolved within the named scope.

### Recognizing terminal Codex reviews

- A Codex GitHub review may finish as:
  - a top-level PR conversation comment from `chatgpt-codex-connector[bot]` containing a completed `Codex Review` result and `Reviewed commit: <sha>`;
  - a submitted PR review anchored to the candidate SHA; or
  - the configured no-findings reaction, provided the PR head remained unchanged from the review request through that reaction.
- An exact-head top-level completion comment is terminal even when `pull_request_review_id` is absent. Do not keep waiting for a formal review object or approval reaction after receiving that comment.
- A review acknowledgement or “working” message is not terminal.
- Before deciding that a review remains pending, inspect the complete PR conversation comments, submitted reviews, inline review threads, and reactions. Match the reviewed SHA to the complete current PR-head SHA.
- Bound review waiting. After three unchanged checks or 15 minutes following acknowledgement or completed CI, perform one comprehensive refresh of all review surfaces. If no terminal artifact exists, stop and report the missing review instead of polling indefinitely or triggering a duplicate review.
- After a clean terminal exact-head result, proceed only if the PR head is unchanged, required CI is green, and no consequential unresolved review thread remains.
