"""Enumerated-topic pattern families for subtopic segmentation.

A funding notice that contains a list of numbered topics almost always names
them with one of a small number of conventional labels: "Topic Area 3",
"Technical Area 2", "Research Thrust 1". This module recognizes those labels
and nothing else.

**The families are deliberately narrow, and loosening them is the most
damaging change anyone can make to this design** (docs/TOPIC_LAYER_PLAN.md
§18.3). Measured before any tuning (§6.3, docs/PDF_API_NOTES.md §4): the ONR
Long Range BAA, the AFOSR Open BAA and the ARPA-E SCALEUP NOFO match **zero**
families between them, because none of the three contains an enumerated topic
list. They contain administrative section structure -- 47, 19 and 74
decimal-numbered lines respectively, reading "1. Federal Agency Name",
"2. Funding Opportunity Title", "3. Announcement Type".

A generic numbered-section family would "fix" those three documents by
inventing subtopics from that. It would also put a plausible-looking card with
a page anchor and a deadline in front of a principal investigator, who may
spend weeks writing to a topic that does not exist. A missing subtopic costs
one search that could have gone better. Returning zero topics is the correct
outcome for a notice that has none.

See docs/TOPIC_LAYER_PLAN.md §6.3 for the family table and §6.4 for the
acceptance rules applied on top of these matches.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


# Ordinal kinds, naming how a family's captured group becomes a sort key.
_DECIMAL = "decimal"
_ALNUM = "alnum"          # "3a" -> 3, with the letter kept in the label
_ROMAN_OR_DECIMAL = "roman_or_decimal"
_LETTER_DECIMAL = "letter_decimal"   # NASA ROSES "B.7"

_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}


@dataclass(frozen=True)
class Family:
    """One enumerated-topic convention.

    ``pattern`` must capture the ordinal. ``title_group`` names the group
    holding the trailing title when the pattern captures it; when it is None
    the title is whatever follows the match on the same line.
    """

    identifier: str
    pattern: re.Pattern
    ordinal_kind: str
    agencies: tuple[str, ...]
    title_group: int | None = None


# Order matters: the first family that matches a line owns it. `research_thrust`
# precedes `thrust` because "Research Thrust 3" also satisfies `thrust`'s
# pattern, and letting the looser family claim it would split one real family's
# count across two, which is exactly what best_family()'s margin test then
# rejects. Specific before general, always.
FAMILIES: tuple[Family, ...] = (
    # Sub-lettered ordinals are real: DE-FOA-0003627 subdivides into Topic Area
    # 1a, 1b, 1c and 2. The previous `(\d{1,2})\b` could not match `1a` at all
    # -- \b fails between a digit and a letter -- so that notice yielded only
    # its single `Topic Area 2` mention, eleven times, and was rejected on
    # ordinal_sequence (census, D3).
    Family(
        "topic_area",
        re.compile(r"\bTopic\s+Area\s+(\d{1,2}[a-z]?)\b", re.IGNORECASE),
        _ALNUM,
        ("DOE EERE", "DOE FECM", "ARPA-E", "NETL"),
    ),
    # Observed in the census: DARPA MMoMA (HR001126S0013) enumerates Focus Area
    # 1-4. No family covered it.
    Family(
        "focus_area",
        re.compile(r"\bFocus\s+Area\s+(\d{1,2}[a-z]?)\b", re.IGNORECASE),
        _ALNUM,
        ("DARPA", "AFRL", "DoD"),
    ),
    # Observed in the census: CDC jg-26-0054 enumerates Component 1-5, each a
    # separately fundable activity with its own budget.
    Family(
        "component",
        re.compile(r"\bComponent\s+(\d{1,2})\s*[:.\u2013\u2014]", re.IGNORECASE),
        _DECIMAL,
        ("CDC", "HHS"),
    ),
    # Observed in the census: ARPA-E SCALEUP enumerates CATEGORY 1..7 as its
    # Technical Categories of Interest. Requires the trailing colon so ordinary
    # prose ("category 3 applicants") cannot match.
    Family(
        "technical_category",
        re.compile(r"\bCategory\s+(\d{1,2})\s*[:\u2013\u2014]", re.IGNORECASE),
        _DECIMAL,
        ("ARPA-E", "DOE"),
    ),
    Family(
        "thrust",
        re.compile(r"\bThrust\s+(?:Area\s+)?(\d{1,2})\b", re.IGNORECASE),
        _DECIMAL,
        ("DARPA", "ONR"),
    ),
    # `\bTopic` does not match inside "Subtopic" -- there is no word boundary
    # between "Sub" and "topic" -- so a subtopic-style heading cannot be stolen
    # by this family. The trailing punctuation class is what separates a real
    # DoD topic heading from a prose mention of "topic 3 of the announcement".
    Family(
        "dod_topic",
        re.compile(r"\bTopic\s+(\d{1,2})\s*[:.\u2013\u2014]", re.IGNORECASE),
        _DECIMAL,
        ("MURI", "ONR", "ARO"),
    ),
)

# --- Retired 2026-08-17, §6.3 -------------------------------------------------
#
# Seven families were retired on measurement, not on judgement. Run over the 170
# documents of `docs/FAMILY_TAXONOMY.md`'s stratified sample, and cross-checked
# against the census 20 and survey 40:
#
#   technical_area      0 fires in 170 documents, no validating record in 90
#   sbir_subtopic       0 fires
#   nsf_track           0 fires, including four NSF records read at full text
#   research_thrust     0 fires
#   priority_research   0 fires. 332894's heading is "Priority Research
#                       Thrusts", which `Direction|Opportunity|PRD` never
#                       matched -- its one apparent validator was imaginary
#   area_of_interest    1 fire, 0 real lists: an aggregating NETL agency page,
#                       carrying another opportunity's topics (§6.3b)
#   roses_element       6 fires, 0 real lists. Matched `A.1 BACKGROUND AND
#                       OBJECTIVES` across five revisions of one DOE Idaho FOA
#                       and `C.3 Budget Documents` in a DRL instructions file --
#                       the census's 332894 false positive reproduced on new
#                       documents, with no correct match anywhere in 90 records
#
# Five never fired; two were net-negative. Retirement is not deletion of the
# knowledge: each shape is recorded above and in §6.3, and any of them may
# return **with a validating document whose matched text is quoted** (§17.8).
# `roses_element` in particular has a reason to return if §18.2's NSPIRES
# deferral is resolved -- but ROSES is D⅝'s first structured source, and a
# `native` adapter does not need a regex.
#
# The ordinal machinery they used (`_LETTER_DECIMAL`, `_ROMAN_OR_DECIMAL`,
# `_roman_to_int`, `Family.title_group`) is deliberately left in place for the
# same reason.

FAMILIES_BY_ID = {family.identifier: family for family in FAMILIES}

# The eleventh family (§6.3a). It has no pattern: siblinghood is established by
# outline-tree position, so it lives in subtopic_segmentation where the tree is.
# Named here so best_family() callers and the diagnostics histogram share one
# vocabulary of family identifiers.
STRUCTURAL_FAMILY = "structural_siblings"

# Administrative vocabulary for §6.3a's set-level veto and for ancestor-chain
# admissibility.
#
# This is not an ad-hoc blocklist: it is the **standard federal announcement
# section vocabulary**, which is a published finite list rather than a guess.
# Every term here names a section or subsection the OMB announcement template
# prescribes, which is why matching one is evidence about a heading's ROLE
# rather than about its wording.
#
# Measured (D2, D1): applied to the immediate parent alone this catches none of
# the 23 administrative sibling sets in DE-FOA-0003600, which is why §6.3a's
# primary exclusion is the ancestor chain and this list is the secondary check.
# `restriction` and `other information` were added after D1 measured ARPA-E
# SCALEUP selecting the 13 children of `H. Funding Restrictions` -- Allowable
# Costs, Foreign Travel, Lobbying -- as if they were fundable topics.
ADMINISTRATIVE_TERMS = (
    "eligibility", "eligible", "submission", "submit", "application", "award",
    "review", "reporting", "contact", "deadline", "format", "certification",
    "appendix", "definitions", "acronym", "checklist", "registration",
    "register", "cost share", "cost sharing", "budget", "provisions",
    "clauses", "administrative", "how-to", "how to", "requirements",
    "compliance", "assurance", "restriction", "other information",
    "national policy", "post-award", "reference material",
)
ADMINISTRATIVE_RE = re.compile(
    "|".join(re.escape(term) for term in ADMINISTRATIVE_TERMS), re.IGNORECASE
)


def is_administrative(title: str) -> bool:
    return bool(ADMINISTRATIVE_RE.search(title or ""))

# Minimum candidates for a family to be considered at all (§6.4 rule 1).
MINIMUM_CANDIDATES = 3
# A family must beat the runner-up by this factor, or the set is mixed and is
# rejected rather than guessed (§6.3).
MARGIN = 2


@dataclass(frozen=True)
class PatternMatch:
    """One recognized heading.

    ``index`` is the position in the sequence handed to :func:`best_family`,
    so a caller that passed page-tagged lines can map back to a page without
    this module knowing anything about pages.
    """

    index: int
    text: str
    code: str
    ordinal: int
    ordinal_label: str
    title: str


def _roman_to_int(value: str) -> int | None:
    total = previous = 0
    for char in reversed(value.casefold()):
        current = _ROMAN_VALUES.get(char)
        if current is None:
            return None
        total = total - current if current < previous else total + current
        previous = max(previous, current)
    return total or None


def _ordinal_value(kind: str, match: re.Match) -> tuple[int, str] | None:
    """Return (sortable ordinal, label) for a match, or None if unparseable."""
    if kind == _DECIMAL:
        raw = match.group(1)
        return (int(raw), raw)
    if kind == _ALNUM:
        raw = match.group(1)
        digits = re.match(r"(\d+)([a-z]?)", raw, re.IGNORECASE)
        if not digits:
            return None
        return (int(digits.group(1)), raw)
    if kind == _ROMAN_OR_DECIMAL:
        raw = match.group(1)
        if raw.isdigit():
            return (int(raw), raw)
        value = _roman_to_int(raw)
        return None if value is None else (value, raw.upper())
    if kind == _LETTER_DECIMAL:
        letter, number = match.group(1).upper(), match.group(2)
        # Composite so A.1 < A.2 < B.1 sorts correctly. A run that crosses a
        # letter boundary produces a jump far larger than one, so §6.4 rule 2
        # rejects it -- see the roses_element note in §6.3. NASA ROSES is
        # deferred in §18.2, so no v1 corpus document is affected.
        return ((ord(letter) - ord("A") + 1) * 100 + int(number),
                f"{letter}.{number}")
    return None


def _title_after(text: str, match: re.Match, family: Family) -> str:
    if family.title_group is not None:
        candidate = match.group(family.title_group) or ""
    else:
        candidate = text[match.end():]
    # Strip the punctuation that separates a code from its title.
    candidate = re.sub(r"^[\s:.–—\-•)\]]+", "", candidate)
    return re.sub(r"\s+", " ", candidate).strip()[:200]


def match_family(family: Family, text: str, index: int = 0) -> PatternMatch | None:
    """Match one family against one line, or None."""
    found = family.pattern.search(text or "")
    if not found:
        return None
    parsed = _ordinal_value(family.ordinal_kind, found)
    if parsed is None:
        return None
    ordinal, label = parsed
    return PatternMatch(
        index=index,
        text=text,
        code=re.sub(r"\s+", " ", found.group(0)).strip(" :.–—"),
        ordinal=ordinal,
        ordinal_label=label,
        title=_title_after(text, found, family),
    )


def matches_for(family: Family, texts) -> tuple[PatternMatch, ...]:
    """Every match of one family, honouring the specific-family-wins order."""
    found = []
    for index, text in enumerate(texts):
        owner = _owning_family(text)
        if owner is not family:
            continue
        hit = match_family(family, text, index)
        if hit:
            found.append(hit)
    return tuple(found)


def _owning_family(text: str) -> Family | None:
    """The first family in FAMILIES order that matches, or None.

    One line belongs to exactly one family. Without this a heading like
    "Research Thrust 3" would be counted by both `research_thrust` and
    `thrust`, halving the apparent margin between them.
    """
    for family in FAMILIES:
        found = family.pattern.search(text or "")
        if found and _ordinal_value(family.ordinal_kind, found) is not None:
            return family
    return None


def best_family(texts) -> tuple[str | None, tuple[PatternMatch, ...]]:
    """The dominant family among ``texts``, or (None, ()) if there isn't one.

    Returns the family with the most matches, requiring a >=2x margin over the
    runner-up. A mixed set -- four "Topic Area" headings and three "Technical
    Area" headings in the same document -- is rejected rather than guessed,
    because whichever one won would silently drop the other's topics.
    """
    texts = list(texts)
    grouped: dict[str, list[PatternMatch]] = {}
    for index, text in enumerate(texts):
        family = _owning_family(text)
        if family is None:
            continue
        hit = match_family(family, text, index)
        if hit:
            grouped.setdefault(family.identifier, []).append(hit)

    if not grouped:
        return (None, ())

    ranked = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    winner_id, winner_hits = ranked[0]
    if len(winner_hits) < MINIMUM_CANDIDATES:
        return (None, ())
    if len(ranked) > 1:
        runner_up = len(ranked[1][1])
        if runner_up and len(winner_hits) < MARGIN * runner_up:
            return (None, ())
    return (winner_id, tuple(winner_hits))
