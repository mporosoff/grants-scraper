# Family taxonomy — does the corpus support §6.3's ten families?

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
| Written | `docs/FAMILY_TAXONOMY.md` only. **No code changed, no family added, no plan section edited** |

## Headline

> **Of 53 non-accepting documents, 33 (62%) contain no list to find.** That is
> the largest single fact about yield and it is a property of the corpus, not of
> the families.
>
> **Of the 15 documents where a list demonstrably exists and was read, 9 (60%)
> fail because no family shape covers the form.** So both answers are true at
> once, and they answer different questions: the corpus sets the ceiling, the
> families decide how much of the ceiling is reached.
>
> **Category (f) is now empty and category (e) is down to 5.** Multi-attachment
> fetch and Cov1 closed them. The remaining blockers are 9 missing shapes, 4
> cardinality/depth rules, and 2 occurrence-selection defects.
>
> **The code carries 13 ordinal families, not ten.** §6.3's table has been stale
> since D3 added `focus_area`, `component` and `technical_category`.

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
Addenda) and called it unmodelled by any of §6.2's four layers. Two instances in
90 records is no longer a curiosity.

Both are flagged here as *observations pending the classifier*, not findings.

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
| measured estimate | ~730 K input / ~153 K output tokens, **≈ $4.49 at list pricing** | The run prints measured token counts and actual cost at the end |

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

**Not yet run.** This section, §5 and §6 require `llm_taxonomy.json`, which
needs the API calls in §3. Everything above is complete and independent of them.

When the JSON arrives, this section will report:

- every distinct form found, with the count of documents and of **records** each
  covers, and the per-stratum rate weighted to the catalog population;
- the model's own form names where it invented one, kept verbatim rather than
  folded into my vocabulary;
- a cross-check of the model's form judgments against `structure.py`'s
  mechanical tags, with disagreements listed individually — the tags were hidden
  from the prompt precisely so this comparison means something;
- for each of §6.3's **ten** families: **supported** (a document in the new
  sample carries that form), **contradicted** (the form appears and the family's
  pattern demonstrably fails on it, as `topic_area` did on `Topic Area 1a`), or
  **silent** (nothing in 90 read records exercises it);
- the same verdict for the three families D3 added and for
  `structural_siblings`, because §6.3's table does not list them and the code is
  authoritative (§17.2);
- **forms with no family** and **families with no corpus support**, named
  explicitly.

## 5. A recommended replacement §6.3

**Not yet run.** Will be ordered by document coverage, with the yield each form
would unlock stated as *records in the 90 read* · *catalog extrapolation per
stratum*, and with the false-positive surface of each named — §18.3's asymmetry
applies to every row. **Recommendation only; nothing implemented.**

## 6. Does §1.1's ~13% ceiling survive?

**Not yet answerable.** §1.1 currently states a point estimate of ~128 umbrella
parents (~8–9%) with a plausible top of ~200 records (~13%), resting on stratum
rates of 6–10 records each.

This sample changes the evidence underneath that figure in three ways, and they
do not all push the same direction:

- **Stratum C goes from 6 records to 18** — from a 5-of-6 estimate with a 95%
  interval running roughly 36%–100% to something much tighter. C is only 27
  records, so its effect on the total is bounded, but it is the stratum
  contributing the highest rate.
- **Strata A and B roughly double** (10→23, 9→22). Between them they carry 305
  catalog records at measured rates of 20% and 22%, and they are where most of
  §1.1's point estimate comes from.
- **The five (e) reclassifications cut the other way.** Documents previously
  counted as correct zeros are now unknowns, which means the *denominator* of
  measured non-enumerating records was overstated. That pushes the ceiling up,
  not down.

The corrected figure and what it rests on will be stated here once the run
completes, per stratum and with intervals rather than as a single number.

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

**Not done, and a reader might assume otherwise:**

- **No code was changed, no family was added, no threshold was moved, and no
  section of `docs/TOPIC_LAYER_PLAN.md` was edited** — including §6.3, §6.4a and
  §1.1, which this document argues about. §15 gains no checked box; this is not a
  §18 work package.
- **The API calls in §3 have not been made.** Sections 4, 5 and 6 are open.
- **The `_demote()` defect in §1.2 is recorded, not fixed.**
- **The 30 non-accepting survey documents whose category is (a) rest on the
  survey's reading, not on a re-read in this session.** What was re-derived here
  is reachability and the two blockers that changed. A second rater has never
  seen any of these 60 documents.
- **`363388`'s (a) judgment rests on the document type**, not on extracted text —
  the PDF is image-only and yields 48 characters. If it were a competition, no
  method in this project would know.
- No backfill was run and no cache was committed. §13 open decision 0 still
  blocks committing any subtopic cache.
