# Family taxonomy — does the corpus support §6.3's ten families?

> **⚠ NASA reachability corrected 2026-08-17 — read `docs/ROSES_SOURCE_INSPECTION.md`.**
> Every statement in this document that describes `nspires.nasaprs.com` or
> `solicitation.nasaprs.com` as unreachable, resetting the connection, or
> refusing this client is **a fact about our HTTP client, not about NASA**.
> CPython's default TLS cipher list omits `AES256-GCM-SHA384`, which is the only
> suite those hosts offer; adding it — security level untouched, certificate and
> hostname verification intact — connects at `TLSv1.2`. **All 12 NASA records
> previously recorded as unreachable were re-fetched successfully on 2026-08-17,
> with zero failures.** The counts and classifications below are otherwise
> unchanged; only the attributed cause is wrong.


**§6.3's ten families were written from expectation, before any document in this
catalog had been opened.** B0, the census and the survey have all measured
acceptance *against* them; none has asked whether they are the right ten. This
document tests that, by classifying every miss already on record and then
inducing a taxonomy from a fresh 50-record sample the families have never seen.

| Field | Value |
|---|---|
| Date | 2026-08-17 |
| Corpora classified | census 20 (`docs/CORPUS_CENSUS.md`) + survey 40 (`docs/COVERAGE_SURVEY.md`) = **60 documents, 53 of them non-accepting** |
| New sample | **50 records, 170 documents opened, 7 fetch failures.** Disjoint from all 60 by construction |
| Code read | `scripts/subtopic_patterns.py`, `scripts/subtopic_segmentation.py`, `scripts/subtopic_sources.py`, `scripts/extract_document_evidence.py` at commit `2ececda` |
| Model | `claude-sonnet-5`, `thinking` omitted → adaptive, per §11 |
| Run | 170 calls, **0 errors, 0 unparseable.** 846,201 input / 51,952 output tokens, **$3.32 at list.** Verdicts: 24 yes · 133 no · 13 unclear; confidence 147 high / 13 medium / 10 low |
| Written | `docs/FAMILY_TAXONOMY.md` only. **No code changed, no family added, no plan section edited** |

## Headline

> **Of 53 non-accepting documents, 33 (62%) contain no list to find.** That is
> the largest single fact about yield and it is a property of the corpus, not of
> the families.
>
> **Of the 15 documents where a list demonstrably exists and was read, 9 (60%)
> fail because no family shape covers the form.** Both answers are true at once
> and they answer different questions: the corpus sets the ceiling, the families
> decide how much of it is reached.
>
> **Six forms exist in the corpus. One is covered.** The ten §6.3 families reach
> **~17 of ~171 umbrella records — 10% of the enumerating population.** The other
> 90% use a form nothing recognises.
>
> **Run over 170 real documents, 8 of the 13 families in the code never fire at
> all**, two fire only on documents that carry no list, and one fires on the right
> document at the wrong granularity. Two capture a real list.
>
> **The largest single uncovered form is the one §6.3 forbids.** Bare numbered
> (`N.` / `N)`) is carried by 8 of the 90 read records — the most stably measured
> uncovered form in the corpus — and §6.3 and §18.3 both name a generic numbered
> family as the most damaging change available to this design. That tension is
> the substance of §5 and it does not resolve cleanly.
>
> **Category (f) is now empty and (e) is down to 5.** Multi-attachment and Cov1
> closed them. **The code carries 13 ordinal families, not ten** — §6.3's table
> has been stale since D3.

---

## 1. The miss-cause classification, in full

Requested twice before and not delivered. The denominator is **53** — the 60
census + survey documents minus the 7 that accept a list today.

### Assignment discipline

A document is assigned to the **first** blocker in this chain that stops its
list from becoming a subtopic record. The order matters, because several
documents qualify for two categories and only one of them is the thing to fix:

| Order | Category | Meaning |
|---|---|---|
| 1 | **(e)** | unreachable fetch path — no bytes that could carry the list ever arrived, so whether it enumerates is *unknown* |
| 2 | **(f)** | list present in another attachment the path does not fetch |
| 3 | **(a)** | the documents were read and no list of fundable subdivisions exists |
| 4 | **(b)** | a list is present; no family shape recognises its form |
| 5 | **(c)** | a family matched; a §6.4 / §6.4a acceptance rule refused the set |
| 6 | **(d)** | a family matched; a recorded defect refused it |

The distinction between (a) and (e) is load-bearing and previous documents blur
it. **(a) is a measurement; (e) is the absence of one.** A NYSERDA record whose
portal returns a login page is not evidence that NYSERDA notices do not
enumerate — it is evidence of nothing at all, and counting it as a correct zero
inflates the corpus-is-empty conclusion. Five documents move from (a) to (e) on
that ground.

### Counts

| Category | Census 20 | Survey 40 | **Both** | Share |
|---|---|---|---|---|
| **(a)** no enumerated list present | 8 | 25 | **33** | **62.3%** |
| **(b)** list present, no family shape | 4 | 5 | **9** | 17.0% |
| **(c)** family matched, acceptance rule rejected | 1 | 3 | **4** | 7.5% |
| **(d)** known defect | 2 | 0 | **2** | 3.8% |
| **(e)** unreachable fetch path | 0 | 5 | **5** | 9.4% |
| **(f)** list in another attachment | 0 | 0 | **0** | 0.0% |
| **non-accepting total** | **15** | **38** | **53** | |
| *(accepts a list today)* | *5* | *2* | *7* | |

> **(a) 33 · (b) 9 · (c) 4 · (d) 2 · (e) 5 · (f) 0**

Restricted to documents where **a list exists and was read** — the only subset
that says anything about the families:

| Category | Count | Share of 15 |
|---|---|---|
| **(b)** no family shape | **9** | **60.0%** |
| **(c)** acceptance rule rejected | 4 | 26.7% |
| **(d)** known defect | 2 | 13.3% |

### What this supersedes

`docs/CORPUS_CENSUS.md` reports **(a) 0 · (b) 3 · (c) 1 · (d) 2 · (e) 0 ·
(f) 1**. Two corrections, and the first is the reason this number has been
misleading:

1. **(a) = 0 was an artifact of the denominator.** The census classified only
   its seven *enumerating* misses and left its eight non-enumerating documents
   out of the table entirely. Its own reading puts all eight in (a). Reported as
   zero, the distribution read as a pure mechanism gap; it never was.
2. **`352741` moves (f) → (b).** Verified by running production's
   `best_segmentation` this session: `attachment_sources` returns
   `Amendment 0004.pdf`, the path downloads it, and it comes back
   `no_layer_accepted`. The bytes are no longer the problem — the
   `53-24-01 - HIGH FREQUENCY RADAR` agency-code form has no family. The
   census's prose already said this; its classification table did not.

A third correction concerns a document that *accepts*, and it is the most
consequential thing in this section — see §1.2.

### Every document, individually

`source` = how the judgment was reached: **RUN** re-derived by running
production code this session · **BOTH** carried judgment whose blocker was
re-derived by running code here · **READ** one reader's reading, carried from
the census or survey.

#### Census 20

| id | Notice | Cat. | Src | Why |
|---|---|---|---|---|
| `356623` | ARPA-E SCALEUP DE-FOA-0003467 | **accepts** | READ | `CATEGORY 1:`–`CATEGORY 7:` via `technical_category` (D3), 7/7 correct. Layer D → `low`, does not publish |
| `360678` | DOE Office of Science DE-FOA-0003600 | **accepts** | READ | 70 spans via `outline_structural` incl. `(q) Catalysis Science` p46. Medium, publishes. 2 of 70 are contaminants |
| `361526` | DOE Genesis Mission DE-FOA-0003612 | **accepts** | READ | 21 challenge areas, exactly the published list. The 98 focus areas one level down are in a spreadsheet, unreached |
| `362859` | DARPA MMoMA HR001126S0013 | **accepts** | READ | Focus Area 1–4 via `focus_area` (D3), 4/4 correct. Layer D → `low`, does not publish |
| `363526` | AFOSR DEPSCoR-RC | **accepts** | RUN | 8 spans, method `toc`. **Supersedes the census's (e)** — Cov1 reaches it now. But it arrives at `low`, not `high`; see §1.2 |
| `343653` | DHAPP W81XWH-22 | **(c)** | READ | Ten country FOAs correctly bookmarked at outline depth 0, which §6.3a criterion 1 excludes by construction |
| `332894` | Army LQC BAA W911NF21S0009 | **(b)** | READ | Six Priority Research Thrusts as bare `1.) Spin qubits, fast.` at depth 0. Only the generic numbered family §6.3/§18.3 forbid would catch it |
| `352741` | NRL Long Range BAA | **(b)** | BOTH | **Supersedes (f).** 32 topics coded `53-24-01 - HIGH FREQUENCY RADAR` in `Amendment 0004.pdf`, which *is* fetched today. No family covers the agency-code form |
| `362329` | DHA PRMRP HT942526PRMRPPCTA | **(b)** | READ | Bulleted topic areas under a named portfolio (`AUTOIMMUNE DISORDERS AND IMMUNOLOGY` → `• Celiac Disease`). No ordinal, no outline |
| `362681` | AFOSR Open BAA FA955026S0001 | **(b)** | READ | 39 portfolios coded `A.1.a.` + a repeated `Program Description:` label; zero bookmarks. Neither form has a family |
| `360339` | CDC global health jg-26-0054 *(left the catalog)* | **(d)** | READ | `Component 1-5` matched; located occurrences are a front-matter summary, spans 88–239 chars against a 200 floor. Occurrence selection |
| `363065` | DOE NETL DE-FOA-0003627 | **(d)** | READ | `Topic Area 1a/1b/1c/2` matches after D3, but 36 hits are prose mentions and amendment-log entries; ordinals read `1,2,1,1,1,…` |
| `345241` | Army DAC BAA W911NF-23-S-0003 | **(a)** | READ | No list in the notice; topics on an external website. Topics-by-reference |
| `355867` | NIH RFA-DA-25-024 | **(a)** | READ | Single RFA, no subdivisions. Attachment is a 429-byte stub; the announcement is reached at the agency URL |
| `356605` | ONR Long Range BAA | **(a)** | READ | No list in the notice; technology areas on the ONR website. Topics-by-reference |
| `357305` | NIH PAR-25-274 | **(a)** | READ | Single PAR, no subdivisions |
| `360261` | AFRL CHEERS FA238424S2334 | **(a)** | READ | No list in any attachment. Selected primary is furniture (a clauses list); the secondary was opened and carries no list either |
| `362005` | HUD PRO Housing *(left the catalog)* | **(a)** | READ | Four goals, not fundable units |
| `362711` | Army ARL NOFO W911NF26S0085 *(left the catalog)* | **(a)** | READ | Points to agency documents |
| `363489` | DARPA HR001126S0016 | **(a)** | READ | One technical area. Correct zero |

#### Survey 40

| id | Notice | Cat. | Src | Why |
|---|---|---|---|---|
| `349554` | AFRL PACER | **accepts** | READ | 18 spans `Topic 1 – Aero-Structures`…`Topic 18` from a secondary, all verified correct. Capped `low` by `_demote()`, does not publish |
| `360205` | USDA NIFA AFRI | **accepts** | READ | 37 spans `1a.`–`7g.`, medium. **Publishes** |
| `355211` | Embassy Libya PAS Annual Program Statement | **(e)** | BOTH | `mygrants.servicenowservices.com` returns a content-free shell. Four further `mygrants` URLs in the new sample do the same. Never read |
| `360003` | NASA ROSES 2025 A.10 INNOVATE | **(e)** | BOTH | Its one attachment is a zip holding a Program Specific Data form. Element text is only on NSPIRES, which refuses the client — reproduced on two more NASA records this session |
| `363296` | BJA Daniel Anderl Judicial Security | **(e)** | READ | `bja.ojp.gov` returns a landing page, solicitation one hop away. Never read. Note the sibling cuts the other way: `363574` (BJS) resolves straight to a 32 K-char PDF |
| `nyserda:PON4924` | NYSERDA Clean Green Schools | **(e)** | BOTH | Portal returns no solicitation. Reproduced on `nyserda:PON5899`, which is a **Partner Portal login page** — a credential wall, a sharper diagnosis than "JavaScript shell". Never read |
| `nyserda:RFQL6152` | NYSERDA Clean Energy Training Services | **(e)** | BOTH | Same portal. Never read |
| `345938` | WHS NDEP STEM Open NFO | **(b)** | READ | Eight program areas as bare `1)`…`8)`; zero bookmarks |
| `362233` | DHA CDMRP Lupus | **(b)** | READ | Five bulleted Focus Areas, no ordinal, sitting one subsection above five decoy bullets with nothing to separate them |
| `363000` | FEMA CTP | **(b)** | READ | Three bulleted project types, no ordinal |
| `363607` | State GHSD Advancing Global Health | **(b)** | BOTH | Six fundable Addenda G–L, **one subdivision per attachment**. Reachable now (6 of 10 attachments fetchable). No family models a subdivision that *is* a whole document, and each file alone holds one item |
| `vpr-email:vpr-aed7d81578b24028` | Sloan Research Fellowships | **(b)** | BOTH | Seven named fellowship fields on the foundation's HTML page. Cov1 fetches it; the fields are named, not numbered |
| `332127` | EDA Seattle | **(c)** | READ | Two named programs `a)`/`b)`, bookmarked and visible to `outline_structural`. Rejected on cardinality: §6.4a rule 2d requires 3–60 |
| `334079` | EDA RNTA | **(c)** | READ | Two named programs (R&E, NTA), bookmarked. Same cardinality floor |
| `358100` | DOE NRC licensing | **(c)** | READ | `Topic Area 1`/`2` matches `topic_area` cleanly. Two items against §6.4 rule 1's three-item floor |
| `334971` | CDC RFA-OH-22-005 | **(a)** | READ | No list |
| `339728` | Army Tactical Behaviors | **(a)** | READ | No list |
| `348923` | FHWA ADCMS | **(a)** | READ | No list |
| `349976` | NIH PATH | **(a)** | READ | No list. Stub attachment; announcement reached at the agency URL |
| `356927` | NIH Precision Probiotics | **(a)** | READ | No list. Same stub-plus-agency-URL shape |
| `359236` | Army Staff Research Program | **(a)** | READ | No list |
| `359816` | FDA Animal Food Regulatory Standards | **(a)** | READ | No list |
| `362036` | ARPA-E IGNIITE 2026 | **(a)** | READ | Has a `D. Technical Areas of Interest` section but does not enumerate under it; categories live in ARPA-E eXCHANGE. Topics-by-reference |
| `362070` | ACF CSBG Tribal Capacity | **(a)** | READ | No list |
| `362839` | ACF Affordable Housing | **(a)** | READ | No list |
| `362848` | DHA Duchenne | **(a)** | READ | One focus area, in prose. Same program office and template as `362233`, different shape |
| `363038` | RBCS Fertilizer Expansion | **(a)** | READ | No list |
| `363180` | FWS State Wildlife Grants | **(a)** | READ | No list |
| `363247` | Embassy Tirana GameON | **(a)** | READ | Single-project cooperative agreement in Word. Production cannot parse `.docx` — but there is no list in it either |
| `363259` | DRL Leveraging Academic Institutions | **(a)** | READ | No list |
| `363370` | Embassy Jakarta Media Small Grants | **(a)** | READ | No list |
| `363388` | ETA UIPL 13-26 | **(a)** | READ | Formula allotment notice, not a competition. An 18.7 MB image-only PDF yielding 48 chars, so mechanically `no_extractable_text`; **the (a) judgment rests on the document type, not on extracted text** |
| `363396` | RUS PART Energy | **(a)** | READ | No list |
| `363446` | NHTSA ITSE | **(a)** | READ | No list |
| `363537` | USGS CESU (1) | **(a)** | READ | Single-project cooperative agreement, Word |
| `363538` | USGS CESU (2) | **(a)** | READ | Single-project cooperative agreement, Word |
| `363541` | Embassy Yerevan American Spaces | **(a)** | READ | Single-project cooperative agreement, Word |
| `363586` | SBA Manufacturing Cybersecurity | **(a)** | READ | No list |
| `45810` | NSF Sociology | **(a)** | READ | No list. The NSF `pub_summ.jsp` page carries the whole solicitation, so this zero was judged on full text |
| `351923` | NSF EPSCoR RII | **(a)** | READ | No list, judged on the full NSF page |

### 1.1 What the distribution actually says

**The corpus sets the ceiling.** 33 of 53 non-accepting documents have no list.
Adding families cannot move them, and no threshold can. This is the same
conclusion §1.1 of the plan reaches from a different direction, and it is not in
dispute.

**Inside the ceiling, the families are the binding constraint.** 9 of the 15
readable-list misses fail for want of a shape — a larger share than acceptance
rules (4) and defects (2) combined. So "more regexes buy almost nothing" is true
of *tuning the thirteen that exist* and false of *the shapes they do not model*.
Those are different claims and package D's stop conflated them.

**The five (e) cases are the honest unknown.** They are 9% of the denominator
and they are not evidence about the corpus in either direction.

### 1.2 A finding that came out of verifying this table

`363526` is the corpus's only `high`-confidence acceptance. The census records it
as unreachable-but-correct. Both halves have changed, and the second is a defect:

```
segment_document(bytes) alone            -> 8 subtopics, method='toc', confidence='high'
via Cov1's path (segment_without_primary) -> 8 subtopics, method='toc', confidence='low'
```

`_demote()` in `subtopic_sources.py` caps any result "won from a secondary
attachment" at `low`. It decides *secondary* by asking whether the result came
from the `primary_content` argument. When `source_for_record()` returns `None`,
Cov1's path passes **no primary at all** — so a list read from the record's own
`Full Announcement` PDF is treated as a secondary and demoted.

**`source_for_record()` returns `None` for 685 of 1,475 records — 46.4% of the
catalog.** For every one of them, Cov1 supplies the bytes and `_demote()`
guarantees the result can never publish. Cov1's own note reads *"All ten newly
reached records return `no_layer_accepted`"*, which attributes the zero to the
records not enumerating. That is true of those ten and it hides the structural
cap that will bite the moment a reached record does enumerate — `363526` is
already that case.

Recorded, not fixed: this is a `subtopic_sources.py` change and this session
writes no code.

---

## 2. The 50-record sample

Stratified on attachment profile × agency family, disjoint from all 60 by
construction (asserted in the sampler), deterministic under seed `20260817`.

| Stratum | Catalog | Read by census+survey | **This sample** | Total read | Share of stratum |
|---|---|---|---|---|---|
| A — one attachment, PDF | 215 | 10 | **13** | 23 | 11% |
| B — 2–4 attachments, all PDF | 90 | 9 | **13** | 22 | 24% |
| C — 5+ attachments, all PDF | 27 | 6 | **12** | 18 | **67%** |
| D — any non-PDF attachment | 483 | 7 | **6** | 13 | 3% |
| E — zero attachments, agency URL | 660 | 8 | **6** | 14 | 2% |
| **total** | **1,475** | **40** | **50** | **90** | **6.1%** |

Agency families: other 9 · DoD 8 · State/USAID 8 · HHS-other 6 · EPA/other-sci 4
· Interior 3 · DOE 2 · NASA 2 · NIH 2 · NSF 2 · DOT 2 · USDA 2.

**The quota is deliberately re-weighted, and the bias is stated rather than
hidden.** The survey drew A10 B9 C6 D7 E8 and measured hit rates of 20% / 22% /
83% / 0% / 13%. Three consequences shaped this draw:

- **C gets 12 of its 18 unread records**, taking the stratum to 18 of 27 read.
  That is the survey's own recommendation 1 — C is the richest stratum in the
  corpus and the smallest — and it turns C's rate from a 6-record estimate into
  something close to a census.
- **D-NIH is already measured at 0 hits over 22 reads** (2 in the survey, 20 in
  Cov2). It keeps 2 seats to permit refutation, not to re-confirm a zero.
- **DOE, NASA, NSF, NIH and DOT hold reserved seats.** DOE is nearly exhausted:
  only two unread DOE records with attachments remain in the whole catalog.

C could not supply 14 under a 2-per-agency cap — its unread pool is mostly
near-identical EDA regional planning notices, and a third would measure one
template three times. The two seats went to A and B. **Every catalog figure
below is computed per stratum and weighted by that stratum's catalog population,
never from the raw 50.**

### What was opened

**170 documents across 50 records.** 138 Grants.gov attachments and 32 agency
pages; 129 PDF, 26 HTML, 6 `.docx`, 1 `.xlsx`, 1 zip, 7 fetch failures.

**No filename, extension or folder skipping.** `subtopic_sources.SKIP_TOKENS` is
deliberately not consulted: it is one of the two heuristics that has already
over-matched, and `349554`'s real BAA sits behind exactly that kind of filter.

**The agency page is fetched for every record that has one**, not only for
zero-attachment records — which closed a gap in the first pass of this
instrument. `348407` and `349618` are NIH records whose only attachment is a
422-byte stub; production filters the stub and falls back to the agency notice,
so stopping at the stub would have recorded two false zeros. Fetched properly,
those two pages yield 195 K and 120 K characters of announcement.

**71 of 129 PDFs carry no bookmarks at all.** For those the heading-candidate
lines are the only structural signal, which is why the extractor's cap was
raised from 260 to 600 lines and why truncation is now reported per document —
a truncated heading list produces a false zero indistinguishable from a real
one. After the raise, 2 documents remain marginally truncated at 601 and 602.

### The seven fetch failures

All seven are agency pages, and they independently reproduce the census's D4
failure table on entirely different records:

| Host | Records | Failure |
|---|---|---|
| `nspires.nasaprs.com` / `solicitation.nasaprs.com` | `360004`, `363241` | SSL EOF |
| `www.transit.dot.gov` | `363321` | 403 Forbidden |
| `www.fema.gov` | `363188` | 403 Forbidden |
| `www.aphis.usda.gov`, `www.nrcs.usda.gov` | `363326`, `363285` | ConnectionReset |
| `neup.inl.gov` | `329436` | 404 |

Two further agency pages returned nothing usable without failing: `sam.gov`
(`330175`) yielded **0 characters**, which is worth noting against §7.5's
SAM.gov adapter, and `sfgrants.eda.gov` (`346815`) returned a Salesforce
Lightning shell reading `Sorry to interrupt / CSS Error`.

### 2.1 One shape already visible before any model has run

Two observations came out of building the prompts, and both are structural
enough to state without the classifier:

**`330175` (Air Force Academy, `FA7000-21-S-0001`) is an umbrella with zero
bookmarks.** Its research centres are enumerated in the body as
`1. Aeronautics (Aeronautics Research Center)` through
`15. Center for Space Situational Awareness Research (CSSAR)`, followed by
further numbered groups that restart at `1.`. This is the bare-`N.` shape §6.3
and §18.3 name as the most damaging family to add — and here it is carrying a
real topic list, in a document with no outline to fall back on.

**`361908` (ACF, 5 attachments) looks like a second instance of the
one-subdivision-per-attachment shape.** Its five files are named `PA1_Seventh
Genera…`, `PA 2_Microgrids_…`, `PA 3_Welders to El…`, `PA 4_Tradition in …`,
`PA5_IDEAS_…` — apparently Program Areas 1–5, one per file, each carrying the
same 134-node outline. The survey found that shape once (`363607`, State's six
Addenda) and called it unmodelled by any of §6.2's four layers.

Both are flagged here as *observations pending the classifier*, not findings.
**The first survived and the second did not** — see §4.1: every one of `361908`'s
five attachments carries the whole `PA 1`–`PA 5` list, so it is not a
one-per-attachment case at all. `363607` remains the only one in 90 records.

---

## 3. The API script

`ask_taxonomy.py`, to be run by a human — Claude Code strips
`ANTHROPIC_API_KEY` from tool subprocesses, which is the same constraint §18.1
Cov4 records for the Cov4 classifier.

```bash
python ask_taxonomy.py --dry-run
```

```bash
python ask_taxonomy.py --limit 3
```

```bash
python ask_taxonomy.py
```

| Setting | Value | Why |
|---|---|---|
| model | `claude-sonnet-5` | §11, re-baselined 2026-08-17 |
| `thinking` | **omitted** | On Sonnet 5 that runs adaptive thinking. §11 measures the alternative — `{"type":"disabled"}` — as the whole difference between 88% and 54% span-level precision, and states the requirement as not optional |
| `max_tokens` | 12,000 | Caps thinking *and* response text together on Sonnet 5. A `max_tokens` stop is recorded as an error, never parsed from a truncated object |
| calls | 170, one per document | |
| pre-run estimate | ~730 K input / ~153 K output tokens, ≈ $4.49 at list | **Actual: 846,201 in / 51,952 out, $3.32.** The input estimate was 14% low and the output estimate 3× high; the script prints measured totals at the end |

The request shape follows `rebaseline.py` from the §11 session, which was run
against the real API — it is observed, not inferred (§0.4 rule 10). Only `text`
blocks are read, so thinking blocks cannot corrupt parsing. The run resumes: a
re-invocation retries only failures and unparseable replies.

### What the model is asked

Three questions per document, exactly as specified:

1. Does this document contain an enumerated set of **fundable subdivisions** —
   subdivisions an applicant *chooses among*?
2. If so, quote the headings **verbatim**, in document order, including any
   leading number, letter or code.
3. What **form** do they take — numbered, lettered, named, tabular,
   hierarchical, *or a name the model invents itself*?

Plus `has_counter`, `is_hierarchical`, `marker_example`, and
`subdivisions_referred_elsewhere` — the last because it is what separates (a)
from a topics-by-reference case, which §1's classification needs and no prior
sample recorded.

**Two contamination controls, both deliberate:**

- **The extractor's own form tags are excluded from the prompt.**
  `structure.py` tags every heading line with the form it thinks it matched
  (`bare_N_dot_or_paren`, `named_titlecase`, `agency_code`, …). Showing those
  would hand the model the taxonomy this document is trying to induce, and its
  form answer would be a paraphrase of my regex list rather than a reading of
  the document. The tags are kept out of the prompt and retained in
  `structures.json` as an independent cross-check.
- **The system prompt names the negative classes, not the positive forms.** It
  lists what is *not* a fundable subdivision — review criteria, application
  components, cost categories, project phases, M&E indicators, eligibility
  classes — which is the discriminator §11 already validated at 100/100 on sets.
  The five form names in question 3 are the ones specified in the request, and
  the prompt says explicitly that the list is not exhaustive.

Everything the model sees is verbatim document structure: the outline tree with
depth, parent and page, and the heading-candidate lines in document order.

### Hand back

`llm_taxonomy.json` — 170 entries keyed by `<opportunity_id>#<index>`, each with
the raw reply, the parsed answer, and token counts.

---

## 4. The induced taxonomy

### The measurability filter, applied first

**35 of 170 documents cannot support a verdict** and are excluded from every rate
below: 7 fetch failures, 1 unopened zip, and 27 that yielded under 500
characters and no outline — mostly SF-424-family AcroForms, whose text layer is
344 characters of boilerplate.

This filter is not a formality. The model answered `False` with **`high`**
confidence on `224533#0`, a PDF yielding **zero** characters, and its own reason
says *"no extractable text or headings at all"*. The prose is honest and the
boolean is not, so the boolean is discarded wherever the bytes are empty. The
filter is mechanical, from `structures.json`, not a self-report. Of the 35
excluded documents the model called none of them a hit, so nothing is lost.

**135 documents measured. 24 carry a subdivision set.** At record level, a
record counts as a hit if any of its documents hits:

| | Records |
|---|---|
| carry a subdivision set | **13** |
| measured, no set | 34 |
| no measurable document at all | 3 — `224533`, `360004`, `363241` |

### The six forms

The model produced **18 distinct label strings** for 24 documents —
`numbered list`, `numbered`, `hierarchical numbered`, `hierarchical numbered
lists` are one form under four names. Normalising on **mechanics** (marker shape,
counter present, nesting, tabular) rather than on the label string collapses them
to six. The model's own wording is kept in the last column rather than discarded.

Pooled over all 90 read records — the census 20 contributes *form discovery*
only, never a rate, for the reason in §4.2:

| Form | Records (of 90) | Mechanics | Covered by a family today? | The model called it |
|---|---|---|---|---|
| **F4** named or bulleted, **no counter at all** | **9** | a bullet glyph or nothing marks each item; delimited by position or a repeated label | **No.** `label_run` deferred (§6.3a); `structural_siblings` only if bookmarked | *bulleted topic list, named list with bullets, bulleted named list, named list* |
| **F2** labelled ordinal `<Label> N:` | **9** | a known label word plus a counter | **Yes** — the only covered form | *numbered components, hierarchical numbered/lettered* |
| **F1** bare numbered `N.` / `N)` / `N -` | **8** | a bare counter plus a named title, no label word | **No** — this is the generic numbered family §6.3 and §18.3 forbid | *numbered list, numbered, numbered restarting per subsection, numbered grouped by category, hierarchical numbered* |
| **F3** coded named list | **4** | a repeated non-standard code prefix: `PA 1:`, `53-24-01 -`, `A.1.a.`, `Topic A2` | **No** | *coded named list, lettered topics, named topics with letter-number codes* |
| **F6** lettered `a.` / `(a)` / `a)` | **4** | a letter counter plus a named title | Only via `structural_siblings`, and only when bookmarked **and** ≥3 siblings | *lettered* |
| **F5** **tabular** | **1** | items are **rows of a table**, keyed by a Topic Number column | **No — and no *layer* either.** `extract_containers` has no table path | *numbered table, numbered table rows* |

**F5 is genuinely new.** No document in the census 20 or the survey 40 had it.
`363530` (AFOSR DEPSCoR-CB, `NOFOAFRLAFOSR20260003`) presents 12 topics as table
rows with `SECTION` / `SERVICE` / `TOPIC AREA` / `PROGRAM OFFICER` columns —
and they are *the same topics* as census `363526`, the sibling notice, which
presents them as headings. **One program office, two notices, two forms, and only
one of them is reachable by any mechanism in the plan.**

### 4.1 Every hit, with its quoted headings

| Record | Agency | n | Form | Marker | Verdict |
|---|---|---|---|---|---|
| `330175` | Air Force Academy | 24 | F1 | `1. Aeronautics (Aeronautics Research Center)` | Genuine. Research centres and departments, **zero bookmarks**, counter **restarts at 1** in each of three groups |
| `355150` | Army Applications Lab | 16 | F1 | `1.` | Genuine. 16 technology areas, `1.`–`16.` |
| `328902` | FAA Aviation Research | 7 | F1 | `1.` | Genuine. Corroborated by a form asking for *"Title of Applicable FAA Program Area"* |
| `362910` | NRCS RCPP | 2 | F1 | `1.` | **Borderline.** Two *funding pools* (CCA, State/Multi-State) — an allocation mechanism an applicant does choose among |
| `362871` | ONR FY27 | 14 | F4 | `• Artificial Intelligence and Autonomy` | Genuine. 14 bulleted focus areas with nested sub-topics. Note the census judged a *different* ONR BAA as pointing outward; this one enumerates |
| `363578` | State NEA (Syria APS) | 3 | F4 | `•` | Genuine. Each bullet carries its own Estimated Award Ceiling |
| `358716` | HUD ICDBG | 2 | F4 | *(none)* | Genuine. `Community Facilities`, `Economic Development`. Found on the **agency page**, not an attachment |
| `360333` | CDC-GHC | 5 | F2 | `Component 1:` | Genuine. `Component 1`–`5`, each with a funding ceiling |
| `363302` | NETL `DE-FOA-0003634` | 5 | F2 | `Topic Area 1:` | Genuine. `Topic Area 1 / 1a / 1b / 2 / 3` |
| `356612` | DTRA | 7 | F3 | `Thrust Area 1, Topic A2:` | Genuine, **partially quoted** — 5 of 7 quoted verbatim, 2 marked *"(implied by section on…)"*. The counter is a **letter** code `A1`–`A7` |
| `361908` | ACF ANA | 5 | F3 | `PA 1:` | Genuine. `PA 1: Seventh-generation greenhouses` … `PA 5: IDEAS` |
| `346815` | EDA Public Works | 2 | F6 | `a. Public Works` | Genuine. Same two-program shape as the survey's `332127` / `334079` |
| `363530` | AFOSR DEPSCoR-CB | 12 | F5 | `I.C.1 1` | Genuine. 12 topics as table rows |

**Twelve of the thirteen are unambiguous; `362910` is borderline.** Funding pools
are an allocation mechanism rather than a research subject, but an applicant does
select one, so it is counted and flagged rather than silently dropped.

**A correction to §2.1 of this document.** I predicted `361908` was a second
instance of the one-subdivision-per-attachment shape, from its filenames
(`PA1_…`, `PA 2_Microgrids_…`). It is not: **each of the five attachments
contains the whole `PA 1`–`PA 5` list.** The filenames are per-Program-Area but
the content is not, which makes it *easier* than `363607`, not harder — any one
attachment carries the full list. `363607` remains the only true
one-per-attachment case in 90 records.

### 4.2 Why the census is excluded from every rate

The first version of this analysis pooled the census's 12 enumerating records
into the per-stratum numerators while the denominators counted only the
stratified draws. That inflated the catalog estimate from 171 to 230 and it is
exactly the bias `docs/COVERAGE_SURVEY.md` warns about — *"the census's 12-of-20
was a property of the sample, not of the corpus."* The census 20 was hand-picked
to span shapes and enumerates at 60% against a corpus rate near 26%.

So the two kinds of sample do two different jobs and are never mixed:

- **Rates and catalog yield** use only the seeded stratified draws — the survey
  40 and this session's 50, **87 of which carry a measurable document**.
- **Form discovery** uses all 90. Whether a shape *exists* does not depend on how
  its document was sampled, and the census holds `F3`'s `A.1.a.` and `53-24-01 -`
  variants the random draws never hit.

### 4.3 Rates and catalog extrapolation

| Stratum | Catalog | Read | Hits | Rate | 95% Wilson | Catalog range | Forms found |
|---|---|---|---|---|---|---|---|
| A — 1 attachment | 215 | 22 | 4 | 18% | 7–39% | 16–83 | F1×2 F2×1 F4×1 |
| B — 2–4 | 90 | 22 | 6 | 27% | 13–48% | 12–43 | F1×2 F2×1 F3×1 F4×2 |
| C — 5+ | 27 | 18 | 11 | **61%** | 39–80% | 10–22 | F1×2 F2×2 F3×1 F4×3 F6×3 |
| D — non-PDF | 483 | 12 | 1 | 8% | 1–35% | **7–171** | F5×1 |
| E — zero attachments | 660 | 13 | 1 | 8% | 1–33% | **9–220** | F4×1 |
| **total** | **1,475** | **87** | **23** | **26%** | | | |

> **Point estimate: ~171 umbrella records, 11.6% of the catalog.**
> **Plausible band: 54–538 records (3.7%–36.5%).**

The band is enormous and the reason is specific: **D and E hold 1,143 of 1,475
records and have 25 reads and 2 hits between them.** A and B and C are now
reasonably measured; the two largest strata are not.

### 4.4 Per-form catalog yield

| Form | Catalog est. | Random observations | All 90 | Strata seen | Stability |
|---|---|---|---|---|---|
| **F4** named/bulleted | **~73** | 7 | 9 | A B C E | **~22 excluding stratum E.** 51 of the 73 rests on a *single* E observation against 660 records and 13 reads |
| **F5** tabular | **~40** | 1 | 1 | D | **n=1.** Entirely one observation against 483 records and 12 reads. Order of magnitude at best |
| **F1** bare numbered | **~31** | 6 | 8 | A B C | **The most stable uncovered form.** 6 independent observations across three strata; 6/87 overall = 6.9%, Wilson 3.2–14.2% → 47–210 records |
| **F2** labelled ordinal | **~17** | 4 | 9 | A B C | The only covered form |
| **F3** coded named list | ~6 | 2 | 4 | B C | |
| **F6** lettered | ~4 | 3 | 4 | C | |

> **Forms with a family today: ~17 records — 10% of the enumerating population.
> Forms with no family: ~154 records — 90%.**

### 4.5 Verdict on each family, measured

Production's `FAMILIES` tuple was imported and each pattern run over every
outline title, heading line, HTML heading and worksheet row of all 170 documents.

| Family | §6.3? | Fires | Verdict |
|---|---|---|---|
| `topic_area` | ten | 3 docs, 2 records | **SUPPORTED.** Captures `Topic Area 1 / 1a / 1b / 2 / 3` on `363302` exactly — including the sub-lettered form D3 fixed. Third live validating record |
| `component` | D3 | 1 doc, 1 record | **SUPPORTED.** `Component 1:`–`5:` on `360333`, captured exactly. **The census's validating record `360339` left the catalog, so this is now the family's only live evidence** |
| `thrust` | ten | 3 docs, 2 hits | **CONTRADICTED at the granularity that matters.** It fires on `356612`, a real hit, but matches the *container* `Thrust Area 1` — one item — while the fundable list is `Topic A1`–`A7` beneath it. A family that matches the umbrella instead of the topics segments one span, not seven |
| `dod_topic` | ten | **0 in 170 docs** | **SUPPORTED by prior corpora only** (`363526` Topic 1–12, `349554` Topic 1–18). **CONTRADICTED by `356612`**, whose topics are `Topic A2` — a letter ordinal the `(\d{1,2})` group cannot match. Still no MURI document anywhere |
| `roses_element` | ten | **6 docs, 0 hits** | **FALSE-POSITIVE SURFACE, reproduced.** Fires on `A.1 BACKGROUND AND OBJECTIVES` across five revisions of one DOE Idaho FOA and on `C.3 Budget Documents` in a DRL instructions file. This is the census's `332894` failure mode on entirely new documents, and there is still **no document in 90 records that it correctly matches** |
| `area_of_interest` | ten | 1 doc, 0 hits | **FALSE-POSITIVE SURFACE.** Its one fire is `Area of Interest 4: Process Diversification…` on NETL's aggregating agency page — belonging to a *different* opportunity. See §4.6 |
| `focus_area` | D3 | 0 | **SILENT** here; supported by `362859` in the census. Note `362233`'s "Focus Areas" are bulleted, which it cannot match |
| `technical_category` | D3 | 0 | **SILENT** here; supported by `356623` in the census |
| `technical_area` | ten | 0 | **SILENT in 170 documents** |
| `sbir_subtopic` | ten | 0 | **SILENT in 170 documents** |
| `nsf_track` | ten | 0 | **SILENT in 170 documents**, including four NSF records read end to end |
| `research_thrust` | ten | 0 | **SILENT in 170 documents** |
| `priority_research` | ten | 0 | **SILENT in 170 documents.** `332894`'s heading is *Priority Research Thrusts*, which the `Direction\|Opportunity\|PRD` pattern does not match |
| `structural_siblings` | §6.3a | n/a | **SUPPORTED** by `360678` and `361526`. Reaches F6 and hierarchical F1 **only when the PDF has bookmarks — and 71 of 129 PDFs in this sample have none** |

**Summary of the ten:** 1 supported outright (`topic_area`), 1 supported only by
prior corpora and contradicted here (`dod_topic`), 1 contradicted at granularity
(`thrust`), 2 pure false-positive surfaces (`roses_element`,
`area_of_interest`), **5 silent across 170 documents** (`technical_area`,
`sbir_subtopic`, `nsf_track`, `research_thrust`, `priority_research`).

**Families with no corpus support anywhere in 90 records:**
`technical_area`, `sbir_subtopic`, `nsf_track`, `research_thrust`,
`priority_research`, `area_of_interest`, `roses_element` — **7 of the ten.**
Two of the seven are actively harmful.

**Forms with no family:** F1, F3, F4, F5 outright; F6 only when bookmarked.
**That is five of the six forms and ~90% of the enumerating population.**

### 4.6 A new false-positive surface, and it is Cov1's

`363594#2` is NETL's agency landing page. `topic_area` fires on it **10 times**
and `area_of_interest` once — and every one of those topics belongs to a
*different* opportunity (`DE-FOA-0003634`, `DE-FOA-0003627`). The page aggregates
many FOAs. The model refused it for exactly that reason:

> *"the Topic Area lists visible … belong to other, unrelated funding
> opportunities, not to DE-FOA-0003215 itself"*

**Cov1's `subtopic_only_primary` feeds precisely these pages to the segmenter**
for the 221 records declined only for lack of gap-fill. An aggregating agency
page is a document where the ordinal families fire cleanly, monotonically, with
titled captures — and attach another opportunity's topics to this record. Nothing
in §6.4 detects it, because the set is perfectly well-formed; it is simply about
the wrong opportunity. This is a distinct failure mode from announcement
furniture and no threshold in §6.4a addresses it.

### 4.7 The cross-check against my own mechanical tags, and its result

`structure.py` tagged every heading line with the form it matched, and those tags
were withheld from the prompt so this comparison would mean something. **The
comparison is largely uninformative, and that is the honest result.**
`named_titlecase` and `bullet` dominate every document — 56 to 241 hits each —
including all 24 hits and most non-hits. The tags confirm that *a* form is
present and cannot indicate *which* list is the fundable one.

That is the same lesson §6.4a already recorded about structure: an outline node
with twelve children has twelve children, whatever they are. It applies to
heading-shape tagging just as much, and it is an argument for the classifier
rather than against it.

## 5. A recommended replacement §6.3

**Recommendation only. Nothing here is implemented, and §6.3 is unedited.**

Ordered by catalog coverage, with the stability of each estimate stated because
two of the six rows rest on a single observation.

| # | Form | Catalog est. | Read evidence | Cost | What it buys, and what it risks |
|---|---|---|---|---|---|
| 1 | **F4 — named / bulleted, no counter** | ~73 (**~22 excluding the n=1 in stratum E**) | 9 of 90, strata A B C E | **Large** | The biggest population and the hardest problem. This is §6.3a's deferred `label_run` plus a bulleted variant. **Highest false-positive risk in the table** and the corpus proves it: `362233`'s five real Focus Areas sit two inches above five decoy bullets (*Innovation, Impact, Research Strategy…*) with no ordinal to separate them. Do not build this on structure alone — it is the row that most needs §11's classifier in front of it |
| 2 | **F1 — bare numbered `N.` / `N)` / `N -`** | ~31 (Wilson 47–210 on the pooled rate) | **8 of 90, strata A B C — the most stable uncovered row** | **Small (regex), large (adjudication)** | **This is the row §6.3 and §18.3 forbid, and the corpus says it is the most common uncovered form.** See §5.1 — it should not be added as a bare family, and it should not stay unaddressed either |
| 3 | **F5 — tabular** | ~40, **n=1** | 1 of 90, stratum D | **Medium** | Needs a table-extraction path in `extract_containers`, which has none — `pdfplumber` is already authorized (§6.1) and provides one. Yield is one observation against 483 records: **do not fund this row on this number.** Its real argument is qualitative — `363530` and census `363526` are the same 12 topics from the same office in two forms, so tabular is a *presentation variant* of an already-validated list, not a new population |
| 4 | **F2 — labelled ordinal** | ~17 | 9 of 90 | **Already built** | Keep all six that fire. Two repairs the corpus names: extend the ordinal group to letters so `dod_topic` matches `Topic A2` (`356612`), and make `thrust` match the topics under a Thrust Area rather than the Thrust Area itself |
| 5 | **F6 — lettered** | ~4 | 4 of 90 | **Trivial-to-medium** | `structural_siblings` already reaches it when bookmarks exist. The binding constraint is not the pattern: three of the four are **2-item lists** (`332127`, `334079`, `346815`) rejected by the 3-item floor, and lowering that floor is the change the survey explicitly declined to recommend |
| 6 | **F3 — coded named list** | ~6 | 4 of 90 | **Medium** | `PA 1:`, `53-24-01 -`, `A.1.a.`, `Topic A2`. Each is agency-specific; a discovered-prefix recogniser is the general form and its false-positive profile is unmeasured. Smallest yield of the six |

**Three structural changes matter more than any row above**, and all three came
out of this session's measurements rather than out of the taxonomy:

- **Delete or gate `roses_element` (§4.5).** In 90 read records it has matched
  **zero** real lists and produced false positives in two independent samples.
  It exists for NASA ROSES, every NASA record in the corpus is unreachable, and
  until NSPIRES is solved the family is pure downside.
- **Fix `_demote()` (§1.2).** It caps every result for the 46.4% of records where
  `source_for_record` returns `None`, including lists read from the record's own
  Full Announcement. No new family publishes anything for those records until
  this changes.
- **Judge the aggregating-agency-page case (§4.6)** before Cov1 feeds more of
  them in. It is a well-formed-set failure that §6.4 cannot see.

### 5.1 The F1 problem, stated rather than resolved

§6.3 and §18.3 name a generic numbered family as *"the single most damaging change
anyone could make to this design"* — the one that manufactures subtopics titled
*Federal Agency Name* from 47 matching lines. **That judgment was correct on the
evidence available and it is still correct.** B0 measured 47, 19 and 74
decimal-numbered administrative lines in three notices.

It is also now in tension with the corpus. F1 is carried by 8 of 90 read
records — `332894`, `345938`, `361526`, `360205`, `328902`, `330175`, `355150`,
`362910` — spanning Army, WHS, DOE, USDA, FAA, the Air Force Academy and NRCS.
It is the most stably measured uncovered form there is.

Both statements are true because they are about different things: **the form is
common and the form is not a signal.** A bare `1.` says nothing about whether
what follows is a research area or *Allowable Costs*.

So the recommendation is **not** a bare F1 family. It is that F1 is the clearest
case in the corpus for the architecture §6.4b already adopted: admit the set
structurally, then classify its members individually, and let confidence gate
review rather than publication. §11 measured that classifier at 100% precision
and 100% recall on 21 sets and 7/7 contaminants on 114 spans, and the four
semantic modes no vocabulary test can reach are exactly the modes an F1 family
would otherwise emit. **F1 is the row that makes Cov4 load-bearing rather than
optional** — and `330175` adds a second requirement, because its counter
**restarts at 1** three times, which §6.4 rule 2's monotonic-ordinal test rejects
outright.

## 6. Does §1.1's ~13% ceiling survive?

**Substantially, yes — but it is a central estimate, not a ceiling, and §1.1's
point estimate is too low.**

§1.1 currently says: point estimate **~128 records (8–9%)**, with the top of the
plausible range around **~200 records (~13%)**.

Measured on 87 stratified-drawn records — more than twice the evidence §1.1
rests on:

| | §1.1 today | This session |
|---|---|---|
| Point estimate | ~128 records, 8–9% | **~171 records, 11.6%** |
| Stated range | up to ~200 (~13%) | **54–538 records (3.7%–36.5%)** |
| Records behind it | 40, 6–10 per stratum | **87, 12–22 per stratum** |

Three things changed, and they do not all push the same way:

- **A, B and C roughly doubled** (10→22, 9→22, 6→18). Their rates came in at
  18%, 27% and 61% against the survey's 20%, 22% and 83% — **A and C both came
  down**, C substantially, which is what a 6-record stratum estimate usually does
  when you read twelve more.
- **The five (e) reclassifications in §1 push the other way.** Records counted as
  measured zeros are unknowns, so the non-enumerating denominator was overstated.
- **D and E are still barely read** — 25 records against a combined population of
  1,143, one hit each. They contribute 91 of the 171 and virtually all of the
  interval width.

**So: ~13% survives as a figure to quote, and should be quoted as the middle of a
wide band rather than as its top.** The honest correction to §1.1 is to move the
point estimate from 8–9% to **~11–12%**, and to say plainly that the interval
runs from about 4% to about 36% because two strata holding 77% of the catalog have
25 reads between them.

**What it rests on**, precisely: 87 records drawn by seeded stratified sampling
across attachment profile and agency family, each of whose documents was opened
without filename filtering; 23 judged to carry a set of fundable subdivisions by
`claude-sonnet-5` at adaptive thinking, of which 13 (this session's) were checked
against their verbatim quoted headings by reading, with one borderline
(`362910`). Stratum rates weighted by catalog population; Wilson intervals at
95%.

**The measurement that would tighten it** is unchanged from the survey's own
recommendation, and this session narrows it to one stratum: **read 30 more
stratum-D records.** D is 483 records, has 12 reads, produced the only tabular
form in the corpus, and its interval alone spans 7–171 records. E is larger but
its ceiling is bounded by reachability — 313 of its records have no fetchable
source at all.

---

## Method, and what this session did not do

The 50-record sample was drawn by `pick50.py` from `attach_meta.jsonl` — the
survey's stage-1 census of all 1,635 attachments across all 1,475 records, which
was validated against the live API with zero count mismatches. Documents were
fetched with production's `download_document`, parsed with `pypdf`, `openpyxl`,
and `zipfile` plus a tag strip for OOXML and HTML, and cached to disk so the
extraction could be re-run without re-fetching. Reachability was re-derived by
importing production's `source_for_record`, `subtopic_only_primary`,
`attachment_sources`, `_skippable` and `_is_html_stub` and running them against
the committed catalog. The two re-classifications in §1 were verified by running
`best_segmentation` and `segment_document` themselves.

Probe scripts are not committed, for the same reason as B0, the census and the
survey: they are one-shot instruments against network-fetched documents, and the
test suite has no network path.

The 170 classifications came from `claude-sonnet-5` with `thinking` omitted, one
call per document, prompts built by `build_prompts.py` with the extractor's own
form tags withheld. The run was made by the repository owner in a human shell,
because Claude Code strips `ANTHROPIC_API_KEY` from tool subprocesses. Forms were
normalised on mechanics by `family_verdict.py`; rates and yields were computed by
`yields2.py` with the census excluded from every denominator (§4.2); the family
verdicts in §4.5 come from importing production's `FAMILIES` tuple and running
each pattern over all 170 documents.

**Not done, and a reader might assume otherwise:**

- **No code was changed, no family was added or removed, no threshold was moved,
  and no section of `docs/TOPIC_LAYER_PLAN.md` was edited** — including §6.3,
  §6.4a and §1.1, which this document argues about and recommends changing. §15
  gains no checked box; this is not a §18 work package.
- **§5 is a recommendation.** Nothing in it is built, and the F1 question in §5.1
  is deliberately left unresolved rather than decided here.
- **The `_demote()` defect in §1.2 is recorded, not fixed**, as are the
  `roses_element` and aggregating-agency-page findings.
- **Only this session's 13 hits were checked by reading their quoted headings.**
  The 133 negatives were not re-read; a negative rests on the model plus the
  measurability filter. One hit (`362910`, funding pools) is flagged borderline
  and counted, and `356612` was quoted only 5-of-7 verbatim with 2 items inferred.
- **One run, single-shot, no self-consistency check** — the same caveat §11
  records for its own measurement. Run-to-run variance is unmeasured here too.
- **`llm_taxonomy.json`, `structures.json` and the 170 prompts are not
  committed.** They are one-shot artifacts against network-fetched documents,
  like every prior session's probes.
- **The classifier's negatives on stratum D and E are the weakest part of this
  document**, and §6 says so: 25 reads against 1,143 records.
- **The 30 non-accepting survey documents whose category is (a) rest on the
  survey's reading, not on a re-read in this session.** What was re-derived here
  is reachability and the two blockers that changed. A second rater has never
  seen any of these 60 documents.
- **`363388`'s (a) judgment rests on the document type**, not on extracted text —
  the PDF is image-only and yields 48 characters. If it were a competition, no
  method in this project would know.
- No backfill was run and no cache was committed. §13 open decision 0 still
  blocks committing any subtopic cache.
