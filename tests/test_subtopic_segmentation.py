"""Segmentation tests: golden outputs, traps, rejections, idempotency.

Layer C is tested end to end through the real ``pdfplumber`` stack, using
PDFs built from base-14 fonts by tests/fixtures/minipdf.py. No PDF-generating
dependency is added anywhere -- see that module's docstring for why one is not
needed.

See docs/TOPIC_LAYER_PLAN.md §6.2-§6.5 and §18.1 item B3.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures.minipdf import build_pdf, containers_from, heading, line  # noqa: E402

from scripts import subtopic_patterns as patterns  # noqa: E402
from scripts import subtopic_segmentation as seg  # noqa: E402


PDF = {"content_type": "application/pdf"}
HTML = {"content_type": "text/html"}

# Long enough that every span clears the 200-character minimum in §6.4 rule 3.
BODY = (
    "This element supports fundamental studies of catalytic conversion, "
    "including operando characterization, reactor design, and the separation "
    "steps that follow. Awards support single investigators and small teams "
    "working on carbon capture and related chemistry at laboratory scale."
)


def body_for(subject):
    """Distinct body prose per page.

    Every page must differ, and must differ in WORDS rather than digits:
    running_lines() masks numbers to '#' before comparing, so bodies that vary
    only by a page number collapse to one repeated line and are correctly
    stripped as a running header. Identical bodies are likewise -- and
    correctly -- treated as boilerplate. Both were fixture bugs here before
    they were anything else.
    """
    return (
        f"This element supports fundamental studies of {subject}, including "
        f"operando characterization and reactor design relevant to {subject}. "
        f"Awards support single investigators and small teams pursuing "
        f"{subject} at laboratory scale, with catalytic chemistry throughout."
    )


def topic_pages(headings, intro="Program announcement overview."):
    """A front page plus one page per heading, each with distinct body text."""
    pages = [[heading("Overview"), line(intro), line(BODY)]]
    for text in headings:
        pages.append([heading(text), line(body_for(text))])
    return pages


class PatternFamilyTests(unittest.TestCase):
    def test_every_family_matches_its_own_convention(self):
        samples = {
            "topic_area": "Topic Area 3 Electrocatalysis",
            "focus_area": "Focus Area 3 Integrated Materials Analysis",
            "component": "Component 3: Rapid Response Activities",
            "technical_category": "Category 3: Building Efficiency",
            "dod_topic": "Topic 3: Quantum Sensing",
            "thrust": "Thrust 3 Materials",
        }
        self.assertEqual(
            set(samples), {family.identifier for family in patterns.FAMILIES}
        )
        for identifier, text in samples.items():
            with self.subTest(family=identifier):
                owner = patterns._owning_family(text)
                self.assertIsNotNone(owner, f"{text!r} matched no family")
                self.assertEqual(owner.identifier, identifier)

    def test_specific_families_win_over_general_ones(self):
        # "Subtopic 3" contains "topic 3", but \bTopic cannot match inside it,
        # so a subtopic-style heading is owned by nothing now that
        # sbir_subtopic is retired -- and must not leak to dod_topic.
        self.assertIsNone(patterns._owning_family("Subtopic 3: Fabrication"))

    def test_retired_families_match_nothing(self):
        """§6.3, retired 2026-08-17. Five never fired in 170 documents.

        These are the conventions the retired families recognised. Nothing may
        match them now: re-adding one requires a validating document with its
        matched text quoted (§17.8), not a synthetic fixture.
        """
        for text in [
            "Technical Area 3 Autonomy",
            "Subtopic 3a Membrane Fabrication",
            "Track 3 Design",
            "Priority Research Direction 3 Charge Transfer",
            "Area of Interest 3 Water Reuse",
            "B.3 Exoplanet Research Program",
        ]:
            with self.subTest(text=text):
                self.assertIsNone(patterns._owning_family(text))

    def test_retiring_research_thrust_did_not_widen_thrust(self):
        """Fm4. The retirement's side-effect, closed.

        `research_thrust` existed so `thrust` would not claim
        `Research Thrust N`. Retiring it briefly handed those lines over -- a
        match surface widened with no validating document, which §17.8 forbids.
        A negative lookbehind restores the boundary without re-adding a family
        that never fired.
        """
        self.assertIsNone(
            patterns._owning_family("Research Thrust 3 Interfacial Chemistry")
        )
        self.assertEqual(
            patterns._owning_family("Thrust 3 Materials").identifier, "thrust"
        )
        self.assertEqual(
            patterns._owning_family("Thrust Area 2 Sensing").identifier, "thrust"
        )

    def test_fm3_dod_topic_matches_a_letter_prefixed_ordinal(self):
        """Fm3. DTRA 356612 codes its seven fundable topics A1-A7."""
        hit = patterns.match_family(
            patterns.FAMILIES_BY_ID["dod_topic"],
            "Thrust Area 1, Topic A2: Exploring Quantum Computing Technology",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit.ordinal_label, "A2")
        self.assertEqual(hit.title, "Exploring Quantum Computing Technology")
        plain = patterns.match_family(
            patterns.FAMILIES_BY_ID["dod_topic"], "Topic 3: Quantum Sensing"
        )
        self.assertEqual((plain.ordinal, plain.ordinal_label), (3, "3"))

    def test_fm4_the_item_wins_the_line_not_the_container(self):
        """Fm4. The measured defect on DTRA 356612.

        Every fundable heading reads `Thrust Area 1, Topic AN: ...`. Before the
        repair `thrust` preceded `dod_topic`, owned all seven lines and emitted
        `Thrust Area 1` seven times with ordinal 1, which §6.4 rule 2 rejected.
        """
        headings = [f"Thrust Area 1, Topic A{n}: Title {n}" for n in range(1, 8)]
        self.assertEqual(
            patterns._owning_family(headings[0]).identifier, "dod_topic"
        )
        family, hits = patterns.best_family(headings)
        self.assertEqual(family, "dod_topic")
        self.assertEqual(len(hits), 7)
        self.assertEqual([hit.ordinal_label for hit in hits],
                         [f"A{n}" for n in range(1, 8)])
        ordinals = [hit.ordinal for hit in hits]
        self.assertEqual(ordinals, sorted(ordinals))
        self.assertEqual(len(set(ordinals)), 7)

    def test_roses_element_false_positive_shape_yields_no_child(self):
        """The measured false positive, pinned as a negative fixture.

        `roses_element` fired on six documents and zero real lists. Its shape
        was ordinary DoD/DOE lettered-decimal section numbering:
        `A.1 BACKGROUND AND OBJECTIVES` across five revisions of one DOE Idaho
        FOA, and `C.3 Budget Documents` in a DRL instructions file. This is
        kept as a **negative** regression fixture -- the previous positive
        fixture (`B.3 Exoplanet Research Program`) implied corpus support the
        family never had.
        """
        headings = [
            "A.1 BACKGROUND AND OBJECTIVES",
            "A.2 AWARD INFORMATION",
            "A.3 ELIGIBILITY INFORMATION",
            "C.3 Budget Documents",
        ]
        for text in headings:
            with self.subTest(text=text):
                self.assertIsNone(patterns._owning_family(text))
        self.assertEqual(patterns.best_family(headings), (None, ()))

        pages = topic_pages(headings)
        result = seg.segment_document(
            {}, build_pdf(pages), containers_from(pages), PDF
        )
        self.assertEqual(result.subtopics, ())
        self.assertEqual(result.reason, "no_layer_accepted")

    def test_administrative_section_headings_match_nothing(self):
        # Measured on three real notices (docs/PDF_API_NOTES.md §4): this is
        # what dominates a real BAA, and matching it would manufacture
        # subtopics titled "Federal Agency Name".
        for text in [
            "1. Federal Agency Name",
            "2. Funding Opportunity Title",
            "3. Announcement Type",
            "I. OVERVIEW INFORMATION",
            "A. PROGRAM DESCRIPTION",
            "IV. SUBMISSION REQUIREMENTS AND DEADLINES",
        ]:
            with self.subTest(text=text):
                self.assertIsNone(patterns._owning_family(text))

    def test_best_family_requires_a_margin_over_the_runner_up(self):
        topic = [f"Topic Area {n} Alpha" for n in range(1, 5)]
        focus = [f"Focus Area {n} Beta" for n in range(1, 4)]
        self.assertEqual(patterns.best_family(topic + focus), (None, ()))

        wide = [f"Topic Area {n} Alpha" for n in range(1, 7)]
        family, hits = patterns.best_family(wide + focus)
        self.assertEqual(family, "topic_area")
        self.assertEqual(len(hits), 6)

    def test_best_family_requires_three_candidates(self):
        self.assertEqual(
            patterns.best_family(["Topic Area 1 A", "Topic Area 2 B"]), (None, ())
        )

    def test_alphanumeric_ordinals_parse(self):
        # Roman-ordinal coverage retired with nsf_track; sub-lettered coverage
        # moves to topic_area, which is the family that measured a real one
        # (DE-FOA-0003627's Topic Area 1a/1b/1c).
        _family, hits = patterns.best_family(
            ["Topic Area 1a Alpha", "Topic Area 2b Beta", "Topic Area 3c Gamma"]
        )
        self.assertEqual([hit.ordinal_label for hit in hits], ["1a", "2b", "3c"])


class EveryFamilySegmentsTests(unittest.TestCase):
    """One built PDF per family, segmented end to end (§18.1 item B3)."""

    # family -> [(heading line, expected title, expected code)]
    CASES = {
        "topic_area": [
            ("Topic Area 1 Electrocatalysis", "Electrocatalysis", "Topic Area 1"),
            ("Topic Area 2 Membranes", "Membranes", "Topic Area 2"),
            ("Topic Area 3 Materials", "Materials", "Topic Area 3"),
        ],
        "focus_area": [
            ("Focus Area 1 Integrated Materials Analysis",
             "Integrated Materials Analysis", "Focus Area 1"),
            ("Focus Area 2 Surface Analysis", "Surface Analysis", "Focus Area 2"),
            ("Focus Area 3 Data Fusion", "Data Fusion", "Focus Area 3"),
        ],
        "component": [
            ("Component 1: Core Priorities", "Core Priorities", "Component 1"),
            ("Component 2: Rapid Response", "Rapid Response", "Component 2"),
            ("Component 3: Emerging Threats", "Emerging Threats", "Component 3"),
        ],
        "technical_category": [
            ("Category 1: Grid Storage", "Grid Storage", "Category 1"),
            ("Category 2: Transportation Fuels", "Transportation Fuels",
             "Category 2"),
            ("Category 3: Building Efficiency", "Building Efficiency",
             "Category 3"),
        ],
        "dod_topic": [
            ("Topic 1: Quantum Sensing", "Quantum Sensing", "Topic 1"),
            ("Topic 2: Autonomy", "Autonomy", "Topic 2"),
            ("Topic 3: Materials", "Materials", "Topic 3"),
        ],
        "thrust": [
            ("Thrust 1 Materials", "Materials", "Thrust 1"),
            ("Thrust 2 Devices", "Devices", "Thrust 2"),
            ("Thrust 3 Systems", "Systems", "Thrust 3"),
        ],
    }

    def test_one_pdf_per_family_segments_into_three_subtopics(self):
        self.assertEqual(
            set(self.CASES), {family.identifier for family in patterns.FAMILIES}
        )
        for identifier, rows in self.CASES.items():
            with self.subTest(family=identifier):
                headings = [row[0] for row in rows]
                pages = topic_pages(headings)
                result = seg.segment_document(
                    {}, build_pdf(pages), containers_from(pages), PDF
                )
                self.assertEqual(
                    result.family, identifier, f"{identifier}: {result.reason}"
                )
                self.assertEqual(len(result.subtopics), 3)
                self.assertEqual(
                    [item.title for item in result.subtopics],
                    [row[1] for row in rows],
                )
                self.assertEqual(
                    [item.subtopic_code for item in result.subtopics],
                    [row[2] for row in rows],
                )
                # roses_element uses a composite ordinal so A.1 < A.2 < B.1
                # sorts correctly; B.1-B.3 is therefore 201-203, not 1-3.
                expected = (
                    [201, 202, 203] if identifier == "roses_element" else [1, 2, 3]
                )
                self.assertEqual(
                    [item.subtopic_ordinal for item in result.subtopics], expected
                )
                self.assertEqual(
                    [item.ordinal_label for item in result.subtopics],
                    ["B.1", "B.2", "B.3"]
                    if identifier == "roses_element"
                    else [row[2].rsplit(maxsplit=1)[-1] for row in rows],
                )

    def test_each_family_also_segments_from_a_real_bookmark_tree(self):
        for identifier, rows in self.CASES.items():
            headings = [row[0] for row in rows]
            with self.subTest(family=identifier):
                pages = topic_pages(headings)
                outline = [
                    (text, index + 1, 0) for index, text in enumerate(headings)
                ]
                result = seg.segment_document(
                    {}, build_pdf(pages, outline=outline), containers_from(pages), PDF
                )
                self.assertEqual(result.method, "outline")
                self.assertEqual(result.confidence, "high")
                self.assertEqual(result.family, identifier)


class LayerOutlineTests(unittest.TestCase):
    def test_bookmarked_notice_segments_at_high_confidence(self):
        headings = [
            "Topic Area 1 Electrocatalysis",
            "Topic Area 2 Membrane Separations",
            "Topic Area 3 Materials Discovery",
        ]
        pages = topic_pages(headings)
        outline = [("Overview", 0, 0)] + [
            (text, index + 1, 0) for index, text in enumerate(headings)
        ]
        result = seg.segment_document(
            {}, build_pdf(pages, outline=outline), containers_from(pages), PDF
        )
        self.assertEqual(result.method, "outline")
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.family, "topic_area")
        self.assertEqual(len(result.subtopics), 3)
        self.assertEqual(
            [item.subtopic_ordinal for item in result.subtopics], [1, 2, 3]
        )
        self.assertEqual(
            [item.page_start for item in result.subtopics], [2, 3, 4]
        )

    def test_outline_page_numbers_are_one_based(self):
        pages = topic_pages(["Topic Area 1 A", "Topic Area 2 B", "Topic Area 3 C"])
        outline = [("Topic Area 1 A", 1, 0)]
        from pypdf import PdfReader
        import io

        reader = PdfReader(io.BytesIO(build_pdf(pages, outline=outline)), strict=False)
        flattened = seg.flatten_outline(reader.outline, reader)
        # Page index 1 is the second page, which is page 2 in this repository.
        self.assertEqual(flattened, [(0, "Topic Area 1 A", 2)])

    def test_nesting_depth_becomes_the_level(self):
        pages = topic_pages(["Topic Area 1 A", "Topic Area 2 B"])
        outline = [("Parent", 0, 0), ("Child", 0, 1), ("Topic Area 1 A", 1, 0)]
        from pypdf import PdfReader
        import io

        reader = PdfReader(io.BytesIO(build_pdf(pages, outline=outline)), strict=False)
        levels = {title: level for level, title, _page in
                  seg.flatten_outline(reader.outline, reader)}
        self.assertEqual(levels["Parent"], 0)
        self.assertEqual(levels["Child"], 1)

    def test_a_destination_returning_none_is_skipped_not_raised(self):
        class Reader:
            def get_destination_page_number(self, _destination):
                return None       # pypdf's real behaviour; it does not raise

        from pypdf.generic import Destination, Fit, NullObject, TextStringObject

        destination = Destination(
            TextStringObject("Topic Area 1 A"), NullObject(), Fit.fit()
        )
        self.assertEqual(seg.flatten_outline([destination], Reader()), [])

    def test_a_space_beside_punctuation_does_not_detach_the_span(self):
        """Cov5. The measured cause of every misaligned summary in the D5 cache.

        pdfminer emits a space adjacent to a hyphen or em-dash that the PDF
        bookmark does not carry -- bookmark `(i) X-Ray Scattering`, body
        `(i) X -Ray Scattering`. The loose title matcher used to split the
        needle on whitespace and rejoin with `\\s+`, which bridges whitespace
        BETWEEN tokens and not INSIDE one, so the title was unlocatable, the
        candidate fell back to `page_start_offset`, and the span began at the
        top of the page -- inside the previous section's prose. Six of 360678's
        68 spans were built that way, including `(i) X-Ray Scattering`, whose
        summary read "Applications submitted by February 1, 2026...".

        The assertion is on the summary, not on the offset, because the summary
        is what both consumers actually read (§6.5).
        """
        # Body headings carry the stray space; bookmarks do not. The em-dash
        # direction (`Technology— General`) is covered in the matcher test
        # below rather than here: tests/fixtures/minipdf.py writes objects as
        # latin-1, so U+2014 cannot go into a bookmark title in a fixture PDF.
        body_headings = [
            "Topic Area 1 X -Ray Scattering",
            "Topic Area 2 Public -Private Partnerships",
            "Topic Area 3 Cross- Cutting Microelectronics",
        ]
        bookmark_titles = [
            "Topic Area 1 X-Ray Scattering",
            "Topic Area 2 Public-Private Partnerships",
            "Topic Area 3 Cross-Cutting Microelectronics",
        ]
        pages = topic_pages(body_headings)
        outline = [("Overview", 0, 0)] + [
            (title, index + 1, 0) for index, title in enumerate(bookmark_titles)
        ]
        result = seg.segment_document(
            {}, build_pdf(pages, outline=outline), containers_from(pages), PDF
        )
        self.assertEqual(len(result.subtopics), 3)
        # Each span must describe its OWN subject. body_for() writes the heading
        # text into the prose, so a detached span shows a neighbour's subject.
        for subject, span in zip(body_headings, result.subtopics):
            self.assertIn(
                subject.split(" ", 3)[-1].casefold(),
                span.summary.casefold(),
                f"span {span.title!r} was handed text describing something else",
            )

    def test_loose_matcher_still_rejects_a_different_heading(self):
        """The Cov5 fix must not make the matcher promiscuous.

        Whitespace becomes optional around punctuation; the alphanumeric runs
        must still appear in order and in full. Without this, a looser matcher
        would let one sibling's title locate onto another's heading, which
        silently mislabels a span rather than merely misaligning it.
        """
        matcher = seg._loose_matcher("(q) Catalysis Science")
        self.assertIsNotNone(matcher.search("(q) Catalysis  Science"))
        self.assertIsNotNone(matcher.search("(q)Catalysis Science"))
        self.assertIsNone(matcher.search("(r) Separation Science"))
        # Both em-dash directions, measured on 360678's (j), (k) and (l).
        dash = seg._loose_matcher("Plasma Science and Technology—High Energy")
        self.assertIsNotNone(
            dash.search("(k) Plasma Science and Technology —High Energy"))
        self.assertIsNotNone(
            dash.search("(k) Plasma Science and Technology— High Energy"))
        self.assertIsNone(
            dash.search("(l) Plasma Science and Technology—Microelectronics"))
        self.assertIsNone(seg._loose_matcher("Nuclear Data").search(
            "Nuclear Physics Computing"))
        self.assertIsNone(seg._loose_matcher("Applied Mathematics").search(
            "Applied Mathematical Sciences"))

    def test_bookmarkless_notice_falls_through_to_a_later_layer(self):
        headings = [
            "Topic Area 1 Electrocatalysis",
            "Topic Area 2 Membrane Separations",
            "Topic Area 3 Materials Discovery",
        ]
        pages = topic_pages(headings)
        result = seg.segment_document(
            {}, build_pdf(pages), containers_from(pages), PDF
        )
        self.assertEqual(len(result.subtopics), 3)
        self.assertNotEqual(result.method, "outline")


class LayerHeadingFontTests(unittest.TestCase):
    def test_bold_headings_are_detected_through_pdfplumber(self):
        import io

        import pdfplumber

        pages = [[heading("Topic Area 1 Electrocatalysis"), line("Body prose.")]]
        with pdfplumber.open(io.BytesIO(build_pdf(pages))) as pdf:
            lines = seg.page_lines(pdf.pages[0])

        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0]["bold"], "bold heading was not detected")
        self.assertFalse(lines[1]["bold"], "body prose was reported as bold")
        self.assertGreater(lines[0]["size"], lines[1]["size"])

    def test_base14_fonts_yield_real_font_names(self):
        import io

        import pdfplumber

        pages = [[heading("Bold heading"), line("Regular body")]]
        with pdfplumber.open(io.BytesIO(build_pdf(pages))) as pdf:
            names = {char["fontname"] for char in pdf.pages[0].chars}
        self.assertIn("Helvetica-Bold", names)
        self.assertIn("Helvetica", names)

    def test_layer_c_segments_when_only_weight_distinguishes_headings(self):
        # The AFOSR case: headings set at body size, distinguished only by
        # weight. Measured at 0.0% of lines admitted by the size branch.
        headings = [
            "Topic Area 1 Electrocatalysis",
            "Topic Area 2 Membrane Separations",
            "Topic Area 3 Materials Discovery",
        ]
        pages = [[heading("Overview", size=11), line(BODY)]]
        for text in headings:
            pages.append([heading(text, size=11), line(BODY)])

        result = seg.segment_document(
            {}, build_pdf(pages), containers_from(pages), PDF
        )
        self.assertEqual(len(result.subtopics), 3)
        self.assertEqual(result.family, "topic_area")


class TrapTests(unittest.TestCase):
    def test_a_table_of_contents_alone_yields_nothing(self):
        toc = [line("Table of Contents")] + [
            line(f"Topic Area {n} Something ........... {n + 2}") for n in range(1, 8)
        ]
        pages = [toc, [heading("Body"), line(BODY)], [heading("More"), line(BODY)]]
        result = seg.segment_document(
            {}, build_pdf(pages), containers_from(pages), PDF
        )
        self.assertEqual(result.subtopics, ())
        self.assertEqual(result.reason, "no_layer_accepted")

    def test_toc_pages_are_detected(self):
        toc = [line("Table of Contents")] + [
            line(f"Topic Area {n} Something ........... {n + 2}") for n in range(1, 8)
        ]
        pages = [toc, [heading("Body"), line(BODY)]]
        self.assertEqual(seg.detect_toc_pages(containers_from(pages)), {1})

    def test_a_reference_list_is_rejected_by_the_candidate_cap(self):
        references = [
            line(f"[{n}] Author {n}, Thrust {n} of the prior program, 2021.")
            for n in range(1, 71)
        ]
        pages = [[heading("References")] + references]
        result = seg.segment_document(
            {}, build_pdf(pages), containers_from(pages), PDF
        )
        self.assertEqual(result.subtopics, ())

    def test_headings_crammed_on_one_page_fail_the_span_minimum(self):
        crammed = [line(f"Topic Area {n} Short") for n in range(1, 6)]
        pages = [[heading("Overview"), line(BODY)], crammed]
        result = seg.segment_document(
            {}, build_pdf(pages), containers_from(pages), PDF
        )
        self.assertEqual(result.subtopics, ())


class AcceptanceRuleTests(unittest.TestCase):
    """Each of the seven §6.4 rules, rejected in isolation."""

    def _candidates(self, ordinals, spacing=400, page_of=None, title="Alpha"):
        return [
            seg._Candidate(
                code=f"Topic Area {ordinal}",
                ordinal=ordinal,
                ordinal_label=str(ordinal),
                title=title,
                offset=index * spacing,
                page=(page_of(index) if page_of else index + 1),
                anchor=None,
            )
            for index, ordinal in enumerate(ordinals)
        ]

    def _flat(self, pages=6, size=400):
        containers = [
            {"page": n + 1, "section": None, "anchor": None, "text": "x" * (size - 1)}
            for n in range(pages)
        ]
        return seg._flatten(containers)

    def test_rule_1_fewer_than_three_candidates(self):
        failures = seg.acceptance_failures(self._candidates([1, 2]), self._flat())
        self.assertIn("min_candidates", failures)

    def test_rule_2_ordinals_must_increase(self):
        failures = seg.acceptance_failures(
            self._candidates([1, 3, 2]), self._flat()
        )
        self.assertIn("ordinal_sequence", failures)

    def test_rule_2_allows_one_gap_but_not_two(self):
        self.assertNotIn(
            "ordinal_sequence",
            seg.acceptance_failures(self._candidates([1, 3, 5]), self._flat()),
        )
        self.assertIn(
            "ordinal_sequence",
            seg.acceptance_failures(self._candidates([1, 4, 7]), self._flat()),
        )

    def test_rule_3_spans_must_be_long_enough(self):
        failures = seg.acceptance_failures(
            self._candidates([1, 2, 3], spacing=50), self._flat()
        )
        self.assertIn("span_length", failures)

    def test_rule_3_spans_must_not_be_enormous(self):
        flat = self._flat(pages=200, size=1000)
        failures = seg.acceptance_failures(
            self._candidates([1, 2, 3], spacing=60_000, page_of=lambda i: i + 1), flat
        )
        self.assertIn("span_length", failures)

    def test_rule_5_too_many_candidates(self):
        failures = seg.acceptance_failures(
            self._candidates(list(range(1, 70)), spacing=400),
            self._flat(pages=80),
        )
        self.assertIn("too_many_candidates", failures)

    def test_rule_6_candidates_confined_to_the_toc(self):
        failures = seg.acceptance_failures(
            self._candidates([1, 2, 3], page_of=lambda _index: 1),
            self._flat(),
            toc_pages={1},
        )
        self.assertIn("toc_confined", failures)

    def test_rule_7_most_candidates_need_a_title(self):
        failures = seg.acceptance_failures(
            self._candidates([1, 2, 3], title=""), self._flat()
        )
        self.assertIn("missing_titles", failures)

    def test_rule_8_rejects_announcement_furniture(self):
        # Fitted against the 770-document backfill: legitimate sets score
        # 0.000-0.008 on process vocabulary, furniture sets 0.133-0.889.
        furniture = [
            "1. NOFO Summary",
            "2. Funding Details",
            "A. Purpose",
            "B. Goals and Objectives",
            "C. Authority",
        ]
        candidates = [
            seg._Candidate(code=t, ordinal=i + 1, ordinal_label=str(i + 1),
                           title=t, offset=i * 400, page=i + 1, anchor=None)
            for i, t in enumerate(furniture)
        ]
        failures = seg.acceptance_failures(candidates, self._flat())
        self.assertIn("administrative_vocabulary", failures)

    def test_rule_8_leaves_real_topic_titles_alone(self):
        real = [
            "(q) Catalysis Science",
            "(r) Separation Science",
            "(a) Materials Chemistry",
            "(c) Synthesis and Processing Science",
            "(m) Gas Phase Chemical Physics",
        ]
        candidates = [
            seg._Candidate(code=t, ordinal=i + 1, ordinal_label=str(i + 1),
                           title=t, offset=i * 400, page=i + 1, anchor=None)
            for i, t in enumerate(real)
        ]
        failures = seg.acceptance_failures(candidates, self._flat())
        self.assertNotIn("administrative_vocabulary", failures)

    def test_trailing_uncoded_siblings_are_trimmed(self):
        # Fitted: DOE's 68 `(a)`-`(x)` programmes trailed by `Multi-
        # Institutional Teams` and `Open Science`; Genesis's 21 `N -` challenge
        # areas trailed by `Annual Meetings` and four more. A whole-set rate
        # cannot catch 2 bad titles in 70.
        titles = [f"({chr(97 + i)}) Subject {i}" for i in range(8)]
        titles += ["Multi-Institutional Teams", "Open Science"]
        candidates = [
            seg._Candidate(code=t, ordinal=i + 1, ordinal_label=str(i + 1),
                           title=t, offset=i * 400, page=i + 1, anchor=None)
            for i, t in enumerate(titles)
        ]
        kept = seg._trim_to_dominant_form(candidates)
        self.assertEqual(len(kept), 8)
        self.assertNotIn("Open Science", [c.title for c in kept])

    def test_a_set_with_no_dominant_form_is_left_alone(self):
        titles = ["GRID", "TRANSPORTATION", "BIOENERGY", "BUILDING EFFICIENCY"]
        candidates = [
            seg._Candidate(code=t, ordinal=i + 1, ordinal_label=str(i + 1),
                           title=t, offset=i * 400, page=i + 1, anchor=None)
            for i, t in enumerate(titles)
        ]
        self.assertEqual(len(seg._trim_to_dominant_form(candidates)), 4)

    def test_trimming_never_drops_below_the_minimum(self):
        titles = ["(a) One", "Uncoded two", "Uncoded three", "Uncoded four"]
        candidates = [
            seg._Candidate(code=t, ordinal=i + 1, ordinal_label=str(i + 1),
                           title=t, offset=i * 400, page=i + 1, anchor=None)
            for i, t in enumerate(titles)
        ]
        self.assertEqual(len(seg._trim_to_dominant_form(candidates)), 4)

    def test_a_clean_set_passes_every_rule(self):
        self.assertEqual(
            seg.acceptance_failures(self._candidates([1, 2, 3]), self._flat()), ()
        )

    def test_failures_are_reported_together_not_one_at_a_time(self):
        failures = seg.acceptance_failures(
            self._candidates([1, 3, 2], spacing=50, title=""), self._flat()
        )
        self.assertIn("ordinal_sequence", failures)
        self.assertIn("span_length", failures)
        self.assertIn("missing_titles", failures)


class DerivedFieldTests(unittest.TestCase):
    def test_running_headers_are_stripped(self):
        subjects = ["alpha", "beta", "gamma", "delta", "epsilon"]
        containers = [
            {"page": index, "section": None, "anchor": None,
             "text": f"DE-FOA-0003467 Page {index}\n"
                     f"Distinct prose concerning {subject} only.\n"
                     f"Footer line"}
            for index, subject in enumerate(subjects, start=1)
        ]
        running = seg.running_lines(containers)
        # The solicitation number varies only by page number, which the digit
        # mask collapses -- that is the point of masking.
        self.assertIn("DE-FOA-# Page #", running)
        self.assertIn("Footer line", running)
        # Genuinely distinct prose survives.
        for subject in subjects:
            self.assertNotIn(
                f"Distinct prose concerning {subject} only.", running
            )

    def test_short_pages_do_not_have_their_body_counted_twice(self):
        # §6.5's sketch counted lines[:3] + lines[-3:] directly, so on a page
        # of <=3 lines every line was counted twice. With three containers the
        # cutoff is 1.2, so a line appearing once per page scores 1 and is not
        # a header -- but scored 2 under the bug, and every line in the
        # document was stripped, leaving empty summaries and empty term maps.
        containers = [
            {"page": index, "section": None, "anchor": None,
             "text": f"Heading about {subject}\nBody prose about {subject}."}
            for index, subject in enumerate(["alpha", "beta", "gamma"], start=1)
        ]
        self.assertEqual(seg.running_lines(containers), set())

    def test_a_genuine_header_is_still_caught_on_short_pages(self):
        containers = [
            {"page": index, "section": None, "anchor": None,
             "text": f"SOLICITATION HEADER\nBody prose about {subject}."}
            for index, subject in enumerate(["alpha", "beta", "gamma"], start=1)
        ]
        self.assertEqual(seg.running_lines(containers), {"SOLICITATION HEADER"})

    def test_summary_truncates_at_a_sentence_boundary(self):
        text = ("First sentence here. " * 20) + "Trailing fragment without a stop"
        summary = seg.summarize(text, limit=100)
        self.assertLessEqual(len(summary), 100)
        self.assertTrue(summary.endswith("."), summary)

    def test_term_map_uses_the_catalog_tokenizer(self):
        from scripts.build_catalog import tokenize

        text = "Electrocatalysis of CO2 with catalytic membranes and membranes."
        terms = seg.build_term_map(text)
        self.assertEqual(set(terms), set(tokenize(text)))
        # Three-character terms must survive: co2 is exactly what this retrieves.
        self.assertIn("co2", terms)
        self.assertEqual(terms["membrane"], 2)

    def test_term_map_is_capped(self):
        text = " ".join(f"term{n}" for n in range(900))
        self.assertLessEqual(len(seg.build_term_map(text, max_terms=400)), 400)

    def test_program_areas_use_both_real_vocabularies(self):
        labels, topics = seg.program_area_fields(
            "Work on carbon capture and catalytic conversion of CO2."
        )
        self.assertIn("carbon management", labels)
        self.assertIn("catalysis", labels)
        self.assertIn("Carbon management", topics)
        self.assertIn("Catalysis and reaction engineering", topics)

    def test_own_deadline_only_when_a_single_unambiguous_date_appears(self):
        self.assertEqual(
            seg.own_deadline_for("Applications due September 30, 2026.", None),
            "2026-09-30",
        )
        self.assertIsNone(
            seg.own_deadline_for(
                "Concept papers due September 2, 2026 and full applications "
                "due September 30, 2026.",
                None,
            )
        )
        self.assertIsNone(seg.own_deadline_for("No dates at all here.", None))

    def test_own_deadline_defers_to_a_contradicting_parent(self):
        self.assertIsNone(
            seg.own_deadline_for("Due September 30, 2026.", "2026-11-15")
        )
        self.assertEqual(
            seg.own_deadline_for("Due September 30, 2026.", "2026-09-30"),
            "2026-09-30",
        )


class IdentityTests(unittest.TestCase):
    def test_normalize_code(self):
        self.assertEqual(seg.normalize_code("Topic Area 2"), "ta-2")
        self.assertEqual(seg.normalize_code("TOPIC AREA 2"), "ta-2")
        self.assertEqual(seg.normalize_code("Area of Interest 3"), "a-3")
        self.assertEqual(seg.normalize_code("Technical Area 11"), "ta-11")

    def test_title_fingerprint_is_word_order_insensitive(self):
        self.assertEqual(
            seg.title_fingerprint("Electrochemical CO2 Conversion"),
            seg.title_fingerprint("CO2 Conversion Electrochemical"),
        )
        self.assertNotEqual(
            seg.title_fingerprint("Electrochemical CO2 Conversion"),
            seg.title_fingerprint("Membrane Separations"),
        )

    def test_inserting_a_topic_does_not_renumber_the_rest(self):
        def record(code, title):
            return {
                "subtopic_code_norm": seg.normalize_code(code),
                "title": title,
                "title_fingerprint": seg.title_fingerprint(title),
            }

        old = [
            record("Topic Area 1", "Electrocatalysis"),
            record("Topic Area 2", "Membrane Separations"),
            record("Topic Area 3", "Materials Discovery"),
        ]
        # An amendment inserts a new Topic Area 2; everything below shifts down.
        new = [
            record("Topic Area 1", "Electrocatalysis"),
            record("Topic Area 2", "Direct Air Capture"),
            record("Topic Area 3", "Membrane Separations"),
            record("Topic Area 4", "Materials Discovery"),
        ]
        pairs = seg.match_subtopics(old, new)

        matched = {
            before["title"]: after["title"]
            for before, after in pairs
            if before and after
        }
        self.assertEqual(matched["Electrocatalysis"], "Electrocatalysis")
        self.assertEqual(matched["Membrane Separations"], "Membrane Separations")
        self.assertEqual(matched["Materials Discovery"], "Materials Discovery")

        added = [after for before, after in pairs if before is None]
        self.assertEqual([item["title"] for item in added], ["Direct Air Capture"])
        self.assertEqual([b for b, a in pairs if a is None], [])

    def test_a_retitled_topic_matches_by_fuzzy_title(self):
        old = [{"subtopic_code_norm": "ta-1",
                "title": "Electrochemical Conversion of Captured CO2",
                "title_fingerprint": "aaaaaaaa"}]
        new = [{"subtopic_code_norm": "ta-1",
                "title": "Electrochemical Conversion of Captured CO2 Streams",
                "title_fingerprint": "bbbbbbbb"}]
        pairs = seg.match_subtopics(old, new)
        self.assertEqual(len(pairs), 1)
        self.assertIsNotNone(pairs[0][0])
        self.assertIsNotNone(pairs[0][1])

    def test_a_genuinely_removed_topic_is_reported_as_removed(self):
        old = [{"subtopic_code_norm": "ta-9", "title": "Retired Area",
                "title_fingerprint": seg.title_fingerprint("Retired Area")}]
        pairs = seg.match_subtopics(old, [])
        self.assertEqual(pairs, [(old[0], None)])


class GoldenOutputTests(unittest.TestCase):
    def _segment(self):
        headings = [
            "Topic Area 1 Electrocatalysis for CO2 Reduction",
            "Topic Area 2 Membrane Separations and Water Reuse",
            "Topic Area 3 Materials Discovery",
        ]
        pages = topic_pages(headings)
        outline = [(text, index + 1, 0) for index, text in enumerate(headings)]
        return seg.segment_document(
            {}, build_pdf(pages, outline=outline), containers_from(pages), PDF
        )

    def test_golden_fields(self):
        result = self._segment()
        golden = [
            {
                "subtopic_code": "Topic Area 1",
                "subtopic_code_norm": "ta-1",
                "subtopic_ordinal": 1,
                "title": "Electrocatalysis for CO2 Reduction",
                "page_start": 2,
                "page_end": 2,
            },
            {
                "subtopic_code": "Topic Area 2",
                "subtopic_code_norm": "ta-2",
                "subtopic_ordinal": 2,
                "title": "Membrane Separations and Water Reuse",
                "page_start": 3,
                "page_end": 3,
            },
            {
                "subtopic_code": "Topic Area 3",
                "subtopic_code_norm": "ta-3",
                "subtopic_ordinal": 3,
                "title": "Materials Discovery",
                "page_start": 4,
                "page_end": 4,
            },
        ]
        actual = [
            {
                "subtopic_code": item.subtopic_code,
                "subtopic_code_norm": item.subtopic_code_norm,
                "subtopic_ordinal": item.subtopic_ordinal,
                "title": item.title,
                "page_start": item.page_start,
                "page_end": item.page_end,
            }
            for item in result.subtopics
        ]
        self.assertEqual(actual, golden)

    def test_every_subtopic_carries_a_usable_summary_and_terms(self):
        for item in self._segment().subtopics:
            with self.subTest(code=item.subtopic_code):
                self.assertTrue(item.summary.strip())
                self.assertLessEqual(len(item.summary), seg.MAX_SUMMARY_CHARS)
                # The body must reach the term map, not just the heading line.
                self.assertIn("operando", item.subtopic_terms)
                self.assertIn("catalytic", item.subtopic_terms)
                self.assertGreater(len(item.subtopic_terms), 10)

    def test_serialized_subtopic_stays_within_the_size_budget(self):
        import json

        for item in self._segment().subtopics:
            payload = json.dumps(
                {
                    "summary": item.summary,
                    "subtopic_terms": item.subtopic_terms,
                    "title": item.title,
                    "subtopic_code": item.subtopic_code,
                },
                separators=(",", ":"),
            )
            with self.subTest(code=item.subtopic_code):
                self.assertLessEqual(len(payload.encode("utf-8")), 2048)


class IdempotencyTests(unittest.TestCase):
    def test_segmenting_the_same_document_twice_is_identical(self):
        headings = [f"Topic Area {n} Area {n}" for n in range(1, 4)]
        pages = topic_pages(headings)
        content = build_pdf(pages)
        containers = containers_from(pages)

        first = seg.segment_document({}, content, containers, PDF)
        second = seg.segment_document({}, content, containers, PDF)
        self.assertEqual(first.subtopics, second.subtopics)
        self.assertEqual(first.method, second.method)

    def test_the_fixture_builder_is_byte_deterministic(self):
        pages = topic_pages(["Topic Area 1 A", "Topic Area 2 B", "Topic Area 3 C"])
        self.assertEqual(build_pdf(pages), build_pdf(pages))


class BudgetAndEdgeCaseTests(unittest.TestCase):
    def test_an_exhausted_run_budget_stops_before_any_work(self):
        class Spent:
            def exhausted(self):
                return True

        result = seg.segment_document(
            {}, b"", containers_from(topic_pages(["Topic Area 1 A"])), PDF,
            run_budget=Spent(),
        )
        self.assertEqual(result.reason, "run_budget")
        self.assertEqual(result.subtopics, ())

    def test_the_per_document_budget_ends_segmentation(self):
        ticks = [0.0]

        def clock():
            ticks[0] += 15.0
            return ticks[0]

        result = seg.segment_document(
            {}, b"", containers_from(topic_pages(["Topic Area 1 A"])), PDF,
            clock=clock,
        )
        self.assertEqual(result.reason, "time_budget")

    def test_run_budget_never_raises_when_exhausted(self):
        now = [0.0]
        budget = seg.RunBudget(seconds=600, clock=lambda: now[0])
        self.assertFalse(budget.exhausted())
        now[0] = 601.0
        self.assertTrue(budget.exhausted())
        self.assertEqual(budget.remaining(), 0.0)

    def test_a_scanned_document_reports_no_extractable_text(self):
        containers = [
            {"page": 1, "section": None, "anchor": None, "text": "   "},
            {"page": 2, "section": None, "anchor": None, "text": ""},
        ]
        result = seg.segment_document({}, b"", containers, PDF)
        self.assertEqual(result.reason, "no_extractable_text")

    def test_unreadable_bytes_never_raise(self):
        pages = topic_pages(["Topic Area 1 A"])
        result = seg.segment_document(
            {}, b"\x00\x01 not a pdf", containers_from(pages), PDF
        )
        self.assertEqual(result.subtopics, ())
        self.assertIsNotNone(result.reason)

    def test_an_ordinary_notice_with_no_topic_list_yields_nothing(self):
        pages = [
            [heading("I. OVERVIEW INFORMATION"), line(BODY)],
            [heading("II. BASIC INFORMATION"), line(BODY)],
            [heading("1. Federal Agency Name"), line(BODY)],
            [heading("2. Funding Opportunity Title"), line(BODY)],
        ]
        result = seg.segment_document(
            {}, build_pdf(pages), containers_from(pages), PDF
        )
        self.assertEqual(result.subtopics, ())
        self.assertEqual(result.reason, "no_layer_accepted")

    def test_html_notices_use_section_containers(self):
        containers = [
            {"page": None, "section": "Overview", "anchor": "overview",
             "text": "Program overview. " + BODY},
            {"page": None, "section": "Topic Area 1", "anchor": "ta1",
             "text": "Topic Area 1 Electrocatalysis\n" + BODY},
            {"page": None, "section": "Topic Area 2", "anchor": "ta2",
             "text": "Topic Area 2 Membranes\n" + BODY},
            {"page": None, "section": "Topic Area 3", "anchor": "ta3",
             "text": "Topic Area 3 Materials\n" + BODY},
        ]
        result = seg.segment_document({}, b"", containers, HTML)
        self.assertEqual(len(result.subtopics), 3)
        self.assertEqual(
            [item.anchor for item in result.subtopics], ["ta1", "ta2", "ta3"]
        )
        self.assertTrue(all(item.page_start is None for item in result.subtopics))

    def test_low_confidence_layer_is_labelled_as_such(self):
        containers = [
            {"page": n, "section": None, "anchor": None,
             "text": f"Topic Area {n} Area {n}\n{BODY}"}
            for n in range(1, 4)
        ]
        result = seg.segment_document({}, b"", containers, PDF)
        self.assertEqual(result.method, "numbered")
        self.assertEqual(result.confidence, "low")


class LocationFailureTests(unittest.TestCase):
    """BUG-10. A heading that cannot be located never gets a substitute offset.

    Cov5 found the damage and fixed its *cause*; the `page_start_offset`
    fallback survived and §6.5 recorded it as the residual. These tests exercise
    the fallback path **directly** rather than relying on a corpus that happens
    not to reach it -- which was the whole problem, and which was not even true:
    measured over 152 cached documents at P7.2, `_locate_nodes` never fell back
    and `_candidates_from` fell back six times, kept four guesses, and every one
    of the four was wrong.

    Each test asserts that the *old* fallback was reachable -- that
    `page_start_offset` would have returned a number -- so none of them can pass
    vacuously.
    """

    PROSE = (
        "This element supports fundamental studies of catalytic conversion and "
        "separation chemistry, including operando characterization and reactor "
        "design at laboratory scale, with awards to single investigators and "
        "small teams working across the relevant disciplines throughout. "
    )

    def _flat(self, headings):
        """One container per heading, each holding that heading and its prose."""
        containers = [
            {"page": index + 1, "section": None, "anchor": None,
             "text": f"{title}\n{self.PROSE}{title.split()[0]} recurs here."}
            for index, title in enumerate(headings)
        ]
        return seg._flatten(containers), containers

    # --- the ordinal call site, which is the one that actually fires ---------

    def test_an_unlocatable_pattern_hit_is_dropped_and_never_guessed(self):
        headings = ["Topic Area 1 Electrocatalysis",
                    "Topic Area 2 Photon Materials",
                    "Topic Area 3 Plasma Frontiers"]
        flat, _containers = self._flat(headings)
        # A fourth hit whose text is nowhere in the document -- the shape of a
        # prose line the extractor joined differently from the container copy.
        absent = "Topic Area 4 Ghost Programme That Was Never Extracted"
        hits = [
            patterns.match_family(patterns.FAMILIES_BY_ID["topic_area"], text, index)
            for index, text in enumerate(headings + [absent])
        ]
        self.assertTrue(all(hits))
        pages = [1, 2, 3, 3]

        # The removed fallback WAS reachable: page 3 has a start offset.
        self.assertIsNotNone(flat.page_start_offset(3))

        candidates = seg._candidates_from(hits, flat, pages, [None] * 4)
        self.assertEqual(len(candidates), 3)
        self.assertEqual([item.ordinal for item in candidates], [1, 2, 3])
        # Every surviving candidate sits exactly on its own heading.
        for candidate, title in zip(candidates, headings):
            self.assertTrue(
                flat.text[candidate.offset:].startswith(title),
                f"{candidate.title!r} was not located on its own heading",
            )
        self.assertEqual(
            [miss["site"] for miss in flat.misses], ["pattern_hit"]
        )
        self.assertIn("Ghost Programme", flat.misses[0]["title"])

    def test_a_locatable_hit_after_an_unlocatable_one_still_lands(self):
        """The drop must not consume the cursor or the siblings behind it."""
        headings = ["Topic Area 1 Electrocatalysis",
                    "Topic Area 2 Photon Materials",
                    "Topic Area 3 Plasma Frontiers"]
        flat, _containers = self._flat(headings)
        absent = "Topic Area 9 Ghost Programme Never Extracted Anywhere"
        texts = [headings[0], absent, headings[1], headings[2]]
        hits = [
            patterns.match_family(patterns.FAMILIES_BY_ID["topic_area"], text, index)
            for index, text in enumerate(texts)
        ]
        candidates = seg._candidates_from(hits, flat, [1, 1, 2, 3], [None] * 4)
        self.assertEqual([item.ordinal for item in candidates], [1, 2, 3])
        self.assertEqual(len(flat.misses), 1)

    # --- the structural call site, and §6.4a rule 2a -------------------------

    def _structural_fixture(self, ghost=None):
        """Four sibling programme titles, one per page, plus an intro page.

        Returns (entries, flat, containers). With `ghost` set, that title is
        given to the bookmark and NOT written into the body, so `locate` fails
        for exactly one node of an otherwise admissible set.
        """
        titles = [
            "Catalysis Science Research",
            "Photon Materials Chemistry",
            "Plasma Physics Frontiers",
            # NOT "Quantum Information Systems": `is_administrative` matches
            # the substring "format" inside "information", and one flagged
            # title in a four-item set already trips §6.3a's 0.25 set-level
            # administrative veto. A pre-existing quirk of the substring test,
            # noted rather than fixed here -- it is a false-NEGATIVE surface
            # and P7.2 is a punctuation-and-alignment repair.
            "Quantum Sensing Devices",
        ]
        body_titles = list(titles)
        if ghost is not None:
            body_titles[ghost] = "Some Other Heading Entirely Different"
        containers = [
            {"page": index + 1, "section": None, "anchor": None,
             "text": f"{title}\n{self.PROSE}{title.split()[0]} recurs here."}
            for index, title in enumerate(body_titles)
        ]
        flat = seg._flatten(containers)
        entries = [
            seg.OutlineNode(level=1, title=title, page=index + 1,
                            chain=("Program Description",))
            for index, title in enumerate(titles)
        ]
        return entries, flat, containers

    def test_a_fully_locatable_structural_set_is_admitted(self):
        """The control. Without it the rejection test below proves nothing."""
        entries, flat, _containers = self._structural_fixture()
        outcome = seg._structural_from_outline(entries, flat, set())
        self.assertIsNotNone(outcome, "the control set must be admitted")
        method, confidence, family, candidates = outcome
        self.assertEqual(method, "outline_structural")
        self.assertEqual(family, patterns.STRUCTURAL_FAMILY)
        self.assertEqual(len(candidates), 4)
        self.assertEqual(flat.misses, [])

    def test_one_unlocatable_sibling_rejects_the_whole_structural_set(self):
        """§6.4a rule 2a: a set missing a sibling is rejected, never trimmed.

        Before P7.2 this set came back with the missing node's offset GUESSED at
        the top of its page -- or, where the guess fell behind the cursor,
        trimmed to three siblings and emitted as though it were the whole list.
        """
        entries, flat, _containers = self._structural_fixture(ghost=2)
        # The removed fallback was reachable for that node.
        self.assertIsNotNone(flat.page_start_offset(3))
        self.assertIsNone(seg._structural_from_outline(entries, flat, set()))
        self.assertEqual([miss["site"] for miss in flat.misses], ["outline_node"])
        self.assertIn("Plasma Physics Frontiers", flat.misses[0]["title"])

    def test_locate_nodes_yields_none_rather_than_a_page_start(self):
        """The narrowest statement of the fix, on the function BUG-10 names."""
        entries, flat, _containers = self._structural_fixture(ghost=0)
        located = list(seg._locate_nodes(entries, flat))
        offsets = [offset for _node, offset in located]
        self.assertIsNone(offsets[0])
        self.assertNotIn(flat.page_start_offset(1), offsets)
        self.assertTrue(all(offset is not None for offset in offsets[1:]))

    # --- the drop is reportable, which is the other half of "not silent" ----

    def test_the_diagnostics_report_unlocated_headings(self):
        containers = [
            {"page": n, "section": None, "anchor": None,
             "text": f"Topic Area {n} Area {n}\n{BODY}"}
            for n in range(1, 4)
        ]
        result = seg.segment_document({}, b"", containers, PDF)
        self.assertEqual(len(result.subtopics), 3)
        self.assertEqual(result.diagnostics["unlocated_headings"], 0)

    def test_a_span_is_never_built_on_a_page_start_guess(self):
        """End to end: no accepted span may open at a page boundary it guessed.

        The assertion is on the text at `char_start`, because that is what both
        consumers read -- a guessed span opens inside the previous section's
        prose, which is exactly the Cov5 damage (§6.5).
        """
        headings = ["Topic Area 1 Electrocatalysis",
                    "Topic Area 2 Photon Materials",
                    "Topic Area 3 Plasma Frontiers"]
        pages = topic_pages(headings)
        result = seg.segment_document(
            {}, build_pdf(pages), containers_from(pages), PDF
        )
        self.assertEqual(len(result.subtopics), 3)
        self.assertEqual(result.diagnostics["unlocated_headings"], 0)
        flat = seg._flatten(containers_from(pages))
        for span, title in zip(result.subtopics, headings):
            # The span opens ON its heading. A guessed offset opens at the top
            # of the page instead, which on a real notice is the previous
            # section's prose -- the Cov5 damage (§6.5). Coinciding with a page
            # start is not itself the defect: in this fixture, as in most
            # notices, the heading legitimately begins its page.
            self.assertTrue(flat.text[span.char_start:].startswith(title))
            self.assertIn(span.title.split()[0].casefold(),
                          span.summary.casefold())



class DelimiterRepairTests(unittest.TestCase):
    """BUG-2. Three families rejected the ASCII hyphen; one also rejected `.`.

    A punctuation repair, and the tests are organised as a bounded equivalence
    class per family: everything that matched before must still match, the two
    newly authorised forms must match, and the family must still REQUIRE a
    delimiter -- which is the invariant §6.3 actually states, and which is what
    keeps `Category 3 applicants` out.

    Whitespace variants are only those a real notice prints. They are named per
    case rather than generalised into a permissive grammar.
    """

    #: Every delimiter the three repaired families accept, after BUG-2.
    DELIMITERS = (":", ".", "\u2013", "\u2014", "-")

    REPAIRED = {
        "dod_topic": ("Topic 1", "Aero-Structures"),
        "component": ("Component 1", "Core Global Health Security"),
        "technical_category": ("Category 1", "Advanced Energy Storage"),
    }

    def test_the_three_repaired_families_accept_the_same_five_delimiters(self):
        for identifier, (code, title) in self.REPAIRED.items():
            family = patterns.FAMILIES_BY_ID[identifier]
            for delimiter in self.DELIMITERS:
                for spacing in (f"{code}{delimiter} {title}",
                                f"{code} {delimiter} {title}"):
                    with self.subTest(family=identifier, text=spacing):
                        hit = patterns.match_family(family, spacing)
                        self.assertIsNotNone(hit, spacing)
                        self.assertEqual(hit.ordinal, 1)
                        self.assertEqual(hit.code, code)
                        self.assertEqual(hit.title, title)

    def test_the_delimiter_is_still_required(self):
        """The invariant §6.3 states, and the reason these families are narrow.

        Widening punctuation must not make the delimiter optional: without it,
        `category 3 applicants` becomes a subtopic.
        """
        for identifier, (code, title) in self.REPAIRED.items():
            with self.subTest(family=identifier):
                self.assertIsNone(
                    patterns.match_family(
                        patterns.FAMILIES_BY_ID[identifier], f"{code} {title}")
                )
        self.assertIsNone(patterns._owning_family("Category 3 applicants"))
        self.assertIsNone(patterns._owning_family("Component 1 Core"))
        self.assertIsNone(patterns._owning_family("Topic 1 Aero"))

    def test_the_code_never_keeps_the_delimiter_it_matched(self):
        """Identity must not depend on which punctuation the notice used."""
        for delimiter in self.DELIMITERS:
            for spacing in (f"Category 2{delimiter} LOMR Review",
                            f"Category 2 {delimiter} LOMR Review"):
                with self.subTest(text=spacing):
                    hit = patterns.match_family(
                        patterns.FAMILIES_BY_ID["technical_category"], spacing)
                    self.assertEqual(hit.code, "Category 2")
                    self.assertEqual(
                        seg.normalize_code(hit.code),
                        seg.normalize_code("Category 2:"),
                    )

    def test_the_families_that_require_no_delimiter_did_not_gain_one(self):
        """`topic_area`, `focus_area` and `thrust` are out of BUG-2's scope."""
        for text, identifier in (
            ("Topic Area 3 Electrocatalysis", "topic_area"),
            ("Focus Area 3 Integrated Materials Analysis", "focus_area"),
            ("Thrust 3 Materials", "thrust"),
        ):
            with self.subTest(text=text):
                owner = patterns._owning_family(text)
                self.assertEqual(owner.identifier, identifier)

    def test_one_delimiter_class_serves_all_three(self):
        """So a fourth variant cannot be filed later, which is how BUG-2 arose."""
        for identifier in self.REPAIRED:
            self.assertIn(
                patterns._DELIMITERS,
                patterns.FAMILIES_BY_ID[identifier].pattern.pattern,
                identifier,
            )

    # --- §17.8: what is validated by a real document, and what is not --------

    def test_technical_category_s_second_validating_document_is_real(self):
        """FEMA FY 2026 CTP NOFO -- `363000`, and `362999` carries the same file.

        Found by searching P7.1's frozen corpus, then READ: the notice calls
        these *"the allowable project types under this NOFO"*, gives each its own
        MAS/SOW template, scores them differently, and makes one ineligible for
        non-profits. Verbatim, including its punctuation and its spacing:
        """
        headings = [
            "Category 1- Technical Hazard Identification, Risk Analysis and "
            "Mapping or Flood Risk Projects (FRP)",
            "Category 2 - Letter of Map Revision (LOMR) Review",
            "Category 3. Project Management",
        ]
        family, hits = patterns.best_family(headings)
        self.assertEqual(family, "technical_category")
        self.assertEqual([hit.ordinal for hit in hits], [1, 2, 3])
        self.assertEqual([hit.code for hit in hits],
                         ["Category 1", "Category 2", "Category 3"])
        self.assertEqual(hits[2].title, "Project Management")

    def test_arpa_e_scaleup_still_validates_technical_category(self):
        """`356623`'s colon form is the family's original validating document."""
        headings = [f"CATEGORY {n}: Advanced Energy Systems {n}" for n in (1, 2, 3)]
        family, hits = patterns.best_family(headings)
        self.assertEqual(family, "technical_category")
        self.assertEqual(len(hits), 3)

    def test_the_ascii_hyphen_is_a_parser_contract_not_a_measured_form(self):
        """Honesty about what is measured, per §17.8.

        For `technical_category` the ASCII hyphen AND the period are validated by
        a real document (above). For `dod_topic` and `component` they are **not**:
        searching every document P7.1 cached found ZERO `Component N-` headings,
        and the only real `Topic N-` occurrence is a prose one -- NRL `352741`'s
        amendment log, quoted in the negative test below. So the hyphen for those
        two families is a **parser contract**, tested synthetically here and
        labelled as synthetic, while each family keeps its own real-document
        validation: `dod_topic` on `363526` (`Topic 1`-`12`), `349554`
        (`Topic 1`-`18`) and `356612` (`Topic A1`-`A7`); `component` on `360333`
        (`Component 1:`-`5:`).
        """
        synthetic = patterns.match_family(
            patterns.FAMILIES_BY_ID["dod_topic"], "Topic 1- Aero-Structures")
        self.assertIsNotNone(synthetic)
        self.assertEqual(synthetic.title, "Aero-Structures")
        # The en-dash form PACER actually prints, which is why BUG-2 never
        # surfaced in production.
        real = patterns.match_family(
            patterns.FAMILIES_BY_ID["dod_topic"],
            "Topic 1 \u2013 Aero-Structures")
        self.assertEqual(real.code, synthetic.code)
        self.assertEqual(real.title, synthetic.title)

    # --- negatives: the widened class must not turn prose into a set ---------

    def test_a_real_prose_period_form_yields_no_subtopic(self):
        """DTRA `356612`'s notice, verbatim. `Category 6.1` is a DoD budget
        activity code, and with `.` in the class the pattern DOES match it -- so
        the honest assertion is the end-to-end one: two occurrences in a
        document are below §6.4 rule 1's three-item floor and nothing is built.
        """
        lines = [
            "funded by budget Category 6.1 (Basic Research), whether performed "
            "by universities or industry",
            "or (b) funded by budget Category 6.2 (Applied Research) performed "
            "on-campus at a university.",
        ]
        family, hits = patterns.best_family(lines)
        self.assertIsNone(family, "two prose hits must not form a family set")
        containers = [
            {"page": index + 1, "section": None, "anchor": None,
             "text": f"{text}\n{BODY}"}
            for index, text in enumerate(lines)
        ]
        result = seg.segment_document({}, b"", containers, PDF)
        self.assertEqual(result.subtopics, ())

    def test_a_real_prose_hyphen_form_yields_no_subtopic(self):
        """NRL `352741`'s amendment log, verbatim. `Topic 61-24-26` is an agency
        code in a sentence, and it is the ONLY real `Topic N-` in the corpus."""
        line = ("The purpose of this amendment is to add Summary Topic 61-24-26 "
                "to Appendix 1 as well as to update the point of contact.")
        hit = patterns.match_family(patterns.FAMILIES_BY_ID["dod_topic"], line)
        self.assertIsNotNone(hit, "the pattern does match it; the set rules refuse it")
        containers = [{"page": 1, "section": None, "anchor": None,
                       "text": f"{line}\n{BODY}"}]
        result = seg.segment_document({}, b"", containers, PDF)
        self.assertEqual(result.subtopics, ())
        self.assertEqual(result.reason, "no_layer_accepted")

    def test_administrative_prose_with_the_new_delimiters_stays_out(self):
        """§18.3's most damaging change, re-checked against the widened class."""
        lines = [
            "1. Federal Agency Name",
            "2. Funding Opportunity Title",
            "3. Announcement Type",
            "Applications in Category 3 - see Section IV for submission dates.",
            "Component 2 - Reporting requirements are described in Appendix B.",
        ]
        containers = [
            {"page": index + 1, "section": None, "anchor": None,
             "text": f"{text}\n{BODY}"}
            for index, text in enumerate(lines)
        ]
        result = seg.segment_document({}, b"", containers, PDF)
        self.assertEqual(result.subtopics, ())


class RequiredP7FixtureTests(unittest.TestCase):
    """The two false-positive surfaces P5's closeout makes required P7 fixtures.

    `evaluation/p7_false_positive_fixtures.json` carries the verbatim evidence
    and the document hashes; this pins the *shape* against the live patterns, so
    a widening that would admit either surface fails here rather than in a
    backfill. Neither was tuned against -- P7.2 changed punctuation and nothing
    else, and both are still refused for the reason P7.1 measured.
    """

    def test_cdc_component_funding_is_still_refused(self):
        """`360335` lists four components, `360334` three. `component` MATCHES
        them -- it always has -- and the set is refused on span length, because
        the headings sit in a dense bulleted block. Adding the ASCII hyphen
        changes neither half of that.
        """
        headings = [
            "Component 1: Core Global Health Security Priorities",
            "Component 2: Rapid Small-Scale Response to Infectious Disease "
            "Outbreaks or other Public Health Emergencies",
            "Component 3: Rapid Large-Scale Response to Infectious Disease "
            "Outbreaks or other Public Health Emergencies",
            "Component 4: Emerging Infectious Disease Threats",
        ]
        family, hits = patterns.best_family(headings)
        self.assertEqual(family, "component")
        self.assertEqual(len(hits), 4)
        # The measured rejection: every heading is followed by its ceiling on
        # the same dense page, so no span reaches §6.4 rule 3's 200 characters.
        containers = [{"page": 1, "section": None, "anchor": None,
                       "text": "\n".join(
                           f"{heading}\nComponent {index + 1} Ceiling: 1,000,000"
                           for index, heading in enumerate(headings))}]
        flat = seg._flatten(containers)
        candidates = seg._candidates_from(
            hits, flat, [1] * len(hits), [None] * len(hits))
        self.assertIn("span_length",
                      seg.acceptance_failures(candidates, flat, set()))
        result = seg.segment_document({}, b"", containers, PDF)
        self.assertEqual(result.subtopics, ())

    def test_eda_investment_priorities_match_no_family_at_all(self):
        """`347414`, verbatim. Seven named priorities, bare-numbered, of which
        *"each project must be consistent with #2"* and which *"are also
        evaluation factors"*. P7.1 measured that NO family fires here; the
        widened delimiter class must not change that. This is an Fm2 hazard, and
        the fixture exists so P7.4 meets it deliberately.
        """
        lines = [
            "EDA's Investment Priorities are:",
            "1. Equity",
            "2. Recovery & Resilience",
            "3. Workforce Development",
            "4. Manufacturing",
            "5. Technology-Based Economic Development",
            "6. Environmentally-Sustainable Development",
            "7. Exports & Foreign Direct Investment",
            "Under this NOFO, each project must be consistent with #2, "
            "Recovery & Resilience.",
        ]
        for text in lines:
            with self.subTest(text=text):
                self.assertIsNone(patterns._owning_family(text))
        self.assertEqual(patterns.best_family(lines), (None, ()))



if __name__ == "__main__":
    unittest.main()
