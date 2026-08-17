# ROSES structured-source inspection — S1a

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
surface, which is all S1 needs.

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

**Table 3 is the substrate**, because appendix order *is* the hierarchy S1 is
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
- Use a `SECLEVEL=1` HTTPS adapter with verification intact.
- Parse Table 3 only; fetch Table 2 for corroboration and health.
- Identity = `(appendix_code, program_title)`; carry `solId` when present.
- Preserve appendix order as given — do not sort.
- Map statuses from NASA's own strings; derive `closed` from dates only.
- Tolerate 3-cell rows, duplicate codes, missing codes and dirty dates.
