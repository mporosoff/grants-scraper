# ROSES structured-source inspection — P6.1a *(legacy S1a)*

> **Canonical IDs.** This document was written as `D⅝ S1` and is now **P6.1**;
> its sections are **P6.1a** (source inspection) and **P6.1d** (final yield).
> Standalone ROSES ingestion is **P8** (legacy `Package N`), taken as **DEC-13**.
> The drift-gate defect is **BUG-7** (formerly debt `D7`). The single translation
> table is `docs/TOPIC_LAYER_PLAN.md` §18.0.3.

**Read before touching `scripts/sources/adapters/nasa_roses.py`.** §6.1's PDF
sketches were written from assumption and were wrong twice; §0.4 rule 10 exists
because of that. Everything below was fetched live on **2026-08-17** and every
figure is from the response, not from expectation.

## 0. The headline finding — NSPIRES is reachable, and four sessions said otherwise

`nspires.nasaprs.com` and `solicitation.nasaprs.com` have been recorded as
refusing this client since the D4 backfill: 12 `ConnectionReset` entries in
`docs/CORPUS_CENSUS.md`, two more in `docs/COVERAGE_SURVEY.md`, two in
`docs/FAMILY_TAXONOMY.md`'s 50-record read, and §18.2's NSPIRES deferral rests
on it.

**It is not the server. It is our TLS cipher policy.**

> **⚠ Corrected 2026-08-17 by the item-1 isolation matrix. The first version of
> this section said the fix was to lower the cipher security level to 1. That
> was sufficient but *not necessary*, and stating it that way would have shipped
> a wider change than the evidence supports.** The corrected diagnosis and the
> full matrix are below.

```
TCP 443 connect                                     OK
1. default SSL context (verified)                   FAIL  SSLEOFError
2. set_ciphers("AES256-GCM-SHA384"), normal level   OK    TLSv1.2 / AES256-GCM-SHA384
3. set_ciphers("DEFAULT:AES256-GCM-SHA384")         OK    TLSv1.2 / AES256-GCM-SHA384
4. set_ciphers("DEFAULT@SECLEVEL=2")  <- normal!    OK    TLSv1.2 / AES256-GCM-SHA384
5. set_ciphers("AES256-GCM-SHA384@SECLEVEL=1")      OK    TLSv1.2 / AES256-GCM-SHA384
6. set_ciphers("DEFAULT@SECLEVEL=1")                OK    TLSv1.2 / AES256-GCM-SHA384
```

**Row 4 is the one that matters: the normal security level works.** So OpenSSL's
`SECLEVEL` was never the blocker. What blocks the handshake is that CPython's
`create_default_context()` curates a **14-suite** TLS≤1.2 list that omits
`AES256-GCM-SHA384`, and these hosts offer nothing else — confirmed by
enumerating the default context (`AES256-GCM-SHA384 present: False`).

**The narrowest fix, and the one implemented:** take CPython's own default list
and append that single suite. Measured — **exactly one suite added, none
removed**, `SECLEVEL` untouched, `verify_mode=CERT_REQUIRED` and
`check_hostname=True` both intact, negotiated as `TLSv1.2 /
AES256-GCM-SHA384` with a verified `CN=solicitation.nasaprs.com`.

**What it costs, stated rather than glossed.** `AES256-GCM-SHA384` uses static
RSA key exchange (`kea=kx-rsa`), so traffic to an opted-in host has **no forward
secrecy** — which is precisely why CPython drops it. Acceptable for these hosts:
the request carries no secret, the response is a public solicitation table, and
the certificate is still verified so the peer is authenticated. **Not**
acceptable for any source carrying credentials, which is why the option is
per-adapter and off by default (§17.11).

So the recorded "NASA refuses the client" is a **client-side misdiagnosis**, and
§18.2's NSPIRES deferral should be re-read with that in mind. This does not by
itself reopen the deferral: NSPIRES's *open-solicitations list* is still
session-gated (`solicitations!init.do` returns a splash), which is what
`adapters/nspires.py` documents. What is now reachable is the ROSES table
surface, which is all P6.1 needs.

## 1. Stable discovery path — no year, no GUID, no amendment number

| Step | URL | Stability |
|---|---|---|
| 1 | `https://science.nasa.gov/researchers/sara/grant-solicitations/` | Stable SARA landing page, no year in the path |
| 2 | scrape `https://solicitation.nasaprs.com/ROSES(\d{4})table3` from it | **The current ROSES year is discovered, not hard-coded** |
| 3 | GET that short link | 302s to the versioned document |
| 4 | final URL | `…/Table%203%20ROSES-2025_Amend%2069.html` |

The SARA page currently says *"ROSES-26 will be released in July of 2026. Thus,
ROSES-25 will stay open through August 2026"* and links Tables 2 and 3 for the
authoritative year. **Nothing transient is hard-coded**: not the year, not
`solId`, not `cmdocumentid`, not the amendment number. The amendment number is
*read from* the resolved URL as a version signal.

## 2. The parse substrate — Table 3, with Table 2 for corroboration

| | Table 3 | Table 2 |
|---|---|---|
| Title | *SOLICITED RESEARCH PROGRAMS (In Order of Appendices A–F)* | same programs, **due-date order** |
| `<table>` | 1 | 1 |
| `<tr>` | 70 (1 header + **69** elements) | 71 (1 header + **70**) |
| Columns | `APPENDIX` · `PROGRAM` · `NOI or Step-1 Due Date [2]` · `(Step-2) Proposal Due Date` | identical |

**Table 3 is the substrate**, because appendix order *is* the hierarchy P6.1 is
meant to preserve. Table 2 carries the same element set in a different order and
is used **only for corroboration and health checking** — never parsed into
records.

That corroboration immediately earned its place: **Table 2 contains `A.7 Water
Quality Applications` and Table 3 does not.** A real inconsistency in NASA's own
published tables, found by comparing them.

## 3. Row semantics

**Column order:** appendix code, program title, NOI/Step-1 due date, Step-2 due
date. 53 rows carry 4 cells; **17 carry 3**, of which 16 use `colspan="2"` to
span a single status across both date columns and one (`C.5`) simply omits a
cell — a source irregularity the parser must tolerate rather than assume away.

**Every row carries a link.** Link kind is what distinguishes a container from
an element:

| Link kind | Count | Meaning |
|---|---|---|
| `summary.do?solId={GUID}` | 58 | the element's own NSPIRES page — **NASA's element identity** |
| `viewrepositorydocument?cmdocumentid=…` | 6 | **overview/container rows**, a PDF rather than a solicitation |
| `solicitation.nasaprs.com/<SOLNUM-CODE>` | 4 | short link, e.g. `NNH25ZDA001N-ATMOS` |
| `summary.do?solNum=…` | 2 | element page keyed by solicitation number |
| other | 1 | `science.nasa.gov/researchers/funding-for-events/` |

**Appendix codes are not a key.** 69 codes across six divisions — A 14, B 6,
C 13, D 14, E 3, F 19 — and they are **neither contiguous nor unique**: `A.7` is
absent, and **`D.3C` appears twice** (XRISM General Observer Type 1 and Type 2)
sharing a single `solId`. So neither the code nor the GUID is unique on its own;
identity must be `(appendix code, program title)`.

## 4. Native status vocabulary, as it actually appears

Every distinct value in the two date columns, counted:

| Value | Count | Meaning |
|---|---|---|
| `N/A` | 32 | no date in that column — on overview rows, both columns |
| `Not Solicited This Year` | 14 | element exists in the hierarchy, not offered this cycle |
| `TBD` | 4 | offered, date not yet set |
| `No Due Date [3]` / `[4]` / `[5]` | 3 | **rolling submission**; the footnote gives the real cutoff |
| `Not Solicited see C.2 and F.3` | 1 | not-solicited variant pointing elsewhere |
| `Follow link from title` | 1 | date lives on the element page |
| explicit dates | ~60 | with qualifiers `(Step-1)`, `(Step-2)`, `(Mandatory NOI)`, `(Phase-1 via ARK RPS)`, `(via NSPIRES)` |

**Date formatting is dirty and must be parsed tolerantly:** `12/03 /2025`,
`12/ 15 /2025`, `02/02 /2026`, `1/26/2026` all appear — stray spaces inside the
date and single-digit months.

**There is no explicit "closed" or "expired" status.** Closure is *derived* from
the date: 32 rows have their latest date before today, 9 on or after. The
adapter must do that derivation deterministically and must not invent a status
NASA does not publish.

**Overview/container rows are identifiable three independent ways** — a
`viewrepositorydocument` link, a title ending in "Overview", and `N/A` in both
date columns. Exactly six, one per division: `A.1`, `B.1`, `C.1`, `D.1`, `E.1`,
`F.1`. All three signals agree on all six.

## 5. Amendments

Two representations, at different granularities:

1. **Document level, reliable.** The resolved URL carries `Amend 69`. This is
   the version signal the adapter records.
2. **Row level, by styling.** Footnote [1]: *"Amended due dates and new program
   elements will be indicated with bold red text as ROSES-2025 is amended
   through the year."* Measured: `<font color="#ff0000">` appears 147 times
   across **46 rows**. It is machine-detectable, so the adapter records
   `amended: true` per row — but 46 of 69 rows are marked after 69 amendments,
   so it accumulates across the cycle and is **not** a "changed since last run"
   signal.

## 6. Consequences for the parser

- Enter through the SARA page; discover the year; never hard-code it.
- **Use the per-adapter compatible-cipher opt-in, not a security-level change.**
  `SECLEVEL` was **not** the blocker (§0, row 4: the normal security level
  works). CPython's curated TLS≤1.2 list omits `AES256-GCM-SHA384` and these
  hosts offer nothing else, so the implemented fix takes CPython's own default
  list and appends **that one suite** — nothing removed, `SECLEVEL` untouched,
  `verify_mode=CERT_REQUIRED` and `check_hostname=True` both intact. The
  behaviour is `PoliteClient(legacy_tls_ciphers=True)`, **opt-in per adapter and
  off by default**; do not broaden it to other adapters without independent
  evidence for each host (§17.11). Pinned by
  `tests/test_sources_http_tls.py` — one suite added, none removed, list derived
  from the live default context rather than hard-coded.
- Parse Table 3 only; fetch Table 2 for corroboration and health.
- Identity = `(appendix_code, program_title)`; carry `solId` when present.
- Preserve appendix order as given — do not sort.
- Map statuses from NASA's own strings; derive `closed` from dates only.
- Tolerate 3-cell rows, duplicate codes, missing codes and dirty dates.

---

# P6.1d — final yield

**Measured 2026-08-17 against the committed catalog, after the reachability
sweep.** Matching is on the **solicitation number** (`NNH\d{2}ZDA\d{3}N-<CODE>`),
which is exact, with normalised-title matching as a fallback. The earlier
checkpoint used titles alone and reported 9; **the corrected figure is 10.**
`D.8 Habitable Worlds Observatory` (`363325`) matches on solicitation number and
the title matcher had missed it.

## The counts

| | Count |
|---|---|
| Table 3 rows total | **69** |
| Overview / container rows (not program elements) | **6** |
| **Valid ROSES program elements** | **63** |
| Open / current under the derived-currentness rule | **12** |

Currentness is **derived, not native.** NASA publishes no closed status; the
adapter compares the published due date to the run date and labels the result
`derived_currentness`, kept in a separate field from `native_status` so a reader
can never mistake our inference for NASA's statement.

## The two populations, kept separate

### A. Relationship recovery — 10 elements

Ten of the 63 already exist as Funding Finder records. For these, P6.1 supplies
something the segmentation path cannot: **an authoritative parent→child
relationship, published by the awarding agency**, at the `native` rung.

| Appendix | Element | Catalog record | Matched by |
|---|---|---|---|
| A.4 | Earth Science Applications: Water Resources | `359996` | title |
| A.10 | Atmospheric Composition Modeling and Analysis | `360003` | solicitation number |
| A.13 | Carbon Cycle Science | `363224` | solicitation number |
| A.14 | Terrestrial Ecology | `363240` | title |
| A.15 | Ocean Biology and Biogeochemistry | `363241` | solicitation number |
| B.2 | Heliophysics Supporting Research | `361234` | title |
| C.2 | Emerging Worlds | `360004` | solicitation number |
| C.4 | Solar System Observations | `363258` | title |
| D.8 | Habitable Worlds Observatory | `363325` | solicitation number |
| F.17 | Support for Open Source Tools, Frameworks | `362495` | title |

**All 10 are open now.** And all 10 are records the project had previously
recorded as unreachable — the correspondence is exact, which is the practical
payoff of the TLS fix (§17.11).

**Five matched only by title.** That is worth recording as a caution rather than
a success: title matching is the weaker key, and a future ingestion decision
should not assume solicitation numbers are always present on both sides.

### The previously-category-(a) question, answered — the number is zero

P6's gate asks which of the recovered records were previously **category (a)**
(`docs/FAMILY_TAXONOMY.md` §1: *read, and no list of fundable subdivisions
exists*), because that is the number that says whether structured sources reach
the outward-pointing (a) population. **Verified against the classification
records 2026-08-18: none of the 10 were (a).**

| Evidence | Finding |
|---|---|
| `docs/FAMILY_TAXONOMY.md` §1 miss-cause table | **1 of the 10 is classified there at all** — `360003`, and it is **(e)** *unreachable fetch path*, not (a) |
| `docs/FAMILY_TAXONOMY.md` reachability tables | `360004` and `363241` appear as `nspires.nasaprs.com` SSL-EOF failures and as "no measurable document at all" — (e) in substance |
| `docs/CORPUS_CENSUS.md` fetch-failure list | **all 10** appear as `ConnectionReset` rows against NASA hosts — again (e), and this is the list the (e) judgement rests on |
| The 53-document miss-cause sample | The other 9 were never inside it, so they carried **no** category at all — which is why the answer is 0 rather than a small number |

**So P6.1 reached 0 previously-(a) records, and the (a) population remains
unmeasured by structured sources.** What P6.1 reached is the **(e)** population —
records whose bytes never arrived — which is exactly what the TLS
misdiagnosis had created. That is a real result and a *different* result from the
one the gate was written to look for: §6.7·0's claim that structured sources
*may* reach part of the 62% (a) population is still **untested**, and **P6.2** is the
next chance to test it. Recorded here so no later session reads "10 recoveries"
as evidence about (a).

### B. Potential catalog expansion — 53 elements, measured only

> **Superseded by P8 (2026-08-19) for the emission half, and still correct for the
> measurement.** The 53 remain the unmatched inventory; what changed is that the
> **2 actionable** ones are now emitted as catalog records and the rest are
> re-evaluated every refresh (§18.1 P8). The paragraph below describes P6.1's
> deliberate boundary, which P8 was chartered to remove.

Fifty-three program elements have no catalog record. They are **counted, and not
emitted.** `parse()` returns nothing, so this population cannot reach
`opportunities.js` structurally rather than by convention, and the adapter ships
`enabled = False` on top of that.

**Only 2 of the 53 are open.** The other 51 are `Not Solicited This Year`, TBD,
or past their date. The headline number overstates the live opportunity by
roughly 25×, and that asymmetry is what DEC-13 was decided on.

> **DEC-13 is TAKEN (2026-08-18): build it, as
> **P8** — NASA ROSES Catalog Source (§18.1), immediately after P6.1 and
> before P6.2.** The conclusion is **not** "add 53 records". It is that the
> complete program-element inventory is **re-evaluated automatically on every
> scheduled catalog refresh**: an unmatched element enters the catalog when it
> becomes current/actionable and stays out of the public current catalog while
> inactive. The 53 are therefore a **maintained candidate inventory**, not a
> backlog awaiting a human. Today that makes **2** of them candidates for
> inclusion; if any of the other 51 is solicited in a later amendment or cycle,
> the scheduled refresh finds it without anyone remembering to look.
>
> ~~**Known gap until P8 ships:** those **2 currently open unmatched elements** are
> NASA solicitations that Funding Finder does not list.~~ **Closed 2026-08-19: P8
> shipped.** Both are emitted — `D.3E` IXPE Cycle 4 / NICER Cycle 9 General
> Observer and `D.9` Habitable Worlds Observatory Instrument Concept Assessments —
> and all 63 elements are re-decided on every scheduled refresh, so the other 51
> need no human follow-up. Net **+2 records, 1,475 → 1,477**.

## What this is not

**B is not subtopic recall, and the two must not be added together.** §1.1's
~171 records / 11.6% counts *catalog records that gain subtopic children*.
Population B is *catalog records that do not exist yet* — a sourcing question
about which opportunities the project lists at all. Combining them would count a
sourcing gain as a segmentation gain.

**§1.1 is unchanged by P6.1.** Population A recovers relationships for 10 records
that were already inside the survey's denominator as non-hits; converting them
from "unreadable" to "native children" is a provenance and quality improvement,
not a change to any stratum rate, interval or denominator. If it moves §1.1 at
all it does so through 10 records out of 1,472, which is inside the noise of a
54–538 band.

## Scope actually held

- Adapter `enabled = False`, so `opportunities.js` is byte-identical.
  **Re-verified 2026-08-18 three ways**, because the gate script was red that day
  for a reason that has nothing to do with P6.1 (see the BUG-7 note below): (i) 18 of
  20 artifacts matched the baseline unchanged, (ii) the two that differed produced
  **byte-identical** hashes on the pre-P6.1 tree at `7cece6b`, and (iii) pinning the
  build's UTC date to the baseline's freeze date reproduced **all 20** committed
  fingerprints exactly. **With BUG-7 fixed, `tools/verify_no_drift.sh` exits 0
  directly — 22 artifacts unchanged, baseline never re-frozen.**
- The 53 standalone elements were **not** emitted *(P6.1's boundary; P8 now emits the actionable subset — 2 today)*.
- No cache committed.
- P6.2 and P6.3 not started.
- No pattern family added or resurrected; `roses_element` stays retired, and
  the adapter never calls `segment_document` — proven by a test that patches it
  and asserts zero calls.

## BUG-7 — the no-drift gate was date-dependent, and P6.1 is not the cause

**Diagnosed 2026-08-18 while closing P6.1's §0.5 clause.** `tools/verify_no_drift.sh`
fails on a clean tree with exactly two artifacts differing — `feeds/changes.json`
and `feeds/changes.xml` — and it fails the same way at the pre-P6.1 commit.

| Step | Result |
|---|---|
| Drift gate on `topic-layer` (`c64576e`) | exit **1**, `feeds/changes.json` + `feeds/changes.xml` differ |
| Same gate in a worktree at `7cece6b` (pre-P6.1) | exit **1**, **the same two hashes**, `4e21a05f…` / `9795c888…` |
| Normalized text diff, restamped build vs today's build | **only two lines differ** — two event `id` values |
| Rebuild with the catalog's `generated_at` date pinned to the baseline's UTC freeze date (`2026-08-17`) | all 20 fingerprints match the committed baseline **exactly**, including `0f2f6160…` / `605b38c8…` |

**Cause.** `scripts/build_changes.py::_event_id` seeds its SHA-1 with
`changed_at[:10]` — the build's **UTC calendar date** — so every event id changes
at midnight UTC. `tools/fingerprint.py` normalizes the ISO-8601 timestamp
literals and the one named date-only field, but it cannot un-hash an id that a
date was baked into. Commit `fc844e6` ("Make the no-drift gate stable across a
UTC date rollover") fixed `source_first_seen_date`; **this is a second rollover
axis on the same day boundary that the fix did not reach.**

**This is a gate-tooling defect, not a production defect and not a drift.** The
nightly is supposed to emit a new event id for a new day. What is broken is the
gate's hermeticity: it can only be green on the day its baseline was frozen.

**Fixed 2026-08-18 (BUG-7, full record in `docs/TOPIC_LAYER_PLAN.md` §8.4).**
`tools/hermetic_build.sh` now writes a `.work/` copy of the catalog with
`generated_at` pinned and hands that to `build_changes`, so `changed_at` and every
event id are deterministic. Production semantics are unchanged, no `scripts/` file
was touched, the event ids are still **not** normalized in `fingerprint.py` — an
opaque content hash must stay opaque — and the pin is the baseline's own UTC
freeze date, so **no re-freeze was needed**: `tools/verify_no_drift.sh` returns
**exit 0, 22 artifacts unchanged**. P8's gate can now tell an intentional
catalog change from manufactured drift.
