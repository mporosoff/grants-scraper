# Funding Finder — Design Roadmap & Next Steps

**Prepared:** July 26, 2026
**Purpose:** turn three ideas into clearly scoped workstreams so each can be designed and built without scope creep. Effort is relative (S / M / L), not calendar promises.

> Note on wording: I read item 1 ("make the audit layer less coarse") as the **relevance-feedback / evaluation layer** — the "Match Quality Testing" controls (useful / not relevant / verify) we discussed as too coarse. If you meant something else by "audit layer," flag it.

> **Status update (July 26, 2026, later):** Workstream 0 is done (`.gitattributes`, vendored-hash normalization, and the one-time repository renormalization are complete). Workstream A's graded scale is shipped and the evaluator now reports graded relevance **and nDCG** for retrieval and reranking. Workstream C has moved well past shells: the verified NSF upcoming-due-dates adapter is enabled, the daily workflow runs the merge step, and the source layer now has an atomic per-source replace, a committed last-known-good snapshot cache, currentness/actionability validation, per-source health bounds, full post-merge validation, and a provenance-aware UI/AI/export pass. The NIH Guide adapter is intentionally disabled because NIH stopped publishing NOFOs there in FY2026; Grants.gov remains the official NIH NOFO source. Workstream B (local preference model) is the main remaining build.

---

## The three workstreams at a glance

| # | Workstream | What it delivers | Depends on | Effort |
|---|---|---|---|---|
| A | Richer relevance feedback | Graded labels + reason codes so we can tell "close" from "wrong" | — | S–M |
| B | Local preference model | Feedback actually re-ranks *this user's* future results, on-device | A | M (+L for optional LLM) |
| C | Adapter layer → connected sources | Turn the shells into working, verified sources | Step 0 | Framework done; each source S–M |
| 0 | (Prerequisite) Repo hygiene | Fix line endings before adding more code | — | S |

Suggested order: **0 → A → B** in sequence (A feeds B), with **C running in parallel**. The deferred pilot validates A+B.

---

## Workstream 0 — Repository hygiene (complete)

The repository now has explicit LF normalization, reviewed third-party parser
bytes remain exempt, and the vendored-hash test normalizes line endings before
comparison.

**Scope:** add a `.gitattributes` (`* text=auto eol=lf`), run `git add --renormalize .`, make the vendored-parser hash test normalize line endings before hashing. Nothing functional changes.

**Definition of done:** a fresh clone shows a clean `git status`; the full test suite is green (the 3 current CRLF "failures" disappear).

---

## Workstream A — Make the relevance-feedback layer less coarse

**Problem.** Useful / Not relevant / Verify captures *acceptance*, not *degree of fit*. It can't express "close, but not quite," and it doesn't clearly separate two different jobs:
- **Evaluation** (for you, the developer): measure whether retrieval and ranking work, aggregated across a pilot. *This is what the tool does today.*
- **Signal for the user** (Workstream B): make this user's next results better. *This does not exist yet.*

**Scope (in).**
1. **Graded relevance scale** (4 levels), e.g. `Not relevant → Marginal (close) → Relevant → Highly relevant`. This maps to standard graded-relevance metrics (nDCG).
2. **Keep and surface the reason codes** already in the design (topic, eligibility, career stage, deadline, award size, burden, duplicate/known, insufficient detail). The *reason* is the most useful signal — it says *why* something missed.
3. **Lightweight UX:** a quick grade + optional "why," not a form. Opening feedback shouldn't feel like homework.
4. **Schema + evaluator update:** extend the local evaluation record and `evaluate_phase2.py` to compute graded metrics; keep the export privacy-safe and backward-compatible with existing binary labels.

**Scope (out).** No personalization yet (that's B). No new developer telemetry — stays device-local and export-only.

**Risks / decisions.** Don't over-ask the user; more granularity only helps if it stays one or two clicks. Decide the exact scale and whether "close" requires a reason.

**Definition of done.** A user can grade 4 levels with an optional reason; the export remains privacy-safe; the evaluator reports graded metrics (e.g., nDCG) separately for retrieval vs. reranking.

---

## Workstream B — Local, adaptive preference model

**Goal.** Make feedback *do something for the user*: promote patterns they like, demote what they reject, recover things wrongly filtered — stored locally, private, transparent, reversible.

**The key design insight (don't skip this).** Feedback can only act on what was **shown**. If a filter wrongly excluded a good opportunity, the user never sees it, never rates it, and a naive up/down-rank loop just reinforces its own first mistake — a filter bubble. So the model needs **two halves**:
- **Down-weight / remove** the not-relevant (easy, safe).
- **Recall-widening + exploration** to counter false negatives (the hard, valuable half): learn synonyms/topics from "highly relevant" items and re-query; keep a small "exploration" slot that surfaces a few candidates *just outside* current filters to test whether they're too tight.

**Scope (in).**
1. **Deterministic local preference profile (no LLM):** per-user weights that boost/penalize topics, agencies, eligibility, and remembered dismissals; layered on top of the existing BM25 ranking. Transparent and explainable.
2. **Exploration slot + recall widening** (per the insight above).
3. **Transparency & control:** "boosted because you found similar useful," an undo, and a switch to turn personalization off. The base catalog must stay fully searchable *un-personalized* on request.
4. **Optional, later — LLM "Refine from my ratings" (batched, explicit):** send the labeled examples' *public* metadata + reason codes (never the catalog, never per-click) to the model to propose an updated query expansion and suggested filter changes, shown for approval. The LLM adjusts the *query/ranking*; it never fabricates or auto-deletes opportunities.

**Scope (out).** No cross-device sync or server (that's a later, service-backed decision). No silent auto-removal of opportunities.

**Guardrails.** Conservative weighting + a minimum number of labels before adapting (avoid overfitting a handful of clicks); keep the per-search path LLM-free; personalization is a lens, never a gate.

**Dependencies.** Needs Workstream A's graded signal + reason codes to learn from.

**Definition of done.** Rating a few items measurably and transparently reorders subsequent results *on-device*; wrongly-filtered items can resurface via exploration; the un-personalized full catalog is always one click away.

---

## Workstream C — Adapter layer: from framework to connected sources

**Current state (precise).**
- **Framework:** built, tested (28 source tests), verified against the real 1,465-record catalog. Safe by default (adapters off unless enabled; Grants.gov always wins; one broken source can't break the build). Now also: atomic per-source replace, committed last-known-good snapshot cache, currentness/actionability validation, per-source health bounds, and full post-merge validation.
- **`rss` engine:** works and is tested. **`sample`:** works offline (demo).
- **`nsf-funding`:** enabled and live against NSF's official upcoming-due-dates feed.
- **`nih-guide`:** disabled intentionally; NIH Guide now carries policy and informational notices rather than FY2026 NOFOs.
- **`nyserda`, `ur_infoready`:** **shells** — `parse()` returns nothing.
- **`pnd-rfp`:** ready to configure (needs live feed URL + a topic filter).
- **Net:** NSF is connected; additional non-federal and institutional sources remain to be built.

**"Can we wire in every source we can think of?"** We can *add an adapter for each*, but each real source is its own implementation + live verification, and a few should never be added (licensed databases). So the plan is: enumerate the full backlog, implement incrementally, enable one verified source at a time. Here's the backlog, tiered:

| Tier | Source | Route | Effort | Notes |
|---|---|---|---|---|
| **1 — do first** | UR InfoReady | scrape public competitions page | S–M | Highest institutional value; internal + limited submissions. Best first real adapter. |
| 1 | NYSERDA | scrape one funding page | S–M | You named it; energy-relevant; low volume. |
| **2 — breadth** | Candid PND RFP Bulletin | RSS (engine already built) | M | One source → many foundations. Needs topic/eligibility filter (nonprofit-skewed). |
| 2 | ~10 flagship foundations (Templeton, Sloan, Moore, Simons, Keck, …) | per-site scrapers | S each × N | Cap the list; maintenance scales with N. Derive from your spreadsheet's top sponsors. |
| **3 — fill gaps** | NSF Dear Colleague Letters | scrape NSF opportunities page | M | Overlaps Grants.gov → needs dedup. |
| 3 | NY Grants Gateway / Contract Reporter | portal listing | M | Broader NY state (includes NYSERDA + more). |
| 3 | SAM.gov | official API (key) | M | Contracts, not research grants — low priority. |
| **Never** | SPIN/InfoEd, Pivot, Duke, GrantForward, Instrumentl, Candid FDO | licensed/subscription | — | Prohibited/paid; explicit non-goal. |

**Per-source "definition of done"** (the reusable checklist): adapter module + fixture test + health check (plausible row count) + documented public-use basis + maintenance owner + `enabled = True`. Then one shared change: add the single documented workflow step (in `scripts/sources/README.md`) and confirm the regression test passes on the merged asset.

**Recommendation.** Do **UR InfoReady first** (highest value, single page), then **NYSERDA**, then **PND**. Don't try to wire everything at once — enable sources one verified adapter at a time.

---

## Also worth putting on the list (things easy to miss)

1. **Source facets — done.** The browser now exposes both source name and source type, and preserves those selections in the saved local profile.
2. **Handle sparse non-federal data gracefully.** Foundation/state records rarely have structured award floors or eligibility codes, so they populate fewer facets and more "not listed." The UI should degrade cleanly and lean on "verify at official source." *(S)*
3. **The deferred pilot is now more important, not less.** Both A and B optimize toward a feedback signal; if that signal is coarse or biased, an adaptive loop can *degrade* quality. You need real labeled data to (a) validate graded metrics and (b) tune/trust the preference model. This ties directly to the audit's open Phase 2C pilot. *(Planning, not code.)*
4. **Guard the enrich/evidence steps against external records.** Those steps assume Grants.gov-shaped records. Running the source-merge as the *last* step (as designed) already avoids this, but add a one-line guard/test so a future reordering can't send a foundation record to the Grants.gov detail API. *(S)*
5. **Cross-source dedup will need to grow up.** Today's dedup is identity + (title, close_date). As sources overlap (NSF in Grants.gov *and* on nsf.gov), you may need fuzzier matching. Fine for now; revisit at Tier 3. *(M, later)*
6. **Governance:** per-source maintenance owner, health check, and failure alert (the Phase 4 checklist). One-person bus factor is fine for a pilot, not for 6 live sources. *(Planning.)*
7. **Legal hygiene per scrape:** respect `robots.txt` and rate limits (the HTTP client already paces); document each source's public-use basis. *(Ongoing.)*

---

## One-paragraph summary

Repository hygiene, graded feedback, graded evaluation metrics, source facets, the safe source lifecycle, the daily merge, and the first verified external source are complete. The main next build is Workstream B: a local, transparent preference model with an exploration slot so it can recover wrongly-filtered opportunities rather than only reinforcing its first guess. In parallel, turn the remaining adapter shells into verified sources one at a time, starting with UR InfoReady and NYSERDA. Keep the base catalog searchable without personalization, and use the deferred researcher pilot to verify that these layers improve real matches.
