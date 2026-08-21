# DOE Office of Science structured-source inspection — P6.2

**Read before writing any `science.osti.gov` parser.** Everything below was fetched
live on **2026-08-21** or read out of the committed catalog and
`docs/FAMILY_TAXONOMY.md`. No figure here is an expectation.

> **Headline, stated first because it decides the package.** P6.2 asks whether
> authoritative DOE Office of Science structure can recover fundable children that
> generic document inference misses — **especially for category-(a) parents**. The
> measured answer is that **the Office of Science category-(a) population is empty**:
> the catalog holds **2** Office of Science parents, **both already accepted** by
> generic parsing, and **exactly 1** catalog record points at `science.osti.gov` at
> all. The hypothesis has no test subject in this population. **No DOE source was
> implemented**, and §"What would reverse this" states exactly what evidence would
> change that.

---

## 1. P6.2.1 — the source and parent inventory

### 1.1 The six program offices, probed live

All six `Research` pages are reachable, server-rendered HTML, **no authentication,
no client rendering, no access restriction encountered** (§17.11: there was no
failure layer to isolate — they simply work).

| Office | Authoritative source | Structure shape as published | Usable? | Reason |
|---|---|---|---|---|
| **BES** | `science.osti.gov/bes/Research` | **Not a program list.** 14 research-shaped links, of which 8 are dated CRA *archives*, plus policies and initiatives | **No** | The office page does not enumerate its programs |
| **BES / CSGB division** | `science.osti.gov/bes/csgb/Research-Areas` | **A real list: 15 clean `<a>` links**, grouped under **3 `<h3>` team headings** | **Partly** | 12 programs + **3 organizational team labels** (see §1.2) |
| **ASCR** | `science.osti.gov/ascr/Research` | 9 research-shaped links, labels are **navigation prose**: `ASCR Applied Mathematics Webpage »`, `quantum computing`, `AI` | **No** | Labels are not program names; extracting them is inference, not structure |
| **BER** | `science.osti.gov/ber/Research` | 2 links, both **divisions** (`BSSD`, `EESSD`) | **No** | Division level, not program level |
| **FES** | `science.osti.gov/fes/Research` | 6 links; some are program-shaped, one label is body prose (`research into plasma science and technology`) | **No** | Mixed; no deterministic list |
| **HEP** | `science.osti.gov/hep/Research` | 10 program-shaped links (`Energy Frontier`, `Cosmic Frontier`, …) | **Partly** | Clean labels, but see §2 — there is no parent to attach them to |
| **NP** | `science.osti.gov/np/Research` | 13 links, two labelled `click here` / `click here.` | **No** | Anchor text is navigation, not identity |

**One office in six publishes a program list at the office level (HEP). One division
in one office publishes one (BES/CSGB).** The plan's "walk Division → Team → Program"
sketch describes CSGB accurately and describes nothing else measured here.

### 1.2 The fundability test, applied to the one clean list

`/bes/csgb/Research-Areas` looks like the best case in the whole survey, so it got the
test rather than the benefit of the doubt. The page's own markup answers it:

```
<h3> Fundamental Interactions            <- team heading, organizational
<h3> Chemical Transformations            <- team heading, organizational
<h3> Photochemistry and Biochemistry     <- team heading, organizational
```

**3 of the 15 links are the team headings themselves; 12 are research areas.** A
parser that treated "authoritative DOE page ⇒ fundable subdivision" would publish
three organizational labels as fundable programs. That is precisely the failure the
package was told to avoid, and it is present in the single most promising source.

**What makes the remaining 12 fundable is not the website.** It is
`DE-FOA-0003600`'s own program description, which enumerates the BES sub-programs an
applicant applies against — `(q) Catalysis Science` at level 2, page 46, under
`2. Basic Energy Sciences (BES)` (`docs/CORPUS_CENSUS.md`). **The notice is the
authority for fundability; the website corroborates it.**

### 1.3 The DOE catalog population, in full

Nine DOE records exist. Every one was already classified before P6.2 began.

| Record | Number | Office | Prior status (`docs/FAMILY_TAXONOMY.md`) |
|---|---|---|---|
| `360678` | `DE-FOA-0003600` | **Office of Science** | **accepts** — 70 spans via `outline_structural`, **68 of 71 programmes = 96%**, incl. `(q) Catalysis Science` |
| `361526` | `DE-FOA-0003612` | **Office of Science** | **accepts** — 21 challenge areas, exactly the published list |
| `356623` | `DE-FOA-0003467` | ARPA-E | **accepts** — 7 of 7 categories |
| `363302` | `DE-FOA-0003634` | NETL | list present, `topic_area` matches `Topic Area 1 / 1a / 1b / 2 / 3` |
| `363065` | `DE-FOA-0003627` | NETL | **(d)** known defect — prose mentions and amendment-log hits |
| `358100` | `DE-FOA-0003339` | Idaho / NE | **(c)** acceptance rule — 2 items against the 3-item floor |
| `362036` | `DE-FOA-0003624` | ARPA-E | **(a)** — topics live in **ARPA-E eXCHANGE**, not Office of Science |
| `329436` | `DE-FOA-0002265` | Idaho / NE | **(e)** — `neup.inl.gov` returned 404 |
| `363594` | `DE-FOA-0003215` | NETL | the aggregating-agency-page false positive (**BUG-9**, §6.3b) |

**Catalog records pointing at `science.osti.gov`: 1** (`360678`).

---

## 2. P6.2.2 — the category-(a) test population

Using `docs/FAMILY_TAXONOMY.md` as the authoritative prior classification, and **not
redefining category (a)** — it means *no enumerated fundable subdivision was present
in the material read*, not *no external hierarchy exists*.

| Measure | Office of Science | All DOE |
|---|---|---|
| Candidate parent records | **2** | **9** |
| Previously **category (a)** | **0** | **1** (`362036`, ARPA-E) |
| Other miss categories | 0 | 3 — (c) `358100`, (d) `363065`, (e) `329436` |
| Already accepted by generic parsing | **2 of 2** | 4 |
| Authoritative external structure exists | 1 (`360678` → `science.osti.gov`) | 2 (plus `362036` → ARPA-E eXCHANGE) |
| External structure is **fundable** | 1, and only because the **notice** says so | 1 |

**The Office of Science category-(a) denominator is zero.** There is no percentage to
report, and stating one would be overinterpretation of an empty set.

**The four outward-pointing category-(a) records §6.7·0 named are not DOE.**
Re-checked against the catalog: `345241` is **Army DEVCOM**, `356605` is **ONR**,
`362036` is **ARPA-E**, and `362711` has left the catalog. Two of the three surviving
records are DoD — **they are P6.3's population, not P6.2's.**

---

## 3. P6.2.3 — reconciliation with the existing source router

Inventoried after P6.1 and P8, and **nothing new is needed**: `SourceAdapter`
lifecycle, `registry.collect()` error isolation, the optional `set_context` catalog
hand-off, per-adapter `check_health`, `retain_on_failure` last-known-good, and
§6.7·0's first-refusal/corroboration rules are all in place and are all agnostic to
which agency an adapter serves. **A DOE adapter would have been a new `fetch`/`parse`
pair and nothing else.** No second framework was contemplated and none was written.

---

## 4. P6.2.4 — the provenance ruling

| Candidate | Rung under §5.1 | Why |
|---|---|---|
| BES/CSGB research-area list | **`referenced` at best** | DOE publishes the *page*; it does not publish the parent→child relationship as data. The relationship is asserted by the FOA |
| ASCR/BER/FES/NP research pages | **`inferred`** | Recovering program names from `click here` and `… Webpage »` anchor text is pattern extraction over prose. **Official hosting does not make a parsed textual pattern `native`** |
| The 68 children already extracted from `DE-FOA-0003600` | **`inferred`** (unchanged) | Established by this project's outline segmentation, not by an agency statement. `segmentation_method` stays orthogonal |

**No DOE source qualifies as `native`.** Nothing in P6.2 would have been credited to
`inline`/`inferred`, and nothing here changes the provenance of anything already
extracted.

---

## 5. P6.2.5 — what was implemented, and what was not

**Nothing was implemented as a live source, and that is the finding rather than a
deferral.** The three conditions the package set for building — measured support, a
passed fundability test, and a parent to attach children to — are met by at most one
source, and it fails the third:

1. **BES/CSGB** has a genuine deterministic list, but **12 of its 15 entries are
   fundable only because the notice says so**, and the one parent it serves already
   has **96%** of those children from generic parsing. Net-new children: **0**.
2. **Five of six office pages** publish no deterministic program list at all.
3. **HEP** publishes clean labels but **no HEP-specific parent exists in the
   catalog** — the only Office of Science parents are the two above.

Building it would have added a six-shape scraping surface, a per-office health
canary, and an annual re-verification cost, to corroborate children the project
already has and to publish three organizational labels it would then have to filter
out using the notice it already parses.

### What would reverse this

Any one of these is sufficient, and each is cheap to check when it happens:

- **A new Office of Science parent appears that generic parsing does not resolve** —
  the population is 2 today, and the argument is entirely about that number.
- **DOE publishes a machine-readable program taxonomy** (an API, a JSON feed, or one
  table listing office → program), replacing six page shapes with one.
- **A measurement shows the FOA's 68 spans are wrong or incomplete** where the
  website is right — today the two agree, and the notice is the more specific source.
- **`docs/COVERAGE_SURVEY.md`'s stratum re-read surfaces DOE records not in these 9.**

---

## 6. P6.2.7 — the measurement

**Reported against P6.2's own denominator and never folded into a segmentation
acceptance rate** (§17.8).

| Measure | Office of Science | All DOE |
|---|---|---|
| Candidate parent records examined | **2** | **9** |
| Parents with authoritative external structure | **1** | **2** |
| Parents with **fundable** structured children | **1** (fundability asserted by the notice, not the site) | 1 |
| **Parents resolved by P6.2** | **0** | **0** |
| **Total children recovered by P6.2** | **0** | **0** |
| Previously category-(a) parents recovered | **0 of 0** | **0 of 1** |
| Previously category-(a) children recovered | **0** | **0** |
| Parents still unresolved, with cause | — | 4: `362036` (a, points to ARPA-E eXCHANGE), `363065` (d, defect), `358100` (c, 3-item floor), `329436` (e, 404) |
| Non-fundable structures rejected | **3** — the CSGB `<h3>` team headings | 3 |
| Source failures | **0** — all seven pages fetched cleanly | 0 |
| Provenance split `native` / `referenced` | **0 / 0** | 0 / 0 |
| Overlap with children generic parsing already found | **12 of 12** usable CSGB areas already present among `360678`'s 68 spans | — |
| **Net-new parent coverage attributable solely to P6.2** | **0** | **0** |

**Stated plainly, in the form the package asked for:**

> **P6.2 recovered 0 of 0 tested category-(a) Office of Science parents, producing 0
> fundable children that were unavailable to generic document parsing.**
>
> **The denominator is zero, not small.** The Office of Science population is two
> records and both were already resolved before P6.2 began, so this is not a low
> success rate — it is an untestable hypothesis in this population, and the honest
> result is the empty denominator rather than a percentage.

---

## 7. P6.2.8 — the P6.3 decision table

| P6.2 result | Implication for structured-source generalization | Case for P6.3 |
|---|---|---|
| **Category-(a) penetration: 0 of 0.** The population was empty | The claim that structured sources reach category (a) is **still untested after two attempts**. P6.1 reached (e); P6.2 found no (a) to reach | **Neutral-to-negative.** P6.3 would be the third attempt to test a hypothesis that has not yet met its population |
| **Net-new children: 0.** The one relevant parent is 96% covered by generic parsing | Structured sources are most valuable where the **notice is silent**, not where it is thorough. DOE's notice is thorough | **Supportive but conditional** — DoD BAAs are the case where notices are known to be thin |
| **Gain was entirely dependent on one convenient taxonomy — and even that one was redundant** | NASA's ROSES table was *unusually* clean. Five of six DOE offices publish nothing comparable. **Generalization from ROSES was wrong** | **Cautionary.** Expect DoD to look like DOE, not like NASA, unless measured otherwise |
| **Maintenance surface: 6 page shapes per agency, 3 organizational labels needing notice-based filtering, 0 records gained** | Per-recovered-child cost was **infinite** here (zero denominator). Per-agency cost is real and recurring | **Negative on cost** |
| **The outward-pointing (a) records that do exist are DoD** — `345241` Army DEVCOM, `356605` ONR | The population P6.3 targets is **the one that actually contains outward-pointing category-(a) records** | **The strongest argument for P6.3**, and the only one grounded in measured records |

### Recommendation

**Need one narrowly specified measurement before deciding.**

Not "proceed": P6.3 is the most expensive item in P6 — three source systems, a
SAM.gov credential (**MEAS-6**, blocked on a human), and per-lab index shapes — and
two attempts have now failed to produce evidence that structured sources reach
category (a).

Not "do not proceed": unlike DOE, the DoD population **does** contain outward-pointing
category-(a) records, named and in the catalog today.

**The measurement to run first, and it needs no credential and no adapter:** open
`345241` (Army DEVCOM BAA) and `356605` (ONR Long Range BAA) — both category (a),
both explicitly pointing outward, both already in the catalog — and answer one
question: *does the agency page they point at enumerate fundable subdivisions, or
does it point onward again?* Two documents, one afternoon. If either enumerates, P6.3
has a measured target and a real denominator. If neither does, P6.3 should be
declined on evidence rather than deferred indefinitely.

This is the same discipline that produced P6.1's adapter and this package's negative
result: **measure the source before scheduling the parser.**
