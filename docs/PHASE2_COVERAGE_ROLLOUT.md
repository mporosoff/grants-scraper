# Phase 2 — Source-Coverage Rollout & Known Gaps

**Purpose:** record the current source-coverage implementation, known gaps, and
priority order.

**Context / what exists today:** Grants.gov (full daily catalog), NSF (RSS),
NYSERDA (JSON API), and the server-rendered ARPA-E and DOE EERE Exchange NOFO
lists. NASA NSPIRES and UR InfoReady remain disabled shells while stable routes
are unavailable; neither is represented as live coverage. A program-area
discoverability layer now tags opaque umbrella FOAs (e.g. DOE Office of
Science) so topical searches like "catalysis" surface them. A device-local
Save/Favorites store, a graded-relevance feedback scale + nDCG metrics, and a
local preference-model re-ranker are also in.

**Key finding that motivates this doc:** Grants.gov coverage is uneven. NIH
(~733 records) and DoD (~109) are well represented, but **DOE is badly
under-represented** because DOE's mission offices run their *own* application
portals ("Exchange" systems) that don't fully mirror to Grants.gov. DOE Office
of Science grant FOAs *are* on Grants.gov (verified: DE-FOA-0003600 umbrella +
Genesis), but EERE, ARPA-E, and lab-call opportunities largely are not.

---

## A. Federal coverage gaps (priority)

| Source | Why it's a gap | Ingestion route | Effort | How to get the endpoint |
|---|---|---|---|---|
| ~~**DOE EERE Exchange** (eere-exchange.energy.gov)~~ | Not fully on Grants.gov; own portal | Server-rendered NOFO list | Shipped | Enabled adapter with health bounds and last-known-good lifecycle |
| ~~**ARPA-E eXCHANGE** (arpa-e-foa.energy.gov)~~ | Partially on Grants.gov; own portal | Server-rendered NOFO list | Shipped | Enabled adapter sharing the verified DOE Exchange parser |
| **DOE Office of Science — National Lab Announcements** (science.osti.gov/grants/Lab-Announcements) | Lab calls not on Grants.gov | HTML list (server-rendered) | Medium | Confirm raw-HTML row structure |
| **Other DOE offices** (NE, FECM/NETL, GDO, MESC, OCED, IEDO) | Own solicitations/Exchange portals | JSON API / HTML per office | Medium each | Per-office Network capture |
| **NASA NSPIRES / solicitation.nasaprs.com** | Some overlap with Grants.gov; NSPIRES authoritative | HTML/list; possible feed | Medium | Investigate |
| **USDA NIFA** | Mostly on Grants.gov; confirm completeness | Grants.gov + spot-check | Low | — |
| **NSF Dear Colleague Letters** | DCLs aren't all in Grants.gov | Scrape new.nsf.gov/funding/opportunities (dedup vs Grants.gov) | Medium | — |
| **NIH Guide notices / NOSIs** | NOFOs already via Grants.gov; notices/NOSIs supplemental | NIH Guide RSS (adapter exists, disabled) | Low | Re-enable + filter to relevant notices |
| **SAM.gov** | Contracts, not grants — lower priority | Official API (key) | Medium | Only if contract vehicles wanted |

> Note: ARPA-E and EERE Exchange currently expose their opportunity summaries
> in server-rendered HTML rather than a public JSON endpoint. The adapters keep
> only NOFO rows and are fixture-tested against that structure.

## B. Non-federal

| Source | Route | Effort | Notes |
|---|---|---|---|
| **Foundations via Candid PND "RFP Bulletin"** | RSS aggregator (adapter scaffold exists) | Medium | Confirm current feed URL; add a topic/eligibility filter (nonprofit-skewed) |
| **Curated flagship foundations** (Templeton, Sloan, Moore, Simons, …) | Per-site scrapers | Low each × N | Cap the list to bound maintenance |
| **NY State Grants Gateway / Contract Reporter** | Portal listing | Medium | Broader NY state beyond NYSERDA |

## C. Discoverability track (beyond the quick fix already shipped)

1. **Phase-3 FOA-PDF text extraction for umbrella FOAs** — *shipped.*
   `extract_document_evidence.py` now scans each official notice's PDF/HTML for a
   controlled program-area vocabulary (`scripts/program_areas.py`) and, for every
   term actually present, attaches the compact canonical label to the record's
   indexed `document_search_text` and its Topic tags to the facet — with a
   page/section citation retained in the evidence cache. So "catalysis" surfaces
   DOE's opaque Office-of-Science umbrella FOA even though its catalog text never
   says the word. This generalizes the hand-maintained `discoverability.py`
   lexicon (which stays as a fast catalog-text fallback) to any FOA whose notice
   mentions the program area, and never dumps raw notice text into the catalog.
2. **AI query-expansion with program-area synonyms** — map user topics to agency
   program vocabularies during the optional AI expansion step.
3. **Extend `scripts/sources/discoverability.py`** — add more program lexicons
   (NIH institutes, NSF directorates) as gaps are found.

## D. Other widget gaps / needed work (cross-cutting)

- **Run the deferred Phase 2C relevance pilot.** Still the highest product risk:
  the AI matching and the new preference model optimize a signal that hasn't
  been validated with real researchers. Measure before trusting.
- **Saved searches + automatic email alerts** (Phase 5) — *first cut shipped,
  GitHub-native.* Two complementary paths now exist: (1) **static RSS/Atom
  feeds** (`scripts/build_feeds.py` → `feeds/`) generated in the daily pipeline,
  needing no backend or personal data; and (2) **weekly email digests** of a
  saved search via a shared server-side matcher (`scripts/alert_match.py`, which
  reuses the site's exact tokenizer + BM25 index) driven from a **private**
  companion repo (bundle in `docs/weekly-alerts/`). The local Save/Favorites
  remains device-only; true cross-device saved searches + an in-page subscribe
  form + automated double-opt-in are the remaining Phase 5 work.
- **AI-key friction → institutional AI gateway.** Most faculty won't paste an
  OpenAI/Anthropic key; a UR-managed gateway would unlock the AI features.
- **Source health monitoring / endpoint drift is implemented.** Enabled
  sources have plausible-count bounds, currentness/actionability gates,
  last-known-good snapshots, a nonzero degraded exit status, and an
  owner-facing GitHub issue from the scheduled workflow. InfoReady remains
  disabled and contains no embedded secret.
- **Cross-source dedup at scale.** Current dedup is identity + normalized
  title/number. As overlapping sources grow (NSF in Grants.gov *and* nsf.gov),
  add fuzzier matching.
- **Accessibility:** dark-mode (`prefers-color-scheme`) and high-contrast
  (`forced-colors`) support are implemented; continue testing as the interface
  changes.
- **Browser coverage:** saved opportunities, graded feedback, preference-model
  behavior, chat formatting/narrowing, and the responsive page contract have
  automated tests. Keep adding real-browser checks for interaction regressions.
- **Mobile UX pass** and a **legal/ToS review** per scraped source.

## E. Suggested order

1. ~~**Discoverability via FOA-PDF extraction** (C1)~~ — *done.* Broadly fixes
   topical gaps like the DOE catalysis example without new sources.
2. ~~**DOE EERE Exchange + ARPA-E eXCHANGE adapters** (A)~~ — *done* (enabled,
   fixture-tested, source-health gated; first production run is the release
   verification step).
3. **Run the relevance pilot** (D) — validate matching before scaling further.
   Now the highest-value remaining step.
4. **Foundations via Candid PND** (B) — breadth across many funders at once.
5. **Saved searches + alerts** (D/Phase 5) — highest-value recurring-use feature.
6. Establish a stable, permissioned InfoReady route if UR internal coverage is
   still desired; then add the remaining DOE offices, NASA, and NSF DCLs.
