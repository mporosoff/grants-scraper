# MEAS-7 — do the outward-pointing DoD category-(a) notices lead anywhere fundable?

**The gate on the P6.3 decision.** Everything below was fetched live on
**2026-08-22** or read from the committed catalog, `docs/FAMILY_TAXONOMY.md` and
`docs/CORPUS_CENSUS.md`. Two records were measured, plus a denominator check. **No
adapter, parser or package was written.**

> **Result first.** **MEAS-7 found 1 of 2 outward-pointing DoD category-(a) parents
> with authoritative external fundable child structure, producing 14 external-only
> children not available to generic parsing.** The Army DEVCOM/TDAC BAA topics page
> is a genuine `referenced` hierarchy with applicant-facing identifiers. ONR's
> "technology areas" are a research-interest taxonomy that names neither the BAA nor
> any way to apply against an area, and they fail the fundability test.
>
> **Recommendation: PROCEED WITH P6.3, scoped to Army/TDAC only** — one source, one
> page, 14 children, and *not* the broad DoD router the old concept imagined.

---

## 1. MEAS-7.1 — the denominator, re-established

Checked against the current catalog and the existing classifications. **This was not
a fresh DoD sample**; it only asks whether the stated two-record denominator went
stale.

| Record | Still in catalog? | Still category (a)? | Notice points outward? | In denominator |
|---|---|---|---|---|
| `345241` Army DEVCOM/DAC BAA `W911NF-23-S-0003` | **yes**, posted, closes 2028-01-04 | **yes** — *"No list in the notice; topics on an external website. Topics-by-reference"* | **yes, in its own words** (§2.1) | **yes** |
| `356605` ONR Long Range BAA `N0001425SB001` | **yes**, posted, closes 2026-09-30 | **yes** — *"No list in the notice; technology areas on the ONR website. Topics-by-reference"* | **yes** (census read) | **yes** |

**Every other DoD category-(a) record in `docs/FAMILY_TAXONOMY.md` was checked and
none qualifies:**

| Record | Classification note | Why it is not in MEAS-7 |
|---|---|---|
| `362711` Army ARL NOFO `W911NF26S0085` | **(a)**, *"Points to agency documents"* | **Would have qualified on shape — but it has left the catalog** (verified absent). No parent exists to attach children to, so it cannot be measured. **Recorded here so it re-enters the denominator if it returns** |
| `360261` AFRL CHEERS | (a), *"No list in any attachment"* | Not outward-pointing — a genuine absence, not a reference |
| `363489` DARPA `HR001126S0016` | (a), *"One technical area. Correct zero"* | Not outward-pointing |
| `339728` Army Tactical Behaviors | (a), *"No list"* | Not outward-pointing |
| `359236` Army Staff Research Program | (a), *"No list"* | Not outward-pointing |
| `362848` DHA Duchenne | (a), *"One focus area, in prose"* | Not outward-pointing |

**Denominator: Y = 2, unchanged.** One near-miss (`362711`) is documented above rather
than silently dropped.

---

## 2. MEAS-7.2 — Army DEVCOM / TDAC

### 2.1 The notice names its own external authority

`345241`'s description states it directly, and this is the strongest single piece of
evidence in the whole measurement:

> *"In an effort to provide DAC's research topics and related information in an easy
> to digest format, DAC has published the following public website listing all current
> DAC research topics: `https://www.army.mil/article/261533`, hereafter referenced as
> the DAC BAA topics website. … DAC funds a modest amount of extramural research in
> certain specific areas, and those areas are described on the DAC BAA topics website.
> **Changes to these topics will be made using this website on an as needed basis. A
> change to the DAC BAA topics website is not an amendment to this BAA** and will not
> be posted on grants.gov and sam.gov."*

The agency is saying that the **website, not the BAA, carries the topic structure**,
and that the two are deliberately decoupled. That is the definition of a `referenced`
relationship under §5.1 — the parent points at an external source that establishes
the children.

### 2.2 What the page actually publishes

Fetched `https://www.army.mil/article/261533` — **HTTP 200, server-rendered HTML,
89,925 bytes, no authentication, no client rendering, no access restriction.**

- Page `<h1>`: **`TDAC BAA Research Topics`**
- Lead line: *"Current Research Topics for the Transformation Decision Analysis Center
  Broad Agency Announcement For Applied Research"* — **followed by `W911NF-23-S-0003`,
  the BAA number itself.** The parent association is explicit and needs no inference.
- Each topic carries three labelled fields: **`Title:`**, **`Announcement ID:`**,
  **`TPOC:`**.

**14 unique topics**, by Announcement ID:

| ID | Title |
|---|---|
| `TDAC BAA-001` | Methodologies and Techniques to Analyze Assistive Automation (AA) & Artificial Intelligence |
| `TDAC BAA-002` | Scientific Understanding and Analytical Methodology for Multi-Domain Operations (MDO) |
| `TDAC BAA-003` | The Science and Analysis of Systems of Systems (SOS) |
| `TDAC BAA-004` | Analytical Methodology for Future Army Systems Enabled by Quantum Technology |
| `TDAC BAA-005` | Artillery — Hypersonics Data and Analysis |
| `TDAC BAA-006` | Network Vulnerability and Effects Assessment Methodology (N-VEAM) |
| `TDAC BAA-010` | Cybernetic Systems (Inferring Human Intent for Human–AI Integration) |
| `TDAC BAA-011` | Humans in Multi-Agent Systems |
| `TDAC BAA-012` | Human Systems Integration (HSI) Modeling and Analysis |
| `TDAC BAA-017` | Sustainment Performance and Mission Success Impacts |
| `TDAC BAA-020` | Machine Learning and Open Source Big Data for Prognostics and Prediction |
| `TDAC BAA-022` | M&S Tools and Algorithms to Assess Electromagnetic Pulse (EMP) Vulnerability |
| `TDAC BAA-024` | Personnel Survivability |
| `TDAC BAA-026` | Support to TDAC Research Competencies |

*The markup repeats the list (27 `Title:` hits for 14 unique IDs) — a duplicated
print/mobile block. Dedup by Announcement ID is deterministic and is a parser detail,
not an ambiguity.*

### 2.3 Fundability test — passed, on applicant-facing evidence

| Criterion | Verdict | Evidence |
|---|---|---|
| Distinct | **yes** | 14 unique `TDAC BAA-0NN` identifiers |
| **Applicant-selectable / genuinely fundable** | **yes** | Each topic has an **Announcement ID** to cite and a **TPOC** to contact; the BAA solicits whitepapers *against these areas*. These are not org units or capability blurbs |
| Children of **this** opportunity | **yes** | The page's own lead names `W911NF-23-S-0003` |
| Absent from previously read solicitation material | **yes** — see §4 | |
| Deterministically identifiable | **yes** | Stable `TDAC BAA-0NN` codes; labelled `Title:` / `Announcement ID:` / `TPOC:` fields |

### 2.4 Provenance and usability

- **Provenance: `referenced`.** The Army publishes the *page*; the notice points at it
  and declares it authoritative. It is **not `native`** — DoD does not publish the
  parent→child relationship as structured data, and official hosting alone does not
  promote a parsed page (§5.1, and the same ruling P6.2 made for DOE).
- **Usability:** server-rendered, no auth, no credential, no robots obstacle
  encountered, one URL, ~90 KB. **URL stability is the main risk** — it is an
  `army.mil/article/<id>` news-article permalink, and the notice pins that exact id,
  so the notice itself is the canary: if the article moves, the BAA text is wrong too.

---

## 3. MEAS-7.3 — ONR

### 3.1 What the notice points at

`356605`'s catalog record points to
`https://www.onr.navy.mil/work-with-us/funding-opportunities`. Fetched: **HTTP 200,
80,875 bytes, server-rendered, no auth.** It is a **listing of solicitation *types***
— BAA/NOFO, CSO, RFP, RFQ, RFI, Special Notice, SeaPort, J&As — plus navigation to
ONR's departments. **It enumerates no topics.**

### 3.2 One authoritative hop, as the measurement allows

Two candidate destinations, both fetched cleanly:

| Page | What it is | LRBAA linkage |
|---|---|---|
| `/our-research/onr-technology-and-research` | An **A–Z index**: *"ONR-sponsored research covers a broad spectrum… Listed below are the technology areas ONR is pursuing."* Entries: `Acoustic Transduction Materials and Devices`, `Active Aperture Array`, `Advanced Autonomous Systems – Super Swarm`, `Aerodynamics`, `Anti-Submarine Warfare`, … | **none** — 0 mentions of `Long-Range`, `LRBAA`, `N00014`, or `white paper` |
| `/organization/departments/code-32` (Ocean Battlespace Sensing) | An **organizational department page**: `Divisions` → *Ocean Sensing and Systems Applications*, *Ocean, Atmosphere and Space Sciences* | **none** — 0 mentions of the BAA or its number |

### 3.3 Fundability test — failed

| Criterion | Verdict | Evidence |
|---|---|---|
| Distinct | yes | The A–Z list has distinct entries |
| **Applicant-selectable / genuinely fundable** | **NO** | The page calls them *"the technology areas ONR is pursuing"* — a statement of **research interests**. There is **no per-area identifier, no POC, no submission instruction, and no reference to the BAA** |
| Children of **this** opportunity | **NO** | **No ONR page reached names `N0001425SB001` or the LRBAA at all.** There is no deterministic parent association to build on |
| Absent from the notice | not reached — the prior test already fails | |
| Deterministically identifiable | partially | Alphabetical prose list; ONR department codes 31–35 are org units |

**Verdict: organizational / research-interest taxonomy, not fundable subdivisions.**
This is exactly the case the package warned about — authoritative, official, and
*not* a child structure. Classifying it as fundable would put ~180 A–Z subject
labels into the catalog as if they were things one applies to.

---

## 4. MEAS-7.4 — external-only, or a generic-parser miss?

The distinction that decides whether this is P6.3 evidence or P5/P7 evidence.

**Army: external-only.** Three independent records agree, and the agency's own words
are the strongest:

1. **The notice states it** — topics live on the website, and *"a change to the DAC BAA
   topics website is not an amendment to this BAA"*.
2. **`docs/CORPUS_CENSUS.md` read the 61-page PDF** and recorded *"no — topics live on
   an external website"*, scored **✓ correct zero**.
3. **`docs/FAMILY_TAXONOMY.md`** classifies it (a): *"No list in the notice; topics on
   an external website."*

*Stated honestly: the 61-page PDF was not re-read in this session. The stored
`document_search_text` is a 2,237-character summary, so its silence on `TDAC BAA-0` is
weak corroboration and is not counted as proof. The census's direct read is the
evidence.*

**So the 14 TDAC topics are children that generic document parsing cannot reach at any
quality of recognizer, because the bytes are not in the document path.** That is
precisely the condition that justifies a `referenced` source rather than a pattern.

**ONR: not applicable** — there is no legitimate child list to compare.

---

## 5. MEAS-7.5 — the result table

| Record | Agency | External source | Fundable child structure? | Child count | External-only? | Generic overlap | Provenance | Technically usable? | Maintenance burden | Implication |
|---|---|---|---|---|---|---|---|---|---|---|
| `345241` | Army DEVCOM / TDAC | `army.mil/article/261533`, **named in the notice** | **YES** — `Title:` + `Announcement ID:` + `TPOC:` per topic | **14** | **YES** — agency states the BAA does not carry them | **0 of 14** available to generic parsing | **`referenced`** | **Yes** — 200, server-rendered, no auth, one URL | **Low**: one page, one shape, dedup by ID; risk is article-permalink drift, and the notice pins the id | **Evidence for P6.3** |
| `356605` | ONR | `onr.navy.mil` funding page → A–Z technology areas / department pages | **NO** — research interests and org units; no identifier, no POC, no BAA linkage | 0 | n/a | n/a | **neither** | Yes, but nothing to ingest | n/a | **Not evidence for P6.3** |

> **MEAS-7 found 1 of 2 outward-pointing DoD category-(a) parents with authoritative
> external fundable child structure, producing 14 external-only children not
> available to generic parsing.**

**Y did not change** — it remains 2. `362711` would have made it 3 on shape, but it has
left the catalog and has no parent to measure; it is recorded in §1 so it returns to
the denominator if the record does.

---

## 6. MEAS-7.6 — the P6.3 decision

**PROCEED WITH P6.3 — scoped to Army/TDAC only.**

The bar the package set was *"at least one meaningful external-only fundable hierarchy
and a proportionate maintenance burden"*. Army clears both: 14 applicant-selectable
topics with stable identifiers, unreachable by any document parser because the agency
publishes them elsewhere by design, behind one server-rendered URL that the notice
itself names.

### Minimum evidence-supported P6.3 scope

| In scope | Out of scope, and why |
|---|---|
| **One `referenced` source: the TDAC BAA topics page for `345241`** | **ONR** — measured, failed the fundability test |
| Parent association by the **BAA number printed on the page** (`W911NF-23-S-0003`) | **A broad DoD router** — the old three-system concept has no measured support |
| Child identity: **`Announcement ID`** (`TDAC BAA-0NN`), deduped | **SAM.gov** — separately gated by its own credential/evidence questions (**MEAS-6**), and nothing here changes that |
| Health: floor on topic count, and **fail-closed** if the page stops naming the BAA number | **AFOSR/AFRL, DARPA, DTRA, ARPA-E, ARPA-H** — not measured; that is **MEAS-8** |
| Provenance **`referenced`**, never `native`; Cov4 bypass obligation carried forward | Any generic pattern family |

**Honest sizing.** This is **one page, one parent, 14 children** — a smaller package
than P6.1 and far smaller than the imagined DoD router. It should be scheduled and
scoped as such, and its yield reported against its own denominator.

### What this makes of the structured-source hypothesis overall

| Attempt | Population reached | Result |
|---|---|---|
| **P6.1 NASA ROSES** | category **(e)** — unreachable bytes | **Strong, and exceptional.** A published table, 63 elements, 10 relationship recoveries |
| **P6.2 DOE Office of Science** | category **(a)** — but the population was **empty** | **No applicable population, no incremental source.** Both parents already resolved by generic parsing |
| **MEAS-7 DoD** | category **(a)**, outward-pointing, 2 records | **1 of 2.** Army yes (14 external-only children); ONR no (organizational taxonomy) |

So the hypothesis is **not** generally true and **not** dead: it holds exactly where an
agency **deliberately publishes topics outside the notice**, which the Army says in so
many words and DOE does not do at all. That is a much narrower and more useful rule
than "structured sources beat inference".

---

## 7. What was not done

No adapter, no parser, no P6.3 implementation, no SAM.gov work, no broad Army/ONR/DoD
crawl, no AFOSR/DARPA/ARPA-E/ARPA-H sweep, no generic pattern work, no P5/P7 work. Six
pages were fetched in total: two destinations plus one authoritative hop each, and two
were only reached to settle the ONR organizational-vs-fundable question.
