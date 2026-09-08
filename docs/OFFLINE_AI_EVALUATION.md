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
no secret values were accessed. Sonnet baseline run `34234760078` made one
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

The user added repository Actions secret `OPENAI_API_KEY`. Its value was never
read or copied. The existing evaluation-step mapping was correct; PR #178 fixed
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
