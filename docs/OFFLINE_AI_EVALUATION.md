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

Evaluate Sonnet and all-Luna once. Select all-Luna only if every stage passes.
If only verification fails, evaluate the actual fixed Luna/Sonnet-verifier route.
If Luna is inadequate, at most one mini comparison is allowed within remaining
budget. Retain established stages where replacement evidence is insufficient.
The separate Cov4 evaluation uses all 43 frozen candidates, the unchanged
production prompt and ownership guard, and real native/referenced bypasses.
Its acceptance requires zero genuine-child losses, contaminants published,
cross-opportunity publication, classifier errors, and bypass classifier calls.
Insufficient evidence or budget retains production Cov4 unchanged.

Run `offline-ai-evaluation.yml` on **main**, choosing one phase at a time:
`preflight`, `teams-sonnet`, `teams-luna`, optional
`teams-luna-sonnet-verifier` or `teams-mini`, `cov4`, `stability`, and `replay`.
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
