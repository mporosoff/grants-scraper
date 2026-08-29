# Funding Finder Implementation Plan: Hajim Reverse Match and Program-Officer Portfolios

**Status:** Reconciled implementation scope — updated against the post-Phase-4 production architecture on 2026-08-29  
**Repository:** `mporosoff/grants-scraper`  
**Primary input supplied with this plan:** `Hajim_Research_Active_Faculty_Profile_2026-08-28.xlsx`  
**Input SHA-256:** `f625ec89beabcfe7a7c178b83dcd9ca6737be455fc70c3b00f06882f2d6114fc`  
**Product baseline:** Start from the current protected `main` (reported at reconciliation as `f8de27043d04c4e91a867f2b71bd26e1ca48a3e8`). Before implementation, refresh protected `main` and treat that exact checkout, `AGENTS.md`, `PROJECT.md`, generated-data contracts, and existing tests as authoritative.  
**Implementation boundary:** Implement only the two features defined below. Do not begin adjacent proposal-management, internal-funding, faculty-database, or dashboard work.

**Reconciliation note:** The workbook was re-audited and its stated counts, headers, dates, and SHA-256 remain correct. The original Program-Officer design predated the merged server-authoritative award snapshot system and is replaced below; do not reintroduce browser-side source-page accumulation or “load the complete portfolio” logic.

---

## 1. Codex execution directive

Read this plan, the supplied workbook, `AGENTS.md`, `PROJECT.md`, `README.md`, the existing faculty-matching code, the Funded Awards/Institutional Intelligence code, and the relevant tests before editing.

Use the existing architecture rather than creating parallel systems:

- GitHub Pages remains the public product surface.
- Existing scheduled generation remains the build path for catalog-derived assets.
- Existing award adapters and the award API remain authoritative for NSF, NIH, and DOE award records.
- Existing browser-local provider credentials remain the only credentials used for optional AI questions.
- Existing Team Match and faculty-match assets must be refactored or extended, not replaced by a second independent researcher system.
- Ordinary reverse matching and program-officer portfolio browsing must require no AI key.
- No new account system, user database, vector database, hosted faculty service, or persistent program-officer database is authorized.

Implement the work as **two separate protected PRs** so review and rollback remain bounded:

1. **PR 1 — Hajim faculty data foundation and opportunity-to-faculty reverse match**
2. **PR 2 — Program-officer portfolio navigation and complete-portfolio-grounded Q&A**

Merge PR 1 before branching PR 2 from the updated protected `main`. Follow the exact-head review and convergence rules in `AGENTS.md`. Do not edit while a review is pending, do not reuse checks from an earlier SHA, and do not initiate unrelated paid-provider or vector experiments.

---

## 2. Product decisions

Only the following two additions are approved.

### 2.1 Hajim Reverse Match

From a Funding Finder opportunity, a user can select **Find relevant Hajim faculty** and see a ranked, evidence-backed list of current research-active faculty whose official research-interest text overlaps the opportunity.

This answers:

> Who at Hajim may have relevant expertise for this opportunity?

It does **not** choose a PI, construct an optimal team, predict submission success, or claim that a person should lead the proposal.

### 2.2 Program-Officer Portfolios

From a normalized funded-award record, a user can select a source-listed program officer/program official/program manager and immediately see the awards associated with that exact published name at that exact source. No AI key is required.

Program-officer navigation defaults to the most recent five source award years because that is the most useful and predictable initial scope. A clearly labeled **Search all available years** option remains available. In either mode, the existing Award Worker snapshot—not the browser—must establish exact versus partial coverage and authoritative totals.

When the user asks an optional AI question, the application must search the full server snapshot for evidence relevant to the question and send only a bounded evidence subset to the selected provider. It must not hydrate or render every award merely to answer the question.

This answers:

> What awards does this source associate with this officer?  
> Has a project resembling X appeared in that returned portfolio, and when?

It does **not** create a permanent identity profile for the person, merge name variants speculatively, infer preferences, or predict what the officer will fund.

---

## 3. Explicit non-goals

Do not implement any of the following:

- automated “pursue/pass” briefs;
- proposal uploads, proposal review, or compliance review;
- pursuit workspaces, task plans, internal routing, or budget tooling;
- internal-funding or limited-submission expansion;
- canned program-officer dashboards, charts, or portfolio “personality” summaries;
- cross-agency program-officer identity resolution;
- fuzzy merging of `Jane Doe`, `Jane A. Doe`, and similarly named people;
- an all-University or externally hosted researcher database;
- OpenAlex as the authority for who currently belongs to Hajim;
- automated team optimization or “best PI” selection;
- a new standalone free-text expertise-search product in this release;
- a new semantic/vector service for faculty matching;
- automatic AI calls for either feature;
- changes to unrelated Funding Finder retrieval, alerting, NOFO analysis, or search-vector evaluation.

Pure internal functions may be made reusable, but no additional user-facing feature should be exposed beyond the two approved workflows.

---

# PR 1 — Hajim faculty data foundation and reverse match

## 4. Workbook source contract

The supplied workbook is a reviewed snapshot of the current Hajim research-active faculty population. It removes the need to infer the roster from OpenAlex or arbitrary affiliation strings.

### 4.1 Workbook facts that must be preserved

The workbook contains five sheets:

- `Summary`
- `Faculty Profiles`
- `Method & Sources`
- `Exclusion Audit`
- `Analysis Helpers`

Only **`Faculty Profiles`** is the row-level import source. The other sheets are verification, methodology, provenance, and analysis aids.

The `Faculty Profiles` sheet has these exact columns:

1. `Faculty Name`
2. `Primary / Home Unit`
3. `Faculty Relationship`
4. `Academic Rank / Appointments`
5. `Hajim Faculty Roster(s)`
6. `Research Interests (website text, lightly normalized)`
7. `Derived Research Theme(s)`
8. `Email`
9. `Lab / Faculty Website`
10. `Source Faculty Page URL(s)`
11. `Checked Date`

The reviewed snapshot contains:

- **156** unique included faculty;
- **115** `Hajim primary/core faculty`;
- **11** `Hajim research faculty`;
- **19** `Joint Hajim appointment / program faculty`;
- **11** `Materials Science program faculty (non-Hajim home)`;
- **126** Hajim primary/core plus research faculty;
- **30** joint/program-affiliated faculty;
- zero missing emails;
- zero missing source-faculty-page URLs;
- a checked date of `2026-08-28` for every included record;
- **145** records with source-listed research-interest text;
- **11** records whose interest field is exactly `Not listed on source faculty page`.

The workbook methodology must remain visible in product documentation:

- the roster covers the seven official Hajim faculty directories;
- included records are active professor-level research appointments, including designated research professor titles;
- emeritus, instructional-only, professor-of-practice, adjunct, visiting-only, postdoctoral, staff/scientist-only, and separately labeled affiliate-only entries are excluded unless the person also appears on a qualifying primary roster;
- deduplication is primarily by email;
- Materials Science faculty with non-Hajim home units remain included and are explicitly labeled;
- derived themes are convenience tags, not official University classifications;
- missing interests are not filled from outside sources.

### 4.2 Source-control decision

Treat the `.xlsx` file as a **handoff/import artifact**, not the runtime or nightly-build input.

Create a deterministic importer that converts the supplied workbook into a reviewable canonical JSON file:

- input: the supplied `.xlsx`;
- committed source of truth: `config/hajim_faculty.json`;
- generated lightweight browser directory: `data/hajim_faculty_directory.js`;
- generated match asset: the existing `data/faculty_matches.js` path, upgraded to a compact versioned schema.

Do **not** commit the binary workbook unless the repository owner explicitly directs otherwise. Record its filename, SHA-256, checked date, and workbook record counts inside the canonical JSON so the imported snapshot remains auditable.

Neither the workbook nor the full canonical JSON may be loaded by the public browser application. Team Match should initially receive only the compact directory fields needed for local discovery and display. Match edges and evidence must be generated separately and lazy-loaded when matching is actually requested.

Future roster updates should use the same importer with a newly reviewed workbook and produce an ordinary JSON diff.

---

## 5. Canonical Hajim faculty schema

Add a deterministic import module, preferably:

- `scripts/import_hajim_faculty.py`

The importer should emit `config/hajim_faculty.json` with a schema resembling:

```json
{
  "schema_version": 1,
  "source": {
    "kind": "reviewed_hajim_faculty_xlsx",
    "filename": "Hajim_Research_Active_Faculty_Profile_2026-08-28.xlsx",
    "sha256": "f625ec89beabcfe7a7c178b83dcd9ca6737be455fc70c3b00f06882f2d6114fc",
    "checked_date": "2026-08-28",
    "record_count": 156,
    "rankable_record_count": 145,
    "unlisted_interest_count": 11
  },
  "counts": {
    "hajim_primary_core": 115,
    "hajim_research": 11,
    "joint_hajim_or_program": 19,
    "materials_science_non_hajim_home": 11
  },
  "profiles": [
    {
      "faculty_id": "niaz-abdolrahim",
      "name": "Niaz Abdolrahim",
      "home_unit": "Mechanical Engineering",
      "relationship": "hajim_primary_core",
      "relationship_label": "Hajim primary/core faculty",
      "appointment_text": "Associate Professor of Mechanical Engineering; Staff Scientist, Laboratory for Laser Energetics",
      "appointments": [
        "Associate Professor of Mechanical Engineering",
        "Staff Scientist, Laboratory for Laser Energetics"
      ],
      "rosters": [
        "Mechanical Engineering",
        "Materials Science"
      ],
      "research_interests_text": "Multiscale modeling of materials; nanoporous materials; nanowires; thin films; atomistic simulations",
      "research_phrases": [
        "Multiscale modeling of materials",
        "nanoporous materials",
        "nanowires",
        "thin films",
        "atomistic simulations"
      ],
      "derived_themes": [
        "Materials / Polymers / Nanoscience"
      ],
      "email": "niaz@rochester.edu",
      "website_url": null,
      "source_urls": [
        "https://www.hajim.rochester.edu/me/people/faculty/index.html",
        "https://www.hajim.rochester.edu/matsci/people/faculty/index.html"
      ],
      "checked_date": "2026-08-28",
      "rankable": true
    }
  ]
}
```

The exact field names may be adjusted to match established repository naming conventions, but the semantic content and provenance must remain intact.

### 5.1 Import normalization rules

The importer must:

- require the exact `Faculty Profiles` sheet and exact header names;
- normalize Unicode to NFC;
- collapse incidental internal whitespace without rewriting scientific content;
- preserve display capitalization and punctuation;
- split semicolon-delimited appointments, rosters, research phrases, and themes;
- split source URLs on the workbook’s ` | ` delimiter;
- normalize emails to lowercase for identity checks while retaining the canonical display value;
- use normalized email as the primary deduplication identity;
- generate a deterministic human-readable `faculty_id` from the name, adding a deterministic collision suffix only when necessary;
- map the four exact relationship labels to stable enum values;
- convert empty website cells to `null`;
- mark the exact missing-interest sentinel as `rankable: false`;
- reject unrecognized relationship labels rather than silently mapping them;
- reject non-HTTPS source URLs;
- sort arrays only where ordering is not semantically meaningful;
- emit stable key and row ordering so a repeated build is byte-for-byte identical.

### 5.2 Required importer validation

The actual supplied workbook import must fail unless all of these hold:

- 156 profiles are produced;
- emails are unique case-insensitively;
- all required names, home units, relationship labels, emails, source URLs, and checked dates are present;
- the four relationship counts are exactly 115, 11, 19, and 11;
- 145 profiles are rankable and 11 are explicitly unrankable because source interests are absent;
- every checked date is `2026-08-28`;
- the source workbook hash is captured correctly;
- the canonical JSON passes its schema validator;
- running the importer twice produces identical bytes.

Do not infer research interests for the 11 unrankable profiles from OpenAlex, ORCID, publication titles, department names, appointment text, or lab-site text.

---

## 6. Refactor the existing faculty-matching pipeline

The repository already contains a ChemE-only matching pipeline in `scripts/faculty_match.py`, a generated `data/faculty_matches.js`, and a Team Match consumer. Do not create a second matcher.

### 6.1 Required refactor

Refactor the active match path to consume `config/hajim_faculty.json` instead of:

- the hard-coded 14-person `FACULTY` list;
- hard-coded ChemE-only `FACULTY_KEYTERMS`;
- hard-coded ChemE-only summaries and domains;
- OpenAlex resolution as the membership authority;
- `faculty_profiles.json` as the active roster.

Audit every reference to `faculty_profiles.json`, the `profiles` command, and the old hard-coded maps before removing or deprecating them. The final scheduled build must use the canonical Hajim JSON.

OpenAlex functionality may remain only as clearly optional future enrichment if it is still used elsewhere. It must not gate inclusion, establish current affiliation, or silently overwrite official workbook text.

### 6.2 Generated asset schema

Generate two purpose-built browser projections atomically from the same canonical faculty JSON and current catalog. They must share the same faculty-source SHA, catalog fingerprint, schema family, and generation identity so they cannot drift.

1. `data/hajim_faculty_directory.js` is a small local discovery asset for Team Match. It contains only stable faculty ID, name, home unit, relationship, roster labels, rank/appointment display text, rankable state, and a normalized local-search document derived from the official research-interest text. Do not include match lists or the workbook itself.
2. `data/faculty_matches.js` is the compact evidence-qualified match graph used by Team Match and Funding Finder. Store each faculty/opportunity edge once and expose lightweight `by_faculty` and `by_opportunity` indexes containing edge IDs or array offsets. Do not serialize the same edge twice in full.

A suitable match shape is:

```javascript
globalThis.FACULTY_MATCHES = {
  schema_version: 2,
  generation_id: "...",
  catalog: { record_count: 1430, generated_at: "...", fingerprint: "..." },
  faculty_source: {
    checked_date: "2026-08-28",
    sha256: "...",
    record_count: 156,
    rankable_record_count: 145
  },
  edges: [
    {
      faculty_id: "niaz-abdolrahim",
      opportunity_id: "OPPORTUNITY_ID",
      score: 12.4,
      tier: "likely_relevant",
      matched_profile_phrases: ["nanoporous materials"],
      opportunity_evidence: [{ field: "title", excerpt: "..." }],
      corroborating_themes: ["Materials / Polymers / Nanoscience"]
    }
  ],
  by_opportunity: { "OPPORTUNITY_ID": [0] },
  by_faculty: { "niaz-abdolrahim": [0] }
};
```

Avoid duplicating full faculty profiles or opportunity records inside edges. Use stable IDs and compact evidence; the browser already has the catalog record and the directory has display metadata.

Keep the graph bounded:

- top 12 rankable faculty per opportunity;
- top 25 current opportunities per faculty for Team Match compatibility, unless measured current behavior requires a smaller existing bound;
- no edge whose evidence fails the admission gate;
- no edge for an unrankable profile.

Loading rules:

- Funding Finder must lazy-load the match graph only when reverse match is requested.
- Team Match may load the compact directory at startup, but should lazy-load the match graph on first selected/restored Hajim faculty member unless the measured graph is already within the current initial-page budget.
- A missing, stale, or incompatible match graph must not prevent ordinary Funding Finder search, faculty directory discovery, or manual researcher entry from working.
- The public application must never fetch the `.xlsx` or `config/hajim_faculty.json`.

Before merge, record raw and gzip bytes for the current 14-person assets and both proposed projections. Add explicit generated-asset budgets to validation. Any new initial Team Match payload above 250 KiB gzip, or any unexplained material growth, requires redesign or explicit owner approval; do not silently accept a multi-megabyte synchronous asset.

---

## 7. Reverse-match retrieval contract

Scaling the existing phrase matcher from 14 curated ChemE profiles to 156 multidisciplinary profiles without changing its quality controls is not acceptable. The current implementation must be generalized and validated.

### 7.1 Authoritative evidence

Faculty evidence, in descending authority:

1. source-listed research-interest phrases;
2. the complete source-listed research-interest text;
3. derived themes as corroboration only.

The following may be displayed as context but must not establish topical fit:

- home unit;
- faculty relationship;
- academic rank;
- roster membership;
- email;
- website URL.

### 7.2 Opportunity evidence

Use current published catalog fields already authorized for search. In descending weight:

1. opportunity title;
2. official synopsis/description;
3. already-published evidence-backed subprogram or subject text where available in the current catalog architecture;
4. disciplines and topic areas as corroboration only.

Do not retrieve raw notices or make new model calls during reverse matching.

### 7.3 Admission rules

A faculty member may enter an opportunity’s reverse-match result set only when official profile text provides substantive evidence.

Required invariants:

- a derived-theme overlap alone can never admit a faculty member;
- one generic token such as `materials`, `health`, `energy`, `data`, `systems`, `research`, or `modeling` can never admit a faculty member;
- a short multiword research phrase should normally require all distinctive concepts;
- a longer phrase may tolerate modest word-form variation but must retain multi-concept coverage;
- exact scientific acronyms and compound terms should remain distinct where the existing search utilities already do so;
- matching must use corpus rarity/IDF or an equivalent mechanism so terms common across many of the 156 profiles carry less weight;
- profile evidence must be local to one or more identifiable official research phrases;
- broad topic tags can strengthen or order an admitted result but cannot broaden membership;
- missing-interest profiles remain excluded rather than being guessed from department or title.

### 7.4 Ranking

Use a deterministic fielded lexical score. A recommended composition is:

- high phrase-match bonus for official research phrases;
- high title-field evidence bonus;
- BM25-like or comparable rarity-weighted overlap between opportunity text and the full research-interest text;
- bounded bonus for multiple independent matched profile phrases;
- modest derived-theme corroboration;
- no rank, appointment, relationship, or department prestige boost.

Do not expose raw scores as probabilities. The UI may use restrained labels such as:

- `Likely relevant`
- `Possible relevance`

The result copy must avoid `best PI`, `recommended PI`, `should lead`, or any implication of eligibility or willingness to participate.

### 7.5 Explanations

Every displayed reverse match must include a deterministic explanation grounded in both sides:

- one or more exact/near-exact source-listed research phrases;
- the opportunity field or short excerpt that produced the overlap;
- any derived theme only as explicitly labeled corroboration.

Example:

> **Matched faculty interest:** “carbon dioxide capture and conversion”  
> **Opportunity evidence:** Title and synopsis discuss catalytic CO₂ conversion.

Do not generate explanations with AI.

---

## 8. Reverse-match user experience

### 8.1 Funding Finder card action

Add a secondary result-card action:

> **Find relevant Hajim faculty**

The action should be available on ordinary opportunity cards and should:

1. lazy-load the faculty-match asset;
2. select the current opportunity ID;
3. open an inline panel, drawer, or accessible details region associated with the card;
4. render the top evidence-qualified faculty;
5. leave all existing save, calendar, source, award-history, chat, and review actions unchanged.

Do not navigate to a new standalone application in this release.

Keep at most one reverse-match panel open at a time. Opening another card’s panel should close the prior panel and restore a manageable page length; it must not remove or reorder ordinary search results.

### 8.2 Result presentation

For each faculty result, show:

- faculty name;
- primary/home unit;
- relationship label;
- match tier;
- matched official research-interest phrases;
- short opportunity evidence;
- derived themes, clearly labeled as derived;
- email action;
- lab/faculty website when listed, otherwise an official source-faculty-page link;
- source checked date.

Default scope:

> **All included Hajim roster faculty (156)**

Provide one compact scope control:

> **Hajim primary/research only (126)**

The broader default is intentional: reverse match is a discovery workflow, and the workbook deliberately retains joint and interdisciplinary Materials Science faculty. Their relationship and home unit must remain visible so the user can judge institutional context.

The panel should also state:

> Eleven current roster profiles do not list research interests on their source faculty page and therefore are not automatically ranked.

### 8.3 Failure behavior

If the faculty asset cannot be loaded or its catalog/source fingerprint is incompatible:

- do not hide or break the opportunity card;
- show a plain failure message inside the reverse-match panel;
- offer one retry;
- do not fall back to an AI guess;
- preserve all normal Funding Finder functions.

### 8.4 Accessibility and mobile

The reverse-match control and panel must support:

- keyboard activation;
- correct `aria-expanded`/`aria-controls` state;
- focus movement to the opened heading and restoration to the trigger on close;
- readable mobile stacking;
- no nested inaccessible scroll trap;
- Windows high-contrast behavior consistent with the current product;
- reduced-motion behavior.

---

## 9. Team Match compatibility

Team Match already consumes `globalThis.FACULTY_MATCHES` and supports selected researchers, custom researchers, ORCID-derived context, and local team-fit behavior. Its current faculty chooser is a native select designed around 14 ChemE researchers; it is **not** an adequate searchable control for 156 multidisciplinary profiles. This is the one targeted Team Match interaction change authorized by this plan.

Replace that picker with two visually and semantically separate paths:

1. **Search Hajim faculty at the University of Rochester** — an accessible local combobox/typeahead over `data/hajim_faculty_directory.js`, with placeholder text such as **Search by name, department, roster, or research interest**.
2. **Add a researcher manually** — a separate, persistent button with helper text such as **For collaborators outside Hajim or anyone not listed**. It opens the existing name/keywords/ORCID form and preserves the existing browser-local behavior.

The directory search must:

- keep the full 156-person directory out of a permanently expanded DOM list;
- begin suggestions after two meaningful characters, while still allowing an explicit “show suggestions” action for keyboard/touch users;
- show at most 10–12 results at once;
- rank exact/prefix name matches first, followed by home unit/roster matches and then official-interest phrase matches;
- show name, home unit, and a compact relationship or roster label in each result;
- remain entirely local—no provider, Worker, analytics, or query logging call;
- support arrow keys, Enter, Escape, focus return, `aria-expanded`, `aria-controls`, `aria-activedescendant`, and a live result count;
- work at 390 px without horizontal overflow or an obscured result list;
- preserve selected-researcher chips and the existing maximum team size of four.

When four researchers are selected, disable both add paths and explain the team-size limit. Removing a researcher must re-enable them. Restored URLs and saved browser-local custom researchers must retain the same behavior.

Additional compatibility requirements:

- populate Team Match from the same 156-profile canonical roster;
- preserve custom/external researcher entry and ORCID behavior;
- preserve the current every-researcher evidence gate;
- retain relationship/home-unit labeling where useful;
- ensure the expanded roster does not change selected-team semantics;
- keep enhanced Team Match ordering unable to add an opportunity that failed local full-team fit.

The reverse-match release must not create a second faculty source of truth. The lightweight directory and match graph are different projections generated atomically from the same canonical JSON and catalog fingerprint.

---

## 10. Reverse-match tests and quality gates

### 10.1 Python tests

Add focused tests, preferably:

- `tests/test_import_hajim_faculty.py`
- extend or replace the relevant `faculty_match` tests with multidisciplinary fixtures.

Cover:

- exact workbook header contract;
- relationship mapping;
- semicolon and URL splitting;
- Unicode normalization;
- email deduplication;
- missing-interest handling;
- invalid/non-HTTPS source URL rejection;
- deterministic ID collision handling;
- exact actual-snapshot counts;
- deterministic JSON output;
- generated schema version;
- theme-only non-admission;
- generic-token non-admission;
- multi-concept phrase admission;
- unrankable profile exclusion;
- top-N bounds;
- opportunity/faculty reverse-index consistency;
- one-copy edge normalization and deterministic edge-index ordering;
- identical generation IDs/source fingerprints across the directory and match graph;
- generated raw/gzip size budgets.

Use a generated temporary workbook or a compact committed fixture for importer unit tests. The actual handoff workbook does not need to be committed merely to make CI pass.

### 10.2 Browser contract tests

Add:

- `tests/browser/hajim-reverse-match-contract.test.mjs`

Cover:

- schema validation and fingerprint handling;
- opportunity-to-faculty lookup;
- 156/145/11 source metadata;
- all-faculty versus primary/research scope filtering;
- deterministic explanation rendering;
- source URL and checked-date rendering;
- no model/provider/network call during ordinary reverse match;
- lazy-load failure isolation;
- no theme-only admission;
- Team Match compatibility with the upgraded schema;
- the lightweight directory can load without loading the match graph;
- the workbook and canonical JSON are never requested by browser code;
- local directory search ordering and the 10–12 result display bound;
- manual/external researcher entry remains a separate action;
- no network or analytics event contains the faculty-search string.

### 10.3 E2E tests

Extend:

- `tests/e2e/funding-finder.spec.mjs`
- `tests/e2e/team-match.spec.mjs`
- `tests/e2e/accessibility.spec.mjs`

Required browser flow:

1. search for or focus a fixture opportunity;
2. select **Find relevant Hajim faculty**;
3. verify the asset is loaded only at that point;
4. verify a relevant non-ChemE faculty result can appear;
5. verify its official profile evidence, home unit, relationship, and source date;
6. toggle to primary/research-only scope;
7. close and restore focus;
8. confirm ordinary Funding Finder remains usable after an induced faculty-asset failure.

Also cover Team Match with the actual 156-record directory fixture:

1. verify the page does not render a 156-option control or button wall;
2. search by name, home unit, roster, and official-interest phrase using keyboard and touch;
3. select a Hajim researcher and confirm the match graph loads only when needed;
4. add an outside researcher through the separate manual/ORCID path;
5. reach and leave the four-person maximum cleanly;
6. restore selected and saved researchers without changing team-fit semantics;
7. verify mobile containment and automated accessibility.

### 10.4 Relevance-quality fixture

Create a small human-reviewed, source-controlled quality fixture spanning at least:

- optics/photonics/lasers;
- imaging/sensing;
- biomedical/bioengineering;
- materials/polymers/nanoscience;
- AI/ML/data science;
- fusion/plasma/high-energy-density physics;
- catalysis/electrochemistry/energy;
- computing systems/security/networks.

For each case, record:

- expected relevant profiles or expected profile themes;
- explicitly irrelevant near-neighbors;
- decisive official profile phrases;
- decisive opportunity text;
- whether the case is an admission or ordering test.

The gate is not “the script ran.” The gate is that top results are defensible across disciplines and known generic-overlap false positives remain excluded.

Do not tune thresholds from live anecdotes without preserving the resulting case in the fixture.

---

## 11. Reverse-match documentation and workflow updates

Update:

- `README.md`
- `PROJECT.md`
- the public Help content
- `.github/workflows/refresh-opportunities.yml`
- any generated-data validation list in `tools/run_refresh_validation.py`

The scheduled refresh should run approximately:

```bash
python -m scripts.faculty_match match \
  --catalog data/opportunities.js \
  --faculty-config config/hajim_faculty.json \
  --directory-out data/hajim_faculty_directory.js \
  --out data/faculty_matches.js
```

The exact CLI may differ, but the active build must no longer depend on `faculty_profiles.json`.

Add relevant paths to the workflow’s push trigger so changes to the canonical faculty config, importer, matcher, directory projection, or tests regenerate and validate both assets atomically. Validate their shared generation identity, current catalog fingerprint, determinism, and byte budgets before publication.

Do not regenerate the faculty roster from public webpages nightly. The canonical roster is a deliberately reviewed snapshot. The catalog-to-faculty edges may be rebuilt nightly against current opportunities.

---

# PR 2 — Snapshot-native program-officer portfolios and bounded Q&A

## 12. Reconciled award foundation

The merged Award Worker architecture already supersedes the original browser-pagination assumptions in this plan:

- `program_officer` is an accepted Institutional Intelligence criterion and `ii_program_officer` round-trips through managed URLs;
- NSF, NIH, and DOE normalize source-listed program contacts and support source-specific name criteria;
- the Worker creates an immutable one-hour result snapshot, scans requested sources in parallel within source-specific safety bounds, deduplicates normalized awards, and owns exact-versus-partial truth;
- exact totals are exposed only when every requested source is exhausted without an error or safety bound;
- direct numbered pages of 10, 25, or 50 awards come from the server snapshot;
- full-snapshot metrics, years, investigator identities, programs, facets, and deterministic answers are already server-authoritative;
- a failed-source retry creates a successor snapshot while retaining successful source results;
- browser card hydration is independent and capped at 25 records per agency per action; that cap is **not** a discovery or result-total cap;
- expired or cache-colo-missing snapshots are refreshable from the submitted structured criteria;
- optional provider answers already use bounded evidence and validate evidence IDs.

Production closeout has already demonstrated a complete 629-award snapshot and public response sizes below 500 KiB, with the Award Worker on the Paid/Standard model and a version-controlled 250 ms CPU ceiling. Preserve that architecture and its production telemetry checks.

The remaining gaps for this feature are:

- source-name searches are not yet required to post-validate that each returned award contains the clicked contact name;
- program contacts are not consistently actionable as a dedicated recent-awards search;
- general Funded Awards correctly defaults to all available years, but a contact deep link needs a more useful recent-five-year default and an explicit all-years opt-in;
- topical Q&A currently selects evidence from browser-resident/hydrated cards rather than scoring the full server snapshot;
- abstract availability varies by source and must not be confused with result coverage.

Do not add `ensureCompletePortfolio()`, client-side page exhaustion, or a second portfolio cache. “All results” means all normalized records represented by the server snapshot within the requested years and source safety bounds—not every award rendered in the DOM at once.

---

## 13. Program-officer identity and result-validation contract

A portfolio identity is:

```text
(source, exact source-published program-contact name, deterministic contact key)
```

The display name remains byte-faithful apart from existing safe display normalization. The deterministic key may normalize Unicode, case, whitespace, punctuation, and comma-order solely for same-source comparison. It must retain every substantive name token, middle initial, and suffix: `Jane Doe`, `Jane A. Doe`, and `Jane B. Doe` must not collapse into one key.

Required behavior:

- preserve exact source scope and the clicked source-published display name;
- pass the source-native name criterion upstream;
- after normalization, admit an award to the PO snapshot only when its normalized `program_contacts` contains the same deterministic contact key;
- exclude broad/partial upstream matches before snapshot membership, totals, aggregates, pages, or Q&A evidence are computed;
- display source-published email when available, without using email to merge identities;
- keep variants and cross-source names separate unless an official source identifier later establishes equivalence;
- state that source records without the exact listed form may be absent;
- never describe the result as the person’s complete career portfolio.

Every adapter must have deterministic fixtures for initials, missing/extra middle initials, apostrophes, hyphens, accents, suffixes, comma-form names, organization/help-desk contacts, and partial-name false positives.

---

## 14. Zero-AI portfolio navigation

### 14.1 Funded-award cards and default time scope

Make each valid person-like `program_contacts` name actionable. Suggested presentation:

> **Jane A. Doe** · Program Officer · jane.doe@nsf.gov  
> **Search this contact’s recent NSF awards**

The action must:

1. set Agency to the award’s normalized source;
2. set Program officer to the exact published name and deterministic key;
3. clear institution, topic, PI, and program filters;
4. set the default to the most recent five **source award years**, inclusive;
5. create a new server snapshot through the existing structured award flow;
6. update the managed shareable URL, including the year preset and explicit bounds;
7. move focus to the results heading;
8. require no AI key.

Derive the default from one immutable UTC `as_of` instant: `year_start = UTC year - 4`, `year_end = UTC year`. As of 2026, the default is 2022–2026. Preserve each adapter’s existing source-native award/fiscal-year semantics and label the UI **source award years** to avoid implying that all agencies use calendar years identically.

Show a visible preset control:

- **Recent 5 years (recommended)** — default only when entering dedicated PO mode;
- **Search all available years** — clears both year bounds and creates a successor snapshot;
- existing custom From/Through inputs remain available and create a successor snapshot.

Do not change the blank/all-years default for ordinary institution, investigator, topic, or program searches.

Result copy must be precise:

> NSF awards from source award years 2022–2026, returned and post-validated for the exact source-listed name “Jane A. Doe.”

and:

> Name variants and records without this exact source-listed contact form may not be included.

### 14.2 Current-opportunity integration

Audit `contacts[].role` values in the current opportunity catalog before adding **Search funded awards for this contact** to Funding Finder cards. Expose it only for NSF, NIH, or DOE Office of Science; a person-like name; an explicitly allowlisted program/scientific officer role; and a source that supports the criterion.

Do not label this action “View portfolio,” because a solicitation contact is not necessarily the historical award program officer. If role quality is insufficient, omit this optional integration; funded-award-card links remain the required deliverable.

### 14.3 Shared-link helper

Extend the existing award-link/state helpers rather than concatenating query strings in multiple UI files. A validated helper should accept `{ source, name, yearPreset, yearStart, yearEnd }`, reject blank or organization-like names, emit only managed Institutional Intelligence parameters, clear unrelated filters, and safely round-trip Unicode names, punctuation, the preset, explicit year bounds, snapshot ID, page, and page size.

Browser back/forward must restore the same PO mode. If the snapshot has expired, the existing refresh path must rebuild from those criteria rather than silently falling back to a different scope.

---

## 15. Snapshot coverage and presentation model

Extend the existing server snapshot contract rather than adding browser-owned coverage state. A PO snapshot should expose compact metadata resembling:

```javascript
{
  mode: "program_officer_portfolio",
  snapshot_id: "...",
  source: "NSF",
  exact_name: "Jane A. Doe",
  contact_identity_key: "jane a doe",
  year_preset: "recent_5_years",
  year_start: 2022,
  year_end: 2026,
  completeness: "complete",
  exact_total: 137,
  at_least: 137,
  safety_bound_reached: false,
  source_error: null,
  records_with_abstracts: 131,
  expires_at: "..."
}
```

`exact_total` must be `null` for `partial`, `safety_bounded`, `rate_limited`, `unsupported`, or `unavailable` snapshots. `at_least` may report normalized records actually retained. `records_with_abstracts` measures evidence richness and must never determine or imply result completeness.

Completeness is true only when the existing snapshot engine exhausted the one requested source successfully, hit no source safety/offset bound, suffered no page failure, and post-validated every retained award against the exact contact key. Do not widen the existing NSF/NIH/DOE scan caps merely to make a UI total look exact; first add source diagnostics and preserve truthful partial states.

Presentation rules:

- show an exact total only for a complete snapshot;
- otherwise show **At least N matching awards** plus the specific safe coverage state;
- retain numbered server pages and the existing 10/25/50 page-size selector;
- never add a “load all cards” control or insert hundreds of cards into the page;
- the existing per-agency **Load additional awards** action may hydrate up to 25 cards at a time, but its label must state the number and explain that it hydrates recent cards rather than discovering the snapshot total;
- deterministic counts, facets, investigators, programs, and years must use the full snapshot aggregate, not hydrated cards;
- switching recent/all/custom years creates a new snapshot and resets incompatible page/facet state.

The five-year default reduces latency and safety-bound risk without removing historical access. **Search all available years** must still scan the requested source under the same server limits and report exact or partial coverage truthfully.

---

## 16. Full-snapshot-grounded Q&A

### 16.1 Trigger behavior

When the user asks a question in exact, single-source PO mode:

1. lock source, contact display name/key, year bounds, snapshot ID, and completeness state;
2. answer aggregate questions directly from the existing full-snapshot aggregate;
3. for topical questions, produce a small bounded set of retrieval phrases;
4. ask the Award Worker to score those phrases against the full snapshot and return only the best evidence records;
5. send only that bounded evidence pack to the explicitly selected browser-local provider;
6. validate every cited evidence ID;
7. qualify the answer according to snapshot and abstract coverage.

Do not hydrate all cards or send the complete portfolio to the provider. For non-PO searches, preserve current Institutional Intelligence behavior.

### 16.2 Bounded Worker evidence endpoint

Add one authenticated/origin-checked endpoint to the existing Award Worker, for example:

```text
POST /awards/snapshots/evidence
```

Its request contract should be limited to a valid snapshot ID, bounded normalized retrieval phrases, and a requested result limit no greater than 24. It must load the immutable snapshot, require PO mode, score all normalized snapshot records deterministically, and return a bounded evidence pack plus `records_scored`, `records_selected`, completeness, year scope, and abstract-coverage metadata.

Ranking fields, in descending weight:

1. project title;
2. abstract when present;
3. program name, activity code, program codes, and program office;
4. investigator and institution as low-weight supporting fields;
5. award year as filter/sort context, not topical evidence.

Reuse the repository’s established scientific tokenization/query normalization where practical. Exact title evidence must outrank a weak abstract mention, and generic overlap must not dominate.

Do not log or persist raw retrieval phrases. Apply existing origin checks, request-size validation, rate limiting, snapshot expiry handling, CPU ceiling, subrequest limits, and safe error responses. This endpoint must not create a new database or long-lived corpus.

If abstracts are absent, do not fetch details for an entire portfolio. The Worker may hydrate only a bounded top-candidate set through existing source detail paths when it remains within current limits; otherwise return the available evidence and disclose abstract coverage.

### 16.3 Provider payload and deterministic answers

Retain the current provider maximums:

- at most 24 award records;
- at most 800 abstract characters per record;
- at most 18,000 serialized evidence characters.

The provider receives the user’s question, locked public scope metadata, bounded public award evidence, and compact retrieval metadata—never the whole snapshot.

Answer without AI when the existing full-snapshot aggregate can resolve the question: total awards, represented years, investigators, programs, institutions, chronological listings, and facets. A chronological listing remains server-paginated; do not materialize every card.

### 16.4 Claim policy

Allowed only when the selected-year snapshot is complete and retrieval scored the full snapshot:

> I found three related projects among the 137 NSF awards from source award years 2022–2026 returned for the exact source-listed name “Jane A. Doe.”

A scoped negative may say:

> No closely related project was identified among those 137 complete, post-validated NSF records for 2022–2026.

Never say:

> Jane Doe has never funded this topic.

For partial coverage:

> No related project was identified in the available records, but the source snapshot is incomplete, so this is not a negative finding.

Answers must distinguish source facts, deterministic retrieval, model interpretation, selected-year scope, result completeness, and abstract coverage.

---

## 17. Program-officer files likely to change

Audit first; then make the smallest coherent changes.

### Browser/UI

- `funded_awards.html`
- `assets/institutional-intelligence.js`
- `assets/institutional-intelligence-snapshots.js`
- `assets/institutional-intelligence-core.js`
- `assets/institutional-intelligence.css`
- `assets/award-links.js`
- possibly `assets/app.js` only for the strictly gated current-opportunity action

### Worker/adapters

- `workers/award-api/src/index.js` for the bounded snapshot-evidence route and request validation;
- `workers/award-api/src/snapshot.js` for PO mode, exact post-validation, and full-snapshot evidence scoring;
- NSF, NIH, and DOE adapters only as needed to expose deterministic contact keys or correct source-specific post-validation.

Do not replace the Cache API snapshot design, weaken exact-versus-partial semantics, increase scan limits speculatively, or move authoritative computation back into the browser. Preserve origin checks, abuse controls, rate limits, maximum year span, request-size limits, cache behavior, 250 ms CPU safety ceiling, and rollback-aware deployment.

### Tests and documentation

- extend `tests/browser/institutional-intelligence-contract.test.mjs`;
- extend the current snapshot and Award API contract suites;
- add a focused PO identity/evidence contract suite;
- extend `tests/e2e/institutional-intelligence.spec.mjs`, `funded-awards.spec.mjs`, and accessibility coverage;
- extend Funding Finder E2E only if the optional current-opportunity action ships;
- update `README.md`, `PROJECT.md`, Help, and privacy text.

---

## 18. Program-officer test matrix

### 18.1 Navigation, identity, and years

Test that:

- clicking an NSF/NIH/DOE contact opens only that source and requires no AI key;
- recent PO mode uses one immutable UTC `as_of` and exactly five inclusive source award years;
- September 30/October 1 and December 31/January 1 boundaries do not create mixed-clock cache, URL, or request state;
- **Search all available years** clears both bounds while ordinary Funded Awards defaults remain unchanged;
- custom years, preset, source, name, snapshot, page, and page size survive URL/history round-trip;
- organization/help-desk contacts are not actionable;
- exact/prefix upstream false positives are removed by post-validation;
- punctuation and comma-order normalize safely, while missing/extra middle initials, suffixes, variants, and cross-source identities remain separate.

### 18.2 Snapshot coverage and presentation

Test complete, partial, safety-bounded, rate-limited, unsupported, unavailable, expired, and successor-retry states. Prove exact totals appear only for complete post-validated snapshots; `at_least` remains truthful otherwise; full-snapshot aggregates do not depend on hydrated cards; pages 10/25/50 are stable; a 629-record fixture does not create 629 DOM cards; and the 25-per-agency hydration action neither changes snapshot membership nor masquerades as discovery.

Include an all-years fixture that reaches a source safety bound and remains visibly partial, plus a recent-five-year fixture that is complete. Do not loosen the bound to make the test pass.

### 18.3 Retrieval and Q&A

Create fixtures where:

- the only relevant award is beyond the displayed page and former first 24 records;
- the Worker scores every snapshot record but returns no more than 24;
- exact title evidence outranks a weak abstract mention;
- bounded scientific synonyms recover a legitimate match and generic overlap does not dominate;
- locked source/contact/year/snapshot scope cannot be altered by the AI plan;
- no more than 24 records, 800 abstract characters per record, and 18,000 serialized evidence characters reach the provider;
- raw retrieval phrases are not logged or persisted;
- unsupported evidence IDs are discarded;
- deterministic totals and facets come from the snapshot aggregate;
- missing abstracts lower disclosed evidence coverage without changing result completeness;
- complete and partial negative-answer language differs correctly;
- expired/cross-colo snapshots take the existing refresh path safely.

### 18.4 End-to-end acceptance flow

The decisive fixture-backed flow is:

1. open a funded-award card and select a program contact;
2. see the exact source-scoped recent-five-year snapshot without an AI key;
3. move among numbered pages and optionally select all years without rendering the entire set;
4. ask whether a fixture topic appears and when;
5. retrieve a relevant fixture award beyond the visible page through the bounded Worker evidence route;
6. send only bounded evidence to a mocked provider and cite a valid award;
7. report exact selected-year coverage when complete;
8. repeat with a safety-bounded or failed-source snapshot and verify visibly partial, non-definitive language.

Use mocked provider and award-source responses in CI. Do not require paid provider keys.

---

# 19. Cross-cutting privacy, security, and trust rules

Both features operate on public institutional and sponsor records, but existing privacy and security boundaries still apply.

- Reverse match makes no provider call.
- Program-officer structured browsing makes no provider call.
- Optional PO Q&A uses the same explicitly selected browser-local provider and credential store as existing Institutional Intelligence.
- Never send faculty emails, the faculty workbook, the full faculty roster, user profiles, CV text, ORCID publication text, uploaded notices, saved notes, alert subscriptions, or unrelated chat in a PO question.
- The provider receives only the user’s question, locked public PO/source scope, bounded public award evidence, and compact retrieval metadata.
- The Award Worker receives only bounded retrieval phrases for snapshot evidence selection; it must not log or persist them. No new portfolio corpus or database is created.
- Team Match faculty-directory searches stay in the browser and are not sent to a Worker, provider, or analytics service.
- No faculty ranking or PO question should be logged with personally sensitive user context.
- Existing CSP, origin restrictions, no-store behavior, request validation, and rate limits remain in force.
- Missing or partial source evidence must remain explicit.
- A model may interpret supplied evidence but may not create source facts.

---

# 20. Implementation order

## PR 1 order

1. Establish clean baseline from current protected `main`.
2. Add workbook importer and synthetic importer tests.
3. Import the supplied workbook and review the canonical JSON diff.
4. Add canonical schema validation and actual-snapshot invariants.
5. Refactor `scripts/faculty_match.py` to use the canonical config.
6. Generate the compact faculty directory and one-copy match graph atomically; add determinism, fingerprint, and byte-budget validation.
7. Replace the 14-person Team Match select with the accessible Hajim search and separate manual/external researcher action while preserving team semantics.
8. Add the lazy-loaded Funding Finder reverse-match UI and one-open-panel behavior.
9. Add multidisciplinary relevance fixtures and tune only from recorded cases.
10. Update workflow, validation, documentation, and Help.
11. Run focused tests during development and one configured full protected gate on the final candidate SHA.
12. Complete exact-head review, merge, verify protected `main`, and verify live directory search, manual entry, lazy assets, and reverse matching.

## PR 2 order

1. Establish clean baseline from the newly merged protected `main`.
2. Add deterministic source-contact keys and adapter/snapshot post-validation fixtures.
3. Add source-scoped PO deep-link helpers with recent-five-year, all-years, custom-year, and history contracts.
4. Make normalized funded-award program contacts actionable without AI.
5. Extend the existing snapshot contract for PO identity, selected-year scope, abstract coverage, and truthful exact/partial display.
6. Add the bounded full-snapshot evidence endpoint and deterministic retrieval tests.
7. Connect optional Q&A to that evidence route while preserving provider limits and evidence-ID validation.
8. Add deterministic snapshot-aggregate answers and the scoped claim policy.
9. Add the current-opportunity contact link only if the role audit passes.
10. Update Help, privacy copy, and documentation.
11. Run focused tests during development and one configured full protected gate on the final candidate SHA.
12. Complete exact-head review, merge, verify protected `main`, deploy through the Award Worker release path, and verify the live recent/all-years listing and controlled Q&A path.

---

# 21. Validation commands and protected gates

Codex must inspect current CI and use its exact commands. At minimum, the final SHA of each PR should pass the current equivalents of:

```bash
python -m tools.run_refresh_validation
node --test tests/browser/*.test.mjs
pnpm test:e2e
```

Also run targeted tests during development, including the new importer/matcher and PO portfolio contracts.

Before final review:

```bash
git diff --check
```

For generated faculty assets:

1. generate once;
2. record the output hash;
3. generate again from the same inputs;
4. require identical bytes;
5. run generated-data validation against the current catalog;
6. record raw/gzip sizes for the directory and match graph and enforce the approved budgets;
7. verify the full workbook and canonical JSON are absent from public runtime requests.

Do not run unrelated paid Voyage/OpenAI/Anthropic evaluations. Provider behavior must be tested with fixtures and mocks. If the existing protected workflow automatically runs broader release gates, allow those configured gates to run rather than duplicating them manually.

PR 2 is expected to change the Award Worker. Complete the repository’s protected candidate deploy/handshake/smoke and rollback-aware workflow. Verify actual production CPU distribution and invocation outcomes under the existing 250 ms configured ceiling; do not infer production CPU safety solely from local wall-clock timing.

---

# 22. Deployment and rollback

### Reverse match

Rollback options, from smallest to largest:

1. disable the reverse-match UI flag or remove the action while leaving the canonical roster and Team Match data intact;
2. restore the prior generated directory and `data/faculty_matches.js` together using their matching generation identity;
3. revert the PR.

Ordinary Funding Finder must remain usable if the reverse-match asset is absent or incompatible.

### Program-officer portfolios

Rollback options:

1. hide the PO action while preserving the existing typed `program_officer` filter;
2. disable the new snapshot-evidence endpoint/Q&A integration and fall back to current bounded resident-card answers with explicit limitations;
3. revert the PR;
4. use the existing Award Worker version rollback procedure.

No migration or user-data rollback should be required because neither feature introduces a persistent application database.

---

# 23. Definition of done

The implementation is complete only when all of the following are true.

## Hajim Reverse Match

- The supplied workbook has been converted to deterministic, reviewable canonical JSON.
- The canonical profile count is 156, with 145 rankable and 11 explicitly unrankable profiles.
- OpenAlex no longer determines the active Hajim roster.
- The existing faculty matcher is generalized rather than duplicated.
- Team Match consumes a compact projection of the same canonical roster; neither the workbook nor canonical JSON is browser-loaded.
- Team Match offers **Search Hajim faculty at the University of Rochester** through an accessible, bounded local combobox rather than a 156-name select/button wall.
- **Add a researcher manually** remains a separate prominent path for collaborators outside Hajim or anyone not listed, with existing ORCID and browser-local behavior preserved.
- The directory and match graph share one generation identity and stay within validated initial/lazy-load byte budgets.
- Every current opportunity can request a lazy-loaded, no-AI reverse match.
- Results are evidence-qualified, source-cited, and relationship-labeled.
- Derived themes never admit a result by themselves.
- Generic single-token overlaps do not flood the result set.
- A multidisciplinary human-reviewed quality fixture passes.
- Failure of the reverse-match asset does not impair Funding Finder.
- Mobile and accessibility gates pass.

## Program-Officer Portfolios

- A normalized funded-award program contact can be clicked to run a source-scoped exact-name award search without AI.
- The structured URL is shareable and restorable.
- Dedicated PO mode defaults to the five most recent source award years, while all-years and custom-year options remain explicit and restorable.
- Each retained result is post-validated against the exact source/contact key before totals and evidence are computed.
- The UI distinguishes complete, partial, safety-bounded, rate-limited, unsupported, unavailable, and expired coverage without conflating result coverage with abstract coverage.
- Existing server snapshots, direct pages of 10/25/50, and full-snapshot aggregates remain authoritative; the browser never loads every card to establish totals.
- Optional topical questions score the full server snapshot through the bounded evidence endpoint before choosing the provider pack.
- The provider still receives no more than the established bounded evidence limits.
- Deterministic counts/programs/investigators/years use the full aggregate.
- Negative findings are permitted only with complete coverage and remain scoped to the exact source query.
- Name variants and cross-agency identities are not speculatively merged.
- No AI key is required for portfolio browsing.
- Fixture-backed E2E tests recover a relevant award beyond the visible page, keep the DOM bounded, and correctly qualify a partial snapshot.
- Existing Funded Awards and Institutional Intelligence workflows remain intact.

## Release integrity

- Each PR’s final exact SHA has passing required checks.
- Each PR receives terminal exact-head review under `AGENTS.md`.
- No consequential review thread remains unresolved.
- Protected `main` contains the intended merge.
- Live GitHub Pages verification confirms the no-AI user flows.
- Final reporting includes the merged PRs, final `main` SHA, test evidence, generated faculty source hash/counts, and any documented source-coverage limits that remain.

---

# 24. Final reporting template

After both PRs are merged, report:

```text
Feature 1: Hajim Reverse Match
- PR:
- Merge SHA:
- Canonical faculty source:
- Workbook SHA-256:
- Profiles: 156 total / 145 rankable / 11 unrankable
- Directory/match schema and shared generation ID:
- Directory raw/gzip bytes:
- Match graph raw/gzip bytes:
- Team Match Hajim search/manual-entry verification:
- Targeted tests:
- Full gates:
- Live verification:

Feature 2: Program-Officer Portfolios
- PR:
- Merge SHA:
- Sources verified: NSF / NIH / DOE
- Recent-five-year and all-years fixtures:
- Exact contact post-validation evidence:
- Complete/partial snapshot evidence:
- Bounded evidence limits:
- Award Worker version / rollback version:
- Configured CPU ceiling and production CPU/outcome observations:
- Targeted tests:
- Full gates:
- Live verification:

Final protected main SHA:
Known bounded limitations:
```

Stop after reporting the merged and verified implementation. Do not begin any excluded feature.
