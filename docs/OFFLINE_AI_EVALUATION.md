# Frozen offline AI evaluation, September 8, 2026

This preparatory entrypoint evaluates public-derived evidence only. It does not
change production team routing, Cov4, the catalog, browser features, or releases.
Production remains on the established Sonnet route until a separately reviewed
promotion has adequate evidence.

`evaluation/offline_team_frozen.json` pins 24 scopes and bounded researcher claim
snapshots from protected `916cc29ae0354923925956516d7700a6f7a7eebc`. The last six
are untouched holdouts. Scope expectations are grounded in the supplied source;
reviewed curated role rationales and gaps remain independent evidence. Historical
generated decisions are not truth labels. No holdout expectations may be changed
after candidate results are opened. The two predeclared stability cases are
optoelectronic materials and the NARMS surveillance program.

Both providers receive the same frozen claim pools, combining reviewed curated
members with bounded token-overlap retrieval. This isolates model-stage quality;
it does not measure Voyage recall. Actual existing Voyage retrieval is exercised
by the later bounded production pilot. Source quotes, supplied claim identities,
edge bounds, independent verification, and no-upgrade rules use the existing
deterministic production validators. Model outputs still require an independent
comparison with source annotations, including direct/method-transfer/adjacent
distinctions and honest gaps; passing JSON shape alone cannot authorize promotion.

Predeclared acceptance requires zero critical false acceptance, fabricated
quotes/claims, cross-topic leakage, or unsupported upgrades; at least 90% scope
decision accuracy, 85% legitimate-scope acceptance, 95% valid completions, and
useful proposal coverage within 10 percentage points of the established baseline.
Both aggregate and six-holdout results must be reported. Rejecting everything
cannot pass. This small sample cannot establish corpus-wide accuracy.

Select all-Luna only if every stage passes. An exact retained Sonnet baseline
may be reused; the confirmed Anthropic billing pause prohibits new baseline or
hybrid-verifier calls. If Luna is inadequate, at most one mini comparison is
allowed within remaining budget. Retain established stages where replacement
evidence is insufficient, while reporting their separate provider availability.
The separate Cov4 evaluation uses all 43 frozen candidates, the unchanged
production prompt and ownership guard, and real native/referenced bypasses.
Its acceptance requires zero genuine-child losses, contaminants published,
cross-opportunity publication, classifier errors, and bypass classifier calls.
Insufficient evidence or budget retains production Cov4 unchanged.

Run `offline-ai-evaluation.yml` on **main**, choosing one phase at a time.
The completed September 8 phases are `preflight`, `teams-luna`, `teams-mini`,
and `cov4`. Do not repeat them to seek a different result. `replay` reuses
completed exact stages without provider calls. Do not dispatch `teams-sonnet`,
`teams-luna-sonnet-verifier`, or the two-provider `stability` phase while
Anthropic is paused. Repeating stability cannot qualify a route that already
fails mandatory acceptance gates.
No untrusted PR code receives credentials. OpenAI uses only `OPENAI_API_KEY`;
Sonnet uses only `ANTHROPIC_API_KEY`. This workflow never receives Voyage,
Cloudflare, private-notice, or publication credentials.

One stable logical task shares the configured $15 ceiling across all phases.
Each request reserves a conservative UTF-8-size input ceiling plus output and
reasoning allowance before dispatch. All concurrent reservations count. Actual
provider usage is captured before parsing and reconciled; unknown outcomes retain
their full reservation. The single request retry loop includes transport and
shape failures. Refusals and authentication/configuration failures never retry or
fall back to another provider. Completed stages are cached by their full request
contract and validated on every read; simultaneous identical calls are suppressed.

Every phase first restores the authoritative ledger, then uploads a whole-budget
reservation before any request. An always-run step retains the ledger, results,
and safe public-derived response cache as an append-only Actions artifact for
90 days. A killed run without its state checkpoint makes remaining spend
unavailable; it never resets the budget. Missing/expired evidence, authentication
failures, and corrupt state fail explicitly. Restoring a cache is not proof that
money remains. Results record requested and returned model IDs; the currently
documented Luna alias has no distinct dated snapshot listed.

Prices in `config/offline_ai.json` were verified September 8, 2026 against the
linked official model/pricing pages. OpenAI cached/reasoning tokens are subsets
of its input/output totals; Anthropic cache reads/writes are separate input
categories and are added exactly once. Missing usage remains unknown. Budget
charges may be conservative estimates, not account invoices. These application
ceilings cover this task, not unrelated users of the same account.

Initial output caps are provisional safety ceilings: 4,096 for decomposition,
8,192 for adjudication/verification including reasoning, and 2,048 for Cov4.
The baseline retains its historical 8,000 team ceiling. Final stage sizing and
any claimed savings must use measured comparable requests, not cap differences.
Receipts expose stage/provider tokens, latency, retries, cache events, failures,
and conservative charges. The warm replay disables new selection and installs a
transport that fails if any completed request tries to call a provider.

## Historical access and billing stops

The protected entrypoint merged in PR #171 at
`facd83554751c6504592c934536e781f446552cc`. Preflight run `34234658950`
found no `OPENAI_API_KEY` in the Actions step and made zero API requests.
Repository and existing environment secret-name metadata also lacked that name;
the operator inspected names only. Sonnet baseline run `34234760078` made one
request and received HTTP 400, then stopped that provider's new requests.
Its usage was unreported, so the ledger retains the conservative $0.088875
reservation. The original adapter did not capture the provider error category;
its cause is unknown. Later diagnostics allowlist error categories without
retaining response bodies or error messages.

Those initial runs completed no scope. They provide no matched quality,
noninferiority, useful-output cost or savings evidence. They remain historical
in `evaluation/offline_ai_selection.json`; the resumed results below supersede
only the obsolete OpenAI credential-unavailable status. The immutable frozen
inputs and historical Cov4/MEAS3 evidence remain unchanged.
The production pilot in run `34244913333` selected five scopes. Three concurrent
Sonnet decomposition requests returned the sanitized `insufficient_credit`
category; no later requests were dispatched and no scope completed. Reported
tokens are unknown; $0.273103 remains conservatively reserved, separate from
seven Voyage requests. This is no evidence of model quality or cost savings.
The candidate was rejected for an independent document-wrapper module-identity
defect before production mutation. Its reports remain retained. The confirmed
Anthropic account stop is recorded in `generation_provider_pauses` so a corrected
replacement cannot repeat the paid pilot or spend on document classification.
The user confirmed that Anthropic has no credit. Preserve this persistent
billing pause and all historical charges. Do not retry Anthropic, rotate its
key, request replenishment, or clear the pause. Existing valid derived outputs
remain reusable; a configured provider is not necessarily available.

## Resumed OpenAI access and finite quality results

The user added repository Actions secret `OPENAI_API_KEY`. The trusted Actions
step consumed it for API authentication; no value was inspected, printed or
copied by the operator. The existing evaluation-step mapping was correct; PR #178 fixed
only the obsolete missing-key stop and unsuccessful preflight marker. It merged
as `92f3856adf5c4b432a2ad4bc340c709dcd0b9038` after clean exact-head review and
required checks. Preflight [34255768570](https://github.com/mporosoff/grants-scraper/actions/runs/34255768570)
then made one successful `gpt-5.6-luna` Responses request, zero retries,
44 input and 14 output tokens, estimated at $0.000026.

The same frozen 24 scopes and six holdouts were evaluated without changing
prompts or acceptance criteria:

| Route | Correct scope decisions | Legitimate scopes accepted | Holdout correct | Proposals | Requests / retries | Estimated cost |
| --- | --- | --- | --- | --- | --- | --- |
| Luna, [34255888466](https://github.com/mporosoff/grants-scraper/actions/runs/34255888466) | 17/24 (70.8%) | 11/18 (61.1%) | 3/6 | 9 | 46 / 0 | $0.050465 |
| Mini, [34256488126](https://github.com/mporosoff/grants-scraper/actions/runs/34256488126) | 16/24 (66.7%) | 11/18 (61.1%) | 3/6 | 4 | 48 / 0 | $0.203133 |

Both completed all schema-valid assessments, but both fail the unchanged 90%
scope-accuracy and 85% legitimate-acceptance gates. Both rejected all three
legitimate holdout scopes. For example, the frozen optoelectronics child was
rejected as too broad. Mini also accepted the annotated NARMS surveillance scope
as suitable, although assembly produced no team because evidence was insufficient.
No exhaustive semantic safety pass is claimed after these blocking scope failures.
No exact successful Sonnet baseline exists for this frozen three-stage comparison;
historical team cards do not establish identical retrieved inputs. Matched
noninferiority and measured savings remain unproven. The tested routes cannot
be promoted by adjusting expectations or by adding an unfunded Sonnet verifier.

Cov4's independent [34256646858](https://github.com/mporosoff/grants-scraper/actions/runs/34256646858)
evaluated all 43 frozen candidates with the unchanged prompt and ownership guard.
It retained all 28 genuine children, prevented both cross-opportunity cases, and
made zero classifier calls for 5 native and 14 referenced bypasses. However, it
admitted the annotated organizational heading `360678:x-org-bes` (Basic Energy
Sciences), violating the zero-contaminant rule. Its 43 requests had no retries or
API errors and cost an estimated $0.009219. This was evaluation-only publication
eligibility; no trial topic was published to production. Production Cov4 remains
configured for paused Anthropic and unavailable for new paid classifications.
Unchecked topics remain withheld.

The restored logical ledger now retains $0.351718 in estimated charges, including
the original unknown-usage $0.088875 Anthropic reservation. New OpenAI work totals
138 requests and $0.262843. No Anthropic request followed secret provisioning.
A local copy of Luna's completed state passed a transport-forbidden replay with
46 cache hits, zero new requests, unchanged charges and unchanged provider stops.
The original artifact was untouched. These are dated application estimates, not
invoice totals; fewer useful proposals are not evidence of cost-effectiveness.

Infrastructure publication is complete: generated merge
`bd933e91925c7ef8e67c8ea0cc9920f3cc135d1b`, candidate
`16bf1e7f39f04e6b15a7ab47ce6b43a80ae804a2f21c180570ae1f09522d0395`, and
run `34247479596` verified exact Pages assets, provider smoke and serving Worker
version `312bf71d-19d0-4fef-8226-d2bbf7cc8c04` with its complete fingerprint.
The later team assembly `34253575692` made zero provider calls but could not
finalize its candidate artifact; no validation or production mutation followed.
It was not regenerated. The already published release remains authoritative.

Credential access is resolved. Provider migration and targeted recovery of
previously available teams are **required but blocked**, not completed or optional:
no tested replacement meets the frozen gates. A new bounded provider/prompt
evaluation with independent evidence is needed before those outcomes can proceed.
Keep the original results and holdouts intact, preserve Anthropic's pause, and
do not regenerate the catalog to address a model-quality failure. Exact phase
contracts, receipt hashes, case results, accounting and separate outcomes are in
`evaluation/offline_ai_access_quality_20260908.json`.

## Authorized prompt-repair round

After these failed trials, the user authorized one new bounded team-prompt repair
evaluation with independently reviewed source references and six fresh holdouts.
The user also reported funding Anthropic and separately authorized **one baseline
only**, within the same remaining $15 evaluation allowance. This supersedes the
evaluation billing stop only for that finite baseline. The production Anthropic
pause, Cov4 configuration, historical results, original holdouts, prices, request
limit and all previously charged usage remain intact.

`evaluation/offline_team_prompt_repair_frozen.json` pins the original 18 development
cases without changing their source or claim inputs, plus six new holdouts from
verified public candidate `16bf1e7f39f04e6b15a7ab47ce6b43a80ae804a2f21c180570ae1f09522d0395`.
The new cases cover a funded catalyst/reactor child, hearing restoration research,
canine cancer immunotherapy research, conferences, scholarships and service
delivery. Scope expectations and capability limits are grounded in their supplied
source before either route runs. Every numerical acceptance criterion is copied
unchanged from the original frozen evaluation. Historical model decisions are
not truth labels, and new holdouts cannot be relabeled after results are opened.

The Sonnet baseline uses the unchanged production prompt. The one all-Luna
candidate clarifies only decomposition: a coherent funded research domain may
offer multiple methods without prescribing one experiment. It still rejects
whole umbrellas and operational/service scopes, retains verbatim source quotes,
and uses the existing independent adjudication/verification and deterministic
evidence validators. Source and claim pools are identical across both routes.
No production prompt, route, scientific contract or generated asset changes here.

Run the existing protected workflow with `phase=round2-sonnet` and
`authorize_anthropic_baseline=true` once, then `phase=round2-luna`. Both phases
restore `economical-ai-20260908` accounting and persist its outer reservation
before provider work. The first baseline dispatch records a consumed grant tied
to the frozen protocol. The same interrupted baseline may resume completed stages;
it cannot clear a new authentication/billing/provider failure or authorize a
different protocol. Between baseline jobs Anthropic is paused in evaluation, so
the grant does not enable old Sonnet or hybrid phases. Production's separate
`insufficient_credit` pause is never cleared by this entrypoint.

If mandatory quality checks pass, `phase=round2-stability` repeats only Luna's
two predeclared cases. It receives no Anthropic key. `phase=round2-replay` forbids
provider transport and replays only retained scientific decisions. Its cache
reader cannot modify caches, provider pauses, events, or spending. Replay receipts
cover both route contracts and exact result-file hashes; new results may extend
coverage only while every previously covered file remains byte-identical. Missing
or modified evidence fails closed and preserves the prior receipt. Completed
case/phase contracts fail closed on identity mismatch; a late workflow failure
does not authorize a new trial, altered holdouts, or reset spending. Promotion
still requires independent source/claim review, matched useful-output comparison,
all unchanged gates, and a separately reviewed production configuration.

## Completed comparison and independent functional recovery

The authorized round is complete on protected SHA
`6b0eeca92db892d8294d8b74ba31b9725f41e1a4`. Sonnet run `34265194226`
established working access but scored 21/24 correct scope decisions and accepted
15/18 legitimate scopes, below the unchanged 90% and 85% thresholds. It used
59 requests including three retries, estimated at $1.746518. Source review also
identified omitted required capabilities in scope `361205` and unsupported
neural-recording inferences in `356811`. These trial outputs were not published.

Repaired-Luna run `34267226821` scored 20/24 and 14/18, using 52 requests without
retries, estimated at $0.062044. It is not promoted; no stability run, hybrid,
additional model search, or relaxed quality criterion follows that failure.
The exact receipts, per-case hashes, limitations, and consequential Sonnet
findings are in `evaluation/offline_team_prompt_repair_20260908.json`.
Replay `34268178167` verified all 48 retained decisions with zero requests and
an unchanged ledger. Total evaluation accounting is 250 requests and $2.160280
against the original 300-request/$15 ceiling; unknown historical charges remain.

The user's subsequent authorization separates functional recovery from model
optimization. Proven prior teams can be restored deterministically without a
new model. Production Anthropic recovery requires working access and adequate
behavior; because the baseline exposed concrete defects, those require focused
repair before clearing its production pause. The established Sonnet Cov4 route
has a separate authorized bounded service check; its failed OpenAI replacement
does not establish Sonnet unavailability or authorize unchecked topics.

## Established Sonnet recovery check (2026-09-08)

The authorized 24-case Sonnet/repaired-Luna comparison is complete and neither route passed the unchanged quality gates. Luna remains unpromoted. Working Anthropic access alone does not clear the production pause. The confirmed existing Sonnet defects are three false bounded-scope rejections, an omitted required measurement gap, and an unsupported neural-recording capability inference.

`evaluation/established_sonnet_repair_frozen.json` freezes nine affected regression/control cases and the minimal proposed prompt clarification. `recovery-sonnet` evaluates those exact source/claim snapshots with established Sonnet, original schemas/validators and the existing 8,000-token ceilings; `recovery-replay` checks exact decisions without credentials or provider requests. This focused regression is not another 24-case holdout comparison or a new model search. Independent source review of every required check remains necessary before enabling repaired production prompts. Historical comparison evidence is preserved.

`cov4-sonnet` separately checks the unchanged established Cov4 request on a genuine child and the organizational-heading contaminant rejected by the frozen reference. It verifies returned model identity and preserves bounded unresolved diagnostics. It publishes no topics and makes no migration-equivalence claim. Existing ownership and zero-call native/reference contracts remain required. All phases restore the same logical $15/300-request evaluation ledger (250 requests and $2.160280 charged before these checks), retain safe completed work, and cannot clear a new billing/configuration/security stop. Only the obsolete evaluation-scoped pause is resumed for these explicitly authorized finite checks; production configuration is unchanged.

Functional recovery is independent of model optimization: candidate `26bb1731731005c18fcd355184b4ad21805b52fd4c0216d51bbe7f9adf5f19c5`, merged through PR #183 as `35a2b19272e2f6b0a3b8c479cb1c0576f0682bea`, restored 61 previously available scopes using retained exact source/claim/decision proofs with zero team requests. Run 34269973299 verified exact Pages bytes, retained Worker fingerprint and pre/post provider smokes. Of the prior 96 scopes, 76 are available and 20 remain pending: 19 changed-source scopes and one declared branch requiring source revalidation. No pending scope has yet been counted as paid reassessment or legitimate removal.

The first established-service check is now retained in `evaluation/established_sonnet_repair_20260908.json`: Sonnet corrected the two unsafe measurement/recording gaps and the structural-biology false rejection, but still rejected the electrochemical child and hearing-restoration goal. It reached 7/9 scope accuracy and 19/21 schema-valid responses, below the unchanged gates. Cov4 access worked on both requests, but established Sonnet admitted the organizational-heading contaminant; it remains unavailable for new classifications. No production pause was cleared. Run 34283892954 replayed all nine team decisions with zero calls and a byte-identical ledger.

`scope-repair-sonnet` / `scope-repair-replay` are a second distinct focused attempt, frozen in `evaluation/established_sonnet_repair_2_frozen.json`. The decomposition instructions now define specificity as a coherent fundable research goal and remove the conflicting requirement for a fully specified experiment or missing referenced details. All nine source/claim inputs, original acceptance criteria and the successful adjudication/verification prompts are unchanged. New schema failures retain bounded safe field diagnostics. This materially changed decomposition contract requires checking its affected cases again; all prior results and charges remain preserved. The shared ledger has 273/300 requests and $2.772630/$15 charged before this attempt. No further Cov4 trial or model search is included.

The second Sonnet repair (run 34284732993) corrected all nine scope decisions and passed the schema-rate gate (21/22 responses). Independent source review still found an unsupported experimental-capability upgrade: scope `344592:ab-0019`, role-2, claim `urh-000063-c002` was credited with fabrication/processing from the supplied evidence “silicon integrated nanophotonics.” The exact reason and violated contract are retained in the machine-readable report. The proposed prompts remain evaluation-only and the production pause remains recorded; numerical success is not a clean quality result. The latest replay (34285066778) covered all nine decisions with zero requests and a byte-identical ledger. Total evaluation use is 295/300 requests and $3.577096/$15; no request or spending cap is increased.

Functional recovery continues independently. Fourteen additional retained team graphs were checked against the current candidate: their original scope fingerprints reproduce from protected publication #159; official title, description, URLs, number and agency remain unchanged; only the public document-fact projection differs. Source review found no change to their scientific team decisions. The explicit source-change proofs in `targeted_team_recovery.reviewed_source_changes` bind both complete old/current scope fingerprints and projection hashes. Restoration still requires the prior published graph hash, current claim revisions/eligibility, every exact source quote and complementary assembly. It retains original generator attribution and records the separate source revalidation. Missing/mismatched proof never clears a flag. The Accelerator Partner requirement on 357340 remains an explicit gap, as in the retained decision.

The fourteen source-reviewed restorations are now live: candidate `6b64ce5a872f4ba7863e23c016eeb7f4957aa18bc749cb2e45886801f78213b2`, generated merge `17262aad1f7d8036679d379b8973e512abac29fa`, run 34287621491. It verified 90 of the prior 96 scopes (15 retained, 61 earlier exact restorations, 14 source-reviewed restorations), 60 parent calls and 235 combinations. The ledger recorded zero provider requests; source/catalog/document/vector bytes stayed unchanged. Exact Pages bytes, retained Worker version `312bf71d-19d0-4fef-8226-d2bbf7cc8c04`, complete Worker fingerprint and pre/post provider smokes passed.

Two further retained rows, `363375` and `eere-exchange:DE-TA1-0003589`, use the established curated-team contract rather than the generated role/claim schema. Their protected historical source fingerprints reproduce, original decision graphs and all referenced profile hashes remain compatible, and the current bounded source supports the retained roles and explicit gaps. The CMMA row retains its declared-branch source identity. Explicit curated reviews bind the old/current fingerprints, role source quotations and complete referenced profiles; the active dependency validator still checks current eligibility and member evidence. The restoration preserves the original curated representation, without inventing generated claim references or generator attribution. Missing or changed proof keeps a row withheld, and generated rows still pass the original assembly gate.

These two curated restorations are now live in candidate `3f7a93244cd6542a3d69a849608d2c96b347e58be6b07c1aeb96126719738de3`, generated merge `43cdd6a5f0b3649d57b91bfb4390a01ba54d1f77`, run 34290241070: 92 of the prior 96 scopes, 62 parent calls and 237 combinations, with zero provider work. All seven candidate gates, exact Pages bytes, retained Worker provenance and pre/post provider smokes passed. The existing Sonnet grounding defect and the independent Cov4 contamination failure remain unresolved; deterministic recovery does not establish model-quality readiness.

Of the four remaining scopes, two have obsolete citations whose planning roles remain directly supported by the unchanged current official descriptions. For `363179`, the security role can cite the explicit secure-compute goal instead of an old table-of-contents entry. For `357493`, the investigator-initiated clinical-trial goal supports the retained optional, unfilled clinical coordination/regulatory planning role; it creates no new mandate or capability claim. Source review confirms that no role, required flag, member, claim edge, variant, objective or gap changes. The explicit citation reviews bind original published graph/source identity, old/current document-projection hashes, exact old/new quotes and the complete reviewed resulting graph. The normal generated assembly and current claim checks remain mandatory. An unrelated amendment, claim change, missing quotation or changed result fails closed.

This citation-only repair proposes 94 of the prior 96 scopes: 15 retained and 79 restored using retained evidence, including 18 explicit source reviews. It makes zero new provider assessments and counts zero legitimate removals. Two remain pending: `332894:superconducting-qubits` lacks current bounded child-declaration proof; `356953` lacks the retained phased-milestone source evidence needed for its objective and required gap. Neither is silently reclassified as a scientific rejection. New source/profile/claim changes invalidate the narrowly bound restoration proofs normally.
