# Topic Layer Implementation Plan

**Deterministic subtopic extraction for umbrella solicitations**
Repository: `mporosoff/grants-scraper` (Funding Finder)
Status: in progress · Version 8.6 · Written 2026-08-15 · **Revised 2026-08-17 against `docs/RECON.md`, measured build data, two CI failures, `docs/CORPUS_CENSUS.md`, `docs/COVERAGE_SURVEY.md`, a measured LLM span-classifier run re-baselined on `claude-sonnet-5` (§11), a size/BM25 measurement that closed both blocking storage decisions (§12, §13), and `docs/FAMILY_TAXONOMY.md` — which induced the pattern taxonomy from a third stratified sample and retired seven of the ten families in §6.3**

> **Start at §18.** It defines the minimum path — the **nine** work packages that are actually being built (A–G plus **D½ Coverage**, added in 8.2, and **D¾ Forms**, added in 8.5) — and lists what is deferred and what it costs. §10's four phases remain as background; §18 supersedes them as the unit of work, and §15 tracks §18.
>
> **8.3 changes one thing structurally: the unit of judgment moves from the sibling *set* to the individual *span* (§6.4b), because a set-level verdict lets two policy paragraphs delete 70 DOE programmes.** §11 is reopened for the precision half only, on a measured run; its recall argument is untouched.
>
> **8.4 closes the two blocking storage decisions.** `MAX_TERMS` stays at 400 and subtopics ship in a lazily-loaded `data/subtopics.js` sidecar — one question, not two, once you measure that 60.3% of a cache record is a term map the browser never reads as content. **Nothing now blocks committing a cache except running the backfill again.** Every rate quoted against `docs/CORPUS_CENSUS.md`'s 20 documents is still superseded by `docs/COVERAGE_SURVEY.md` (§1.1).
>
> **8.6 makes §15 readable.** A new **Open state at a glance** table at the top of §15 indexes every open decision, unmet gate, unfixed defect and outstanding measurement, and §15 gains a **Debt** section for the twelve threads that previously lived only in session reports. §6.7a is surfaced as a real §13 decision after fifteen sessions behind a pointer. **The Cov5 classifier re-run measured a precision effect of zero — and measured run-to-run variance larger than the signal it was looking for (§11).**
>
> **8.5 replaces §6.3.** The ten families were written from expectation and have now been tested against the corpus rather than measured against. **Seven are retired: five never fired across 170 real documents and two produced only false positives.** §6.3 is now an induced taxonomy of six *forms*, ordered by measured coverage, and **§18.1 is re-ordered so Cov4's classifier lands before any new family work** — the two largest uncovered forms are both unsafe on structure alone.

---

## ⚠ What changed in 8.7 — the provenance audit

**An outside audit argued that this plan over-weights generic document inference
relative to hierarchies agencies already publish. Substantially accepted**, and
the acceptance is structural rather than cosmetic: §5.1 ranks provenance, §6.7·0
routes to the least-ambiguous source first, §18.1 inserts package D⅝ ahead of
all remaining recogniser work, and Cov4 narrows to the inference it was designed
to check.

**The audit was right about the ordering.** Every scheduled recogniser item
operated at the bottom rung on sources that had to be guessed at, while the
sources agencies publish as data were unscheduled. NASA is the case in one
agency: the family named for ROSES was **retired with zero correct matches in 90
read records** (§6.3), its nine plausible umbrellas all fail at fetch time, and
nobody had tried Table 3.

**Two corrections to the audit, recorded because they change what D⅝ can claim.**

1. **It cites 42% correct-acceptance. That figure is superseded and was never a
   corpus rate.** 42% was 5 of the **12 enumerating documents in the hand-picked
   census 20**, measured at the end of package D. `docs/COVERAGE_SURVEY.md`
   established that the census was chosen to span shapes and enumerates at 60%
   against a corpus rate near 26%, so every rate against it flatters the design
   by roughly 2×. The current figures are in `docs/FAMILY_TAXONOMY.md`: **the ten
   families reach ~10% of the enumerating population**, and the enumerating
   population is itself **~171 records, 11.6% of the catalog** (§1.1). The audit's
   conclusion survives its wrong number — it is stronger at 10% than at 42% — but
   the number should not be requoted.

2. **Structured sources do not address the 62% (a) population, and nothing in
   D⅝ should be read as claiming they do.** `docs/FAMILY_TAXONOMY.md` §1
   classifies every non-accepting document across 60 read records: **33 of 53 —
   62% — contain no enumerated list of fundable subdivisions in any source.**
   They are single-project cooperative agreements, single-programme NOFOs and
   formula allotments. There is no table to parse, no program page to follow, and
   no hierarchy to import, because **there is no hierarchy.** A `native` adapter
   changes nothing for them.

   > **So D⅝'s value is new parents, not expanded ones.** It reaches umbrella
   > records that generic inference currently misses entirely — ROSES elements
   > that never get fetched, DOE programmes that live on program pages — and it
   > does not widen coverage of records already read and found to enumerate
   > nothing. Any measurement of D⅝ must report **new parents gained**, separately
   > from any change to existing records, which is why S1d's gate says exactly
   > that.

---

## ⚠ What changed in 8.5 — the family taxonomy

**`docs/FAMILY_TAXONOMY.md` (2026-08-17) asked the one question the census and the survey never did: are these the right families?** Both earlier documents measured acceptance *against* §6.3's ten. This one induced a taxonomy from a third stratified sample — **50 records, 170 documents opened, disjoint from the census 20 and the survey 40** — classified by `claude-sonnet-5` at adaptive thinking with the extractor's own form tags withheld from the prompt, and cross-checked by running production's `FAMILIES` tuple over every document.

**The result is that §6.3 was mostly wrong, and wrong in a way that was invisible to acceptance-rate measurement.** A family that never fires costs nothing and shows up nowhere; seven of the ten are in that state or worse.

| Was (§6.3, written from expectation) | Is (measured over 170 documents / 90 read records) | Why it matters |
|---|---|---|
| Ten ordinal families, each with a "typical source" | **13 in code** (D3 added three, undocumented in §6.3 until now), of which **8 never fire** across 170 documents | §6.3's table has been stale since D3, and §17.2's "the code is authoritative" applied to it and went unchecked |
| The families are narrow deliberately, and narrowness is the safety property | **Narrow is not the same as correct.** `roses_element` fired on **6 documents and 0 real lists** — `A.1 BACKGROUND AND OBJECTIVES`, `C.3 Budget Documents` — reproducing the census's `332894` false positive on new documents, with no correct match anywhere in 90 records | Two families are net-negative: they contribute only false-positive surface. Retiring them is a precision *gain*, not a recall cost |
| The largest pattern blind spot is "named subdivisions with no ordinal" | Correct, and now sized: **F4 named/bulleted is 9 of 90 read records, ~73 catalog.** But **F1 bare-numbered is 8 of 90 and the most *stably* measured uncovered form** | The most common uncovered form is the one §6.3 and §18.3 forbid adding. §18.3 now carries exit criteria rather than a flat prohibition |
| Six forms unknown; families assumed to span the space | **Six forms exist. One is covered.** The ten reach ~17 of ~171 umbrella records — **10% of the enumerating population** | 90% of umbrellas use a form nothing recognises. That is the recall gap, and it is not a tuning gap |
| Tabular lists unconsidered | **F5 tabular is real and new** — `363530` presents 12 topics as table rows, and they are *the same 12 topics* as `363526`, which presents them as headings. `extract_containers` has no table path | One program office, two notices, two forms, one reachable. A presentation variant, not a new population |
| ~128 umbrella parents, 8–9% | **~171 records, 11.6%**, on 87 stratified records at 12–22 per stratum. Band **54–538 (3.7%–36.5%)** | §1.1 corrected. The number to plan against is the A/B/C core — **~80 records, band 38–148** |

**The methodological finding, stated because it generalizes past §6.3.** Three families were written *from measurement* — `focus_area`, `component` and `technical_category`, all added in D3 from documents the census had read. **All three have corpus support.** Seven of the ten written *from expectation* do not. That is a 3-for-3 record against a 3-for-10 one, and §17.8 now makes it a rule.

---

## ⚠ What changed in 7.0 — read if you have seen an earlier version

Version 6.2 and earlier were written **without reading the code** (§17.2). Session 1 read it and produced `docs/RECON.md`. Nine substantive discrepancies were found. This version corrects all of them. If you remember something from an earlier draft, check here first:

| Was | Is | Why |
|---|---|---|
| PyMuPDF for parsing | **`pdfplumber` (MIT) + the existing `pypdf`** | PyMuPDF is AGPL-3.0 and conflicts with this repository's all-rights-reserved posture (§6.1) |
| A new `scripts/document_fetch.py`, extracted from `extract_document_evidence.py` | **No extraction.** Segmentation runs inside the existing pass, via a minimal flag-guarded call site (§6.1, §8.3) | Nothing imports `extract_document_evidence.py`, so the extraction bought nothing and risked a working file |
| "There is no registry" (§3) | **A registry exists** — `scripts/sources/discoverability.py`, 11 umbrella rules, in production (§3) | It already handles the DOE Office of Science case §6.7 called the largest gap |
| DoD BAAs "absent from the catalog entirely" | **31 BAA records are in the catalog today**, including ONR LRBAA, ARL, DARPA, AFOSR (§10 Phase 1) | Grants.gov carries more contract-vehicle BAAs than assumed |
| §7.9 rebuilds a profile representation that does not exist yet | **CV upload, extraction and BM25 scoring already ship**; the browser's ORCID path uses Crossref, not OpenAlex (§7.9) | The work is narrower than described |
| `build_catalog.py --input-dir` reads the three caches | **It reads only the Grants.gov XML ZIP** (§8.4) | The hermetic gate had to be redesigned around the real pipeline |
| Baseline from `evaluate_phase2.py` against the catalog | **A frozen query set compared on result IDs and ranks** (§8.5) | `evaluate_phase2.py` consumes human relevance labels, which are gitignored |
| Five named functions to move out of `extract_document_evidence.py` | **None of them exist** (§8.3) | The real symbols are named in §6.1 |
| Phase 1 step 5, "replace the MIT LICENSE" | **Deleted — already done.** There is no `LICENSE` file; `copyright` carries the all-rights-reserved notice | Completed in commits `d76c2a3`…`8b7ef92` |

`docs/RECON.md` is the evidence for every row. Where this plan and the repository still disagree, the repository wins and this document gets corrected again (§17.2).

**7.1 adds four corrections from measured build data, which 7.0 did not have:**

| Was | Is | Why |
|---|---|---|
| §9.4 runtime gate: "delta under 20%" | **Absolute ceiling: total job runtime under 15 minutes** (§9.4) | Real runs are 2:20–3:30, so 20% is ~34 seconds — while §6.1's own per-document budget permits 15 minutes. The gate forbade what the design allowed |
| Only a per-document time budget | **Adds `SUBTOPIC_RUN_BUDGET_SECONDS = 600`** (§6.1) | 45 documents × 20 s = 15 minutes. The per-document cap alone does not bound the run |
| §9.4 item 4: "no issue was opened or updated" | **"No new issue number appears; #30 updating is expected"** (§9.4, §12) | #30 has 19 comments and updates nightly; #29 is also open. Both predate this work and neither can produce a new number while open |
| Subtopic storage settled in §7.1 | **Open decision with a recommendation** (§13.1) | The catalog is 23.6 MB with `opportunities` at 22.54 MB. In-catalog children change what `record_count` means for five consumers. A sidecar is now the recommendation, conditional on cross-corpus scoring |

7.1 also links the plan to issues **#7**, **#8** and **#9**, which cover overlapping ground (§13).

**8.0 adds §18, the minimum path, after the gate's two CI failures showed the plan was larger than it was verified.** Four changes:

| Was | Is |
|---|---|
| §10's four phases were the unit of work | **§18's seven packages are** (A–G). §10 is retained as background; §15 tracks §18 |
| Everything in §10 was in scope | **Twelve areas are explicitly deferred with the cost of each written down** (§18.2). Deferring `program_taxonomy` means the DOE BES omnibus gets no child records in v1 |
| One numbered step per session (§0.4 rule 5) | **One package per session; one commit per item**, suite between commits. Plus a new rule 5b: no session ends with a dirty tree |
| Backfill drains over a month of nightlies; two-week parallel comparison; one week of observation | **Local backfill in one run; single build comparison; one nightly of observation** |

§17.6 is new and records the two Phase 1 CI failures as standing rules: mark `tools/*.sh` executable at commit time, and verify any new fingerprinted artifact across two delayed builds *and* a green Linux run before committing its baseline. Both failures were invisible on Windows.

---

## ⚠ What changed in 8.1 — the census revision

Package C opened with a corpus census (`docs/CORPUS_CENSUS.md`): 20 notice documents, judged by **reading** rather than by pattern matching. It found that **12 enumerate fundable subdivisions, a family identifies the right list in 1 of those 12, and the segmenter produces subtopics for 0.** This revision is the design response. It changes no code.

| Was | Is | Why |
|---|---|---|
| Ten families, all keyed on an ordinal | **Eleven.** `structural_siblings` (§6.3a) establishes siblinghood from **outline-tree position**, with no counter | Four of the twelve enumerating documents *name* their subdivisions. No tuning of an ordinal regex reaches them |
| §6.4 rule 2: "ordinals monotonically increasing with ≤1 gap", universally | **Conditional on family type.** Ordinal families unchanged; structural families use §6.4a — sibling coherence, span-length distribution, title character, siblings-per-parent | A family with no ordinal cannot satisfy a rule about ordinals, and rule 2 is what proves a set "behaves like an enumeration" |
| §6.7: `DE-FOA-0003600` "does not enumerate research areas… the text genuinely is not there" | **False.** It carries **286 bookmarks** including `2. Basic Energy Sciences (BES) → (a) Materials Chemistry … (c) Synthesis and Processing Science` | Nobody had opened the file. The claim was inferred from the document's reputation as an umbrella |
| §18.2: the `program_taxonomy` deferral costs the DOE BES omnibus all child records — "the most painful single deferral in this table" | **Substantially reduced.** The children, their descriptions, their page anchors and their topic tagging are reachable by Layer A + §6.3a, as ordinary `inline` subtopics. Program managers, stable URLs, deeper taxonomy levels and cross-year identity still need the scraper | The premise the deferral rested on was the §6.7 error above |
| Package D begins with pattern tuning | **Begins with two segmenter fixes** (D0a, D0b), gated before any tuning | Both defects currently present as *pattern* failures. Tuning against that reading would relax rule 2 or widen a family — §18.3's most damaging possible change |
| `dod_topic` — "Typical source: MURI, ONR, ARO" | **Re-verified 2026-08-17 and the claim needs splitting.** MURI is absent from the *stored* corpus — zero matches across all 1,475 catalog records and all 958 evidence entries — but a **live Grants.gov search returns one record, `344592` (`W911NF-23-S-0001`, DEVCOM ARL BAA), which IS in the catalog**. MURI is in Grants.gov's full-text index for that notice and not in our stored fields, whose description is truncated at 2,793 characters. So "absent entirely" was an artifact of what we store. What is confirmed is narrower and still sufficient: **no MURI solicitation is posted on Grants.gov as its own notice**, and there is no MURI document validating this family. The family is validated only by the AFOSR DEPSCoR notice's identical `Topic N:` convention | MURI is SAM.gov-only, and that adapter is deferred (§18.2) |

**Two things this revision deliberately does not do.** It does not cover the AFOSR shape — 39 named portfolios with no outline at all — which needs a different mechanism, sketched as `label_run` in §6.3a and left unbuilt with its risks stated. And it does not calibrate §6.4a's six numeric thresholds, which are reasoned starting points that package D must fit against the census corpus. This document has twice recorded numbers that proved wrong when run (§6.1's library versions, §6.2's font-size branch); these are flagged as unmeasured rather than presented as settled.

---

## ⚠ What changed in 8.2 — the coverage survey

**`docs/CORPUS_CENSUS.md` is a non-representative sample and every rate derived from it is now superseded.** Its 20 documents were chosen to *span shapes*, which is the right way to find mechanisms and the wrong way to size them. `docs/COVERAGE_SURVEY.md` (2026-08-16) supplies the reference figures: attachment metadata for **all 1,635 attachments on all 1,475 catalog records**, a **40-record stratified read sample** disjoint from the census 20, and reachability re-derived against the catalog rather than against the evidence cache.

**Where a rate appears in this document, the survey's figure is the one to quote.** The census remains the reference for *shapes* — which mechanisms exist, and what each miss is caused by — and its per-document judgments were all confirmed. It is not a denominator.

| Was (census, 20 hand-picked) | Is (survey, 1,475 records / 40 stratified) | Why it matters |
|---|---|---|
| 12 of 20 documents enumerate = **60%** | **10 of 40 = 25%**; ~128 records catalog-wide, ~115 of them at three items or more | The 60% was a property of the sample. Every acceptance rate quoted against 12 flatters the design by roughly 2× |
| The one-source assumption is wrong for **60% of the corpus** (12 of 20 carry >1 attachment) | **15.7% of the catalog** carries more than one attachment (232 of 1,475) | The census's records are far heavier than the corpus. Multi-attachment is still necessary — see AFRL PACER below — but it is not a majority case |
| Reachability framed as **246 of 1,016 evidence entries** never attempted | **685 of 1,475 catalog records — 46.4% — are never attempted**, because `source_for_record()` returns `None`. 672 of them have no evidence entry at all | The old denominator counted only records that already had an entry, which is the population that by definition was reached |
| The blind spots are pattern shapes | **The two largest blind spots are fetch plumbing**: 236 unreachable records carry live attachments, and 108 records carry a complete NIH announcement in an `.html` file `select_primary_document` cannot select because it is not a PDF | §18 is re-ordered accordingly: a new **Coverage** package sits between D and E, and all remaining pattern work is demoted below it |
| Genesis Mission's `.xlsx` focus areas imply a spreadsheet class | **Measured zero.** Across 40 stratified records and 131 opened files, **no `.xlsx` and no `.docx` carried a subdivision list.** Genesis is an outlier, not a class | Word and spreadsheet parsing are downgraded to measured-zero in §18.2 — recorded, not deleted |
| Low confidence never publishes, full stop | **Superseded by a review queue** (§13 settled list, new Coverage item). The tiers fitted in D5 suppress a *known-correct* 18-span extraction from AFRL PACER, and raising any of them re-admits the fabrications D5 removed | This is not a threshold problem and no threshold tuning resolves it. It needs a human in the loop |

---

## ⚠ Naming collision — read before writing any code

This repository **already uses the word "topic"** to mean *subject area*: `feeds/topic/catalysis-and-reaction-engineering.xml`, `feeds/topic/carbon-management.xml`, and 25 more. Those values live in the `topic_areas` record field and the `topic` facet, and they are produced by three cooperating mechanisms — `TOPIC_RULES` in `scripts/build_catalog.py:167`, the controlled vocabulary in `scripts/program_areas.py`, and the registry in `scripts/sources/discoverability.py`.

This document uses "topic" throughout to mean something entirely different — a **fundable subdivision of an umbrella solicitation**, like Topic Area 3 of a DOE FOA or Topic 7 of a MURI BAA.

**Resolution: in code, the new concept is called `subtopic`.** The normative mapping:

| Concept | Identifier to write |
|---|---|
| child record id | `subtopic_id` |
| term map | `subtopic_terms` |
| cache file | `data/subtopic_records.json` |
| archive file | `data/subtopic_archive.json` |
| record discriminator | `record_type: "subtopic"` |
| segmentation modules | `scripts/subtopic_patterns.py`, `scripts/subtopic_segmentation.py` |
| build flag | `--enable-subtopics` |
| browser flag | `window.FF_SUBTOPICS_ENABLED` |

As of 7.0 this document uses the `subtopic` forms in code blocks, tables and flag names. Prose still reads "topic" for readability. The rule applies to **identifiers, filenames, flags, and user-facing labels**, and it is not optional — a codebase with two meanings of "topic" will produce wrong wiring.

Note one further collision introduced by the plan itself: §6.3 originally listed a pattern family named `subtopic` (for "Subtopic 3a" headings in SBIR-style calls). That name collided with the record type, so the family was renamed **`sbir_subtopic`**. *(8.5: `sbir_subtopic` is **retired** — zero fires across 170 documents, no validating record in 90 — so the collision is gone rather than managed. Kept here because the hazard it illustrates is real: a grep for `subtopic` returning both a record-type discriminator and a regex family is exactly the wrong-wiring risk this section exists to prevent, and the next family named after a heading word will recreate it.)*

The existing subject-area meaning of "topic" is untouched. Do not rename anything that already exists.

## How to use this document

**Do not read this front to back and start typing.** It is a reference, not a tutorial. Read in this order:

| When | Read | Why |
|---|---|---|
| Before anything | §0 **in full**, then `docs/RECON.md`, then **§18**, then §14 glossary | §0 is a gate. RECON is what the code actually does. §18 is what is being built. §14 defines vocabulary used everywhere else. |
| Deciding whether to proceed | §1–§4 | Problem, scope, and the constraints you cannot violate |
| Starting any package | §8, §9, §17.6, then §15 | Discipline, Actions safety and the cross-platform rules **before** the item list |
| Package B or D | §5, §6 in full | Data model and segmentation. This is the densest material in the document. |
| Package E or F | §7 and §13.1 in full | Every integration point, and the storage decision |
| Stuck or unsure where you are | §15 checklist, then §12 risk register | The checklist is the single source of truth for progress |

**If you only remember three things:** §0.5 (flag off means byte-identical output), §8.1 (additive only, never rewrite), §9.3 (new steps exit 0 on benign outcomes).

**Sections you can skip on a first pass:** §11 (deferred, not being built), §13 (open decisions, resolved separately).

---

## 0. STOP — read this before touching anything

> **This plan is additive. It is not a rewrite.** Every existing file in this repository works today and is generating a live, published catalog on a daily schedule. Nothing in this document authorizes replacing, reformatting, or restructuring an existing file. If you find yourself writing a new version of a file that already exists, you have misread the plan.

### 0.1 The reconnaissance requirement

**There are eleven questions. Not eight, not nine.** Earlier versions gave three different counts in three places (§0.1, §10 Phase 1 step 0, §15). Eleven is correct and the other counts are corrected.

**Status: complete.** Session 1 answered all eleven from the code; the answers, with file and line citations, are in **`docs/RECON.md`**. Read that file before Phase 1. Do not re-derive it, and do not treat this section as still-open work.

The questions are retained below because they are the right questions to re-ask whenever the repository drifts — and because a later session that finds RECON.md stale should re-answer them rather than trust it.

1. Which script writes each file in `data/`? Which of those are added by the workflow's `git add`, and which are build-local?
2. What is the exact step order in `.github/workflows/`, and which steps are permitted to fail?
3. Which nonzero exit paths trigger the owner-issue automation, and what distinguishes "a source degraded" from "the build is broken"?
4. What is the precise top-level shape of `data/opportunities.js` as the browser consumes it? Is there a schema version field?
5. Which functions in `extract_document_evidence.py` are imported by other modules?
6. What is the total workflow runtime today, and what is the job timeout?
7. Does the Pages deploy job depend on the build job succeeding?
8. What exactly does `currentness.py` gate, and who calls it — build time, feed time, browser, or all three?
9. Team matching spans `scripts/faculty_match.py` (build time, producing `data/faculty_matches.js`), `assets/team-matcher.js`, and `assets/team-researchers.js`. Which of these scores, which renders, and does any of it share the BM25 index with `search-retrieval.js`?
10. `assets/profile.js` and `tests/fixtures/browser_cv.txt` indicate CV upload already exists. What does the current CV path do with the text, and how does it combine with OpenAlex data?
11. There are three workflow *files*, but only two are workflows *of this repository* — `.github/workflows/refresh-opportunities.yml` and `.github/workflows/tests.yml`. `docs/weekly-alerts/weekly-digest.yml` sits under `docs/`, where GitHub never looks, and its own header says it belongs in a separate private repository. Which are active, which is the nightly build, and do any share state?

### 0.2 Commands to answer them

These are the commands that actually work on this tree. Two corrections from session 1: the write-site grep must cover `write_text` and `write_catalog`, not just `open(`, or it misses most writers; and a local checkout owned by `BUILTIN\Administrators` makes git refuse the directory unless every command carries `-c safe.directory=…`.

```bash
git clone https://github.com/mporosoff/grants-scraper && cd grants-scraper
git checkout -b topic-layer            # never work on the deploy branch

# If git reports "dubious ownership", prefix every git command:
#   git -c safe.directory="$PWD" <cmd>

# Size and shape of the tree
find . -name '*.py' -not -path './.git/*' | xargs wc -l | sort -n

# Read every line of the workflow. All of it. Twice.
cat .github/workflows/*.yml

# Which script writes which artifact (open() alone misses most of them)
grep -rn "write_catalog\|write_text(\|json.dump(\|open(.*['\"]w['\"]" scripts/ --include=*.py

# What actually gets committed back — one explicit line, not a pattern
grep -rn -A5 "git add" .github/workflows/

# What is allowed to be committed at all. This is a deny-by-default allowlist
# and it is the thing that will silently block a new data/ file.
sed -n '/^\/data\//,/^$/p' .gitignore

# Every nonzero-exit path (these drive the issue automation)
grep -rn "sys.exit\|SystemExit\|return 1\|return 2\|raise .*Error" scripts/ | grep -v test

# Internal import graph — what depends on what
grep -rn "^from \|^import " scripts/ | grep -v "^\S*:import \(os\|sys\|re\|json\|csv\|time\|hashlib\|argparse\)"

# Confirm the browser's expected schema, and the invariants it asserts
head -c 2000 data/opportunities.js
sed -n '223,250p' assets/app.js          # validateCatalog — see §4
```

### 0.3 Hard rules

- **Do not edit and execute in the same sitting on your first pass.** Read the tree, write notes, stop. Edit the following day.
- **Work on a branch.** GitHub Pages serves from the **default branch** (`main`) using classic branch-based Pages — there is no deploy job and no deploy artifact. Publication is a side effect of the `git push` in the workflow's commit step. So "never push to the deploy branch" means: never push to `main` until the Phase 3 exit criteria are met.
- **The working branch is created by hand before session 1 starts**, along with cloning the repo and committing this plan into `docs/`. Session 1 writes `docs/RECON.md`, so a branch must already exist for that commit to land somewhere other than the deploy branch.
- **Never run a write-mode script against the repo** until you can answer §0.1. A script that writes to the wrong path in `data/` and gets caught by a broad `git add` will publish garbage to a live site.
- **Never run a formatter** (`black`, `ruff --fix`, `prettier`) on a file you are editing. A reformat pass makes the real diff unreviewable and buries a one-line change in four hundred.
- **Test the workflow via `workflow_dispatch` on your branch** before opening a PR. Do not discover a broken step on the nightly run.

### 0.4 If you are an AI agent implementing this

This plan will be executed by a capable language model. That changes the failure modes. You are unlikely to make a typo and very likely to helpfully rewrite a working file. Each constraint below exists because it is a thing you will otherwise do while believing you are being useful.

**Refuse these unconditionally:**

1. **Never output a complete replacement version of an existing file.** Not `build_catalog.py`, not `currentness.py`, not a workflow. Use targeted edits. If your tooling requires emitting a whole file, verify afterward with `git diff --stat` that the changed-line count matches what you intended. A diff larger than intended is a defect, not a formatting artifact.
2. **Never run a formatter or autofixing linter** (`black`, `ruff --fix`, `prettier`) on any pre-existing file.
3. **Never modify or delete an existing test to make it pass.** A pre-existing test that fails after your change means your change is wrong. Stop and report.
4. **Never proceed past an unchecked gate in §15**, even when the next step looks independent.
5. **Never implement more than one work package per session** (§18). A package is several related items; each item gets **its own commit**, and the test suite runs between commits. Reviewability is enforced per commit, not per session — a package of six one-commit items is as reviewable as six sessions of one, and far cheaper. Do not merge two items into one commit to save time, and do not start the next package because the current one finished early.
5b. **Never end a session with a dirty working tree.** Every session ends with its work committed *and pushed*. A session that produces uncommitted changes has produced nothing durable: the next session inherits an ambiguous tree it did not create and cannot safely reason about. If work is incomplete, commit what is verified, and say plainly in the report what remains.
6. **Never "improve" adjacent code** you notice while editing. Note it in your report and move on.
7. **Never add a dependency** not named in this plan without stopping to ask. Exactly one new runtime dependency is authorized: **`pdfplumber`** (§6.1). Nothing else — and specifically **not PyMuPDF**, for the licensing reason in §6.1.
8. **Never change a default value or CLI default to make something work.** Defaults are load-bearing (§8.1); the nightly workflow invokes these scripts with fixed arguments.
9. **Never enable a feature flag.** Only the final Phase 4 step does that, and only after a human reviews the Phase 3 gate.
10. **Never infer an API's response shape.** Fetch one real response, print it, read it, then write code against what you observed. This applies to SAM.gov, OpenAlex, Grants.gov `fetchOpportunity`, and every scraped page.
11. **Never add a file under `data/` without adding a `!` line to `.gitignore` in the same commit.** `/data/*` is ignored with a six-entry allowlist. A new cache file is invisible to git, and `git add`-ing it exits non-zero, which aborts the commit step and blocks the nightly publish.

**Anti-confabulation requirements:**

- Never state that a test passed, a build succeeded, or a gate cleared without pasting the actual command output.
- Never assert what a file contains without having read it **in this session**. This plan describes intent; the repository is truth and may have drifted since this was written.
- If a file, function, or field described here does not exist, say so and stop. Do not invent a plausible substitute and proceed.
- If a §0.1 reconnaissance question cannot be answered from the code, say which one and stop.
- The plan is not a substitute for reading the repository. §0.1 is not skippable on the grounds that this document already explains the architecture.

**Report at the end of every session:**

1. Files read this session
2. The exact diff you intended, stated before you made it
3. Commands run, with their real output
4. Which §15 checklist item is now complete
5. **What you did *not* do that a reader might assume you did**

Everything else in this section stands unchanged, and **rules 1, 3 and 10 in particular**: never emit a whole-file replacement, never touch an existing test to make it pass, never infer an API's shape. Loosening the session boundary changes only how much work fits in a sitting, not how carefully any of it is done.

**When blocked, stop and ask.** Do not improvise around a missing credential, an ambiguous schema, a failing gate, or an unexpected API response. An improvised workaround here publishes to a live site that faculty use to make funding decisions.

### 0.5 The golden rule

> **With `--enable-subtopics` off, every generated artifact must be byte-identical to what the current code produces from the same inputs.**

This is not an aspiration; it is a CI gate, defined in §8.4. If the flag is off and any output differs, the change is wrong regardless of how good it looks.

Two clarifications that §8.4 could not previously give, because the gate as originally specified was unbuildable:

- "The same inputs" means the frozen Grants.gov XML archive **plus** the three frozen caches, driven through the whole five-script chain. `build_catalog.py` alone does not read the caches.
- "Byte-identical" is evaluated after normalizing four known-volatile timestamp fields. They change on every run by design and carry no behavioral signal. §8.4 names them exactly.

---

## 1. Problem

Funding Finder's unit of record is the **opportunity**: one number, one synopsis, one deadline, one set of filter fields. For a Broad Agency Announcement, an omnibus NRA, or a multi-topic DOE FOA, the *fundable* unit is the **topic**, and topic text lives inside the attached notice PDF.

- A DoD MURI BAA enters the catalog as one record. Its ~20 research topics, each written by a different program officer, are invisible to BM25.
- An ARPA-E or EERE FOA with four Topic Areas is scored on its cover-page abstract, not on the technical content that determines relevance.
- NASA ROSES program elements carry boilerplate synopses pointing at NSPIRES, so all elements look identical lexically.
- `document_evidence.json` extracts **administrative** facts (page limits, cost share, submission stages). That scope is correct and unchanged; it simply leaves this gap unfilled.

No retrieval tuning fixes this. The discriminating text is not in any indexed field.

### 1.1 How large is this problem, honestly

**Most records in this catalog are not umbrellas, and this section previously implied otherwise by arguing from four vivid examples.** *(Revised 8.5. The figures below supersede the survey's ~128 / 8–9%, which rested on 40 records at 6–10 per stratum; `docs/FAMILY_TAXONOMY.md` adds 50 more and re-derives them on 87.)*

> **23 of 87 stratified-drawn records (26%) carry an enumerated set of fundable subdivisions.**

Extrapolated per stratum — each stratum's hit rate against that stratum's catalog population — that is a point estimate of **~171 umbrella parents catalog-wide, 11.6% of 1,475 records**, with a 95% band of **54–538 records (3.7%–36.5%)**.

**Quote the band, and know which part of it is real.** The width is not evenly distributed; it is almost entirely two strata:

| | Catalog | Read | Hits | Rate | Catalog range |
|---|---|---|---|---|---|
| **A/B/C — records with PDF attachments** | 332 | 62 | 21 | 34% | **38–148** |
| D — any non-PDF attachment | 483 | 12 | 1 | 8% | 7–171 |
| E — zero attachments, agency URL | 660 | 13 | 1 | 8% | 9–220 |

> **The number to plan against is the A/B/C core: ~80 records, band 38–148.** Those three strata are read at 22, 22 and 18 records against populations of 215, 90 and 27 — C is 67% censused. **Strata D and E contribute 91 of the 171 on a single hit each**, against a combined population of 1,143 with 25 reads between them. Any figure that leans on D or E is arithmetic on n=1.

Two corrections to how this was previously stated. **The census 20 must never enter a rate** — it was hand-picked to span shapes and enumerates at 60%; pooling it into the stratified numerators inflates the estimate from 171 to 230, and `docs/FAMILY_TAXONOMY.md` §4.2 records making and catching that exact error. And **a record whose document was never retrieved is not a measured zero** — five survey records previously counted as non-enumerating are reclassified as unknown, because a JavaScript shell or a login wall is evidence of nothing (§18.1's miss taxonomy, category (e)).

**The record count understates the stake, and that is the actual argument for building this.** Umbrellas are the multi-award programs: a single AFRI notice funds 37 program areas, DOE's Office of Science omnibus 70 sub-programs, the Genesis Mission 21 challenge areas across 98 focus areas, AFRL PACER 18 topics. A single-project cooperative agreement — which is what most of the other ~91% of records are — funds one award. So a tenth of the records covers a much larger share of the dollars a PI could actually apply for, and it is precisely the share where one record collapses many distinct opportunities into one lexically flat card.

**What this bounds.** The ceiling on this feature is roughly one record in eight or nine gaining children. It is not a catalog-wide transformation, and a design decision that trades precision on the other seven-eighths for recall on this eighth is a bad trade — which is what §18.3's asymmetry says in different words, now with a denominator behind it.

**The cheapest measurement that would tighten this, and it is one thing:** **read 30 more stratum-D records.** D holds 483 records, has 12 reads, contributes 40 of the point estimate on one observation, spans 7–171 on its own, and produced the corpus's only tabular list. Stratum E is larger but its ceiling is bounded by reachability — 313 of its records have no fetchable source of any kind — so D is where the interval actually closes. This is the successor to the survey's own "sample C and E" recommendation, which C has now discharged.

## 2. Scope

**In scope:** deterministic segmentation of already-fetched notices into topic spans; a topic record type stored, indexed, filtered, fed and rated through the existing pipeline; topic-level change events; coverage adapters for the two largest blind spots; evaluation extension with an auto-derived gold set.

**Out of scope for v1:** any LLM call in the scheduled workflow (see §11); any change to structured Grants.gov fields used by filters or sorting; committing raw notices or full extracted text.

**Non-goals:** replacing `extract_document_evidence.py`; replacing or retiring `scripts/sources/discoverability.py` (see §3); building a second umbrella registry.

## 3. The registry that already exists

Version 6.2 of this document was titled "Why there is no registry" and argued that structural detection makes a curated umbrella list unnecessary. The argument about *segmentation* still holds. The claim that no registry exists was wrong.

**`scripts/sources/discoverability.py` is a hand-maintained umbrella registry, 445 lines, in production.** It calls itself "an evidence registry" in its own docstring. It defines `PROGRAM_RULES` — eleven rules keyed on opportunity number or tightly scoped title/description triggers — each carrying program-area `topics`, searchable `terms`, and `evidence_urls` citing the agency pages that justify them. It is versioned (`DISCOVERABILITY_REGISTRY_VERSION`), runs inside `sources/merge.integrate`, and reverses its own prior contribution before re-evaluating so a rule can be corrected or retired without leaving residue. Eleven records in the committed catalog carry `discoverability_augmented: true`.

Its coverage today: DOE Office of Science umbrella (`DE-FOA-0003600`), DOE Basic Energy Sciences, DOE EERE, ONR Long Range BAA (`N0001425SB001`), DEVCOM ARL foundational BAA (`W911NF-23-S-0001`), NASA SpaceTech REDDI (`NNH26ZTR001N`), and five NOAA BAAs.

A second, complementary mechanism also exists: **`scripts/program_areas.py`** is a 24-entry controlled vocabulary of `(label, topics, pattern)` triples, and `extract_program_areas()` in `extract_document_evidence.py` scans the *actual notice text* for them, attaching a label only where it genuinely appears, with a page or section citation retained in the evidence cache. 359 records currently carry `document_program_areas`.

**So the honest framing of this project is not "there is no registry." It is:**

> Discoverability of umbrella FOAs is already solved at the *record* level. What is missing is **granularity** — a child record per fundable subdivision, with its own text, its own page anchor, its own retrieval identity, and its own deadline. A search for "electrocatalysis" already finds `DE-FOA-0003600`. It cannot tell you *which of the seventeen things inside it* you should read.

That is a smaller, sharper claim than v6.2 made, and it is the one the evidence supports.

**What this means for the design.** Structural segmentation still needs no list — a document's own headings reveal whether it is an umbrella. Three or more sibling headings matching one pattern family, with monotonic numbering, is the detector, and the same pass produces the child spans. New programs are detected on first fetch, and unfamiliar formats degrade to zero subtopics rather than going stale. None of that changes. What changes is that **the segmenter is a third mechanism alongside two that already work, not a replacement for a gap**, and §6.7 must be read with that in mind.

**One narrow addition, and it is not curation.** `data/expected_solicitations.json` (~10 lines) exists solely for regression detection, because "source returns plausible but incomplete results" is the one failure the existing health gates cannot catch. Details in §7.4.

## 4. Inherited constraints

| Constraint | Implication |
|---|---|
| Raw notices and full extracted text never committed | Topic full text is ephemeral. Only a bounded summary plus a term-frequency map is persisted (§5.2). |
| Machine-extracted dates/amounts never replace structured filter fields | Topic deadlines are advisory display facts unless the parent has no structured deadline. |
| Only short cited facts published, each with an anchor | Every topic carries `page_start`/`page_end` resolving to the exact PDF page. |
| Sources fail closed or retain filtered last-known-good; degradation opens a GitHub issue | Segmentation failure degrades to "parent unchanged," never to a partial catalog. |
| Ordinary search makes zero AI calls | Unchanged. Topic retrieval is pure BM25. |
| Document fetches bounded per run (`--max-documents 45`) | Segmentation adds **no steady-state fetches** — it runs inside the existing pass, on bytes that pass has already downloaded. Backfill is the exception and is bounded; see below and §8.3. |
| Repository state is committed to git each build | Output must be diff-stable (§5.4) or the repo grows without bound. |
| `/data/*` is gitignored with a six-entry `!` allowlist | A new `data/` file needs a `.gitignore` line **and** a `git add` line, in the same commit (§9.3). |
| The browser hard-asserts catalog invariants before rendering | `assets/app.js` `validateCatalog` throws unless `schema_version === 3` **exactly**, `opportunities.length === record_count`, `record_count >= 1000`, and `search_index.document_count === record_count`. See below. |

**The "no new fetches" claim needs qualifying — v6.2 stated it too strongly.** `extract_document_evidence.py` has *three* independent skip gates, and only the third leaves usable bytes in memory:

1. **Not due.** `due_for_check()` excludes a record from the candidate list entirely when its source signature is unchanged and it was checked within `--recheck-days`. No request is made.
2. **304 Not Modified.** When the conditional request returns 304, `build_document_entry` is never called and the response body is empty. No bytes.
3. **Hash unchanged.** Bytes were downloaded, but the SHA-256 matches the previous entry, so `build_document_entry` deep-copies the prior entry and returns **without parsing containers at all**.

So on a steady-state night, almost every document takes path 1 or 2, and segmentation would see nothing. That is fine once subtopics exist — there is nothing to recompute — but it means **subtopics would never backfill onto the ~1,400 documents already in the cache**. §8.3 specifies the backfill trigger that fixes this, and it is the single most important implementation detail in this document.

**The `validateCatalog` invariants are the hardest constraint here.** Child records cannot be added to `opportunities` incrementally or partially: the moment one is appended, `record_count` and `search_index.document_count` must both move with it, in the same write. `postings` and `document_lengths` are positional arrays indexed by an integer document id, so children must be **appended**, never interleaved, or every existing document id shifts.

## 5. Data model

### 5.1 Topic record

```json
{
  "record_type": "subtopic",
  "subtopic_id": "361526:ta-2",
  "opportunity_id": "361526:ta-2",
  "parent_id": "361526",
  "parent_opportunity_number": "DE-FOA-0003612",
  "subtopic_code": "Topic Area 2",
  "subtopic_code_norm": "ta-2",
  "subtopic_ordinal": 2,
  "title": "Electrochemical Conversion of Captured CO2",
  "title_fingerprint": "3f9a1c02",
  "summary": "<= 600 chars, sentence-boundary truncated",
  "term_display": {"electrocataly": "electrocatalysis", "faradaic": "Faradaic"},
  "subtopic_source": "inline",          // provenance ladder, see below
  "recurrence_group": "muri:interfacial-charge-transfer",
  "status": "posted",
  "topic_areas": ["Catalysis and reaction engineering", "Carbon management"],
  "program_area_labels": ["catalysis", "carbon management"],
  "page_start": 14,
  "page_end": 19,
  "source_document_url": "https://...",
  "source_document_hash": "sha256:...",
  "segmentation_method": "outline",
  "confidence": "high",
  "own_deadline": null,
  "own_deadline_is_advisory": true,
  "first_seen": "2026-08-20",
  "last_verified": "2026-08-20",
  "extractor_version": "1.0.0+pdfplumber0.11.4+pypdf5.1.0"
}
```

#### `subtopic_source` — the provenance ladder

**Rewritten in 8.7 from a two-value field (`inline` / `referenced`) into a
four-value ladder, after an outside audit found this plan over-weighting generic
document inference relative to hierarchies agencies already publish.** The audit
is substantially accepted; §6.7 and §18.1 carry the structural consequences.

The ladder is ordered by **how much this project had to guess**:

| Value | The agency has… | Example |
|---|---|---|
| **`native`** | published an explicit child list, table or API — the subdivisions are *data*, not prose | NSPIRES ROSES Table 3; a program-element API; a solicitation table with one row per topic |
| **`referenced`** | published a program page that establishes the parent→child relationship, off the solicitation | DOE Office of Science program pages under `science.osti.gov`; ONR department pages |
| **`inline`** | enumerated the children **in** the solicitation, in a form a family recognises | `Topic Area 1 / 1a / 1b`; `(a) Materials Chemistry` under a bookmark tree |
| **`inferred`** | enumerated nothing recognisable, and generic structural inference had to establish the set | `structural_siblings` over an outline; a bare-numbered run; a label run |

**The distinction that matters is not format, it is who asserted the
relationship.** A bookmark tree is a *layout* artifact that this project reads as
a hierarchy; a ROSES table is the agency stating its own hierarchy. Both may
produce identical-looking records, and they do not deserve identical trust.

#### Confidence derives from provenance first, method second

Confidence was previously a property of the **segmentation method** alone —
Layer A `high`, `outline_structural` `medium`, Layer D `low`. That is now the
second term, not the first:

| Provenance | Ceiling | Floor | Rationale |
|---|---|---|---|
| `native` | `high` | `high` | There is nothing to be uncertain about. The agency published the list; a parser either read it or failed loudly |
| `referenced` | `high` | `medium` | The relationship is asserted by the agency; the risk is staleness and mis-linkage, not invention. `medium` when the parent match is heuristic |
| `inline` | `high` | `low` | Method decides within the band, exactly as today |
| `inferred` | **`medium`** | `low` | **Never `high`.** §6.3a already caps `structural_siblings` at `medium`; this generalises that cap to the whole provenance class rather than to one family |

**Two rules follow, and they are the point of the ladder:**

1. **A higher rung is never downgraded by a lower rung's evidence.** If a `native`
   source lists twelve elements and inference over the PDF finds nine, the answer
   is twelve and the discrepancy is a **canary failure** (§7.4), not a merge.
2. **`_demote()`'s secondary-attachment cap applies to `inline` and `inferred`
   only.** A `native` list does not become less trustworthy for having been found
   in the second attachment fetched.

#### Interaction with §6.4b's span-level judgment

§6.4b moved the unit of judgment from the set to the span. The ladder decides
**which spans are judged at all**:

| Provenance | Set acceptance (§6.4 1–8) | Span classifier (Cov4) | Review queue |
|---|---|---|---|
| `native` | **not applicable** — there is no set to accept, only a list to read | **bypassed** | bypassed |
| `referenced` | not applicable | **bypassed** | bypassed |
| `inline` | applies | applies | `medium`/`low` survivors |
| `inferred` | applies | **applies — this is what Cov4 is for** | `medium`/`low` survivors |

**Cov4 narrows to `inferred` and `inline`, and its purpose sharpens.** The
classifier exists to answer *"did generic inference find the fundable list or the
announcement's furniture?"* — a question that does not arise when an agency
published the list itself. Running a semantic filter over a ROSES table would be
spending money and adding a failure mode to second-guess an authoritative source.
See §18.1 Cov4.

**This does not weaken §18.3's asymmetry.** Nothing bypasses the *acceptance* of
a source; it bypasses the *inference-checking* of one. A `native` parser that
returns zero rows on an HTTP 200 is a canary failure and publishes nothing
(§7.4) — which is the same fail-closed outcome by a different route.

> **⚠ `subtopic_terms` is NOT a field on this record — corrected 2026-08-17.** Earlier versions carried the term map inline, and it measured **60.3% of every serialized record**. It now folds into the sidecar's own search index, exactly as parent term frequencies already fold into `opportunities.js`'s `search_index.postings` rather than sitting on each opportunity. The record above is the **display payload**, and it measures median 942 B / max 1,218 B against §12's 2 KB ceiling. `term_display` **stays on the record** — it is what renders match chips as `electrocatalysis` instead of the stem `electrocataly` (§7.6), so it is display data, not retrieval data. See §5.2 for the index shape and §13's settled sidecar decision.

**⚠ Identity keys on the parent's catalog `opportunity_id`, never on its opportunity number.** Earlier versions of this section built `subtopic_id` as `<parent_opportunity_number>:<code_norm>`, and that is unbuildable for part of the catalog. Measured 2026-08-16: **20 of 1,475 records carry a null `opportunity_number`** — every one of them from the VPR email digest (`vpr-email:` namespace), and the list is not marginal:

```
DEFENSE ADVANCED RESEARCH PROJECTS AGENCY (DARPA)     Schmidt Sciences
NSF Computer and Information Science and Engineering  Sloan Research Fellowships
NSF Computational and Data-Enabled Science            Simons Foundation collaborations
NSF Mathematical Foundations of AI                    ACS Petroleum Research Fund
NSF Plasma Physics · NSF Division of Physics          Camille & Henry Dreyfus Foundation
```

Several are exactly the umbrella shape this project targets, and a DARPA or NSF-core parent is a *better* segmentation candidate than average, not a worse one.

**What the current implementation actually does, measured rather than assumed.** `scripts/subtopic_records.py` reads `opportunity_number or opportunity_id or ""`, so it does **not** emit `None:ta-2` and does **not** collide — an earlier draft of this section claimed both and was wrong. The fallback makes it safe today and wrong in two quieter ways:

- **The key is mixed.** 1,455 records key on the opportunity number and 20 key on the id. If a VPR-digest record later gains an opportunity number — which is exactly what happens when a program is subsequently posted to Grants.gov — every child's `subtopic_id` changes from `vpr-email:…:ta-2` to `DE-FOA-…:ta-2`, and §5.3's carried-forward identity breaks precisely when the parent becomes more important, not less.
- **The display field is polluted.** Those 20 records get `parent_opportunity_number` set to `vpr-email:vpr-a63ebf17…`, so a field that exists to show a PI a recognizable solicitation number instead shows an internal digest id.

Every record has an `opportunity_id`; the browser already derives identity from `record.opportunity_id || record.opportunity_number` (`assets/app.js` `recordId`), and `extract_document_evidence` keys its cache the same way. So:

| Field | Role |
|---|---|
| `parent_id` | **the parent's `opportunity_id`. The identity key.** |
| `subtopic_id` | `<parent_id>:<subtopic_code_norm>` |
| `opportunity_id` | equal to `subtopic_id`, so the browser can find the child at all |
| `parent_opportunity_number` | **display only.** Retained because a card reading *DE-FOA-0003612 · Topic Area 2* is what a PI recognizes — but nothing keys on it, and it may be null |

This is settled now rather than in package E, because E is where identity gets written into storage and a key change after a backfill means rewriting every record's `subtopic_id` and losing the first-seen dates §5.3 carries forward.

> **⚠ `scripts/subtopic_records.py` still implements the superseded scheme** — `subtopic_id_for(parent_opportunity_number, code_norm)`, with the fallback described above, and `parent_opportunity_number` populated from the same fallback. **Changing it is the first item of package E**, before any cache is written. It is free to change today because no backfill has run and `data/subtopic_records.json` does not exist; it is expensive after. Two assertions in `tests/test_subtopic_records.py` pin the old shape (`DE-FOA-0003600:ta-1`) and will need updating with it — that is a specified design change, not a test bent to fit code.

Four further corrections to the v6.2 shape, all from reading the real catalog:

- **`opportunity_id` is required, not optional.** The browser derives every record's identity from `record.opportunity_id || record.opportunity_number` (`assets/app.js` `recordId`), and `extract_document_evidence` keys its cache the same way. A child with neither is invisible to half the system. Setting it equal to `subtopic_id` is the least surprising choice.
- **`program_area_tags` was invented.** No such field exists, and the example values matched neither real vocabulary. There are two actual vocabularies and they are different things: `topic_areas` holds **Topic-facet display strings** like `"Catalysis and reaction engineering"` (this is the field that feeds facets and `feeds/topic/*.xml`), while `program_areas.py` labels are lowercase shorthand like `"catalysis"`, `"carbon management"`. A child record must populate `topic_areas` to appear under a facet at all. `co2_utilization` exists in neither vocabulary and has been removed.
- **`status` uses the catalog's own vocabulary**, not a private one. `currentness.record_is_current` only accepts `posted` or `forecasted` as live; anything else is excluded. A child emitting `"open"` would be filtered out of every feed and every browser view as `invalid_status`. Subtopic lifecycle is expressed through §7.2's derived states layered *on top of* a valid base status, not by inventing new values for this field.
- **`extractor_version` names the real toolchain** (§6.1).

Fields inherited from the parent and therefore **not** stored on the child are listed in §5.5. The child must still carry enough to satisfy `validateCatalog` and the render path: `title`, `agency`, `status`, `source`, `source_type` at minimum.

### 5.2 Full text without storing full text

Indexing only a 600-character summary discards most of the retrieval gain. Committing the span violates the privacy boundary. Resolution: **persist the BM25 posting data, not the prose.**

v6.2 imported three names here and **two of them do not exist**. `stem` is not a function — stemming is folded into `normalize_token`, which `tokenize` already calls. And the constant is `STOP_WORDS`, not `STOPWORDS`. `tokenize` also already drops stopwords and tokens of length ≤ 1, so the filtering v6.2 added on top was redundant. The correct version is shorter:

```python
# scripts/subtopic_segmentation.py
from collections import Counter

from scripts.build_catalog import tokenize   # already normalizes, stems, drops stopwords

def build_term_map(span_text: str, max_terms: int = 400) -> dict[str, int]:
    """Stemmed term frequencies in the catalog's own vector space.
    Supports full-strength BM25; not reconstructable into readable prose.
    Capped to bound file size."""
    return dict(Counter(tokenize(span_text)).most_common(max_terms))
```

Using `tokenize` unmodified is not merely convenient — it is **required for correctness**. `search_index.postings` keys are the output of this exact function. A term map built by any other tokenizer produces keys that do not collide with the index, and the subtopic simply never matches. Do not reimplement it, do not "improve" it, and do not add a length filter: `co2` is three characters and is exactly the kind of term this feature exists to retrieve.

The span itself is discarded when the process exits. This mirrors what `build_catalog.py` already publishes for opportunity records, so the boundary holds without a new policy.

**Where the map lives — settled 2026-08-17.** `build_term_map` is unchanged and `MAX_TERMS` stays at **400** (§13, settled). What changed is the destination: the map is **not** stored on each subtopic record. It is inverted into the sidecar's own index, mirroring the shape `opportunities.js` already uses — a `records` array plus a sibling `search_index`, never per-record postings:

```jsonc
// data/subtopics.js  (lazily loaded; §13 settled decision)
globalThis.FF_SUBTOPICS = {
  "schema_version": 1,
  "records": [ /* §5.1 display payloads: median 942 B, max 1,218 B */ ],
  "search_index": {
    "algorithm": "bm25",
    "document_count": 223,
    "average_document_length": 191.7,
    "document_lengths": [ /* positional, indexed into records */ ],
    "postings": {"electrocataly": [0, 14, 7, 3], "co2": [0, 22]}
  }
}
```

Three reasons this is the right shape, and one hazard it inherits:

- **It is the same structure the browser already knows how to score.** `assets/search-retrieval.js` reads `postings`, `document_lengths`, `average_document_length` and `document_count`; a second index of that shape needs no new scorer, only the cross-corpus normalization E1 must prototype (§13.1).
- **It is much smaller than storing the map per record.** A term appearing in forty spans is one posting list, not forty dictionary entries — and the tokenizer contract in this section is what makes those keys collide correctly in the first place.
- **It keeps §12's ceiling meaningful.** The ceiling bounds what a card costs; retrieval data measured in a separate index against a separate budget is the only way that number stays honest.
- **Hazard, inherited from `build_catalog`:** `postings` and `document_lengths` are **positional** into `records`. Anything that sorts, filters or dedups `records` between index build and serialization silently corrupts every posting. Build and serialize in one write, and never re-order afterwards (§4 records the same trap for the parent catalog).

### 5.3 Stable identity across amendments

**This is the subtle one.** If `subtopic_id` keys on ordinal, an amendment that *inserts* Topic 3 renumbers everything below it, and the diff reports one addition plus seventeen spurious amendments.

Fix: key on normalized code, and match old→new by title similarity **before** falling back to code.

```python
import hashlib, re, statistics
from difflib import SequenceMatcher

def normalize_code(code: str) -> str:
    """'Topic Area 2' -> 'ta-2'; stable across capitalization and punctuation."""
    s = code.lower()
    s = re.sub(r'\barea of interest\b', 'aoi', s)
    words = re.findall(r'[a-z]+|\d+', s)
    initials = ''.join(w[0] for w in words if not w.isdigit())
    nums = '-'.join(w for w in words if w.isdigit())
    return f"{initials}-{nums}".strip('-')

def title_fingerprint(title: str) -> str:
    norm = re.sub(r'[^a-z0-9 ]+', '', title.lower())
    norm = ' '.join(sorted(norm.split()))          # word-order insensitive
    return hashlib.blake2s(norm.encode(), digest_size=4).hexdigest()

def match_subtopics(old: list[dict], new: list[dict]) -> list[tuple]:
    """Returns (old_or_None, new_or_None) pairs. Title match wins over code
    match so insertions and renumbering do not produce false amendments."""
    pairs, rem_old, rem_new = [], list(old), list(new)

    # Pass 1: exact title fingerprint
    for n in list(rem_new):
        hit = next((o for o in rem_old
                    if o['title_fingerprint'] == n['title_fingerprint']), None)
        if hit:
            pairs.append((hit, n)); rem_old.remove(hit); rem_new.remove(n)

    # Pass 2: fuzzy title >= 0.85
    for n in list(rem_new):
        best, score = None, 0.0
        for o in rem_old:
            s = SequenceMatcher(None, o['title'].lower(), n['title'].lower()).ratio()
            if s > score:
                best, score = o, s
        if best and score >= 0.85:
            pairs.append((best, n)); rem_old.remove(best); rem_new.remove(n)

    # Pass 3: normalized code
    for n in list(rem_new):
        hit = next((o for o in rem_old
                    if o['subtopic_code_norm'] == n['subtopic_code_norm']), None)
        if hit:
            pairs.append((hit, n)); rem_old.remove(hit); rem_new.remove(n)

    pairs += [(o, None) for o in rem_old]     # removed
    pairs += [(None, n) for n in rem_new]     # added
    return pairs
```

`subtopic_id` is assigned once at first sight and **carried forward through matching**, so identity survives renumbering, retitling and repagination.

**The key inside `subtopic_id` is the parent's `opportunity_id`, not its opportunity number (§5.1).** Twenty catalog records — DARPA, four NSF core programs, Schmidt Sciences, Sloan, Simons, ACS PRF and others from the VPR digest — have a null `opportunity_number`, so a number-keyed identity is `None:ta-2` for all of them at once: every such parent's children collide with every other's, and the collision is silent. `normalize_code` and `title_fingerprint` above are unaffected — they operate on the code and title, which exist regardless — and only the composition of `subtopic_id` changes:

```python
subtopic_id = f"{parent['opportunity_id']}:{normalize_code(code)}"
```

`match_subtopics` itself needs no change: it pairs on `title_fingerprint`, then fuzzy title, then `subtopic_code_norm`, none of which involve the parent key. What changes is only what the carried-forward `subtopic_id` is made of. Keep `parent_opportunity_number` on the record for display (§5.1), and never match on it.

### 5.4 Diff stability

`data/subtopic_records.json` is committed every build. Unstable serialization would balloon the repository.

```python
json.dump(payload, f, sort_keys=True, indent=1, ensure_ascii=False)
f.write("\n")
```

Records sorted by `(parent_opportunity_number, subtopic_ordinal)`. Volatile fields such as `last_verified` are updated **only when something else changed** — otherwise the timestamp alone rewrites the file daily.

**Two mechanical prerequisites, both easy to forget and both fatal:**

1. Add `!/data/subtopic_records.json` and `!/data/subtopic_archive.json` to `.gitignore`, inside the `/data/*` allowlist block. Without this the files are untracked and the cache rebuilds from nothing every night, making every subtopic look new (§9.3).
2. Add both paths to the workflow's `git add` line.

Note that this file's serialization style deliberately differs from every other file in `data/`. The existing caches are written minified (`separators=(",", ":")`) via `write_catalog` / `write_cache`. This one is indented and key-sorted because it is the only committed artifact whose *line-level* diff a human will read when triaging a phantom-amendment flood. The size cost is acceptable; a minified 20,000-record file produces a one-line diff that tells you nothing.

### 5.5 Field inheritance

| Field | Source |
|---|---|
| agency, sub-agency, instrument, eligibility, applicant type | inherited from parent, never re-derived |
| award floor / ceiling / total funding | inherited from parent |
| deadline used for filtering and sorting | **parent's structured deadline** |
| `own_deadline` | advisory display only; set only if one unambiguous date occurs in the span and does not contradict the parent |
| status | derived per §7.2 |

## 6. Deterministic segmentation

### 6.1 The parsing toolchain — settled

**Decision: `pdfplumber` (MIT) plus the existing `pypdf`. Not PyMuPDF.**

PyMuPDF is AGPL-3.0. This repository ships an all-rights-reserved notice (`copyright`) and the owner may license it commercially. Linking an AGPL library into the build pipeline would either force the whole work under AGPL terms or require a paid Artifex commercial licence. Neither is acceptable for a departmental tool that may be licensed onward, and the licence question is not one an implementing session should relitigate. **Do not substitute PyMuPDF, `fitz`, or any AGPL fork, whatever the performance argument.**

The two libraries divide cleanly along what each layer needs:

| Need | Library | API |
|---|---|---|
| Bookmark / outline tree (Layer A) | **`pypdf`** — already a dependency | `reader.outline`, `reader.get_destination_page_number(dest)` |
| Per-page text (Layers B and D, summaries) | **`pypdf`** — already used | `page.extract_text()` |
| Per-character font name and size (Layer C) | **`pdfplumber`** — new | `page.chars` → dicts carrying `fontname`, `size`, `text`, `x0`, `top` — all five confirmed present in 0.11.10 (B0) |
| Encryption handling | **`pypdf`** — already used | `reader.is_encrypted` / `reader.decrypt("")` |

`pdfplumber` is MIT-licensed and built on `pdfminer.six` (also MIT). It is the one new runtime dependency this plan authorizes.

**Why this works where v6.2's design would not.** v6.2's Layer C tested `span['size'] >= 1.15 * median or span['flags'] & (1 << 4)` — a PyMuPDF span dict with a bitfield whose bit 4 means bold. `pdfplumber` has no `flags` bitfield. It gives you the **font name**, which is strictly better for this purpose: bold is detected from the name itself, and the same string also distinguishes the heading face from the body face even when both are the same point size. §6.2 Layer C is rewritten against `chars`.

**Confirmed by measurement (B0), and more load-bearing than expected.** Real font names carry the weight exactly as claimed — `TimesNewRomanPS-BoldMT`, `BCDFEE+TimesNewRomanPS-BoldMT`, `HGOLHU+Calibri-Bold`, `Arial-BoldMT`. One example form above is wrong: the real ARPA-E name is `Calibri-Bold` with a hyphen, not `Calibri,Bold` with a comma; both match the regex. And the "even when both are the same point size" clause turns out to be the *whole* mechanism rather than a bonus — see §6.2, where the size branch admits 0.0% of lines on the AFOSR BAA.

**Determinism.** Pin both exactly, and pin `pdfminer.six` too — it is a transitive dependency of `pdfplumber` and it is the component that actually decides character positions and font names. An unpinned minor bump shifts extraction, which shifts spans, which surfaces as a flood of phantom `subtopic_amended` events.

```
# requirements.txt — additions and one tightening (as committed, A2)
pypdf==6.16.1                 # was: pypdf>=5.0.0,<7
pdfplumber==0.11.10
pdfminer.six==20260107        # transitive, pinned because it drives extraction
```

**All three version numbers in versions 7.0–8.0 of this section were wrong, and one of them was dangerous.** They were written from library knowledge rather than resolved against PyPI. Corrected against `pip index versions` on 2026-08-16:

| 8.0 said | Actual | Consequence of trusting 8.0 |
|---|---|---|
| `pdfplumber==0.11.4` | **0.11.10** | Stale by six patch releases |
| `pdfminer.six==20240706` | **20260107** | Stale, *and* unsatisfiable — `pdfplumber` 0.11.10 hard-pins `pdfminer.six==20260107`, so the two lines together do not resolve |
| `pypdf==5.1.0` | **6.16.1** | **A two-major-version downgrade.** `>=5.0.0,<7` resolves to 6.16.1 today, so "pinning" to 5.1.0 would have silently changed the library already parsing every notice in production, under a commit message claiming to change nothing |

The rule this yields, which is more useful than any specific number: **pin the version the existing constraint already resolves to.** A pin is meant to freeze behavior, not change it. Confirm with `pip install --dry-run --ignore-installed --report` against the *current* constraint before writing the pin, and treat any version that differs from the resolved one as a behavior-affecting change needing its own justification.

Tightening `pypdf` from a range to a pin is still a change to an existing line, so it is its own commit with the existing suite run before and after.

`pdfplumber` 0.11.10 pulls `pypdfium2`, `Pillow` and `cryptography` transitively. Checked at implementation time: BSD-3-Clause/Apache-2.0, MIT-CMU, and Apache-2.0/BSD-3-Clause respectively. No AGPL enters the closure, so §6.1's licensing constraint holds through the transitive graph and not merely at the top level.

The resolved versions go into `extractor_version` (`"1.0.0+pdfplumber0.11.10+pypdf6.16.1"`) so that when a phantom-amendment flood does happen, the cause is visible in the diff rather than requiring an investigation.

**Cost, stated honestly.** `pdfplumber` is slower than `pypdf`, materially so on large documents, because `page.chars` materializes every character as a dict. On a 250-page BAA that is millions of dicts. Four mitigations, all mandatory:

1. **Layer C only runs when Layer A fails.** Most DOE, ARPA-E and NSF notices carry bookmarks and resolve on `pypdf` alone, never opening `pdfplumber` at all.
2. **Page cap.** `extract_document_evidence.py` already caps at `MAX_PDF_PAGES = 250`; Layer C additionally caps at the first `SUBTOPIC_CHAR_SCAN_PAGES = 120` pages, since an enumerated topic list that begins after page 120 of a notice is not a real pattern.
3. **Per-document wall-clock budget.** A hard `SUBTOPIC_TIME_BUDGET_SECONDS = 20` per document, checked between pages. On exceeding it, abandon segmentation for that document, record `reason: "time_budget"`, and return zero subtopics.
4. **Per-run wall-clock budget.** A hard `SUBTOPIC_RUN_BUDGET_SECONDS = 600` across the whole step, checked before each document is segmented. On exceeding it, stop segmenting entirely for the rest of the run, record `reason: "run_budget"` for every document not reached, and let `extract_document_evidence` finish its own work normally.

**The per-document budget alone does not bound the run, and this is not a small gap.** `--max-documents 45` × 20 s = **15 minutes** of segmentation in the worst case — on a job whose total runtime today is 2:20–3:30. A per-document cap stops one pathological PDF; it does nothing about forty-five merely-slow ones, which is the realistic failure mode when a new agency template defeats Layer A and pushes everything to Layer C. Both budgets are required, and the run budget is the one that actually protects the job.

`SUBTOPIC_RUN_BUDGET_SECONDS = 600` is deliberately set below the 15-minute ceiling in §9.4: 3:30 of existing pipeline plus 10:00 of segmentation is 13:30, leaving headroom for a slow runner without breaching the gate. Exhausting the run budget is a **normal, non-fatal outcome** — it exits 0, records the reason, and the un-segmented documents are picked up on subsequent nights through the ordinary backfill path (§8.3). It is not an error and must not raise.

Track `run_budget` separately from `time_budget` in the diagnostics histogram. The first means the run is systematically too slow and the pattern set needs work; the second means one document is pathological. Conflating them hides the difference.

**There is no `scripts/document_fetch.py`.** v6.2 proposed extracting a shared fetch layer out of `extract_document_evidence.py`, on the theory that other modules import from it and need protecting. **Nothing imports it** — the only importers anywhere are two test files. The extraction bought nothing, and it modified a 1,928-line working file that produces live published data. It has been dropped entirely. Segmentation runs inside the existing pass instead (§6.1a, §8.3).

The real symbols, for anyone looking for v6.2's invented names:

| v6.2 called it | It is actually |
|---|---|
| `fetch_document` | `download_document(url, headers=None, *, timeout=30, maximum_bytes=…, session=requests)` |
| `FetchedDocument` | no such type; `build_document_entry` returns a `(dict, bool)` tuple |
| `Unchanged` | no such type; a `previous_hash == digest` early return |
| `_sha256_bytes` | an inline `hashlib.sha256(content).hexdigest()` |
| `_extract_page_texts` | `extract_pdf_pages` / `extract_html_sections`, dispatched by `extract_containers` |

`extract_containers(content, content_type, name, final_url)` is the function segmentation actually consumes. It returns `(containers, extraction)` where each container is `{"page": int|None, "section": str|None, "anchor": str|None, "text": str}` — already the page-indexed text Layer B and Layer D need, already cleaned, already capped at `MAX_PAGE_CHARS = 30_000` per page. Layer A and Layer C need the raw bytes as well, which are in scope at the same call site.

### 6.1a Where segmentation runs — settled

**Decision: inside `extract_document_evidence.py`'s existing pass, at one minimal flag-guarded call site. Not as a separate `scripts/extract_subtopics.py` script.**

The reason is the three skip gates in §4. A separate script running after `extract_document_evidence` would find no bytes in memory and would have to re-download every document it wanted to segment — doubling the fetch budget, doubling the runtime, and violating the inherited constraint that document fetches are bounded per run. Running inside the existing pass is the only design where "segmentation adds no fetches" is true.

The segmentation *logic* still lives entirely in new files. What `extract_document_evidence.py` receives is a call site of roughly this size:

```python
# scripts/extract_document_evidence.py — inside build_document_entry,
# after containers/extraction are computed and facts are extracted.
subtopics = []
if enable_subtopics:                       # keyword arg, defaults False
    from scripts import subtopic_segmentation
    subtopics = subtopic_segmentation.segment_document(
        record, content, containers, document, fetched_at,
    )
```

plus the matching `"subtopics": subtopics` key in the returned entry dict, and the backfill condition in §8.3. That is the entire footprint in the existing file. Everything else — patterns, layers, acceptance, derived fields, term maps, identity matching — is in `scripts/subtopic_patterns.py` and `scripts/subtopic_segmentation.py`.

**Resolving the §8.1 tension explicitly.** §8.1 says "new behavior lives in new files; existing files receive insertions only." This decision does not violate that rule, but it does sit close enough to it that the reasoning must be written down rather than assumed:

- The *behavior* is in new files. `extract_document_evidence.py` gains a guarded call and a dict key, not logic. If you find yourself writing a regex, a heuristic, or a loop over pages inside `extract_document_evidence.py`, you have violated the rule and should move it.
- The insertion is **flag-guarded at the innermost point**, so with the flag off the added code evaluates one `if` per document and does nothing else. §0.5 byte-identity is preserved by construction, not by testing.
- The import is **function-local**, so with the flag off `subtopic_segmentation` is never imported, `pdfplumber` is never loaded, and a broken new module cannot break the nightly build by import error alone.
- The alternative — a separate script — is not more additive. It would require its own fetch layer, its own change detection, and its own cache lifecycle, all duplicating logic that already exists and all of it new surface area that can fail. "More new files" and "less risk" are not the same thing, and here they point in opposite directions.

The §8.1 rule table is amended accordingly.

### 6.2 Four layers, first success wins

The layer *order* and the acceptance discipline are unchanged from v6.2. The implementations are rewritten against `pypdf` and `pdfplumber`.

```python
# scripts/subtopic_segmentation.py
LAYERS = (_layer_outline, _layer_toc, _layer_headings, _layer_numbered)

def segment_document(record, content, containers, document, fetched_at):
    """Entry point called from extract_document_evidence.build_document_entry.

    `containers` is what extract_containers() already produced: page-indexed,
    cleaned text. `content` is the raw bytes, needed only by Layers A and C.
    """
    if document_is_html(document):
        return _segment_html(containers, ...)      # §6.6
    if not any(c["text"].strip() for c in containers):
        return SegmentationResult.empty("no_extractable_text")   # scanned; no OCR in v1
    deadline = monotonic() + SUBTOPIC_TIME_BUDGET_SECONDS
    for layer in LAYERS:
        if monotonic() > deadline:
            return SegmentationResult.empty("time_budget")
        result = layer(content, containers, deadline)
        if result and accepts(result):
            return result
    return SegmentationResult.empty("no_layer_accepted")
```

**Layer A — outline tree** (`confidence: high`, `pypdf`). Most DOE, ARPA-E and NSF notices carry bookmarks and resolve here, at negligible cost.

`pypdf` exposes the outline as a **nested list**, not the flat `(level, title, page)` triples v6.2 assumed. Nesting depth *is* the level, so flatten it first:

```python
from pypdf import PdfReader
from pypdf.generic import Destination

def _flatten_outline(items, level=0, reader=None, out=None):
    """pypdf's reader.outline is a nested list: a Destination, or a list of
    children belonging to the Destination that preceded it."""
    out = [] if out is None else out
    for item in items:
        if isinstance(item, list):
            _flatten_outline(item, level + 1, reader, out)
        elif isinstance(item, Destination):
            try:
                page = reader.get_destination_page_number(item) + 1   # 1-based
            except Exception:                    # broken/external destination
                continue
            out.append((level, str(item.title or "").strip(), page))
    return out

def _layer_outline(content, containers, deadline):
    reader = PdfReader(io.BytesIO(content), strict=False)
    try:
        entries = _flatten_outline(reader.outline, reader=reader)
    except Exception:                            # no outline, or malformed
        return None
    for level in sorted({lvl for lvl, _, _ in entries}):
        sibs = [(t, p) for lvl, t, p in entries if lvl == level]
        fam, hits = best_family(t for t, _ in sibs)
        if fam and len(hits) >= 3:
            return build_spans(containers, hits, method="outline", confidence="high")
    return None
```

**Corrected against measurement (B0, 2026-08-16 — full output in `docs/PDF_API_NOTES.md`).** The nesting walk above is right and was confirmed on a 119-destination ARPA-E NOFO. The exception handling is wrong:

**`get_destination_page_number` does not raise. It returns `None`.** Its signature is `-> Optional[int]` and its docstring says "The page number or None if page is not found". The sketch survives only because `None + 1` raises `TypeError`, which the bare `except Exception` then catches — it is correct by accident, via an arithmetic error on the next token, and the comment describes a mechanism that does not exist. Write it explicitly:

```python
page_index = reader.get_destination_page_number(item)
if page_index is None:        # not found; pypdf returns None, it does not raise
    continue
page = page_index + 1         # pypdf is 0-based; this repository is 1-based
```

Keep a `try` around it as well, but for the *reader*, not for this call.

Four further specifics, three measured and one still true as written:

- **0-based page numbers**, confirmed — every other page reference in this repository is 1-based.
- **No bookmarks yields an empty list, not an error**, confirmed on both DoD BAAs. A normal outcome, not a failure.
- **A destination whose page is a bare integer is silently dropped.** `NumberObject(3)` returns `None` even when page 3 exists, because the lookup resolves indirect references and does not treat a literal integer as an index. A notice writing `/Dest [3 /Fit]` loses that entry with no error. None of six sampled documents do this; Layer A under-reports rather than fails if one does.
- **A cross-document page reference returns a plausible wrong number**, matching on object number without checking ownership. Layer A cannot reach this — its destinations always come from the reader it queries — but it is a trap for anyone later constructing `Destination` objects by hand.

Not every outline nests: `W81XWH-22-DHAPP.pdf` has 11 destinations, all at level 0, so the per-level loop gets exactly one attempt rather than several. Such a document is also **ineligible for the structural family**, which excludes depth 0 outright (§6.3a).

**Layer A gains a second pass, and the walk gains a field (§6.3a).** After the ordinal loop above has declined at every level, Layer A tries `structural_siblings`. That family reasons about *siblinghood*, not equal depth, so the walk must carry **each node's parent** alongside its level — two nodes at level 2 under different level-1 parents are not siblings, and the per-level grouping above would wrongly treat them as one set. The tuple becomes `(level, parent_key, title, page)`; nothing else about the walk changes, and the ordinal pass ignores the new field.

Order is fixed: **ordinal families first, structural only if all of them decline.** A label match is self-validating and a structural match is not, so the weaker signal never pre-empts the stronger one.

**Layer B — table of contents** (`high`, text only). Find TOC pages in the already-extracted `containers`, then locate each title verbatim in the body; the TOC's own page number is never trusted as a boundary. Unchanged from v6.2 and needs no new library.

```python
DOT_LEADER = re.compile(r'^(?P<title>.+?)\.{3,}\s*(?P<page>\d+)\s*$')
# scan first max(3, 15% of pages); require >= 5 matching lines on a single page
```

**Layer C — body heading sweep** (`medium`, `pdfplumber`). This is the only layer that opens `pdfplumber`, and it runs only after A and B have both declined.

**Corrected (B0, 2026-08-16).** This paragraph used to open "Most DoD BAAs are produced without bookmarks and resolve here." The first half is confirmed — both DoD BAAs sampled carry **zero** bookmarks, so they do reach Layer C. The second half is **not supported**: neither produced a single match from any of the ten §6.3 families, so Layer C correctly declined and the documents yielded zero subtopics. See §6.3's coverage note and `docs/PDF_API_NOTES.md` §4.

`pdfplumber` gives per-character dicts, so reassemble lines before matching. Bold is read from `fontname` — PDF font names carry the weight in the subset name, e.g. `ABCDEF+Arial-BoldMT`, `TimesNewRomanPS-BoldMT`, `Calibri,Bold`:

```python
import pdfplumber, statistics

BOLD_RE = re.compile(r'bold|black|heavy|semibold|demi', re.IGNORECASE)

def _page_lines(page, round_to=1):
    """Group page.chars into lines by rounded vertical position.
    Returns [{"text", "size", "bold"}] in reading order."""
    rows = {}
    for ch in page.chars:
        rows.setdefault(round(ch["top"] / round_to) * round_to, []).append(ch)
    lines = []
    for top in sorted(rows):
        chars = sorted(rows[top], key=lambda c: c["x0"])
        text = "".join(c["text"] for c in chars).strip()
        if not text:
            continue
        sizes = [c["size"] for c in chars]
        lines.append({
            "text": text,
            "size": statistics.median(sizes),
            "bold": sum(bool(BOLD_RE.search(c.get("fontname") or "")) for c in chars)
                    > len(chars) / 2,
        })
    return lines

def _layer_headings(content, containers, deadline):
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        pages = pdf.pages[:SUBTOPIC_CHAR_SCAN_PAGES]
        all_lines, body_sizes = [], []
        for index, page in enumerate(pages, start=1):
            if monotonic() > deadline:
                return None                       # budget spent; caller records the reason
            lines = _page_lines(page)
            body_sizes.extend(line["size"] for line in lines)
            all_lines.extend((index, line) for line in lines)
            page.flush_cache()                    # release per-page char dicts
    if not body_sizes:
        return None
    median = statistics.median(body_sizes)
    cands = [
        (page_number, line) for page_number, line in all_lines
        if (line["size"] >= 1.15 * median or line["bold"]) and len(line["text"]) <= 200
    ]
    fam, hits = best_family(line["text"] for _, line in cands)
    if fam and len(hits) >= 3:
        return build_spans(containers, hits, method="heading_font", confidence="medium")
    return None
```

`page.flush_cache()` is not optional on a 120-page document — without it `pdfplumber` retains every page's char list for the lifetime of the `with` block, and a large BAA will use well over a gigabyte on a runner that has seven. Confirmed present on `pdfplumber.page.Page` in 0.11.10.

**The size half of the candidate test does almost nothing, measured (B0).** Over the first 60 pages of each document, by branch:

| Document | Lines | `size >= 1.15 × median` | `bold` | Either |
|---|---|---|---|---|
| ONR LRBAA | 2,315 | **4 (0.2%)** | 134 (5.8%) | 135 (5.8%) |
| AFOSR Open BAA | 2,434 | **0 (0.0%)** | 145 (6.0%) | 145 (6.0%) |
| ARPA-E SCALEUP | 2,849 | 120 (4.2%) | 545 (19.1%) | 545 (19.1%) |

On both DoD BAAs — the corpus this layer exists for — the size branch contributes nothing: AFOSR has **three distinct font sizes in the whole document** and sets its headings at body size in bold. On the ARPA-E NOFO every size-qualifying line is also bold, so the union equals the bold set in all three. **Layer C is, on this evidence, a bold-detection layer.** Keep the size term — it costs nothing and will earn its place on notices that use display type — but do not rely on it, and do not describe the signal as size-or-weight when weight is doing all of the work.

`BOLD_RE` itself is confirmed against real font names, including the six-letter subset prefixes (`BCDFEE+TimesNewRomanPS-BoldMT`, `HGOLHU+Calibri-Bold`). Two wrinkles: it also matches bold-italic, which is correct for heading detection; and subset prefixes are **not stable within a single document** (the same face appears as both `BCDEEE+` and `BCDHEE+`), so any future logic counting distinct fonts must strip `^[A-Z]{6}\+` first.

Bold alone also over-admits — real AFOSR candidates include bolded body prose such as `'Hyperlinks have been embedded within this document…'`. The §6.4 acceptance rules, not the candidate test, are what keep this layer honest.

**Cost, measured:** 60 pages take 5.8–6.9 s with `flush_cache()` per page, so 120 pages is roughly **12–14 s** against the 20 s per-document budget. That is under it with ~1.5× margin, not 10×. Layer C will legitimately exhaust `time_budget` on the largest documents on a slow runner, which is a designed non-fatal outcome — read `time_budget` counts in the package D histogram with that in mind rather than as evidence of pathology.

Note the method name changed from v6.2's `heading_regex` to **`heading_font`**, because the signal is typographic and the stored `segmentation_method` should say so. Layer D is the regex-only one.

**Layer D — plain numbered fallback** (`low`, text only). Regex over `containers` text, no typographic signal. **Low confidence never publishes** — settled, see §13. It is written to the cache with `confidence: "low"` for diagnostics and routed to the review queue, and the merge in §7.1 filters it out. A wrong subtopic is worse than a missing one: it puts a plausible-looking card with a page anchor in front of a PI, and the cost of them writing a proposal against a topic that does not exist dwarfs the cost of them not seeing it.

### 6.3 The form taxonomy — induced, not assumed

**Rewritten in 8.5 from `docs/FAMILY_TAXONOMY.md`. Every earlier version of this section listed families this project expected to find; this one lists forms the corpus was measured to contain.** That distinction is the point of the rewrite, and §17.8 makes it a standing rule.

`scripts/subtopic_patterns.py` holds the implementation. This section is now organized by **form** — a mechanical description of how a document delimits its subdivisions — with the families that serve each form named underneath. Forms are ordered by **measured catalog coverage**, which is also the order §18.1 works them in.

#### The six forms

Measured over **90 read records** — the census 20, the survey 40, and the taxonomy 50. Coverage estimates come only from the 87 stratified-drawn records; the census contributes form discovery and never a rate (§1.1).

| Form | Records (of 90) | Catalog est. | How items are delimited | Served by |
|---|---|---|---|---|
| **F4** named or bulleted, **no counter at all** | **9** | **~73** — but ~22 excluding a single stratum-E observation | a bullet glyph, or nothing: position or a repeated label is the only delimiter | **nothing.** `label_run` (§6.3a) deferred; `structural_siblings` only when bookmarked |
| **F2** labelled ordinal `<Label> N:` | **9** | ~17 | a label word from a known vocabulary plus a counter | **the six surviving families below** |
| **F1** bare numbered `N.` / `N)` / `N -` | **8** | ~31 (Wilson 47–210 on the pooled rate) | a bare counter plus a named title, no label word | **nothing** — see §18.3 for why, and for the exit criteria |
| **F3** coded named list | **4** | ~6 | a repeated non-standard code prefix: `PA 1:`, `53-24-01 -`, `A.1.a.`, `Topic A2` | **nothing** |
| **F6** lettered `a.` / `(a)` / `a)` | **4** | ~4 | a letter counter plus a named title | `structural_siblings`, and **only** when bookmarked *and* ≥3 siblings |
| **F5** **tabular** | **1** | ~40, **n=1** | items are **rows of a table**, keyed by a topic-number column | **nothing, and no *layer*** — `extract_containers` has no table path |

> **Forms with a family: ~17 records. Forms without: ~154.** The families reach **10% of the enumerating population.**

**F1 is the most stably measured uncovered form** — 6 independent stratified observations across three strata, against F4's 7 (one of which carries 51 of its 73 estimate) and F5's 1. It is also the form §18.3 forbids. That is not a contradiction, and §18.3 now says why.

**F5 is a presentation variant, not a population.** `363530` (AFOSR DEPSCoR-CB) prints 12 topics as table rows with `SECTION` / `SERVICE` / `TOPIC AREA` / `PROGRAM OFFICER` columns. They are *the same 12 topics* as `363526` (DEPSCoR-RC), which prints them as headings and segments correctly. One program office, two notices, two forms, one reachable. Do not size F5 from its ~40 — size it from the fact that an already-validated list is invisible because of how it was laid out.

#### The six families that fire, all serving F2

Each: id, regex with an ordinal capture group, and **the record that validates it**. A family with no validating record does not belong in this table — that is §17.8.

| Family | Pattern (illustrative) | Validated by |
|---|---|---|
| `topic_area` | `Topic\s+Area\s+(\d{1,2}[a-z]?)` | `363302` (NETL, `Topic Area 1 / 1a / 1b / 2 / 3`), `363065`, `358100` |
| `dod_topic` | `Topic\s+(\d{1,2})\s*[:.–—]` | `363526` (AFOSR DEPSCoR, Topic 1–12), `349554` (AFRL PACER, Topic 1–18) |
| `component` | `Component\s+(\d{1,2})\s*[:.–—]` | `360333` (CDC-GHC, Component 1–5) — **the only live one; `360339` left the catalog** |
| `focus_area` | `Focus\s+Area\s+(\d{1,2}[a-z]?)` | `362859` (DARPA MMoMA, Focus Area 1–4) |
| `technical_category` | `Category\s+(\d{1,2})\s*[:–—]` | `356623` (ARPA-E SCALEUP, `CATEGORY 1:`–`CATEGORY 7:`) |
| `thrust` | `Thrust\s+(?:Area\s+)?(\d{1,2})` | `356612` (DTRA) — **fires, but at the wrong granularity; see below** |

**Three of these six were written from measurement, in D3, from documents the census had already read: `component`, `focus_area`, `technical_category`. All three have corpus support.** That is the evidence behind §17.8.

**`thrust` is kept on notice, not on merit.** On `356612` it matches the *container* `Thrust Area 1` — one item — while the fundable list is `Topic A1` through `Topic A7` beneath it. A family that matches the umbrella instead of its topics segments one span where seven exist. §18.1 carries the repair as a work item; until then this row is a known-wrong-granularity match, not a validation.

**`dod_topic` is validated by convention and contradicted by an ordinal.** MURI still appears **zero times** across the corpus — §18.2's SAM.gov deferral arriving, not a sampling gap — so the family has no MURI document and cannot have one until that adapter ships. Its two validating records use `Topic N:`. **`356612` shows the limit: its topics are `Topic A2`, a letter ordinal the `(\d{1,2})` group cannot match at all.** §18.1 carries that repair too.

#### The seven families retired in 8.5

**Retired with their evidence, because a family that never fires is invisible to every acceptance-rate metric this project has and therefore accumulates silently.** Run over all 170 documents of the taxonomy sample, cross-referenced against the census 20 and survey 40:

| Retired | Why |
|---|---|
| `technical_area` | **0 fires in 170 documents.** No validating record in 90 |
| `sbir_subtopic` | **0 fires in 170 documents.** No validating record in 90 |
| `nsf_track` | **0 fires in 170 documents**, including four NSF records read end to end at full solicitation text |
| `research_thrust` | **0 fires in 170 documents.** No validating record in 90 |
| `priority_research` | **0 fires in 170 documents.** `332894`'s heading is *Priority Research Thrusts*, which the `Direction\|Opportunity\|PRD` pattern does not match — the one document that looked like its case is not its case |
| `area_of_interest` | **1 fire, 0 real lists.** Its only match is `Area of Interest 4: Process Diversification…` on NETL's *aggregating* agency page, belonging to a different opportunity entirely (§6.3b) |
| `roses_element` | **6 fires, 0 real lists.** Matches `A.1 BACKGROUND AND OBJECTIVES` across five revisions of one DOE Idaho FOA and `C.3 Budget Documents` in a DRL instructions file. This is the census's `332894` false positive reproduced on entirely new documents, and there is **no document in 90 records it correctly matches** |

**Five never fired; two produced only false positives.** The last two matter most: they are not neutral dead weight, they are net-negative. `roses_element` exists for NASA ROSES, every NASA record in the corpus is unreachable — NSPIRES refuses the client, reproduced on three records across two sessions — and until §18.2's NSPIRES deferral is resolved the family can only misfire on DoD and DOE lettered-decimal section numbering, which is near-universal.

**Retiring is not deleting the knowledge.** If NSPIRES ships, `roses_element` has a documented shape and a reason to return — with a validating ROSES document, per §17.8. The same applies to the other six.

`best_family()` is unchanged: it returns the family with the most matches, requiring a ≥2× margin over the runner-up so mixed-family segmentation is rejected rather than guessed.

The family formerly called `subtopic` in v6.2 was **`sbir_subtopic`**, now retired. The naming-collision hazard it created — a grep for `subtopic` returning both a record-type discriminator and a regex family — retires with it.

**⚠ Coverage, measured before any tuning (B0, 2026-08-16).** All ten families *as they then stood* were run over the full text of three real notices — the ONR Long Range BAA, the AFOSR Open BAA and the ARPA-E SCALEUP NOFO. **Zero matches, in all three, from every family.** *(8.5: B0's three-document zero is the first observation of what the taxonomy sample later measured at scale — 8 of 13 families never firing across 170 documents. It was read at the time as evidence the families were appropriately narrow. It was equally evidence that seven of them were inert, and nobody asked.)*

That is the correct outcome, not a bug: none of the three contains an enumerated topic list. What they contain is administrative NOFO section structure — `I.`/`II.`, `A.`/`B.`, `1.`/`2.` — at 47, 19 and 74 decimal-numbered lines respectively. The ONR LRBAA is structurally the **same shape as the DOE BES omnibus** in §6.7: an umbrella that points outward to research areas rather than enumerating them. §6.7 identifies that shape only for DOE. It is at least as common in DoD long-range BAAs, and that materially changes what package D should expect.

**Two consequences, pointing in opposite directions, and both matter.**

First, `no_layer_accepted` will dominate the histogram for the BAA corpus, and package D's per-agency-family acceptance rates should be set from measurement rather than hope. §18.1 package D already requires `no_layer_accepted` to be separated from genuine failures; this is the evidence for why that separation is load-bearing rather than bookkeeping.

Second — and this is the one that will be tempting to get wrong — **do not add a generic numbered-section family to make these documents produce something.** On these three files that would manufacture subtopics titled *Federal Agency Name*, *Funding Opportunity Title* and *Announcement Type* from 47 and 74 matching lines. That is exactly the change §18.3 names as "the single most damaging change anyone could make to this design." The families are narrow deliberately. Three documents yielding zero subtopics is the fail-closed asymmetry working.

*(8.5: this paragraph stands, and it is now half the picture. The same bare-numbered form — F1 — is carried by 8 of 90 read records and is the most stably measured **uncovered** form in the corpus. Both facts are true: the form is common and the form is not a signal. **§18.3 now states the conditions under which F1 becomes admissible rather than leaving a flat prohibition**, and the condition is a classifier in front of it, not a better regex.)*

**Tune against the corpus that already exists.** The catalog carries 31 records whose title or agency names a BAA, including DARPA office-wide BAAs (`HR001126S0003`, `S0010`, `S0011`, `S0013`, `S0016`), the ONR Long Range BAA (`N0001425SB001`), the DEVCOM ARL foundational BAA (`W911NF-23-S-0001`), AFOSR (`NOFOAFRLAFOSR20260001`), NRL (`N00173-24-S-BA01`) and ERDC (`W912HZ26S0001`). Their notice PDFs are reachable through the existing document-evidence path today. This is the development corpus, and it does not depend on SAM.gov existing (§10 Phase 1).

### 6.3b The aggregating agency page — a false-positive surface with no rule against it

**Found in 8.5, and it belongs to Cov1 rather than to any pattern.** `363594`'s agency URL is NETL's funding landing page. `topic_area` fires on it **ten times** and `area_of_interest` once, and **every one of those topics belongs to a different opportunity** (`DE-FOA-0003634`, `DE-FOA-0003627`). The page aggregates many FOAs.

This is a distinct failure mode from announcement furniture, and **nothing in §6.4 or §6.4a can see it**, because the set is not malformed. The ordinals count up. The titles are real research areas. The span lengths are comparable. The process-vocabulary rate is near zero. Every acceptance rule passes, and the result attaches another record's topic list to this one.

**Cov1's `subtopic_only_primary` feeds exactly these pages to the segmenter** — that is its purpose, for the 221 records declined only for want of gap-fill. So widening reachability widened this surface, and the classifier is currently the only thing in the design that catches it: asked about `363594`, the model refused it for precisely the right reason — *"the Topic Area lists visible … belong to other, unrelated funding opportunities."*

Two candidate mitigations, neither specified nor measured here:

- **Require the opportunity's own number or title to appear near the candidate set** on any document reached through `subtopic_agency_notice`. Cheap, and it fails on agency pages that never restate the FOA number.
- **Treat agency-page sources as classifier-mandatory** — never publishable on structural grounds alone, whatever the tier.

Carried as a Cov4 gate item in §18.1, because it is an argument about what the classifier is *for* rather than about a threshold.

### 6.3a `structural_siblings` — the eleventh family, and the only non-ordinal one

**Family id: `structural_siblings`. Family type: `structural`. Source of evidence: the PDF outline tree. Layer A only. Confidence ceiling: `medium`.**

Every family in §6.3 recognizes a *label*. This one recognizes a *position*: a set of outline nodes that are siblings under one parent is a candidate topic list, whatever those nodes are called. That is what reaches `DE-FOA-0003600`, whose subdivisions are named `(a) Materials Chemistry`, `(b) Biomolecular Materials`, `(c) Synthesis and Processing Science` — real fundable programs carrying no ordinal a regex could capture.

#### The sibling criterion

Layer A already flattens `reader.outline` into `(level, title, page)`. The structural family needs one more thing from that walk: **each node's parent**, so siblinghood is a fact rather than an inference from equal depth. Two nodes at level 2 under different level-1 parents are not siblings, and the current per-level grouping in §6.2 would wrongly treat them as such.

A **depth** `d` qualifies when all of the following hold:

1. **`d ≥ 1`.** Depth 0 is never eligible. The top level of a federal NOFO outline is the standard announcement skeleton, and it is administrative by construction.
2. **Per-parent completeness.** For each parent that contributes candidates at depth `d`, *all* of that parent's children at `d` are taken. Cherry-picking a subset is forbidden — a partial sibling list is a segmentation that silently drops topics.
3. **Cardinality.** The union across qualifying parents holds 3–60 nodes, matching §6.4 rules 1 and 5.
4. **Parent admissibility.** Every contributing parent's own title must fail the administrative lexicon (below). A parent whose title matches `research|program description|topics?|areas? of interest|portfolio|technical|scope` is a positive signal but is **not** required — requiring it would exclude taxonomies that label the level implicitly.

**Depth selection: take the deepest qualifying depth, and take it across all parents.** This matters more than it looks. `DE-FOA-0003600` has both `A. Purpose → {1. ASCR, 2. BES, …}` (the program offices) and `2. BES → {(a) Materials Chemistry, …}` (the programs inside them). The useful granularity for a catalysis group is the deeper one, and taking it across every parent yields the whole taxonomy — ASCR's children *and* BES's children *and* the rest — rather than one office's. A design that stopped at the first qualifying parent would return four subtopics from a 224-page notice and look like it had worked.

#### Administrative-section exclusion

**The primary exclusion is structural, not lexical**, because a blocklist is the weakest instrument available here and should carry as little load as possible.

- **Position.** Depth 0 is excluded outright (criterion 1). The federal NOFO skeleton — Overview, Eligibility, Application Contents, Submission, Review, Award Notices, Post-Award, Other — is prescribed at the top level by the OMB standard announcement structure, so excluding depth 0 removes most of it without naming a single word.
- **Parent title.** A list of children under `IV. Submission Requirements` is never a topic list (criterion 4).

The lexical test is a **set-level veto**, deliberately not a per-item filter:

> If **≥25%** of sibling titles contain a term from the administrative lexicon, reject the entire set.

Lexicon: `eligibility`, `submission`, `application`, `award`, `review`, `reporting`, `contact`, `deadline`, `format`, `certification`, `appendix`, `definitions`, `acronym`, `checklist`, `registration`, `cost share`, `budget`, `provisions`, `clauses`.

Set-level is the right shape because one `Budget` sibling among fifteen research programs is normal and should not veto a good list, while four of fifteen means the whole set is the admin skeleton. A per-item filter would quietly delete the odd one out and let the rest through — which is the failure mode that produces a plausible, wrong list.

#### The false-positive risk, stated plainly

**This family is materially weaker than the ten ordinal ones, and pretending otherwise would be the mistake.** `Topic Area 3` is self-validating: that phrase is used for topic areas and essentially nothing else, so a match is almost certainly a real topic. Structure carries no such guarantee. **An outline node with twelve children has twelve children, whatever they are** — a definitions glossary, a list of required forms, and a list of research programs are structurally identical.

Three consequences follow, and all three are requirements rather than suggestions:

1. **Confidence is capped at `medium`.** `structural_siblings` never emits `high`, even from Layer A, which otherwise yields `high`. It is a weaker signal and the stored `confidence` must say so.
2. **The acceptance rules do the work the regex used to do.** §6.4's rule 2 replacement (§6.4a) is not a formality for this family — it is the *only* thing standing between an outline tree and a page of invented subtopics.
3. **Ordinal families always win.** The structural family is tried **only** when no ordinal family has been accepted at any level of the outline. It never competes in `best_family()`'s ≥2× margin test, because that test arbitrates between label families; a structural match is a fallback, not a rival.

#### Interaction with Layers A–D

| Layer | Structural family runs? | Why |
|---|---|---|
| **A — outline** | **Yes**, after the ordinal pass declines at every level | This is the only layer with a real parent/child tree, which is the entire evidence base |
| **B — table of contents** | **No, in v1** | A TOC is a flattened rendering of the outline, and depth would have to be recovered from leading whitespace in extracted text. B0 measured that whitespace in `pdfminer` output is unreliable enough that Layer C's line assembly needs positional rounding; inferring hierarchy from it would manufacture sibling sets. Recorded as a known gap, not an oversight |
| **C — heading font** | **No, in v1** | Bold/not-bold is one bit and cannot establish a hierarchy. B0 measured the size branch admitting **0.0%** of lines on the AFOSR BAA and 0.2% on ONR, so there is not enough typographic level signal on the documents that reach Layer C to build a tree from |
| **D — plain numbered** | **No, by definition** | Layer D is the ordinal-regex fallback and stays exactly that |

So `structural_siblings` runs in exactly one place. That restriction is deliberate and is what keeps its false-positive surface bounded.

#### What this does *not* solve: AFOSR

The census names two documents. This family reaches one of them.

**`DE-FOA-0003600` has 286 bookmarks and is reached.** **`FA955026S0001`, the AFOSR Open BAA, has zero bookmarks** — measured in B0 — so there is no outline tree, and a family defined by outline position cannot touch it. Its 39 portfolios are marked by a *repeated structural label*: each begins `Program Description:` and carries a program-manager mailbox.

That is a different mechanism and needs its own family, provisionally `label_run`: a run of ≥3 body lines matching one repeated `^<Label>:` form, where the label is discovered from the document rather than listed in advance, with the preceding line taken as the title. It is **not added here**, for a reason worth stating: the discovered-label approach has a false-positive profile nobody has measured, and `Program Description:`, `Basic Research Objectives:` and `Contact Information:` all repeat 39 times in the same document — so the mechanism must also choose *which* repeated label delimits topics. That is package D work with its own validation, and it should not ride in on this section's coattings.

**Until then, AFOSR-shaped notices — named subdivisions with no outline — remain uncovered, and that is roughly a third of the enumerating documents in the census.**

**⚠ 8.5 — how much of the corpus this family can see, measured.** `structural_siblings` is the only mechanism serving F6 and hierarchical F1, and it is entirely dependent on the outline tree. In the taxonomy sample, **71 of 129 PDFs carry no bookmarks at all — 55%.** Every one of those documents is invisible to this family regardless of what form its list takes, and the corpus's two most striking F1 umbrellas are both in that group: `330175` (Air Force Academy, 24 research centres) and `355150` (Army Applications Lab, 16 technology areas) have zero bookmarks each.

So the coverage claim for `structural_siblings` should be read as *"the qualifying half of the corpus that carries an outline"*, not as *"documents with a sibling set."* That halves its reach before any threshold is applied, and it is the strongest single argument for `label_run` and F1 — those are the mechanisms that work on the other 55%.

### 6.4 Acceptance rules

Accept only if **all** hold. Any failure → zero topics, parent untouched, reason logged.

1. ≥3 candidates from a single family
2. **Ordinal families only:** ordinals monotonically increasing with ≤1 gap. **Structural families:** replaced by §6.4a
3. Each span ≥200 and ≤40,000 characters
4. Spans non-overlapping, page ranges contiguous
5. Total candidates ≤60 (guards against reference lists and form indexes)
6. Candidates not confined to the detected TOC page range
7. **Ordinal families only:** ≥60% of candidates carry a non-empty title after the code. **Structural families:** there is no code, so this is subsumed by §6.4a's title tests
8. **Announcement-furniture veto, every family.** The share of *tokens* across the candidate titles drawn from `PROCESS_VOCABULARY` is below `PROCESS_TOKEN_MAX = 0.07`. Fitted in D5, not reasoned — see §6.4a. *(This rule shipped in D5 and was missing from this list until 8.3; the code is `subtopic_segmentation.py` and it is authoritative — §17.2.)*

> **Rules 1–8 judge a set. They are all-or-nothing by construction, and §6.4b changes what that verdict governs:** a set that passes is admitted, and its *members* are then filtered individually. Read §6.4b before treating this list as the last word on what publishes.

### 6.4a Rule 2 for structural families

Rule 2 exists to answer one question: *does this set behave like an enumeration?* For an ordinal family the counter answers it directly. A structural family has no counter, so the question has to be answered from the shape of the set itself. All four tests must hold.

**2a — Sibling coherence.** Every candidate's parent is admissible (§6.3a criterion 4), and for each contributing parent the full child list is present. A set that is missing siblings is rejected rather than trimmed.

**2b — Span-length distribution.** Across the candidate spans, the coefficient of variation (σ/μ) is **≤ 1.5**, and no single span exceeds **40%** of the union's total characters.

This is the quantitative replacement for "the ordinals count up," and it is the strongest of the four. A real topic list is made of comparable things: twelve research programs get roughly comparable prose. An administrative skeleton is wildly uneven — a three-line *Agency Contact Information* sits beside a forty-page *Application Contents and Format*. That unevenness is measurable without knowing a single word of the content, which is exactly what is wanted from a language-independent structural test.

**2c — Title character.** All three hold:
- **≥60%** of titles carry **≥2 content tokens** after `build_catalog.tokenize` (which already drops stopwords). `Materials Chemistry` passes; `Purpose` does not.
- **Type/token ratio ≥ 0.6** across the concatenated title set. Administrative outlines repeat their vocabulary relentlessly — *Application* Contents, *Application* Review, *Application* Submission — while a list of research programs mostly does not reuse words. This catches skeletons that survive the lexicon because they use unlisted synonyms.
- Median title length **12–120 characters**. Below 12 is a label; above 120 is a sentence, and a sentence is prose that happens to be bookmarked.

**2d — Siblings per parent.** Each contributing parent has **3–60** children at the chosen depth, and the union is 3–60. A parent with two children is not an enumeration; a parent with 200 is a glossary.

> **These six thresholds — 1.5, 40%, 60%, 2 tokens, 0.6, 12–120 — are stated to be calibrated, not because they have been measured.** They are reasoned starting points, and this document has now twice recorded numbers that turned out wrong when run (§6.1's versions, §6.2's size branch). Package D must fit them against the census corpus in `docs/CORPUS_CENSUS.md` and record the fitted values here, with the false-positive count on the eight documents that enumerate nothing as the headline number. A structural family that admits any of those eight is worse than no structural family at all.

**Fitted in D1 and D5, and then found to be the wrong instrument — read this before touching a threshold again.** D1 fitted three of the six; D5 fitted a process-vocabulary veto at 0.07 (§6.4 rule 8), demoted `heading_font` to `low` on 0/1 measured precision, and added a dominant-code-form trim. That work took fabricated publishable records from 54 to 0 and cost nothing legitimate, and it remains correct. What it cannot do is separate the last case:

> **AFRL PACER (`349554`) yields 18 correct topics — `Topic 1 – Aero-Structures` through `Topic 18` — and every one of them is suppressed.** It resolves at Layer D (`numbered`), which is `low`; it would be won from a secondary attachment, which §6.6 caps at `low`; and `low` never publishes. The extraction is right, was read span by span, and is invisible.

**No setting of these thresholds resolves that.** Raising Layer D's tier, or lifting the secondary-attachment cap, re-admits precisely the fabrications D5 removed — `1. NOFO Summary`, `a. Narrative Section I: Project Description` — because those come from the *same* tiers. The tiers are not mis-fitted; they are being asked to carry a decision they cannot make, which is *"is this particular list the fundable one?"* That question has one reliable answer — **and as of 8.3 there are two evaluators that give it, a human and a classifier measured at 100% on both axes (§11). See §6.4b, the Coverage package's Cov4 (§18.1), and §13's revised settled decision.**

**⚠ 8.5 — two acceptance rules now have named corpus counter-examples, and neither is a threshold to tune.**

**Rule 2's monotonic-ordinal test rejects a real list whose counter restarts.** `330175` (Air Force Academy) enumerates 24 research centres and departments in **three groups, each restarting at `1.`** — `1. Aeronautics` … `15. Center for Space Situational Awareness Research`, then `1. Reserved` … `3. Eisenhower Center`, then `1. Department of Behavioral Sciences and Leadership` onward. Read as one sequence the ordinals run 1→15, 1→3, 1→6, which rule 2 refuses outright. This is not the TOC-duplication artifact D0a/D0b fixed; the document genuinely restarts its counter per section, and any F1 mechanism has to model grouped sequences rather than one monotonic run.

**Rule 1's three-item floor is the binding constraint on F6, not the pattern.** Three of the four F6 records in 90 are **two-item lists** — `332127` and `334079` (EDA regional programmes) and `346815` (`a. Public Works`, `b. Economic Adjustment Assistance`) — and `structural_siblings` already sees all three, bookmarked, and is refused by §6.4a rule 2d's 3–60 cardinality window and §6.4 rule 1 together. **So F6 pattern work buys nothing.** Lowering the floor to two remains **rejected** — `docs/COVERAGE_SURVEY.md` measured it as the cheapest and most dangerous change available, admitting every two-item administrative pair in 1,475 notices — which means F6's ~4 records are reachable only through the span-level architecture in §6.4b, where a two-item set can be admitted and then filtered member by member. Recorded so a later session does not spend pattern effort on it.

### 6.4b The unit of judgment is the span, not the set

**Added 8.3.** Everything above judges a **set**: rules 1–8 pass or fail all candidates together, and §6.2's confidence tier is likewise assigned to the whole result. That is the right granularity for *"did segmentation find an enumeration?"* and the wrong one for *"which of these should a PI see?"* — and the corpus shows the cost of conflating them in both directions.

**The false-positive direction.** `360678` — DOE Office of Science, 70 programmes including `(q) Catalysis Science`, the single most valuable extraction in this corpus — contains two administrative siblings, `Multi-Institutional Teams` and `Open Science`. Package D measured them; §6.3a's set-level veto could not catch them without also rejecting the 68 real ones (5 of 26 is 19%, under the 25% threshold). A set-level classifier reading the same evidence **condemned the entire set over those two members** (§11, Haiku). The same model at span level isolated exactly the two and passed the other 68. **Two policy paragraphs should not be able to delete Catalysis Science, and under a set-level verdict they can.**

**The false-negative direction.** `349554` (AFRL PACER) yields 18 correct topics at `low`, and `low` never publishes — so all 18 are suppressed to guard against fabrications that live in *other* `low` results. Judged individually, all 18 pass (18/18 on both models, §11).

**The rule.**

> A set that satisfies §6.4 rules 1–8 is **admitted**. Its members are then classified **individually**, and only members that pass are published. A set is never published or suppressed wholesale on the strength of some of its members.

Two consequences worth stating plainly, because they change what the tiers mean:

- **Set-level acceptance keeps its current job** — *is there an enumeration here at all?* — and loses the job it was doing badly, which is *is every member of it fundable?*
- **Confidence stops gating publication and starts gating review.** `high` publishes its surviving spans; `medium` and `low` publish their surviving spans **only once reviewed** (§18.1 Cov4). This is what makes PACER shippable without touching a threshold: its tier is unchanged, its spans are filtered, and the residual goes to a human. §18.3's asymmetry is preserved — nothing reaches a PI that has not survived both the filter and, below `high`, a person.

**This does not relax §6.4.** A set that fails acceptance still yields zero subtopics and leaves the parent untouched. Span filtering only ever *removes* members from a set that already passed; it can never add one, and it can never rescue a rejected set. If every member of an admitted set is filtered out, the result is zero subtopics and the reason is logged — the same fail-closed outcome as a rejected set.

### 6.5 Derived fields

> **✅ Cov5 — diagnosed, measured and fixed 2026-08-17. The mechanism this section previously named was wrong.**
>
> **What was observed.** Five spans in `360678` were handed excerpt text belonging to neither their title nor their subject: `(i) X-Ray Scattering` carried *"Applications submitted by February 1, 2026, will be considered for funding in FY 2026"*; `(d) Earth-Energy Systems Modeling` carried text trailing off into *"Specific Instructions"*. Both consumers were degraded at once — the §11 classifiers judged those spans by the text they were given, and the same string is what a PI reads on the card.
>
> **The mechanism, corrected.** This section used to say *"a span begins at its bookmark offset, so it can open mid-sentence inside the previous section's prose."* **That cannot be the mechanism, because a bookmark offset *is* the heading.** The span opens mid-sentence precisely when the code **fails** to find the heading and substitutes something else. Traced to one line: `_Flat._find` built its loose title matcher by splitting the needle on whitespace and rejoining with `\s+`, which bridges whitespace *between* whitespace-delimited tokens and never *inside* one. `pdfminer` emits a space adjacent to a hyphen or em-dash that the bookmark does not carry —
>
> ```
> bookmark  (i) X-Ray Scattering                     body  (i) X -Ray Scattering
> bookmark  (n) Public-Private Partnerships          body  (n) Public -Private Partnerships
> bookmark  (k) …Technology—High Energy Density…     body  …Technology —High Energy Density…
> ```
>
> — so `X-Ray` is one token and `X` / `-Ray` are two, and no amount of `\s+` reaches it. `locate()` returned `None`, `_locate_nodes` fell back to `page_start_offset()`, and the span began at the **top of the bookmark's page**, inside the previous section's prose. **All six cases had that one cause.** Not span boundaries, not running-header stripping, not container joining.
>
> **Prevalence, measured by re-running segmentation rather than by a text heuristic** — a start-of-sentence estimate had been tried and discarded for contradicting the observed error pattern, and the mechanism is a yes/no fact about a code path rather than an inference from prose:
>
> | | Spans | Detached | Rate |
> |---|---|---|---|
> | before the fix | 223 | **6** | **2.7%** |
> | after the fix | 224 | **0** | 0.0% |
>
> **It clustered entirely by document, not by method.** All six were in `360678` (6 of 68, 8.8%); the other twelve accepted documents scored zero, `numbered` and `heading_font` scored zero, and the one apparent method signal — `outline_structural` at 3.3% — is `360678` alone. **A sixth case was found that nobody had listed:** `(j) Plasma Science and Technology—General Plasma Science`.
>
> **The fix** makes whitespace optional around every non-alphanumeric character, **never at the pattern's edges**. The edge exclusion is load-bearing and was caught only by re-reading the output: a leading `\s*` makes `re.search` start the match in the whitespace *before* the heading, moving the span start a few characters early — enough that `build_subtopics`' "drop the heading line" step consumes that whitespace instead of the heading, so every summary then opens by repeating its own title. `360678` goes **68 → 69 spans**: one candidate was not merely misaligned but dropped outright. The other twelve documents are span-for-span identical, because the exact `str.find` fast path still runs first.
>
> **What is not fixed, and is the residual risk.** `_locate_nodes`' `page_start_offset` fallback is still there and still silent. It fires zero times across the D5 corpus now, but any future title it cannot locate produces the same wrong-excerpt outcome with no diagnostic. Making that fallback visible — or dropping the candidate instead of guessing its offset — is a separate decision with a real cost either way (§6.3a criterion 2 forbids dropping a sibling from a set), and it is **not** taken here.
>
> **How this was found is worth keeping.** Nobody searched for it. A classifier rejected five spans and stated why, and the reasons turned out to describe the text rather than the topic (§11). The measurement that produced a prevalence figure came only after someone asked for one.

**Running header/footer removal** — required before summarizing, or every summary opens with the solicitation number:

```python
def running_lines(containers, threshold=0.4):
    c = Counter()
    for container in containers:
        lines = [l.strip() for l in container["text"].splitlines() if l.strip()]
        for l in dict.fromkeys(lines[:3] + lines[-3:]):   # <- dedupe, see below
            c[re.sub(r'\d+', '#', l)] += 1          # page numbers -> '#'
    cutoff = threshold * len(containers)
    return {l for l, n in c.items() if n >= cutoff}
```

**Corrected (B2, 2026-08-16).** The sketch iterated `lines[:3] + lines[-3:]` directly, which counts **every line twice** on any page holding three or fewer lines, because head and tail are then the same list. At a 0.4 threshold that marks ordinary body prose as a running header and strips it — producing empty summaries and empty term maps on exactly the short spans a segmented topic tends to be. Found by the first end-to-end run; the fix is the `dict.fromkeys` above, which counts a line once per page rather than once per end it is near.

- **Title:** text after the code on the heading line, whitespace-normalized, ≤200 chars.
- **Summary:** leading sentences of the cleaned span, truncated at the last sentence boundary before 600 characters.
- **`own_deadline`:** only if exactly one unambiguous date expression occurs in the span and it does not contradict the parent's structured deadline.
- **Subject-area tagging — two fields, two vocabularies.** v6.2 had a single invented `program_area_tags` field whose example values belonged to neither real vocabulary. Reuse both real ones instead, via the code that already implements them:

  ```python
  from scripts import program_areas

  labels = [
      label for label, _topics, pattern in program_areas.ENTRIES
      if pattern.search(span_text)
  ][:program_areas_cap]
  record["program_area_labels"] = labels
  record["topic_areas"] = program_areas.topics_for(labels)
  ```

  `program_areas.ENTRIES` is the compiled `(label, topics, pattern)` vocabulary; `topics_for()` maps labels to the **Topic-facet display strings** the catalog actually facets and feeds on. Populating `topic_areas` is what makes a subtopic appear under `feeds/topic/catalysis-and-reaction-engineering.xml` and in the Topic filter. Populating only the lowercase labels would produce a child that is searchable but invisible to every facet. No new vocabulary is invented in either field.

  A subtopic span is a much better input to this vocabulary than a whole notice is, which is a real and independent argument for the feature: `extract_program_areas` currently attributes "catalysis" to an entire 200-page BAA because the word appears once on page 147. Run against a 4-page span, the same vocabulary says *which* topic area is the catalysis one.

### 6.6 Edge cases that must be handled

| Case | Handling |
|---|---|
| Scanned / image-only PDF | Zero extractable text → `no_extractable_text`, logged, no OCR in v1 |
| Encrypted PDF | **Do not add new handling.** `extract_pdf_pages` already calls `reader.decrypt("")` inside a bare `except` for empty-password encryption, and `extract_containers` has already run before segmentation is called. If containers came back empty, Layer A's own `PdfReader` will fail the same way; catch broadly, record `encrypted`, skip |
| PDF that `pdfplumber` can open but `pypdf` cannot, or vice versa | Each layer guards its own open; a library failure in one layer falls through to the next rather than aborting the document |
| Document exceeds the time budget | `time_budget` reason, zero subtopics, parent untouched (§6.1) |
| Topics in a *separate* attachment (common for DOE "Topic Area Descriptions" appendices) | **Re-justified 2026-08-16 by `docs/COVERAGE_SURVEY.md`, which found the case the census lacked.** AFRL PACER (`349554`) carries 17 attachments; the one `select_primary_document` picks is `Atch 10 BAA Attachment - Security Program Questionnaire.pdf`, a single page of 1,853 characters. The real BAA is `FA2391-23-S-2403.pdf`, and handed that file **production's own segmenter returns 18 correct topics**. So the mechanism now has a positive case, not only NRL's necessary-but-not-sufficient one — and it also has a corrected size: **15.7% of the catalog carries more than one attachment (232 of 1,475), not the 60% the census's heavier records implied.** Corpus-wide, only **4 records of 1,475** have a furniture-named selected primary, but `349554` and the census's `360261` are two of them. Expected yield, from the survey's stratified sample: **1 of 40 records, ~5 catalog-wide.** Small, real, and already built. Original entry follows.<br><br>**Implemented 2026-08-16 — `scripts/subtopic_sources.py`, and it bought nothing yet.** A parallel, subtopic-only path segments every attachment, dedups by content hash and keeps the best-scoring result; `source_for_record()` keeps its single-source contract so fact extraction is untouched and §0.5 holds by construction. **Measured across the census: zero correct acceptances gained, one wrong-list introduced.** CDC `360339` segmented its `M&E Indicator List` — `2.1. Point of Entry General Capacity`, `5.2. Laboratory Quality Control` — instead of its five fundable Components. So secondary-won results are **capped at `low` confidence and never publish**, on a measured precision of 0 of 1. NRL `352741` is the case that justified the work and it still misses: the path now fetches `Amendment 0004.pdf`, which really does hold its 32 topics, and the `53-24-01` code form has no family. Necessary but not sufficient. **The structural lesson: more documents means more enumerated lists, and most enumerated lists in a notice are not the fundable subdivisions** — indicator frameworks, review criteria, proposal components, cost categories. Widening the input widened the false-positive surface faster than it widened recall. Original measurement follows.<br><br>**Measured 2026-08-16 — the gap is much larger than "common for DOE appendices" suggested.** All 62 attachments across the 20 census records were enumerated: **12 of 20 records carry more than one attachment**, so the one-source assumption is wrong for 60% of the corpus. One miss is caused by it outright — NRL `352741`'s **32 research topics with 25 per-topic contact mailboxes** live in `Amendment 0004.pdf`, never fetched, while the primary notice it does fetch contains none of them. And the Genesis Mission's **98 focus areas** sit in a `.xlsx` attachment, which `extract_containers` could not parse even if it were fetched (it dispatches on `pdf`/`html`/`text` only, though `openpyxl` is already a runtime dependency). `source_for_record` returns exactly **one** source per record — `primary_document_url`, else the agency notice URL as a gap-fill. Building a multi-attachment path means changing its contract, its cache key shape, and the `--max-documents` budget. Still deferred; the cost is now quantified rather than guessed. See `docs/CORPUS_CENSUS.md` |
| HTML notice (NSPIRES, agency pages) | `extract_html_sections` already returns section/anchor-keyed containers with no page numbers. Use the section tree as the outline equivalent; same families, same acceptance rules; `page_start`/`page_end` null and the anchor carries the evidence link |
| **HTML as a Grants.gov *attachment*** — **selection implemented 2026-08-16 (Cov2); yield measured at zero** | `subtopic_sources.attachment_sources` now offers `.html` attachments and filters stubs below `MIN_HTML_BYTES = 2048` — a threshold sitting in an empty two-orders-of-magnitude gap between the 255 sub-1 KB stubs and the 111 announcements averaging ~145 KB, not a tuned parameter. **Cov2's own first task was then run: 20 of the 111 non-stub NIH announcements were fetched and pushed through production's `content_kind`, `extract_containers` and `segment_document`.** All 20 parsed cleanly — `kind=html`, 29–112 containers, 50–125 K characters, zero extraction failures — and **0 of 20 produced a subtopic list**, with **0 false positives**. They are single-programme NIH NOFOs whose section tree is the standard skeleton (`Part 1. Overview Information`, `Key Dates`, `Section II. Award Information`, `Cost Sharing`). The plumbing is right and the population is empty; do not expect recall here. **One gap found and deliberately not built:** `extract_html_sections` puts the heading in the container's `section` and the prose in its `text`, so every text-scanning family looks straight past the headings, and §6.6's own instruction to *"use the section tree as the outline equivalent"* is unimplemented. Building it would be speculative work against a population measured to yield nothing; `tests/test_subtopic_sources.py::HtmlAttachmentTests` pins the gap so the next session inherits the evidence rather than the assumption. Original entry follows.<br><br>**Measured 2026-08-16, and unhandled** | **366 of the 1,635 attachments in the catalog are `.html`, and every one belongs to NIH.** They split by size: **255 are stubs under 1 KB**, and **111 are complete announcements averaging ~145 KB, across 108 records**. `select_primary_document` requires a PDF (`attachment_is_pdf` gates the whole loop), so **not one of the 108 is selectable**, and all 108 sit in the unreachable population. This is the single largest clean fetch win in the survey's table. Temper it with what the survey also found: the two NIH records and one FDA record sampled on that same NIH template all enumerate **nothing**, so the yield per record reached is unknown and plausibly low. `docs/COVERAGE_SURVEY.md` names reading 20 of the 108 as the cheapest measurement that would settle it |
| **A `.zip` attachment** — 15 records | Not handled, and probably not worth handling. `360003` (ROSES A.10 INNOVATE) has exactly one attachment, a zip; inside it is `INNOVATE25_PSD.pdf`, which is a *Program Specific Data* form, not the element text. NASA's element text really is only on NSPIRES |
| **Image-only PDF, in the wild** | `363388` (ETA `UIPL 13-26.pdf`) is 18.7 MB across 49 pages and yields **48 characters**. The `no_extractable_text` path is correct and does fire; no OCR in v1 stands |
| Same FOA arriving via two sources (Grants.gov + EERE Exchange) | Dedup on `source_document_hash` before merge; first source wins |
| Amendment renumbers topics | Title-first matching (§5.3) |
| **Subdivisions that are one-per-attachment** — new shape, 2026-08-16 | State's `363607` Advancing Global Health APS carries six Addenda — Cameroon, Côte d'Ivoire, Mozambique, NTDs, Nutrition, Surveys and Surveillance — **each a separate PDF and each a fundable subdivision**, with the APS itself only saying *"through specific Addenda, the Department will signal priorities."* Nothing in §6.2's four layers models a subdivision that **is** a whole document rather than a span inside one. Recorded, not designed; the record is also unreachable, so nothing is fetched for it today |

### 6.7 Topics by reference — a first-class ingestion path

**Retitled and promoted in 8.7.** This section was written as *"the DOE BES
case"* and read as a one-agency workaround, which is how a whole class of
authoritative sources came to sit behind every generic-inference item in the
plan. An outside audit named that inversion and it is accepted. **Referenced —
and above it `native` — are ingestion paths of the same standing as inline
segmentation, not fallbacks for when segmentation fails.** DOE BES is the worked
example below, not the scope.

#### 6.7·0 The source router — least-ambiguous source gets first refusal

**The rule.** For any record, resolve its subdivisions from the *highest rung of
the §5.1 provenance ladder that answers*, and stop there. Lower rungs are not
consulted for that record unless the higher one **declines**, and a higher rung
that answers *wrongly* is a canary failure (§7.4), never an invitation to fall
back.

| Order | Rung | Asks | Declines when |
|---|---|---|---|
| 1 | **`native`** | Is there a published child list, table or API for this parent? | No registered native source matches this parent |
| 2 | **`referenced`** | Does an agency program page establish this parent's children? | No program-page rule matches |
| 3 | **`inline`** | Does the solicitation enumerate them in a recognised form? | No family accepts (§6.4) |
| 4 | **`inferred`** | Can generic structural inference establish a set? | `no_layer_accepted` |

**Why first refusal rather than merge.** Merging a native list with an inferred
one produces a record whose provenance is not a single value and whose
disagreements are invisible. Twelve ROSES elements and nine inferred spans is
not twenty-one children and not a union — it is one right answer and one
measurement that the parser or the notice has drifted. §5.1's rule 1 states it;
this is where it is enforced.

**Why this changes the order of work and not just the vocabulary.** Every
mechanism in §18.1's D¾ operates at rung 4. Rung 1 for a given parent is
strictly better evidence *and*, for the sources named in §18.1 D⅝, strictly
cheaper to parse — a table with one row per element against a heuristic over a
200-page PDF. **The plan had rung 4 scheduled and rung 1 unscheduled.** That is
the inversion, and §18.1 now fixes it.

**What the router does not do.** It does not improve coverage of records that
enumerate nothing anywhere. §18.1 D⅝ is explicit about this: its value is **new
parents**, not expanded ones.


**Correction to v6.2.** This section previously opened by calling the DOE Office of Science omnibus "the single largest remaining gap." It is not a gap — it is the single most-worked case in the repository. `scripts/sources/discoverability.py` carries two rules for it (`doe-office-of-science-umbrella`, `doe-basic-energy-sciences`), keyed on both `DE-FOA-0003600` and the title phrase "office of science financial assistance," attaching eleven Topic-facet tags and nineteen searchable terms, with `science.osti.gov/bes/Research` and `.../csgb/Research-Areas/Catalysis-Science` cited as evidence. A search for "catalysis" finds that FOA today.

What remains is narrower and still real: **the record has no children.** You can find the omnibus, but not the program inside it, not its program manager, and not its own page. That is a granularity problem, not a discoverability one, and it is worth solving — just not by re-solving what already works.

With that correction, the three-shape analysis below still holds.

DOE Office of Science solicitations split into three shapes, and only two of them segment.

| Shape | Example | Covered? |
|---|---|---|
| **Targeted FOA with enumerated directions** | BES "Chemical and Materials Sciences to Advance Clean Energy Technologies"; EFRC calls organized around Priority Research Directions | **Superseded in 8.5 — both named families are retired** (§6.3: zero fires across 170 documents, no validating record in 90). The *shape* this row describes is real and this row is the only place the plan records it, but nothing implements it now, and re-adding either family requires a validating document quoted under §17.8. Original text: **Yes**, once the `priority_research` and `research_thrust` families are added (§6.3) |
| **Multi-topic FOA with numbered topic areas** | Most EERE, FECM, ARPA-E | **Yes**, already |
| **Annual omnibus that points outward** | NSF division core solicitations | **No.** Segmentation returns zero topics, correctly, because there is no enumerated list in the document |

#### ⚠ Correction: `DE-FOA-0003600` is not an outward-pointing omnibus. The text is there.

Every prior version of this section — including the "corrected" 7.0 rewrite above — asserted the following, and it is **false**:

> The annual Office of Science continuation FOA is the vehicle through which BES core research is funded, but the FOA does not enumerate research areas — it refers the reader to the program's own web pages. … Segmentation cannot fix this, because the text genuinely is not there.

`docs/CORPUS_CENSUS.md` opened the document and read it. It carries **286 bookmarks**, including a complete program taxonomy:

```
III. Program Description
  A. Purpose
    1. Advanced Scientific Computing Research (ASCR)
      (a) Applied Mathematics
      (b) Computer Science
    2. Basic Energy Sciences (BES)
      (a) Materials Chemistry
      (b) Biomolecular Materials
      (c) Synthesis and Processing Science
      (d) Experimental Condensed Matter Physics
```

That is program-office → program granularity, in the notice, reachable by **Layer A today** once §6.3a's structural family exists. The claim that the text "genuinely is not there" was inferred from the document's reputation as an umbrella and never checked against the file. It is the most consequential factual error this plan has carried, because it is the basis on which the single most valuable case for this project's actual user was written off.

**What the notice does *not* supply, and this part of the original claim survives:** program-manager identity and contact, stable per-program URLs under `science.osti.gov`, and any taxonomy level deeper than the notice prints.

**Resolved by measurement (D2, 2026-08-16).** All 286 bookmarks were read. The tree is **9 / 46 / 167 / 64 nodes across four levels**, and **`(q) Catalysis Science` is present at level 2, page 46, under `2. Basic Energy Sciences (BES)`** — the only `/catalys/i` bookmark in the document. BES carries 24 sub-programs at that level, including `Separation Science`, `Photochemistry and Radiation Chemistry` and `Photosynthetic Systems`. So the granularity this project's user needs is in the notice, at a citable page, and §18.2's reassessment below stands rather than being conditional. Full tree in `docs/CORPUS_CENSUS.md`.

The row above has been narrowed to NSF division core solicitations, which remain genuinely outward-pointing and are unaffected by this correction.

**Solution: a third input to the same child-record model** — referenced subtopics, sourced from the agency's published program taxonomy rather than from the notice.

- **DOE Office of Science** — the BES research-area pages under `science.osti.gov`, walked as a tree (Division → Team → Program), each program yielding a description, a program manager, and a stable URL.
- **NSF** — division program listings, where each program has its own page, program officer and description.

Output uses the **same subtopic record schema** (§5.1) with `subtopic_source: "referenced"` rather than `"inline"`. This is deliberate: reusing the record type means the merge, rollup, scoring, feeds, change events and team matching machinery all work with zero additional code. Only three fields behave differently:

| Field | `inline` | `referenced` |
|---|---|---|
| `evidence_anchor` | `p14` (page in the notice) | the program page URL |
| `page_start` / `page_end` | populated | `null` |
| `source_document_hash` | hash of the notice PDF | hash of the fetched program page |

#### 6.7a Where this should live — two options, not yet decided

RECON established that `discoverability.py` already owns the linkage between an omnibus FOA and the program areas it funds, for exactly the solicitations this feature targets. So the question is no longer "build a new adapter or not." It is **whether referenced subtopics extend the existing registry or sit beside it.** Both are defensible. This decision is deferred to a human; it is recorded in §13 as open.

**Option 1 — extend `discoverability.py` to emit child records.**

Its `PROGRAM_RULES` entries already carry `topics`, `terms` and `evidence_urls` per umbrella. Add an optional `programs: [...]` key naming each fundable program under that umbrella, with its URL and program manager, and have `augment_records` emit one child record per program alongside the topic/term augmentation it already performs.

| For | Against |
|---|---|
| The linkage rule exists exactly once, in the file that already owns it. No second place to update when a FOA number rolls over | The registry becomes a content store, not just a rule set. Program descriptions are prose, and prose in a `.py` file is not maintainable at scale |
| `augment_records` already has correct reversal semantics — it strips its prior contribution before re-evaluating, so retiring a rule cleanly removes its children | Child emission inside `merge.integrate` happens *after* `build_search_index` has run in `extract_document_evidence`; the merge would have to rebuild the index, which it already does, but the ordering becomes load-bearing and subtle |
| Zero new adapters, zero new health-gate surface, zero new failure modes in the nightly | `discoverability.py` has no fetch layer at all today. Adding one changes it from a pure function over records into a network client, which is a genuine change in kind |
| Smallest possible diff | Couples the umbrella-tagging feature to the subtopic feature; a bug in one can now break the other |

**Option 2 — a separate `scripts/sources/adapters/program_taxonomy.py`.**

A normal source adapter following `adapters/_template.py`, inside the existing lifecycle, subject to the same health gates and fail-closed behavior, with its own `enabled` flag and its own `retain_on_failure` policy.

| For | Against |
|---|---|
| Fetching is what adapters do. It gets `PoliteClient`, retry, health bounds, last-known-good snapshots and degradation alerting for free | The linkage rule now exists in two files, and they can disagree. `discoverability.py` says `DE-FOA-0003600` is the Office of Science umbrella; the adapter must independently agree |
| `discoverability.py` stays a pure function over records — easy to test, no network, no I/O | A new enabled adapter is a new way for the nightly to report degraded, and the degradation channel is already noisy (`jhu-fellowships` is failing today) |
| Independently switchable: referenced subtopics can be disabled without touching umbrella tagging | More new code, more new tests, more new surface |
| Matches how every other external source in this repo is structured | The adapter emits *child* records, which no existing adapter does; `merge_records` and `validate` may need to learn about `parent_id` regardless |

**Recommendation: Option 2, with the linkage rule imported from `discoverability.py` rather than duplicated.**

The decisive argument is that this feature *fetches from the network on a schedule*, and this repository has one well-tested pattern for that — the adapter lifecycle — with health bounds, snapshot retention and fail-closed behavior that took real work to get right. Rebuilding any of it inside `discoverability.py` is strictly worse than reusing it. The main objection to Option 2 is duplicated linkage, and that objection dissolves if the adapter reads the umbrella identity from the registry instead of restating it:

```python
# scripts/sources/adapters/program_taxonomy.py
from ...sources.discoverability import PROGRAM_RULES

UMBRELLA_RULE_IDS = {"doe-office-of-science-umbrella": DOE_BES_TREE, ...}
# match the parent by asking discoverability which records the rule matched,
# never by restating the FOA number here
```

One rule set, one place to update on the annual roll-over, and the fetch machinery stays where fetch machinery belongs. Detect the roll-over by matching the solicitation title pattern, not the number — `discoverability.py`'s `triggers` already does this for `"office of science financial assistance"`.

**Is this curation?** Less than it looks, and no more than what already ships. The taxonomy is published in structured form on the agency's own site and scraped on the normal refresh cadence. The hand-maintained part is the linkage — a handful of entries that change about once a year — and that part already exists in `discoverability.py` today.

**Ordering note:** build this in Phase 2 alongside inline segmentation, not Phase 1, because it depends on the subtopic record schema existing.

## 7. Wiring into existing modules

### 7.1 Catalog merge

> **⚠ This section describes one of two options, and the choice is open.** §13.1 sets out the alternative — a lazily-loaded `data/subtopics.js` sidecar with its own compact index — and **recommends the sidecar**, conditional on cross-corpus score normalization surviving the §8.5 gate. Read §13.1 before implementing anything here. The rest of §7.1 assumes the in-catalog option; if the sidecar is chosen, the insertion-point analysis below is replaced by a new generated asset and the `record_count` consequences disappear.

Topics enter `data/opportunities.js` as child records with `parent_id` — **not** as a parallel store. The argument for this is that BM25 indexing, filters, sorting, Atom feeds, `alert_match.py`, team matching, the rating UI and CSV export all work on topics with no rewrite. The argument against is that it changes what `record_count` means for five existing consumers. §13.1 weighs both.

**Where the merge happens matters, and v6.2 did not say.** Five scripts rewrite `opportunities.js` in sequence, and only two of them rebuild the search index:

| Order | Script | Rebuilds `search_index`? |
|---|---|---|
| 1 | `build_catalog` | yes — builds it |
| 2 | `enrich_catalog` | no |
| 3 | `extract_document_evidence` | **yes** — `build_search_index(merged)` |
| 4 | `sources merge` | **yes** — inside `rebuild_catalog` |
| 5 | `check_links` | no — annotates and re-serializes |

Children must be appended **and** indexed in the same write, or `validateCatalog` throws (§4). Two candidate insertion points therefore work, and one does not:

- **Step 3, `extract_document_evidence`** — natural, because that is where the subtopics were just computed and where the index is already rebuilt. But step 4 then re-derives the catalog from its own base list and would drop them unless `merge` learns about children.
- **Step 4, `sources merge`** — the last step that rebuilds the index, so nothing downstream can drop the children. Requires reading `data/subtopic_records.json` from disk rather than from memory. **This is the recommended point**, and it is why the cache file exists at all rather than passing subtopics in memory.
- **`build_catalog` (step 1)** — v6.2's choice. It cannot work: `build_catalog` runs before the documents have been fetched, so the subtopics for this run do not exist yet.

Filter at the merge, not at write time. The cache keeps every row for diagnostics; the catalog sees only what passes. **Revised in 8.2 (§18.1 Cov4):** the test is no longer `confidence != "low"`. It is

```
publish  =  confidence == "high"
         OR (confidence in {"medium", "low"}
             AND an approval exists for this subtopic_id
             AND that approval's document_sha256 == the current document's)
```

so `medium` no longer publishes unreviewed — strictly more conservative than the previous rule — and an approved `low` can. The hash clause is what makes an approval falsifiable: when the notice changes, its subtopics re-queue instead of inheriting yesterday's judgment.

### 7.2 Currentness

Extends `scripts/currentness.py` with a **new** `subtopic_status()` function. The existing `record_is_current` keeps its signature and semantics untouched; it gains only a `record_type` early return.

```
open     = (own_deadline is null AND parent is current)
        OR (own_deadline is not null AND own_deadline >= as_of)
closed   = own_deadline has passed while parent remains current   # the ROSES case
expired  = parent no longer current
removed  = parent current AND document hash changed AND subtopic absent from new segmentation
```

Note `as_of`, not `build_date` — that is the parameter name `record_is_current` and `filter_current` already use, and matching it avoids inventing a second word for the same thing.

**Reapplied independently at runtime — in four places, not one.** RECON found that `currentness.py` is *not* applied by `build_catalog`; the published catalog retains records the gate would exclude, and consumers apply it against today's date. There are three separate browser re-implementations plus the Python module:

| Where | Function |
|---|---|
| `scripts/currentness.py` | `record_is_current` / `filter_current` — used by feeds, changes, docs stats, faculty match, alerts |
| `assets/app.js` | `recordIsCurrent` (re-implemented) |
| `assets/team-matcher.js` | `recordIsCurrent` (re-implemented) |
| `assets/team-researchers.js` | `recordIsCurrent` (re-implemented) |

Extending the gate for subtopics means touching **one Python module and three JavaScript copies**. Miss one and expired subtopics appear in that surface only — a bug that shows up on the team page but not the search page, which is miserable to diagnose. Budget for all four.

**Expired topics are retained, not purged — settled.** This diverges from how parent records are gated, deliberately. A closed MURI topic list is the best available predictor of next year's MURI topic list, and a program that shifts emphasis year over year is visible only if you keep the prior cycle. Rules:

- Retained for **3 years** past expiry, then dropped. Bounded, and long enough for two full cycles of an annual program.
- **Flagged**, not silently mixed in: every archived record carries its expiry date and its `recurrence_group`, and the UI labels it as a past cycle wherever it appears.
- **Excluded from default search and from all alerts.** Surfaced only behind an explicit "include past cycles" filter, so they never dilute live results.
- Written to a **separate `data/subtopic_archive.json`**, loaded lazily only when the filter is switched on. Otherwise three years of dead topics inflate every page load for a feature used occasionally.

Three mechanical consequences of the separate archive file:

1. It needs its own `!/data/subtopic_archive.json` line in `.gitignore` and its own entry in the workflow's `git add` list (§9.3).
2. Archived records are **not** in `opportunities` and therefore **not** in `search_index`. Searching past cycles means scoring them client-side against a separately shipped index, or accepting substring matching on the archive. Decide this when building the filter; do not assume BM25 comes along for free.
3. Because they are outside `opportunities`, they cannot break the `record_count` / `document_count` invariants (§4) — which is a second, independent reason for the separate file beyond page weight.

**Recurrence linking.** `title_fingerprint` (§5.3) is already computed, so linking cycles is nearly free: when a topic appears under a *different* parent with a matching or ≥0.85-similar title, assign both the same `recurrence_group`. This powers the planning view — "this topic ran in FY25 and FY26, wording drifted toward electrochemical pathways" — which is the actual reason for retaining expired records.

### 7.2b User suppression — "not relevant"

Recall improvements are only useful if the result list stays trustworthy. A single visible action, **Not relevant**, on any card:

1. **Hides it immediately** from that user's search and team-match results.
2. **Records a local negative label** with a reason code.

**This control is issue #8**, not a new feature. Use that issue's stated vocabulary rather than inventing one: mark as *useful*, *not relevant*, or *pursue*, with optional mismatch reasons — **topic, eligibility, award size, deadline, career stage, already known**. Design the storage shape against **#9**'s export requirement (labels, reason codes, scores and rationales to CSV, credentials excluded) so the export is a serialization rather than a migration.

Design decisions:

| Concern | Decision |
|---|---|
| Granularity | Two options on the control: hide *this topic*, or hide *the whole solicitation and its topics*. Both are needed — one bad topic does not condemn a parent. |
| Storage | Browser-local, consistent with §7.9. Keyed on `subtopic_id` / record id. |
| **Dependency on stable ids** | This feature is only correct because §5.3 carries `subtopic_id` forward through amendments. If ids churned on renumbering, mutes would silently break and hidden items would reappear. **Do not weaken §5.3.** |
| Recurring topics | A mute applies to the current cycle only. When a topic reappears under a new parent in a new `recurrence_group` cycle, it is shown again — a new cycle deserves a fresh look. Offer "mute across cycles" as an explicit secondary option. |
| Undo | A **Muted items** panel is mandatory, not optional. Without it, one mistaken tap hides something permanently and invisibly. |
| **Alerts limitation** | Mutes are browser-local; Atom feeds and email digests are generated in the workflow and cannot see them. **A muted item will still appear in alerts.** Either accept the split, or add an export that emits a suppression list the user pastes into their saved-search config. Flag this in the help text either way — a silent inconsistency here erodes trust in the whole tool. |
| Feedback value | Negative labels are the scarcest input to the evaluation harness. Offer an optional "share these" export writing to the existing review queue. Never transmit anything automatically. |

### 7.3 Retrieval and rendering

```js
// assets/search-retrieval.js — parent absorbs child scores, no double counting
const childScores = children.map(scoreRecord);
const parentScore = Math.max(scoreRecord(parent), ...childScores, 0);
```

Children render collapsed under the parent, expandable, with a matched-topic count badge. Topic cards reuse the parent's save/calendar/source actions and carry a page anchor to their own evidence.

### 7.4 Source-health canaries — detecting silent incompleteness

**Reframed in 8.7, and the reframing is the point.** This was written as
`expected_solicitations` — a curated list of notices that ought to exist, which
reads as a registry and was deferred in §18.2 as one ("no assertion that a known
umbrella silently vanished"). It is not a registry. **It is the only instrument
in the plan that detects a parser succeeding at nothing.**

**The failure mode it exists for.** A scraper against an agency page returns
**HTTP 200**, the adapter reports healthy, the run is green, the diagnostics show
no errors — and the parser extracted **zero rows** because the page was
restyled. Every existing health check passes: the fetch worked, nothing raised,
`no_layer_accepted` is a normal outcome (§9.3), and zero subtopics is
indistinguishable from a notice that genuinely has none. **Silent incompleteness
is the characteristic failure of structured sources**, and D⅝ is about to add
three of them.

A canary is therefore an assertion about **shape, not content**: not *"this
notice should exist"* but *"if this source is healthy, it yields at least this
much."*

| Canary | Assertion | Catches |
|---|---|---|
| **ROSES** | **≥20 open program elements** | Table 3 restyled, moved, or paginated; NSPIRES auth wall; a parser matching a heading that no longer exists |
| **DOE SC continuation** | the current Office of Science continuation notice **contains its BES children** | The program-page scraper silently losing one office; a taxonomy that stopped at program-office level |
| **ONR LRBAA** | **a current parent exists** at all | The long-range BAA rolling to a new number and the source router matching nothing |

Each states a floor an unhealthy source falls through, and none asserts an exact
count — an exact count is a curated registry and goes stale on the agency's
schedule, which is the objection that got this deferred in the first place.

**Wiring.** A canary failure is a **source-health** failure, not a segmentation
failure: it opens the existing owner issue through the channel §16.1 already
uses, and it **publishes nothing new for that source** — the same fail-closed
outcome as a classifier outage (§18.1 Cov4). It must not be `continue-on-error`,
which is the defect §9.3 records for the document-evidence step.

**This supersedes §18.2's deferral of `expected_solicitations`.** That line reads
*"no assertion that a known umbrella silently vanished from a healthy source"* and
treats it as a nice-to-have. With D⅝ adding native and referenced sources, it is
the mitigation for §12's scraper-fragility row and ships **with S1**, not after.

`data/expected_solicitations.json`:

```json
[
  {"pattern": "^W911NF-\\d{2}-S-\\d{4}$", "label": "DEVCOM ARL BAA", "source": "grants_gov"},
  {"pattern": "^N000142\\dSB\\d{3}$",     "label": "ONR LRBAA",      "source": "grants_gov"},
  {"pattern": "^HR001\\d{3}S\\d{4}$",     "label": "DARPA office BAA", "source": "grants_gov"}
]
```

**Two corrections from RECON.** v6.2's ONR pattern was `^N00014-\d{2}-S-B\d{3}$`, which matches nothing — the number in this catalog is `N0001425SB001`, with no hyphens. And both entries were attributed to `sam_gov`, a source that does not exist yet; these records arrive via **Grants.gov** today. Getting either wrong makes the assertion fire on every build for a reason unrelated to the thing it is meant to detect, which trains everyone to ignore it.

Validate any pattern added here against the live catalog before committing it:

```bash
python -c "
import json,pathlib,re
t=pathlib.Path('data/opportunities.js').read_text(encoding='utf-8')
c=json.loads(t.split('globalThis.GRANT_CATALOG=',1)[1].strip().rsplit(';',1)[0])
p=re.compile(r'^N000142\dSB\d{3}\$')
print([r['opportunity_number'] for r in c['opportunities'] if p.match(r['opportunity_number'] or '')])
"
```

`scripts/check_expected.py` runs after merge. If a declared solicitation is absent **while its source reports healthy**, exit nonzero → the existing workflow opens or updates the owner issue.

**Before wiring this, resolve the standing degradation.** `jhu-fellowships` currently reports `failed_no_fallback`, so the "External funding source refresh degraded" issue is already being opened or updated on every run. Adding a second assertion channel into a channel that is already firing means neither gets read. Either fix or disable that adapter first, or give `check_expected.py` its own distinct issue title so the two do not merge.

### 7.5 SAM.gov adapter notes

The API's shape drives the implementation:

- `postedFrom` / `postedTo` are **required**, format `MM/dd/yyyy`, window ≤365 days → page backward in ≤365-day windows.
- Keyword search matches **titles only**, not descriptions or attachments → do not rely on it for relevance; pull by notice type and NAICS, then filter locally.
- The description returns as a **URL**, not inline → a second request per notice.
- Quota is roughly 1,000 requests/day → prefilter on title and notice type before spending a description call, and cache description bodies by notice id so each is fetched once.

Budget: one search page (`limit=1000`) plus description calls only for notices passing the prefilter. Expect low hundreds of requests per run.

### 7.6 Match explanation ("why this matched")

A card reading *"Topic Area 3 — Interfacial Charge Transfer"* under a solicitation number the user has never seen looks like noise and gets skipped. Every topic result must carry its own justification, or the topic layer increases recall while decreasing the number of things people actually click.

This is **deterministic and computed at query time in the browser** — no stored field, no AI call. The scoring pass already knows which terms fired; it currently discards that. Retain it.

```js
// assets/match-explain.js  (new)
// Returned alongside the score, not stored in the catalog.
{
  match_path: "subtopic",           // "record" | "subtopic"
  parent_label: "DE-FOA-0003646 — Advanced Carbon Management",
  matched_terms: [                  // top 5 by BM25 contribution, descending
    {display: "electrocatalysis", stem: "electrocataly", field: "subtopic_terms", weight: 4.21},
    {display: "Faradaic",         stem: "faradaic",      field: "subtopic_terms", weight: 2.88},
    {display: "CO2 reduction",    stem: "co2",           field: "title",          weight: 2.10}
  ],
  matched_tags: ["Catalysis and reaction engineering", "Carbon management"],
  evidence: {page_start: 14, page_end: 19, url: "https://..."}
}
```

`matched_tags` carries **Topic-facet display strings**, matching the `topic_areas` field on the record (§5.1). v6.2's example used `["catalysis", "co2_utilization"]`, which mixed a `program_areas.py` label with a value from no vocabulary at all.

**The `term_display` requirement.** `subtopic_terms` holds *stems*. Rendering the chips straight from it produces "electrocataly" and "faradaic", which reads like a bug. Hence `term_display` in §5.1: a stem → most-frequent-surface-form map, capped at the top 60 stems per topic. It is display metadata only, adds a few hundred bytes per record, and does not reconstruct prose — the privacy boundary in §5.2 holds.

**Rendering.** A single chip row under the title:

> Matched **electrocatalysis**, **Faradaic**, **CO₂ reduction** · in Topic Area 3 of DE-FOA-0003646 · p. 14

with a disclosure expanding to the full term/weight table and a link resolving to the exact page. Naming the parent inline is not optional — it is what turns an obscure-looking code into a recognizable opportunity.

**Ship it independently.** Match explanation is useful for ordinary opportunity records too, and it is a smaller, lower-risk change than the topic layer. Put it behind its own flag, `FF_MATCH_EXPLAIN`, so it can go live before topics do and its value can be judged separately. Two flags, two rollbacks.

### 7.7 Team match

Team match is not a downstream consumer that inherits this for free. Recon question 9 asked whether it shares the BM25 index or runs its own similarity. **The answer is: it is three separate scorers, and they differ.**

| Module | When | Scoring | Shares `search_index`? |
|---|---|---|---|
| `scripts/faculty_match.py` | build time | hand-curated key-phrase hits (`FACULTY_KEYTERMS`) + domain overlap + bounded recency | **no** |
| `assets/team-matcher.js` | browser | its own `wordFrequency` map and bucketed `idf()` rebuilt from `opportunities` | **no** — borrows `tokenize` and the acronym resolver only |
| `assets/team-researchers.js` | browser | calls `retrievalEngine.score()` and reads `result.scores[documentId]` | **yes** |

So one of the three inherits subtopics for free once children are in `opportunities` and indexed. The other two need explicit work, and neither has any notion of a parent/child relationship — the top-3-per-parent cap has to be built twice, in two different scoring idioms. Budget accordingly; v6.2 treated this as one change.

Note also that `faculty_match.py`'s OpenAlex concepts are already overridden by hand-curated key terms, with a code comment saying the auto topics "mis-resolved several people and attached over-broad tags." Do not design as though OpenAlex classification is the live representation there; it largely is not.

Topic records are in fact a **better** input than parent records for all three. A researcher profile is a term distribution over abstract-length technical prose; a topic span is abstract-length technical prose. A parent synopsis is a page of administrative boilerplate. The comparison gets more apples-to-apples, not less.

Required changes in `assets/team-researchers.js` and `team_match.html`:

| Concern | Requirement |
|---|---|
| Flag parity | The same `record_type === 'subtopic'` early-return guard as the main search, in **both** `team-matcher.js` and `team-researchers.js`. With `FF_SUBTOPICS_ENABLED` off, team-match output must be **byte-identical** — this is covered by §0.5 and must be verified manually since it is browser-side. |
| Result explosion | One researcher × 20 MURI topics is unusable. **Cap at the top 3 topics per parent per researcher**, with an "and N more" disclosure. This was previously an open question; treat it as a requirement. |
| Rollup consistency | Same max-score parent absorption as §7.3, so a researcher is not listed against both a parent and its children as separate hits. |
| Match explanation | Team match needs `why this matched` *more* than the live site does, because the user is often evaluating a colleague's fit rather than their own. Show which **profile terms** drove the match, not just query terms. |
| Export | If team match has a CSV or clipboard export, subtopic rows must carry `parent_opportunity_number` and `subtopic_code` or the export is unusable outside the tool. |
| Reverse direction | Opportunity → faculty gets sharper: a topic matches fewer people more precisely. Confirm the reverse view reads the same rolled-up scores. |

### 7.8 Help and documentation

Minimal but not zero. Three additions:

1. **The hierarchy** — that a result may be a topic *within* a solicitation, and what the parent link means.
2. **Deadlines** — that a topic's date can differ from its parent's, and that the parent's structured deadline is what filters and sorting use. This is the one genuine source of user confusion; state it plainly.
3. **Match explanation** — one line on how to read the chip row and what the page anchor resolves to.

Also add a short note distinguishing `inline` from `referenced` topics (§6.7), since a referenced program record links to an agency page rather than a page in a PDF and will otherwise look inconsistent.

### 7.9 Researcher profile representation

**Read this section's correction before its argument.** v6.2 was written as though profile matching were unbuilt and OpenAlex concepts were the live representation. On the live site, neither is true:

| v6.2 assumed | Actually |
|---|---|
| CV support needs building | **Ships today.** `assets/profile.js` `extractCv()` parses PDF via vendored pdf.js and `.docx` via vendored mammoth, entirely client-side, capped at 120,000 chars, stored browser-local |
| CV text needs a scoring path | **Ships today.** `assets/profile-ranking.js` `buildTermQuery()` weights `expertise_keywords` 5.0, `research_description` 2.2, `orcid_text` 0.72, `cv_text` 0.42, looks each expanded term up in `catalog.search_index.postings`, and emits the top 28 as a query — already the same BM25 vector space as `subtopic_terms` will be |
| ORCID resolves through OpenAlex | **The browser uses Crossref.** `assets/orcid.js` queries `api.crossref.org/works?filter=orcid:…`, keeps items whose author ORCID matches, and builds `publicationText` from title + subjects + container. No abstracts, no OpenAlex |
| OpenAlex concepts drive team match | **They are already overridden.** `faculty_match.py` uses hand-curated `FACULTY_KEYTERMS`, with a comment recording that OpenAlex auto topics "mis-resolved several people and attached over-broad tags" |
| "Personal profile takes ORCID + CV + free text" is the proposal | That is a description of what shipped |

So the diagnosis below is right, and it has already been acted on for the parts that were cheap. What genuinely remains new in this section is narrower: **rehydrated abstracts as a terms source, recency weighting, and the negative-term list.** Scope it that way.

**The diagnosis, which still holds.** OpenAlex `concepts` / `topics` are a classifier taxonomy — a few thousand leaf buckets spanning all of science. A catalysis PI collapses into "Chemistry", "Catalysis", "Materials science", shared with tens of thousands of unrelated researchers. Those labels cannot distinguish reverse water-gas shift over Mo₂C from enzymatic catalysis, so matching on them produces exactly the vague results observed. The failure is the representation, not the API.

**Fix: use works text, not classification.** For each researcher, pull their works and build the profile from **titles plus reconstructed abstracts**. Run that text through `build_catalog.tokenize` (§5.2) so the profile lands in the identical vector space as `subtopic_terms`.

**Which provider — an open question this section should stop assuming.** OpenAlex's `abstract_inverted_index` rehydrates to full abstract text and is free, which is a real advantage over Crossref, whose abstract coverage is patchy. But the browser already has a working, CORS-accessible Crossref integration, and replacing it is not free. Two viable paths:

- **Add abstracts to the existing Crossref path** where Crossref supplies them, and accept partial coverage. Smallest change; no new provider.
- **Switch the browser to OpenAlex** for works retrieval, keeping ORCID as the resolution key via `GET /authors/orcid:0000-…`. Better abstract coverage, but replaces a working integration and adds a `mailto` polite-pool requirement.

Measure both against the query-set gate (§8.5) before choosing. Do not switch providers on the strength of the abstract-coverage argument alone — that is the same "it looks better" reasoning that put the concept taxonomy in place originally.

Three inputs, three distinct roles. Keep all three, but re-role them:

| Input | Role | Rationale |
|---|---|---|
| **ORCID** | **Identity resolution only** | Disambiguates *which* author record is the right person — a genuine problem for common names and for PIs with split records. ORCID's own metadata is self-curated and sparse, which makes it a poor terms source but an excellent key. This is already how `assets/orcid.js` uses it: the ORCID iD is a filter, and only works whose author ORCID matches are kept. |
| **Works text (Crossref today, OpenAlex under consideration)** | **Backward-looking base** | What the researcher has actually published. High volume, automatic, zero user effort. |
| **Resume / CV / interest statement** | **Forward-looking supplement** | What they intend to work on *next*. Neither other source can supply this. A PI pivoting from thermal to electrocatalysis has a publication record that lags the pivot by roughly three years, and for grant matching intent outweighs history. |

**Two profile paths, different inputs.**

| | Personal profile (live site) | Team match |
|---|---|---|
| Input | ORCID (optional) + resume/CV + free-text interests | **ORCID only** — anything richer makes the interface unusable at roster scale |
| Storage | Browser-local, per user | Committed roster for standing faculty; runtime entry for ad-hoc ORCIDs |
| Built | Client-side on entry | Build-time for the roster (cached, fast); client-side for ad-hoc |

ORCID's job in both paths is the same and is the reason to keep it: it resolves to the correct author record and removes the name-collision problem entirely. It is a key, not a terms source.

**Hybrid build for team match.** Committed-roster profiles are built in the workflow and cached in a new roster file, so the page loads instantly and costs nothing per view. ORCIDs entered at runtime resolve client-side, and results are cached in browser storage so re-entering a colleague's ORCID is instant. Degrade gracefully if the API is unreachable: the roster still works.

Two file-location details v6.2 got wrong. The existing roster is **`faculty_profiles.json` at the repository root**, not under `data/`. And it is **not** in the workflow's `git add` list — the workflow runs only `faculty_match match`, never `faculty_match profiles`, so the roster is refreshed by hand and committed by hand. A new `faculty_profiles_v2.json` inherits both facts: root-level, and manually committed unless the `git add` line is extended. Being outside `data/` at least means it is not caught by the `/data/*` ignore rule.

**Weighting:** recency-weight works (last 3 years ×2, older ×1); weight the free-text statement as though it were ~10 papers so it can actually move a ranking rather than being drowned out. Support an optional **negative term list** so a PI can suppress a collaboration outside their own area that is polluting their record.

Note that the existing source weights are already tuned and were changed as recently as commit `bce35ce`, which separated **admission** from **reranking**: `buildTermQuery`'s `admissionOnly` mode excludes `cv_text` and `orcid_text` entirely, so they influence ranking but never decide whether a record is admitted. Any reweighting must preserve that split, or a CV alone will start admitting records — which is the failure mode that change was made to fix.

**Verification, not intuition.** The frozen query set (§8.5) is the instrument: swap the profile representation, re-score, compare result IDs and rank movement. `evaluation/profile_relevance_probe.mjs` already does exactly this comparison for one query and three profile variants, and it is the thing to generalize. Do not decide by eyeballing the term list — that is how the current representation got adopted.

## 8. Integration discipline

### 8.1 Additive-only rules

These are not style preferences. Each one exists because violating it has a specific failure mode in this repository.

| Rule | Why |
|---|---|
| New **logic** lives in new files. Existing files receive flag-guarded call sites and data keys, not algorithms. | Keeps every diff reviewable and every rollback a one-line flag flip. See the amendment below — this is the rule §6.1a interacts with. |
| **No existing function signature changes.** New behavior arrives as a keyword argument with a default that preserves current behavior. | Two test files import nine functions from `extract_document_evidence.py` by name, and §8.1's own "no existing test is modified" rule makes those signatures binding. |
| **No existing function is deleted or renamed.** | Same reason. The test suite is the contract. |
| **No existing CLI flag changes meaning.** New flags default off. | The workflow invokes these scripts with fixed arguments. A changed default silently changes the nightly build. |
| **No existing data file changes schema.** New fields are added; readers tolerate their absence. | `data/opportunities.js` is consumed by browser code that ships separately from the build — and `schema_version` is asserted `=== 3` exactly, so it must **not** be bumped (§4). |
| **No existing test is modified.** New tests are added alongside. | The existing suite is your regression detector. Editing it destroys the only thing verifying you did no harm. |
| **No new file under `data/` without a `.gitignore` allowlist line in the same commit.** | `/data/*` is deny-by-default. Missing the line makes the file untracked and aborts the commit step. |
| **No reformatting.** Ever. | A `black` pass on a 600-line file turns a 3-line change into an unreviewable diff. |

**Amendment: "new behavior in new files" is about logic, not call sites.** §6.1a places a small flag-guarded call inside `extract_document_evidence.py`, because that is the only point in the pipeline where the document bytes exist. That is compatible with this rule as now worded, and the reasoning is set out in full in §6.1a. The test to apply while editing: *if what you are typing into an existing file could have a unit test written against it, it is logic and it belongs in a new module.* A call, a keyword argument, and a dict key cannot be unit-tested in isolation and are fine. A regex, a loop over pages, or a threshold is not.

Two rules from v6.2 were deleted rather than corrected:

- The `document_fetch.py` alias rule is gone because the extraction is gone (§6.1). Nothing imports `extract_document_evidence.py`, so there were never any downstream callers for aliases to protect.
- The `LICENSE` row is gone because the work is done. There is no `LICENSE` file; `copyright` already carries the all-rights-reserved notice.

### 8.2 Per-file edit contract

| File | Type | You may | You must not | Verify by |
|---|---|---|---|---|
| `scripts/subtopic_patterns.py` | **new** | Anything | — | New unit tests |
| `scripts/subtopic_segmentation.py` | **new** | Anything | — | Fixture golden tests |
| `scripts/subtopic_records.py` | **new** | Identity matching, cache read/write, archive rotation | — | Cache diff stability |
| `scripts/check_expected.py` | **new** | Anything | — | Manual first run |
| `scripts/sources/adapters/sam_gov.py` | **new** | Anything — follow `adapters/_template.py` | Deviate from the adapter interface | `tests/test_sources.py` |
| `scripts/sources/adapters/program_taxonomy.py` | **new** | Anything — follow `adapters/_template.py` | Deviate from the adapter interface; restate a linkage rule that `discoverability.py` already owns (§6.7a) | `tests/test_sources.py` |
| `assets/match-explain.js` | **new** | Anything | — | Manual A/B with `FF_MATCH_EXPLAIN` off |
| `tools/verify_no_drift.sh`, `tools/freeze_inputs.sh` | **new** | Anything | — | Runs green in CI (§8.4) |
| `evaluation/query_set.json`, `tools/query_baseline.mjs` | **new** | Anything | — | Deterministic across two runs (§8.5) |
| `.gitignore` | **modify** | Add `!` allowlist lines for the two new `data/` files | Broaden `/data/*` or remove an existing `!` line | `git check-ignore -v data/subtopic_records.json` returns nothing |
| `scripts/sources/adapters/nspires.py` | **activate shell** | Fill in the existing stub's contract | Change the adapter interface | Existing adapter-contract tests |
| `scripts/extract_document_evidence.py` | **modify** | Add an `enable_subtopics=False` keyword arg; add the guarded call site in `build_document_entry`; add the backfill condition (§8.3); add a `"subtopics"` key to the entry dict | Change any existing signature or public name, change the fact/program-area output schema, change exit codes, put segmentation logic in this file | Existing suite passes **unchanged** (9 imported symbols) |
| `scripts/sources/merge.py` | **modify** | Read `data/subtopic_records.json` and append children in `rebuild_catalog`, behind the flag | Change `merge_records` semantics for parent records | §8.4 hermetic gate |
| `scripts/currentness.py` | **modify** | Add a new `subtopic_status()` function; add a `record_type` early-return in the existing gate | Change `record_is_current`'s signature or semantics for non-subtopic records | New interaction tests + §8.4 |
| `scripts/build_changes.py` | **modify** | Append four new event types to the existing emitter | Touch existing event-generation code | §8.4 gate on a fixture with no subtopics |
| `scripts/evaluate_phase2.py` | **modify** | Add a subtopic-level metric block **only if** labelled exports carrying subtopic ids exist | Change existing metric definitions; assume it reads the catalog — it does not (§8.5) | Re-run against the same export files |
| `assets/search-retrieval.js` | **modify** | Add rollup guarded by `if (!globalThis.FF_SUBTOPICS_ENABLED) return <existing path>` | Change existing scoring math | Manual A/B + §8.5 query gate |
| `assets/app.js`, `match_explorer.html` | **modify** | Add rendering behind the flag; early-return on `record_type === 'subtopic'` when off | Restructure existing render path; relax `validateCatalog` | Manual A/B with flag off |
| `assets/team-researchers.js`, `assets/team-matcher.js`, `scripts/faculty_match.py`, `team_match.html` | **modify** | Add subtopic handling + per-parent cap behind the flag; same `record_type` guard, in **all three** scorers (§7.7) | Change existing similarity math or export column order | Manual A/B with flag off (§7.7) |
| `assets/site-help.js` | **modify** | Append the three items in §7.8 | Restructure existing help content | Visual check |
| `requirements.txt` | **modify** | Add `pdfplumber` and `pdfminer.six` pinned exactly; tighten `pypdf` from a range to a pin | Add PyMuPDF or any AGPL library (§6.1); add test-only deps | Clean install in CI |
| `requirements-dev.txt` | **new** | Test-only deps, if any are needed | — | Installed only in the test job |
| `.github/workflows/*.yml` | **modify** | Add the two new `data/` paths to `git add`; add new steps at the documented position (§9) | Reorder, rename, or alter existing steps; change `permissions:` or `concurrency:` | Dispatch run on branch |
| `PROJECT.md` | **append** | Record the decision and measured deltas | Rewrite existing history | — |

Files v6.2 listed that are **not** touched by this project: `scripts/document_fetch.py`, `scripts/extract_topics.py`, `scripts/topic_patterns.py`, `scripts/topic_segmentation.py`, `scripts/build_gold_set.py` (all superseded or dropped), `scripts/build_catalog.py` (the merge moved to `sources/merge.py`, §7.1), and `LICENSE` (does not exist; work already done).

### 8.3 The call site in `extract_document_evidence.py`, and the backfill trigger

This replaces v6.2's `document_fetch.py` extraction, which was dropped (§6.1). It is the only change to working code before the flag exists, so it gets extra care.

The file is 1,928 lines and produces live published data. The total footprint here is **four small insertions**, all guarded. Nothing is moved, deleted, or renamed.

**Insertion 1 — the keyword argument.** `enrich_document_evidence` gains `enable_subtopics=False`, threaded to `build_document_entry`. Both already take keyword-only arguments, so this changes no positional signature and breaks no test.

**Insertion 2 — the call site**, in `build_document_entry`, after `containers` and `facts` are computed:

```python
subtopics = []
if enable_subtopics:
    from scripts import subtopic_segmentation      # function-local: never imported when off
    subtopics = subtopic_segmentation.segment_document(
        record, content, containers, document, fetched_at,
    )
```

and `"subtopics": subtopics` in the returned entry dict. With the flag off this evaluates one `if` and stores an empty list — and since the entry dict is serialized into `data/document_evidence.json`, even the empty key is a schema change, so **omit the key entirely when the flag is off** rather than writing `[]`. §0.5 requires byte-identity, and an added `"subtopics":[]` on 726 cache entries is not byte-identical.

**Insertion 3 — the backfill trigger. This is the one that matters.**

§4 lists three skip gates. On a steady-state night nearly every document takes one of them, so a naive implementation segments only documents that happen to change, and the ~1,400 already-cached documents **never get subtopics at all**. The feature would appear to work on a handful of records and silently never backfill.

Each gate needs the same predicate, which belongs in the new module, not in this file:

```python
# scripts/subtopic_records.py
def needs_subtopic_extraction(entry, *, enabled, extractor_version):
    """True when a cached entry has no usable subtopic result for the current
    extractor. Backfill and version-bump reprocessing both route through here."""
    if not enabled:
        return False
    if entry is None:
        return False                      # a full extraction is already happening
    if "subtopics" not in entry:
        return True                       # never attempted
    if entry.get("subtopic_extractor_version") != extractor_version:
        return True                       # toolchain or pattern set moved (§6.1)
    return False
```

Applied at all three gates:

| Gate | Where | Change |
|---|---|---|
| **1. Not due** | `due_for_check()` | `return True` when `needs_subtopic_extraction(...)`. Without this the record is never even a candidate |
| **2. 304** | `enrich_document_evidence`, where `If-None-Match` / `If-Modified-Since` are set | **Omit the conditional headers** for records needing backfill. A 304 returns no body, and you cannot segment bytes you did not receive |
| **3. Hash unchanged** | `build_document_entry`, the `previous_hash == digest` branch | Before returning the deep-copied prior entry, run segmentation on the freshly downloaded `content` and attach the result. Do **not** fall through to the full-extraction path — that would re-run fact extraction and rewrite `facts`, `review_queue` and `version`, churning the cache for no reason |

Gate 3's placement is the subtle one. The bytes *are* in hand there — they were downloaded and hashed — so this is genuinely free. Gates 1 and 2 each cost one request per document, once, and then never again.

**Backfill is a bounded, one-time campaign — and it is run locally, not through the nightly.**

Earlier versions offered a choice: drain roughly 1,400 documents at `--max-documents 45` over about a month of nightly runs, or run it locally and commit the cache once. **The nightly option is withdrawn.** It is strictly worse on every axis that matters:

- It puts the feature in a half-populated state for a month, during which every diagnostic reading is meaningless — an acceptance rate over 300 documents tells you nothing about the other 1,100.
- It gives backfill suppression (§10 step 23) no single marker date, forcing a more complicated rule for a transient condition.
- It adds ~1,400 document fetches to the nightly's budget spread over weeks, which is exactly the fetch pressure §4 exists to bound.
- It couples a one-time migration to a daily production job, so a bug in segmentation is discovered on the live schedule rather than on a laptop.

**Run it locally against a copy of `data/document_evidence.json`, with a high `--max-documents`, and commit the resulting cache in one reviewable commit.** The nightly is never involved, the cache arrives complete, diagnostics are readable immediately, and the marker date is a single day. This is §18 package D.

**Insertion 4 — diagnostics.** Extend the existing `document_metrics` block with subtopic counts and a rejection-reason histogram, so Phase 2 has something to observe.

Procedure, in this order:

1. Add the new modules with tests. Nothing in `extract_document_evidence.py` yet. Commit.
2. Add insertions 1, 2 and 4, flag off. Run the existing suite — it must pass with **zero** changes to test files. Run the §8.4 gate — output must be byte-identical. Commit.
3. Add insertion 3, still flag off. It is unreachable while `enable_subtopics` is False, but the `due_for_check` edit sits in a hot path, so re-run both gates. Commit.
4. Only then exercise the flag on, locally, against a copy of the cache. Never against `data/` on the branch.

Keeping steps 2 and 3 apart matters: if the nightly starts fetching more documents than it used to, `git bisect` points at exactly one four-line commit.

### 8.4 The hermetic no-drift gate

The golden rule (§0.5) needs to be mechanically checkable, and it cannot be checked against live data because live data changes every night by design. So the check runs against **frozen inputs**.

**v6.2's version could not be built.** It ran `build_catalog.py --input-dir tests/fixtures/frozen` over the three cache files. `build_catalog.py` reads **none of them** — its only input is the Grants.gov XML extract ZIP. The caches are consumed by three *later* scripts that each rewrite `opportunities.js` in place. A gate over `build_catalog` alone would have verified about a fifth of the pipeline and none of the parts this project actually touches.

It also proposed three new CLI flags, two of which duplicate flags that exist:

| v6.2 wanted | Reality |
|---|---|
| `--build-date` | **`--as-of` already exists** and does exactly this. Per §8.1, use it; do not add a synonym |
| `--input-dir` | No meaning. The analogue is the existing **`--archive`** |
| `--output-dir` | No meaning. The analogue is the existing **`--output`** |

**So no new CLI flags are needed at all**, and v6.2's Phase 1 step 1 is deleted.

#### What makes an offline run possible

The pipeline already has an offline mode; it was simply never used as one. Every network-touching stage is bounded by a flag that accepts zero, and the bounds are validated as `>= 0`, not `> 0`:

| Stage | Offline invocation | Why it works |
|---|---|---|
| `build_catalog` | `--archive <frozen.zip> --as-of 2026-08-20` | `--archive` skips the download entirely |
| `enrich_catalog` | `--max-updates 0 --max-agency-updates 0` | Zero fetches; still merges the frozen cache onto records |
| `extract_document_evidence` | `--max-documents 0` | Zero fetches; still merges the frozen evidence cache and rebuilds the index |
| `sources merge` | `--adapter sample --include-disabled --write` | The `sample` adapter reads a local JSON fixture and requires no network |
| `check_links` | `--max-checks 0` | Zero checks; the failure threshold needs ≥20 checks so it cannot trip |
| `build_changes`, `build_feeds` | as normal | Never network-touching |

**Verified by running it** (Phase 1 step 1, 2026-08-16). All seven stages execute offline against the frozen fixture and produce 20 artifacts. Two corrections the prototype forced:

- **`build_catalog` needs `--min-records 1`.** The default is 1000 and the fixture publishes 3 records, so `validate_catalog` raises without it. This is a harness argument, not a changed default — the workflow still passes `--min-records 1000`.
- **`update_catalog_docs` must be excluded.** Its four output paths are hard-coded to `REPOSITORY_ROOT` (`README.md`, `PROJECT.md`, `match_explorer.html`, `team_match.html`) and cannot be redirected, so including it would write into the repository on every CI run. It was already absent from the table above; this records *why* it must stay absent.

That is a complete, hermetic, network-free run of the real pipeline.

#### The frozen inputs

`tests/fixtures/` already contains `grants_db_extract.xml` (4 KB) — reuse it rather than inventing a parallel fixture. It needs to be zipped, because `read_archive` expects a ZIP.

`tools/freeze_inputs.sh` builds the archive, trims the caches, runs the build once and writes the baseline. Two details the sketch in earlier versions got wrong:

- **The zip is built with Python's `zipfile`, not `zip(1).`** `zip` is absent from some environments this runs in, and the entry timestamp has to be pinned (`date_time=(1980,1,1,0,0,0)`) or the archive hash moves on every regeneration.
- **Trimming currently yields *empty* caches, and that is expected.** The live caches are keyed by real Grants.gov opportunity ids; the frozen XML fixture carries ids `1001`, `1003`, `1005`. They do not intersect, so trimming to "records present in the frozen XML" removes everything: 1,411 → 0 enrichment entries and 958 → 0 evidence entries.

**What that means for the gate's coverage, stated plainly.** The gate covers every stage's *merge and serialization* path — normalization, facet counts, index construction, discoverability augmentation, link annotation, change diffing, feed rendering — which is the whole surface that byte-identity is about. It does **not** cover the populated fact-merge path inside `merge_document_entry`, because no frozen entry has facts. That is a real limitation and it sits precisely on the file §8.3 modifies.

Closing it means hand-authoring one `document_evidence` entry keyed to fixture id `1001`, with a fact, a citation and a program area. That is fixture authorship rather than pipeline work, it is independent of everything else in Phase 1, and it should be done before Phase 2 step 14 adds the call site. Recorded as a follow-up rather than smuggled into this step.

#### Normalizing the timestamps

Four fields change on every run by design and carry no behavioral signal:

```
generated_at
detail_enrichment_generated_at
document_evidence_generated_at
link_health_generated_at
```

plus `cache["generated_at"]` and `checked_at` inside the caches.

v6.2 assumed a fixed `--build-date` handled this. It does not: `--as-of` sets the *currentness* date, while these four come from `utc_now()` at the moment each script runs. There are two ways to deal with it:

- **Normalize them out of the fingerprint (recommended).** The gate replaces each with a constant before hashing. **Zero production-code changes**, which matters enormously for a gate that must exist *before* any behavior-affecting change — a safety net you had to modify the system to install is not much of a safety net.
- **Inject them.** Add a `--now` override to four scripts. Stricter, but it is production surface added for a test, and `enrich_document_evidence` already accepts `now=` at the function level, so the CLI plumbing is the only missing piece. Keep this in reserve for the case where timestamp normalization is hiding something.

Take the first. The drift this gate exists to catch is a changed record, a changed facet, a changed posting — never a changed clock.

**The `sed` normalizer sketched in earlier versions does not work.** Diffing two hermetic runs showed it wrong in four ways, and the field list it named was incomplete:

| Problem | Evidence |
|---|---|
| Misses `merged_at` | `diagnostics.additional_sources.merged_at` in `opportunities.js` |
| Misses `changed_at` | every event in `feeds/changes.json` |
| Misses Atom `<updated>` entirely | not JSON-shaped; `feeds/changes.xml` carries volatile timestamps at *entry* level too |
| Pattern `"key":"value"` has no whitespace tolerance | `link_health.json`, `feeds/changes.json` and `feeds/index.json` are written indented, so `"generated_at": "…"` never matches |

`feeds/index.html` also carries a bare timestamp in prose, inside no tag at all.

**Resolution: `tools/fingerprint.py`, in Python, normalizing every ISO-8601 datetime literal.** One regex over the file text handles minified JSON, indented JSON, Atom XML, the JavaScript assignment and the HTML prose uniformly:

```python
TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
)
```

Date-only values such as `2026-09-30` are untouched, so every close date, archive date and other currentness input stays fingerprinted. The one thing this gives up is entry-level `<updated>` in `all.xml` and the facet feeds — but those are derived from record dates that are themselves fully fingerprinted inside `opportunities.js`, so no signal is lost from the gate as a whole.

**Line endings must be normalized too — this is the second thing the gate has to absorb.** The pipeline writes its artifacts through two different APIs:

| Artifacts | Writer | Result |
|---|---|---|
| `opportunities.js`, `opportunity_enrichment.json`, `document_evidence.json`, `source_records.json` | `tempfile.NamedTemporaryFile(..., newline="\n")` | **LF on every platform** |
| all 15 `feeds/*` plus `link_health.json` | `Path.write_text()` with no `newline` argument (`check_links.py:310`, `build_changes.py:252` and `:256`, `build_feeds.py:172`) | **platform default** — CRLF on Windows, LF on Linux |

A baseline recorded on Windows therefore disagrees with a Linux CI run for exactly those 16 artifacts and no others. That is a property of the developer's operating system, not of the code under test, and it is what broke the gate on its first CI run (2026-08-16). `normalize()` collapses CRLF and lone CR to LF before hashing.

Normalizing rather than fixing the three writers is deliberate: `build_feeds.py`, `build_changes.py` and `check_links.py` stay untouched, so the nightly build goes on emitting exactly the bytes it emits today. The cost is that the gate cannot detect a change that *only* alters line endings — acceptable, because `.gitattributes` applies `* text=auto eol=lf` to the repository and the nightly runs on `ubuntu-latest`, so committed output is LF either way.

**Diagnostic note for the next person who sees this fail.** Raw `diff -rq` between two builds always reports every artifact as differing, because every artifact contains a timestamp. That is not the signal. Diff the **normalized** bytes — import `normalize` from `tools/fingerprint.py` and compare its output — or you will chase a temporal cause that is not there. Two builds 65 seconds apart, crossing a minute boundary, produce zero normalized differences.

`tools/verify_no_drift.sh` rebuilds into a `mktemp -d`, fingerprints, and `diff -u`s against the committed baseline, printing the §0.5 explanation on failure.

`tools/hermetic_build.sh` is the seven-stage sequence from the table above, writing into the directory it is given and never touching `data/`. **That isolation is the point** — §0.3 forbids running write-mode scripts against the repo, and this gate runs on every build. Intermediates (the pre-build catalog snapshot `build_changes` diffs against) go in `<out>/.work/`, and `fingerprint.py` skips any dot-prefixed path component so they are not part of the baseline.

Wire it into `tests.yml`, not into `refresh-opportunities.yml`. It is a correctness check on the code, it needs no network, and `tests.yml` already runs on every push and pull request. Invoke it as `bash tools/verify_no_drift.sh` rather than relying on the executable bit — this repository's checkout has `core.fileMode = false`, so the mode is not reliably recorded.

**A gate that cannot fail is worth nothing, so prove it fails.** After building it, perturb a frozen input, confirm `verify_no_drift.sh` exits 1 and names the affected artifacts, then restore and confirm it passes again. Done for the initial build: adding one record to the frozen enrichment cache moved exactly two fingerprints (`opportunities.js`, `opportunity_enrichment.json`) and the gate reported both.

This gate is what makes every subsequent phase safe. Build it first.

**Status: built and passing (Phase 1 step 1, 2026-08-16).** 20 artifacts baselined in `evaluation/artifact_fingerprints.txt`; deterministic across repeated runs; wired into `tests.yml`; zero production-code changes, as promised.

### 8.5 The retrieval regression gate — replacing the labelled baseline

v6.2's Phase 1 step 3 said: "Run `evaluate_phase2.py` against the current catalog; commit `evaluation/baseline_pre_topics.json`." **This cannot be done.** `evaluate_phase2.py` takes one or more *exported human relevance-label files* as positional arguments and requires `schema_version == 1` with a `feedback` list. It never opens the catalog; its own docstring says it "never needs an API key, research description, or CV." Worse, the label corpus is deliberately private — `.gitignore` excludes `/evaluation/inbox/` and `/evaluation/reports/`, and the only committed sample is a 2.2 KB fixture.

So there is no labelled baseline to freeze, and producing one means a labelling campaign that is not in this project's scope.

**Replacement: a frozen query set, compared on result IDs and ranks.** This needs no relevance judgments at all. It does not measure whether the results are *good* — it measures whether they *changed*, which is the actual question §0.5 asks and the only one that can be answered without labels.

The harness already exists in prototype. `evaluation/profile_relevance_probe.mjs` loads `assets/search-query.js`, `assets/search-retrieval.js` and `assets/profile-ranking.js` into a `node:vm` context, loads `data/opportunities.js` into the same context, builds the real retrieval engine, and prints ranked `opportunity_id` lists with scores — for one query and three profile variants. Generalize it; do not start over.

```jsonc
// evaluation/query_set.json
{
  "schema_version": 1,
  "catalog": "tests/fixtures/frozen/opportunities.js",
  "queries": [
    {"id": "q001", "kind": "keyword", "query": "electrocatalysis CO2 reduction"},
    {"id": "q002", "kind": "keyword", "query": "catalysis"},
    {"id": "q003", "kind": "acronym", "query": "MOF"},
    {"id": "q004", "kind": "number",  "query": "DE-FOA-0003600"},
    {"id": "q010", "kind": "profile", "profile": {
      "research_description": "heterogeneous catalysis and CO2 hydrogenation",
      "expertise_keywords": "catalysis, reactor design",
      "cv_text": "@tests/fixtures/browser_cv.txt"
    }}
  ]
}
```

Cover, at minimum: single common terms; multi-word technical phrases; an acronym (exercises the resolver); a literal opportunity number (exercises exact-match); a query that should return nothing; one profile-only query; and one query per umbrella family this project targets. Thirty to fifty queries is enough — the gate's value is breadth of *code path*, not statistical power.

```
tools/query_baseline.mjs --write   →  evaluation/query_baseline.json
tools/query_baseline.mjs --check   →  exit 1 on regression
```

Each query records the top 50 as `[{rank, id, score}]`. The `--check` comparison reports three numbers per query and gates on the third:

| Metric | Meaning | Gate |
|---|---|---|
| **Set delta** | IDs entering or leaving the top 50 | Report always |
| **Rank displacement** | Sum of \|Δrank\| for IDs in both | Report always |
| **Top-10 churn** | IDs entering or leaving the top 10 | **Fails the build if non-zero with the flag off** |

Top-10 churn is the gate because it is what a user sees. Set delta at rank 47 is noise; a new record at rank 3 is a product change.

Three properties that make this work where the labelled baseline could not:

- **No labels.** It compares a build against its own prior self, so it can be created today, from the code as it stands.
- **Deterministic.** Same catalog plus same query set gives byte-identical output — scoring is pure BM25 over a fixed index, with no clock and no network. Confirm this by running it twice before committing the baseline.
- **It is the right instrument for §7.9 too.** Swapping the profile representation, changing a weight, or adding subtopic children all show up here as rank movement on a fixed query set. That is exactly the "verification, not intuition" §7.9 asks for, and it is why `profile_relevance_probe.mjs` was written in the first place.

**What it does not do.** It cannot tell you a change was an *improvement* — only that it was a change. Judging improvement still needs labels, and that remains true and unsolved. When Phase 3 shows the flag-on build moving top-10 results, a human has to look at the diff and decide. The gate's job is to guarantee that nobody has to *notice* the movement first.

**⚠ On the frozen fixture, the top-10 gate is weaker than this section implies. Measured, not argued (A6, 2026-08-16).** The gate was built and then deliberately perturbed twice:

| Perturbation | Set delta | Displacement | Top-10 churn | Result |
|---|---|---|---|---|
| Swap ranks 1 and 2 of `q002` | 0 | 2 | **0** | Reported, **exits 0** |
| Drop a result from `q002`, add a phantom to `q030` | 1 each | 0 | **2** | **Exits 1**, naming both ids |

The reason is arithmetic, not a bug: the frozen catalog holds **5 records**, so no matched record can ever fall past rank 10. "IDs entering or leaving the top 10" therefore collapses into "did the matched *set* change" — admission changes are gated, **pure reordering is not.** Churn as defined in the table above is the right gate for the ~1,475-record live catalog it was designed against; on a 5-record fixture it is a strictly weaker instrument than the surrounding prose suggests.

Two consequences, both for later packages rather than for A6:

- **Package E must not read a green flag-off gate as "ranking is unchanged."** E is where cross-corpus score normalization lands, and reordering is exactly the failure mode it risks. Read the reported **displacement** numbers there, and consider gating on non-zero displacement for the duration of E — the harness already computes and prints it, so this is a threshold decision, not new code.
- The alternative — pointing the query set at a larger catalog — reintroduces the problem §8.5 exists to avoid, because the live catalog changes nightly and its baseline would drift every run. The frozen fixture is still the right catalog; it is the *gating metric* that needs a second look when scores start moving.

**The labelled path is already tracked, and it is not this project's to build.** Two open issues cover exactly the ground `evaluate_phase2.py` needs and does not have:

| Issue | Title | Relationship |
|---|---|---|
| **#8** | Add browser-local relevance labels and reason codes | The *producer*. Faculty mark results useful / not relevant / pursue with mismatch reason codes, kept browser-local. This is also the same control §7.2b specifies for subtopic suppression — the two are one feature, not two |
| **#9** | Export a privacy-safe matching evaluation dataset | The *exporter*. Labels, reason codes, scores and rationales to CSV with credentials excluded. This is what would feed `evaluate_phase2.py` |

So the sequence is #8 → #9 → a labelled baseline, and none of it exists today. §8.5 is not a permanent substitute for that work; it is the gate that lets this project proceed **without blocking on it**. When #9 ships, the labelled comparison becomes possible and §10 step 33 becomes meaningful — until then that step is correctly skippable.

Note the dependency runs the other way too: **§7.2b's "not relevant" control is #8.** Building it as part of Phase 3 step 28 partially delivers #8, and it should be built with #9's export format in mind rather than inventing a private one. Read both issues before designing the reason-code vocabulary.

Freeze `tests/fixtures/frozen/opportunities.js` as the gate's catalog — the output of the §8.4 hermetic build, so both gates run over the same inputs and one fixture set serves both.

## 9. GitHub Actions integration

### 9.1 Read before you edit

The workflow is the single most dangerous file in this repository, because a mistake there does not throw an error you see — it publishes wrong data, or silently stops publishing, or opens issues every night forever. Read `docs/RECON.md` answers 2, 3, 6, 7 and 11 before opening it.

### 9.2 Where the new steps go

v6.2's step list was wrong in five ways: source adapters run fourth, not second; there is no second "build catalog / merge" step; check-links runs *before* build-feeds; two steps it omitted exist; and **there is no deploy-Pages step at all**. The real order, with insertions marked:

```
   1  checkout
   2  setup-python 3.13 (pip cache)
   3  setup-node 22
   4  copy data/opportunities.js -> $RUNNER_TEMP/opportunities.previous.js
   5  pip install -r requirements.txt
   6  unittest discover -s tests            (pre-refresh)
   7  node --test tests/browser/*.test.mjs
   8  build_catalog       --output data/opportunities.js --min-records 1000 --max-record-count 5000
   9  enrich_catalog      --max-updates 250 --request-delay 0.25
  10  extract_document_evidence --max-documents 45 --request-delay 0.2 --recheck-days 14
                                            ← continue-on-error: true
                                            ← subtopic segmentation happens INSIDE this step (§6.1a)
  11  sources merge       --write --fail-on-degraded     id: additional-sources
                                            ← continue-on-error: true
                                            ← subtopic->catalog merge added here, Phase 3 (§7.1)
+ 11a check expected solicitations          ← NEW, Phase 1
  12  faculty_match match
  13  build_changes
  14  check_links         --max-checks 150 --workers 8 --fail-threshold 0.35
  15  build_feeds
  16  update_catalog_docs
  17  unittest discover -s tests            (post-refresh)
  18  commit + rebase-retry push            ← THIS is what publishes; Pages serves the branch
  19  owner issue if steps.additional-sources.outcome == 'failure'
  20  owner issue if failure()
```

Insert; do not reorder anything existing.

**There is no separate "extract topics" step.** v6.2 placed one after step 10; §6.1a settles that segmentation runs inside step 10, because that is the only point where the document bytes exist.

**`verify_no_drift` does not go here either.** It belongs in `tests.yml`, which already runs on every push and pull request, needs no network, and does not risk the publish path (§8.4).

**Pages.** There is no deploy job and no deploy artifact — GitHub Pages serves the default branch directly, so step 18's push *is* the publication. Everything before it is fail-fast, so any new failing step inserted before 18 blocks publication of otherwise-good data. That is precisely why the Phase 2 subtopic work must not add a failure path (§9.3) — the conclusion v6.2 reached for a mechanism that turns out not to exist.

### 9.3 Failure-mode rules for new steps

| Concern | Requirement |
|---|---|
| Benign zero-result runs | Segmentation returning zero subtopics is a **normal** outcome — for scanned PDFs, non-umbrella notices, and the omnibus shape in §6.7. It must never raise. Wrap the call site in a broad `except`, record the reason, and continue. Reserve failure for "could not write the cache." |
| **Persistence — two files, two places** | Add `!/data/subtopic_records.json` and `!/data/subtopic_archive.json` to `.gitignore` **and** both paths to the `git add` line. Missing the `.gitignore` line is worse than missing the `git add` line: `git add` on an ignored path exits non-zero, and the commit step runs under `bash -eo pipefail`, so **the step aborts and the nightly stops publishing entirely**. |
| Not poisoning the issue automation | Step 10 is already `continue-on-error: true`, so segmentation failures inside it are contained without any workflow edit. See the warning below — that containment is more complete than you want. |
| Runtime | Total job runtime is **2:20–3:30** today, against a 45-minute timeout. Enforce **both** §6.1 budgets: `SUBTOPIC_TIME_BUDGET_SECONDS = 20` per document bounds one pathological PDF, and `SUBTOPIC_RUN_BUDGET_SECONDS = 600` bounds the run. The per-document cap alone permits 45 × 20 s = 15 minutes. The §9.4 gate is an absolute 15-minute ceiling, not a delta. |
| Permissions | No new scopes are required. If you believe you need to widen `permissions:`, stop — something is wrong with the design. |
| Concurrency | Do not touch the `concurrency:` block. |
| Path filter | `refresh-opportunities.yml` triggers on `push` only for 14 explicitly-listed paths. New scripts do **not** trigger a push-run unless added to that list. Decide deliberately; leaving them off is defensible during Phase 2. |
| Dependency cache | Adding `pdfplumber` changes the `requirements.txt` hash, so the first run after that commit is slow. Expected, not a bug. |
| Dev dependencies | There is **no `requirements-dev.txt`**, and `tests.yml` installs only `requirements.txt`. **It stayed that way (B3, 2026-08-16), but not for the reason this row gave.** `tests/test_document_evidence.py` does build PDF fixtures with `pypdf.PdfWriter`, and that pattern is *not* sufficient for Layer C: `PdfWriter` assembles pages and metadata but does not lay text down in a chosen font, so it cannot author the `fontname` and `size` variation Layer C reads. The answer is the **base-14 fonts** — Helvetica, Helvetica-Bold, Times-Roman, Times-Bold are built into every conforming PDF consumer and need no embedded font program, so a hand-written content stream of a few hundred bytes yields real, resolvable font names (`pdfminer.six` reports `Helvetica-Bold` verbatim). `tests/fixtures/minipdf.py` does this in ~180 lines, byte-deterministically, and also writes a real bookmark tree so Layer A is covered from the same builder. No PDF-generating library was added. Add `requirements-dev.txt` only if something genuinely cannot be done with the existing deps — and check the base-14 route first. |
| Pages coupling | Publication is the `git push` in step 18, and every step before it is fail-fast. A new failing step before 18 blocks publication of otherwise-good data. |

**⚠ A failure inside step 10 is currently silent, and this cuts both ways.**

Step 10 has `continue-on-error: true` **and no `id:`**. So when it fails: the job still succeeds, `failure()` does not fire, and the `steps.additional-sources.outcome` condition does not match it either. No issue is opened. `extract_document_evidence` already has a health gate (`validate_refresh_health`, raising when >80% of ≥5 attempted fetches fail) that is swallowed exactly this way — and note it runs *after* both caches are written, so a failed health check still persists that run's output.

For Phase 2 this is what §9.3 wants: a cache nobody reads cannot break the publish. But it also means **"segmentation is failing on every document" is invisible** — there is no alert, no issue, and nothing in the commit diff. Rely on the diagnostics block (§8.3 insertion 4) and check it deliberately during the Phase 2 observation window. Do not assume silence means success.

When Phase 4 removes the containment, give step 10 an `id:` and route it to the degraded-source issue explicitly. Removing `continue-on-error` alone routes it to the *job-failed* issue, which overstates a document-parsing problem as a broken build.

### 9.4 Dispatch-test checklist before merging any workflow change

1. Push the branch. Run via `workflow_dispatch`.
2. Confirm **total job runtime is under 15 minutes**, read from the Actions run summary.
3. Confirm the diff of committed artifacts contains only what you expect. With the flag off, it should contain **nothing** attributable to your change.
4. Confirm **no new issue number appears.** Record the highest existing issue number before the run and check it has not advanced afterwards. **Issue #30 receiving another comment is expected and is not a failure** — see below.
5. Confirm `verify_no_drift` passed in `tests.yml` on the same commit (§8.4).
6. Confirm `query_baseline.mjs --check` reports **zero top-10 churn** with the flag off (§8.5).
7. Confirm the `.gitignore` allowlist line landed: `git check-ignore data/subtopic_records.json` must print nothing and **exit 1**. Use the plain form, not `-v` — earlier versions of this item said `-v` returns nothing, which is wrong. On a path rescued by a negation, `-v` prints the negating rule (`.gitignore:23:!/data/subtopic_records.json`) and exits **0**, so the `-v` form looks like a failure when it is a pass. Verified on this tree 2026-08-16.
8. Only then open the PR.

#### Why item 2 is an absolute ceiling, not a delta

v6.2 and 7.0 both said "runtime delta under 20%." That gate is unusable, in both directions at once.

Real runs are **2:20–3:30** against a 45-minute job timeout. Twenty percent of that is roughly **34 seconds** — so a change that added half a minute of work would fail the gate, even though the job has forty-one minutes of unused headroom. Meanwhile §6.1's own per-document budget permits `--max-documents 45` × 20 s = **15 minutes** of segmentation, which the same gate would have to reject on principle while the design explicitly allows it. A gate that forbids what the design permits is not a safety check; it is a contradiction that will simply be ignored the first time it fires.

**The gate is therefore an absolute ceiling: total job runtime under 15 minutes.** That is roughly four times the current run, comfortably inside the 45-minute timeout, and it is bounded by construction — 3:30 of existing pipeline plus the `SUBTOPIC_RUN_BUDGET_SECONDS = 600` cap in §6.1 cannot exceed about 13:30. If a run breaches 15 minutes, something is wrong that the run budget failed to contain, and that is worth stopping for.

Record the absolute duration on every dispatch run regardless of pass or fail. The repository does not store runtime anywhere, so this checklist is the only place a baseline accumulates.

#### Why item 4 counts issue numbers rather than issue activity

Two auto-created issues are **already open and already recurring**, both from before any subtopic work:

| Issue | Title | Trigger | Activity |
|---|---|---|---|
| **#30** | External funding source refresh degraded | `steps.additional-sources.outcome == 'failure'` | 19 comments; updated on essentially every run |
| **#29** | Automated Grants.gov refresh failed | `failure()` | 6 comments; last updated 2026-08-14 |

#30 fires because `jhu-fellowships` reports `failed_no_fallback` (§7.4). Because the workflow's issue script looks up an *existing open issue by title* and comments on it rather than opening a new one, neither of these will ever produce a new issue number while they remain open. So "no issue was opened or updated" is unobservable — #30 updates every night no matter what you do.

**What is observable is a new issue number.** Any genuinely new failure mode introduced by this work would carry a title neither script currently emits, and would therefore create a new issue. Check the number, not the activity.

Two consequences worth stating plainly:

- **#30 updating is expected. Do not treat it as a regression, and do not "fix" it by silencing the alert.** Resolve or disable `jhu-fellowships` on its own terms (§7.4), separately from this project.
- **#29 being open means the `failure()` channel is also blunted.** If a Phase 1 or Phase 3 change breaks the build, the alert will be a comment on a week-old issue rather than a new notification. Watch the run conclusion in the Actions tab directly during dispatch testing; do not rely on the issue channel to tell you the job failed.

## 10. Phases

> **§18 supersedes this section as the unit of work.** These four phases describe everything the project *could* include; §18 defines the nine packages actually being built (A–G plus D½ Coverage and D¾ Forms) and lists what is deferred with the cost of each. Read §10 for the reasoning behind an individual step — it is retained in full and still explains *why* each piece exists — but take the sequence and the checklist from §18 and §15.

Reordered so everything large and additive lands before anything existing changes behavior. Four phases.

---

### Phase 1 — Foundations (additive; no existing behavior changes)

Everything here adds instrumentation or adds a new source. The catalog gains records from new sources; nothing about how the site works changes.

One honest exception to "purely additive," which v6.2 claimed: **step 4 tightens `pypdf` from a version range to an exact pin.** That is a modification to an existing dependency line, and while it is behavior-*preserving* at the currently-resolved version, it is not an insertion. It gets its own commit, with the existing suite and the §8.4 gate run before and after.

0. **Reconnaissance — done.** All eleven §0.1 questions are answered in `docs/RECON.md`. Read it; do not repeat it.
1. **Build the no-drift harness** (§8.4): freeze inputs into `tests/fixtures/frozen/`, write `tools/hermetic_build.sh`, `tools/fingerprint.sh` and `tools/verify_no_drift.sh`, capture `evaluation/artifact_fingerprints.txt`, wire it into `tests.yml`. **Do this before any behavior-affecting change** — it is the safety net for everything that follows. No production-code changes are required (§8.4).
2. **Build the retrieval regression gate** (§8.5): write `evaluation/query_set.json` and `tools/query_baseline.mjs` by generalizing `evaluation/profile_relevance_probe.mjs`; commit `evaluation/query_baseline.json`. Run it twice before committing to confirm determinism.
3. **Add the size-budget test** to `tests/` (§12 gives the numbers — `opportunities.js` is already 24.8 MB, so the budget is absolute, not a multiplier).
4. **Pin the PDF toolchain** (§6.1): add `pdfplumber` and `pdfminer.six` pinned exactly; tighten `pypdf` from `>=5.0.0,<7` to an exact pin. Own commit, existing suite run before and after, `verify_no_drift` green. No new code uses them yet.
5. **Write `scripts/sources/adapters/sam_gov.py`**, modelled on `scripts/sources/adapters/_template.py`, inside the existing adapter lifecycle, per §7.5.
6. **Activate `scripts/sources/adapters/nspires.py`**, anchored on the ROSES Table 2 / Table 3 HTML listings rather than PDF parsing. Its docstring already records why it is off and what the ROSES omnibus problem is — read it first.
7. **Rebuild researcher profiles per §7.9**, scoped to what is actually new there: rehydrated abstracts as a terms source, recency weighting, and the negative-term list. Decide the Crossref-vs-OpenAlex question on measured results from step 2, not on argument. Purely additive — write to a new `faculty_profiles_v2.json` at the repository root and leave `faculty_profiles.json` untouched until measured.
8. **Populate `data/expected_solicitations.json`** and wire `scripts/check_expected.py` into the workflow at position 11a (§9.2). Validate every pattern against the live catalog first (§7.4), and resolve the standing `jhu-fellowships` degradation so the alert channel is readable.

**Four steps from v6.2 are gone:**

- *Build determinism arguments* — `--as-of`, `--archive` and `--output` already exist and do the job; the three proposed flags were duplicates or meaningless (§8.4).
- *Freeze the `evaluate_phase2.py` baseline* — impossible; it consumes human relevance labels, not the catalog. Replaced by step 2 (§8.5).
- *License housekeeping* — **already done.** There is no `LICENSE` file; `copyright` carries the all-rights-reserved notice. Completed in commits `d76c2a3` through `8b7ef92`.
- *Extract `scripts/document_fetch.py`* — dropped; nothing imports the module it would have protected (§6.1).

*`scripts/build_gold_set.py` has also moved out of Phase 1.* It was the instrument for a labelled evaluation that step 2 now replaces for regression purposes. Deriving known-positives from past awards is still worth doing — it is the only way to judge whether a change is an *improvement* rather than merely a change (§8.5) — but it is a multi-source scraping project in its own right, and gating this work on it was the wrong dependency. It is recorded in §13 as an open decision.

> **Why SAM.gov is still in Phase 1**, with a corrected justification. v6.2 argued that the canonical DoD umbrellas "never appear on Grants.gov" and are "absent from the catalog entirely." **That is false**: 31 BAA records are in the catalog today, including the ONR Long Range BAA, the DEVCOM ARL foundational BAA, five DARPA office BAAs, AFOSR, NRL and ERDC. The Phase 2 development corpus therefore already exists and is reachable through the existing document-evidence path — SAM.gov is **not** a blocker for the segmenter, and Phase 2 can start without it. It stays in Phase 1 on the weaker but still sufficient grounds that it closes a genuine residual gap (MURI specifically, and SAM.gov-only notices) and is independently valuable whether or not subtopics ever ship. If Phase 1 runs long, this is the step to defer.

**Exit criteria:** existing tests green **with zero test-file edits**; `verify_no_drift` passing in CI; query baseline committed and reproducible; PDF toolchain pinned; new sources reporting healthy through the existing gates; catalog record count up, behavior otherwise identical.

---

### Phase 2 — Extraction, offline (writes a cache nothing consumes)

The subtopic pipeline runs daily and produces a cache. The published catalog does not read it. Zero risk to the live site.

9. **Write `scripts/subtopic_patterns.py`** with the families in §6.3 and `best_family()`. *(8.5: §6.3 no longer holds ten. It holds **six** — `topic_area`, `dod_topic`, `component`, `focus_area`, `technical_category`, `thrust` — plus `structural_siblings` (§6.3a). Seven were retired on measurement: five never fired across 170 documents and two produced only false positives. Do not restore a family from this step list without §17.8's validating document.)*
10. **Write `scripts/subtopic_segmentation.py`**: layers A–D (§6.2) against `pypdf` and `pdfplumber`, acceptance rules (§6.4), derived fields (§6.5), edge cases (§6.6), time budget and page caps (§6.1).
11. **Generate synthetic fixtures** into `tests/fixtures/synthetic/` — one PDF per pattern family, plus a bookmark-less variant, a TOC-only trap, and a reference-list trap. *(8.5: "one per family" is now six, not ten. A fixture per family also proves nothing about whether a family occurs in the corpus — every one of the seven retired families had a passing synthetic fixture and zero real documents, which is how they survived four packages unnoticed. §17.8 is the check a fixture cannot be.)* Synthetic means no real notice is ever committed. Build them with `pypdf.PdfWriter`, following `tests/test_document_evidence.py`, so no test-only dependency is added. If a fixture genuinely requires a layout engine that `pypdf` cannot produce — Layer C needs real font metadata — add `reportlab` to a new `requirements-dev.txt`, installed only in the test job.
12. **Write `tests/test_subtopic_segmentation.py`**: golden outputs per fixture; idempotency (two runs byte-identical); rejection cases; a `match_subtopics()` renumbering test (insert a topic mid-list, assert one addition and zero amendments); and a Layer C test asserting bold detection from a real `fontname`.
13. **Write `scripts/subtopic_records.py`**: identity matching via `match_subtopics`, term maps, cache read/write with the §5.4 stable serialization, archive rotation (§7.2), and `needs_subtopic_extraction()` (§8.3).
14. **Add the call site** to `extract_document_evidence.py` per §8.3, flag off, in the four-commit order given there. Add the two `.gitignore` allowlist lines and the two `git add` paths in the same change (§9.3).
15. **Write `scripts/sources/adapters/program_taxonomy.py`** (§6.7) emitting `subtopic_source: "referenced"` records — **after** the §6.7a option is decided by a human. Same adapter lifecycle, same health gates.
16. **Tune offline** against the real corpus: the 31 BAA records already in the catalog (§6.3), plus anything SAM.gov added in Phase 1. Iterate on patterns until acceptance rates are acceptable per agency family. *(8.5: **this instruction is withdrawn as written.** Tuning toward an acceptance rate is what §17.8 now forbids and what package D stopped doing at 42% for the same reason. Iterate toward a named, quoted validating document per family and report per-family fire counts including the zeros; an acceptance rate that rises because a family was widened is not evidence.)* This is offline work against a local cache copy — never against `data/`.
17. **Run once via `workflow_dispatch`** on your branch with the flag on and walk the §9.4 checklist before merging. No workflow step is added — segmentation is inside step 10 (§9.2).
18. **Run the backfill locally** (§8.3) against a copy of the evidence cache with a high `--max-documents`, and commit the resulting cache once. The nightly is not used for backfill.
19. **Observe one nightly** run of cache output and diff churn before proceeding. Read the diagnostics block deliberately — a total segmentation failure inside step 10 is silent (§9.3). One run is enough because the backfill already completed locally; what this checks is that the *steady state* is diff-stable, and that is visible on the first night.

**Exit criteria:** ≥80% acceptance on documents that visibly contain topic lists; zero low-confidence records published; `subtopic_records.json` diff-stable day over day; backfill complete or its remaining depth known; published build unchanged.

---

### Phase 3 — Wiring, dark (behind flags, fully reversible)

Everything is built and running in parallel, off by default.

20. **Write `assets/match-explain.js`** (§7.6) behind its own `FF_MATCH_EXPLAIN` flag. Ship this **first and independently** — it is lower risk than subtopics, valuable on ordinary records, and earns its own rollout.
21. **`sources/merge.py --enable-subtopics`**: read `data/subtopic_records.json`, append children with `parent_id`, filter by the §7.1 publish test (8.2: `high`, or `medium`/`low` with a hash-matched approval — no longer a bare `confidence != "low"`), dedup on `source_document_hash`, rebuild the index including `subtopic_terms` — all in one write, so `record_count` and `search_index.document_count` move together (§4, §7.1).
22. **Add `term_display`** to the subtopic builder in `scripts/subtopic_records.py`, capped at 60 stems. Without it the match chips render stems and look broken.
23. **Backfill suppression**: subtopics whose `first_seen` equals the backfill marker date are excluded from `build_changes.py` on that build only — otherwise the first digest is entirely noise. Because §8.3's backfill is a single local run, there is exactly one marker date and the rule stays simple.
24. **Extend `currentness.py`** per §7.2 — `subtopic_status()` plus a `record_type` early return — **and the three browser re-implementations** in `app.js`, `team-matcher.js` and `team-researchers.js`. Dedicated parent/child interaction tests.
25. **`assets/search-retrieval.js`**: max-score rollup (§7.3), guarded by `if (!globalThis.FF_SUBTOPICS_ENABLED)`.
26. **`assets/app.js` + `match_explorer.html`**: collapsed subtopic rendering behind `FF_SUBTOPICS_ENABLED`. Do **not** relax `validateCatalog` (§4).
27. **`assets/team-researchers.js`, `assets/team-matcher.js`, `scripts/faculty_match.py`, `team_match.html`**: all six requirements in §7.7. Remember this is **three** independent scorers, only one of which uses the shared BM25 index; the top-3-per-parent cap has to be built more than once. Verify flag-off parity manually — browser-side, and the hermetic gate does not reach it.
28. **"Not relevant" control + muted-items panel** + local negative labels (§7.2b). **This delivers part of issue #8** — use its vocabulary and #9's export shape.
29. **Expired-subtopic archive** to `data/subtopic_archive.json`, "include past cycles" filter, recurrence grouping (§7.2). Decide how archived records are searched — they are outside `search_index`.
30. **Update the help page** per §7.8.
31. **Extend `build_changes.py`** with `subtopic_added` / `subtopic_amended` / `subtopic_closed` / `subtopic_removed`.
32. **Confirm `build_feeds.py`** emits subtopic entries with stable ids, and **`alert_match.py`** matches subtopics with no modification. Note `alert_match.py` is not run by any workflow here — it is a library consumed by a separate private digest repository — so "confirm" means unit tests, not observing a run.
33. **Extend `evaluate_phase2.py`** to report subtopic-level recall separately — **blocked on issue #9** (privacy-safe evaluation dataset export), which is itself blocked on **#8** (labels). Neither has shipped. If they still have not by the time you reach this step, skip it and say so rather than inventing a metric.
34. **Run a single build comparison**: both catalogs built once in CI from the same inputs, compared on the §8.5 query set (result-ID and rank movement), catalog size, and `opportunities.js` byte size. The comparison is deterministic — same frozen catalog, same query set, pure BM25 — so repeating it for two weeks produces the same numbers fourteen times. What a longer window would catch is *input* variation, and that is what the nightly's own diff churn already shows.

**Exit criteria:** flag-on top-10 movement on the §8.5 query set is reviewed and accepted by a human, case by case; flag-off top-10 churn is zero; size budget held (§12); `verify_no_drift` still passing with the flag off.

---

### Phase 4 — Enable and operate

35. **Flip** `--enable-subtopics` and `FF_SUBTOPICS_ENABLED` in the published build. Give step 10 an `id:` and route its failures to the degraded-source issue before removing `continue-on-error` — removing it alone reports a document-parsing problem as a broken build (§9.3).
36. **Record** the decision, rationale and measured deltas in `PROJECT.md`.
37. **Standing operations:** monthly review of the rejection-reason histogram for pattern drift as agencies change templates; `check_expected.py` failures triaged as source regressions; quarterly confirmation that the cron schedule is still enabled (§16.3).
38. **Gate the optional AI layer** (§11) on the measured deltas from step 34 — not before.

**Rollback:** every step through 34 is reversible by flipping the flag off. The subtopic cache keeps building harmlessly and the published catalog reverts to current behavior.

Two changes are **not** flag-reversible, and both are Phase 1: pinning the PDF toolchain (step 4) and any `.gitignore` / `git add` edit. Both are behavior-preserving, both are covered by the existing suite and the §8.4 gate, and both are trivially revertable by their own commit — but neither is undone by flipping a flag. v6.2 named the `document_fetch.py` extraction as the sole irreversible step; that step no longer exists.

---

## 11. Deferred optional AI layer

**Status: reopened for one half, measured (2026-08-17).** This section had two halves. The **recall** half — *can a model rescue the misses?* — is closed, and nothing below disturbs it. The **precision** half — *can a model tell a fundable list from announcement furniture, given spans that already exist?* — was recorded as "plausible" and has now been run.

### The recall half stays closed, and this is not a re-argument

Assessed against the measured causes of every segmentation miss (`docs/CORPUS_CENSUS.md`): **an LLM labeler under this section's own constraint reaches 0 of 7 misses.** In six of the seven, deterministic segmentation located *no spans at all* — three have no family shape, one was rejected by an acceptance rule, one has its list in an attachment that is never fetched — so there is nothing for a labeler to label. In the remaining two, candidates were located and then rejected, and having a model overturn that rejection is exactly the "discover topics" role this section forbids: the model would be deciding *whether a list exists*, not describing one that does.

**That argument is untouched by the measurement below and remains correct. Do not cite the new numbers to reopen acceptance; they are about a different question.**

### The precision half, measured

Run 2026-08-17 against the 22 accepted sibling sets of the D4 backfill (9 legitimate / 13 furniture, labelled by reading every title in D5) and against 114 individual spans. Labels were never in the prompt. `361876` is held out of the set-level scoring as a contested label — both models reasoned to the same feature and weighted it oppositely — leaving 21 scored.

**Set level — is this set the fundable list?**

| | precision | recall | of the 4 modes the lexicon cannot see |
|---|---|---|---|
| §6.4 rule 8 lexicon | 100% | 67% (8/12) | 0/4 |
| `claude-haiku-4-5` | 91% (10/11) | 83% (10/12) | 3/4 |
| `claude-sonnet-4-6` | 100% (12/12) | 100% (12/12) | 4/4 |
| **`claude-sonnet-5`** · thinking default | **100% (12/12)** | **100% (12/12)** | **4/4** |
| **`claude-sonnet-5`** · thinking disabled | **100% (12/12)** | **100% (12/12)** | **4/4** |

**Span level — is this individual span fundable, inside a set already judged correct?** 114 spans across `349554` (18, all verified good), `360678` (70, 2 known contaminants) and `361526` (26, 5 known contaminants).

| | contaminants caught | good spans wrongly rejected | precision | recall |
|---|---|---|---|---|
| `claude-haiku-4-5` | 7/7 | 3 of 107 | 70% | 100% |
| `claude-sonnet-4-6` | 7/7 | 0 of 107 | 100% | 100% |
| **`claude-sonnet-5`** · thinking default | **7/7** | 1 of 107 | **88%** | **100%** |
| `claude-sonnet-5` · thinking disabled | 7/7 | 6 of 107 | 54% | 100% |

**PACER passes 18/18 in every configuration of every model run.**

**The model string is `claude-sonnet-5`, with `thinking` left at its default — re-baselined 2026-08-17.** Sonnet 4.6 was never chosen; it was what happened to be measured, and it is a generation behind. The re-baseline ran the identical prompts (imported, not copied) and **the set-level result is unchanged: 100/100 in both thinking configurations, 4/4 semantic modes, no disagreements.** Span-level recall is unchanged at 7/7. The one change is precision, and it is a configuration variable that did not exist on 4.6 — see the requirement below.

**Sonnet 4.6 strictly dominates the fitted lexicon** — everything rule 8 catches, plus all four semantic modes no vocabulary test can reach (`362823` NEPA factors, `360378` a rating scale, `363315` project phases, `363470` M&E workstreams), with zero false alarms at either unit. **PACER's 18 spans passed 18/18 on both models**, which is independent confirmation that the extraction §6.4a calls known-correct is in fact correct.

**Haiku's three span-level false rejections are not model error.** All three were read: the excerpt the pipeline supplied does not describe the titled span. `(i) X-Ray Scattering` was handed *"Applications submitted by February 1, 2026, will be considered for funding in FY 2026"*. Haiku's stated reason — *"Application deadline and fiscal year funding policy"* — correctly describes **the text it was given**. That is the §6.5 summary defect recorded as Cov5, not a classifier limitation; Sonnet got the same three right by weighting the title over the excerpt.

**Haiku's one set-level false positive is the argument for §6.4b.** It flagged `360678` — the DOE Office of Science set, 70 programmes including `(q) Catalysis Science` — reasoning *"List mixes distinct research areas with application requirements, team structures, and policy frameworks."* It was **right about the contamination** and wrong to condemn the set: those are the two members `Multi-Institutional Teams` and `Open Science`, and at span level the same model isolated exactly those two and left the other 68 alone. The set-level false positive and the span-level true positives are one observation at two granularities. See §6.4b.

**Cost, measured rather than estimated.** Steady-state set-level classification is **$0.581 per 100 sets at `claude-sonnet-5` list pricing, $0.291 batched** — the figure to quote. That is **+53% over Sonnet 4.6's $0.380 / $0.190**, and the increase is **tokenization, not the task**: the identical prompt corpus measures **36,811 input tokens on Sonnet 5 against 23,986 on 4.6**. Haiku 4.5 remains $0.129 / $0.065. The 4.6 experiment cost $0.205 for 50 calls; the Sonnet 5 re-baseline cost $0.309 at introductory pricing ($0.463 at list) for another 50. At ~115 umbrella parents catalog-wide (§1.1), a full pass is well under a dollar on any of them. **Cost is not a reason to defer this**, which is a change from what this section assumed.

### Configuration requirement: adaptive thinking must be enabled

**Not optional, and it is the whole difference between 88% and 54% span-level precision.** On `claude-sonnet-5`, omitting the `thinking` parameter runs adaptive thinking; setting `thinking: {"type": "disabled"}` does not. Measured on the same 114 spans:

| `claude-sonnet-5` | contaminants caught | wrongly rejected | precision |
|---|---|---|---|
| thinking at default (adaptive) | 7/7 | **1** of 107 | **88%** |
| `thinking: {"type": "disabled"}` | 7/7 | **6** of 107 | 54% |

**Why:** five of the six rejections under disabled thinking are spans whose *excerpt* is corrupted (Cov5, §6.5), and the model says so in its own reasons — four begin *"Text is…"*. With thinking on, it reasons past the bad excerpt to the title and judges correctly; without it, it takes the supplied text at face value. **So the requirement is really a robustness margin against the Cov5 defect**, and it should be revisited — but not removed — once Cov5 is fixed. *(8.5a: Cov5 is now fixed, so the condition has arrived. Do not act on it from this paragraph alone — the margin was measured against corrupted excerpts, and whether it is still needed is a measurement on clean ones. §18.1 Cov5 carries the re-run that answers it.)*

This variable did not exist on Sonnet 4.6, where thinking-off was the only available behaviour. A later session swapping the model string without carrying this setting would silently halve precision. **Set-level results are identical in both configurations**, so the requirement is span-level only; applying it everywhere is simpler and costs little.

### The Cov5 re-run — measured effect on precision: zero

**Run 2026-08-17 after Cov5 shipped, 6 calls, 0 errors, $0.25.** Prompts were
*imported* from the same experiment rather than rewritten, so the arms are
comparable by construction. Three sets, two arms each: `360678` (the only set
carrying Cov5 spans) plus `349554` and `361526` as controls.

**Exactly 6 of `360678`'s 68 excerpts changed** — the six Cov5 spans, no others.
62 are byte-identical between arms. That is what makes the rest of this readable.

| | Spans | Rejected before | Rejected after |
|---|---|---|---|
| `349554` control | 18 | 0 | 0 |
| `361526` control | 21 | 0 | 0 |
| `360678` affected | 68 → **69** | 1 | 1 |
| **false-rejection rate** | 107 → 108 | **1 = 0.9%** | **1 = 0.9%** |

> **The rate did not move. Cov5's measured effect on span-level precision is
> zero** — and the *identity* of the rejected span changed, which is the
> interesting part.

**The controls did not move at all** — zero rejections in both arms, zero flips.
That is the containment check passing: a fix to six excerpts in one document
changed nothing in two documents that had none.

**Two flips, in opposite directions, and only one of them is Cov5.**

- **`(n) Public-Private Partnerships`: REJECT → accept.** One of the six. Its
  excerpt went from *"simulation for fusion research, and using quantum
  sensing…"* to *"Public-private partnerships (PPPs) enable greater resources to
  be applied…"*.
- **`(h) Quantum Information Science for High Energy Physics`: accept → REJECT
  — on a byte-identical excerpt.** Not a Cov5 span, same input in both arms.
  Its two reasons are also mutually incoherent: it was accepted as *"Named
  technical research topic in quantum information for HEP"* and rejected as
  *"Specific quantum information HEP research topic"*. **This is run-to-run
  variance, and it is the first measurement of caveat 2 below.**

**So the variance is the same magnitude as the effect.** One flip toward the fix,
one away from it, at n=1 each. This run cannot separate Cov5's benefit from noise,
and saying it improved precision would be reading a coin flip. What it does
establish is the containment: nothing outside the six changed on purpose.

**Five of the six were already accepted before the fix.** `(d)`, `(i)`, `(j)`,
`(k)` and `(l)` were all accepted while carrying excerpts about application
deadlines and relativistic physics, with reasons naming their *titles*
(*"Named technical research topic in X-ray scattering"*). That is adaptive
thinking doing exactly what this section predicted — reasoning past a corrupted
excerpt to the title — and it is why Cov5 had little precision left to recover
at this model and setting. **On `claude-sonnet-5` with thinking disabled, or on
`claude-haiku-4-5`, the same six spans were rejected**, so the fix removes a
dependency on that margin rather than improving the margin's own numbers.

**The recovered 69th span is accepted.** `(m) Plasma Science and Technology—
Quantum Information Science` — the candidate Cov5's fix recovered from being
dropped outright — passes the filter. That is a recall gain of one real
subdivision, and it is the clearest user-visible benefit in this run.

**Cov4's gate is not unblocked.** It requires **zero** false rejections on
verified-good spans, and the rate is 1 of 108. The one rejection is now a
variance artifact rather than a corrupted excerpt, which is a different problem
with a different fix — self-consistency, not span construction.

### Two open label questions

Recorded, not resolved. Both are single-labelled by one reader, and both now have model evidence against them. Tracked as §13 open decision 11.

- **`361876`** — labelled *furniture* in D5 (`3.3.1 Food safety` … `3.3.6 Projects and Activities Not Eligible`). Held out of every score above as contested. It is now called **furniture by three of four model-runs** — Haiku, and both Sonnet 5 configurations — against Sonnet 4.6's lone *legitimate*. Sonnet 5's reason is the sharpest given: *"Mixes distinct topic areas with an ineligibility exclusions section, not a coherent choose-one subdivision list."* **Scored rather than held out, Sonnet 5 would be 22/22 at set level.** It stays held out here: one model changing its mind does not settle a label, and reporting 22/22 on a set the corpus itself flags as ambiguous would overstate the result.
- **`(n) Public-Private Partnerships`** in `360678` — carried as a *good* span, and therefore counted as a false rejection against every model that dropped it. **Haiku and both Sonnet 5 configurations rejected it independently.** Its excerpt is also Cov5-corrupted, but its title is plausibly a funding mechanism rather than a technical subject, which is a different objection from the corrupted-excerpt cases. If it is relabelled a contaminant, Sonnet 5 at default thinking becomes **8/8 with 0 false rejections** — but nobody has re-read it, and relabelling a span *because models rejected it* is exactly how an evaluation corpus stops being independent evidence. **A human reads it, or it stays as it is.**

  **Updated 2026-08-17 by the Cov5 re-run, and deliberately NOT closed.** With a clean excerpt the span flips to **accept**. That is real evidence and it is not sufficient, for three reasons that all point the same way:

  1. **The pre-fix rejection was never about the excerpt.** Its stated reason was *"Describes a funding mechanism/partnership type, not a subject"* — a judgement about the **title**, which did not change. So the flip is not the corrupted excerpt being cleared; it is the same title being judged differently with different surrounding text.
  2. **The model's characterisation did not change, only its verdict.** It now accepts the span while calling it *"Specific public-private partnership funding activity"* — still a funding mechanism, which is precisely the objection.
  3. **The same run measured a 1-in-108 flip on byte-identical input.** One flip is exactly the noise floor this run established, so a single flip cannot carry a label.

  **And closing it here would break the rule this bullet exists to state.** Relabelling a span *good* because a model accepted it is the same error as relabelling it *contaminant* because models rejected it. The question is narrowed, not answered: **is `(n) Public-Private Partnerships` a subject an applicant applies against, or a mechanism through which any subject may be funded?** One person reading page 85 of `DE-FOA-0003600` settles it in a minute. Tracked as §13 open decision 11.

### 8.5 — the classifier's role changed, and it is now a precondition rather than a final gate

**Nothing measured in this section changed. What changed is what depends on it.** Through 8.4 the span filter was a precision improvement layered on top of families that already worked: it removed contaminants from `360678` and unsuppressed PACER. `docs/FAMILY_TAXONOMY.md` measured the families and found that they reach **10% of the enumerating population**, and that the two largest uncovered forms — **F4 named/bulleted (~73 records) and F1 bare numbered (~31)** — are both forms where structure carries no signal about whether a set is fundable:

- **F4 is demonstrably unsafe on structure alone.** `362233`'s five real Focus Areas sit one subsection above five decoy bullets — *Innovation, Impact, Research Strategy, Focus Areas, Research Team* — with no ordinal, no outline and no lexical difference to separate them.
- **F1 is unsafe by construction.** A bare `1.` says nothing about whether what follows is a research area or *Allowable Costs*; B0 measured 47, 19 and 74 administrative decimal-numbered lines in three notices.

So the sequencing in §18.1 inverts: **Cov4 lands before any new family work**, because a recogniser for either form, shipped without a semantic filter in front of it, is the fabrication surface D5 spent a package closing. §18.3's exit criteria for F1 name this classifier explicitly.

**One consequence for the gate.** Cov4's validation set was going to come from the Coverage backfill. It should now also include **F1 and F4 candidate sets specifically** — including at least one aggregating agency page (§6.3b) and one grouped-restarting-counter document (`330175`) — because those are the populations the filter will actually be asked to adjudicate, and neither resembles the 22 sibling sets it was measured on.

### Three caveats that bound the result

1. **The prompt names two of the four modes.** It was built around the discriminator *"subjects an applicant chooses among, versus what the awardee does or how a proposal is judged"* — which describes `360378` and `363470` fairly directly. Haiku still missed `363470`, and the lexicon missed both, so the effect is not decisive; but these two are an easier test than `363315` and `362823`.
2. **One run, no self-consistency check.** Single-shot calls, no repeats, no temperature sweep. ~~Run-to-run variance is unmeasured.~~ **Partially measured 2026-08-17, and it is not negligible.** The Cov5 re-run put 62 byte-identical excerpts through the same prompt twice and **one of them flipped** — `(h) Quantum Information Science for High Energy Physics`, accepted in one arm and rejected in the other, with mutually incoherent reasons. That is a **1.6% flip rate on identical input (1 of 62)**, against a false-rejection rate of 0.9% that the same run was trying to measure. **The noise is larger than the signal**, which means every span-level figure in this section carries an uncertainty of roughly one span, and Cov4's "zero false rejections" gate cannot be demonstrated by a single pass. Cov4 must specify repeats — majority-of-three is the obvious form and is what §18.1's adversarial-verify pattern already does elsewhere.
3. **21 sets and 114 spans, one backfill, one labeller.** `361876` is openly contested. This is enough to justify building; it is not enough to trust unvalidated on new data, which is why Cov4's gate requires exactly that.

### What is still out of scope

- **Discovering topics.** Unchanged and absolute. The model classifies spans deterministic segmentation already located, and may never emit a `subtopic_code` absent from the source span.
- Reading the Genesis `Focus Areas` spreadsheet needs a spreadsheet reader, not a model.

Not built in v1. Recorded so the deterministic design does not preclude it.

**Adds:** cleaner human-readable summaries, normalized dates written in prose, consistent phrasing across agency formats. Polish, not mechanism.

**Does not do:** discover topics. The model would only label and summarize spans deterministic segmentation already located, and would be forbidden from emitting a `subtopic_code` not present verbatim in the source span.

**Cost if enabled:** a small/fast-tier model on ~2,250 spans for a full backfill (~1,200 input / ~250 output tokens each) is on the order of a few dollars, or roughly half that through the Batch API. Steady state, gated by the existing hash change detection, is a few hundred spans per week — a couple of dollars a month. Confirm current model names and per-token pricing at the time this is considered rather than trusting a figure written in 2026; the estimate's *shape* (single-digit dollars for backfill, negligible steady state) is what matters here, and it is robust to a lot of pricing drift.

**Secret handling if enabled:** key in a protected GitHub environment; workflow triggered only by `schedule` and `workflow_dispatch`; `pull_request_target` never used; no derived value echoed. The key never touches committed output.

## 12. Risk register

| Risk | Mitigation |
|---|---|
| ~~The per-subtopic 2 KiB ceiling is arithmetically impossible as written~~ **Resolved 2026-08-17 — the ceiling was measuring the wrong artifact** | The ceiling now bounds the **display payload** that ships to the browser, not the build-time cache record. Measured: display payload is **median 942 B, max 1,218 B, 0 of 223 over 2 KiB**; the cache record is 60.3% `subtopic_terms`, which lives in the sidecar's index and never reaches a card. Former §13 decisions 0 and 1, both now settled |
| **Catalog inflation — the numbers, since v6.2's budget was unusable** | `opportunities.js` measures **23.6–24.8 MB** across recent builds for ~1,475 records; it fluctuates nightly, so treat any single figure as a snapshot. A 1.5× multiplier would set a ~37 MB ceiling, which is not a budget — it is permission to nearly double. Use **absolute** limits instead: hard fail above **32 MB**; warn above **28 MB**; and cap *per-subtopic* cost at **2 KB** serialized. **Rewritten 2026-08-17 — what the 2 KB bounds, and the sentence that was wrong.** The ceiling applies to the **display payload**: the fields a card renders — identity, code, title, summary, page anchors, status, topic areas, deadline, confidence. Measured across the D5 cache: **median 942 B, max 1,218 B, 0 of 223 records over budget.** It does **not** apply to the build-time cache record, of which **60.3% is `subtopic_terms`** — retrieval data that folds into the sidecar's index (§5.2) and never reaches the browser as record content. ~~If a design needs more, cut `max_terms`, not the ceiling.~~ **That instruction is unachievable and is withdrawn:** the ceiling is violated identically at every cap from 400 to 100 (202/223), passes only at 5 terms, and at *zero* terms the largest record still occupies 1,930 of the 2,048 bytes — the term map never had more than ~6% of the budget to work with. `MAX_TERMS` stays at 400 (§13, settled). **The aggregate budget passes unchanged:** `opportunities.js` is **23.69 MiB** today and 1,000 spans at 400 terms would bring a merged file to **27.43 MiB — under the 28 MiB warn line** — and under the sidecar decision it does not merge at all, so the parent catalog is byte-identical. GitHub warns on files above 50 MB, so 32 MB also preserves headroom for ordinary catalog growth |
| Result pollution: 20 topics plus parent all match one query | Max-score rollup; collapsed rendering; no independent parent entry |
| Phantom `subtopic_amended` flood after a library upgrade | Exact pins on `pdfplumber`, `pdfminer.six` **and** `pypdf` (§6.1) — `pdfminer.six` especially, since it is transitive and actually drives extraction; versions embedded in `extractor_version` make the cause visible in the diff |
| **AGPL contamination from PyMuPDF** | Settled in §6.1: `pdfplumber` (MIT) + `pypdf`. §0.4 rule 7 names the one authorized new dependency. A future session "optimizing" Layer C by reaching for `fitz` reintroduces the licence problem silently |
| **Subtopics never backfill onto the ~1,400 already-cached documents** | The three-gate backfill trigger in §8.3. This is the single most likely way for the feature to appear to work while doing almost nothing |
| **`pdfplumber` memory exhaustion on a large BAA** | Page cap (120), `page.flush_cache()` per page, per-document time budget (§6.1). Layer C runs only after Layer A declines |
| **New `data/` file silently untracked, or the commit step aborts** | `.gitignore` allowlist line **and** `git add` path, same commit; §9.4 checklist item 7 verifies it |
| **Browser refuses to start because catalog invariants broke** | Children appended and indexed in one write; `record_count` and `search_index.document_count` move together (§4, §7.1) |
| Amendment renumbering produces false diffs | Title-first matching (§5.3) |
| Git repository growth from daily cache commits | Sorted stable serialization; volatile fields updated only on real change (§5.4) |
| `currentness.py` evicts parent and child inconsistently | Explicit rule (§7.2) plus interaction tests — in **four** places: the Python module and three browser re-implementations |
| First run floods change feed and digest | Backfill suppression (§10 step 23). The local single-run backfill (§8.3) gives one marker date, so the rule stays simple. Note the change-event work is deferred in the minimum path (§18.2), which removes this risk from v1 entirely |
| **Segmentation fails on every document and nobody notices** | Step 10 is `continue-on-error` with no `id:`, so its failures open no issue at all (§9.3). Diagnostics block plus deliberate review during the Phase 2 observation window |
| **Both auto-issue channels are already open and recurring — this predates the subtopic work entirely** | **#30 "External funding source refresh degraded"** has been open since 2026-08-09 with 19 comments and updates on essentially every run, because `jhu-fellowships` reports `failed_no_fallback`. **#29 "Automated Grants.gov refresh failed"** has been open since 2026-08-08 with 6 comments. Neither was caused by this project and neither is this project's to fix. Because the workflow comments on an existing open issue of the same title rather than opening a new one, **no new issue number will ever appear for either**, which is why §9.4 item 4 checks issue *numbers*. Resolve `jhu-fellowships` separately (§7.4); until then, watch the Actions run conclusion directly rather than trusting the issue channel |
| **No recorded runtime baseline** | Total job wall-clock is not stored in the repository — only in Actions run history, which ages out. The 2:20–3:30 figure came from reading run summaries by hand. Record the absolute duration on every dispatch run (§9.4 item 2) so the trend toward the 15-minute ceiling is visible before it is breached |
| Segmentation false positives on reference lists | Acceptance rules (§6.4); nothing below `high` publishes without an explicit hash-bound approval (§7.1, §18.1 Cov4) |
| **REALIZED 2026-08-17 — a pattern family that never fires is invisible to every metric in this plan** | Seven of §6.3's ten families accumulated unmeasured across four work packages: **five never fired once across 170 real documents, and two fired only on documents carrying no list** (`roses_element` on `A.1 BACKGROUND AND OBJECTIVES`, `area_of_interest` on another opportunity's topics). Nothing caught it because acceptance rate, false-positive count and the rejection histogram are all computed **per document**, so a family contributing nothing contributes nothing to any of them, and a passing synthetic fixture (§10 step 11) looks identical to real coverage. Mitigation is §17.8: a validating document **quoted** per family, and **per-family fire counts reported including the zeros**. B0 had the evidence in 2026-08-16 — zero matches from all ten families on three notices — and read it as the families being appropriately narrow |
| **A family matches the container instead of its members, which is worse than missing** | `thrust` fires on DTRA `356612` — a real hit — and matches `Thrust Area 1`, the umbrella, while the fundable list is `Topic A1`–`A7` beneath it. That segments one plausible card where seven belong, so it presents as a success in every count. Acceptance rules cannot see it: one candidate simply fails rule 1 and the set is silently declined, or worse, passes with the wrong granularity. Mitigation: §18.1 Fm4 scopes or retires it, and §17.8 requires the validating quote to be **at the granularity the family claims** |
| **Agency-HTML scrapers break silently, and structured sources are where this hurts most** | A restyled page returns **HTTP 200 with zero rows**, and every existing check passes: the fetch worked, nothing raised, and zero subtopics is a normal outcome (§9.3). **This is a durability tradeoff and it should be stated plainly rather than assumed away.** Generic PDF parsing is robust to agency redesigns — a bookmark tree is a bookmark tree — and buys weak evidence: §6.3 measures the families at 10% of the enumerating population, and 7 of 10 were retired with no corpus support. A ROSES table parser is strong evidence and **brittle against a site redesign nobody warns us about**. D⅝ chooses the brittle-and-strong option deliberately, on the argument that a loud failure is recoverable and silent weak coverage is not — but the maintenance surface is real and grows per source, which is exactly why §18.1 D⅝ builds **one** adapter and re-measures rather than three. Mitigation: **§7.4 canaries**, one per source, asserting a floor rather than a count; a canary failure is a source-health failure that publishes nothing new for that source and opens the owner issue |
| **`--max-documents` caps each pass, not the run — so the flag understates the work by 2× with subtopics on** | Measured by reading the call site: `refresh_subtopics_without_source` is passed **the same `max_documents` value** as the administrative pass (`extract_document_evidence.py`, the Cov1 insertion under `if enable_subtopics`), not a share of it. Each pass independently takes `candidates[:max_documents]`, so `--max-documents 45` can fetch up to **90** documents and the D4/D5 backfills' `--max-documents 1200` could attempt **2,400**. Nothing is wrong with the results; what is wrong is that the nightly's runtime headroom (§9's 15-minute ceiling) and every published backfill figure were reasoned against one pass. Either split one budget across both passes or give the subtopic pass its own named flag — **do not silently halve the existing default**, which is load-bearing (§0.4 rule 8) |
| **An evidence entry outlives the record that produced it, and is then never rechecked** | Measured: **13 orphans** in the catalog — records carrying an evidence entry whose parent no longer resolves to a source, 12 of them `primary_notice`. `363526` is the named case and was the corpus's only high-confidence acceptance. Separately, **213 cache entries belong to records that have left the catalog entirely**. Neither population is pruned, neither is refetched, and both inflate any denominator computed from the cache rather than from the catalog — which is exactly the error `docs/COVERAGE_SURVEY.md` corrected when it replaced "246 of 1,016 evidence entries" with "685 of 1,475 catalog records". Mitigation: prune on the catalog, never on the cache, and compute every rate against the catalog (§15 debt) |
| **A rate is quoted against a denominator that has since changed** | Measured, twice. `360339` — one of the census's twelve enumerating documents and the sole validating record for the `component` family — **left the catalog within a day of the census being taken**, along with `362005` and `362711`. Every acceptance rate quoted as "of 12" silently became "of 11". The corpus moves under the measurements: 3 of 20 census records were gone within 24 hours. Mitigation, already stated in `docs/CORPUS_CENSUS.md` and now a rule here: **re-derive a denominator at the moment you quote it, and name the date.** Do not compare a rate to a figure from a previous session without re-deriving both |
| **A summary that describes the wrong subject reaches a PI and a classifier at once** | Cov5, realized and fixed 2026-08-17 (§6.5). Six of 223 spans carried excerpt text from a neighbouring section because one loose regex could not bridge a `pdfminer`-inserted space beside a hyphen. **It was found by a classifier rejecting the spans and stating why, not by any check in this plan** — no test, gate or histogram covers "does this summary describe its own title?". The residual is the still-silent `page_start_offset` fallback; the mitigation available today is that Cov4's classifier reads the same string a PI would, so a corrupted excerpt shows up as a rejection rather than as a bad card |
| New agency template breaks segmentation | Fails closed to zero topics; rejection reason logged and monitored (Phase 4, step 30) |
| SAM.gov quota exhaustion | Prefilter before description calls; cache descriptions by notice id (§7.5) |
| Eval discontinuity | Query baseline frozen before any change (Phase 1, step 2, §8.5) |
| BES-style omnibus yields zero topics and looks like a bug | Expected and correct. Note the record is **already** discoverable via `discoverability.py`; what is missing is child granularity, covered by the referenced-subtopic path (§6.7). Track `no_layer_accepted` separately from genuine failures in the diagnostics block |
| Topic cards look obscure and get ignored, so recall rises but clicks fall | Match explanation is a **requirement**, not a nicety (§7.6); ship `FF_MATCH_EXPLAIN` before or with topics |
| Match chips render stems ("electrocataly") | `term_display` map (§5.1, Phase 3 step 22c) |
| Team match floods with one researcher × 20 topics | Top-3-per-parent cap (§7.7) |
| Team match drifts with the flag off, outside the hermetic gate's reach | Explicit manual A/B in Phase 3 step 23b |
| Muted items still appear in email/Atom alerts | Known split (§7.2b); documented in help; optional suppression-list export |
| A mistaken mute hides something permanently and invisibly | Muted-items panel is mandatory (§7.2b) |
| Three years of expired topics inflate every page load | Archive written to a separate lazily-loaded `data/subtopic_archive.json` (§7.2) |
| Scheduled workflow silently disabled after 60 quiet days | Unconditional heartbeat commit every run (§16.3); quarterly manual check that the schedule is enabled |
| Missed or delayed cron run | Change-detection ladder makes runs idempotent and self-healing; nothing assumes yesterday ran (§16.3) |
| SAM.gov key invalid or revoked | Existing source health gate opens the owner issue; it is the only credential in the system (§16.1) |
| Runtime ORCID lookups hammer OpenAlex or fail offline | `mailto` polite pool, browser-cached results, roster path degrades gracefully (§7.9) |
| Silent behavior drift in a "harmless" refactor | Hermetic no-drift gate on frozen inputs (§8.4), passing from Phase 1 onward |
| New cache never persisted because it is missing from `git add` | Explicit workflow requirement (§9.3); symptom is every subtopic appearing new each night |
| Segmentation raises and trips the issue automation | Zero subtopics is a normal outcome and never raises; the call site catches broadly (§9.3) |
| Pathological PDF hits the job timeout and blocks the publish | Per-document time budget and page cap (§6.1) |
| Formatter run buries a small change in an unreviewable diff | Explicit no-reformat rule (§8.1) |
| **A later session reintroduces a corrected error** | This plan's own §17.2 loop: RECON.md is the evidence, the "What changed in 7.0" table is the index of what was wrong, and both stay in the repository |

## 13. Open decisions

**Settled** — recorded here so they are not relitigated:

- **PDF toolchain: `pdfplumber` (MIT) + the existing `pypdf`.** Not PyMuPDF, which is AGPL-3.0 and conflicts with this repository's all-rights-reserved posture and possible commercial licensing (§6.1).
- **Segmentation runs inside `extract_document_evidence.py`'s existing pass**, at a minimal flag-guarded call site, with the logic in new modules (§6.1a, §8.3).
- ~~**Low-confidence segmentations stay hidden**, not surfaced with a warning.~~ **Revised 2026-08-16 (8.2).** The principle is unchanged and the mechanism is not: **nothing below `high` auto-publishes, and `low` *and* `medium` are routed to a review queue** rather than discarded (§18.1 Cov4). The binary gate was changed because it was measured suppressing a known-correct 18-span extraction (AFRL PACER) while no threshold setting could admit it without re-admitting D4's fabrications. A wrong topic is still worse than a missing one; what changed is that a threshold no longer decides which is which. **Refined 2026-08-17 (8.3):** the decision is made per **span**, not per set (§6.4b), by a measured classifier first (§11) and a human on the residual — and when the classifier is unavailable the run publishes nothing new rather than publishing unfiltered.
- **Expired topics are retained 3 years and flagged**, in a separate lazily-loaded `data/subtopic_archive.json`, excluded from default search and alerts (§7.2).
- Team match takes **ORCIDs only**. Resume and free-text belong to the personal browser-local profile (§7.9).
- Profiles are built from **works text, not assigned concepts**. ORCID is an identity key (§7.9).
- **The regression gate is a frozen query set compared on result IDs and ranks**, not a labelled baseline (§8.5).
- **`MAX_TERMS` stays at 400 — closes former open decision 0 (2026-08-17).** Measured against the uncommitted D5 cache (223 spans): the 2 KiB per-record ceiling is violated **identically at every cap from 400 down to 100 — 202 of 223 in all four cases**. Cutting terms does not move that number, because the term map is not what breaches it. The test passes only at **5 terms per span, costing 74.8% of BM25 mass** on the §8.5 query set. At **cap 0 — no term map at all — it passes with the largest record at 1,930 B**, i.e. the entire term map has **118 bytes**, about 6% of the ceiling, to live in. So **§12's instruction "cut `max_terms`, not the ceiling" is not a hard trade, it is unachievable**, and that sentence is corrected in §12. The cap also barely binds today: median map is **185 terms**, only 15 of 223 spans (7%) reach 400, and none exceeds it. *If a cut is ever wanted for an unrelated reason, **200 is the defensible one** — 3.8% BM25 loss for 14% of cache size; **100 is a poor trade** at 13.7% for 33%.* The real fix is the budget's subject, not its value — see the next bullet and §12.
- **Subtopics ship in a lazily-loaded `data/subtopics.js` sidecar — closes former open decision 1 (2026-08-17).** Two independent arguments converge, which is why this is now settled rather than recommended:
  1. **`record_count` (§13.1).** In-catalog children force `opportunities.length === record_count` to include subtopics, silently changing the meaning of a **published** number with at least five consumers — README/PROJECT badges, `--min-records`/`--max-record-count`, the browser's small-catalog assertion, and `validate_catalog`'s growth bound. "1,475 opportunities" becoming "2,400" is a schema change in substance.
  2. **The display/retrieval split (measured 2026-08-17).** **60.3% of every cache record is `subtopic_terms`** — retrieval data the browser consumes through an index, never as card content. Strip it and the fingerprints, and the display payload is **median 942 B, max 1,218 B, 0 of 223 over the 2 KiB ceiling**. The budget and the storage question are the same question: the term map does not belong on the record.
  **§13.1's flip condition is retired.** It said the recommendation flips to Option A if cross-corpus scoring cannot be normalized. That was written when `record_count` was the only argument; the display/retrieval split is independent of scoring and holds regardless. **Cross-corpus normalization does not go away — it is package E's E1, and it is now a "make this work" task rather than a "decide this" one.** If E1's prototype fails the §8.5 gate, the answer is normalization work, not re-merging into `opportunities.js`.
- No external deadline. Sequence for safety, not speed.

**Still open:**

2. **Where referenced subtopics live.** **Surfaced in full in 8.6 — this was
   recorded as "deferred to a human" fifteen sessions ago and has never been
   decided, and a one-line pointer to §6.7a was not enough to get it decided.**

   **The question.** RECON established that `discoverability.py` already owns the
   linkage between an omnibus FOA and the program areas it funds, for exactly the
   solicitations this feature targets. So the question is not "build an adapter or
   not" — it is **whether referenced subtopics extend the existing registry or sit
   beside it.**

   | | Option 1 — extend `discoverability.py` | Option 2 — a new `adapters/program_taxonomy.py` |
   |---|---|---|
   | Linkage rule | Exists exactly once, in the file that already owns it | Exists in two files that can disagree, unless imported |
   | Fetching | `discoverability.py` has **no fetch layer at all** today; adding one changes it from a pure function over records into a network client | Fetching is what adapters do — `PoliteClient`, retry, health bounds, last-known-good snapshots, degradation alerting, all free |
   | Failure surface | Zero new adapters, zero new health-gate surface | A new enabled adapter is a new way for the nightly to report degraded, and that channel is already noisy (`jhu-fellowships` fails today) |
   | Coupling | Couples umbrella tagging to the subtopic feature; a bug in one breaks the other | Independently switchable |
   | Ordering | Child emission inside `merge.integrate` happens *after* `build_search_index` has run; the merge must rebuild the index, which it does, but the ordering becomes load-bearing and subtle | Matches how every other external source here is structured |
   | Content | The registry becomes a content store — program descriptions are prose, and prose in a `.py` file does not scale | Emits *child* records, which no existing adapter does; `merge_records` and `validate` may need `parent_id` either way |

   **Recommendation: Option 2, with the linkage rule imported rather than
   duplicated.** The decisive argument is that this feature *fetches from the
   network on a schedule*, and this repository has one well-tested pattern for
   that. Rebuilding health bounds, snapshot retention and fail-closed behaviour
   inside `discoverability.py` is strictly worse than reusing them. Option 2's
   only real objection is duplicated linkage, and that dissolves if the adapter
   reads umbrella identity **from** the registry — `from ...sources.discoverability
   import PROGRAM_RULES`, matching the parent by asking which records a rule
   matched, never by restating the FOA number. Detect the annual roll-over by
   title pattern, as `discoverability.py`'s `triggers` already does.

   **What has changed since this was deferred, and it shrinks the decision.**
   §18.2's reassessment found that the *children themselves* are in the notice and
   reachable by `structural_siblings` today — `(q) Catalysis Science` is a bookmark
   at a citable page. So whichever option wins now owns only **program-manager
   identity, stable per-program URLs, taxonomy depth below what the notice prints,
   and cross-year program identity.** That is materially smaller and less urgent
   than the decision as originally written.

   **What would decide it:** nothing further needs measuring. This is a
   human's architectural call, and it is not on the critical path — no package
   A–G or D½/D¾ item depends on it. **Full tradeoff tables remain in §6.7a.**
3. **Works-text provider** — add abstracts to the existing Crossref path, or switch the browser to OpenAlex for better abstract coverage (§7.9). Decide on measured results from the §8.5 gate, not on argument.
4. **Whether to build `scripts/build_gold_set.py` at all.** Dropped from Phase 1 because §8.5 replaces it as a *regression* gate. It remains the only way to judge whether a change is an *improvement*. Tracked upstream by **#8** (produce labels) and **#9** (export them); a gold set is not buildable until at least #9 ships. Proposed: revisit after Phase 3, when there is a concrete question that rank movement alone cannot answer.
5. **How archived subtopics are searched.** They sit outside `search_index`, so the "include past cycles" filter needs either a separately shipped index or substring matching (§7.2). **This decision largely collapses into the now-settled sidecar** — subtopics ship as a sidecar with their own index (§13 settled), so the archive is the same mechanism with a different retention window. What remains is only the retention window and whether the archive index ships at all.
6. **Summary length.** 600 chars proposed. The term map carries retrieval, so this is purely a display-quality call.
7. **Topics in Atom feeds.** Proposed: include, since a new topic under an existing umbrella is exactly the event the current feed misses.
8. **Taxonomy depth for referenced topics.** Attach at program level (BES → Catalysis Science) or one level deeper? Proposed: program level, where the program manager and the funding decision sit.
9. **Mute/alert split.** Accept that muted items still appear in alerts, or build the suppression-list export? Proposed: accept for v1, document it plainly, revisit if it annoys anyone. The mute control itself is **#8**.
10. **OCR.** Deferred. Revisit only if `no_extractable_text` rejections prove material.
11. **Two label questions in the §11 evaluation corpus**, recorded rather than resolved — `361876` and `(n) Public-Private Partnerships`. Both are single-labelled, and both carry model evidence against the recorded label. Neither changes a published number; neither should be silently "corrected" by whoever next touches the corpus. **Narrowed 2026-08-17 by the Cov5 re-run and still open.** `(n)` flips to *accept* once its excerpt is clean — but its pre-fix rejection reason was about the **title**, which did not change; the model still calls it a *"funding activity"* while accepting it; and the same run measured a 1-in-62 flip on byte-identical input, so one flip is the noise floor. **The decidable question is now one sentence: is `(n) Public-Private Partnerships` a subject an applicant applies against, or a mechanism through which any subject may be funded?** One person reading page 85 of `DE-FOA-0003600` settles it. Do not settle it from a model verdict in either direction — that is how an evaluation corpus stops being independent evidence.

12. **The `deadlines` payload duplicates itself, and it is 17.5% of
    `opportunities.js`.** **Measured 2026-08-17 against the committed catalog.
    Independent of subtopics — this is pre-existing catalog cost that the sidecar
    decision (§13 settled) does nothing about, and it is larger than anything the
    subtopic layer proposes to add.**

    | | Bytes | Share of `opportunities.js` |
    |---|---|---|
    | `deadlines` payload, all 1,393 records carrying one | **4,351,475 (4.35 MB)** | **17.5%** |
    | of which: `note` byte-identical to `citation.quote` | 876,134 (0.84 MiB) | 3.5% |
    | of which: identity fields cloned per date | 496,679 (0.47 MiB) | 2.0% |
    | of which: quote text literally repeated across dates | 256 | ~0% |
    | **removable duplication** | **1,373,069 (1.31 MiB)** | **5.5%** |

    **Two distinct duplications, and the smaller one is the one usually named.**
    `note` repeats `citation.quote` verbatim in **2,438 of 2,765 note fields
    (88.2%)** — that is the dominant term. Separately, every date entry carries its
    own full `citation` object, so `document_url`, `citation_url`, `document_name`
    and `sha256` are cloned per date across **481 records with more than one dated
    citation**; the distribution runs to **13 dates on one record**. The *quotes*
    mostly differ per date, so "the full citation is cloned" is true of the
    document-identity fields and not of the quote.

    **Why this is a decision and not a defect fix.** Dropping a duplicated `note`
    changes a **published artifact's shape**, which is §0.5 territory: the
    hermetic gate will flag it, correctly, and the browser reads `note`. The three
    options are (a) drop `note` when it equals `citation.quote` and have consumers
    fall back to the quote, (b) hoist document identity to one per record and have
    date entries reference it, (c) leave it and spend the 5.5%. **Proposed: (a)
    then (b), in that order and in separate commits**, because (a) is 0.84 MiB for
    one conditional and (b) is a schema change with a browser consumer.

    **Not urgent.** 23.69 MiB sits under §12's 28 MiB warn line with room, and
    subtopics ship in a sidecar so they do not add to this file. Recorded because
    a later session measuring catalog growth will find 17.5% in one field and
    should find this analysis with it rather than redoing it.


*Removed from this list:* "confirm the exact all-rights-reserved notice" — the `copyright` file already carries it and the work is done.

**Existing issues covering this ground.** This plan was written as a standalone document and does not reference the issue tracker. Three open issues overlap it directly, and work here should be filed against them rather than duplicating them:

| Issue | Title | Overlap |
|---|---|---|
| **#7** | Parse primary NOFO documents during the scheduled workflow | The parent issue for `extract_document_evidence.py` itself — page limits, review criteria, cost share, contacts, eligibility. The subtopic layer is a **second consumer of the same fetched bytes** (§2), so §6 and §8.3 are work *inside* #7's scope, not alongside it. The §6.1 toolchain decision and the §8.3 call site both land here |
| **#8** | Add browser-local relevance labels and reason codes | §7.2b's "not relevant" control **is this issue.** Same control, same reason-code vocabulary, same browser-local storage. Phase 3 step 28 partially delivers it |
| **#9** | Export a privacy-safe matching evaluation dataset | The labelled-export path §8.5 works around and §10 step 33 depends on. Blocked on #8 |

Two consequences worth acting on: **§7.2b should be designed against #8's stated vocabulary** ("useful, not relevant, pursue" plus mismatch reasons — topic, eligibility, award size, deadline, career stage, already known) rather than inventing one; and **§10 step 33 should be marked blocked on #9** rather than merely conditional, since that is where the dependency actually sits.

### 13.1 Former open decision 1, in full — catalog child records vs. a lazily-loaded sidecar

> **Settled 2026-08-17: the sidecar.** The analysis below is retained because it is the argument, and because a later session deserves to see why rather than be told. Two things in it are now superseded: the "Recommendation" heading is a decision, and its **flip condition — revert to Option A if cross-corpus scoring cannot be normalized — is retired**, because the display/retrieval split measured in §12 is independent of scoring and settles the question on its own. Cross-corpus normalization remains real work; it is package E's E1, and it is now a task rather than a fork in the road.

§7.1 asserts that subtopics enter `data/opportunities.js` as child records, and calls it "the single most important structural decision." It is, which is why it deserves an argued alternative rather than an assertion. The measurements below were not available when §7.1 was written.

#### What the catalog is actually made of

`data/opportunities.js` — 23.6 MB total:

| Component | Size | Share |
|---|---|---|
| `opportunities` (1,475 records) | 22.54 MB | 95% |
| `search_index` | 2.51 MB | 11% |

Within the records, three fields dominate:

| Field | Size | Share of file |
|---|---|---|
| `document_evidence` | 8.59 MB | 36% |
| `deadlines` | 4.35 MB | 18% |
| `document_search_text` | 2.96 MB | 13% |

*(Components measured independently and do not sum exactly to the file size — nested subtree serialization differs from the minified whole. Treat them as proportions, not addends.)*

Two facts follow, and they point in opposite directions:

- **Average record cost is ~15.6 KB.** A 2-KB subtopic (§12) is *cheap by comparison* — roughly an eighth of an existing record. A thousand subtopics add ~2 MB, about 8% growth. That is not the catastrophe the size-budget row implies, and it is a real argument for §7.1.
- **The browser already downloads 23.6 MB on every cold visit, and 68% of it is machine-extracted evidence text nobody reads until they open a card.** The page is already heavier than it should be. Adding to it is defensible; adding to it *by default, for a feature used occasionally* is the same mistake §7.2 already refused to make for the expired-subtopic archive.

#### Option A — child records in `data/opportunities.js` (§7.1 as written)

Subtopics are appended to `opportunities`, indexed into the same `search_index`, and carry `parent_id`.

**For:**

- **Everything downstream works with no rewrite.** This is the genuine and large win. BM25 retrieval, filters, sorting, facet counts, Atom feeds, `alert_match.py`, CSV export, the rating UI, and `team-researchers.js` all iterate `catalog.opportunities` and score against `catalog.search_index`. A child record is just another record to all of them.
- **One index, one scoring pass, one rollup.** §7.3's max-score parent absorption is a comparison between numbers produced by the same scorer. Across two indexes it becomes a comparison between numbers produced by two different scorers over two different corpora, with different IDF denominators — which is not obviously meaningful and is certainly not a one-line change.
- **Build-time consumers get it free.** `build_feeds.py`, `build_changes.py`, `update_catalog_docs.py`, `faculty_match.py` and `check_links.py` all read the catalog through `load_catalog`. A sidecar is invisible to every one of them unless each is taught to load it.
- **Per-record cost is genuinely small** relative to what is already there.

**Against:**

- **The `validateCatalog` invariants make this all-or-nothing.** `assets/app.js` throws unless `schema_version === 3` exactly, `opportunities.length === record_count`, and `search_index.document_count === record_count`. So `record_count` must include subtopics — which means **every existing consumer of `record_count` silently changes meaning.** `update_catalog_docs.py` writes it into README and PROJECT badges; `build_catalog.py`'s `--min-records` / `--max-record-count` validation bounds it; the browser's "unexpectedly small catalog" check tests it; `validate_catalog` in `sources/merge.py` bounds growth at `len(base) + 20000`. "1,475 opportunities" becoming "2,400 opportunities" is a **published, user-visible number** that would now mean something different without anyone deciding it should.
- **The positional posting index is fragile under this change.** `postings` is `[docId, tf, …]` and `document_lengths` is a positional array, both indexed into `opportunities`. Children must be strictly appended, and the index rebuilt in the same write. Any future change that sorts, filters or dedups `opportunities` between index build and serialization silently corrupts every posting. Today nothing does that — but `check_links` already re-serializes the catalog *without* rebuilding the index, so the invariant is currently held by convention rather than by construction.
- **It taxes every visitor for a feature most will not use.** Cold-load weight is the one cost paid by everyone.
- **Facet counts get strange.** `facet_counts` counts records per facet value. With children included, "Catalysis and reaction engineering — 47" mixes solicitations and subdivisions of solicitations. Either the facet counts become misleading or `facet_counts` learns to exclude `record_type === "subtopic"`, which is another existing function changing behavior.

#### Option B — a lazily-loaded `data/subtopics.js` sidecar with its own compact index

A second generated asset, fetched on demand — on first search, or when a parent card is expanded — carrying its own records and its own BM25 index over `subtopic_terms` only.

**For:**

- **Zero cold-load cost.** `opportunities.js` is byte-identical with the feature shipped, which makes §0.5 flag-off parity trivially true for the largest artifact and removes the size-budget question entirely.
- **`validateCatalog` is untouched.** `record_count`, `document_count`, `schema_version` and every published count keep their current meaning. No existing consumer changes behavior.
- **No positional-index hazard.** A separate index over a separate array cannot corrupt the parent postings, because it does not share them.
- **A compact index can be much smaller than a shared one.** Subtopic postings only need `subtopic_terms` and `title` — not the 11-field weighted blend `build_search_index` computes for parents. And `document_search_text`, 13% of the current file, has no subtopic equivalent at all.
- **It is the same mechanism §7.2 already requires** for `data/subtopic_archive.json`. Building one lazy-loading path and using it twice is less work and less surface than building a lazy path for the archive and an eager path for live subtopics.
- **Failure is graceful.** If the sidecar 404s or is slow, the site works exactly as it does today. A malformed child record inside `opportunities.js` throws `validateCatalog` and the application does not start at all.

**Against:**

- **Every build-time consumer must be taught to load it.** `build_feeds.py`, `build_changes.py`, `alert_match.py` and `faculty_match.py` read one file today. This is real, distributed work, and it is exactly the "no rewrite" benefit §7.1 was designed to capture. Some of it can be avoided — feeds and alerts may legitimately not want subtopics in v1 — but that is a scope decision that then has to be made explicitly for each consumer.
- **Cross-corpus scoring is a genuine research-shaped problem, not a plumbing problem.** Two BM25 indexes produce scores on different scales because IDF depends on corpus size and term distribution. §7.3's `Math.max(parentScore, ...childScores)` is meaningless across scales without normalization, and picking a normalization is a judgment call that affects ranking quality directly.
- **Two files to keep consistent.** A subtopic whose parent has been dropped from the catalog is now possible in a way it is not when both live in one file. Needs an explicit consistency check.
- **`team-researchers.js` loses its free ride.** It is the one scorer that inherits subtopics automatically under Option A (§7.7); under Option B it needs the sidecar and the cross-corpus normalization too.

#### Recommendation: Option B, the sidecar — with the scoring problem confronted first

The decisive consideration is that **Option A changes the meaning of `record_count`**, and `record_count` is a published number with at least five consumers, one of which is a hard browser assertion and another of which is a build-failure bound. §8.1's rule is that no existing data file changes schema and readers tolerate absence; making 1,475 become 2,400 is not a schema change in form, but it is one in substance, and it is the kind that produces a confusing bug report six months later rather than a failing test today. Option B leaves every existing meaning intact, which is what the additive discipline in §8 is actually for.

The size argument is secondary and weaker than it first appears — 2 MB on a 23.6 MB file is not decisive on its own. But it compounds: the file is *already* too heavy, 68% of it is evidence text, and the honest reading is that `opportunities.js` needs to get smaller rather than absorb another feature. Option B is at worst neutral there and at best the first step toward splitting the heavy fields out too.

**The recommendation is conditional on one thing being resolved first.** Cross-corpus score normalization is the real cost of Option B, and it is the part most likely to be underestimated. Before committing, prototype §7.3's rollup across two indexes on the frozen catalog and check it against the §8.5 query set. If parent/child scores cannot be made comparable in a way that survives that gate, **Option A's single-index simplicity is worth its costs** and the recommendation flips. Do not choose the sidecar on architectural grounds and discover the ranking problem in Phase 3.

Whichever is chosen, three things hold either way: the per-subtopic 2 KB cap (§12); the archive stays a separate lazily-loaded file (§7.2); and nothing below `high` ships unreviewed (§7.1, §18.1 Cov4).

## 14. Glossary

| Term | Meaning |
|---|---|
| **Umbrella** | A solicitation whose fundable units are subdivisions of itself: a BAA, an omnibus NRA, a multi-topic FOA. Detected structurally (§3), never from a list. |
| **Topic** | A fundable subdivision of an umbrella. The new child record type. Two flavors: `inline` (enumerated in the notice PDF) and `referenced` (published in an agency program taxonomy, §6.7). |
| **Parent** | The solicitation record a topic belongs to. Topics inherit agency, eligibility and the filtering deadline from it (§5.5). |
| **Span** | The contiguous run of text belonging to one topic, bounded by its heading and the next sibling heading. Ephemeral — never stored (§5.2). |
| **Term map** | Stemmed term-frequency dictionary. Carries BM25 retrieval without storing readable prose. Used for both topics and researcher profiles. |
| **`term_display`** | Stem → surface-form map, display only, so match chips read "electrocatalysis" rather than "electrocataly" (§7.6). |
| **Segmentation** | The deterministic four-layer process that locates topic boundaries in a document (§6.2). |
| **Acceptance rules** | The seven conditions a segmentation must satisfy before publishing. Failure means zero topics, never partial topics (§6.4). |
| **Hermetic gate** | CI check that drives the whole five-script pipeline from frozen fixture inputs with every network bound set to zero, then diffs timestamp-normalized output hashes (§8.4). |
| **Query gate** | CI check that scores a frozen query set against a frozen catalog and compares result IDs and ranks. Needs no relevance labels. Fails on top-10 churn with the flag off (§8.5). |
| **Flag off parity** | With `--enable-subtopics` off, output must be byte-identical to pre-change. The core safety property. |
| **Backfill** | The one-time campaign that adds subtopics to the ~1,400 documents already in the evidence cache. Requires the three-gate trigger in §8.3, without which the feature silently covers only newly-changed documents. Run **locally in one pass** and committed once (§18 package D) — never drained through the nightly. |
| **Work package** | The unit of work in §18: several related items, one session, one commit per item. Replaces §10's numbered step as the thing a session delivers. |
| **Minimum path** | §18's packages A–G plus D½ Coverage and D¾ Forms — the smallest version of this project worth shipping. Everything outside it is deferred with a stated cost (§18.2). |
| **Backfill suppression** | Excluding first-seen subtopics from change events so the first digest is not entirely noise (Phase 3, step 23). Distinct from *backfill* itself. |
| **Discoverability registry** | `scripts/sources/discoverability.py` — the eleven-rule umbrella registry that already exists, attaching program-area topics and search terms to opaque umbrella FOAs (§3). Not to be confused with the subtopic layer, which adds child *records*. |
| **Gold set** | Auto-derived known-positives from past awards. The only way to judge whether a change *helped* rather than merely *changed*. Deferred; see §13 open decision 3. |

## 15. Progress checklist

Copy into a tracking issue. **The gate lines are not steps — they are stops.** Do not cross one that is unchecked.

**This checklist tracks the §18 minimum path, which is what is being built.** It was renumbered in 8.0 around §18's packages; §10's phase numbering is retained there as background but is no longer the unit of work. A checklist copied from an earlier version will not line up.

One **package** per session (§0.4 rule 5). One **commit** per item, with the suite run between commits. Every session ends pushed (§0.4 rule 5b).

---

## Open state at a glance

**Added 8.6. This is the index, not the record** — every line points at the
section that owns it. If something is open and not listed here, that is a bug in
this table.

### Blocking a human decision — nothing proceeds on these without an answer

| # | Decision | Where | Open since |
|---|---|---|---|
| §13.2 | **Where referenced subtopics live** — extend `discoverability.py`, or a new `program_taxonomy` adapter. Recommendation stated (adapter, linkage imported); nothing on the critical path depends on it | §13, tradeoffs in §6.7a | 15 sessions |
| §13.11 | **Is `(n) Public-Private Partnerships` a subject or a funding mechanism?** One person reading page 85 of `DE-FOA-0003600`. Do not settle it from a model verdict | §13, evidence in §11 | 2 sessions |
| §13.12 | **Whether to de-duplicate the `deadlines` payload** — 1.31 MiB removable of a 4.35 MB field, 5.5% of `opportunities.js`. Changes a published artifact's shape, so §0.5 applies | §13 | new in 8.6 |
| §18.3a | **Whether an F1 bare-numbered family may ever be added.** Four exit criteria stated; the prohibition stands until all four hold | §18.3a | new in 8.5 |
| §13.3–13.10 | Works-text provider · gold set · archive search · summary length · feed inclusion · taxonomy depth · mute/alert split · OCR | §13 | various |

### Gates not met — these stop work by design

| Gate | Why it is not met |
|---|---|
| **Package D** | Correct-acceptance stopped at 42%, below the 50% threshold set for the package (§18.1) |
| **Package D½** | Cov4, Cov5(done), Cov6 and Cov7 outstanding; **Cov4's "zero false rejections" cannot be shown in a single pass** — measured variance exceeds the measured rate (§11 caveat 2) |
| **Any cache commit** | The D5 cache holds six pre-Cov5 summaries and is missing a span (§15 debt D1). Regenerate before committing anything derived from it |

### Defects, unfixed

| # | Defect | Owner |
|---|---|---|
| Cov6 | `_demote()` caps publication for **46.4% of the catalog** — Cov1 supplies the bytes, `_demote` guarantees they never publish | §18.1 |
| D0 | `--max-documents` caps each **pass**, not the run, so the flag understates the work by 2× with subtopics on | §15 debt, §12 |
| D1 | The D5 cache's six corrupted summaries, and one missing span | §15 debt |
| D2 | **Three** families reject an ASCII hyphen — `dod_topic`, `component`, `technical_category`; the last also rejects `.` | §15 debt → Fm3 |
| D3 | §6.6's HTML outline layer is specified and unbuilt; deliberately, on a population measured at 0 lists in 20 | §15 debt |
| D4–D6 | 213 stale cache entries · 13 orphaned entries · 25 fetch failures across 5 hosts | §15 debt |
| — | `structural_siblings` is blind to **55% of the corpus's PDFs** (71 of 129 have no bookmarks) | §6.3a |
| — | The aggregating-agency-page false positive: every acceptance rule passes on another opportunity's topic list | §6.3b |
| — | Cov5's residual: `_locate_nodes`' `page_start_offset` fallback is still silent | §6.5 |

### Measurements outstanding

| # | Measurement | Why it matters |
|---|---|---|
| M2 / Cov7 | **30 more stratum-D records** | Closes over half of §1.1's 54–538 interval. Cheapest measurement in the project |
| M3 | **Classifier run-to-run variance** | Measured incidentally at 1.6% against a 0.9% signal. Cov4's gate is undemonstrable until this is bounded |
| M1 | Cov5 leaves the 757 no-span documents unchanged | Asserted in a session report, never run |
| — | F1/F4 candidate sets in Cov4's validation | Neither resembles the 22 sibling sets §11 measured (§11) |

### What is true and settled, so it is not relitigated

`MAX_TERMS` stays at 400 · subtopics ship in a `data/subtopics.js` sidecar · the
PDF toolchain is `pdfplumber` + `pypdf`, never PyMuPDF · segmentation runs inside
`extract_document_evidence.py` at a flag-guarded call site · nothing below `high`
publishes unreviewed · **seven of §6.3's ten families are retired on measurement**
(§6.3) · §11's recall half stays closed. Full list in §13 *Settled*.

---

### Done

- [x] **0.** All **eleven** §0.1 questions answered from code → `docs/RECON.md`
- [x] **0b.** Plan corrected against RECON.md → 7.0; corrected again against measured build data → 7.1
- [x] **A0.** §8.4 hermetic no-drift gate built, wired into `tests.yml`, green on `ubuntu-latest` — 20 artifacts baselined, sensitivity proven on both the catalog and feeds sides, zero production-code changes

---

### Package A — Foundations completion

**Complete 2026-08-16.** One commit per item, suite run between commits, pushed and green on `ubuntu-latest`.

- [x] A1. **Populate the frozen fixtures** — three enrichment and three evidence entries keyed to ids `1001`/`1003`/`1005`, so the gate covers the populated `merge_document_entry` path (§8.4). **Do this first:** it is what makes every later gate meaningful — *12 cited facts across 3 records where there were none; baseline 20 → 22 artifacts; §17.6 rule 2 followed, two builds 78 s apart, 0/22 normalized differences*
- [x] A2. Pin `pdfplumber`, `pdfminer.six`, `pypdf` (§6.1) — *all three of §6.1's version numbers were wrong; `pypdf==5.1.0` would have been a two-major-version downgrade. §6.1 corrected*
- [x] A3. `.gitignore` allowlist line for `data/subtopic_records.json` (§0.4 rule 11) — *§9.4 item 7's `-v` check also corrected; it reports a pass as a failure*
- [x] A4. Size-budget test — absolute limits, not a multiplier (§12) — *32 MiB fail / 28 MiB warn / 2 KiB per subtopic; each threshold proven to fire; 205 → 208 tests*
- [x] A5. Heartbeat file `.github/last_build` (§16.3) — *written unconditionally before the commit step; deliberately outside the workflow's push path filter so it cannot self-trigger*
- [x] A6. Query set + `evaluation/query_baseline.json` (§8.5) — *37 queries, byte-identical across two runs, wired into `tests.yml`. Found that top-10 churn is a weaker gate on the 5-record fixture than §8.5 implied; see the warning there*
- [x] **GATE:** suite green, zero test-file edits · `verify_no_drift` green in CI **now covering populated evidence entries** · query baseline byte-identical across two consecutive runs

### Package B — Segmentation, offline and self-contained

**Complete 2026-08-16.** One commit per item, suite run between commits, pushed and green on `ubuntu-latest`.

- [x] B0. **Verify the §6.1–§6.2 API sketches against real notices** — added ahead of B1 because §17.2 flagged them as unverified claims and two turned out to be wrong. `docs/PDF_API_NOTES.md`; §6.1–§6.3 corrected. *Resolves the first of §17.2's two outstanding claims*
- [x] B1. `scripts/subtopic_patterns.py` — ten families, `best_family()` (§6.3) — *specific-family-wins ordering added; without it "Research Thrust 3" is double-counted and trips its own margin test*
- [x] B2. `scripts/subtopic_segmentation.py` — layers A–D, acceptance rules, derived fields, time and page budgets (§6.1, §6.2, §6.4, §6.5) — *two bugs found by running it, one inherited from §6.5's `running_lines` sketch; both corrected in code and plan*
- [x] B3. Synthetic fixtures + `tests/test_subtopic_segmentation.py` — *57 tests; Layer C covered end to end through pdfplumber using base-14 fonts, so **no `requirements-dev.txt` was needed**; §9.3's reasoning corrected*
- [x] **GATE:** new tests pass · suite green (208 → 265) · `verify_no_drift` unchanged at 22 artifacts (nothing imports these yet, so nothing can regress)

### Package C — Wire the call site, flag off

**Complete 2026-08-16.** One commit per item, suite run between commits, pushed and green on `ubuntu-latest`.

- [x] C0. **Corpus shape census** — added ahead of C1. 20 notice documents judged by reading → `docs/CORPUS_CENSUS.md`. *12 of 20 enumerate fundable subdivisions; a family identifies the right list in 1 of those 12; the segmenter produces subtopics for 0. Found that the best match is blocked by a segmenter defect rather than a pattern gap, and that §6.7 is wrong about `DE-FOA-0003600`.* **⚠ Non-representative by design — the 20 were chosen to span shapes. Its per-document judgments were all confirmed and it remains the reference for *shapes*; it is not a denominator. Use `docs/COVERAGE_SURVEY.md` for every rate (Cov0)**
- [x] C1. `scripts/subtopic_records.py` — identity matching, term maps, cache I/O, `needs_subtopic_extraction()` — *§5.3 matching and §5.2 term maps already landed in `subtopic_segmentation.py` during B, so this module imports them; §5.4 diff stability enforced by test*
- [x] C2. Flag-guarded call site in `extract_document_evidence.py` (§8.3, four commits) — the only change to working production code in the minimum path — *two commits, insertions 1/2/4 then insertion 3. Exactly one line removed in the whole diff*
- [x] C3. `git add` paths in the workflow — *guarded by a `-f` test, since the file does not exist until package G*
- [x] **GATE:** flag **off** → `verify_no_drift` byte-identical and suite green with zero test-file edits (this is §0.5) · flag **on** → a cache produced for five documents copied out of the evidence cache locally. **Partial on one clause:** the cache was produced for five documents, but with **zero spans** — all five returned `no_layer_accepted`, which is exactly what C0's census predicts for this corpus. The production call site was separately shown to produce three high-confidence spans on a document that does enumerate, so the machinery is proven; the patterns are what do not yet reach real notices (package D)

### Package D — Tune and backfill

**Read `docs/CORPUS_CENSUS.md` before starting.** It is the measured picture this package tunes against: 12 of 20 documents enumerate, a family identifies the right list in 1 of those 12, and the segmenter produces subtopics for 0.

> **⚠ Superseded denominator (8.2).** That 12-of-20 is a **non-representative** sample — the documents were chosen to span shapes. `docs/COVERAGE_SURVEY.md` is the reference: **10 of 40 stratified records enumerate (25%)**, ~128 catalog-wide. Every rate in this package's gate below is quoted against 12 and therefore reads roughly **twice** as favourably as the corpus supports. The gate is left as measured rather than restated, because it was a true measurement of that corpus; do not carry its percentages forward.

- [x] **D0a. Fix Layer B's body cutoff** — *the defect was larger than the census recorded: `_candidates_from` also searched from offset 0, so it found the TOC copy of every title and never reached the body. The floor had to move to the search, not the results. 0 → 8 candidates located on `363526`*
- [x] **D0c. Cap the final span** — *a THIRD defect, not in the census. The last span ran to end-of-document (111,290 chars on `363526` against a 40,000 ceiling), so any notice whose list ends before the document does was unacceptable by construction — which is nearly all of them*
- [x] **D0b. Fix Layer C/D TOC co-collection** — *no corpus movement on its own, because Layer B now wins on the one document where it mattered; it removes a failure mode rather than fixing a current one*
- [x] **GATE:** D0a/D0b landed before tuning · `363526` segments — 8 topics, `toc`, `dod_topic`, high confidence
- [x] D1. `structural_siblings` (§6.3a) implemented; §6.4a thresholds fitted — **three moved, each with its measurement** (§6.3a, §6.4a). 0 false positives
- [x] D2. All 286 bookmarks read — **`(q) Catalysis Science` is at level 2, page 46**; depth 3, 9/46/167/64 nodes (§6.7)
- [x] D3. Census-named families added: `focus_area`, `component`, `technical_category`, and `topic_area` widened to sub-lettered ordinals
- [ ] D4. Full **local** backfill — **RAN 2026-08-16 (53 min, 770 documents, 0 queued) and the cache was deliberately NOT committed.** Of the 12 documents whose subtopics would publish, **6 carry the wrong list, and 43 of 194 publishable records are fabricated** — `1. NOFO Summary`, `a. Narrative Section I: Project Description`, `1. Title X Statute`, `A. Short Description of Funding Opportunity`. §18.3's trade forbids shipping 43 wrong cards to gain 146 right ones. Histogram: `no_layer_accepted` 736 · accepted 22 · `no_extractable_text` 11 · `time_budget` 1 · `run_budget` 0. See `docs/CORPUS_CENSUS.md`
- [ ] **D5. Give `structural_siblings` a positive test.** It admits any sibling set whose ancestors are not administrative, and the level-0 lexicon is keyed to DOE's `III. Program Description` convention. `362827`'s ancestor is `A. Summary`, `348830`'s is a bare `I.` — neither matches, so both publish their NOFO skeleton. **Until this exists `outline_structural` should emit `low`, not `medium`**
- [x] **D5. Give `structural_siblings` a positive test** — done, and it took three fitted changes rather than one: a process-vocabulary veto at 0.07 applied to every family (§6.4 rule 8), `heading_font` demoted to `low` on 0/1 measured precision, and a dominant-code-form trim for contaminants inside otherwise-correct sets. **Fabricated publishable records 54 → 0**, legitimate 140 → 133, all 133 read individually
- [x] **D7. Resolve the §12 per-subtopic budget** — **closed 2026-08-17, and the premise was wrong.** The ceiling was measuring the build-time cache record, 60.3% of which is `subtopic_terms` that never reaches the browser. Measured: the ceiling is violated identically at every cap from 400 to 100 (202/223), passes only at 5 terms (74.8% BM25 loss), and at *zero* terms the largest record still occupies 1,930 of 2,048 bytes — so §12's *"cut `max_terms`, not the ceiling"* was unachievable and is withdrawn. **`MAX_TERMS` stays at 400**; the ceiling now bounds the **display payload** (median 942 B, max 1,218 B, 0/223 over); the term map folds into the sidecar index (§5.2). Both former §13 decisions 0 and 1 are settled together, because they were one question
- [x] **D6. Re-measure on a stratified sample — done 2026-08-16 → `docs/COVERAGE_SURVEY.md`.** 40 records stratified by attachment profile and agency, disjoint from the census 20; 131 files and pages opened with nothing skipped by name. **10 of 40 enumerate (25%), not 12 of 20 (60%)**; ~128 catalog-wide. *Partial: this measures **coverage**, not precision. The false-positive rate on a random sample — D6's original question — is still unmeasured, because the D5 changes were fitted after the backfill that would have to be re-run to measure them. Re-run the backfill and read the publishable titles again after the Coverage package*
- [ ] **GATE — measured, and one clause not met.** Denominator is the **12 enumerating** documents, not 20 (`docs/CORPUS_CENSUS.md`). **⚠ 8.2: that denominator is a non-representative sample; the corpus rate is 25% (`docs/COVERAGE_SURVEY.md`). These figures stand as a true measurement of *this corpus* and must not be quoted as the design's coverage:**

| Metric | Result |
|---|---|
| Acceptance | **5/12 = 42%** (baseline 0/12) |
| **Correct-acceptance**, every span read | **5/12 = 42%** — all five accepted documents found the right list |
| **Publishable** (`zero low-confidence published`) | **3/12 = 25%** — `356623` and `362859` resolve at Layer D, which is low confidence and never publishes |
| **False positives on the 8 non-enumerating** | **0/8** |
| Span-level precision | **108/115 = 94%** — and all 7 bad spans are in the publishable set (`Open Science`, `Annual Progress Reports`, `Teaming Arrangements`…) |
| Rejection histogram | all 7 misses `no_layer_accepted`; no `run_budget`, no `time_budget` |

**On the highest-value document, `DE-FOA-0003612` (Genesis Mission — live, closes 2026-12-17): 21 of 21 published challenge areas recovered exactly, 0 of 99 focus areas, 5 spurious administrative spans.** Full entry in `docs/CORPUS_CENSUS.md`.

**Why more regexes are not the answer.** Of the seven misses, **four need one missing mechanism** (`label_run` for named subdivisions), **two need occurrence selection** — the pattern matches in several places and nothing decides which is the heading, the same class of defect as D0a/D0b — and **one is §6.3a's depth-0 rule refusing a legitimate list** (`343653`'s ten country FOAs). Only `332894` would require the loosening §18.3 forbids. Two mechanisms would address six of seven; more patterns would address one.

**⚠ Tuning stopped at 42%, below the 50% threshold, deliberately.** Every remaining miss needs a new *mechanism*, not a wider regex: `label_run` for outline-less named portfolios (AFOSR, NRL), occurrence selection for patterns that match in several places (`360339`, `363065` — a front-matter summary list and 36 prose mentions respectively), or a generic numbered-section family for `332894`'s bare `1.)`. §6.3 and §18.3 both name that last one as the most damaging change available. **The 0/8 false-positive count is the number that should not be traded**, and reaching 50% by loosening would trade exactly that.

Per-agency-family acceptance, as the gate requires rather than in aggregate: **DOE 3/5** (`360678`, `361526`, `356623`; missing `363065`, and `362329` is DHA not DOE) · **DoD 2/6** (`363526`, `362859`; missing `332894`, `343653`, `352741`, `362681`) · **HHS/CDC 0/1** · **NASA 0/0** (no ROSES document in the corpus; §18.2).

### Package D½ — Coverage

**Read `docs/COVERAGE_SURVEY.md` before starting.** It is the measured picture this package works against, and its ranked table is this package's ordering. Every yield below is *sampled records out of 40* · *catalog extrapolation*.

- [x] **Cov0. Survey the corpus** — done 2026-08-16, ahead of the package → `docs/COVERAGE_SURVEY.md`. *1,635 attachments across all 1,475 records; 40-record stratified read sample; reachability re-derived. 44.7% of the catalog carries no attachment, 46.4% is never fetched, and 25% of sampled records enumerate — not 60%*
- [x] **Cov1. Fix the `source_for_record` selection gap** — *done 2026-08-16. Measured on the survey's 40: reachable **30/40 → 40/40**, correctly segmenting **2/40 → 2/40**, false positives **0**. All ten newly reached records return `no_layer_accepted`; Sloan's seven fields are now fetched and still not accepted, because they are named rather than numbered (`label_run`, deferred §18.2). Writes no evidence entry — a separate cache key, present only with the flag on.* Original note: 2/40 · ~48. **685 records (46.4%) never attempted; 672 have never been fetched once; 236 carry live attachments.** Extend the parallel subtopic-only path (`subtopic_sources.py`); do **not** change `source_for_record` itself
- [x] **Cov2. HTML attachment support** — *done 2026-08-16. Stubs filtered at `MIN_HTML_BYTES = 2048`; **20 of the 111 non-stub NIH announcements read end to end**: 20/20 parsed (29–112 containers, 50–125 K chars), **0/20 produced a list, 0 false positives**. The plumbing is right and the population is empty. Gap found and deliberately not built: `extract_html_sections` keeps headings in `section`, so §6.6's "use the section tree as the outline equivalent" is unimplemented; a test pins it. Unmeasurable on the 40-record sample, which contains no non-stub HTML record.* Original note: 1/40 · ~43, plus **108 records reached whose yield is unmeasured**. 366 `.html` attachments, all NIH; 111 complete announcements; 255 sub-1 KB stubs that must not displace the agency URL. **Read 20 of the 108 first** — that measurement is inside this item, not after it
- [x] **Cov3. Re-enable multi-attachment fetch** — *done 2026-08-16, **no code change**. Traced live: the furniture primary returns `no_layer_accepted`, `FA2391-23-S-2403.pdf` returns 18 spans and wins on score. Pinned by `FurniturePrimaryTests`. The winner is `low` and never publishes — Cov4's evidence. A 9.5 MB model contract ate the per-document time budget, recorded not fixed.* Original note: 1/40 · ~5. Already built and neutralized by its own `low` cap. Justified by **AFRL PACER `349554`**: selected primary is a one-page Security Program Questionnaire; `FA2391-23-S-2403.pdf` yields **18 correct topics**. Land selection-by-result-quality with it
- [ ] **Cov4. Redesign the confidence model** — **two stages (§18.1, rewritten 8.3), narrowed in 8.7 to `inferred` and `inline` provenance only — `native` and `referenced` children bypass the classifier and the queue (§5.1). Still required: PACER is `inferred` and no structured source covers it. Draw the validation set after D⅝, not before.** The unit moves from set to span (§6.4b); a classifier filters spans (§11: Sonnet 4.6 caught 7/7 contaminants with 0/107 false rejections, PACER 18/18); the review queue takes only the residual — abstentions and `medium`/`low` survivors. **Fail-closed: no classifier → no new subtopics, never unfiltered ones.** Key from GitHub Secrets; Claude Code strips it from tool subprocesses, so local testing needs a human to make the calls. Reuses `assets/review.js` and **partially delivers issue #8**
- [x] **Cov5. Fix span-summary alignment** — *done 2026-08-17. One cause for all six: a `pdfminer`-inserted space beside a hyphen or em-dash made the bookmark title unlocatable, and `_locate_nodes` substituted the top of the page. **6 of 223 spans = 2.7% → 0 of 224**, measured by re-running all 13 accepted documents. Clustered by document (`360678` only), not by method. `360678` 68 → 69 spans. Two tests added, none modified; suite 321 green, `verify_no_drift` green. Residual: the `page_start_offset` fallback stays silent (§6.5).*
- [ ] **Cov6. Fix `_demote()`'s blanket cap on no-primary records** — **added 8.5.** It decides "secondary" by whether `primary_content` was populated, and Cov1's path passes none, so a list read from a record's own Full Announcement is capped at `low`. Verified: `363526` gives `high` from `segment_document` and `low` through `segment_without_primary`. **Caps publication for 46.4% of the catalog** — every later recall item lands in the cache and reaches no PI until this is fixed (§18.1)
- [ ] **Cov7. Read 30 more stratum-D records** — **added 8.5.** The cheapest outstanding measurement: D is 483 records with 12 reads, contributes 40 of §1.1's 171 on one observation, spans 7–171 alone, and holds the only tabular list. Supersedes the survey's "sample C and E"; C is discharged at 18 of 27
- [ ] **GATE:** unreachable count re-derived against the **catalog** · records *reached* and records *yielding an accepted list* reported **separately** for Cov1–Cov3 · fabricated publishable records still **0**, measured by reading every published title as D5 did · **Cov6 verified by re-running `363526` end to end, not by reading the code** · §0.5 byte-identical with the flag off · **every gate's exit code checked directly, not read through `tail` (§17.7)**

### Package D⅝ — Structured Umbrellas

**Added 8.7, and it precedes D¾.** Rung-1 and rung-2 sources (§6.7·0) — the
hierarchies agencies publish as data — before any further generic inference.
**Build S1 only, then re-measure.**

- [ ] **S1a. Read NSPIRES ROSES Table 3 and record its shape** — §0.4 rule 10, before any parser is written. Row schema, element-code form, how continuation years are expressed
- [ ] **S1b. `native` adapter for ROSES program elements** — ~35 elements across Earth science, heliophysics, planetary science, astrophysics and biological/physical sciences. Emits `subtopic_source: "native"`, `confidence: "high"`, bypassing Cov4 and the review queue (§5.1). Parent match by element code, never by FOA number
- [ ] **S1c. Canaries** — `expected_solicitations`: **ROSES has ≥20 open elements**. Zero rows on an HTTP 200 fails loudly (§7.4)
- [ ] **S1d. Re-measure and stop** — report **new parents**, not expanded coverage; re-run §8.5. **S2 (DOE SC referenced taxonomy, all six offices) and S3 (DoD source router) stay unscheduled until a human reads S1d**
- [ ] **GATE:** S1 only · new parents reported separately · canary proven against a simulated zero-row 200 · `native` confirmed to bypass Cov4 in code · §0.5 byte-identical with the flag off

### Package D¾ — Forms

**Added 8.5. Gated behind Cov4 and, from 8.7, behind package D⅝** — the two largest uncovered forms are both unsafe on structure alone (§18.1), and all four recogniser items are rung-4 inference whose yields were measured before any structured source was tried. **Fm1, Fm2, Fm5 and Fm6 build only against records still uncovered after D⅝, and their yields are re-measured on that residual.** Fm3, Fm4 and Fm7 are unaffected — two repairs and a decision not to build. Yields below are *records in the 90 read* · *catalog estimate*, **pre-D⅝**.

- [ ] **Fm1. F4 — named / bulleted, no counter** — 9 of 90 · **~73**, or ~22 excluding one stratum-E observation. `label_run` (§6.3a) plus a bulleted variant. Highest false-positive risk in the plan; `362233`'s five real Focus Areas sit one subsection above five decoy process bullets. **Do not build on structure alone**
- [ ] **Fm2. F1 — bare numbered** — 8 of 90 · ~31, the most stable uncovered row. **Blocked by §18.3a's four exit criteria — read them first.** Needs grouped restarting counters (`330175`) and title extraction that survives a trailing em-dash clause (`355150`)
- [ ] **Fm3. Repair `dod_topic`'s ordinal group** — widen `(\d{1,2})` to letters so `Topic A1`–`A7` matches (`356612`). Third appearance of the same oversight; `topic_area` got it in D3
- [ ] **Fm4. Repair `thrust`'s granularity** — it matches the container `Thrust Area 1`, not the seven topics under it. Scope to the items or retire it under §17.8; it has **no record validating it at the right granularity**
- [ ] **Fm5. F5 — table path in `extract_containers`** — 1 of 90 · ~40 **on n=1**. `pdfplumber` already authorized (§6.1). Fund on the qualitative argument — `363530` prints the same 12 topics as `363526` — not on the ~40. **Read Cov7 first**
- [ ] **Fm6. F3 — coded named list** — 4 of 90 · ~6. `PA 1:`, `53-24-01 -`, `A.1.a.`. Discovered-prefix recogniser, false-positive profile unmeasured. Smallest yield; do last or not at all
- [ ] **Fm7. F6 — record the verdict, write no pattern** — 4 of 90 · ~4. Three of four are two-item lists `structural_siblings` already sees and rule 1 / rule 2d reject on cardinality. Reachable only via §6.4b span-level admission, so it arrives with Cov4 or not at all
- [ ] **GATE:** every new or repaired family names its validating document **and quotes the matched text** (§17.8) · acceptance rate reported **per form** · fabricated publishable records still **0** by reading every title · false positives reported on the **33 category-(a) documents** in `docs/FAMILY_TAXONOMY.md` §1 · §0.5 byte-identical with the flag off

### Package E — Storage and scoring

- [ ] **E0. Re-key subtopic identity onto the parent's `opportunity_id`** (§5.1, §5.3). **Do this before anything writes a cache.** `subtopic_records.py` keys on `opportunity_number` with an `opportunity_id` fallback, so 1,455 records key one way and 20 key the other, and a VPR-digest parent that later gains an opportunity number silently re-identifies all its children. Free today — no backfill has run; expensive after E2
- [ ] E1. Prototype cross-corpus scoring on the frozen catalog — this resolves **§13.1**
- [ ] E2. Implement the winner (sidecar or in-catalog children)
- [ ] E3. **Minimal currentness only:** a subtopic is current **iff its parent is current**. Nothing else
- [ ] **GATE:** query baseline run · flag-off top-10 churn **zero** · flag-on movement reviewed case by case. **Read the displacement numbers too, not just churn** — on the 5-record frozen fixture nothing can fall past rank 10, so churn gates admission changes but not pure reordering, which is precisely what E risks (§8.5)

### Package F — Make it visible

- [ ] F1. Retrieval rollup in `assets/search-retrieval.js` (§7.3)
- [ ] F2. `term_display` in the subtopic builder, capped at 60 stems
- [ ] F3. `assets/match-explain.js` behind `FF_MATCH_EXPLAIN` (§7.6)
- [ ] F4. Search UI behind `FF_SUBTOPICS_ENABLED` — `app.js` + `match_explorer.html`; do **not** relax `validateCatalog`
- [ ] **GATE:** manual A/B with both flags off, byte-identical (browser code is outside the hermetic gate) · query baseline unchanged with flags off

### Package G — Enable

- [ ] G1. Flip `--enable-subtopics` and `FF_SUBTOPICS_ENABLED`
- [ ] G2. Document-evidence step given an `id:` and routed **before** `continue-on-error` is removed (§9.3)
- [ ] G3. `PROJECT.md` — decision, rationale, measured deltas
- [ ] **GATE:** §9.4 dispatch checklist walked in full — runtime under 15 minutes, no new issue number, #30 updating expected

---

### Debt — carried, not scheduled

**Added 8.6. Everything here was previously live only in a session report.** None
of it belongs to a package, none of it blocks a gate, and all of it is real. An
item leaves this list by being done, by becoming a package item, or by being
explicitly declined with a reason — never by being forgotten.

**Defects, unfixed:**

- [ ] **D0. `--max-documents` caps each pass rather than the run.** With
  `--enable-subtopics` on, the subtopic pass receives the same value as the
  administrative pass, so the run can fetch twice what the flag says (§12).
  Decide between one shared budget and a second named flag; do **not** change the
  existing default (§0.4 rule 8)
- [ ] **D1. The D5 cache carries six summaries that describe the wrong subject.**
  Cov5 fixed the extractor, not the artifact. The uncommitted cache at
  `backfill3/` still holds the pre-fix text for `(d)`, `(i)`, `(j)`, `(k)`, `(l)`
  and `(n)` of `360678`, and is missing `(m)` entirely. **Any figure computed from
  that cache inherits the defect**, including §11's span-level table. Regenerate
  before the cache is used for anything else — and note it is 68 spans where a
  re-run gives 69
- [ ] **D2. Three families reject an ASCII hyphen.** Measured by running the
  patterns: `dod_topic`, `component` and `technical_category` all accept `:`,
  en-dash and em-dash but **not `-`**, and `technical_category` also rejects `.`.
  `Topic 1- Aero-Structures` does not match. PACER's `349554` happens to use an
  en-dash, which is why this has never surfaced. Fold into **§18.1 Fm3**, whose
  scope is currently only the letter-ordinal gap — and add the ASCII hyphen to
  the same character class rather than filing a third variant later
- [ ] **D3. §6.6's HTML outline layer is specified and unbuilt.**
  `extract_html_sections` puts the heading in the container's `section` and the
  prose in its `text`, so every text-scanning family looks past the headings and
  §6.6's instruction to *"use the section tree as the outline equivalent"* is
  unimplemented. Pinned by `tests/test_subtopic_sources.py::HtmlAttachmentTests`
  so the gap is inherited as evidence. **Deliberately not built:** the measured
  population is 0 lists in 20 NIH announcements (Cov2), so this is speculative
  until some HTML source is measured to enumerate

**Cache hygiene:**

- [ ] **D4. Prune the 213 stale evidence entries** whose records have left the
  catalog. They are cache residue, not a reachability problem, and they inflate
  any denominator taken from the cache (§12)
- [ ] **D5. Decide what to do with the 13 orphaned entries** — records whose
  evidence entry names a real attachment but whose parent no longer resolves to a
  source. Cov1 reaches most of them now, so this may already be closed by
  measurement rather than by code; verify before writing anything
- [ ] **D6. Triage the 25 recorded fetch failures.** `nasaprs.com` 12,
  `transit.dot.gov` 4, `rd.usda.gov` 2, `bja.ojp.gov` 1, `nsf.gov` 2, plus 4
  against dead URLs from records that have left the catalog. **Two hosts account
  for 18 of 25 and neither is a segmentation problem** — NASA is §18.2's NSPIRES
  deferral and DOT/USDA are 403s that a header change may or may not fix.
  Independently reproduced on six further records in the taxonomy sample, so the
  hosts are stable, not transient

**Measurements outstanding:**

- [ ] **M1. Verify Cov5's fix leaves the 757 no-span documents unchanged.** The
  prevalence re-run covered the **13 accepted** documents (224 spans). The other
  757 in the D5 backfill produced no spans, so there is nothing to misalign — but
  that they still produce none, and still for the same recorded reason, is
  **asserted and not measured**. A widened title matcher could in principle
  locate a candidate that previously failed, which is how `360678` gained a span
- [ ] **M4. Read `344592` (`W911NF-23-S-0001`, DEVCOM ARL BAA) for MURI topics.** A live Grants.gov search finds MURI in its full text; our stored description is truncated at 2,793 chars and does not contain it. **If that notice enumerates MURI topics inline, part of what §18.2's SAM.gov deferral is said to cost is already reachable** — the record is in the catalog and fetchable today. Cheap: one document, and it is already in the development corpus §6.3 names
- [ ] **M2. Read 30 more stratum-D records** — the cheapest outstanding
  measurement in the project, and the one that closes over half of §1.1's
  interval. Tracked as **§18.1 Cov7**; listed here so it is visible without
  reading §18
- [ ] **M3. Establish the classifier's run-to-run variance.** Measured
  incidentally at **1 of 62 byte-identical spans flipping (1.6%)**, against the
  0.9% false-rejection rate it is meant to measure (§11 caveat 2). **The noise is
  larger than the signal**, so Cov4's "zero false rejections" gate is not
  demonstrable in a single pass and must specify repeats

**Already tracked as package items, listed here only for visibility:**
`_demote()`'s 46.4% publication cap is **§18.1 Cov6**; the rule 1 floor rejecting
F6's two-item lists is **§18.1 Fm7** and §6.4a; the 30 stratum-D reads are
**Cov7** (M2 above).

### Deferred — not part of the minimum path

**Do not start any of these before package G is complete.** Each is a separate decision to be made with evidence from A–G. Costs are in §18.2; the DOE BES omnibus getting no child records in v1 is the most significant of them.

- [ ] ~~SAM.gov adapter~~ (§7.5)
- [ ] ~~NSPIRES activation~~
- [ ] ~~`program_taxonomy` / referenced subtopics~~ (§6.7) — **blocked on §13.1 decision 2**
- [ ] ~~`expected_solicitations.json` + `check_expected.py`~~ (§7.4)
- [ ] ~~§7.9 profile rebuild~~ into `faculty_profiles_v2.json`
- [ ] ~~Expired archive, "include past cycles", recurrence grouping, `own_deadline`~~ (§7.2)
- [ ] ~~"Not relevant" control + muted-items panel~~ (§7.2b) — tracked as **#8**
- [ ] ~~Team match: `faculty_match.py`, `team-matcher.js`, per-parent cap~~ (§7.7)
- [ ] ~~Subtopic change events, Atom feeds, alerts~~
- [ ] ~~Help page~~ (§7.8)
- [ ] ~~`evaluate_phase2.py` extension~~ — blocked on **#9**, itself blocked on **#8**
- [ ] ~~AI layer decision~~ (§11)
- [ ] ~~Standing operations: monthly histogram review, quarterly cron check~~

---

## 16. Operational feasibility on GitHub Pages

**Short answer: yes.** Every input this plan requires is publicly obtainable by an Actions runner, and exactly one credential is involved.

### 16.1 Data acquisition

| Source | Auth | Automatable |
|---|---|---|
| Grants.gov XML extract | none | Yes — already working |
| Grants.gov `search2` / `fetchOpportunity` | none | Yes — already working |
| Notice PDFs and attachments | none | Yes — already working |
| DOE eXCHANGE (ARPA-E, EERE) | none | Yes — already working |
| NSF, NYSERDA | none | Yes — already working |
| NSPIRES / ROSES Tables 2 & 3 | none | Yes — public HTML |
| `science.osti.gov` BES program taxonomy | none | Yes — public HTML |
| OpenAlex (works, abstracts, author-by-ORCID) | none | Yes — free; send `mailto` for the polite pool |
| NSF Award Search, NIH RePORTER, USAspending | none | Yes — gold-set derivation |
| **SAM.gov opportunities** | **api.data.gov key** | Yes — would be the only *new* credential |

ORCID is never called directly. Today the browser resolves an ORCID iD through **Crossref** (`api.crossref.org/works?filter=orcid:…`); if §13 open decision 2 selects OpenAlex, it would resolve through `openalex.org/authors/orcid:…` instead. Either way ORCID is a key, not an API dependency, and neither provider needs auth.

**Correction to "the only credential in the system."** SAM.gov would not be the first. The nightly workflow already consumes `VPR_IMAP_USER` and `VPR_IMAP_PASS` for the VPR email-digest adapter, which is enabled and contributing 38 records. SAM.gov would be the second and third credential path, and the mailbox one is the more fragile of the two.

### 16.2 Where updating actually happens

Pages serves static files from the default branch and never executes anything — there is no deploy job. All updating is Actions, and the `git push` in the commit step is the publication event. Staleness is handled in **two independent places**, and this is the most important resilience property in the system:

1. **Build time** — records are gated as the catalog is assembled. Note this is **not** `currentness.py`: `build_catalog.py` has its own `is_current()` operating on raw Grants.gov XML during extract parsing, and it does not import `currentness`. The published catalog therefore *retains* some records `currentness` would exclude.
2. **Runtime** — `currentness.py` is applied by feeds, change events, docs stats, faculty match and alerts, and re-implemented independently in three browser modules, always against *today's* date rather than the build date.

Consequence: if the workflow stops running, the site does not show stale opportunities. It stops showing *new* ones while continuing to correctly retire expired ones. It degrades to incomplete, never to wrong. Preserve this property; do not "optimize" the runtime gate away as redundant.

### 16.3 Platform realities to design around

**Scheduled workflows are silently disabled after 60 days of inactivity.** <cite index="11-1">In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days.</cite> <cite index="16-1">Activity means a push or similar repository modification; issue comments and stars do not count.</cite>

> **This interacts badly with §5.4.** Diff-stable serialization means a quiet stretch produces *no commit at all*. A holiday period, a government shutdown, or a run of days where last-known-good is retained unchanged could produce zero commits — and the clock runs. **Mitigation: write a one-line heartbeat file (`.github/last_build`) containing the build timestamp on every successful run, unconditionally.** It guarantees a daily commit, costs a few bytes, and does not violate §5.4, which governs data files. Without it, the site can quietly stop updating with no error anywhere.

<cite index="17-1">Disabling produces no error in the Actions tab and no banner unless you navigate directly to the workflow page; notification is a single easily-missed email.</cite> Verify quarterly that the schedule is still enabled.

**Cron timing is best-effort.** <cite index="17-1">Delays of 5 to 30 minutes are routine, and delays beyond an hour occur during peak windows.</cite> Schedule at an odd minute rather than on the hour, and treat a skipped day as normal — the change-detection ladder (§6.1) means the next run picks up everything missed. Nothing in this design assumes a run happened yesterday.

**Repository growth.** Daily commits over years accumulate. This is precisely why §5.4's stable serialization matters: real daily deltas should be kilobytes, not megabytes. Expired topics go to a separate lazily-loaded archive (§7.2) so they do not inflate the file the browser loads on every visit. Site size and bandwidth stay well inside GitHub Pages' published soft limits for a departmental tool — confirm current figures in GitHub's docs rather than trusting this sentence.

**Everything committed is public.** The existing privacy boundary (§4) already assumes this. Do not weaken it because a field would be convenient to store.

**No request-time compute.** Mute lists, personal profiles, resume text and any AI chat remain browser-side by necessity, not preference. This is why muted items cannot be suppressed from email alerts (§7.2b).

---

## 17. Running this with an AI agent

### 17.1 Where this document lives

A human commits it to the repository as `docs/TOPIC_LAYER_PLAN.md` before the first agent session begins. The agent cannot obtain this file on its own. Do not paste it into a chat message. It must be a file so that it persists across sessions, is versioned alongside the code it describes, and can be **corrected** as the work proceeds.

### 17.2 Versions 1–6.2 were written without reading the code

They were written from the repository's README and public description. File names, function names, module boundaries and workflow step order were **inferences**, and nine of them were wrong.

**When the plan and the repository disagree, the repository wins, and the plan gets corrected.** An agent that silently works around an inaccuracy leaves a document that is wrong for every later session. Correcting a section to name the function that actually exists is part of the work, not a distraction from it.

Version 7.0 is the first version corrected against the code. It is not thereby *verified* — RECON.md read the repository at commit `b40d400`, and the repository keeps moving. Two specific things in 7.0 are still unverified by execution and should be treated as claims, not facts:

- ~~**The `pdfplumber` and `pypdf` API sketches in §6.1 and §6.2 have not been run.**~~ **Resolved 2026-08-16 (package B, commit B0).** All three were run against real notices; findings are in `docs/PDF_API_NOTES.md` and §6.1–§6.3 are corrected against them. `reader.outline`'s nesting was right; `get_destination_page_number`'s "raises" was **wrong** (it returns `None`); `page.chars`' `fontname` values were right, but the size half of Layer C's candidate test was shown to admit 0.0–0.2% of lines on the DoD BAAs it exists to serve.
- **The offline-mode invocations in §8.4 were derived by reading argument parsers, not by running them.** `--max-documents 0` and friends are *accepted* by validation; that they produce a complete, network-free run is inferred.

Both are Phase 1 work and both fail loudly rather than silently, which is why they are acceptable to carry as claims. Say so in the session report when you check them.

### 17.3 Session protocol

| Session | Scope | Deliverable | Status |
|---|---|---|---|
| 1 | §0.1 reconnaissance **only** — all **eleven** questions. The human performs repo setup (clone, branch, commit this plan) beforehand; an agent's first action should not be repo surgery. No edits to existing files, no installs, no write-mode scripts. | `docs/RECON.md` — eleven answers with file/line citations, a "Plan discrepancies" section, a "Blocked" section | **done** |
| 2 | Revise this plan against `docs/RECON.md`. Still no code changes. | Corrected `docs/TOPIC_LAYER_PLAN.md` | **done — this is 7.0** |
| 3 | §8.4 hermetic no-drift gate. | `tools/`, frozen fixtures, baseline, wired into `tests.yml` | **done** |
| 4 | Repair the gate after its first CI failure. | Line-ending normalization in `fingerprint.py` | **done** |
| 5 | §18 package A — foundations completion. | Six commits, gates green, §15 updated, branch pushed | **done 2026-08-16** |
| 6 | §18 package B — segmentation, offline and self-contained. Opened with an unplanned B0 verifying §17.2's API claims. | Four commits, gates green, §15 updated, branch pushed | **done 2026-08-16** |
| 7 | §18 package C — wire the call site, flag off. Opened with an unplanned C0 corpus census. | Five commits, §0.5 gate green, §15 updated, branch pushed | **done 2026-08-16** |
| 8 | §18 package D — tune and backfill. | Nine commits; D4/D5 backfills run and the cache deliberately **not** committed; D7 opened (closed 2026-08-17 — see §13 settled) | **done 2026-08-16 — gate not met.** Fabricated publishable records reached 0, but the A4 size budget fails (§13 open decision 0) |
| 9 | Coverage survey — research only, no code. | `docs/COVERAGE_SURVEY.md`; this revision (8.2) | **done 2026-08-16** |
| 10 | Coverage package Cov1–Cov3, plus an unplanned §11 classifier measurement and re-baseline. | Four commits; §11 reopened on the precision half; this revision's 8.3 and 8.4 | **done 2026-08-16/17** |
| 11 | Family taxonomy — research only, no code. Classified every miss across the census 20 and survey 40; drew and read a third stratified sample of 50 records / 170 documents; induced the taxonomy from a `claude-sonnet-5` run. | `docs/FAMILY_TAXONOMY.md`; two commits | **done 2026-08-17** |
| 12 | Revise this plan against `docs/FAMILY_TAXONOMY.md`. No code. | This revision — **8.5**: §6.3 replaced, seven families retired, §17.8 added, §18.1 re-ordered, §18.3a's exit criteria | **done 2026-08-17** |
| 13+ | **One §18 work package per session.** Each item inside it is its own commit, with the suite run between commits. | The package, its gate output, an updated §15, and a pushed branch | next: **finish package D½ — Cov4, then Cov5–Cov7**. Read `docs/FAMILY_TAXONOMY.md` first; §18.1's ⚠ note is why Cov4 precedes all form work, and package D¾ is gated behind it. §13 open decision 0 still blocks committing any cache until a human resolves it |

Sessions 1 and 2 are not overhead. They are what makes the additive-edit discipline in §8 possible, because you cannot make a surgical edit to a file whose structure you inferred. Session 1 found that the single most consequential fact in this project — which PDF library the repository uses — was wrong in every prior version, and that error alone would have produced an unusable Layer C and an AGPL licensing problem.

### 17.4 Standing rules for every implementation session

- State the intended diff **before** making it.
- After editing, paste `git diff --stat` and the test suite output. Never assert a result you did not observe.
- **One commit per §18 item, with the suite run between commits.** Not one commit per session.
- **Commit and push before the session ends.** Never leave the tree dirty (§0.4 rule 5b).
- Stop at the end of the package. Do not begin the next one.
- Stop at any unchecked gate in §15.
- When blocked, stop and ask. Do not improvise.
- End with the §0.4 session report, including what you did *not* do.
- **If you find this plan wrong again, correct it and say so in the report.** Version 7.0 fixed nine errors from versions written without reading the code; it will not be the last. The "What changed in 7.0" table at the top is the pattern to follow — record what was wrong, not just what is now right, so the next session can tell a correction from a fresh assertion.

### 17.5 Where work happens

A proper `git clone`, on a branch, with the test suite runnable and `git diff` available. **Not a copied folder of files** — the constraints in §8 are enforced by diff review, and there is no diff without git history. Never push to `main` — which is what GitHub Pages serves — until the Phase 3 gate is cleared.

If `git` reports "dubious ownership" on the checkout, prefix commands with `-c safe.directory="$PWD"` rather than changing global git config.

### 17.6 Cross-platform rules — both Phase 1 failures were Windows blind spots

Development happens on Windows; CI runs on `ubuntu-latest`. The §8.4 gate failed twice in Phase 1, and **neither failure was visible locally**. Both were platform gaps, and both cost a CI round-trip that these two rules would have prevented.

**Rule 1 — mark every new `tools/*.sh` executable at commit time.**

This checkout has `core.fileMode = false`, so `chmod +x` locally is not recorded and the file lands in git as mode `100644`. On a Linux runner it is then not executable. Either invoke it as `bash tools/foo.sh` in the workflow, or record the bit explicitly:

```bash
git update-index --chmod=+x tools/foo.sh
```

Do both, in fact — the workflow invocation is what actually matters, and the mode bit is what makes the script usable by hand on Linux. Verify with `git ls-files -s tools/` before pushing; the mode must read `100755`.

**Rule 2 — any new artifact entering the fingerprint set needs two builds and a green Linux run before its baseline is committed.**

The second failure was line endings: four artifacts are written through `NamedTemporaryFile(newline="\n")` and are LF everywhere, while sixteen go through `Path.write_text()` and take the platform default. A baseline recorded on Windows disagreed with Linux for exactly those sixteen. Nothing about that is visible from a Windows-only test, however many times you run it.

So before committing any baseline that covers a new artifact:

1. Run the producing build **twice, with a delay between**, into separate directories.
2. Diff the **normalized** bytes, not the raw bytes and not the hashes — every artifact contains a timestamp, so a raw diff always reports everything as differing and tells you nothing. Import `normalize` from `tools/fingerprint.py`.
3. Check the artifact's line endings explicitly.
4. Push and confirm green on `ubuntu-latest` **before** treating the baseline as settled.

The general form of the lesson: **a determinism gate is only as good as the axes you varied while testing it.** Time and platform are both axes. Testing repeatedly on one machine varies neither.

### 17.7 Never read a gate's result through `tail`, `head` or `grep`

**This rule was written after reproducing the hazard in the session that wrote it, not from a report.** An earlier draft attributed a false green to package D; that could not be verified against the package D record and the attribution was removed. What *is* verified is this: the coverage-survey session ran `python -m unittest discover -s tests 2>&1 | tail -6`, read `OK (skipped=1)` off the tail, and reported the suite as green. The suite genuinely was green — re-running it bare gave `exit=0` — but **the reported evidence did not establish that**, because a pipeline's exit status is the status of its **last** command, and `tail` returns 0 whatever it was fed. The report was right by luck.

`grep` is worse than useless here: it exits **1** when it matches nothing, so `... | grep FAIL` exits non-zero precisely when everything passed.

The rule, for every gate in this document — the suite, `verify_no_drift`, the query baseline, the size budget:

- **Check the exit code.** Run the command bare, or capture `$?` immediately, or use `set -o pipefail` before any pipeline. Never infer a result from what happened to be on screen.
- **Truncation hides the failure by construction.** `unittest` prints its `FAILED (failures=N)` line last, which survives a tail — but a traceback, an import error, a `no tests ran`, or a crash before the summary does not. `verify_no_drift` prints its differing artifacts *before* its verdict, so a tail is exactly the wrong end.
- **Paste the exit code in the session report**, not just the output. §0.4 already forbids asserting a pass you did not observe; observing the last ten lines is not observing the result.

```bash
python -m unittest discover -s tests; echo "exit=$?"     # correct
bash tools/verify_no_drift.sh; echo "exit=$?"            # correct
python -m unittest discover -s tests 2>&1 | tail -6      # tells you nothing
```

This is the same class of error as §9.4 item 7, where a `-v` check reported a pass as a failure: **a check whose result you have not verified is not a check.**

### 17.8 No family, threshold or acceptance rule without corpus evidence behind it

**Added in 8.5, from a 3-for-3 record against a 3-for-10 one.**

Three families were written **from measurement** — `component`, `focus_area` and `technical_category`, added in D3 from documents the census had already read and quoted. **All three have corpus support.** Ten families were written **from expectation**, before any document in this catalog had been opened. **Seven have none**, and two of the seven produce only false positives (§6.3).

That is not bad luck. It is what happens when a recogniser is specified from what a corpus *ought* to contain, and it has now happened three times in this document with three different instruments:

| Specified from reasoning | What measurement said |
|---|---|
| §6.3's ten families | 7 of 10 have no corpus support; 5 never fire in 170 documents |
| §6.4a's six structural thresholds | *"stated to be calibrated, not because they have been measured"* — D1 refitted three, D5 replaced the load-bearing one entirely |
| §6.3a's ancestor lexicon | Caught 0 of 23 administrative sibling sets in `DE-FOA-0003600`; D4 found it keyed to one agency's outline convention |

**The rule.**

> **Do not add a pattern family, a threshold, or an acceptance rule to this plan or to the code without naming at least one document in the corpus that it matches, and quoting the text it matches.** A specification that cannot name its validating document is a hypothesis, and it must be labelled as one — recorded under "candidate", never in a table that reads as implemented behaviour.

Three corollaries, each of which this project learned the hard way:

1. **A validating document must be quoted, not cited.** `priority_research` looked validated by `332894`, whose heading is *Priority Research Thrusts* — and the pattern requires `Priority Research Direction|Opportunity|PRD`, which that heading does not match. The citation was right and the match was imaginary. Quoting the literal text is what would have caught it.
2. **"Zero matches" is a result and must be read.** B0 measured zero matches from all ten families on three notices in 2026-08-16 and recorded it as the families being appropriately narrow. It was equally evidence that most of them were inert, and that reading was available at the time. **Whenever a family fires zero times over a sample, say so per family, not in aggregate.**
3. **A retired family keeps its evidence.** Retirement is not deletion: record the shape, the reason and what would bring it back, so a later session does not rediscover the idea and re-add it unmeasured. §6.3's retirement table is the format.

This rule governs §6.3, §6.3a, §6.4, §6.4a and any future recogniser, and it applies to *removals* too — `roses_element` is retired on six measured false positives and zero correct matches across 90 records, not because it looked wrong.

---

## 18. Minimum path

§10's four phases describe everything this project could be. **This section describes the smallest version of it that is worth shipping**, and it is what should actually be built. Everything not listed in packages A–G and D½ is deferred, explicitly, with the cost of deferring it written down.

The reason for cutting is not schedule pressure. It is that §10 bundles the core mechanism — *segment a notice into child records and make them findable* — with six or seven adjacent projects that each have their own failure modes, their own credentials, and their own tuning loops. Shipping them together means none of them is observable when something goes wrong. The minimum path isolates the mechanism, proves it, and leaves the rest as separate decisions to be made with evidence rather than in advance.

**Sequencing rule:** one package per session (§0.4 rule 5). Each item inside a package is its own commit with the suite run between commits. A package is not complete until its gate is green and the branch is pushed.

**Ordering rule, added in 8.2: plumbing before patterns, and no exceptions without a measurement.** `docs/COVERAGE_SURVEY.md` ranked every available mechanism by how many records it unlocks. The ordering is not close:

| Rank | Mechanism | Sampled (of 40) | Catalog est. | Where it now lives |
|---|---|---|---|---|
| 1 | Fix the fetch-path gap | 2 | **~48** | **Cov1** |
| 2 | HTML / external pages | 1 | **~43** | **Cov2** |
| 3 | Named / structural unnumbered lists | 2 | ~32 | **deferred** (§18.2) |
| 4 | Lower §6.4 rule 1's floor from 3 to 2 | 3 | ~14 | **rejected** (§18.2) |
| 5 | New ordinal families (bare `N)`) | 1 | ~10 | **deferred** (§18.2) |
| 6 | Multi-attachment fetch + quality ranking | 1 | ~5 | **Cov3** — already built |
| 7 | Word (`.docx`) parsing | **0** | **0 lists** | **measured zero** (§18.2) |
| 8 | Spreadsheet parsing | **0** | **0 lists in sample** | **measured zero** (§18.2) |

Rows 1 and 2 overlap on one record, so their union is ~48, not ~91. **The top of the table is about which bytes arrive; rows 3–5 are about what to do with bytes that already arrive.** That is the opposite of where package D's effort went, and it is consistent with what D concluded on its own evidence: more regexes bought almost nothing. **Any future session proposing pattern work before the Coverage package is complete must first show a measurement that beats ~48 records.**

### 18.1 The packages

#### Package A — Foundations completion

| Item | Notes |
|---|---|
| **Populate the frozen fixtures** — three enrichment and three evidence entries keyed to ids `1001`, `1003`, `1005` | The gate currently covers only the *empty*-cache merge path, because the live cache keys do not intersect the fixture ids (§8.4). Hand-authored entries with facts, citations and a program area bring the populated `merge_document_entry` path under the gate — the exact path package C then modifies. **This is first for that reason: it is what makes every later gate meaningful.** |
| Pin `pdfplumber`, `pdfminer.six`, `pypdf` | §6.1. Own commit; suite before and after |
| `.gitignore` allowlist line for `data/subtopic_records.json` | Ahead of package C, so the cache cannot be silently untracked when it first appears (§0.4 rule 11) |
| Size-budget test | Absolute limits, not a multiplier (§12) |
| Heartbeat file `.github/last_build` | §16.3 — prevents silent 60-day schedule disabling |
| Query set + `evaluation/query_baseline.json` | §8.5 |

**Gate:** suite green with zero test-file edits · `verify_no_drift` green in CI, now covering populated evidence entries · query baseline byte-identical across two consecutive local runs.

#### Package B — Segmentation, offline and self-contained

| Item | Notes |
|---|---|
| `scripts/subtopic_patterns.py` | Ten families, `best_family()` (§6.3) |
| `scripts/subtopic_segmentation.py` | Layers A–D against `pypdf` and `pdfplumber`; acceptance rules (§6.4); derived fields (§6.5); time and page budgets (§6.1) |
| Synthetic fixtures + `tests/test_subtopic_segmentation.py` | One PDF per family, a bookmark-less variant, a TOC-only trap, a reference-list trap; golden outputs, idempotency, rejection cases, a `match_subtopics()` renumbering test, a Layer C bold-detection test |

Nothing in this package is imported by any existing module, so nothing can regress. **Gate:** new tests pass · suite green · `verify_no_drift` unchanged.

#### Package C — Wire the call site, flag off

| Item | Notes |
|---|---|
| `scripts/subtopic_records.py` | Identity matching, term maps, cache I/O with §5.4 serialization, `needs_subtopic_extraction()` |
| Flag-guarded call site in `extract_document_evidence.py` | §8.3, in its four-commit order. The only change to working production code in the whole minimum path |
| `git add` paths in the workflow | Paired with package A's `.gitignore` line |

**Gate:** with the flag **off**, `verify_no_drift` byte-identical and the suite green with zero test-file edits — this is §0.5, and it is the single most important gate in the project. With the flag **on**, run locally against five documents copied out of the cache and confirm a `data/subtopic_records.json` is produced with plausible spans.

#### Package D — Tune and backfill

| Item | Notes |
|---|---|
| **Fix Layer B's body cutoff** — do this first | `body_start` is computed as `max(page_start_offset(p) for p in toc_pages)`, which is where the last TOC page *begins*. TOC candidates therefore sit *after* it and survive the `offset > body_start` filter that exists to remove them. It must be where the last TOC page **ends** |
| **Fix Layer D's TOC/body co-collection** — also first | Layer D collects candidates from every container, TOC pages included. §6.4 rule 6 rejects candidates *confined* to the TOC, so a set mixing TOC and body passes rule 6 and fails rules 2 and 3 instead. Exclude `detect_toc_pages()` output from candidate collection in Layers C and D |
| Implement `structural_siblings` (§6.3a) and calibrate §6.4a's six thresholds | Against `docs/CORPUS_CENSUS.md`. **The headline number is the false-positive count on the eight documents that enumerate nothing** — a structural family that admits any of them is worse than none |
| Read all 286 bookmarks of `DE-FOA-0003600` | Records whether `Catalysis Science` is reachable in the notice, which decides how much of §18.2's `program_taxonomy` deferral survives (§6.7) |
| Pattern tuning | Against the corpus already in the catalog: the 31 BAA records (DARPA, ONR, ARL, AFOSR, NRL, ERDC) and the DOE FOAs. No new source needed (§6.3). The census names the concrete gaps: `Category N`, `Component N`, `Focus Area N`, bare `N - Title`, `topic_area` unable to express sub-lettered `1a`/`1b`, and `roses_element` false-positiving on DoD `A.1`/`E.1` section numbers. *(8.5: package D is complete and this row is history. Three of the four named gaps were closed by D3's `technical_category`, `component` and `focus_area`, and `topic_area` gained its sub-lettered ordinal. The fourth — `roses_element`'s false positives — was never fixed and the family is now **retired** on six further false positives across new documents and zero correct matches in 90 records (§6.3). Do not read this row as work outstanding.)* |
| Full local backfill | High `--max-documents`, run against a copy, cache committed in one reviewable commit (§8.3). The nightly is not used |

> **⚠ The two Layer B/D defects must be fixed before any tuning, because they currently masquerade as pattern failures and will mislead it.** The census's single best match — AFOSR DEPSCoR `363526`, where `dod_topic` correctly matched all twelve topics — is rejected today with `('ordinal_sequence', 'span_length')`. Both TOC copies and both body copies enter the candidate list, so ordinals run 1→12 then restart at 1, and the TOC spans are 120–230 characters against a 200-character minimum. Read without this note, that rejection says *"the ordinal rule is too strict"* or *"`dod_topic` is wrong"*, and the obvious response — relax rule 2, or widen the family — is exactly the change §18.3 names as the most damaging available. **A tuning session that starts before these two fixes will draw the wrong conclusion from its own histogram.**

**Gate:** acceptance rate reported **per agency family**, not in aggregate — an 80% average hiding 0% on DoD is a failure, not a pass · rejection-reason histogram read deliberately, with `no_layer_accepted` separated from genuine failures and `run_budget` from `time_budget` · zero low-confidence records in the published set.

#### Package D½ — Coverage

**Added in 8.2, ordered by `docs/COVERAGE_SURVEY.md`'s ranked table.** Package D asked *"can the segmenter find the list?"* and answered it. This package asks the question that turned out to be larger: **do the bytes holding the list ever arrive?** For 46.4% of the catalog they do not, and no pattern reaches a document that is never fetched.

Every item states its expected yield from the survey's stratified sample — *sampled records out of 40* and the *catalog extrapolation* — because two of the four are small and saying so up front is what stops a later session from over-investing in them.

> **⚠ Re-ordered in 8.5: Cov4 comes before any new family work, and package D¾ is gated behind Cov4's gate passing.**
>
> `docs/FAMILY_TAXONOMY.md` measured the families at **10% of the enumerating population** and found the two largest uncovered forms to be **F4 named/bulleted (~73 records)** and **F1 bare numbered (~31)**. Both are forms where structure carries no signal about whether a set is fundable — F4 demonstrably so, since `362233`'s five real Focus Areas sit one subsection above five decoy bullets with no ordinal, no outline and no lexical difference between them.
>
> **So the classifier is the precondition for the recall work, not its final gate.** A recogniser for either form shipped without a semantic filter in front of it re-opens exactly the fabrication surface D5 spent a package closing — and this time at ~104 records of new input rather than the 22 sets D5 was fitted on. Building F4 or F1 first would be building the 43-fabricated-cards outcome deliberately.
>
> This inverts 8.2's ordering, which put all pattern work below all plumbing on the grounds that plumbing was larger. Plumbing *was* larger and Cov1–Cov3 are done. What 8.2 could not know is that the remaining pattern work is mostly unsafe rather than mostly small.

| Item | Expected yield | Notes |
|---|---|---|
| **Cov1. Fix the `source_for_record` selection gap** | **2/40 sampled · ~48 catalog** (overlaps Cov2 on one record) | `source_for_record()` returns `None` for **685 of 1,475 records — 46.4% of the catalog** — and **672 of those have no evidence entry at all**, so they have never been fetched even once. **236 of the 685 carry live Grants.gov attachments right now.** The rule declining them is `select_primary_document`, which accepts only a PDF carrying explicit NOFO/FOA/RFA/BAA language or a lone PDF in a Full Announcement folder. That is the right rule for **citation** — a wrong one-click link is worse than none — and the wrong rule for **segmentation**, which does not publish the link it read. Measured alternatives, against the 685: any PDF in a Full/Revised Announcement folder **46**; any PDF at all **57**; any non-stub HTML **108**; any attachment at all **236**; dropping the `needs_gap_fill` test on agency URLs **221**; union **372 = 25.2% of the catalog**. **Do not change `source_for_record` itself.** Extend the parallel subtopic-only path that `scripts/subtopic_sources.py` already establishes, so fact extraction, `document_evidence.json` and §0.5 are untouched by construction. 313 records have no source of any kind and stay out of reach under every rule |
| **Cov2. HTML attachment support** | **1/40 sampled · ~43 catalog**, and **108 records reached** whose yield is unmeasured | **366 attachments are `.html`, all NIH; 111 are complete ~145 KB announcements across 108 records; 255 are sub-1 KB stubs.** All 108 are unselectable today purely because `attachment_is_pdf` gates the loop. `extract_html_sections` already produces section/anchor-keyed containers, so the segmentation side needs no new mechanism — this is a selection and dispatch change. **Measure before believing the yield:** the two NIH records and one FDA record on that template sampled by the survey enumerate nothing, so reading 20 of the 108 is the first task inside this item, not an afterthought. Also handle the stub: a 422-byte `.html` is not a document and must not displace the agency URL |
| **Cov3. Re-enable multi-attachment fetch** — **done 2026-08-16, and it needed no code change** | **1/40 sampled · ~5 catalog** | **Traced against the live record before anything was written, which is why nothing was.** `source_for_record()` picks `Atch 10 BAA Attachment - Security Program Questionnaire.pdf`; `attachment_sources` offers 6 of the record's 17 attachments; `collect_attachments` ranks `FA2391-23-S-2403.pdf` **first**, because its description reads "PACER BAA" and the `\b(nofo\|foa\|rfa\|baa)\b` test fires; the primary returns `no_layer_accepted`, the BAA returns **18 spans**, and the better result wins on score rather than order. The path was already correct end to end. Two observations recorded instead of changes: the winning result is `low` (Layer D plus §6.6's secondary cap) and **never publishes**, which is Cov4's evidence and not a threshold to tune; and a 9.5 MB, 76-page `Model Contract` attachment consumed the **per-document time budget** — harmless here because the BAA had already won, but on a record whose topic list ranks later, a fat contract could eat the budget first. `tests/test_subtopic_sources.py::FurniturePrimaryTests` pins the ranking so a future change to `SKIP_TOKENS`, `MAX_ATTACHMENTS` or `_score` cannot silently un-win it. Original note follows.<br><br>Already built (`scripts/subtopic_sources.py`, §6.6) and currently neutralized by its own `low` cap. The census justified it on NRL `352741` alone, which it did **not** fix. The survey supplies the case that it does: **AFRL PACER `349554`, whose selected primary is a one-page Security Program Questionnaire while `FA2391-23-S-2403.pdf` yields 18 correct topics** through production's own segmenter. Two things must land with it — selection by *result quality* rather than attachment order (4 records of 1,475 have a furniture-named primary, and this is one), and the `low` cap, which Cov4 replaces rather than lifts |
| **Cov4. Redesign the confidence model** — **narrowed 8.7 to `inferred` and `inline` provenance** | Unblocks **every** item above, and 2 of the survey's 10 enumerating records immediately | Its own item, specified in full below. **Rewritten 8.3:** the unit of judgment moves from set to span (§6.4b), a classifier filters spans (§11: 7/7 contaminants, 0/107 false rejections at Sonnet 4.6), and the review queue handles only the residual — disagreements and abstentions. Fail-closed: no classifier means no new subtopics, never unfiltered ones |
| **Cov5. Fix span-summary alignment** — **done 2026-08-17** | Not a coverage item — a correctness one | **Diagnosed, measured and fixed; §6.5 carries the full record and corrects the mechanism this plan previously named.** One cause for all six cases: `_Flat._find`'s loose title matcher tolerated whitespace *between* tokens and not *inside* one, so a `pdfminer`-inserted space beside a hyphen or em-dash (`X -Ray` for `X-Ray`) made the bookmark title unlocatable, and `_locate_nodes` silently substituted the top of the page. **Prevalence 6 of 223 spans = 2.7% before, 0 of 224 after**, measured by re-running segmentation on all 13 accepted documents rather than by a text heuristic. **Clustered by document, not by method** — all six in `360678` (8.8% of its spans), zero everywhere else. A sixth case was found that nobody had listed. `360678` gains a span (68 → 69): one candidate had been dropped outright, not merely misaligned. **Residual, not fixed:** the `page_start_offset` fallback is still silent, and fires zero times today only because nothing currently fails to locate. Original note follows.<br><br>**Measured 2026-08-17, revised upward the same day (§6.5).** **Five** spans in `360678` — **7% of its 70**, in the document carrying `(q) Catalysis Science` — carry excerpt text describing neither their title nor their subject; `(i) X-Ray Scattering` is summarized by an application-deadline sentence. Span boundaries start at a bookmark offset, so a span can open mid-sentence inside the previous section and the 240-character head summarizes the wrong thing. **Degrades two consumers:** the Cov4 classifier judged those three by the text it was given, and the same string is what a PI reads on the card. **Prevalence unmeasured** — five confirmed by reading, all in one document, all surfaced as a by-product of classifier rejections rather than by a search; nothing has examined the other 222 spans. A start-of-sentence heuristic was tried and discarded for contradicting the observed error pattern. Measure it before trusting the summary for either purpose |

| **Cov6. Fix `_demote()`'s blanket cap on no-primary records** — **added 8.5, and it caps the yield of everything above** | Unblocks publication for the **685 records — 46.4% of the catalog** — that Cov1 made reachable | **`_demote()` decides "secondary attachment" by asking whether a result came from the `primary_content` argument.** Cov1's path passes **no primary at all** when `source_for_record()` returns `None`, so a list read from the record's own `Full Announcement` PDF is treated as a secondary and capped at `low`, which never publishes. **Verified by running production this session:** `363526` — the corpus's *only* `high`-confidence acceptance — returns `8 subtopics, method='toc', confidence='high'` from `segment_document` directly and `confidence='low'` through `segment_without_primary`. The difference is `_demote()`, not the document. Cov1's own note reads *"All ten newly reached records return `no_layer_accepted`"*, which attributes the zero to the records and hides this cap; it bites the moment a reached record enumerates, and `363526` is already that case. **The test is whether the winning document is the record's own announcement, not whether an argument was populated.** Until this is fixed, every new family lands recall in the cache that cannot reach a PI |
| **Cov7. Read 30 more stratum-D records** — **added 8.5** | Firms up **over half** the §1.1 interval | The cheapest outstanding measurement in the project. Stratum D — any non-PDF attachment — holds **483 records, has 12 reads, contributes 40 of §1.1's 171-record point estimate on a single observation, and spans 7–171 on its own.** It also produced the corpus's only tabular list (F5), so its one hit is carrying both a population estimate and a form. Stratum E is larger but its ceiling is bounded by reachability — 313 of its records have no fetchable source of any kind — so **D is where the interval actually closes.** This supersedes the survey's "sample C and E" recommendation, whose C half the taxonomy sample discharged (C is now 18 of 27 read). Reuse `pick50.py`'s stratification with a fresh seed and the 90 read records excluded |

**Gate:** unreachable-record count re-derived and reported against the catalog, not the evidence cache · for each of Cov1–Cov3, records *reached* and records *yielding an accepted list* reported separately, because they are different numbers and conflating them is how the multi-attachment path was over-sold the first time · **fabricated publishable records still 0**, measured the way D5 measured it — by reading every title in the publishable set, not by sampling · **Cov6 verified by re-running `363526` end to end and observing `high`, not by reading the code** · §0.5 byte-identical with the flag off.

##### Cov4 in full — span filtering, with a review queue for the residual

**⚠ Narrowed in 8.7 to `inferred` and `inline` provenance only.** §5.1's ladder
decides which spans reach this filter at all, and **`native` and `referenced`
children bypass the classifier and the review queue entirely.** The reason is
that Cov4 answers one question — *did generic inference find the fundable list,
or the announcement's furniture?* — and that question does not arise when the
agency published the list itself. Running a semantic filter over a ROSES table
would spend money and add a network failure mode in order to second-guess an
authoritative source, and a disagreement between the two is a **canary failure**
(§7.4), not a filtering decision.

**Cov4 is still required, and the reason is PACER.** `349554`'s 18 topics resolve
at Layer D over a secondary attachment — **`inferred` provenance, no structured
source, and the extraction is known-correct** (18/18 in every model run, §11). No
structured source covers AFRL PACER and none is proposed in D⅝. So this item is
smaller, not gone: it keeps exactly the population that generic inference
produced, which is the population it was designed for.

**What this changes about the gate.** Cov4's validation set must now be drawn
from `inferred` and `inline` records specifically, not from whatever the backfill
happens to accept. If D⅝'s S1 lands first, the ROSES parents leave the
classifier's population entirely and the residual is smaller and differently
distributed — so **re-derive the validation set after D⅝, not before**.

**The problem is not a threshold, and this must be stated before the design or someone will tune instead.** D5's fitted tiers took fabricated publishable records from 54 to 0 and cost nothing legitimate. They also suppress a **known-correct** extraction: AFRL PACER's 18 topics resolve at Layer D (`numbered` → `low`), would be won from a secondary attachment (capped at `low` by §6.6), and `low` never publishes. Raising either tier re-admits the exact fabrications D5 removed, because those came from the same tiers. **No threshold setting separates them.** The distinguishing question — *is this the fundable list, or is it the application's furniture?* — is semantic.

**Rewritten 8.3, because that question now has two measured evaluators rather than one assumed one.** §11 records the run: at span level, `claude-sonnet-4-6` caught **7 of 7** known contaminants with **0 false rejections across 107 good spans**, and passed PACER 18/18. The original design put a human on every `low` and `medium` set. That is still the safety net, but it is no longer the filter — it is what handles what the filter will not decide.

**The two-stage shape.** Judgement happens per span (§6.4b), not per set.

| Stage | Does what | Outcome |
|---|---|---|
| 1. Acceptance (§6.4 rules 1–8) | *Is there an enumeration here?* | Fail → zero subtopics, parent untouched. Unchanged |
| 2. Span filter (classifier) | *Is this member a fundable subdivision?* | `reject` → dropped, logged. `accept` → continues. `abstain` / malformed → treated as unresolved |
| 3. Tier gate | *Does the survivor need a human?* | `high` → publishes. `medium` / `low` → queued |
| 4. Review queue | Only **unresolved** spans and **queued** tiers | Approve → publishes. Reject → dropped, feeds the lexicon |

**The queue's population shrinks from "every low and medium set" to "the residual".** That is the point of the rewrite: the reviewer sees disagreements and abstentions, not 115 parents' worth of obviously-correct spans.

| Tier | Today | Under Cov4 |
|---|---|---|
| `high` | publishes | publishes **its surviving spans** |
| `medium` | publishes | filtered, then **queued**, not published |
| `low` | written to cache, never surfaced | filtered, then **queued**, not published |

Nothing publishes without either a `high` tier *and* a passing filter verdict, or an explicit human approval. **This is strictly more conservative than today at `medium`** — deliberate: D4 showed `outline_structural` at `medium` producing an administrative skeleton about as often as a real list on a random sample.

**Fail-closed contract — the single most important line in this item.** The classifier is a network dependency inside a nightly build, and network dependencies fail.

> **When the classifier is unavailable, unauthenticated, rate-limited, times out, or returns anything unparseable, the run publishes NOTHING NEW. It never falls back to publishing unfiltered spans.**

Concretely: an unresolved span is not a passing span. On any classifier failure the affected spans are marked unresolved, they route to the queue, and the previously published set is left exactly as it was — the same "parent untouched" outcome §6.4 already specifies for a failed acceptance, and the same shape as §9.3's rule that a benign outcome exits 0. A build that cannot reach the API is a build that adds no subtopics, and that must be visible in the diagnostics block rather than silent. **The failure mode this forbids — degrading to unfiltered publication — is precisely how 43 fabricated cards would reach a PI, so it is not a defensive nicety.**

**Credentials.** The key lives in **GitHub Secrets**, injected into the workflow step's environment, with the §11 handling rules unchanged: protected environment, `schedule` and `workflow_dispatch` triggers only, never `pull_request_target`, no derived value echoed, key never in committed output. **Local testing has a wrinkle worth writing down, because it cost a session to diagnose:** Claude Code **strips `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `CLAUDE_API_KEY` from tool subprocesses** while passing other user-scope variables through — deliberately, so an agent cannot spend or leak the operator's key. Setting it at user scope and restarting does not change this. **So an agent session cannot run this path itself; a human runs the script in their own terminal and hands back the output.** Design the classifier entry point as a standalone script with a file-based result, not as something only reachable from inside the build, or it cannot be tested at all without a live workflow run.

**Surface.** Reuse `assets/review.js`, which already exists and already does the hard parts. It exposes `globalThis.FUNDING_REVIEW` — `loadReview`, `saveReview`, `sanitizeReview`, `buildPackage`, `recordUsage`, `handoffSummary` — over a browser-local store at `funding-finder.deployment-review.v1`, schema version 1, holding a `source_reviews` map keyed per opportunity with a status drawn from `accurate` / `incorrect` / `could_not_verify`, a field, a note, `document_url`, `document_sha256`, `document_version` and `evidence_ids`. A subtopic review is the same shape with the key extended to `subtopic_id` and the status vocabulary extended to `approve` / `reject` / `could_not_verify`. Bump `REVIEW_SCHEMA_VERSION` when the vocabulary changes — `loadReview` discards any store whose version does not match exactly, so an unbumped change silently drops a reviewer's labels.

**How approval promotes a record.** Labels are browser-local and the catalog is built in a workflow, so promotion cannot be automatic and must not pretend to be:

1. The reviewer approves or rejects queued subtopics in the browser. Nothing about the published catalog changes at this point.
2. `buildPackage` exports the labels — this is why it already carries `document_sha256` and `document_version`, which are exactly the fields that make a label falsifiable when the document changes.
3. A human commits the exported approvals to a reviewed-labels file under `data/` — **which needs a `.gitignore` `!` line and a `git add` line in the same commit (§0.4 rule 11)**.
4. The §7.1 merge admits a `medium` or `low` subtopic **iff** an approval exists whose `document_sha256` matches the current document. A changed document re-queues its subtopics rather than inheriting the old approval, which is the whole reason the hash is in the payload.

**How rejections feed the lexicon.** A rejection is a labelled negative on a *set*, which is the scarcest input this project has — D5's vocabulary was fitted on 22 hand-labelled sets. Rejected titles feed `ADMINISTRATIVE_TERMS` (`scripts/subtopic_patterns.py`) and the §6.4 rule 8 process vocabulary. **Not automatically.** The vocabulary is fitted, and D5 measured what a careless addition costs: adding `information` alone moved the worst legitimate set from 0.008 to 0.043, four times closer to the 0.07 threshold. So rejections accumulate as evidence and a human re-fits, with the same two numbers reported as D5 reported them — legitimate sets lost (must stay 0) and fabrications caught.

**This partially delivers issue #8.** #8 asks for *useful* / *not relevant* / *pursue* labels with mismatch reasons on any card (§7.2b). The review queue is the same storage shape, the same browser-local discipline and the same export path, applied to a narrower population — queued subtopics rather than every result. Build the storage against #8's vocabulary and #9's export requirement so #8 is a widening of an existing control rather than a second one, and say plainly in the help text that approval affects only this browser until the labels are exported and committed.

**What this does not solve.** The reviewer load is much smaller than the original design's but not zero, and there is still no second reviewer, so inter-rater agreement is unmeasured. It still inverts the §18.3 asymmetry for anything approved — the failure mode is now an *approved or filter-passed* wrong span, which reaches a PI with a page anchor exactly as an auto-published one would. And the filter's own measurement is thin: **21 sets, 114 spans, one backfill, one labeller, one run with no self-consistency check, and a prompt that names two of the four semantic modes** (§11's three caveats). What the two stages buy is that a wrong span now has to survive a classifier measured at 100% on held-out-from-prompt labels *and*, below `high`, a person reading its title.

**Gate for Cov4** — in addition to the package gate above:

- **Validation on unseen data, before the filter gates anything.** The D4 corpus fitted nothing here, but it *is* the corpus the discriminator was written from, so it is not a clean test. Label a fresh set of spans — the Coverage package's own backfill produces them — and report the same four numbers: contaminants caught, good spans wrongly rejected, and both rates. **A false-rejection rate above zero on verified-good spans blocks the item**, because that is `Catalysis Science` disappearing.
- **The fail-closed path is tested, not asserted.** Run the build with the key absent and with it invalid; both must produce zero new subtopics, a logged reason, and an unchanged published set.
- **Reviewer load reported as a count**, so the claim that the queue shrank is measured rather than assumed.
- **Cost reported from real `usage` totals**, against §11's $0.190 per 100 sets batched at Sonnet 4.6.
- **Added 8.5 — the validation set must include the populations the filter will actually face.** The 22 sibling sets it was measured on are all outline-derived from documents with bookmarks. Cov4 now gates on at least: **one aggregating agency page** (§6.3b — `363594` is the measured case, where `topic_area` fires ten times on another opportunity's topics and every acceptance rule passes), **one grouped-restarting-counter document** (`330175`, whose 24 real subdivisions restart at `1.` three times), and **one bulleted set with an adjacent decoy** (`362233`, five real Focus Areas above five process bullets). None of the three resembles what §11 measured, and each is a form the recall work depends on.

#### Package D⅝ — Structured Umbrellas

**Added in 8.7, and it sits before D¾ deliberately.** An outside audit found this
plan over-weighting generic document inference relative to hierarchies agencies
already publish. Accepted: §5.1 now ranks provenance and §6.7·0 routes to the
least-ambiguous source first, and this package is where the highest rung gets
built. **Every D¾ item operates at rung 4 on a source that had to be guessed at;
these operate at rung 1 on sources the agency publishes as data.**

Ordered by **breadth of disciplines served per unit of implementation cost** —
not by record count, which is the metric that produced the inversion.

| # | Source | Disciplines served | Cost | Provenance |
|---|---|---|---|---|
| **S1** | **NSPIRES ROSES Table 3** | Earth science, heliophysics, planetary science, astrophysics, biological and physical sciences — **~35 program elements across essentially all of NASA science** | **Lowest available.** Table 3 is a published, structured table of program elements with dates: one row per element, no prose heuristic anywhere | `native` |
| **S2** | **DOE Office of Science referenced taxonomy** | ASCR, BES, BER, FES, HEP, NP — **all six program offices**, ~70 programmes including the case that motivated §6.7 | Medium. Program pages under `science.osti.gov`, one scraper per office shape | `referenced` |
| **S3** | **DoD source router** over Grants.gov, SAM.gov and the ONR/NRL/AFOSR indexes | Engineering, physics, materials, computing, and the DoD basic-research portfolio generally | Highest. Three source systems, a SAM.gov credential (§7.5), and per-lab index shapes that differ | mixed |

> **Build S1 only, then re-measure. This is the gate, not a suggestion.**
>
> One adapter is enough to prove or disprove the provenance model end to end:
> does a `native` source actually bypass Cov4 cleanly, do the canaries catch a
> silent parser failure, does the router refuse lower rungs correctly, and do the
> resulting records survive §8.5's query baseline. **Building all three commits to
> a three-system maintenance surface on an argument nothing has tested yet** —
> and this plan has now twice shipped a mechanism whose measured yield was zero
> (Word parsing, spreadsheet parsing) and once retired seven families that were
> specified from expectation (§17.8).
>
> S1 is also the cheapest thing to be wrong about. If ROSES Table 3 turns out to
> be less parser-friendly than it looks, that is one adapter's cost and the
> conclusion generalises to S2 and S3 before either is written.

**Why S1 first on breadth, not just on cost.** NASA ROSES is the single largest
concentration of *unreached* umbrella parents in the corpus that anyone has
identified: the D5 backfill's nine plausible umbrellas were all ROSES, they
resolve to `agency_notice` URLs and fail at fetch time on `nasaprs.com`
(§18.2's NSPIRES deferral), and `roses_element` — the family named for them —
was **retired in 8.5 with zero correct matches in 90 read records** (§6.3). So
the generic path for NASA is measured at zero and the structured path is
untried. That is the inversion in one agency.

| Item | Notes |
|---|---|
| **S1a. Read Table 3 and record its shape** | §0.4 rule 10: fetch one real response, print it, read it, write code against what was observed. **Do this before writing a parser** and record the row schema, the element-code form, and how continuation years are expressed |
| **S1b. `native` adapter for ROSES program elements** | Adapter lifecycle per §6.7a's recommendation, emitting `subtopic_source: "native"`, `confidence: "high"`, bypassing Cov4 and the review queue (§5.1). Parent match by ROSES element code, never by FOA number |
| **S1c. Canaries** | `expected_solicitations` entry: **ROSES has ≥20 open elements**. A parser returning zero rows on an HTTP 200 must fail loudly (§7.4) |
| **S1d. Re-measure** | Report **new parents gained**, not expanded coverage of existing ones, and re-run §8.5's query baseline. **Then decide S2 and S3 on that evidence** |

**Gate:** S1 only · new parents reported separately from any change to existing records · canary proven by simulating a zero-row HTTP 200 · `native` records confirmed to bypass Cov4 in code as well as in this document · §0.5 byte-identical with the flag off · **S2 and S3 remain unscheduled until S1d is read by a human**.

#### Package D¾ — Forms

**Added in 8.5, ordered by `docs/FAMILY_TAXONOMY.md` §5. Gated behind Cov4's gate passing — see the ⚠ note under D½ — and, from 8.7, behind **package D⅝** as well.**

> **⚠ Re-gated in 8.7. Fm1, Fm2, Fm5 and Fm6 do not start until D⅝'s S1d has been read.** These four are rung-4 generic inference (§6.7·0), and their measured yields were computed against a corpus in which **no structured source had been tried**. Two conditions, both binding:
>
> 1. **Build only against records still uncovered after structured sources.** A parent that D⅝ resolves at `native` or `referenced` is not a candidate for a recogniser, however well it would have matched. Recompute the uncovered population first.
> 2. **Re-measure the yield on that residual.** Every figure in the table below is *records in the 90 read* against the whole corpus. If S1 lands ~35 NASA elements at rung 1, the residual F-form population is smaller and differently distributed, and the ordering below may not survive it.
>
> **Fm3, Fm4 and Fm7 are not re-gated.** Fm3 and Fm4 are repairs to families that already fire on live records, and Fm7 is a decision not to build anything — none of the three widens the inference surface. This is the recall work the taxonomy identified: five of six measured forms have no family, accounting for ~90% of the enumerating population.

Every item carries its measured yield as *records in the 90 read* · *catalog extrapolation*, and **the stability of that extrapolation**, because two of the rows rest on a single observation and one of those is the largest number in the table.

| Item | Measured yield | Notes |
|---|---|---|
| **Fm1. F4 — named / bulleted, no counter** | 9 of 90 · **~73, but ~22 excluding one stratum-E observation** | The largest population and the hardest problem: §6.3a's deferred `label_run` plus a bulleted variant. **Highest false-positive risk in the plan**, and the corpus supplies the proof rather than the worry — `362233`'s five real Focus Areas sit one subsection above *Innovation, Impact, Research Strategy, Focus Areas, Research Team*, with no ordinal, no outline and no lexical separation. **Do not build this on structure alone.** Also note that `structural_siblings`, the only mechanism serving anything like it today, is blind to **55% of the corpus's PDFs** (§6.3a) |
| **Fm2. F1 — bare numbered `N.` / `N)` / `N -`** | **8 of 90 · ~31** (Wilson 47–210 on the pooled rate) — **the most stable uncovered row** | **Blocked by §18.3's prohibition, which 8.5 converted from a flat refusal into exit criteria. Read §18.3 before starting this, and satisfy its four conditions.** Two mechanics the corpus requires beyond the regex: grouped sequences with **restarting counters** (`330175`, §6.4a) and title extraction that survives a trailing em-dash clause (`355150`'s `1. Autonomous platforms – The Army is particularly interested in`) |
| **Fm3. Repair `dod_topic`'s ordinal group** | Recovers `356612` (7 topics) | The group is `(\d{1,2})` and DTRA's topics are `Topic A1` through `Topic A7` — a **letter** ordinal it cannot match at all. `sbir_subtopic` already modelled `\d{1,2}[a-z]?` before its retirement, and `topic_area` gained the same in D3; the inconsistency is an oversight, not a decision, and this is the third time it has appeared. Widen to letters **and** add the validating quote to §6.3's table per §17.8 |
| **Fm4. Repair `thrust`'s granularity** | Same record, same 7 topics | `thrust` fires on `356612` and matches the **container** `Thrust Area 1`, not the seven `Topic AN` items beneath it, so it segments one span where seven exist. A family that matches the umbrella instead of its members is worse than one that misses, because it produces a plausible single card. Either scope `thrust` to the items or retire it under §17.8 — **it currently has no record validating it at the right granularity** |
| **Fm5. F5 — a table path in `extract_containers`** | 1 of 90 · **~40, n=1** | `pdfplumber` is already an authorized dependency (§6.1) and supplies table extraction, so this is a dispatch item, not a dependency one. **Do not fund it on the ~40** — that is one stratum-D observation against 483 records and 12 reads. Fund it on the qualitative argument: `363530` prints the *same 12 topics* as `363526`, which segments correctly, so a validated list is invisible purely because of layout. **Cov7 should be read before sizing this item** |
| **Fm6. F3 — coded named list** | 4 of 90 · ~6 | `PA 1:` (`361908`), `53-24-01 -` (`352741`), `A.1.a.` (`362681`), `Topic A2` (`356612`, which Fm3 covers). Each is agency-specific; a **discovered-prefix** recogniser is the general form and its false-positive profile is unmeasured. Smallest yield in the package — do this last, or not at all |
| **Fm7. F6 — record the verdict, write no pattern** | 4 of 90 · ~4 | **There is nothing to build.** Three of the four are two-item lists (`332127`, `334079`, `346815`) that `structural_siblings` already sees, bookmarked, and that §6.4 rule 1 and §6.4a rule 2d reject on cardinality. Lowering the floor to two stays **rejected** (§18.2). F6 is reachable only through §6.4b's span-level admission, so it arrives free with Cov4 or not at all. Item exists so a later session does not spend pattern effort here |

**Gate:** every new or repaired family names its validating document **and quotes the matched text** (§17.8) · acceptance rate reported per form, not in aggregate · **fabricated publishable records still 0**, by reading every published title · false-positive count reported on the **33 category-(a) documents** in `docs/FAMILY_TAXONOMY.md` §1, which are the measured correct zeros and therefore the right negative set · §0.5 byte-identical with the flag off.

#### Package E — Storage and scoring

| Item | Notes |
|---|---|
| Prototype cross-corpus scoring on the frozen catalog | This is what resolves §13.1. Two BM25 indexes produce scores on different IDF scales; §7.3's max-score rollup is meaningless across them without normalization. **Prototype before choosing** — the decision is conditional on this working (§13.1) |
| Implement the winner | Sidecar `data/subtopics.js` if normalization survives the query gate; in-catalog child records if it does not |
| **Minimal currentness only** | A subtopic is current **iff its parent is current**. Nothing else. No `own_deadline`, no `closed`/`expired`/`removed` states, no archive. One rule, one place, trivially testable |

**Gate:** §8.5 query baseline run · flag-off top-10 churn **zero** · flag-on movement reviewed case by case by a human.

#### Package F — Make it visible

| Item | Notes |
|---|---|
| Retrieval rollup in `assets/search-retrieval.js` | §7.3, guarded by `if (!globalThis.FF_SUBTOPICS_ENABLED)` |
| `term_display` in the subtopic builder | Capped at 60 stems; without it the match chips render stems and look broken |
| `assets/match-explain.js` | §7.6, behind its own `FF_MATCH_EXPLAIN`. Ships independently and is valuable on ordinary records |
| Search UI behind `FF_SUBTOPICS_ENABLED` | `assets/app.js` + `match_explorer.html`. Collapsed children under the parent. Do **not** relax `validateCatalog` |

**Gate:** manual A/B with both flags off — output byte-identical, verified by hand because the hermetic gate does not reach browser code · query baseline unchanged with flags off.

#### Package G — Enable

| Item | Notes |
|---|---|
| Flip `--enable-subtopics` and `FF_SUBTOPICS_ENABLED` | §9.3 |
| Give the document-evidence step an `id:` and route it | Before removing `continue-on-error`, so a parsing failure reports as a degraded source rather than a broken build (§9.3) |
| `PROJECT.md` | Decision, rationale, measured deltas |

**Gate:** §9.4 dispatch checklist walked in full — total job runtime under 15 minutes, no new issue number, #30 updating expected.

### 18.2 Explicitly deferred

Each line states what is lost. None of this is abandoned; all of it is a later decision made with evidence from A–G.

| Deferred | What is lost by deferring it |
|---|---|
| **SAM.gov adapter** (§7.5) — **justification corrected 2026-08-17** | MURI specifically, and any SAM.gov-only notice. **The MURI half was verified this session and is upheld with a sharper basis.** A live Grants.gov search for `MURI` returns **exactly one record — `344592`, the DEVCOM ARL Broad Agency Announcement, which is already in the catalog** — and it is a general foundational BAA, not a MURI solicitation; a search for the expanded phrase returns 25 unrelated NIH, NSF and State records matching on the words. **There is no standalone MURI notice on Grants.gov, so the deferral's premise holds.** Two corrections to how it was argued, though: the supporting claim "MURI appears zero times across the corpus" measured **stored fields**, which are truncated — Grants.gov's own index finds MURI in `344592`'s full text, so the text exists in a document this project can already fetch. And it follows that **`344592` is worth reading before SAM.gov is built**: if the ARL BAA enumerates MURI topics inline, part of what this deferral is said to cost is already reachable at rung 3. Unmeasured; recorded as §15 debt M4. **Not** the development corpus — 31 BAA records are already in the catalog, which is why this was safe to cut. **One consequence the census made concrete:** MURI is absent from the corpus *entirely* — zero mentions across all 958 evidence entries — so `dod_topic`, the family §6.3 lists as serving it, has **no MURI document validating it**. It is validated instead by the AFOSR DEPSCoR notice's identical `Topic N:` convention across twelve topics, which confirms the *convention* but not the agency. Do not read a green `dod_topic` result as evidence MURI will segment |
| **NSPIRES activation** (§10) | NASA ROSES program elements stay invisible as individual records. NASA remains partially covered via Grants.gov |
| **`program_taxonomy` and all `referenced` subtopics** (§6.7) | **Substantially reduced — see the reassessment below.** What is genuinely lost is now program-manager identity, stable per-program URLs, and taxonomy depth beyond what the notice prints. The per-program *children themselves* are no longer part of this deferral, because the census found them in the notice |
| **`expected_solicitations.json` + `check_expected.py`** (§7.4) | No assertion that a known umbrella silently vanished from a healthy source. Mitigated slightly by #30 already being noisy, which this would have made noisier |
| **§7.9 profile rebuild** | Researcher profiles keep the current Crossref + CV + free-text representation. Rehydrated abstracts, recency weighting and the negative-term list all wait. The current representation works; it is just not measured |
| **Expired archive, recurrence grouping, `own_deadline`** (§7.2) | No "include past cycles" view, no cross-cycle linking, no per-subtopic advisory deadline. Package E's minimal rule means an expired parent takes its children with it, which is correct but lossy — last year's MURI topic list is gone rather than archived |
| **§7.2b "not relevant" suppression** | No mute control and no muted-items panel. Recall rises with no user-side way to prune it. This is also issue **#8**, so it has an owner outside this project |
| **§7.7 team match** | Subtopics do not reach `faculty_match.py` or `team-matcher.js`. `team-researchers.js` gets them incidentally, since it scores through the shared BM25 index — so the team page will be *inconsistent* between its two paths until this is done. Worth stating in the help text if it ships that way |
| **Subtopic change events, Atom feeds, alerts** (§10 steps 31–32) | A new topic under an existing umbrella — precisely the event the current feed misses — still does not appear in `changes.xml`, the feeds, or the weekly digest. Subtopics are findable by search only |
| **Help page** (§7.8) | Users meet the parent/child hierarchy with no explanation of what a child card is or what its page anchor means |
| **`evaluate_phase2.py` extension** | No subtopic-level recall metric. Already blocked on **#9** (itself blocked on **#8**), so deferring costs nothing that was available |
| **The optional AI layer** (§11) | Summaries stay deterministic and occasionally clumsy. This was never in v1 |

#### Added in 8.2 — deferred *below* the Coverage package, with their measured yield

**⚠ Superseded in 8.5. The first two rows are no longer deferred — they are package D¾ items Fm1 and Fm2, and their yields were roughly doubled by a larger sample:** `label_run` and the bulleted variant from ~32 to **~73**, bare `N)` from ~10 to **~31**. The reason for the change in standing is not the yield; it is that 8.2 deferred them for being *small* and they are not small. They are now ordered behind **Cov4** rather than behind all plumbing, because they are *unsafe without a classifier* — a different reason with a different exit condition. The third row's verdict is unchanged and still rejected. The original text is kept below because the reasoning it records is still correct.

| Deferred | Measured yield | What is lost by deferring it |
|---|---|---|
| **Named / structural lists with no ordinal** (`label_run`, and the bulleted variant) | 2 of 40 sampled · **~32 catalog** | The largest remaining *pattern* gap and the highest false-positive risk in the table. DHA `362233`'s five real Focus Areas sit one subsection above five decoy bullets — *Innovation, Impact, Research Strategy, Focus Areas, Research Team* — with no ordinal to separate them. Deferring costs ~32 records and avoids re-opening the fabrication surface D5 just closed |
| **New ordinal families for bare `N)`** | 1 of 40 sampled · **~10 catalog** | `345938`'s eight NDEP STEM program areas are written `1) … 8)`. This is precisely the generic numbered family §6.3 and §18.3 name as the most damaging change available — the one that manufactures a subtopic titled *Federal Agency Name*. Same verdict as `332894` |
| **Lowering §6.4 rule 1's three-item floor to two** | 3 of 40 sampled · ~14 catalog | **Rejected, not deferred.** The cheapest change in the table (one constant) and the most dangerous: it would admit DOE `358100`'s real `Topic Area 1`/`2` and EDA's two-program notices, and every two-item administrative pair in 1,475 notices. Recorded because it is the third-largest sampled unlock, so a later session will find it independently and should find this verdict with it |

#### Added in 8.2 — downgraded to **measured zero**, and kept on the record

**Recorded, not deleted.** A measured zero is a result, and deleting it invites a later session to rediscover the idea and build it. In a 40-record stratified sample with **131 files and pages opened and nothing skipped by name**, these produced **no subdivision lists at all**.

| Downgraded | Measurement | Standing |
|---|---|---|
| **Word (`.docx`) parsing** | **0 lists of 40 records.** 177 `.docx` across 88 records; 32 records carry Word and no selectable PDF. Four sampled records publish their announcement *only* as `.docx` — USGS `363537`/`363538`, Embassy Tirana `363247`, Embassy Yerevan `363541` — and **all four are single-project cooperative agreements that enumerate nothing** | Cheap (`zipfile` + a tag strip, no new dependency) and worth doing **for evidence coverage**, not for subtopics. Do not count it toward this feature's yield |
| **Spreadsheet parsing** | **0 lists of 40 records.** 84 `.xlsx` across 64 records; every spreadsheet in the sample was a budget or application template | **The Genesis Mission's 98 focus areas are an outlier, not a class.** That case is real and large — one worksheet, 98 fundable units on a live notice — and it is now the *only* known instance in 1,475 records. Treat it as a per-document case, not a format capability |
| **Per-document targeted extractors** (a reader written for one notice) | Implied zero: the only case that would justify one is Genesis | Deferred on the same evidence. One extractor per document does not generalize, and the survey found no second document that would reuse it. If Genesis is worth its own reader, write it as a per-document case with that framing stated, and never as "spreadsheet support" |

**§8.4 is not on this list.** The hermetic no-drift gate is **built and passing in CI** as of 2026-08-16 — 20 artifacts baselined, sensitivity proven on both the catalog and feeds sides, wired into `tests.yml`. It is the foundation the rest of the minimum path stands on, not a candidate for deferral.

#### Reassessing the `program_taxonomy` deferral after the census

This deferral was written on the premise §6.7 now corrects: that `DE-FOA-0003600` enumerates nothing, so per-program children could only come from scraping `science.osti.gov`. The census disproves the premise. The deferral therefore needs splitting rather than restating, because a scraping project and a pattern are very different amounts of work and only one of them is still required.

**No longer needs a scraper — reachable by Layer A plus §6.3a, inside the minimum path:**

| Now in reach | Why |
|---|---|
| **The existence and naming of per-program children** under the Office of Science omnibus | They are bookmark nodes: `(a) Materials Chemistry`, `(c) Synthesis and Processing Science`. `structural_siblings` selects them by position |
| **A description for each** | The span between one bookmark and the next is exactly what §6.5 already summarizes and §5.2 already builds a term map from |
| **A citable in-notice anchor** | `page_start` from `get_destination_page_number`, giving `p14`-style evidence links identical to every other `inline` subtopic |
| **Topic-facet and program-area tagging per program** | §6.5 runs `program_areas.ENTRIES` over each span. A span for *Synthesis and Processing Science* is a far better input to that vocabulary than the whole 224-page notice, which is the argument §6.5 already makes in the abstract and this document makes concrete |

That is the bulk of what "the DOE BES omnibus gets no child records" was costing, and it arrives with **`subtopic_source: "inline"`**, not `"referenced"` — no new record type, no new lifecycle, no adapter.

**Still genuinely requires the scraper:**

| Still deferred | Why the notice cannot supply it |
|---|---|
| **Program-manager identity and contact** | The Office of Science notice does not print them. AFOSR's does, which is why AFOSR is the *opposite* case — rich contacts, no outline |
| **Stable per-program URLs** (`science.osti.gov/bes/csgb/…`) | The notice cites the program office, not per-program pages. These are what make a child linkable to something durable across FOA numbers |
| **Taxonomy depth below what the notice prints** | If the bookmark tree stops at *Materials Chemistry* and never reaches *Catalysis Science*, only the web tree has that level. **Unverified** — the census read 26 of 286 bookmarks; package D must read all of them and record the answer |
| **Cross-year program identity** | When the FOA number rolls over, matching this year's *Synthesis and Processing Science* to last year's needs a stable key the notice does not carry. §5.3's title-first matching covers renumbering *within* a document lineage, not across a re-issued omnibus |

**The practical consequence for sequencing.** The most painful line in this table is no longer blocked on a scraping project with its own linkage rules. It is blocked on §6.3a working, which is package D pattern work against a corpus that already exists. **§13's open decision 2 — `discoverability.py` versus a `program_taxonomy` adapter — shrinks accordingly**: whichever wins now owns program managers, URLs and cross-year identity, not the children themselves. That is a materially smaller and less urgent decision than the one recorded, and it should be re-read with this in mind before anyone builds either option.

### 18.3 What is kept, and why

Three things survive the cut that a schedule-driven trim would have taken first. Each is load-bearing.

**Flag-off parity (§0.5) and the hermetic gate that enforces it (§8.4).** The entire safety argument for this project is that it can be turned off and the site returns to exactly what it does today. That claim is worthless as an intention and valuable as a mechanically checked invariant. It is also what makes a one-line rollback credible: if the flag is off and output is byte-identical, there is nothing to roll back *to* — the current behavior never left. Keep this even if everything else slips.

**The §8.5 query baseline.** Without it, "did retrieval change?" is answered by looking at a few searches and forming an impression — which is how the OpenAlex concept representation was adopted, and how it survived being wrong for a long time (§7.9). The baseline needs no relevance labels, is deterministic, and turns a subjective question into a diff. It is cheap, and it is the only instrument that tells you package E did what it claimed.

**§6.4 acceptance rules, with nothing-below-`high`-publishes-unreviewed (§7.1, §18.1 Cov4 — until 8.2 this read "low-confidence never publishes"; the queue made it stricter at `medium`, not looser).** These are what make "fail closed" real. A segmentation that does not satisfy all seven rules yields **zero** subtopics and leaves the parent untouched — never a partial or speculative list. The asymmetry is deliberate and worth restating: a missing subtopic costs a user one search that could have gone better; a *wrong* subtopic puts a plausible-looking card with a page anchor and a deadline in front of a PI who may spend weeks writing to it. Relaxing this to raise acceptance rates would be the single most damaging change anyone could make to this design.

### 18.3a The bare-numbered prohibition — exit criteria, not a permanent refusal

**Revised in 8.5. The prohibition stands. What changes is that it now has a stated way out, because it was written when precision was deterministic and it no longer is.**

**Why it was right.** §6.3 and §18.3 name a generic numbered family as *"the single most damaging change anyone could make to this design."* B0 measured the reason: 47, 19 and 74 decimal-numbered administrative lines in three notices, which a bare-`N.` family would have turned into subtopics titled *Federal Agency Name*, *Funding Opportunity Title* and *Announcement Type*. D4 then measured the same failure at scale — 43 of 194 publishable records fabricated, including `1. NOFO Summary` and `A. Purpose`. **Nothing in 8.5 contradicts any of that, and a reader looking for permission to add the family will not find it here.**

**Why it can no longer simply stand.** F1 is carried by **8 of 90 read records** — `332894`, `345938`, `361526`, `360205`, `328902`, `330175`, `355150`, `362910` — across Army, WHS, DOE, USDA, FAA, the Air Force Academy and NRCS, and it is the **most stably measured uncovered form in the corpus** (6 independent stratified observations across three strata). A permanent refusal is a decision to leave ~31 records, the single largest reliably-measured uncovered population, permanently unreachable. That is a defensible decision, but it has to be made deliberately rather than inherited from a note written before the form was sized.

**The two statements are compatible because they are about different things: the form is common, and the form is not a signal.** A bare `1.` carries no information about whether what follows is a research area or *Allowable Costs*. So the question is not "is the pattern safe" — it is not, and no version of it will be — but "is there something downstream that can carry the judgment the pattern cannot."

**Exit criteria. All four must hold before an F1 recogniser may be added, and each is checkable.**

1. **Cov4 shipped and gating, with span-level judgment per §6.4b.** An F1 set must be admitted structurally and then have **every member** classified individually, with only survivors published. Set-level acceptance may never publish an F1 set on its own evidence. The fail-closed contract applies unchanged: no classifier means no F1 subtopics, never unfiltered ones.
2. **Validated on F1 candidates specifically, not on the 22 sibling sets §11 measured.** The validation set must include at least one grouped-restarting-counter document (`330175`) and one document whose numbered lines are predominantly administrative — B0's three notices are the obvious source, and their expected result is **zero published spans**. A false-rejection rate above zero on verified-good F1 spans blocks the item, on the same reasoning as Cov4's own gate.
3. **Measured false positives of zero on the 33 category-(a) documents** in `docs/FAMILY_TAXONOMY.md` §1 — the documents measured to contain no list at all, which is the correct negative set and is larger and more representative than the census's 8 or the survey's 30.
4. **Cov6 fixed**, or the recall is unpublishable anyway (§18.1). Adding F1 while `_demote()` caps 46.4% of the catalog produces cache entries and no user-visible gain, which would make the item look like a failure for an unrelated reason.

**What would settle it either way.** A single measurement: run an F1 recogniser over the D4/D5 backfill corpus — 770 documents already fetched, already labelled for fabrication, already the corpus D5's thresholds were fitted against — with the Cov4 filter in front of it, and report the two numbers D5 reported: **fabricated publishable records (must be 0) and legitimate records lost (must be 0).** If the filter holds on that corpus, criterion 3 is satisfied on 770 documents rather than 33. If it does not, the prohibition becomes permanent on measured grounds rather than on B0's three documents, and this section should be rewritten to say so.

**Until all four hold, F1 stays out.** `docs/FAMILY_TAXONOMY.md` §5.1 states the same conclusion and declines to resolve it; this section is the resolution — not a lift, a condition.
