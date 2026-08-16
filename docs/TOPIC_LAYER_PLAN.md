# Topic Layer Implementation Plan

**Deterministic subtopic extraction for umbrella solicitations**
Repository: `mporosoff/grants-scraper` (Funding Finder)
Status: proposal · Version 6.2 · Written 2026-08-15

---

## ⚠ Naming collision — read before writing any code

This repository **already uses the word "topic"** to mean *subject area*: `feeds/topic/catalysis-and-reaction-engineering.xml`, `feeds/topic/carbon-management.xml`, and roughly two dozen more, backed by `scripts/program_areas.py`.

This document uses "topic" throughout to mean something entirely different — a **fundable subdivision of an umbrella solicitation**, like Topic Area 3 of a DOE FOA or Topic 7 of a MURI BAA.

**Resolution: in code, the new concept is called `subtopic`.** Everywhere this document says `topic_id`, `topic_terms`, `topic_records.json`, `record_type: "topic"`, `extract_topics.py`, `--enable-topics`, `FF_TOPICS_ENABLED`, and so on, the identifier written into the repository must be `subtopic_id`, `subtopic_terms`, `data/subtopic_records.json`, `record_type: "subtopic"`, `scripts/extract_subtopics.py`, `--enable-subtopics`, `FF_SUBTOPICS_ENABLED`.

The existing subject-area meaning of "topic" is untouched. Do not rename anything that already exists.

Prose in this document still reads "topic" for readability. The rule applies to **identifiers, filenames, flags, and user-facing labels**, and it is not optional — a codebase with two meanings of "topic" will produce wrong wiring.

## How to use this document

**Do not read this front to back and start typing.** It is a reference, not a tutorial. Read in this order:

| When | Read | Why |
|---|---|---|
| Before anything | §0 **in full**, §14 glossary | §0 is a gate. §14 defines vocabulary used everywhere else. |
| Deciding whether to proceed | §1–§4 | Problem, scope, and the constraints you cannot violate |
| Starting Phase 1 | §8, §9, then §10 Phase 1, then §15 checklist | Discipline and Actions safety **before** the step list |
| Starting Phase 2 | §5, §6 in full | Data model and segmentation. This is the densest material in the document. |
| Starting Phase 3 | §7 in full | Every integration point |
| Stuck or unsure where you are | §15 checklist, then §12 risk register | The checklist is the single source of truth for progress |

**If you only remember three things:** §0.5 (flag off means byte-identical output), §8.1 (additive only, never rewrite), §9.3 (new steps exit 0 on benign outcomes).

**Sections you can skip on a first pass:** §11 (deferred, not being built), §13 (open decisions, resolved separately).

---

## 0. STOP — read this before touching anything

> **This plan is additive. It is not a rewrite.** Every existing file in this repository works today and is generating a live, published catalog on a daily schedule. Nothing in this document authorizes replacing, reformatting, or restructuring an existing file. If you find yourself writing a new version of a file that already exists, you have misread the plan.

### 0.1 The reconnaissance requirement

**Do not edit a single line until you can answer all eleven questions below from your own reading of the tree.** Not from this document — from the code. This plan describes intent; the repository is the truth, and it may have moved since this was written.

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
11. There are at least three workflow files — `.github/workflows/refresh-opportunities.yml`, `.github/workflows/tests.yml`, and `docs/weekly-alerts/weekly-digest.yml`. Which are active, which is the nightly build, and do any share state?

### 0.2 Commands to answer them

```bash
git clone https://github.com/mporosoff/grants-scraper && cd grants-scraper
git checkout -b topic-layer            # never work on the deploy branch

# Size and shape of the tree
find . -name '*.py' -not -path './.git/*' | xargs wc -l | sort -n

# Read every line of the workflow. All of it. Twice.
cat .github/workflows/*.yml

# Which script writes which artifact
grep -rn "open(" scripts/ | grep -oE "data/[a-z_]+\.(json|js)" | sort | uniq -c

# What actually gets committed back
grep -rn -A5 "git add" .github/workflows/

# Every nonzero-exit path (these drive the issue automation)
grep -rn "sys.exit\|SystemExit\|raise .*Error" scripts/ | grep -v test

# Internal import graph — what depends on what
grep -rn "^from \|^import " scripts/ | grep -v "^\S*:import \(os\|sys\|re\|json\|csv\|time\|hashlib\|argparse\)"

# Confirm the browser's expected schema
head -c 2000 data/opportunities.js
grep -rn "opportunities\|record_type\|schema" assets/app.js | head -40
```

### 0.3 Hard rules

- **Do not edit and execute in the same sitting on your first pass.** Read the tree, write notes, stop. Edit the following day.
- **Work on a branch.** Never push to the branch GitHub Pages deploys from until the Phase 3 exit criteria are met.
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
5. **Never implement more than one numbered step per session.** Complete it, verify it, commit it, stop.
6. **Never "improve" adjacent code** you notice while editing. Note it in your report and move on.
7. **Never add a dependency** not named in this plan without stopping to ask.
8. **Never change a default value or CLI default to make something work.** Defaults are load-bearing (§8.1); the nightly workflow invokes these scripts with fixed arguments.
9. **Never enable a feature flag.** Only step 34 does that, and only after a human reviews the Phase 3 gate.
10. **Never infer an API's response shape.** Fetch one real response, print it, read it, then write code against what you observed. This applies to SAM.gov, OpenAlex, Grants.gov `fetchOpportunity`, and every scraped page.

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

**When blocked, stop and ask.** Do not improvise around a missing credential, an ambiguous schema, a failing gate, or an unexpected API response. An improvised workaround here publishes to a live site that faculty use to make funding decisions.

### 0.5 The golden rule

> **With `--enable-topics` off, every generated artifact must be byte-identical to what the current code produces from the same inputs.**

This is not an aspiration; it is a CI gate, defined in §8.4. If the flag is off and any output differs, the change is wrong regardless of how good it looks.

---

## 1. Problem

Funding Finder's unit of record is the **opportunity**: one number, one synopsis, one deadline, one set of filter fields. For a Broad Agency Announcement, an omnibus NRA, or a multi-topic DOE FOA, the *fundable* unit is the **topic**, and topic text lives inside the attached notice PDF.

- A DoD MURI BAA enters the catalog as one record. Its ~20 research topics, each written by a different program officer, are invisible to BM25.
- An ARPA-E or EERE FOA with four Topic Areas is scored on its cover-page abstract, not on the technical content that determines relevance.
- NASA ROSES program elements carry boilerplate synopses pointing at NSPIRES, so all elements look identical lexically.
- `document_evidence.json` extracts **administrative** facts (page limits, cost share, submission stages). That scope is correct and unchanged; it simply leaves this gap unfilled.

No retrieval tuning fixes this. The discriminating text is not in any indexed field.

## 2. Scope

**In scope:** deterministic segmentation of already-fetched notices into topic spans; a topic record type stored, indexed, filtered, fed and rated through the existing pipeline; topic-level change events; coverage adapters for the two largest blind spots; evaluation extension with an auto-derived gold set.

**Out of scope for v1:** any LLM call in the scheduled workflow (see §11); any change to structured Grants.gov fields used by filters or sorting; committing raw notices or full extracted text.

**Non-goals:** replacing `extract_document_evidence.py` (topics are a *second consumer* of the same fetched bytes); a hand-curated umbrella registry (see §3).

## 3. Why there is no registry

The detector and the segmenter are the same code. You do not need external knowledge that a document is an umbrella — its structure reveals it. Three or more sibling headings matching a topic pattern family, with monotonic numbering, means it is an umbrella, and the same pass has already produced the child spans.

So: no list to maintain, new programs detected on first fetch, unfamiliar formats degrade to zero topics rather than going stale.

**One narrow exception, and it is not curation.** `data/expected_solicitations.json` (~10 lines) exists solely for regression detection, because "source returns plausible but incomplete results" is the one failure the existing health gates cannot catch. Details in §7.4.

## 4. Inherited constraints

| Constraint | Implication |
|---|---|
| Raw notices and full extracted text never committed | Topic full text is ephemeral. Only a bounded summary plus a term-frequency map is persisted (§5.2). |
| Machine-extracted dates/amounts never replace structured filter fields | Topic deadlines are advisory display facts unless the parent has no structured deadline. |
| Only short cited facts published, each with an anchor | Every topic carries `page_start`/`page_end` resolving to the exact PDF page. |
| Sources fail closed or retain filtered last-known-good; degradation opens a GitHub issue | Segmentation failure degrades to "parent unchanged," never to a partial catalog. |
| Ordinary search makes zero AI calls | Unchanged. Topic retrieval is pure BM25. |
| Document fetches bounded per run (`--max-documents`) | Segmentation adds **no** fetches. It reuses bytes already in hand. |
| Repository state is committed to git each build | Output must be diff-stable (§5.4) or the repo grows without bound. |

## 5. Data model

### 5.1 Topic record

```json
{
  "record_type": "topic",
  "topic_id": "DE-FOA-0003646:ta-2",
  "parent_id": "<catalog record id>",
  "parent_opportunity_number": "DE-FOA-0003646",
  "topic_code": "Topic Area 2",
  "topic_code_norm": "ta-2",
  "topic_ordinal": 2,
  "title": "Electrochemical Conversion of Captured CO2",
  "title_fingerprint": "3f9a1c02",
  "summary": "<= 600 chars, sentence-boundary truncated",
  "topic_terms": {"electrocataly": 14, "co2": 22, "faradaic": 6},
  "term_display": {"electrocataly": "electrocatalysis", "faradaic": "Faradaic"},
  "topic_source": "inline",
  "recurrence_group": "muri:interfacial-charge-transfer",
  "status": "open",
  "program_area_tags": ["catalysis", "co2_utilization"],
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
  "extractor_version": "1.0.0+pymupdf1.24.9"
}
```

### 5.2 Full text without storing full text

Indexing only a 600-character summary discards most of the retrieval gain. Committing the span violates the privacy boundary. Resolution: **persist the BM25 posting data, not the prose.**

```python
# scripts/extract_topics.py
from collections import Counter
from build_catalog import tokenize, stem, STOPWORDS   # reuse existing index code

def build_term_map(span_text: str, max_terms: int = 400) -> dict[str, int]:
    """Stemmed term frequencies. Supports full-strength BM25;
    not reconstructable into readable prose. Capped to bound file size."""
    stems = [
        stem(t) for t in tokenize(span_text)
        if len(t) >= 3 and t.lower() not in STOPWORDS
    ]
    return dict(Counter(stems).most_common(max_terms))
```

The span itself is discarded when the process exits. This mirrors what `build_catalog.py` already publishes for opportunity records, so the boundary holds without a new policy.

### 5.3 Stable identity across amendments

**This is the subtle one.** If `topic_id` keys on ordinal, an amendment that *inserts* Topic 3 renumbers everything below it, and the diff reports one addition plus seventeen spurious amendments.

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

def match_topics(old: list[dict], new: list[dict]) -> list[tuple]:
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
                    if o['topic_code_norm'] == n['topic_code_norm']), None)
        if hit:
            pairs.append((hit, n)); rem_old.remove(hit); rem_new.remove(n)

    pairs += [(o, None) for o in rem_old]     # removed
    pairs += [(None, n) for n in rem_new]     # added
    return pairs
```

`topic_id` is assigned once at first sight and **carried forward through matching**, so identity survives renumbering, retitling and repagination.

### 5.4 Diff stability

`data/topic_records.json` is committed every build. Unstable serialization would balloon the repository.

```python
json.dump(payload, f, sort_keys=True, indent=1, ensure_ascii=False)
f.write("\n")
```

Records sorted by `(parent_opportunity_number, topic_ordinal)`. Volatile fields such as `last_verified` are updated **only when something else changed** — otherwise the timestamp alone rewrites the file daily.

### 5.5 Field inheritance

| Field | Source |
|---|---|
| agency, sub-agency, instrument, eligibility, applicant type | inherited from parent, never re-derived |
| award floor / ceiling / total funding | inherited from parent |
| deadline used for filtering and sorting | **parent's structured deadline** |
| `own_deadline` | advisory display only; set only if one unambiguous date occurs in the span and does not contradict the parent |
| status | derived per §7.2 |

## 6. Deterministic segmentation

### 6.1 Shared fetch layer

Factored out of `extract_document_evidence.py` so topics add zero network traffic.

```python
# scripts/document_fetch.py
@dataclass(frozen=True)
class FetchedDocument:
    url: str
    content_type: str
    sha256: str
    etag: str | None
    last_modified: str | None
    fetched_at: str
    page_texts: list[str]          # ephemeral; index 0 == page 1
    page_spans: list[list[dict]]   # per-page spans w/ size + flags, for typography
    outline: list[tuple[int, str, int]]   # (level, title, page)
    tool_versions: dict            # {"pymupdf": "1.24.9"}

class Unchanged(NamedTuple):
    sha256: str
    reason: str                    # "etag" | "last_modified" | "hash"

def fetch_document(url, *, prior_hash=None, prior_etag=None,
                   prior_last_modified=None, timeout=30
                   ) -> FetchedDocument | Unchanged:
    """Change-detection ladder, cheapest first:
       1. If-None-Match / If-Modified-Since -> 304 -> Unchanged("etag")
       2. SHA-256 of bytes == prior_hash          -> Unchanged("hash")
       3. Otherwise parse and return the full document.
    """
```

**Determinism note:** pin `pymupdf` exactly in `requirements.txt`. A minor version bump can shift text extraction, changing spans and hashes, which surfaces as a flood of phantom `topic_amended` events. `tool_versions` is embedded in `extractor_version` so a version change is visible as the cause.

### 6.2 Four layers, first success wins

```python
# scripts/topic_segmentation.py
LAYERS = (_layer_outline, _layer_toc, _layer_headings, _layer_numbered)

def segment(doc: FetchedDocument) -> SegmentationResult:
    if not any(t.strip() for t in doc.page_texts):
        return SegmentationResult.empty("no_extractable_text")   # scanned; no OCR in v1
    for layer in LAYERS:
        result = layer(doc)
        if result and accepts(result):
            return result
    return SegmentationResult.empty("no_layer_accepted")
```

**Layer A — outline tree** (`confidence: high`). Most DOE, ARPA-E and NSF notices carry bookmarks and resolve here.

```python
def _layer_outline(doc):
    for level in sorted({lvl for lvl, _, _ in doc.outline}):
        sibs = [(t, p) for lvl, t, p in doc.outline if lvl == level]
        fam, hits = best_family(t for t, _ in sibs)
        if fam and len(hits) >= 3:
            return build_spans(doc, hits, method="outline", confidence="high")
    return None
```

**Layer B — table of contents** (`high`). Find TOC pages, then locate each title verbatim in the body; the TOC's own page number is never trusted as a boundary.

```python
DOT_LEADER = re.compile(r'^(?P<title>.+?)\.{3,}\s*(?P<page>\d+)\s*$')
# scan first max(3, 15% of pages); require >= 5 matching lines on a single page
```

**Layer C — body heading sweep** (`medium`). Most DoD BAAs are produced without bookmarks and resolve here.

```python
def _layer_headings(doc):
    sizes = [s['size'] for pg in doc.page_spans for s in pg]
    median = statistics.median(sizes)
    cands = [
        s for pg in doc.page_spans for s in pg
        if (s['size'] >= 1.15 * median or s['flags'] & (1 << 4))  # bold bit
        and len(s['text']) <= 200
    ]
    fam, hits = best_family(s['text'] for s in cands)
    if fam and len(hits) >= 3:
        return build_spans(doc, hits, method="heading_regex", confidence="medium")
    return None
```

**Layer D — plain numbered fallback** (`low`). Regex only, no typographic signal. **Low confidence never publishes** — it routes to the review queue.

### 6.3 Pattern families

`scripts/topic_patterns.py`. Each family: id, regex with an ordinal capture group, expected agencies.

| Family | Pattern (illustrative) | Typical source |
|---|---|---|
| `topic_area` | `Topic\s+Area\s+(\d+)` | DOE EERE, FECM, ARPA-E |
| `area_of_interest` | `(?:Area\s+of\s+Interest\|AOI)\s+(\d+)` | DOE, NETL |
| `dod_topic` | `Topic\s+(\d+)\s*[:.\u2013\u2014]` | MURI, ONR, ARO |
| `technical_area` | `Technical\s+Area\s+(\d+)` | DARPA, AFRL |
| `thrust` | `Thrust\s+(?:Area\s+)?(\d+)` | DARPA, ONR |
| `roses_element` | `^([A-F])\.(\d{1,2})\s+(\S.*)$` | NASA ROSES |
| `nsf_track` | `Track\s+([1-9]\|[IVX]+)\b` | NSF |
| `subtopic` | `Subtopic\s+(\d+[a-z]?)` | DOE, SBIR-style |
| `priority_research` | `(?:Priority\s+Research\s+(?:Direction\|Opportunity)\|PRD)\s+(\d+)` | DOE BES targeted FOAs, EFRC |
| `research_thrust` | `Research\s+Thrust\s+(\d+)` | DOE BES, EFRC |

`best_family()` returns the family with the most matches, requiring a ≥2× margin over the runner-up so mixed-family segmentation is rejected rather than guessed.

### 6.4 Acceptance rules

Accept only if **all** hold. Any failure → zero topics, parent untouched, reason logged.

1. ≥3 candidates from a single family
2. Ordinals monotonically increasing with ≤1 gap
3. Each span ≥200 and ≤40,000 characters
4. Spans non-overlapping, page ranges contiguous
5. Total candidates ≤60 (guards against reference lists and form indexes)
6. Candidates not confined to the detected TOC page range
7. ≥60% of candidates carry a non-empty title after the code

### 6.5 Derived fields

**Running header/footer removal** — required before summarizing, or every summary opens with the solicitation number:

```python
def running_lines(page_texts, threshold=0.4):
    c = Counter()
    for t in page_texts:
        lines = [l.strip() for l in t.splitlines() if l.strip()]
        for l in lines[:3] + lines[-3:]:
            c[re.sub(r'\d+', '#', l)] += 1          # page numbers -> '#'
    cutoff = threshold * len(page_texts)
    return {l for l, n in c.items() if n >= cutoff}
```

- **Title:** text after the code on the heading line, whitespace-normalized, ≤200 chars.
- **Summary:** leading sentences of the cleaned span, truncated at the last sentence boundary before 600 characters.
- **`program_area_tags`:** matched against the existing `scripts/program_areas.py` controlled vocabulary. No new vocabulary invented.
- **`own_deadline`:** only if exactly one unambiguous date expression occurs in the span and it does not contradict the parent's structured deadline.

### 6.6 Edge cases that must be handled

| Case | Handling |
|---|---|
| Scanned / image-only PDF | Zero extractable text → `no_extractable_text`, logged, no OCR in v1 |
| Encrypted PDF | Catch the `pymupdf` exception → `encrypted`, skip |
| Topics in a *separate* attachment (common for DOE "Topic Area Descriptions" appendices) | Segment **all** attachments on a record, merge results, dedup by `source_document_hash` |
| HTML notice (NSPIRES, agency pages) | Parallel layer using the `h1`–`h4` tree as the outline equivalent; same families, same acceptance rules |
| Same FOA arriving via two sources (Grants.gov + EERE Exchange) | Dedup on `source_document_hash` before merge; first source wins |
| Amendment renumbers topics | Title-first matching (§5.3) |

### 6.7 Topics by reference — the DOE BES case

**The plan as written does not cover this, and it is the single largest remaining gap.** DOE Office of Science solicitations split into three shapes, and only two of them segment.

| Shape | Example | Covered? |
|---|---|---|
| **Targeted FOA with enumerated directions** | BES "Chemical and Materials Sciences to Advance Clean Energy Technologies"; EFRC calls organized around Priority Research Directions | **Yes**, once the `priority_research` and `research_thrust` families are added (§6.3) |
| **Multi-topic FOA with numbered topic areas** | Most EERE, FECM, ARPA-E | **Yes**, already |
| **Annual omnibus that points outward** | "Continuation of Solicitation for the Office of Science Financial Assistance Program"; NSF division core solicitations | **No.** Segmentation returns zero topics, correctly, because there is no enumerated list in the document |

The third shape is the important one for a catalysis group. The annual Office of Science continuation FOA is the vehicle through which BES core research is funded, but the FOA does not enumerate research areas — it refers the reader to the program's own web pages. The fundable granularity Marc actually cares about (**BES → CSGB → Chemical Transformations → Catalysis Science**, with a named program manager) exists only in the agency's published program taxonomy, never in the PDF.

Segmentation cannot fix this, because the text genuinely is not there.

**Solution: a third input to the same child-record model.**

`scripts/sources/program_taxonomy.py` ingests published agency program hierarchies and attaches them as child records to the omnibus solicitations that fund them:

- **DOE Office of Science** — the BES research-area pages under `science.osti.gov`, walked as a tree (Division → Team → Program), each program yielding a description, a program manager, and a stable URL.
- **NSF** — division program listings, where each program has its own page, program officer and description.

Output uses the **same topic record schema** (§5.1) with `topic_source: "referenced"` rather than `"inline"`. This is deliberate: reusing the record type means the merge, rollup, scoring, feeds, change events and team matching machinery all work with zero additional code. Only three fields behave differently:

| Field | `inline` | `referenced` |
|---|---|---|
| `evidence_anchor` | `p14` (page in the notice) | the program page URL |
| `page_start` / `page_end` | populated | `null` |
| `source_document_hash` | hash of the notice PDF | hash of the fetched program page |

**Is this curation?** No. The taxonomy is published in structured form on the agency's own site and is scraped on the normal refresh cadence, exactly like any other adapter. What *is* required once is the **linkage rule** — which omnibus solicitation a given program hierarchy attaches to. That is a handful of entries (Office of Science continuation FOA → BES tree; NSF CBET core → CBET program list), it lives in the adapter's own config rather than a separate registry, and it changes about once a year when the FOA number rolls over. Detect the roll-over by matching the solicitation title pattern, not the number.

**Ordering note:** build this in Phase 2 alongside inline segmentation, not Phase 1, because it depends on the topic record schema existing. But recognize it as a *source* adapter in the existing lifecycle, subject to the same health gates and fail-closed behavior.

## 7. Wiring into existing modules

### 7.1 Catalog merge

Topics enter `data/opportunities.js` as child records with `parent_id` — **not** as a parallel store. This is the single most important structural decision: it means BM25 indexing, filters, sorting, Atom feeds, `alert_match.py`, team matching, the rating UI and CSV export all work on topics with no rewrite.

### 7.2 Currentness

Extends `scripts/currentness.py`:

```
open     = (own_deadline is null AND parent is current)
        OR (own_deadline is not null AND own_deadline >= build_date)
closed   = own_deadline has passed while parent remains current   # the ROSES case
expired  = parent no longer current
removed  = parent current AND document hash changed AND topic absent from new segmentation
```

Reapplied independently at runtime in feeds, email and browser, matching existing behavior.

**Expired topics are retained, not purged.** This diverges from how parent records are gated, deliberately. A closed MURI topic list is the best available predictor of next year's MURI topic list, and a program that shifts emphasis year over year is visible only if you keep the prior cycle. Rules:

- Retained for **3 years** past expiry, then dropped. Bounded, and long enough for two full cycles of an annual program.
- **Excluded from default search and from all alerts.** Surfaced only behind an explicit "include past cycles" filter, so they never dilute live results.
- Excluded from the `opportunities.js` size budget check by being written to a **separate `data/topic_archive.json`**, loaded lazily only when the filter is switched on. Otherwise three years of dead topics inflate every page load for a feature used occasionally.

**Recurrence linking.** `title_fingerprint` (§5.3) is already computed, so linking cycles is nearly free: when a topic appears under a *different* parent with a matching or ≥0.85-similar title, assign both the same `recurrence_group`. This powers the planning view — "this topic ran in FY25 and FY26, wording drifted toward electrochemical pathways" — which is the actual reason for retaining expired records.

### 7.2b User suppression — "not relevant"

Recall improvements are only useful if the result list stays trustworthy. A single visible action, **Not relevant**, on any card:

1. **Hides it immediately** from that user's search and team-match results.
2. **Records a local negative label** with a reason code, reusing the vocabulary already in the review flow.

Design decisions:

| Concern | Decision |
|---|---|
| Granularity | Two options on the control: hide *this topic*, or hide *the whole solicitation and its topics*. Both are needed — one bad topic does not condemn a parent. |
| Storage | Browser-local, consistent with §7.9. Keyed on `topic_id` / record id. |
| **Dependency on stable ids** | This feature is only correct because §5.3 carries `topic_id` forward through amendments. If ids churned on renumbering, mutes would silently break and hidden items would reappear. **Do not weaken §5.3.** |
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

### 7.4 Assertion-based regression detection

`data/expected_solicitations.json`:

```json
[
  {"pattern": "^W911NF-\\d{2}-S-\\d{4}$", "label": "ARO/MURI BAA", "source": "sam_gov"},
  {"pattern": "^N00014-\\d{2}-S-B\\d{3}$", "label": "ONR LRBAA",    "source": "sam_gov"}
]
```

`scripts/check_expected.py` runs after merge. If a declared solicitation is absent **while its source reports healthy**, exit nonzero → the existing workflow opens or updates the owner issue.

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
  match_path: "topic",              // "record" | "topic"
  parent_label: "DE-FOA-0003646 — Advanced Carbon Management",
  matched_terms: [                  // top 5 by BM25 contribution, descending
    {display: "electrocatalysis", stem: "electrocataly", field: "topic_terms", weight: 4.21},
    {display: "Faradaic",         stem: "faradaic",      field: "topic_terms", weight: 2.88},
    {display: "CO2 reduction",    stem: "co2",           field: "title",       weight: 2.10}
  ],
  matched_tags: ["catalysis", "co2_utilization"],
  evidence: {page_start: 14, page_end: 19, url: "https://..."}
}
```

**The `term_display` requirement.** `topic_terms` holds *stems*. Rendering the chips straight from it produces "electrocataly" and "faradaic", which reads like a bug. Hence `term_display` in §5.1: a stem → most-frequent-surface-form map, capped at the top 60 stems per topic. It is display metadata only, adds a few hundred bytes per record, and does not reconstruct prose — the privacy boundary in §5.2 holds.

**Rendering.** A single chip row under the title:

> Matched **electrocatalysis**, **Faradaic**, **CO₂ reduction** · in Topic Area 3 of DE-FOA-0003646 · p. 14

with a disclosure expanding to the full term/weight table and a link resolving to the exact page. Naming the parent inline is not optional — it is what turns an obscure-looking code into a recognizable opportunity.

**Ship it independently.** Match explanation is useful for ordinary opportunity records too, and it is a smaller, lower-risk change than the topic layer. Put it behind its own flag, `FF_MATCH_EXPLAIN`, so it can go live before topics do and its value can be judged separately. Two flags, two rollbacks.

### 7.7 Team match

Team match is not a downstream consumer that inherits this for free. It has its own scoring path and needs explicit work — see recon question 9 (§0.1), which exists specifically to establish whether it shares the BM25 index or runs its own similarity.

Topic records are in fact a **better** input here than parent records. An OpenAlex faculty profile is a term distribution over abstract-length technical prose; a topic span is abstract-length technical prose. A parent synopsis is a page of administrative boilerplate. The comparison gets more apples-to-apples, not less.

Required changes in `assets/team-researchers.js` and `team_match.html`:

| Concern | Requirement |
|---|---|
| Flag parity | The same `record_type === 'topic'` early-return guard as the main search. With `FF_TOPICS_ENABLED` off, team-match output must be **byte-identical** — this is covered by §0.5 and must be verified manually since it is browser-side. |
| Result explosion | One researcher × 20 MURI topics is unusable. **Cap at the top 3 topics per parent per researcher**, with an "and N more" disclosure. This was previously an open question; treat it as a requirement. |
| Rollup consistency | Same max-score parent absorption as §7.3, so a researcher is not listed against both a parent and its children as separate hits. |
| Match explanation | Team match needs `why this matched` *more* than the live site does, because the user is often evaluating a colleague's fit rather than their own. Show which **profile terms** drove the match, not just query terms. |
| Export | If team match has a CSV or clipboard export, topic rows must carry `parent_opportunity_number` and `topic_code` or the export is unusable outside the tool. |
| Reverse direction | Opportunity → faculty gets sharper: a topic matches fewer people more precisely. Confirm the reverse view reads the same rolled-up scores. |

### 7.8 Help and documentation

Minimal but not zero. Three additions:

1. **The hierarchy** — that a result may be a topic *within* a solicitation, and what the parent link means.
2. **Deadlines** — that a topic's date can differ from its parent's, and that the parent's structured deadline is what filters and sorting use. This is the one genuine source of user confusion; state it plainly.
3. **Match explanation** — one line on how to read the chip row and what the page anchor resolves to.

Also add a short note distinguishing `inline` from `referenced` topics (§6.7), since a referenced program record links to an agency page rather than a page in a PDF and will otherwise look inconsistent.

### 7.9 Researcher profile representation

**The OpenAlex terms were irrelevant because the wrong OpenAlex output was used, not because OpenAlex is the wrong source.**

OpenAlex `concepts` / `topics` are a classifier taxonomy — a few thousand leaf buckets spanning all of science. A catalysis PI collapses into "Chemistry", "Catalysis", "Materials science", shared with tens of thousands of unrelated researchers. Those labels cannot distinguish reverse water-gas shift over Mo₂C from enzymatic catalysis, so matching on them produces exactly the vague results observed. The failure is the representation, not the API.

**Fix: use OpenAlex for works retrieval, not classification.** For each researcher, pull their works and build the profile from **titles plus reconstructed abstracts** (`abstract_inverted_index` rehydrates to full abstract text and is free). Run that text through the same tokenizer and stemmer as §5.2. The profile is then a term map in the identical vector space as `topic_terms` — abstract-length technical prose compared against abstract-length technical prose. Comparing like with like is what makes the scores mean anything.

Three inputs, three distinct roles. Keep all three, but re-role them:

| Input | Role | Rationale |
|---|---|---|
| **ORCID** | **Identity resolution only** | Disambiguates *which* OpenAlex author ID is the right person — a genuine problem for common names and for PIs with split records. ORCID's own metadata is self-curated and sparse, which makes it a poor terms source but an excellent key. |
| **OpenAlex works text** | **Backward-looking base** | What the researcher has actually published. High volume, automatic, zero user effort. |
| **Resume / CV / interest statement** | **Forward-looking supplement** | What they intend to work on *next*. Neither other source can supply this. A PI pivoting from thermal to electrocatalysis has a publication record that lags the pivot by roughly three years, and for grant matching intent outweighs history. |

**Two profile paths, different inputs.**

| | Personal profile (live site) | Team match |
|---|---|---|
| Input | ORCID (optional) + resume/CV + free-text interests | **ORCID only** — anything richer makes the interface unusable at roster scale |
| Storage | Browser-local, per user | Committed roster for standing faculty; runtime entry for ad-hoc ORCIDs |
| Built | Client-side on entry | Build-time for the roster (cached, fast); client-side for ad-hoc |

ORCID's job in both paths is the same and is the reason to keep it: `GET /authors/orcid:0000-…` resolves straight to the correct OpenAlex author record, which removes the name-collision problem entirely. It is a key, not a terms source.

**Hybrid build for team match.** Committed-roster profiles are built in the workflow and cached in `faculty_profiles_v2.json`, so the page loads instantly and costs nothing per view. ORCIDs entered at runtime resolve client-side against the OpenAlex API, which is free and CORS-accessible — include a `mailto` parameter to stay in the polite pool, and cache results in browser storage so re-entering a colleague's ORCID is instant. Degrade gracefully if the API is unreachable: the roster still works.

**Weighting:** recency-weight works (last 3 years ×2, older ×1); weight the free-text statement as though it were ~10 papers so it can actually move a ranking rather than being drowned out. Support an optional **negative term list** so a PI can suppress a collaboration outside their own area that is polluting their record.

**Verification, not intuition.** The auto-derived gold set (Phase 1, step 10) is exactly the instrument for this: swap the profile representation, re-score, compare recall. Do not decide by eyeballing the term list — that is how the current representation got adopted.

## 8. Integration discipline

### 8.1 Additive-only rules

These are not style preferences. Each one exists because violating it has a specific failure mode in this repository.

| Rule | Why |
|---|---|
| New behavior lives in **new files**. Existing files receive insertions only. | Keeps every diff reviewable and every rollback a one-line flag flip. |
| **No existing function signature changes.** New behavior arrives as a keyword argument with a default that preserves current behavior. | Other modules import these. A positional-arg change breaks callers you did not think to check. |
| **No existing function is deleted or renamed.** The `document_fetch.py` extraction leaves backward-compatible aliases behind in `extract_document_evidence.py`. | §6.1 moves code out of a module that other scripts import from. Aliases mean nothing downstream notices. |
| **No existing CLI flag changes meaning.** New flags default off. | The workflow invokes these scripts with fixed arguments. A changed default silently changes the nightly build. |
| **No existing data file changes schema.** New fields are added; readers tolerate their absence. | `data/opportunities.js` is consumed by browser code that ships separately from the build. |
| **No existing test is modified.** New tests are added alongside. | The existing suite is your regression detector for the refactor. Editing it destroys the only thing verifying you did no harm. |
| **No reformatting.** Ever. | A `black` pass on a 600-line file turns a 3-line change into an unreviewable diff. |

### 8.2 Per-file edit contract

| File | Type | You may | You must not | Verify by |
|---|---|---|---|---|
| `scripts/document_fetch.py` | **new** | Anything | — | New unit tests |
| `scripts/topic_patterns.py` | **new** | Anything | — | New unit tests |
| `scripts/topic_segmentation.py` | **new** | Anything | — | Fixture golden tests |
| `scripts/extract_topics.py` | **new** | Anything | — | Cache diff stability |
| `scripts/build_gold_set.py`, `check_expected.py` | **new** | Anything | — | Manual first run |
| `scripts/sources/adapters/sam_gov.py` | **new** | Anything — follow `adapters/_template.py` | Deviate from the adapter interface | `tests/test_sources.py` |
| `scripts/sources/adapters/program_taxonomy.py` | **new** | Anything — follow `adapters/_template.py` | Deviate from the adapter interface | `tests/test_sources.py` |
| `assets/match-explain.js` | **new** | Anything | — | Manual A/B with `FF_MATCH_EXPLAIN` off |
| `scripts/sources/adapters/nspires.py` | **activate shell** | Fill in the existing stub's contract | Change the adapter interface | Existing adapter-contract tests |
| `scripts/extract_document_evidence.py` | **modify** | Delete moved function bodies, import from `document_fetch`, keep module-level aliases | Change any public name, change output schema, change exit codes | Existing suite passes **unchanged** |
| `scripts/build_catalog.py` | **modify** | Add `--enable-topics`; add one merge call at one insertion point; extend index build behind the flag | Restructure the build, reorder existing steps, change output with flag off | §8.4 hermetic gate |
| `scripts/currentness.py` | **modify** | Add a new `topic_status()` function; add a `record_type` early-return in the existing gate | Change the existing function's signature or semantics for non-topic records | New interaction tests + §8.4 |
| `scripts/build_changes.py` | **modify** | Append four new event types to the existing emitter | Touch existing event-generation code | §8.4 gate on a fixture with no topics |
| `scripts/evaluate_phase2.py` | **modify** | Add a topic-level metric block | Change existing metric definitions (breaks baseline comparability) | Re-run against frozen baseline |
| `assets/search-retrieval.js` | **modify** | Add rollup guarded by `if (!window.FF_TOPICS_ENABLED) return <existing path>` | Change existing scoring math | Manual A/B with flag off |
| `assets/app.js`, `match_explorer.html` | **modify** | Add rendering behind the flag; early-return on `record_type === 'topic'` when off | Restructure existing render path | Manual A/B with flag off |
| `assets/team-researchers.js`, `assets/team-matcher.js`, `scripts/faculty_match.py`, `team_match.html` | **modify** | Add topic handling + per-parent cap behind the flag; same `record_type` guard | Change existing similarity math or export column order | Manual A/B with flag off (§7.7) |
| `assets/site-help.js` | **modify** | Append the three items in §7.8 | Restructure existing help content | Visual check |
| `requirements.txt` | **modify** | Pin `pymupdf` exactly; add runtime deps only | Add test-only deps (they go in `requirements-dev.txt`) | Clean install in CI |
| `.github/workflows/*.yml` | **modify** | Insert new steps at the documented position (§9) | Reorder, rename, or alter existing steps; change `permissions:` or `concurrency:` | Dispatch run on branch |
| `LICENSE`, `README.md` | **replace / edit** | Replace MIT with the all-rights-reserved notice | — | Visual check of the README badge |
| `PROJECT.md` | **append** | Record the decision and measured deltas | Rewrite existing history | — |

### 8.3 How to do the `document_fetch.py` extraction safely

This is the only step that modifies working code before the flag exists, so it gets extra care. Do it as a pure move with aliases:

```python
# scripts/extract_document_evidence.py  — after the extraction

# Fetch/parse primitives moved to document_fetch.py in the topic-layer work.
# Aliases retained so existing importers and call sites are unaffected.
from document_fetch import (            # noqa: F401  (re-exported)
    FetchedDocument,
    Unchanged,
    fetch_document,
    _sha256_bytes,
    _extract_page_texts,
)
```

Procedure:

1. Copy the functions into `document_fetch.py`. **Do not edit them during the move** — not even whitespace.
2. Delete the bodies from the original and add the import block above.
3. Run the existing suite. It must pass with **zero** changes to test files.
4. Only after it passes green, in a **separate commit**, make any improvements to the moved code.

Separating "move" from "improve" into two commits means that if something breaks, `git bisect` tells you which one in thirty seconds.

### 8.4 The hermetic no-drift gate

The golden rule (§0.5) needs to be mechanically checkable, and it cannot be checked against live data because live data changes every night by design. So the check runs against **frozen inputs**.

Set this up in Phase 1, *before* any behavior-affecting change. Note that `tests/fixtures/` already contains `grants_db_extract.xml`, `grants_gov_opportunities.json` and `phase2_evaluation_export.json` — reuse that infrastructure rather than inventing a parallel one:

```bash
# tools/freeze_inputs.sh   (run once, in Phase 1)
mkdir -p tests/fixtures/frozen
cp data/source_records.json data/opportunity_enrichment.json \
   data/document_evidence.json tests/fixtures/frozen/
python scripts/build_catalog.py --input-dir tests/fixtures/frozen \
                                --output-dir /tmp/frozen_build --build-date 2026-08-20
find /tmp/frozen_build -type f -exec sha256sum {} \; | sed 's|/tmp/frozen_build/||' \
   | sort > evaluation/artifact_fingerprints.txt
git add tests/fixtures/frozen evaluation/artifact_fingerprints.txt
```

```bash
# tools/verify_no_drift.sh  (CI step, every build, from Phase 1 onward)
python scripts/build_catalog.py --input-dir tests/fixtures/frozen \
                                --output-dir /tmp/verify --build-date 2026-08-20
find /tmp/verify -type f -exec sha256sum {} \; | sed 's|/tmp/verify/||' | sort \
   > /tmp/verify_fingerprints.txt
diff evaluation/artifact_fingerprints.txt /tmp/verify_fingerprints.txt || {
  echo "DRIFT: flag-off output changed. See §0.5."; exit 1; }
```

The fixed `--build-date` is essential — otherwise `currentness.py` produces different output every day and the hash is meaningless. If `build_catalog.py` does not currently accept `--input-dir`, `--output-dir` and `--build-date`, **adding them is itself a Phase 1 task**, and it is an additive change (each defaults to today's behavior).

This gate is what makes every subsequent phase safe. Build it first.

## 9. GitHub Actions integration

### 9.1 Read before you edit

The workflow is the single most dangerous file in this repository, because a mistake there does not throw an error you see — it publishes wrong data, or silently stops publishing, or opens issues every night forever. Answer §0.1 questions 2, 3, 6, 7 and 11 before opening it.

### 9.2 Where the new steps go

```
  … existing steps …
  build catalog (XML)
  run source adapters
  enrich catalog
  extract document evidence
+ extract topics                    ← NEW, Phase 2 (cache only)
  build catalog / merge             ← flag added here, Phase 3
+ check expected solicitations      ← NEW, Phase 1
  build changes
  build feeds
  check links
+ verify no drift                   ← NEW, Phase 1
  commit + push
  deploy Pages
```

Insert; do not reorder anything existing.

### 9.3 Failure-mode rules for new steps

| Concern | Requirement |
|---|---|
| Benign zero-result runs | `extract_topics.py` **exits 0** when it finds no topics. That is a normal outcome, not an error. Reserve nonzero for "could not write the cache." |
| Not poisoning the issue automation | During Phase 2, mark the topic step `continue-on-error: true`. It is producing a cache nobody reads; it must never block the publish of good data or trip the owner-issue path. Remove that only at Phase 3. |
| Persistence | Add `data/topic_records.json` to the workflow's `git add` list explicitly. If you forget, the cache is rebuilt from scratch nightly, every topic looks new, and you will spend a day debugging a phantom. |
| Runtime | Measure job duration before and after. Segmentation on the `--max-documents` bound should be seconds, but parsing a 400-page BAA is not free. Add a per-document timeout so one pathological PDF cannot hit the job timeout. |
| Permissions | No new scopes are required. If you believe you need to widen `permissions:`, stop — something is wrong with the design. |
| Concurrency | Do not touch the `concurrency:` block. |
| Dependency cache | Pinning `pymupdf` changes the `requirements.txt` hash, so the first run after that commit is slow. Expected, not a bug. |
| Dev dependencies | `reportlab` is used only to generate test fixtures. It goes in `requirements-dev.txt`, installed only in the test job — never in the nightly runtime install. |
| Pages deploy coupling | If deploy depends on build success, a new failing step blocks publication of otherwise-good data. This is exactly why Phase 2 uses `continue-on-error`. |

### 9.4 Dispatch-test checklist before merging any workflow change

1. Push the branch. Run via `workflow_dispatch`.
2. Confirm the job completes and the **runtime delta is under 20%**.
3. Confirm the diff of committed artifacts contains only what you expect. With the flag off, it should contain **nothing** attributable to your change.
4. Confirm no GitHub issue was opened or updated.
5. Confirm `verify_no_drift` passed.
6. Only then open the PR.

## 10. Phases

Reordered so everything large and additive lands before anything existing changes behavior. Four phases.

---

### Phase 1 — Foundations (purely additive; no existing behavior changes)

Everything here adds instrumentation, adds a new source, or refactors without changing output. The catalog gains records from new sources; nothing about how the site works changes.

0. **Complete the §0 reconnaissance.** Written answers to all eight questions in §0.1, on a branch, before any edit. This is a gate, not a suggestion — every later step assumes you know which script writes what and which exits trigger the issue automation.
1. **Add build determinism arguments** to `build_catalog.py` if absent: `--input-dir`, `--output-dir`, `--build-date`, each defaulting to current behavior. Purely additive, and required by step 3.
2. **Build the no-drift harness** (§8.4): freeze inputs into `tests/fixtures/frozen/`, capture `evaluation/artifact_fingerprints.txt`, wire `tools/verify_no_drift.sh` into CI. **Do this before any behavior-affecting change** — it is the safety net for everything that follows.
3. **Freeze the baseline.** Run `evaluate_phase2.py` against the current catalog; commit `evaluation/baseline_pre_topics.json`. Post-change numbers are meaningless without it.
4. **Add the size-budget test** to `tests/`: fail the build if `data/opportunities.js` exceeds 1.5× its pre-change byte size.
5. **License housekeeping.** Replace `LICENSE` (MIT is leftover) with the all-rights-reserved notice used on the other deployed tool; update the README license line so the badge matches.
6. **Extract `scripts/document_fetch.py`** from `extract_document_evidence.py` per §6.1, following the two-commit move-then-improve procedure in §8.3. Pin `pymupdf` exactly. **The existing test suite must pass unchanged** — this step is behavior-preserving by definition.
7. **Write `scripts/sources/adapters/sam_gov.py`**, modelled on `scripts/sources/adapters/_template.py`, inside the existing adapter lifecycle, per §7.5.
8. **Activate `scripts/sources/adapters/nspires.py`**, anchored on the ROSES Table 2 / Table 3 HTML listings rather than PDF parsing.
9. **Rebuild researcher profiles per §7.9**: OpenAlex works *text* (titles + rehydrated abstracts) rather than assigned concepts; ORCID demoted to identity resolution. Score the old and new representations against the gold set from step 10 before committing to either. Purely additive — write to a new `faculty_profiles_v2.json` and leave the existing file untouched until measured.
10. **Write `scripts/build_gold_set.py`.** Pull awards to UR Chemical and Sustainability Engineering faculty from NSF Award Search, NIH RePORTER and USAspending over a 3-year window; map each back to its originating solicitation number; emit `evaluation/gold_set.json` as `{query_profile, expected_solicitation_numbers[]}`. Regenerate quarterly in the workflow.
11. **Populate `data/expected_solicitations.json`** and wire `scripts/check_expected.py` into the workflow.

> **Why SAM.gov moved into Phase 1**, reversing the earlier ordering: you cannot develop or tune a segmenter without a corpus of real umbrella documents, and the canonical umbrellas (MURI, ONR LRBAA, AFOSR, ARO, DARPA) are contract-vehicle BAAs that never appear on Grants.gov. Today they are absent from the catalog entirely. Building this adapter first supplies the Phase 2 development corpus *and* closes the largest standing coverage gap independently of whether topics ever ship.

**Exit criteria:** existing tests green **with zero test-file edits**; `verify_no_drift` passing in CI; baseline and gold set committed; two new sources reporting healthy through the existing gates; catalog record count up, behavior otherwise identical.

---

### Phase 2 — Extraction, offline (writes a cache nothing consumes)

The topic pipeline runs daily and produces a cache. The published catalog does not read it. Zero risk to the live site.

11. **Write `scripts/topic_patterns.py`** with the eight families (§6.3) and `best_family()`.
12. **Write `scripts/topic_segmentation.py`**: layers A–D (§6.2), acceptance rules (§6.4), derived fields (§6.5), edge cases (§6.6).
13. **Generate synthetic fixtures** into `tests/fixtures/synthetic/` via `reportlab` — one PDF per pattern family, plus a bookmark-less variant, a TOC-only trap, and a reference-list trap. Synthetic means no real notice is ever committed.
14. **Write `tests/test_topic_segmentation.py`**: golden outputs per fixture; idempotency (two runs byte-identical); rejection cases; a `match_topics()` renumbering test (insert a topic mid-list, assert one addition and zero amendments).
15. **Write `scripts/extract_topics.py`**: consume `document_fetch`, segment, derive fields, build term maps, assign stable ids via `match_topics`, write `data/topic_records.json` with a diagnostics block (acceptance rate by method and by agency, rejection-reason histogram). Honor `--max-documents`.
16. **Write `scripts/sources/program_taxonomy.py`** (§6.7) emitting `topic_source: "referenced"` records for the DOE Office of Science and NSF core omnibus solicitations. Same adapter lifecycle, same health gates.
16b. **Tune offline** against the real corpus — now including the DoD BAAs from Phase 1. Iterate on patterns until acceptance rates are acceptable per agency family.
17. **Wire into the scheduled workflow** after `extract_document_evidence.py`, writing the cache only. Mark the step `continue-on-error: true` and add `data/topic_records.json` to the `git add` list (§9.3). Run once via `workflow_dispatch` on your branch and walk the §9.4 checklist before merging.
18. **Observe one week** of cache output and diff churn before proceeding.

**Exit criteria:** ≥80% acceptance on documents that visibly contain topic lists; zero low-confidence records published; `topic_records.json` diff-stable day over day; published build unchanged.

---

### Phase 3 — Wiring, dark (behind flags, fully reversible)

Everything is built and running in parallel, off by default.

19. **`build_catalog.py --enable-topics`**: merge topic records with `parent_id`; extend index construction to include `topic_terms`; dedup on `source_document_hash`.
20. **Backfill suppression**: topics whose `first_seen` equals the backfill marker date are excluded from `build_changes.py` on that build only — otherwise the first digest is entirely noise.
21. **Extend `currentness.py`** per §7.2, with dedicated parent/child interaction tests.
22. **`assets/search-retrieval.js`**: max-score rollup (§7.3).
22b. **Write `assets/match-explain.js`** (§7.6) behind its own `FF_MATCH_EXPLAIN` flag. Ship this one **first and independently** — it is lower risk than topics and valuable on ordinary records, so it earns its own rollout.
22c. **Add `term_display`** to the topic record builder in `extract_topics.py`, capped at 60 stems. Without it the match chips render stems and look broken.
23. **`assets/app.js` + `match_explorer.html`**: collapsed topic rendering behind `window.FF_TOPICS_ENABLED`.
23b. **`assets/team-researchers.js` + `team_match.html`**: all six requirements in §7.7, including the top-3-per-parent cap and profile-term explanations. Verify flag-off parity manually — this is browser-side and the hermetic gate does not reach it.
23c. **Update the help page** per §7.8.
24. **Extend `build_changes.py`** with `topic_added` / `topic_amended` / `topic_closed` / `topic_removed`.
25. **Confirm `build_feeds.py`** emits topic entries with stable ids, and **`alert_match.py`** matches topics with no modification.
26. **Extend `evaluate_phase2.py`** to report topic-level recall separately from record-level.
27. **Run the parallel comparison for two weeks**: both catalogs built in CI, compared against the frozen baseline on record-level recall, topic-level recall, catalog size and `opportunities.js` byte size.

**Exit criteria:** topic-level recall improves on the gold set; record-level recall does not regress; size budget held; `verify_no_drift` still passing with the flag off.

---

### Phase 4 — Enable and operate

28. **Flip** `--enable-topics` and `FF_TOPICS_ENABLED` in the published build, and remove `continue-on-error` from the topic step so real failures surface through the existing issue automation.
29. **Record** the decision, rationale and measured deltas in `PROJECT.md`.
30. **Standing operations:** quarterly gold-set regeneration; monthly review of the rejection-reason histogram for pattern drift as agencies change templates; `check_expected.py` failures triaged as source regressions.
31. **Gate the optional AI layer** (§11) on the measured deltas from step 27 — not before.

**Rollback:** every step through 27 is reversible by flipping the flag off. The topic cache keeps building harmlessly and the published catalog reverts to current behavior. Step 6 is the only irreversible refactor, and it is behavior-preserving and covered by the existing suite.

---

## 11. Deferred optional AI layer

Not built in v1. Recorded so the deterministic design does not preclude it.

**Adds:** cleaner human-readable summaries, normalized dates written in prose, consistent phrasing across agency formats. Polish, not mechanism.

**Does not do:** discover topics. The model would only label and summarize spans deterministic segmentation already located, and would be forbidden from emitting a `topic_code` not present verbatim in the source span.

**Cost if enabled:** Haiku-tier on ~2,250 spans for a full backfill (~1,200 input / ~250 output tokens each) is on the order of $5, or half that through the Batch API. Steady state, gated by the existing hash change detection, is a few hundred spans per week — roughly $2/month.

**Secret handling if enabled:** key in a protected GitHub environment; workflow triggered only by `schedule` and `workflow_dispatch`; `pull_request_target` never used; no derived value echoed. The key never touches committed output.

## 12. Risk register

| Risk | Mitigation |
|---|---|
| Catalog inflation; `opportunities.js` ships to the browser | Size-budget test (Phase 1, step 4); summary + term map only, never full text |
| Result pollution: 20 topics plus parent all match one query | Max-score rollup; collapsed rendering; no independent parent entry |
| Phantom `topic_amended` flood after a library upgrade | Exact `pymupdf` pin; `tool_versions` in `extractor_version` makes the cause visible |
| Amendment renumbering produces false diffs | Title-first matching (§5.3) |
| Git repository growth from daily cache commits | Sorted stable serialization; volatile fields updated only on real change (§5.4) |
| `currentness.py` evicts parent and child inconsistently | Explicit rule (§7.2) plus interaction tests |
| First run floods change feed and digest | Backfill suppression (Phase 3, step 20) |
| Segmentation false positives on reference lists | Acceptance rules (§6.4); low confidence never publishes |
| New agency template breaks segmentation | Fails closed to zero topics; rejection reason logged and monitored (Phase 4, step 30) |
| SAM.gov quota exhaustion | Prefilter before description calls; cache descriptions by notice id (§7.5) |
| Eval discontinuity | Baseline frozen before any change (Phase 1, step 3) |
| BES-style omnibus yields zero topics and looks like a bug | Expected and correct; covered instead by the taxonomy adapter (§6.7). Track `no_layer_accepted` separately from genuine failures in the diagnostics block |
| Topic cards look obscure and get ignored, so recall rises but clicks fall | Match explanation is a **requirement**, not a nicety (§7.6); ship `FF_MATCH_EXPLAIN` before or with topics |
| Match chips render stems ("electrocataly") | `term_display` map (§5.1, Phase 3 step 22c) |
| Team match floods with one researcher × 20 topics | Top-3-per-parent cap (§7.7) |
| Team match drifts with the flag off, outside the hermetic gate's reach | Explicit manual A/B in Phase 3 step 23b |
| Muted items still appear in email/Atom alerts | Known split (§7.2b); documented in help; optional suppression-list export |
| A mistaken mute hides something permanently and invisibly | Muted-items panel is mandatory (§7.2b) |
| Three years of expired topics inflate every page load | Archive written to a separate lazily-loaded `topic_archive.json` (§7.2) |
| Scheduled workflow silently disabled after 60 quiet days | Unconditional heartbeat commit every run (§16.3); quarterly manual check that the schedule is enabled |
| Missed or delayed cron run | Change-detection ladder makes runs idempotent and self-healing; nothing assumes yesterday ran (§16.3) |
| SAM.gov key invalid or revoked | Existing source health gate opens the owner issue; it is the only credential in the system (§16.1) |
| Runtime ORCID lookups hammer OpenAlex or fail offline | `mailto` polite pool, browser-cached results, roster path degrades gracefully (§7.9) |
| Silent behavior drift in a "harmless" refactor | Hermetic no-drift gate on frozen inputs (§8.4), passing from Phase 1 onward |
| New cache never persisted because it is missing from `git add` | Explicit workflow requirement (§9.3); symptom is every topic appearing new each night |
| New step trips the owner-issue automation nightly | `extract_topics.py` exits 0 on zero results; `continue-on-error` through Phase 2 (§9.3) |
| Pathological PDF hits the job timeout and blocks the publish | Per-document timeout in the topic step (§9.3) |
| Refactor breaks an unnoticed importer | Backward-compatible aliases retained; move and improve split into two commits (§8.3) |
| Formatter run buries a small change in an unreviewable diff | Explicit no-reformat rule (§8.1) |

## 13. Open decisions

**Settled** — recorded here so they are not relitigated:

- Low-confidence topics stay **hidden**, not surfaced with a warning. A wrong topic is worse than a missing one.
- Expired topics are **retained 3 years and flagged**, in a separate lazily-loaded archive, excluded from default search and alerts (§7.2).
- Team match takes **ORCIDs only**. Resume and free-text belong to the personal browser-local profile (§7.9).
- Profiles are built from OpenAlex **works text**, not assigned concepts. ORCID is an identity key (§7.9).
- No external deadline. Sequence for safety, not speed.

**Still open:**

1. **Summary length.** 600 chars proposed. The term map carries retrieval, so this is purely a display-quality call.
2. **Topics in Atom feeds.** Proposed: include, since a new topic under an existing umbrella is exactly the event the current feed misses.
3. **Taxonomy depth for referenced topics.** Attach at program level (BES → Catalysis Science) or one level deeper? Proposed: program level, where the program manager and the funding decision sit.
4. **Mute/alert split.** Accept that muted items still appear in alerts, or build the suppression-list export? Proposed: accept for v1, document it plainly, revisit if it annoys anyone.
5. **OCR.** Deferred. Revisit only if `no_extractable_text` rejections prove material.
6. **License text.** Confirm the exact all-rights-reserved notice used on the other deployed tool so both repositories match.

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
| **Hermetic gate** | CI check that builds from frozen fixture inputs at a fixed date and diffs output hashes. Enforces §0.4 (§8.4). |
| **Flag off parity** | With `--enable-topics` off, output must be byte-identical to pre-change. The core safety property. |
| **Backfill suppression** | Excluding first-run topics from change events so the first digest is not entirely noise (Phase 3). |
| **Gold set** | Auto-derived known-positives from past awards. The only legitimate way to judge whether a change helped (§10 Phase 1). |

## 15. Progress checklist

Copy into a tracking issue. **The gate lines are not steps — they are stops.** Do not cross one that is unchecked.

**Phase 1 — Foundations**
- [ ] 0. §0 reconnaissance complete, nine answers written down
- [ ] 1. `--input-dir` / `--output-dir` / `--build-date` added to `build_catalog.py`
- [ ] 2. No-drift harness built and passing in CI (§8.4)
- [ ] 2b. Heartbeat file `.github/last_build` written unconditionally every run (§16.3) — prevents silent 60-day schedule disabling
- [ ] 3. `evaluation/baseline_pre_topics.json` frozen
- [ ] 4. Size-budget test added
- [ ] 5. LICENSE and README updated
- [ ] 6. `document_fetch.py` extracted — two commits, existing suite green with zero test edits
- [ ] 7. `sources/adapters/sam_gov.py` written and healthy
- [ ] 8. `sources/adapters/nspires.py` activated
- [ ] 9. Profiles rebuilt per §7.9 (OpenAlex works text; ORCID as key) into `faculty_profiles_v2.json`
- [ ] 10. `build_gold_set.py` written, `gold_set.json` generated
- [ ] 11. `expected_solicitations.json` + `check_expected.py` wired
- [ ] **GATE:** existing tests green with zero test-file edits · no-drift passing · new sources healthy · behavior otherwise identical

**Phase 2 — Extraction, offline**
- [ ] 12–15. Patterns, segmentation, synthetic fixtures, tests
- [ ] 16. `extract_topics.py` writing `data/topic_records.json`
- [ ] 17. `sources/program_taxonomy.py` for referenced topics (§6.7)
- [ ] 18. Offline tuning against the real corpus
- [ ] 19. Workflow step added — `continue-on-error: true`, path in `git add`, §9.4 checklist walked
- [ ] 20. One week of observation
- [ ] **GATE:** ≥80% acceptance where topic lists visibly exist · zero low-confidence published · cache diff-stable · published build unchanged

**Phase 3 — Wiring, dark**
- [ ] 21–24. Catalog merge, backfill suppression, currentness, retrieval rollup
- [ ] 25. `match-explain.js` behind `FF_MATCH_EXPLAIN` — ship this one first and independently
- [ ] 26. `term_display` added to the topic builder
- [ ] 27–28. Search UI and team match UI behind `FF_TOPICS_ENABLED`
- [ ] 28b. "Not relevant" control + **muted items panel** + local negative labels (§7.2b)
- [ ] 28c. Expired-topic archive, "include past cycles" filter, recurrence grouping (§7.2)
- [ ] 29. Help page updated (§7.8)
- [ ] 30–32. Change events, feeds, alerts, eval extension
- [ ] 33. Two-week parallel comparison
- [ ] **GATE:** topic recall up · record recall not regressed · size budget held · no-drift still passing with flag off

**Phase 4 — Enable**
- [ ] 34. Flags flipped, `continue-on-error` removed
- [ ] 35. `PROJECT.md` updated with measured deltas
- [ ] 36. Standing operations scheduled, including a quarterly check that the cron schedule is still enabled
- [ ] 37. AI layer decision made on data, not intuition (§11)

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
| **SAM.gov opportunities** | **api.data.gov key** | Yes — the only credential in the system |

ORCID is never called directly. Resolution goes ORCID → `openalex.org/authors/orcid:0000-…`, which removes an entire dependency and its auth story.

### 16.2 Where updating actually happens

Pages serves static files and never executes anything. All updating is Actions. Staleness is handled in **two independent places**, and this is the most important resilience property in the system:

1. **Build time** — `currentness.py` gates expired records out of the published catalog.
2. **Runtime** — the same gate is reapplied in the browser, in feeds, and in email against *today's* date, not the build date.

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

### 17.2 This document was written without reading the code

It was written from the repository's README and public description. File names, function names, module boundaries and workflow step order are **inferences**. Some will be wrong.

**When the plan and the repository disagree, the repository wins, and the plan gets corrected.** An agent that silently works around an inaccuracy leaves a document that is wrong for every later session. Correcting §7 to name the function that actually exists is part of the work, not a distraction from it.

### 17.3 Session protocol

| Session | Scope | Deliverable |
|---|---|---|
| 1 | §0.1 reconnaissance **only** (eleven questions). The human performs repo setup (clone, branch, commit this plan) beforehand — an agent's first action should not be repo surgery. No edits to existing files, no installs, no write-mode scripts. | `docs/RECON.md` — nine answers with file/line citations, a "Plan discrepancies" section, a "Blocked" section |
| 2 | Revise this plan against `docs/RECON.md`. Still no code changes. | Corrected `docs/TOPIC_LAYER_PLAN.md` |
| 3+ | **One numbered §15 checklist step per session.** | The step, its verification output, and an updated checklist |

Sessions 1 and 2 are not overhead. They are what makes the additive-edit discipline in §8 possible, because you cannot make a surgical edit to a file whose structure you inferred.

### 17.4 Standing rules for every implementation session

- State the intended diff **before** making it.
- After editing, paste `git diff --stat` and the test suite output. Never assert a result you did not observe.
- Stop at the end of the step. Do not begin the next one.
- Stop at any unchecked gate in §15.
- When blocked, stop and ask. Do not improvise.
- End with the §0.4 session report, including what you did *not* do.

### 17.5 Where work happens

A proper `git clone`, on a branch, with the test suite runnable and `git diff` available. **Not a copied folder of files** — the constraints in §8 are enforced by diff review, and there is no diff without git history. Never work on the branch GitHub Pages deploys from until the Phase 3 gate is cleared.
