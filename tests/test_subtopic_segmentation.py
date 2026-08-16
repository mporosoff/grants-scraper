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
            "area_of_interest": "Area of Interest 3 Water Reuse",
            "dod_topic": "Topic 3: Quantum Sensing",
            "technical_area": "Technical Area 3 Autonomy",
            "thrust": "Thrust 3 Materials",
            "roses_element": "B.3 Exoplanet Research Program",
            "nsf_track": "Track 3 Design",
            "sbir_subtopic": "Subtopic 3a Membrane Fabrication",
            "priority_research": "Priority Research Direction 3 Charge Transfer",
            "research_thrust": "Research Thrust 3 Interfacial Chemistry",
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
        # "Research Thrust 3" also satisfies thrust's pattern; letting the
        # looser family claim it would split one family's count across two.
        self.assertEqual(
            patterns._owning_family("Research Thrust 3 Interfaces").identifier,
            "research_thrust",
        )
        # "Subtopic 3" contains "topic 3", but \bTopic cannot match inside it.
        self.assertEqual(
            patterns._owning_family("Subtopic 3: Fabrication").identifier,
            "sbir_subtopic",
        )

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
        technical = [f"Technical Area {n} Beta" for n in range(1, 4)]
        self.assertEqual(patterns.best_family(topic + technical), (None, ()))

        wide = [f"Topic Area {n} Alpha" for n in range(1, 7)]
        family, hits = patterns.best_family(wide + technical)
        self.assertEqual(family, "topic_area")
        self.assertEqual(len(hits), 6)

    def test_best_family_requires_three_candidates(self):
        self.assertEqual(
            patterns.best_family(["Topic Area 1 A", "Topic Area 2 B"]), (None, ())
        )

    def test_roman_and_alphanumeric_ordinals_parse(self):
        _family, hits = patterns.best_family(
            ["Track I Alpha", "Track II Beta", "Track III Gamma"]
        )
        self.assertEqual([hit.ordinal for hit in hits], [1, 2, 3])

        _family, hits = patterns.best_family(
            ["Subtopic 1a Alpha", "Subtopic 2b Beta", "Subtopic 3c Gamma"]
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
        "area_of_interest": [
            ("Area of Interest 1 Water Reuse", "Water Reuse", "Area of Interest 1"),
            ("Area of Interest 2 Desalination", "Desalination", "Area of Interest 2"),
            ("Area of Interest 3 Sensing", "Sensing", "Area of Interest 3"),
        ],
        "dod_topic": [
            ("Topic 1: Quantum Sensing", "Quantum Sensing", "Topic 1"),
            ("Topic 2: Autonomy", "Autonomy", "Topic 2"),
            ("Topic 3: Materials", "Materials", "Topic 3"),
        ],
        "technical_area": [
            ("Technical Area 1 Autonomy", "Autonomy", "Technical Area 1"),
            ("Technical Area 2 Sensing", "Sensing", "Technical Area 2"),
            ("Technical Area 3 Networks", "Networks", "Technical Area 3"),
        ],
        "thrust": [
            ("Thrust 1 Materials", "Materials", "Thrust 1"),
            ("Thrust 2 Devices", "Devices", "Thrust 2"),
            ("Thrust 3 Systems", "Systems", "Thrust 3"),
        ],
        "roses_element": [
            ("B.1 Exoplanet Research", "Exoplanet Research", "B.1 Exoplanet Research"),
            ("B.2 Heliophysics Science", "Heliophysics Science",
             "B.2 Heliophysics Science"),
            ("B.3 Astrobiology Science", "Astrobiology Science",
             "B.3 Astrobiology Science"),
        ],
        "nsf_track": [
            ("Track 1 Design", "Design", "Track 1"),
            ("Track 2 Scale", "Scale", "Track 2"),
            ("Track 3 Transition", "Transition", "Track 3"),
        ],
        "sbir_subtopic": [
            ("Subtopic 1a Membrane Fabrication", "Membrane Fabrication",
             "Subtopic 1a"),
            ("Subtopic 2b Catalyst Synthesis", "Catalyst Synthesis", "Subtopic 2b"),
            ("Subtopic 3c Reactor Design", "Reactor Design", "Subtopic 3c"),
        ],
        "priority_research": [
            ("Priority Research Direction 1 Charge Transfer", "Charge Transfer",
             "Priority Research Direction 1"),
            ("Priority Research Direction 2 Interfaces", "Interfaces",
             "Priority Research Direction 2"),
            ("Priority Research Direction 3 Transport", "Transport",
             "Priority Research Direction 3"),
        ],
        "research_thrust": [
            ("Research Thrust 1 Interfacial Chemistry", "Interfacial Chemistry",
             "Research Thrust 1"),
            ("Research Thrust 2 Separations", "Separations", "Research Thrust 2"),
            ("Research Thrust 3 Catalysis", "Catalysis", "Research Thrust 3"),
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


if __name__ == "__main__":
    unittest.main()
