"""Deterministic segmentation of a funding notice into child topic records.

Four layers, first success wins (§6.2). Every layer proposes candidate
headings; the seven acceptance rules in §6.4 then decide whether the proposal
becomes subtopics or nothing at all.

**Failure is closed and total.** A proposal that misses any acceptance rule
yields zero subtopics and leaves the parent record untouched -- never a partial
or speculative list. The asymmetry is deliberate (§18.3): a missing subtopic
costs a user one search that could have gone better, while a wrong subtopic
puts a plausible-looking card with a page anchor and a deadline in front of a
principal investigator who may spend weeks writing to a topic that does not
exist.

Nothing in this module imports ``extract_document_evidence``. That module will
import *this* one at a flag-guarded call site in package C, and the dependency
must run in exactly one direction.

``pdfplumber`` is imported lazily inside Layer C so that importing this module
-- or running Layers A, B and D -- never pays for it.

See docs/TOPIC_LAYER_PLAN.md §6.1-§6.6, and docs/PDF_API_NOTES.md for the
measured library behaviour this is written against.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
import hashlib
import io
import re
import statistics
from time import monotonic

from pypdf import PdfReader
from pypdf.generic import Destination

from scripts import program_areas
from scripts.build_catalog import tokenize
from scripts.subtopic_patterns import (
    STRUCTURAL_FAMILY,
    best_family,
    is_administrative,
)


# --- Budgets and caps (§6.1, §6.4, §5.1) ------------------------------------

# Layer C stops scanning here. An enumerated topic list that begins after page
# 120 of a notice is not a real pattern.
SUBTOPIC_CHAR_SCAN_PAGES = 120
# Per document. Bounds one pathological PDF.
SUBTOPIC_TIME_BUDGET_SECONDS = 20
# Per run, across every document. This is the one that actually protects the
# job: 45 documents x 20s of per-document budget is 15 minutes on its own.
SUBTOPIC_RUN_BUDGET_SECONDS = 600

MIN_CANDIDATES = 3
MAX_CANDIDATES = 60
MIN_SPAN_CHARS = 200
MAX_SPAN_CHARS = 40_000
MAX_ORDINAL_STEP = 2          # a step of 2 is "one gap"; 3+ is a real break
MIN_TITLED_RATIO = 0.6
MAX_TITLE_CHARS = 200
MAX_SUMMARY_CHARS = 600
MAX_TERMS = 400
MAX_PROGRAM_AREA_LABELS = 14

# Layer C candidate test. Measured (docs/PDF_API_NOTES.md §3): the size branch
# admits 0.0-0.2% of lines on the DoD BAAs this layer exists for, and weight
# carries the signal entirely. The term is kept because it costs nothing and
# earns its place on notices that use display type -- it is not load-bearing.
HEADING_SIZE_RATIO = 1.15
MAX_HEADING_CHARS = 200
BOLD_RE = re.compile(r"bold|black|heavy|semibold|demi", re.IGNORECASE)

DOT_LEADER = re.compile(r"^(?P<title>.+?)\.{3,}\s*(?P<page>\d+)\s*$")
TOC_MIN_LEADER_LINES = 5

# §6.4 rule 8 -- the announcement-furniture veto, FITTED not reasoned.
#
# Every word here is about the *process* of applying for or administering an
# award, and none of them can name a research subject. The list deliberately
# excludes `information`, `research`, `area`, `program`, `project`, `technology`
# and similar: those appear in legitimate topic titles, and including
# `information` alone moved the worst legitimate set from 0.008 to 0.043.
#
# Fitted against the 22 accepted documents of the 770-document backfill, each
# labelled by reading every title (docs/CORPUS_CENSUS.md):
#
#   legitimate sets   process-token rate 0.000 - 0.008   (n=10, incl. 363526)
#   furniture sets    process-token rate 0.133 - 0.889   (9 of 13 caught)
#
# The threshold sits mid-gap. The four furniture sets it does NOT catch score
# 0.000 -- they are review criteria, programme phases, NEPA factors and M&E
# workstreams, which share no vocabulary with the application process. They are
# handled by confidence tiering instead, not by this rule.
PROCESS_VOCABULARY = frozenset({
    "summary", "detail", "fund", "funding", "award", "purpose", "goal",
    "objective", "authority", "authorization", "cost", "indirect", "history",
    "background", "context", "description", "narrative", "section", "criteria",
    "consideration", "statute", "regulation", "mandate", "guidance",
    "requirement", "legal", "eligible", "eligibility", "application",
    "proposal", "example", "table", "plan", "contribution", "matching",
    "overview", "statement", "oversight", "restriction", "law", "submission",
    "deadline", "unallowable", "appendix", "checklist", "instruction",
    "template", "form", "notice", "nofo", "solicitation", "attachment",
})
PROCESS_TOKEN_MAX = 0.07

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MONTH_NAMES = (
    "january february march april may june july august september october "
    "november december"
).split()
TEXT_DATE = re.compile(
    r"\b(" + "|".join(MONTH_NAMES) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
    re.IGNORECASE,
)


def extractor_version() -> str:
    """Toolchain identity, so a phantom-amendment flood names its own cause."""
    from importlib.metadata import PackageNotFoundError, version

    def resolved(name):
        try:
            return version(name)
        except PackageNotFoundError:
            return "unknown"

    return f"1.0.0+pdfplumber{resolved('pdfplumber')}+pypdf{resolved('pypdf')}"


# --- Result types -----------------------------------------------------------


@dataclass(frozen=True)
class Subtopic:
    """One accepted child topic, before it is turned into a catalog record."""

    subtopic_code: str
    subtopic_code_norm: str
    subtopic_ordinal: int
    ordinal_label: str
    title: str
    title_fingerprint: str
    summary: str
    subtopic_terms: dict
    page_start: int | None
    page_end: int | None
    anchor: str | None
    char_start: int
    char_end: int
    program_area_labels: tuple
    topic_areas: tuple
    own_deadline: str | None


@dataclass(frozen=True)
class SegmentationResult:
    subtopics: tuple = ()
    method: str | None = None
    confidence: str | None = None
    family: str | None = None
    reason: str | None = None
    diagnostics: dict = field(default_factory=dict)

    @classmethod
    def empty(cls, reason, **diagnostics):
        return cls(reason=reason, diagnostics=diagnostics)

    def __bool__(self):
        return bool(self.subtopics)


class RunBudget:
    """Wall-clock budget shared across every document in one run (§6.1).

    Exhausting it is a normal, non-fatal outcome: it never raises. Documents
    not reached record `run_budget` and are picked up on a later night through
    the ordinary backfill path.
    """

    def __init__(self, seconds=SUBTOPIC_RUN_BUDGET_SECONDS, clock=monotonic):
        self._clock = clock
        self._deadline = clock() + seconds

    def exhausted(self):
        return self._clock() >= self._deadline

    def remaining(self):
        return max(0.0, self._deadline - self._clock())


# --- Identity helpers (§5.3) ------------------------------------------------


def normalize_code(code: str) -> str:
    """'Topic Area 2' -> 'ta-2'; stable across capitalization and punctuation."""
    lowered = (code or "").casefold()
    lowered = re.sub(r"\barea of interest\b", "aoi", lowered)
    words = re.findall(r"[a-z]+|\d+", lowered)
    initials = "".join(word[0] for word in words if not word.isdigit())
    numbers = "-".join(word for word in words if word.isdigit())
    return f"{initials}-{numbers}".strip("-")


def title_fingerprint(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9 ]+", "", (title or "").casefold())
    normalized = " ".join(sorted(normalized.split()))   # word-order insensitive
    return hashlib.blake2s(normalized.encode(), digest_size=4).hexdigest()


def match_subtopics(old, new):
    """Pair old subtopics to new ones so renumbering is not a false amendment.

    Title match wins over code match: an amendment that *inserts* a topic
    renumbers every topic below it, and keying on ordinal would report one
    addition plus seventeen spurious amendments.
    """
    pairs, remaining_old, remaining_new = [], list(old), list(new)

    for candidate in list(remaining_new):
        hit = next(
            (
                item
                for item in remaining_old
                if item.get("title_fingerprint")
                and item["title_fingerprint"] == candidate.get("title_fingerprint")
            ),
            None,
        )
        if hit:
            pairs.append((hit, candidate))
            remaining_old.remove(hit)
            remaining_new.remove(candidate)

    for candidate in list(remaining_new):
        best, score = None, 0.0
        for item in remaining_old:
            ratio = SequenceMatcher(
                None,
                str(item.get("title") or "").casefold(),
                str(candidate.get("title") or "").casefold(),
            ).ratio()
            if ratio > score:
                best, score = item, ratio
        if best and score >= 0.85:
            pairs.append((best, candidate))
            remaining_old.remove(best)
            remaining_new.remove(candidate)

    for candidate in list(remaining_new):
        hit = next(
            (
                item
                for item in remaining_old
                if item.get("subtopic_code_norm")
                and item["subtopic_code_norm"] == candidate.get("subtopic_code_norm")
            ),
            None,
        )
        if hit:
            pairs.append((hit, candidate))
            remaining_old.remove(hit)
            remaining_new.remove(candidate)

    pairs += [(item, None) for item in remaining_old]      # removed
    pairs += [(None, item) for item in remaining_new]      # added
    return pairs


# --- Derived fields (§5.2, §6.5) --------------------------------------------


def build_term_map(span_text: str, max_terms: int = MAX_TERMS) -> dict:
    """Stemmed term frequencies in the catalog's own vector space.

    Uses build_catalog.tokenize unmodified, which is required for correctness
    rather than merely convenient: search_index.postings keys are the output of
    exactly this function, so a term map built by any other tokenizer produces
    keys that never collide with the index and the subtopic simply never
    matches. Do not add a length filter -- 'co2' is three characters and is
    precisely what this feature exists to retrieve.
    """
    return dict(Counter(tokenize(span_text)).most_common(max_terms))


def running_lines(containers, threshold: float = 0.4) -> set:
    """Header/footer lines repeated across pages, with page numbers masked.

    Without this every summary opens with the solicitation number.
    """
    counts = Counter()
    for container in containers:
        lines = [line.strip() for line in (container.get("text") or "").splitlines()]
        lines = [line for line in lines if line]
        # §6.5's sketch counted `lines[:3] + lines[-3:]` directly, which counts
        # every line TWICE on any page holding three or fewer lines -- head and
        # tail are then the same list. At a 0.4 threshold that marks ordinary
        # body text as a running header and strips it, leaving empty summaries.
        # Deduplicate per container: a line is a header once per page, not
        # twice for being near both ends of a short one.
        for line in dict.fromkeys(lines[:3] + lines[-3:]):
            counts[re.sub(r"\d+", "#", line)] += 1
    cutoff = threshold * max(1, len(containers))
    return {line for line, count in counts.items() if count >= cutoff}


def strip_running_lines(text: str, running: set) -> str:
    if not running:
        return text
    kept = [
        line
        for line in (text or "").splitlines()
        if re.sub(r"\d+", "#", line.strip()) not in running
    ]
    return "\n".join(kept)


def summarize(text: str, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Leading sentences, truncated at the last sentence boundary before limit."""
    collapsed = re.sub(r"\s+", " ", text or "").strip()
    if len(collapsed) <= limit:
        return collapsed
    window = collapsed[:limit]
    boundaries = list(SENTENCE_END.finditer(window))
    if boundaries:
        return window[: boundaries[-1].start()].strip()
    return window.rsplit(" ", 1)[0].strip()


def _dates_in(text: str) -> set:
    found = set()
    for year, month, day in ISO_DATE.findall(text or ""):
        found.add(f"{year}-{month}-{day}")
    for name, day, year in TEXT_DATE.findall(text or ""):
        month = MONTH_NAMES.index(name.casefold()) + 1
        found.add(f"{year}-{month:02d}-{int(day):02d}")
    return found


def own_deadline_for(span_text: str, parent_deadline: str | None) -> str | None:
    """Advisory per-span deadline, or None (§5.5, §6.5).

    Set only when exactly one unambiguous date occurs in the span and it does
    not contradict the parent's structured deadline. Two dates is ambiguous;
    zero is nothing; one that disagrees with the parent is a conflict this
    module refuses to adjudicate.
    """
    dates = _dates_in(span_text)
    if len(dates) != 1:
        return None
    only = next(iter(dates))
    if parent_deadline and only != str(parent_deadline)[:10]:
        return None
    return only


def program_area_fields(span_text: str):
    """(labels, topic_areas) from the two real controlled vocabularies (§6.5).

    A span is a far better input to this vocabulary than a whole notice:
    extract_program_areas currently attributes 'catalysis' to an entire
    200-page BAA because the word appears once on page 147. Run against a
    4-page span, the same vocabulary says which topic area is the catalysis one.
    """
    labels = [
        label
        for label, _topics, pattern in program_areas.ENTRIES
        if pattern.search(span_text or "")
    ][:MAX_PROGRAM_AREA_LABELS]
    return tuple(labels), tuple(program_areas.topics_for(labels))


# --- Document text assembly -------------------------------------------------

# Tokenizer for the loose title matcher: alphanumeric runs, whitespace runs, and
# single other characters, in that precedence.
_LOOSE_TOKENS = re.compile(r"\w+|\s+|.", re.DOTALL | re.UNICODE)


@lru_cache(maxsize=2048)
def _loose_matcher(cleaned: str):
    """A pattern for `cleaned` that tolerates stray whitespace beside punctuation.

    Cov5. The previous version split the needle on whitespace and rejoined with
    `\\s+`, which tolerates whitespace *between* whitespace-delimited tokens and
    not *inside* one. Every span in the D5 cache whose excerpt described the
    wrong subject failed here, and all six failed the same way -- pdfminer emits
    a space adjacent to a hyphen or em-dash that the PDF bookmark does not have:

        bookmark  (i) X-Ray Scattering
        body      (i) X -Ray Scattering

        bookmark  (j) Plasma Science and Technology--General Plasma Science
        body      (j) Plasma Science and Technology-- General Plasma Science

    `X-Ray` is one token to `str.split()` and `X` / `-Ray` are two in the body,
    so no amount of `\\s+` between tokens bridges it. The title was then
    unlocatable, `_locate_nodes` fell back to `page_start_offset`, and the span
    began at the top of the bookmark's page -- inside the previous section's
    prose, which is what the summary then described.

    So whitespace becomes optional around every non-alphanumeric character.
    **This cannot match a different heading:** the alphanumeric runs must still
    appear in order and in full, case-insensitively, and the punctuation is
    preserved rather than wildcarded. The exact `str.find` fast path in `_find`
    runs first, so documents that already matched are unaffected.
    """
    atoms = []
    for token in _LOOSE_TOKENS.findall(cleaned):
        if token.isspace():
            atoms.append(("space", token))
        elif token.isalnum():
            atoms.append(("word", token))
        else:
            atoms.append(("punct", token))

    parts = []
    for index, (kind, token) in enumerate(atoms):
        first, last = index == 0, index == len(atoms) - 1
        if kind == "word":
            parts.append(re.escape(token))
        elif kind == "punct":
            # Optional whitespace on BOTH sides: extraction inserts it before a
            # hyphen (`X -Ray`) as readily as after an em-dash (`Technology— G`),
            # and the six measured cases include both directions.
            #
            # Never at the pattern's edges, though. A leading `\s*` makes
            # `re.search` start the match in the whitespace *before* the
            # heading, which moves the span start a few characters early --
            # enough that `build_subtopics`' "drop the heading line" step
            # consumes that whitespace instead of the heading, and every
            # summary then opens by repeating its own title.
            parts.append(("" if first else r"\s*") + re.escape(token))
            if not last and atoms[index + 1][0] == "word":
                parts.append(r"\s*")
        else:
            beside_punct = (
                (index and atoms[index - 1][0] == "punct")
                or (index + 1 < len(atoms) and atoms[index + 1][0] == "punct")
            )
            # A space the bookmark has may be absent from the body when it sits
            # next to punctuation, so it must be optional there too.
            parts.append(r"\s*" if beside_punct else r"\s+")
    return re.compile("".join(parts), re.IGNORECASE)


@dataclass(frozen=True)
class _Flat:
    """Container text concatenated once, with an offset index back to pages.

    `misses` records every heading this document could not locate, so a
    location failure is reportable rather than silent (**BUG-10**). It is a
    mutable field on a frozen dataclass on purpose: one list per
    `segment_document` call, created by `_flatten`, shared by every layer that
    call runs, and never global.
    """

    text: str
    spans: tuple          # (page, anchor, start, end) per container
    misses: list = field(default_factory=list)

    def record_miss(self, site, page, title):
        """A heading that could not be located. See BUG-10 in `_locate_nodes`."""
        self.misses.append({"site": site, "page": page,
                            "title": (title or "")[:120]})

    def locate(self, page, needle, search_from=0):
        """Offset of `needle`, preferring its own page, else anywhere after."""
        cleaned = re.sub(r"\s+", " ", needle or "").strip()
        if not cleaned:
            return None
        for lower, upper in self._windows(page, search_from):
            found = self._find(cleaned, lower, upper)
            if found is not None:
                return found
        return None

    def _windows(self, page, search_from):
        if page is not None:
            for container_page, _anchor, start, end in self.spans:
                if container_page == page:
                    yield (max(start, 0), end)
        yield (search_from, len(self.text))

    def _find(self, cleaned, lower, upper):
        window = self.text[lower:upper]
        direct = window.find(cleaned)
        if direct >= 0:
            return lower + direct
        # Whitespace in extracted PDF text is unreliable; retry loosely.
        match = _loose_matcher(cleaned).search(window)
        return lower + match.start() if match else None

    def page_at(self, offset):
        return self._container_at(offset, 0)

    def anchor_at(self, offset):
        return self._container_at(offset, 1)

    def _container_at(self, offset, position):
        """The container covering `offset`, or the last one starting before it.

        The newline joining two containers sits in no container's range, so an
        exact-containment test alone would fall through for the very offsets
        span boundaries land on -- and returning the document's LAST page for a
        boundary between pages 2 and 3 silently inflates every page_end.
        """
        found = None
        for entry in self.spans:
            start, end = entry[2], entry[3]
            if start <= offset < end:
                return entry[position]
            if start <= offset:
                found = entry[position]
        return found

    def page_start_offset(self, page):
        for container_page, _anchor, start, _end in self.spans:
            if container_page == page:
                return start
        return None

    def page_end_offset(self, page):
        """Offset just past the last character of `page`.

        Layer B needs where a table-of-contents page *ends*, not where it
        begins: candidates located inside the TOC sit after its start offset
        and would survive a `> page_start_offset` filter, which is the whole
        reason that filter exists.
        """
        for container_page, _anchor, _start, end in self.spans:
            if container_page == page:
                return end
        return None


def _flatten(containers) -> _Flat:
    parts, spans, cursor = [], [], 0
    for container in containers:
        text = container.get("text") or ""
        parts.append(text)
        spans.append(
            (container.get("page"), container.get("anchor"), cursor, cursor + len(text))
        )
        cursor += len(text) + 1        # +1 for the joining newline
    return _Flat("\n".join(parts), tuple(spans))


# --- Acceptance (§6.4) ------------------------------------------------------


@dataclass(frozen=True)
class OutlineNode:
    """One bookmark, with the ancestor chain needed to establish siblinghood."""

    level: int
    title: str
    page: int
    chain: tuple = ()

    @property
    def parent(self):
        return self.chain[-1] if self.chain else None

    @property
    def root(self):
        return self.chain[0] if self.chain else None


@dataclass(frozen=True)
class _Candidate:
    code: str
    ordinal: int
    ordinal_label: str
    title: str
    offset: int
    page: int | None
    anchor: str | None


def acceptance_failures(candidates, flat, toc_pages=(), family_type="ordinal"):
    """Every §6.4 rule this candidate set breaks. Empty tuple means accept.

    All rules must hold. Returning the full list rather than the first failure
    is deliberate: the package D histogram is only readable if a rejection
    names every reason it happened.

    `family_type` selects rule 2 (§6.4/§6.4a). An ordinal family answers "does
    this behave like an enumeration?" with its counter; a structural family has
    no counter, so the question is answered from the shape of the set instead.
    """
    structural = family_type == "structural"
    failures = []
    ordered = sorted(candidates, key=lambda item: item.offset)

    # 1. At least three candidates from a single family.
    if len(ordered) < MIN_CANDIDATES:
        failures.append("min_candidates")

    # 5. A ceiling, which guards against reference lists and form indexes.
    ceiling = STRUCTURAL_MAX_SIBLINGS if structural else MAX_CANDIDATES
    if len(ordered) > ceiling:
        failures.append("too_many_candidates")

    if not ordered:
        return tuple(failures)

    if structural:
        # §6.4a 2b. The quantitative replacement for "the ordinals count up":
        # a real topic list is made of comparable things, while an
        # administrative skeleton pairs a three-line contact block with a
        # forty-page application section.
        lengths = [end - start for start, end in _span_bounds(ordered, len(flat.text))]
        total = sum(lengths) or 1
        mean = statistics.fmean(lengths)
        deviation = statistics.pstdev(lengths)
        if mean and deviation / mean > STRUCTURAL_MAX_CV:
            failures.append("span_distribution")
        if max(lengths) / total > STRUCTURAL_MAX_SPAN_SHARE:
            failures.append("span_dominance")
    else:
        # 2. Ordinals monotonically increasing, allowing at most one gap.
        ordinals = [item.ordinal for item in ordered]
        steps = [later - earlier for earlier, later in zip(ordinals, ordinals[1:])]
        if any(step < 1 or step > MAX_ORDINAL_STEP for step in steps):
            failures.append("ordinal_sequence")

    # 3 and 4. Span lengths, and no overlap.
    bounds = _span_bounds(ordered, len(flat.text))
    if any(
        not MIN_SPAN_CHARS <= (end - start) <= MAX_SPAN_CHARS
        for start, end in bounds
    ):
        failures.append("span_length")
    if any(
        previous_end > next_start
        for (_s, previous_end), (next_start, _e) in zip(bounds, bounds[1:])
    ):
        failures.append("span_overlap")

    # 4 (page half). Page ranges contiguous: the next span may start on the
    # page the previous ended, or the one after it, but not further on.
    pages = [item.page for item in ordered]
    if all(page is not None for page in pages):
        page_ends = [flat.page_at(end - 1) for _start, end in bounds]
        for previous_end, next_start in zip(page_ends, pages[1:]):
            if previous_end is not None and next_start - previous_end > 1:
                failures.append("page_gap")
                break

    # 8. Announcement-furniture veto, applied to EVERY family. The backfill
    # showed this failure is not specific to structural sets: a `component`
    # match at Layer C produced `Monitoring, Evaluation, and Learning` just as
    # an outline set produced `1. NOFO Summary`. See PROCESS_VOCABULARY.
    tokens = [token for item in ordered for token in tokenize(item.title)]
    if tokens:
        process_rate = sum(
            1 for token in tokens if token in PROCESS_VOCABULARY
        ) / len(tokens)
        if process_rate >= PROCESS_TOKEN_MAX:
            failures.append("administrative_vocabulary")

    # 6. Candidates must not be confined to the table of contents.
    if toc_pages and all(
        item.page in toc_pages for item in ordered if item.page is not None
    ):
        failures.append("toc_confined")

    # 7. At least 60% carry a non-empty title after the code. Structural
    # families have no code, so this is subsumed by §6.4a 2c, applied at
    # selection time in _structural_titles_ok().
    if not structural:
        titled = sum(1 for item in ordered if item.title.strip())
        if titled < MIN_TITLED_RATIO * len(ordered):
            failures.append("missing_titles")

    return tuple(dict.fromkeys(failures))


def _span_bounds(ordered, total):
    """Character bounds per candidate, with the final span capped.

    Every span but the last is bounded by the next heading. The last one has no
    successor, so running it to end-of-document swallows everything that
    follows the topic list -- and a notice almost always continues with review
    criteria, submission instructions and appendices. On the DEPSCoR notice
    that made the final span 111,290 characters against §6.4 rule 3's 40,000
    ceiling, rejecting a document whose other seven spans were 1,941-6,364.
    Every notice whose list ends before the document does was unacceptable by
    construction, which is very nearly all of them.

    The cap comes from the siblings rather than a new constant: the last topic
    is a peer of the others and should be about as long, so it gets twice the
    median of its predecessors, clamped to rule 3's ceiling. That is §6.4a's
    "comparable things" reasoning applied one span earlier.
    """
    plain = []
    for position, candidate in enumerate(ordered):
        start = candidate.offset
        end = ordered[position + 1].offset if position + 1 < len(ordered) else total
        plain.append((start, min(end, total)))

    bounds = []
    for position, (start, end) in enumerate(plain):
        if position == len(plain) - 1 and len(plain) > 1:
            preceding = [stop - begin for begin, stop in plain[:-1]]
            allowance = max(
                MIN_SPAN_CHARS,
                min(MAX_SPAN_CHARS, int(2 * statistics.median(preceding))),
            )
            end = min(end, start + allowance)
        bounds.append((start, end))
    return bounds


# --- Span construction ------------------------------------------------------


def build_subtopics(candidates, flat, containers, parent_deadline=None):
    ordered = sorted(candidates, key=lambda item: item.offset)
    bounds = _span_bounds(ordered, len(flat.text))
    running = running_lines(containers)
    built = []
    for candidate, (start, end) in zip(ordered, bounds):
        raw = flat.text[start:end]
        cleaned = strip_running_lines(raw, running)
        # Drop the heading line itself from the summary, keeping it in the code.
        body = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        labels, topics = program_area_fields(cleaned)
        built.append(
            Subtopic(
                subtopic_code=candidate.code,
                subtopic_code_norm=normalize_code(candidate.code),
                subtopic_ordinal=candidate.ordinal,
                ordinal_label=candidate.ordinal_label,
                title=candidate.title[:MAX_TITLE_CHARS],
                title_fingerprint=title_fingerprint(candidate.title),
                summary=summarize(body),
                subtopic_terms=build_term_map(cleaned),
                page_start=candidate.page,
                page_end=flat.page_at(end - 1),
                anchor=candidate.anchor,
                char_start=start,
                char_end=end,
                program_area_labels=labels,
                topic_areas=topics,
                own_deadline=own_deadline_for(cleaned, parent_deadline),
            )
        )
    return tuple(built)


def _candidates_from(hits, flat, pages, anchors, start_at=0):
    """Turn pattern hits into positioned candidates, dropping unlocatable ones.

    `start_at` is a floor on where a candidate may be located. Layer B needs it
    set past the table of contents: the TOC lists every heading verbatim and
    comes first in the document, so a search from offset 0 finds the TOC copy
    of each title and never reaches the body copy. Filtering those out
    afterwards leaves nothing at all -- which is what happened before D0a.
    """
    candidates, cursor = [], start_at
    for hit in hits:
        page = pages[hit.index] if hit.index < len(pages) else None
        offset = flat.locate(page, hit.text, cursor)
        # BUG-10, second call site -- and this is the one that actually fires.
        # The register names `_locate_nodes`; §6.5 says the fallback "fires zero
        # times across the D5 corpus". Measured at P7.2 over 152 cached
        # documents: `_locate_nodes` never falls back, and THIS line fell back
        # six times, kept four guesses, and every one of the four was wrong --
        # the heading did not begin the page. None reached an accepted set on
        # that corpus, which was ranking luck rather than a guarantee.
        #
        # An ordinal hit that cannot be located is dropped, which is exactly
        # what the `offset < cursor` case below has always done, and §6.4
        # rule 2's ordinal test then sees the gap. §18.3's asymmetry says which
        # way to err: a missing subtopic costs one search, a misaligned one puts
        # the wrong subject on a card with a page anchor.
        if offset is None or offset < cursor:
            flat.record_miss("pattern_hit", page, hit.text)
            continue
        cursor = offset + 1
        candidates.append(
            _Candidate(
                code=hit.code,
                ordinal=hit.ordinal,
                ordinal_label=hit.ordinal_label,
                title=hit.title or _title_on_next_line(flat, offset),
                offset=offset,
                page=flat.page_at(offset) if page is None else page,
                anchor=anchors[hit.index] if hit.index < len(anchors) else None,
            )
        )
    return candidates


def _title_on_next_line(flat, offset):
    """Title for a code that sits alone on its own line (§6.5).

    §6.5 takes "text after the code on the heading line", which assumes the
    two share a line. Plenty of notices do not: ARPA-E SCALEUP writes

        CATEGORY 1:
        Advanced Energy Storage Systems

    so every title came back empty and §6.4 rule 7 rejected a set whose
    ordinals ran 1-7 cleanly with spans of 986-3,906 characters. Falling back
    to the next non-empty line recovers the title without touching any pattern.
    """
    window = flat.text[offset:offset + 600]
    parts = []
    for line in window.splitlines()[1:]:
        stripped = re.sub(r"\s+", " ", line).strip(" :.–—-")
        if not stripped:
            if parts:
                break
            continue
        if not parts:
            parts.append(stripped)
            # A title that arrives in normal case is one line and done.
            if any(character.islower() for character in stripped):
                break
            continue
        # An all-caps heading often wraps across several lines -- ARPA-E writes
        # "POWER / GENERATION AND / ENERGY / PRODUCTION" down four of them --
        # so keep joining while the lines are still shouting.
        if any(character.islower() for character in stripped):
            break
        parts.append(stripped)
        if sum(len(part) for part in parts) >= MAX_TITLE_CHARS:
            break
    return re.sub(r"\s+", " ", " ".join(parts)).strip()[:MAX_TITLE_CHARS]


# --- Layers (§6.2) ----------------------------------------------------------


def outline_nodes(items, reader, level=0, out=None, chain=()):
    """The outline walk, carrying each node's full ancestor chain.

    pypdf's reader.outline is a nested list: a Destination, or a list of
    children belonging to the Destination that preceded it.

    get_destination_page_number returns None when a page is not found -- it
    does NOT raise, whatever §6.2 used to say. See docs/PDF_API_NOTES.md §2.

    The chain is what the structural family needs. Equal depth does not
    establish siblinghood -- two level-2 nodes under different level-1 parents
    are not siblings -- and D2 measured that the *level-0* ancestor is what
    separates a program taxonomy from an administrative one, so the whole chain
    is kept rather than just the immediate parent.
    """
    out = [] if out is None else out
    last = chain
    for item in items:
        if isinstance(item, list):
            outline_nodes(item, reader, level + 1, out, last)
        elif isinstance(item, Destination):
            try:
                page_index = reader.get_destination_page_number(item)
            except Exception:            # noqa: BLE001 - malformed destination
                continue
            if page_index is None:       # not found; silently skipped by design
                continue
            title = str(item.title or "").strip()
            out.append(OutlineNode(level, title, page_index + 1, chain))
            last = chain + (title,)
    return out


def flatten_outline(items, reader):
    """`(level, title, page)` triples, the shape the ordinal pass consumes.

    Kept exactly as it was when package B tested it. The structural family's
    richer walk is `outline_nodes()`; this stays a thin adapter so adding the
    ancestor chain did not change an existing contract.
    """
    return [(node.level, node.title, node.page)
            for node in outline_nodes(items, reader)]


def _layer_outline(content, containers, flat, deadline, toc_pages):
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        entries = outline_nodes(reader.outline, reader)
    except Exception:                    # noqa: BLE001 - no outline, or broken
        return None
    if not entries:
        return None
    for level in sorted({node.level for node in entries}):
        if monotonic() > deadline:
            return None
        siblings = [node for node in entries if node.level == level]
        family, hits = best_family(node.title for node in siblings)
        if not family:
            continue
        pages = [node.page for node in siblings]
        candidates = _candidates_from(hits, flat, pages, [None] * len(pages))
        failures = acceptance_failures(candidates, flat, toc_pages)
        if not failures:
            return ("outline", "high", family, candidates)

    # §6.3a. Only after every ordinal family has declined at every level: a
    # label match is self-validating and a structural one is not, so the weaker
    # signal never pre-empts the stronger.
    return _structural_from_outline(entries, flat, toc_pages)


# --- §6.3a structural family ------------------------------------------------

# §6.4a thresholds. Every one of these was a reasoned starting point in the
# plan; the values here are the fitted ones, and where a value moved the
# measurement that moved it is named. See §6.4a and docs/CORPUS_CENSUS.md.
STRUCTURAL_MIN_SIBLINGS = 3
# Fitted 60 -> 100 (D2). Level 2 under `III. Program Description` in
# DE-FOA-0003600 is 77 nodes; at 60 the document falls back to 16 program-office
# children and `Catalysis Science` stops being its own record.
STRUCTURAL_MAX_SIBLINGS = 100
STRUCTURAL_MAX_CV = 1.5
STRUCTURAL_MAX_SPAN_SHARE = 0.40
STRUCTURAL_MIN_TITLED_RATIO = 0.6
STRUCTURAL_MIN_CONTENT_TOKENS = 2
# Fitted 0.6 -> 0.35, and §6.4a's reasoning for it was wrong. The claim was
# that administrative outlines repeat vocabulary while research programme lists
# do not. Measured across all 129 sibling sets in the census corpus: the
# ancestor-chain test already removes 111 of them, leaving 18 for this test to
# judge, and the LOWEST legitimate value among those is 0.383 -- DOE's High
# Energy Physics set, whose nine titles are "Experimental Research at the
# Energy / Intensity / Cosmic Frontier" and so legitimately share vocabulary.
# The 24-programme BES set is 0.597, also under the reasoned 0.6. A real
# scientific taxonomy reuses domain words by nature; type/token was measuring
# list size and domain coherence, not administrativeness. Kept at 0.35 only as
# a floor against degenerate repetition, no longer as a primary defence.
STRUCTURAL_MIN_TYPE_TOKEN = 0.35
STRUCTURAL_TITLE_CHARS = (12, 120)
STRUCTURAL_ADMIN_VETO = 0.25


def _admissible_parent(node):
    """§6.3a criterion 4, widened by D2 to the whole ancestor chain.

    The immediate parent is not enough. `C. Administrative and National Policy
    Requirements` matches no administrative term, and neither do most of its 40
    children -- but its level-0 ancestor is `IX. Other Information`, and that
    separates all 23 administrative sibling sets in DE-FOA-0003600 from the 10
    real ones. Structure, not vocabulary, as §6.3a intended.
    """
    if not node.chain:
        return False
    return not any(is_administrative(ancestor) for ancestor in node.chain)


def _structural_from_outline(entries, flat, toc_pages):
    """Sibling sets established by outline position, not by an ordinal."""
    by_depth = {}
    for node in entries:
        if node.level < 1:            # §6.3a criterion 1: depth 0 is never eligible
            continue
        if not _admissible_parent(node):
            continue
        by_depth.setdefault(node.level, []).append(node)

    # §6.3a depth selection, corrected by D2: the admissible depth carrying the
    # MOST nodes, not the deepest. Under `III. Program Description` level 3
    # holds 3 nodes and would otherwise beat level 2's 77.
    for depth in sorted(by_depth, key=lambda d: (-len(by_depth[d]), -d)):
        nodes = by_depth[depth]
        if not STRUCTURAL_MIN_SIBLINGS <= len(nodes) <= STRUCTURAL_MAX_SIBLINGS:
            continue
        # §6.4a 2d: each contributing parent must itself hold a real set.
        per_parent = {}
        for node in nodes:
            per_parent.setdefault(node.parent, []).append(node)
        if any(len(group) < STRUCTURAL_MIN_SIBLINGS for group in per_parent.values()):
            nodes = [
                node
                for node in nodes
                if len(per_parent[node.parent]) >= STRUCTURAL_MIN_SIBLINGS
            ]
        if not STRUCTURAL_MIN_SIBLINGS <= len(nodes) <= STRUCTURAL_MAX_SIBLINGS:
            continue
        if not _structural_titles_ok([node.title for node in nodes]):
            continue

        # BUG-10 and §6.4a rule 2a together. Every node of the chosen sibling
        # set must be locatable; one that is not makes the set INCOMPLETE, and
        # rule 2a says an incomplete set is rejected rather than trimmed. The
        # previous code filtered `offset is None` out of the list, which
        # emitted a trimmed set as though it were the whole one -- and before
        # that the offset would have been guessed instead of missing at all.
        located = list(_locate_nodes(nodes, flat))
        if any(offset is None for _node, offset in located):
            continue
        candidates = [
            _Candidate(
                code=node.title,
                ordinal=index + 1,
                ordinal_label=str(index + 1),
                title=node.title,
                offset=offset,
                page=node.page,
                anchor=None,
            )
            for index, (node, offset) in enumerate(located)
        ]
        if len(candidates) < STRUCTURAL_MIN_SIBLINGS:
            continue
        candidates = _trim_to_dominant_form(candidates)
        failures = acceptance_failures(
            candidates, flat, toc_pages, family_type="structural"
        )
        if not failures:
            return ("outline_structural", "medium", STRUCTURAL_FAMILY, candidates)
    return None


def _locate_nodes(nodes, flat):
    """Locate each bookmark title in the body text, in document order.

    **BUG-10, closed in P7.2. There is no substitute offset any more.**

    This function used to fall back to `flat.page_start_offset(node.page)` when
    a title could not be located, and that guess was indistinguishable from a
    real location downstream: `candidate.offset` sets the span's `char_start`,
    the *previous* sibling's `char_end`, the page range, the excerpt the
    summary is cut from, the text Cov4 classifies -- and, where a code sits
    alone on its line, the title itself through `_title_on_next_line`, and
    therefore `title_fingerprint` and identity. Cov5 measured what that costs:
    six spans in `360678` opened at the top of a page, inside the previous
    section's prose, and both consumers read the wrong subject (§6.5).

    Cov5 fixed the *cause* of those six failures (the loose title matcher) and
    left the fallback in place, recording it as the residual risk. P7.2 removes
    it, because a guessed offset is not evidence and nothing downstream can
    tell that it was guessed.

    Yielding ``None`` is what the caller acts on, and for a structural set the
    answer is fixed by **§6.4a rule 2a** -- *"a set that is missing siblings is
    rejected rather than trimmed"* -- so `_structural_from_outline` refuses the
    whole depth. That is an existing rule, not a new policy.
    """
    cursor = 0
    for node in sorted(nodes, key=lambda item: item.page):
        offset = flat.locate(node.page, node.title, cursor)
        if offset is None or offset < cursor:
            flat.record_miss("outline_node", node.page, node.title)
            yield node, None
            continue
        cursor = offset + 1
        yield node, offset


# Leading code forms a sibling set may share. A set that mostly shares one is
# an enumeration with stragglers; the stragglers are what follow the list.
_CODE_FORMS = (
    ("paren_letter", re.compile(r"^\([a-z]\)\s")),
    ("num_letter", re.compile(r"^\d+[a-z]\.\s")),
    ("dash_num", re.compile(r"^\d+\s*[-–—]\s")),
    ("labelled", re.compile(r"^[A-Z][a-z]+ [A-Z][a-z]+ \d+\.")),
    ("dot_num", re.compile(r"^\d+\.\s")),
    ("dot_letter", re.compile(r"^[A-Za-z]\.\s")),
    ("dotted", re.compile(r"^\d+\.\d+")),
)
# A form must cover this share of the set before its absentees are trimmed.
DOMINANT_FORM_SHARE = 0.6


def _trim_to_dominant_form(candidates):
    """Drop siblings that do not share the set's dominant leading code form.

    FITTED, not reasoned. After the set-level vocabulary veto, seven fabricated
    records survived inside otherwise-correct sets -- `Multi-Institutional
    Teams` and `Open Science` trailing DOE's 68 `(a)`-`(x)` programmes, and
    `Annual Meetings`, `Annual Progress Reports`, `Teaming Arrangements`,
    `Joint Consideration`, `Open Science` trailing Genesis's 21 `N -` challenge
    areas. A whole-set rate cannot catch 2 bad titles in 70 by construction.

    Measured across all 13 accepted documents of the 770-document backfill:

        361526   dash_num      21 coded, drops exactly the 5 known-bad
        360678   paren_letter  68 coded, drops exactly the 2 known-bad
        everything else        drops 0, or has no dominant form and is untouched

    7 of 7 contaminants removed, 0 legitimate records lost.

    This is a coherence rule, not the per-item vocabulary filter §6.3a warns
    against: it makes no judgement about what a title means, only about whether
    it carries the same code as its siblings, and it stays inert unless the set
    is mostly coded.
    """
    if len(candidates) < MIN_CANDIDATES:
        return candidates
    titles = [item.title for item in candidates]
    counts = {
        name: sum(1 for title in titles if pattern.match(title))
        for name, pattern in _CODE_FORMS
    }
    name, best = max(counts.items(), key=lambda item: item[1])
    if best < DOMINANT_FORM_SHARE * len(titles):
        return candidates
    pattern = dict(_CODE_FORMS)[name]
    kept = [item for item in candidates if pattern.match(item.title)]
    return kept if len(kept) >= MIN_CANDIDATES else candidates


def _structural_titles_ok(titles):
    """§6.4a 2c plus §6.3a's set-level administrative veto."""
    if not titles:
        return False
    administrative = sum(1 for title in titles if is_administrative(title))
    if administrative >= STRUCTURAL_ADMIN_VETO * len(titles):
        return False
    contentful = sum(
        1 for title in titles if len(tokenize(title)) >= STRUCTURAL_MIN_CONTENT_TOKENS
    )
    if contentful < STRUCTURAL_MIN_TITLED_RATIO * len(titles):
        return False
    tokens = [token for title in titles for token in tokenize(title)]
    if not tokens:
        return False
    if len(set(tokens)) / len(tokens) < STRUCTURAL_MIN_TYPE_TOKEN:
        return False
    low, high = STRUCTURAL_TITLE_CHARS
    median_length = statistics.median([len(title) for title in titles])
    return low <= median_length <= high


def detect_toc_pages(containers):
    """Pages whose dot-leader density makes them a table of contents."""
    horizon = max(3, int(0.15 * len(containers)))
    pages = set()
    for container in containers[:horizon]:
        leaders = sum(
            1
            for line in (container.get("text") or "").splitlines()
            if DOT_LEADER.match(line.strip())
        )
        if leaders >= TOC_MIN_LEADER_LINES and container.get("page") is not None:
            pages.add(container["page"])
    return pages


def _layer_toc(content, containers, flat, deadline, toc_pages):
    if not toc_pages:
        return None
    titles = []
    for container in containers:
        if container.get("page") not in toc_pages:
            continue
        for line in (container.get("text") or "").splitlines():
            found = DOT_LEADER.match(line.strip())
            if found:
                titles.append(found.group("title").strip())
    family, hits = best_family(titles)
    if not family:
        return None
    # The TOC's own page numbers are never trusted as boundaries; each title is
    # located verbatim in the body instead, outside the TOC page range. This is
    # the END of the last TOC page, not its start -- using the start left every
    # TOC candidate on the correct side of the filter meant to remove it, so
    # both the TOC copy and the body copy of each heading entered the candidate
    # list and the ordinal sequence restarted mid-set (§18.1 package D, D0a).
    body_start = max(
        (flat.page_end_offset(page) or 0) for page in toc_pages
    )
    candidates = _candidates_from(
        hits, flat, [None] * len(titles), [None] * len(titles),
        start_at=body_start,
    )
    # Belt and braces: the floor above should make this a no-op, but a title
    # that appears only inside the TOC must never become a span.
    candidates = [item for item in candidates if item.offset >= body_start]
    failures = acceptance_failures(candidates, flat, toc_pages)
    if failures:
        return None
    return ("toc", "high", family, candidates)


def page_lines(page, round_to=1):
    """Group page.chars into lines by rounded vertical position."""
    rows = {}
    for char in page.chars:
        rows.setdefault(round(char["top"] / round_to) * round_to, []).append(char)
    lines = []
    for top in sorted(rows):
        chars = sorted(rows[top], key=lambda item: item["x0"])
        text = "".join(item["text"] for item in chars).strip()
        if not text:
            continue
        lines.append(
            {
                "text": text,
                "size": statistics.median([item["size"] for item in chars]),
                "bold": sum(
                    bool(BOLD_RE.search(item.get("fontname") or "")) for item in chars
                )
                > len(chars) / 2,
            }
        )
    return lines


def _layer_headings(content, containers, flat, deadline, toc_pages):
    import pdfplumber                    # lazy: Layers A, B and D never pay for it

    all_lines, body_sizes = [], []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for index, page in enumerate(pdf.pages[:SUBTOPIC_CHAR_SCAN_PAGES], 1):
                if monotonic() > deadline:
                    return None          # budget spent; caller records the reason
                if index in toc_pages:   # §18.1 package D item D0b, as Layer D
                    page.flush_cache()
                    continue
                for line in page_lines(page):
                    body_sizes.append(line["size"])
                    all_lines.append((index, line))
                page.flush_cache()        # not optional on a 120-page document
    except Exception:                     # noqa: BLE001 - falls through to Layer D
        return None
    if not body_sizes:
        return None

    median = statistics.median(body_sizes)
    candidates_lines = [
        (page, line)
        for page, line in all_lines
        if (line["size"] >= HEADING_SIZE_RATIO * median or line["bold"])
        and len(line["text"]) <= MAX_HEADING_CHARS
    ]
    family, hits = best_family(line["text"] for _page, line in candidates_lines)
    if not family:
        return None
    pages = [page for page, _line in candidates_lines]
    candidates = _candidates_from(hits, flat, pages, [None] * len(pages))
    failures = acceptance_failures(candidates, flat, toc_pages)
    if failures:
        return None
    # `low`, not `medium`, and that is fitted rather than reasoned: across the
    # 770-document backfill Layer C produced exactly ONE accepted result and it
    # was wrong -- a `component` match yielding `Capacity Building`, `Strategic
    # Communications`, `Monitoring, Evaluation, and Learning`. 0/1 precision is
    # not enough to publish on, and low confidence never publishes (§13).
    return ("heading_font", "low", family, candidates)


def _layer_numbered(content, containers, flat, deadline, toc_pages):
    """Plain regex over container text, with no typographic signal at all.

    Low confidence never publishes (§13). It is recorded for diagnostics and
    routed to the review queue, and the §7.1 merge filters it out.
    """
    lines, pages, anchors = [], [], []
    for container in containers:
        # §18.1 package D item D0b. Table-of-contents pages list every heading
        # verbatim, so collecting them alongside the body puts two copies of
        # each candidate in one set: the ordinal sequence runs 1..n and then
        # restarts at 1, and the TOC copies are a few dozen characters long.
        # §6.4 rule 6 only rejects candidates *confined* to the TOC, so a mixed
        # set passes rule 6 and fails rules 2 and 3 instead -- which reads as a
        # pattern failure and is not one.
        if container.get("page") in toc_pages:
            continue
        for line in (container.get("text") or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lines.append(stripped)
            pages.append(container.get("page"))
            anchors.append(container.get("anchor"))
    family, hits = best_family(lines)
    if not family:
        return None
    candidates = _candidates_from(hits, flat, pages, anchors)
    failures = acceptance_failures(candidates, flat, toc_pages)
    if failures:
        return None
    return ("numbered", "low", family, candidates)


LAYERS = (_layer_outline, _layer_toc, _layer_headings, _layer_numbered)
HTML_LAYERS = (_layer_numbered,)


# --- Entry point ------------------------------------------------------------


def document_is_html(document) -> bool:
    kind = str((document or {}).get("content_type") or "").casefold()
    return "html" in kind


def segment_document(
    record,
    content,
    containers,
    document,
    *,
    parent_deadline=None,
    run_budget=None,
    clock=monotonic,
):
    """Segment one notice. Never raises; zero subtopics is a normal outcome.

    Returns a SegmentationResult carrying either the accepted subtopics or the
    reason there are none.
    """
    if run_budget is not None and run_budget.exhausted():
        return SegmentationResult.empty("run_budget")

    containers = list(containers or [])
    if not any((container.get("text") or "").strip() for container in containers):
        # Scanned or image-only. No OCR in v1.
        return SegmentationResult.empty("no_extractable_text")

    flat = _flatten(containers)
    toc_pages = detect_toc_pages(containers)
    deadline = clock() + SUBTOPIC_TIME_BUDGET_SECONDS
    is_html = document_is_html(document)
    layers = HTML_LAYERS if is_html else LAYERS

    attempted = []
    for layer in layers:
        if clock() > deadline:
            return SegmentationResult.empty(
                "time_budget", layers_attempted=tuple(attempted)
            )
        attempted.append(layer.__name__)
        try:
            outcome = layer(content, containers, flat, deadline, toc_pages)
        except Exception:                # noqa: BLE001 - never break the parent
            continue
        if not outcome:
            continue
        method, confidence, family, candidates = outcome
        subtopics = build_subtopics(candidates, flat, containers, parent_deadline)
        return SegmentationResult(
            subtopics=subtopics,
            method=method,
            confidence=confidence,
            family=family,
            diagnostics={
                "layers_attempted": tuple(attempted),
                "candidate_count": len(candidates),
                "toc_pages": tuple(sorted(toc_pages)),
                "extractor_version": extractor_version(),
                # BUG-10. A heading that could not be located no longer gets a
                # guessed offset, so the only thing left to do about it is to
                # say it happened. Zero on every accepted document measured so
                # far; a non-zero count on an accepted set means candidates were
                # dropped, which is a reason to read the document.
                "unlocated_headings": len(flat.misses),
            },
        )

    return SegmentationResult.empty(
        "no_layer_accepted", layers_attempted=tuple(attempted)
    )
