> Evaluation amended by the user during Stage 1: see EVALUATION_AMENDMENT.md. The original summary is preserved in history/PLAIN_ENGLISH-v2.0-original.md.

> Stage 2 and the single $10 experiment ceiling are now authorized by B1, with cumulative Stage 2 spending limited to $6. See BUDGET_AMENDMENT_B1.md and reports/stage-2-report.md for the actual implementation checkpoint and remaining limitations. Stage 3 and publication remain unapproved.

# The revised plan in plain English

**Version 2.0 · September 9, 2026**  
This explains the authoritative `PLAN.md`. It is not a report that the system has been built or deployed.

## The central idea stays the same

Keep the interface you like. Change the calculations behind it.

When someone clicks **Build a team**, the application calculates relevant people and several complementary groups for that particular call or selected child topic. Removing someone, adding someone, switching options, or retrying after a failed asset download does not make a paid AI request.

We still prepare reusable ingredients when a call or public profile changes: the call’s scientific aspects, public profile passages, and compatible numerical representations of that text. Preparing missing ingredients may have a bounded cost. Forming and editing teams from prepared ingredients does not need another model call.

The first team interaction may download a shared public package. It then calculates only the scope the user selected. Downloading ingredients for multiple enabled calls is not pre-generating all their teams.

## What I corrected in the previous plan

### A group must be reasonable before it is compared with other groups

Being the best team in a bad pool is not enough. The revised plan requires a meaningful connection to the main scientific purpose, useful contributions from its members, and minimum absolute relevance before a group can appear among the alternatives.

A biologist does not get onto a catalysis team for being different. They need an applicable scientific contribution or technique. An appropriately documented spectroscopy method might be useful; unrelated gene-expression interests would not become relevant through a diversity bonus.

### Four people is not automatically better than two

A score that adds scientific coverage often increases when another person is added, even if the improvement is tiny. The new plan explicitly chooses the smallest reasonable group close to the best coverage found. It does not fill every slot simply because the interface allows four.

It also checks the final group, not only the order people were added. If a later addition makes an earlier person redundant, the algorithm should reconsider the combination instead of leaving redundant names in place.

### Useful alternatives do not have to be scientifically distant

We first find good groups. MMR, if it helps, then reduces repeated membership among those groups. It does not reward different departments or distant scientific fields.

Up to eight reasonable options can appear through the existing controls. Fewer is acceptable. Different people doing the same appropriate work are valid alternatives; we will not call them different scientific strategies unless they really are.

### A similarity score must not turn into a false claim of expertise

There are two separate questions: “Is this person worth considering?” and “Does their public evidence establish this exact contribution?”

The first can be approximate. The second must not be invented. The existing interface already supports unconfirmed or adjacent contributions. A strong recommendation score does not automatically activate “Direct evidence” or claim every role is covered.

The system will quote the actual profile passage and show why it is relevant. It will not generate an elaborate narrative that quietly adds genomics, fabrication, equipment, or clinical experience absent from the profile.

### All reasonable matches must remain accessible

The current engine has rules that can hide replacement candidates when a role is not already confirmed. Those rules cannot be copied into the new engine unchanged.

The new calculation keeps the full admitted researcher list separate from the handful of people in its preferred groups. Someone should not disappear merely because they are absent from the eight displayed team options.

The existing interface still requires removing a person before adding another when all four slots are full. That workflow stays. No new screen or control is introduced.

### A prepared call is not a promise that a group exists

Some calls will have several useful individuals but no convincing complementary pair. Others will have little relevance to the current directory. Those are legitimate outcomes.

The engine must handle them without crashing, inventing members, erasing the individual matches, or counting them as successful team recommendations. We will separately report how many calls have prepared inputs, matched people, and reasonable groups.

## Where Bayesian methods fit

Bayesian scoring may help combine clues about the scientific subject, applicable technique, and context while regularizing weak evidence. It does not make the team selection random. We use a fixed fitted model and deterministic calculations.

It also does not earn its place automatically. We compare it with a simpler fixed score and a regularized non-Bayesian model. The simplest approach that delivers the needed usefulness can win.

Use one fixed offline model judge for most semantic assessment. Its development labels may train optional statistical scorers, but they are noisy machine labels, not expert ground truth or proof of calibrated human preferences. Marc is the sole confirmed human reviewer, with at most 20 compact development checks and 20 separate final-audit items. No paid judge runs occur in production interactions.

## Handling updates and mistakes

The entire calculation uses one consistent version of the source, profiles, vectors, and scoring model. It must not mix a new faculty directory with old vector positions or show an explanation for an earlier selection.

A profile correction updates the affected ingredients. That person might become more or less relevant to many calls, so several team rankings may legitimately change. We reuse the unchanged computations; we do not promise every other team stays identical.

Removing someone excludes them from automatic suggestions in that context. It does not label them a bad researcher globally. The existing deliberate restore/add path remains available.

Corrupt or missing data should produce the current retry/unavailable experience, not a paid fallback request. Expired calls and withdrawn claims cannot reappear because an old result was cached.

## A stronger test, without demanding perfect recommendations

We retain the proposed 240-case evaluation: 180 coherent scientific scopes and 60 controls. The controls include broad calls, sibling topics, irrelevant outsiders, legitimate transfers, source changes, and sparse profiles.

Half is for development and half stays sealed. Related calls and their children stay together; near-duplicates are not independent tests. The same researcher directory may appear on both sides because we are testing new calls for that directory, not claiming the result generalizes to every university.

We select the winning method before looking at the sealed results. We do not try many models on the holdout and call whichever looks best independently confirmed.

The fixed model judge, supplemented by Marc’s capped evidence-first blind audit, assesses whether suggestions are reasonable and useful for discussion, whether a group brings complementary contributions, and whether explanations are truthful. They do not certify that the people must work together or will win a grant.

The target remains approximately four out of five top suggestions being reasonable, very few clearly unrelated automatic members, and useful groups where the directory supports them. We also report empty lists, no-group cases, short lists, and uncertainty. Returning almost nothing cannot manufacture a good score.

The planned annotation work is a real dependency, not something hidden in the implementation. Stage 1 identifies what assessments already exist, what review work is needed, and who is actually available. There is no new public review interface or unsolicited recruiting campaign.

## The first release is still meaningful

The target is 150 prepared current scopes across at least 80 parent opportunities, including at least 50 child scopes where real source inventory supports that distribution. We first activate 50 representative scopes, verify that release, and then expand to the agreed 150.

Both configurations are prepared and tested before publication. The move from 50 to 150 has its own release identity and live verification. Existing valid teams outside this inventory remain available through the legacy route.

These numbers describe ready scopes, not 150 promises of perfect teams. We will not choose only easy calls to make the system look good, pad the child count, or force eight options when there are fewer reasonable choices.

## Four stages, with a report and a stop after each

**Stage 1: inspect and settle the details.** Create or verify the isolated experimental branch, freeze the presentation, inspect data and loading costs, define the grouped evaluation, record the fixed judge route and Marc’s capped human audit, and propose one explicit preprocessing budget and safe execution path. No paid calls or production changes.

The report explains what exists, what is missing, what could conflict with the interface freeze, and exactly what Stage 2 would do. Then Codex stops.

**Stage 2: build and compare on development cases.** Implement the numerical engine and nonvisual adapter, test relevance and complementary selection, compare simpler and Bayesian models, and evaluate whether MMR helps. Record failures and actual costs. Freeze the finalist before accessing holdout results.

The report says which components worked and which did not, shows examples, and identifies unresolved issues. Then Codex stops.

**Stage 3: test the frozen system independently.** Evaluate the sealed cases and run the complete existing browser/accessibility suite against the final integrated candidate. Verify the unchanged interface, all lists and options, source links, add/remove behavior, error paths, and zero paid interaction requests. Prepare the 50/150 releases and rollback.

The report gives criterion-by-criterion results, uncertainty, failures, and a ship/revise/defer recommendation. Then Codex stops. It does not deploy because a test badge is green.

**Stage 4: publish and verify.** After your approval, complete independent review, protected merge, the 50-scope release, and the tested expansion to 150. Verify the actual live outputs and preserve rollback and existing coverage.

The final report distinguishes what is live from what was only implemented, documents actual costs and limitations, and stops before any wider expansion.

## How to start

Use `HANDOFF.md` and the Stage 1 prompt in `prompts/01_STAGE_1.md`. Give Codex the whole plan, not just this summary. Do not paste all four execution prompts at once.

The important change is not a more complicated model. It is a clearer contract: reasonable relevance first, useful complementarity second, truthful explanations throughout, and no per-team token loop.
