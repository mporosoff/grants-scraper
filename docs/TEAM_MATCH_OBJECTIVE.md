# Make Team Match work better

**Active objective — October 16, 2026.** Help a researcher find a useful, credible team for a current funding opportunity. Team Match should explain each person's contribution, show the evidence behind the match, identify gaps, and make it easy to judge alternatives.

This is the single continuation objective for the numerical recommender research, contextual/on-demand qualification work, and paid team-generation work. Their results are inputs to choosing an approach; their old plans are not three parallel projects or a required sequence of iterations.

## What better means

- **Relevance:** suggestions address the actual call or topic, with current researcher and opportunity information.
- **Complementarity:** the team covers useful, distinct contributions. It identifies missing expertise rather than inventing coverage or rewarding redundant members.
- **Evidence:** a researcher contribution is supported by an identifiable source. Explanations distinguish established expertise, uncertainty, and an unsupported claim.
- **Usability and reliability:** explanations, alternatives, and adding or removing a member remain understandable and consistent. A failure or insufficient evidence is visible and does not become a confident recommendation.
- **Practical delivery:** latency and cost are measured against an agreed, bounded baseline. An approach that misses its limits is reported honestly rather than qualified by functional success alone.

The existing public product remains the starting point. Preserve working opportunity discovery, researcher intake and registry, search, awards, program-officer navigation, and Alerts while improving Team Match.

## Current evidence and controls

The prior numerical and contextual work produced useful diagnostics, but it did not establish an accepted replacement for the serving recommender. Earlier unresolved disagreements, failed quality or latency checks, unmeasured memory, inconclusive operating-point results, and incomplete migration evidence remain part of the record. Completed engineering or a successful catalog release does not erase them. Retain the findings and the specific research evidence and accounting needed for this objective. Obsolete checkouts, duplicate outputs and retired-project files may be deleted. Do not regenerate missing evidence or relabel model-assisted judgments as independent human results.

Current controls remain unchanged: contextual `public_activation` and `public_paid_work` are false in [the contextual manifest](../config/contextual_team/manifest.json), and production paid team generation is disabled for `source_quality_qualification_pending` in [the offline-AI configuration](../config/offline_ai.json). The separately qualified Cov4 document service is enabled; it is not evidence that team generation is qualified. Existing source currentness, identity, privacy, accounting, and release controls continue to apply.

This consolidation authorizes documentation and backlog cleanup. It grants no new provider calls, experiments, model or threshold search, budget, recurring paid work, registry migration, public activation, or legacy-team withdrawal. Any later implementation and spending need an explicitly bounded scope and must use the existing controls.

## One next sequence

1. Establish one baseline from the current serving behavior and retained, source-backed evidence. Record the useful behavior, concrete failures, latency and cost limits, and evidence gaps without starting new experiments.
2. Choose one approach and one bounded candidate that addresses a concrete user problem. Use the numerical, contextual, and generation findings where they help; do not require completing every former plan.
3. Agree on fixed, source-grounded checks before changing the behavior. Include relevance, complementary contributions, unsupported claims, currentness, explanations, alternatives, failure handling, and the chosen latency and cost limits. Preserve unfavorable results and distinguish functional checks from evidence of recommendation quality.
4. Implement only that candidate within its authorized scope. Run the focused contracts and ordinary required checks, and obtain clean exact-head review under the repository policy.
5. Cut over only after the exact candidate meets its declared acceptance criteria and serving compatibility is verified. Retain existing outputs and rollback evidence. A documentation edit, green CI, or an old trial cannot enable paid work or public activation.

No ranking change, evaluation run, paid generation, or cutover is performed by this plan.

## Retired standalone projects

By the owner's October 16, 2026 decision, these are removed from the active backlog:

- The Alerts orchestration redesign, including the standalone Workflows/Queues follow-up. Preserve the working Alerts service and its operational controls.
- Document-chat PDF/DOCX export and its proposed governing-document expansion. Preserve working notice chat, document parsing, and researcher/CV upload behavior.
- The standalone human pilot/review and recruitment/handoff project. Existing evaluation tools and historical records may remain useful, but there is no mandatory replacement pilot or human-review program hidden in this objective.

Retirement is a scope decision, not a claim that an old exit gate passed. Source-backed evaluation of a chosen Team Match change still matters; it does not require reviving the retired pilot or treating unqualified evidence as qualified.

See [project status](PROJECT_STATUS.md) for the deployed baseline and [the recommender continuation record](team-recommender/CURRENT.md) for the dated historical checkpoint.
