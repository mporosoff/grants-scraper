# PDF API notes — measured, not inferred

§17.2 flagged the `pdfplumber` and `pypdf` sketches in §6.1–§6.2 of
`TOPIC_LAYER_PLAN.md` as **claims, not facts**: they were written from library
knowledge rather than from output pasted from this repository. This document
runs them.

Everything below is output from three real notice PDFs, fetched through the
same Grants.gov attachment URLs `extract_document_evidence.py` already uses.
Nothing here is inferred.

| Field | Value |
|---|---|
| Date | 2026-08-16 |
| `pypdf` | 6.16.1 |
| `pdfplumber` | 0.11.10 |
| `pdfminer.six` | 20260107 |
| Platform | Windows 11, Python 3.13.12 |

## The three documents

Selected from entries already in `data/document_evidence.json`, one per case
the plan distinguishes.

| Role | Document | Opportunity | Pages | Bytes | Outline destinations |
|---|---|---|---|---|---|
| **With bookmarks** | `SCALEUP Ready FA NOFO.pdf` (ARPA-E) | `356623` / `DE-FOA-0003467` | 65 | 880,411 | **119**, nested |
| **Without bookmarks** | `FA955026S0001 AFOSR Open BAA.pdf` | `362681` | 102 | 1,145,031 | **0** |
| **DoD BAA** | `N0001425SB001.pdf` (ONR Long Range BAA) | `356605` | 74 | 810,412 | **0** |

Three further documents were fetched to check that the findings are not
artifacts of one file: `cdc-rfa-jg-26-0054.pdf` (146 destinations),
`hud-CPD-2600-DC-0098.pdf` (82), and `W81XWH-22-DHAPP.pdf` (11 destinations,
**flat — no nesting at all**, a useful contrast).

The ONR LRBAA is named in §6.3's development corpus, so it is the intended
Layer C target rather than an arbitrary pick.

---

## 1. `reader.outline` — the plan is right

```
type(reader.outline)      : list
len(reader.outline)       : 18

  [ 0] Destination  'Basic Information'
  [ 1] Destination  'I. Funding Opportunity Description'
  [ 2] list
  [ 3] Destination  'II. Eligibility Information'
  [ 4] list
  ...
  index 2 is a list of 10 items; index 1 is Destination 'I. Funding Opportunity Description'
   -> the list holds the CHILDREN of the entry that PRECEDED it
```

**Confirmed.** `reader.outline` is a nested `list`; a nested `list` holds the
children of the `Destination` immediately preceding it, and nesting depth is
the heading level. §6.2's `_flatten_outline` walks this correctly.

Also confirmed: **a PDF with no bookmarks returns an empty list, not an error**
(both DoD BAAs return `[]`). That is a normal outcome, not a failure.

Not all outlines nest: `W81XWH-22-DHAPP.pdf` has 11 top-level destinations and
11 total, so `_flatten_outline` yields every entry at `level == 0`. Layer A's
per-level loop handles this, but a document whose only level is 0 gives
`best_family` exactly one shot rather than several.

`Destination` in `pypdf` 6.x is a `DictionaryObject` subclass. It exposes
`.title`, `.page`, `.typ` (e.g. `'/XYZ'`), `.children`, `.has_children` — but
**not** a `.level`. Depth must come from the walk, as the sketch does.

## 2. `get_destination_page_number` — the plan is wrong

§6.2 states:

> `get_destination_page_number` **raises** on destinations that point outside
> the document, so it needs the guard

**It does not raise. It returns `None`.**

```
signature: (self, destination: Destination) -> Optional[int]
docstring: "The page number or None if page is not found"
```

Measured against deliberately malformed destinations:

| Destination page | Result |
|---|---|
| `NullObject()` | **`None`** |
| `NumberObject(9999)` (out of range) | **`None`** |
| `NumberObject(3)` (in range!) | **`None`** |
| page object from a *different* document | **`7`** — a plausible, wrong answer |
| `None` | `ValueError` at *construction*, not lookup |

Across all 358 real destinations in the six sampled PDFs: **zero raised, zero
returned `None`.** The error path is genuinely rare in practice, which is
exactly why it was never noticed.

### Why the sketch works anyway, and why that is not good enough

```python
try:
    page = reader.get_destination_page_number(item) + 1   # 1-based
except Exception:                    # broken/external destination
    continue
```

When the API returns `None`, `None + 1` raises `TypeError`, which the bare
`except Exception` catches. **The sketch is correct by accident**, via an
arithmetic error on the next token, not because the API raised. The comment
explains a mechanism that does not exist. Written explicitly:

```python
page_index = reader.get_destination_page_number(item)
if page_index is None:            # not found; pypdf returns None, it does not raise
    continue
page = page_index + 1             # pypdf is 0-based; this repository is 1-based
```

### Two hazards the plan does not mention

**A bare-integer destination is silently dropped.** `NumberObject(3)` returns
`None` even though page 3 exists — `get_destination_page_number` resolves
indirect references and does not treat a literal integer as a page index. A
notice writing `/Dest [3 /Fit]` loses that outline entry with no error. None of
the six sampled documents do this, but Layer A will under-report rather than
fail if one does.

**A cross-document page reference returns a wrong page number, silently.**
Handing it a page from another `PdfReader` returned `7` — it matches on object
number without checking the object belongs to this document. Layer A cannot
reach this, because its destinations always come from the same reader it
queries. It is recorded as a trap for anyone who later constructs `Destination`
objects by hand.

## 3. `page.chars` fontnames — the plan is right about bold, wrong about size

`page.chars` yields one dict per character with these keys:

```
['adv', 'bottom', 'doctop', 'fontname', 'height', 'matrix', 'mcid', 'ncs',
 'non_stroking_color', 'object_type', 'page_number', 'size', 'stroking_color',
 'tag', 'text', 'top', 'upright', 'width', 'x0', 'x1', 'y0', 'y1']
```

`fontname` and `size` are both present, as §6.1's table claims.
`page.flush_cache()` exists on `pdfplumber.page.Page` in 0.11.10.

### Real `fontname` values

First 40 pages of each document:

**ONR LRBAA** — 88,780 chars, median size 12.00, 13 distinct sizes
```
            TimesNewRomanPSMT                       81,663 (92.0%)
BOLD-MATCH  TimesNewRomanPS-BoldMT                   3,963 ( 4.5%)
            TimesNewRomanPS-ItalicMT                 2,463 ( 2.8%)
BOLD-MATCH  TimesNewRomanPS-BoldItalicMT               305 ( 0.3%)
BOLD-MATCH  Arial-BoldMT                                27 ( 0.0%)
```

**AFOSR Open BAA** — 112,628 chars, median size 12.00, **3 distinct sizes**
```
            BCDEEE+TimesNewRomanPSMT               100,831 (89.5%)
BOLD-MATCH  BCDFEE+TimesNewRomanPS-BoldMT            8,802 ( 7.8%)
            BCDHEE+TimesNewRomanPSMT                 2,025 ( 1.8%)
BOLD-MATCH  BCDIEE+TimesNewRomanPS-BoldMT              180 ( 0.2%)
BOLD-MATCH  BCDGEE+Arial-BoldMT                         69 ( 0.1%)
```

**ARPA-E SCALEUP** — 118,658 chars, median size 12.00, 11 distinct sizes
```
            FTLUFY+Calibri                          84,915 (71.6%)
            MIDUZK+Calibri-Italic                   20,736 (17.5%)
BOLD-MATCH  HGOLHU+Calibri-Bold                     10,160 ( 8.6%)
BOLD-MATCH  LXJELM+Calibri-BoldItalic                2,567 ( 2.2%)
```

**`BOLD_RE = re.compile(r'bold|black|heavy|semibold|demi', re.I)` works.** It
matches every bold face present, including the six-letter subset prefixes
(`BCDFEE+`, `HGOLHU+`) that §6.1 predicted. §6.1's claim that the font name
carries the weight is correct, and the three example forms it gives
(`ABCDEF+Arial-BoldMT`, `TimesNewRomanPS-BoldMT`, `Calibri,Bold`) are the right
shape — though `Calibri,Bold` with a comma did not appear; the real ARPA-E form
is `Calibri-Bold` with a hyphen. Both match the regex.

Two wrinkles worth knowing:

- **`BOLD_RE` also matches bold-italic** (`TimesNewRomanPS-BoldItalicMT`,
  `Calibri-BoldItalic`). Correct for heading detection — bold italic is still
  bold — but it means "bold" is not "bold and not italic".
- **Subset prefixes are not stable within a document.** The same logical face
  appears as both `BCDEEE+TimesNewRomanPSMT` and `BCDHEE+TimesNewRomanPSMT`,
  and as both `BCDFEE+...BoldMT` and `BCDIEE+...BoldMT`. Any logic that counts
  distinct fonts must strip the `^[A-Z]{6}\+` prefix first. Nothing in §6.2
  does this, and nothing in §6.2 needs to — but a future "the heading face is
  the second-most-common font" heuristic would be wrong without it.

### The size test does almost nothing

§6.2's candidate rule is `size >= 1.15 * median or bold`. Measured over the
first 60 pages, by branch:

| Document | Lines | `size >= 1.15 × median` | `bold` | Either |
|---|---|---|---|---|
| ONR LRBAA | 2,315 | **4 (0.2%)** | 134 (5.8%) | 135 (5.8%) |
| AFOSR Open BAA | 2,434 | **0 (0.0%)** | 145 (6.0%) | 145 (6.0%) |
| ARPA-E SCALEUP | 2,849 | 120 (4.2%) | 545 (19.1%) | 545 (19.1%) |

**On both DoD BAAs the size branch contributes nothing.** AFOSR has three
distinct sizes in the entire document and its headings are set at body size in
bold. On the ARPA-E NOFO every size-qualifying line is also bold, so the union
equals the bold set in all three documents.

Layer C is therefore, on this evidence, **a bold-detection layer**. The size
term is not wrong and costs nothing, but §6.2's framing — that the typographic
signal is size *or* weight — overstates what size delivers on exactly the
corpus Layer C exists to serve. Keep it for the documents that do use display
type; do not rely on it.

Bold on its own also **over-admits**. Real AFOSR candidate lines include:

```
p1  size=12.00 bold=True 'Hyperlinks have been embedded within this document and appear as underline'
p1  size=12.00 bold=True 'this document by "clicking" (CTRL + CLICK, or CLICK).'
```

Those are bolded body prose, not headings. The §6.4 acceptance rules, not the
candidate test, are what keep Layer C honest.

### Cost

60 pages take **5.8–6.9 s** wall-clock with `flush_cache()` per page. Scaling
to `SUBTOPIC_CHAR_SCAN_PAGES = 120` gives roughly **12–14 s** against a
`SUBTOPIC_TIME_BUDGET_SECONDS = 20` per-document budget — under it, but with
about 1.5× margin, not 10×. On a slower runner a 120-page document can plausibly
exhaust the budget. That is a designed, non-fatal outcome (`time_budget`), but
it means Layer C will time out on the largest documents sometimes, and
`time_budget` counts in the §18.1 package D histogram should be read with that
in mind rather than treated as evidence of pathology.

## 4. The finding nobody asked for: the families match nothing

Running all ten §6.3 families over the full text of all three documents:

**Zero matches. In any of them. Not one family, not one hit.**

What the documents actually contain is administrative NOFO section structure:

| Document | Roman `I.` | Letter `A.` | Decimal `1.` |
|---|---|---|---|
| ONR LRBAA | 1 | 15 | 47 |
| AFOSR Open BAA | 2 | 4 | 19 |
| ARPA-E SCALEUP | 14 | 41 | 74 |

```
'A. Overview of the Research Opportunity'      'I. OVERVIEW INFORMATION'
'B. Basic Information'                         'II. BASIC INFORMATION'
'1. Federal Agency Name'                       'A. PROGRAM DESCRIPTION'
'2. Funding Opportunity Title'                 'D. TECHNICAL CATEGORIES OF INTEREST'
```

Two conclusions, and they point in opposite directions:

**This is correct behavior.** All three notices genuinely contain no enumerated
topic list, so segmentation returns zero subtopics and leaves the parent
untouched. That is §18.3's fail-closed asymmetry working as designed. The ONR
Long Range BAA is structurally the *same shape* as the DOE BES omnibus in
§6.7 — an umbrella that points outward to research areas rather than
enumerating them. §6.7 identifies that shape only for DOE; it is at least as
common in DoD long-range BAAs, and §6.2's claim that "most DoD BAAs ... resolve
here [Layer C]" is not supported by either DoD BAA sampled.

**And it is a warning about loosening.** The obvious reaction — "add a generic
numbered-section family so these documents produce something" — would
manufacture subtopics titled *Federal Agency Name*, *Funding Opportunity
Title*, and *Announcement Type* from 47 and 74 matching lines respectively.
That is precisely the failure §18.3 calls "the single most damaging change
anyone could make to this design." The families are narrow on purpose. Three
documents producing zero subtopics is the system working, not a coverage bug to
be fixed by relaxing acceptance.

What it does mean is that the §18.1 package D acceptance-rate expectation
should be set from measurement, not hope, and that `no_layer_accepted` will
dominate the histogram for the BAA corpus. §18.1 package D already requires
`no_layer_accepted` to be reported separately from genuine failures, which is
the right instrument; this note is evidence for why that separation matters.

---

## What changed in the plan as a result

| § | Was | Now |
|---|---|---|
| §6.2 Layer A | "`get_destination_page_number` **raises**" | Returns `None`; explicit `is None` check, and the two silent-drop hazards recorded |
| §6.2 Layer C | candidate rule framed as size-or-weight | Weight carries it; size contributes 0–0.2% on DoD BAAs. Kept, not relied on |
| §6.2 Layer C | "Most DoD BAAs ... resolve here" | Unsupported by both DoD BAAs sampled; both are outward-pointing umbrellas that correctly yield zero |
| §6.1 cost | "materially slower" | Quantified: ~12–14 s for 120 pages against a 20 s budget |
| §6.1 fontnames | `Calibri,Bold` given as an example form | Real form is `Calibri-Bold`; subset prefixes are unstable within a document |

## Reproducing

The probe scripts are not committed — they are one-shot instruments against
documents this repository already fetches nightly, and committing them would
add a network-dependent path to a repository whose test suite has none. To
re-run: fetch the three attachment URLs above, then walk `reader.outline`,
call `get_destination_page_number` on each `Destination`, and count
`page.chars` `fontname` values. Every number in this document came from that.
