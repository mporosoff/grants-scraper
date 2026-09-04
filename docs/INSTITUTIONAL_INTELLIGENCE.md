# Institutional Intelligence architecture and ROR reconnaissance

Checked: 2026-09-04 (America/New_York)

## Product boundary

Institutional Intelligence is a Funded Awards section in `funded_awards.html`. It is not loaded by Funding Finder or Team Match and does not introduce another opportunity or award search system. Legacy Institutional Intelligence URLs on Funding Finder redirect to the corresponding state on Funded Awards. The browser sends transparent structured filters through the existing Funded Awards architecture. NSF, NIH, and DOE use the Worker transport. DoD uses the same committed normalized adapter through USAspending's official browser CORS transport because USAspending rejects Cloudflare Worker egress. The browser then uses the shared snapshot primitives to form one four-source snapshot; local hybrid snapshots are retained in bounded one-hour session storage so page, facet, retry, history, and restoration behavior stays unified. No award embeddings, semantic award corpus, reranking, collaborator recommendation, or funding-fit score is involved.

Summaries cover only the normalized records returned on the current source-native result page. The interface states that additional source results may exist and links every displayed project to its official sponsor record. It does not treat a first page as an exhaustive institutional portfolio.

## ROR evaluation

Authoritative public documentation:

- ROR REST API overview: `https://ror.readme.io/docs/rest-api`
- ROR query parameter: `https://ror.readme.io/docs/api-query`
- ROR schema 2.1: `https://ror.readme.io/docs/schema-v2-1`
- ROR terms and data license: `https://ror.org/about/terms/`
- Production endpoint: `https://api.ror.org/v2/organizations?query=<encoded-name-or-alias>`

ROR documents its version 2 `query` parameter as the endpoint intended for user-facing organization typeaheads. It searches the `names` collection, including `ror_display`, `alias`, `acronym`, and multilingual label values, as well as external identifiers. Active records are returned by default. The registry and its metadata are available under CC0 and require no personal account or API key.

The production reconnaissance queried MIT, Caltech, UVA, RIT, UCLA, and University of Rochester. It confirmed these canonical ROR identities:

| Search text | Canonical organization | ROR ID | Match metadata |
|---|---|---|---|
| MIT | Massachusetts Institute of Technology | `https://ror.org/042nb2s44` | acronym |
| Caltech | California Institute of Technology | `https://ror.org/05dxps055` | alias |
| UVA | University of Virginia | `https://ror.org/0153tk833` | acronym |
| RIT | Rochester Institute of Technology | `https://ror.org/00v4yb702` | acronym |
| UCLA | University of California, Los Angeles | `https://ror.org/046rm7j60` | acronym |
| University of Rochester | University of Rochester | `https://ror.org/022kthw22` | canonical name |

### Important result-order finding

ROR explicitly recommends against automatically choosing the first query result. The bounded checks demonstrated why: `MIT` first returned University of Southern Mindanao, `UVA` first returned University Vascular Associates, `RIT` first returned the Dubai campus, and `UCLA` first returned Universidad Centroccidental Lisandro Alvarado. The intended U.S. award institutions were present but not always first.

The Award Worker therefore normalizes all returned candidates and sorts them deterministically. Exact canonical matches outrank exact aliases, which outrank exact acronyms. Because this product searches four U.S. federal funders, a U.S. location and the ROR `education` type are explicit tie-breakers for ambiguous short acronyms. Canonical name and ROR ID provide stable final tie-breaks. The browser shows the ranked candidates and retains user selection; it never treats raw upstream order as identity proof.

The typeahead waits for two characters, debounces browser requests, aborts obsolete requests, returns at most eight normalized candidates, and uses the existing Worker cache for one hour. If ROR is unavailable, the user can still submit a complete sponsor-listed institution name and the award sources continue independently.

## Identity and award-query behavior

ROR augments discovery; it does not replace the award identity layer. ROR does not publish NIH IPF identifiers or the UEI mapping needed by the source adapters. Existing controlled identities therefore remain authoritative for sponsor queries. For example, selecting the Rochester ROR ID resolves to the existing `university-of-rochester` identity and retains:

- NSF search name and UEI;
- NIH exact search name, UEI, and IPF;
- DOE PAMS search name and UEI.
- DoD USAspending search name and UEI.

For any other selected ROR organization, the canonical ROR display name is used as the source-native institution search text. Whether it is represented in the public award results is decided only by normalized NSF, NIH, DOE, and DoD responses, not by ROR membership or an LLM. A zero-result search is shown as such.

Program filters preserve source semantics:

- NSF uses the existing exact program-element or source-native program-name request builder.
- NIH uses exact activity codes.
- DOE program areas use the existing PAMS Program Area field.
- DOE Basic Energy Sciences maps only to the controlled PAMS organization identity `SC-32 - BES - Office of Basic Energy Sciences` and its source-published `SC-32.*` child organization codes. The adapter locates those published codes in the fresh public form before submitting them; it does not rely on fixed list positions.
- DoD uses exact numeric Assistance Listing codes such as `12.800`. USAspending does not expose PI or program-officer fields for these records, so those filters are reported as unsupported and investigator metrics are labeled as source-listed coverage.

## Privacy and optional natural language

All structured filters, alias resolution, aggregation, URLs, history, and drill-downs work without an AI key. Institution and award filters are public research queries sent only to the Award Worker and official public registries/sponsor sources. USAspending requests omit credentials and referrers; successful DoD source and detail responses use a one-hour browser cache, and failed responses are not cached.

The optional question translator uses `FUNDING_AI.providerJson` and `FUNDING_CREDENTIALS`, including the same provider, model, and `funding-finder.credentials.v1` browser-local key store as Funding Finder. Setup inside Institutional Intelligence writes to that same store and synchronizes the main provider controls. No key is sent to the Award Worker.

The model receives only the question, selected public institution, and visible structured award filters. It returns a bounded filter plan; it is not allowed to answer from memory, name awards, infer contacts, recommend collaborators, or score funding fit. Profile text, CV text, ORCID text, saved pursuits, notes, and uploaded documents are excluded. Returned award records and official sponsor pages remain authoritative.
