# Funding Finder

A public funding-opportunity search engine with optional hosted AI refinement and browser-based NOFO chat.

Open the application:

https://mporosoff.github.io/grants-scraper/

## What it does

Anyone can search the comprehensive catalog without an account or API key. The browser provides:

- full-text search across current Grants.gov opportunities;
- a built-in Help guide covering search, uploaded notices, result tools, team
  matching, privacy, troubleshooting, hosted AI, and optional personal OpenAI/Anthropic API keys;
- drag-and-drop NOFO/FOA PDF chat with automatic catalog-record matching;
- one-click browsing of the complete current catalog without search terms;
- filters for status, discipline, topic, agency, eligibility, instrument,
  deadline, award size, cited-FOA availability, and special requirements;
- relevance and field-based sorting;
- one-click official FOA, agency-notice, or Grants.gov record actions;
- four-field deadline/award/eligibility/contact overviews with email POC links;
- side-by-side comparison, saved opportunities, calendar export, and CSV export;
- expandable page/section-cited FOA evidence and pagination;
- visible catalog source, size, generated time, and freshness;
- public RSS/Atom feeds for the full catalog and individual topics/source
  types; and
- a consistent light theme and Windows high-contrast support.

The page initially shows no opportunities. One guided workflow combines a
topic, optional profile/CV context, and optional filters under a single “Find
funding” action. Users can explicitly save a reusable researcher profile on
that device; saving it does not launch a competing search. Strong retrieval
uses a local fielded scorer: BM25 lexical relevance, conservative spelling and
scientific-word-form recovery, meaningful coverage for multi-term searches,
and catalog-topic signals that rerank—but never independently admit—lexical
candidates. Two-concept searches require both concepts; longer searches use a
60% concept-coverage floor. Exact titles and opportunity numbers remain highest
priority. The postings index contains terms
found in the records; it is not a pre-approved list of queries. Common,
unambiguous abbreviations add query-side context without requiring a catalog
rebuild. Unfamiliar acronyms can also be resolved from matching full phrases in
the local catalog when the enabled research profile, CV, or ORCID publications
provide enough context; ambiguous expansions are rejected. This path and
profile relevance make zero AI calls. Compound scientific concepts are kept
distinct: for example, REE/rare-earth targets, extraction methods, and ionic
liquids/ILs must provide compatible evidence instead of matching generic words
such as “processing” or “critical.” Broad BAAs and umbrella solicitations are
indexed from evidence-backed subprogram text when the official notice provides
it.

For a non-empty query, a site-managed enhanced-search Worker can add up to 12
deduplicated Potential matches. It sends the submitted query for one Voyage
query embedding, then reranks a bounded set of public opportunity passages with
the site's server-side key. Active filters constrain BM25 and semantic
candidates before top-k selection. Strong always appears before Potential;
sorting changes order within each tier without changing membership. This path
does not send the user's CV, full profile, researcher names, or ORCID
publication text.

Research descriptions, expertise keywords, CV text, ORCID topics, applicant
type, and career stage feed a separate profile reranker. With an explicit
query, that evidence can reorder the query's admitted candidates but cannot
broaden the candidate set. With a blank query, profile-only retrieval requires
multiple independent profile concepts so a single generic overlap cannot admit
hundreds of opportunities. Generic CV verbs such as “use,” “develop,” and
“research” are excluded from the profile term model. When a research description
or expertise keywords are available, those higher-confidence fields form the
profile-only admission gate; CV and ORCID terms still rerank the admitted set
but cannot broaden it. CV/ORCID terms serve as the fallback gate only when the
manual profile fields are blank.

Hosted Potential matching does not require a user key. Funding Finder also provides hosted AI,
with optional personal OpenAI or Anthropic keys retained as an advanced
alternative, to:

1. create 5–16 independent, meaningful scientific phrases and retrieve each
   through the existing filtered local Strong matcher;
2. assess at most 32 new locally qualified candidates and add at most 12 while
   preserving every ordinary Strong and Potential result; and
3. ask grounded follow-up questions over up to 10 question-relevant records retrieved from the active results.

“Chat with your results” is enabled after narrowing to 100 or fewer results. Topic questions retrieve relevant evidence across that entire filtered set using local and Voyage search before selecting at most 10 records for the answer. An initial deadline, amount, or eligibility comparison uses the first 10 results in the current order (or all results when fewer); the introduction and answer disclose that scope. Factual follow-ups preserve the previous answer’s complete evidence set, including records the model did not name, while still respecting current filters. Single-opportunity and uploaded-notice chat remain available independently of the general result count. The mobile composer stays within the visible viewport as the keyboard opens.

A user can also drop or choose a NOFO, FOA, or other funding-notice PDF in the
main search box. Funding Finder extracts page-marked text in the browser, tries
to match the notice to an existing opportunity number or distinctive catalog
title, shows the matched card with save/calendar/source actions, and opens a
document-grounded “Chat with the NOFO” workspace. No visitor key is required.
A missing catalog match does not prevent document chat.

When the scheduled Phase 3 pipeline has analyzed an official notice, the
result card shows document version/change status and compact cited facts for
submission stages, funding, duration, page limits, cost share,
eligibility/review excerpts, and application components. Each fact opens the
exact PDF page or HTML section. “Ask AI about this FOA” focuses chat on a
single result; AI may cite only evidence identifiers that the browser supplied.

The original CV or uploaded notice file is never retained. A bounded CV excerpt
is sent only when the user enables that option and explicitly runs AI
refinement or chat. Hosted requests pass through the protected Funding Finder
AI gateway, which owns the fixed prompts, schemas, feature-level model routing,
rate limits, and provider secret. An optional personal API key is tab-only
unless the user explicitly saves it on that device. Saved keys
are isolated from profiles and reviewer data, have a visible saved/loaded
status and removal control, and never enter GitHub, URLs, exports, or an
application database. Extracted uploaded-notice text, the additive refinement overlay, and chat
remain page-memory only; notice text is sent only when the user asks a question
about that document.

Team Match applies its every-researcher evidence gate locally. Enhanced ordering
may send one bounded, phrase-delimited aggregate of selected research keywords
and theme labels per unique team recomputation, but it never sends researcher
names or publication text and cannot add an opportunity that failed local
full-team fit.

Funding Finder also has a staged opportunity-to-team pilot for ten calibrated,
specific opportunity scopes. It proposes complementary three- or four-person
teams from source-traceable Hajim capability evidence, explains the team and
each person, keeps missing roles visible, and supports remove/replacement and a
manual-collaborator path. Broad parent programs never receive an automatic team.
Generated team membership is rechecked against the same runtime catalog
currentness and publication-eligible child-topic contracts used by ordinary
search. Team Match derives its current main, standby, and directory-only counts
from the canonical researcher registry while preserving saved researchers,
ORCID, and the four-person limit. The fourth public surface, Configure Faculty
Interests, accepts bounded profile corrections and nominations for protected
administrator review; Team Match remains browser-local unless its separate
review checkbox is selected. See `docs/OPPORTUNITY_TO_TEAM_ROLLOUT.md`.

Funded Awards is the third public surface. It searches public NSF, NIH, DOE
Office of Science, and DoD assistance awards through the sources' native fields,
keeps the adapters separate, and preserves direct-field or official-record
contact provenance. DoD records come from USAspending and are limited to prime
Project Grants and Cooperative Agreements; they do not provide investigator
names or award abstracts. NSF, NIH, and DOE use the Award Worker; the page runs
the same normalized DoD adapter over USAspending's official browser CORS
transport because USAspending rejects Cloudflare Worker egress, then merges the
record into the shared result and snapshot contracts.
Eligible Funding Finder cards open it in a new tab only for exact or explicitly
reviewed controlled mappings; unmapped opportunities are never assigned by fuzzy
title similarity.

Funded Awards also includes Institutional Intelligence for snapshot-native
factual summaries and drill-downs over those normalized public awards. Its ROR-backed
typeahead resolves canonical institution names, aliases, and acronyms while the
existing identity layer retains sponsor-specific UEI/IPF query identifiers.
Institution, agency, program, topic, investigator, and year filters work without
an AI key and are shareable through page URLs. The Award Worker owns immutable
membership, exact-versus-lower-bound totals, full-snapshot metrics and facets,
and direct pages of 10, 25, or 50; card hydration never changes those facts.

Person-like source-published program contacts can start a locked, single-source
Program Officer snapshot for recent five, all available, or custom source award
years. Exact same-source post-validation removes partial-name results before
totals or evidence. Deterministic portfolio browsing and aggregate facts need no
AI. For an explicit Program Officer question, the selected hosted or user-connected
provider supplies only a bounded answer intent, concept, phrase, and exclusion
plan. Meaningful one-letter scientific terms remain paired with a bounded
qualifier such as T cells, X-rays, or R language; bare one-letter terms are
rejected. The Worker then applies deterministic
full-snapshot retrieval capped at 24 public records, 800 abstract characters per
record, and 18,000 serialized evidence characters before the provider receives
that bounded evidence for a cited answer. The model never owns membership,
totals, completeness, eligibility, ranking, or award IDs.
The interface discloses completeness and abstract coverage and never describes
the result as a complete career portfolio. An optional institution question translator
uses the same hosted-by-default Funding Finder provider configuration; it only creates
a transparent filter plan and does not search or rank an award-vector corpus.

Funding Finder search criteria are shareable page parameters and can appear in
browser history or copied links. The custom anonymous usage event sends only a
random session identifier and broad usage category with an origin-only
referrer; network organization is aggregated server-side. Cloudflare Web
Analytics is disabled on every URL that contains query parameters.

Funding Finder v1.3.0 hardens this hosted path as one coordinated release
package. A catalog refresh now rebuilds every public semantic passage and
vector, validates fixed embedding-space canaries, deploys a Worker that accepts
only the current and immediately previous package, and publishes the generated
assets only after all Python, browser, quality, and Worker-handshake gates pass.
The Worker enforces separate embedding/reranking request limits, global request
and daily-token ceilings, and a fail-closed circuit breaker. If enhanced search
is unavailable, Strong matches and the local Team Match order remain usable and
the page says that enhanced matching is temporarily unavailable.

Match-quality controls include `not relevant`, `partial`, `useful`, `strong`,
and `needs verification` labels with reason codes. After three graded ratings,
an optional local preference model can prioritize future Relevance sorting.
The explicit evaluation export includes current search text, filters, ranks,
and ratings while omitting API keys, saved profile text, CV text, and chat.
`scripts/evaluate_phase2.py` measures retrieval recall separately from AI
assessment precision. Evaluation exports distinguish the immutable ordinary
baseline from up to 12 locally qualified additions. The 3–5 researcher pilot is
deliberately deferred until the Phase 3 deployment batch and review handoff are
verified.

Ratings appear directly on result cards. Invited testers can open the collapsed
“Help improve Funding Finder” area to
mark cited evidence accurate, incorrect, or unverifiable, check
the field they inspected, and add a short non-confidential note. This progress
autosaves only on that device. “Send review” uses the native file share sheet
where available; otherwise it downloads a privacy-safe JSON file and opens an
addressed email to the project owner. Returned files can be aggregated into
private Markdown, JSON, and CSV reports.

## Data model

The daily workflow processes the official [Grants.gov XML database extract](https://www.grants.gov/xml-extract), then merges enabled, independently validated
public-source adapters. NSF upcoming due dates, NYSERDA, ARPA-E eXCHANGE, and
DOE EERE Exchange are enabled. NASA NSPIRES and UR InfoReady remain disabled
shells until stable public or permissioned routes exist. It publishes open
posted and current forecasted records plus a compact BM25 search index to
`data/opportunities.js`. Past deadlines are rejected for every source, and
stale undated forecasts are excluded. Grants.gov lifecycle placeholders such
as 2076 and 2099 are never published as application deadlines; explicit
"accepted anytime" notices are represented as rolling instead.

An incremental second step enriches only new or changed records through the
official Grants.gov `fetchOpportunity` detail API. It reconciles structured
deadline and award evidence, preserves supplied deadline time/timezone, and
selects a direct announcement only when the attachment evidence is defensible.
When Grants.gov drops spacing from an NSF synopsis, the same step replaces
only that damaged prose with the synopsis from the linked official NSF funding
page and rebuilds the search index. Successful NSF text is cached for 14 days;
an unparseable agency page leaves the Grants.gov text unchanged.
Its compact cache is `data/opportunity_enrichment.json`.

A bounded third step retrieves selected official PDF or HTML notices. It uses
document hashes and HTTP validators to detect changes and avoid unnecessary
downloads, extracts readable text ephemerally, and publishes only short cited
facts and a human-review queue. Raw notices and full extracted text are never
committed. Machine-extracted dates and amounts do not replace structured
Grants.gov fields used by filters or sorting. Its compact cache is
`data/document_evidence.json`.

External-source records use atomic per-source replacement and the committed
`data/source_records.json` source cache. Most degraded sources retain only a
filtered last-known-good snapshot; stricter sources can fail closed and publish
zero when their records cannot be proven current. The safe merge completes,
exits nonzero for monitoring, and the scheduled workflow opens or updates an
owner-facing GitHub issue. NYSERDA publishes the next open application round
and retains later application and concept-paper dates as structured deadlines.
DOE Exchange adapters publish only actual NOFOs, not RFIs, teaming notices, or
notices of intent, and retain later submission rounds as structured deadlines.
The source cache also preserves a first-seen date so undated external records
can participate reliably in feeds and consent-based alerts.

The VPR/Cindy email adapter normalizes NSF solicitation numbers and titles
before merge, and the catalog record always wins when an email describes an
opportunity already present in the main catalog. For allowlisted private
funders, the scheduled refresh follows the supplied sponsor link and fills
missing sponsor, description, eligibility, deadline, and award fields when the
public page permits bounded automated retrieval. A blocked or unparseable page
never removes fields already supplied by the email.

After the final validated merge, `scripts/build_feeds.py` regenerates static
Atom feeds under `feeds/`. They require no account, backend, or personal data.
Feeds, email matching, and the browser independently reapply a runtime
expiration/non-funding gate so an opportunity that ages out between catalog
runs is not shown as active. The daily workflow also maintains a rolling
change feed and rotates through official links, recording status, content
type, redirect target, and last-check time. Confirmed 404/410 routes are marked
in the generated catalog so both card views omit them and fall back to another
official route; timeouts and access restrictions are not treated as broken.
For a small manually managed pilot, `docs/weekly-alerts/` contains a
private-repository email-digest bundle. It now includes deadline-change,
amendment, closing-soon, and closure events from the rolling change feed. The
public site does not collect email addresses; the bundle requires explicit
consent and keeps subscriptions, watermarks, and SMTP secrets outside this
public repository. See `docs/EMAIL_ALERT_SERVICE_SETUP.md` for the recommended
self-service account, personalized RSS, and email-service architecture.

<!-- catalog-stats:start -->
This replaces the former 48-record Chemical and Sustainability Engineering feed. The
September 5, 2026 build contains 1,410 current funding opportunities (1,083 posted and
327 forecasted) from ARPA-H (10), DOE EERE Exchange (1), Grants.gov (1,331), NASA ROSES
(3), NYSERDA (37), U.S. National Science Foundation (1), VPR funding digest (limited
submissions & foundations) (27), with no deadline before the catalog date. It provides a
direct official announcement for 290 records, an official source-page route for another
618, and the official Grants.gov record for the remaining 502. Across all route types,
717 records also contain an official source URL.
<!-- catalog-stats:end -->

Funding values are intentionally not conflated: award floor/ceiling drive
per-award display and filtering, while total program funding is a separate
fact. Missing evidence remains “not listed” until an official source can
support it.

## Project layout

| Path | Purpose |
|---|---|
| `index.html` | Redirects GitHub Pages to the application |
| `match_explorer.html` | Public opportunity search and AI-refinement interface |
| `team_match.html` | Public multi-researcher opportunity-matching interface |
| `funded_awards.html` | Public NSF/NIH/DOE/DoD historical-award search, Institutional Intelligence, and exact current-opportunity deep links |
| `assets/app.js` | Search, cited source evidence, review/export, profile ranking, AI matching, and chat |
| `assets/award-links.js` | Exact NIH/DOE and exact/reviewed-parent NSF opportunity-to-award mappings plus fail-closed DoD award-to-opportunity links |
| `assets/funded-awards-core.js` | Source-native award-query, institution-summary, and pagination contracts |
| `assets/institutional-intelligence-core.js` | Structured institution filters, URL state, and normalized award aggregation |
| `assets/institutional-intelligence.js` | ROR autocomplete, institutional drill-downs, and optional shared-provider question translation |
| `assets/search-retrieval.js` | Local BM25 candidate retrieval, fuzzy matching, concept coverage, and topic reranking |
| `assets/profile-ranking.js` | Weighted profile/CV terms, profile-only concept coverage, eligibility, and career-fit evidence |
| `assets/team-researchers.js` | Device-local external researchers and shared hybrid researcher-to-opportunity matching |
| `assets/opportunity-team.js` | Lazy content-identified faculty directory and deterministic role/team engine |
| `assets/opportunity-team-panel.js` | Funding Finder team proposal, missing-role, remove, replacement, and focus lifecycle |
| `assets/search-query.js` | Conservative abbreviation and scientific word-form expansion |
| `assets/profile.js` | Local profile/feedback storage and CV extraction |
| `assets/nofo.js` | Browser-only NOFO PDF extraction, opportunity-number detection, and catalog matching |
| `assets/review.js` | Local Phase 3 deployment-review storage and privacy-safe handoff |
| `assets/credentials.js` | Explicit device-local provider-key save/load/clear boundary |
| `assets/ai-provider.js` | OpenAI and Anthropic request adapters |
| `assets/app.css` | Responsive application styles |
| `assets/vendor/` | Vendored PDF.js and Mammoth parsers and license notices |
| `data/opportunities.js` | Generated catalog and search index |
| `data/opportunity_team_index.js` | Tiny eager index of reviewed team-ready opportunity scopes; contains no faculty or role graph |
| `data/opportunity_teams.js` | Compact generated faculty directory and ten-scope role/team projection |
| `config/opportunity_team_model.json` | Canonical source-traceable faculty and opportunity-role model |
| `data/opportunity_enrichment.json` | Incremental official-detail cache |
| `data/document_evidence.json` | Incremental document hash/version, cited-fact, and review-queue cache |
| `data/source_records.json` | Per-source records and refresh diagnostics for enabled external sources |
| `data/link_health.json` | Rotating official-link status, redirect, and last-check state |
| `data/search-v2-release.json` | Atomic catalog/vector/model-space/Worker release handshake |
| `data/search-v2-voyage-canaries.json` | Fixed public embedding-space canaries and fingerprint |
| `scripts/build_catalog.py` | Official XML ingestion and catalog builder |
| `scripts/enrich_catalog.py` | Official detail reconciliation and FOA selection |
| `scripts/extract_document_evidence.py` | Official PDF/HTML retrieval, versioning, deterministic fact extraction, and citations |
| `scripts/program_areas.py` | Evidence-backed controlled vocabulary for discoverability in official notices |
| `scripts/sources/discoverability.py` | Audited official-scope registry for opaque umbrella FOAs and BAAs |
| `scripts/sources/` | Validated multi-source adapters, lifecycle, health gates, and merge |
| `scripts/build_feeds.py` | Static all/topic/source-type Atom feed generator |
| `scripts/build_changes.py` | Rolling new/deadline/amendment/closing/closure event feeds |
| `scripts/check_links.py` | Bounded official-link health and redirect monitor |
| `scripts/currentness.py` | Shared runtime expiration and non-funding gate |
| `scripts/import_opportunity_team_model.py` | Deterministic reduction of offline calibration artifacts and shared generation identity |
| `scripts/alert_match.py` | Server-side saved-search matcher shared by the optional digest bundle |
| `feeds/` | Generated public Atom feeds and feed directory |
| `docs/weekly-alerts/` | Private-repository pilot bundle for consent-based weekly email digests |
| `docs/EMAIL_ALERT_SERVICE_SETUP.md` | Self-service accounts, personalized RSS, and email-alert deployment guide |
| `scripts/evaluate_phase2.py` | Phase 2 retrieval/reranking evaluator |
| `scripts/summarize_phase3_reviews.py` | Private Phase 3 deployment-review aggregator |
| `evaluation/README.md` | Pilot export, privacy, and aggregation workflow |
| `evaluation/PHASE3_REVIEW.md` | Deployment-review storage, return, and reporting procedure |
| `docs/POST_RELEASE_HARDENING.md` | v1.2.1 release lifecycle, operating limits, verification, and rollback |
| `docs/OPPORTUNITY_TO_TEAM_ROLLOUT.md` | Opportunity-role evidence, team assembly, replacement, and staged expansion contract |
| `workers/search-voyage-proxy/` | Bounded hosted embedding/reranking proxy and compatibility allowlists |
| `workers/award-api/` | Bounded, source-isolated NSF, NIH, DOE, DoD, and ROR normalization Worker |
| `PROJECT.md` | Product decisions, architecture, and roadmap |
| `tests/` | Pipeline and public-page regression checks |
| `docs/HOSTING.md` | Deployment and privacy boundary |

## Development

Install the small Python dependency set and run the regression suite:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

For implementation pull requests, use this review and test workflow:

- Run the narrowest affected deterministic tests locally first while implementing
  and addressing review feedback.
- Batch review findings where practical instead of pushing one correction at a
  time, and do not manually trigger duplicate full suites for the same commit.
- Request one comprehensive automated review before the final gate where
  practical. After addressing it, request one final review of the exact head.
- Require one complete protected Python, browser-contract, frozen-query, and
  frozen-P9 run on the exact final commit. E2E/Playwright runs are reserved for
  a separately authorized manual validation task under `AGENTS.md`.
- If the final exact-head review finds a consequential defect, fix it, request
  another exact-head review, and rerun that final gate. Otherwise, do not add
  ceremonial reruns.
- Never merge using green checks from an earlier commit. After merge, the same
  complete Tests workflow runs once more on protected `main`.

Build from an existing official extract:

```powershell
python -m scripts.build_catalog --archive GrantsDBExtractYYYYMMDDv2.zip
```

Or discover and download the latest official extract:

```powershell
python -m scripts.build_catalog
```

Then enrich new or changed records:

```powershell
python -m scripts.enrich_catalog --catalog data/opportunities.js --cache data/opportunity_enrichment.json --max-updates 250
```

Then process a bounded set of new, changed, or due official notices:

```powershell
python -m scripts.extract_document_evidence --catalog data/opportunities.js --cache data/document_evidence.json --max-documents 45
```

To summarize review files returned to the project owner:

```powershell
python -m scripts.summarize_phase3_reviews evaluation/inbox --output-dir evaluation/reports
```

The scheduled workflow runs the Grants.gov, enrichment, document-evidence, and
external-source steps daily; validates source-specific and whole-catalog
health; regenerates the public feeds; retests the generated assets; alerts the
owner about degradation; and commits the normalized browser catalog, feeds,
and compact caches. Raw XML archives, raw notices, full extracted notice text,
subscriber data, SMTP credentials, and returned review files are not committed.

See `PROJECT.md` for the completed Phase 1/1.5 scope, deferred Phase 2 pilot,
and Phase 3 implementation,
and `docs/HOSTING.md` for the deployment boundary.

## Use and copyright

Copyright (c) 2026 Marc D. Porosoff. All rights reserved. 

Personal, non-commercial use is permitted. All other use, including modification, redistribution, and commercial or organizational use, requires written permission from the author. 
