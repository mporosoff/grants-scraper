"""Owned outline spans and authenticated continuity, with no provider calls."""
import unittest
from time import monotonic

from scripts import subtopic_segmentation as seg
from tests.fixtures.minipdf import build_pdf, containers_from, heading, line
from tests.test_subtopic_segmentation import body_for


class OutlineBoundsTests(unittest.TestCase):
    TRANSITIONS = (
        ('(d) Advanced Computing Technologies', '2. Basic Energy Sciences (BES)'),
        ('(k) Electron and Scanning Probe Microscopies', 'Chemical Sciences, Geosciences, and Biosciences'),
        ('(w) Physical Biosciences', 'Scientific User Facilities'),
        ('(x) BES Accelerator and Detector Research', '3. Biological and Environmental Research (BER)'),
        ('(c) Low Dose Radiation Research', '4. Fusion Energy Sciences (FES)'),
        ('(m) Public-Private Partnerships', '5. High Energy and Nuclear Physics (HENP)'),
        ('(o) Nuclear Data', '6. Isotope R&D and Production (IRP)'),
    )
    LEAK = 'Ultramarine carbon capture research. Applications due September 30, 2026.'

    def candidate(self, node, entries, flat, ordinal=1):
        start = flat.locate(node.page, node.title)
        self.assertIsNotNone(start)
        return seg._outline_context(seg._Candidate(
            node.title, ordinal, str(ordinal), node.title, start, node.page, None), entries, flat)

    def test_all_seven_transitions_bound_every_derived_field(self):
        for title, following in self.TRANSITIONS:
            for same_page in (True, False):
                with self.subTest(title=title, same_page=same_page):
                    own = f'{title}\n' + body_for('catalytic conversion')
                    containers = [{'page': 1, 'text': own + '\n' + following + '\n' + self.LEAK}] if same_page else [
                        {'page': 1, 'text': own}, {'page': 2, 'text': following + '\n' + self.LEAK}]
                    containers += [{'page': 3, 'text': 'Distinct appendix alpha.'},
                                   {'page': 4, 'text': 'Distinct appendix beta.'}]
                    flat = seg._flatten(containers)
                    nodes = [seg.OutlineNode(2, title, 1, ('Science', 'Current program')),
                             seg.OutlineNode(1, following, 1 if same_page else 2, ('Science',))]
                    candidate = self.candidate(nodes[0], nodes, flat)
                    row = seg.build_subtopics([candidate], flat, containers)[0]
                    boundary = flat.text.index(following)
                    self.assertEqual((row.char_start, row.char_end), (0, boundary))
                    self.assertEqual(row.page_end, 1)
                    self.assertEqual(row.summary, seg.summarize(own.split('\n', 1)[1]))
                    self.assertNotIn('ultramarin', row.subtopic_terms)
                    self.assertNotIn('Ultramarine', str(row.term_display))
                    labels, topics = seg.program_area_fields(own)
                    self.assertEqual(row.program_area_labels, labels)
                    self.assertEqual(row.topic_areas, topics)
                    self.assertIsNone(row.own_deadline)
                    context = row.classifier_context
                    self.assertEqual(context['char_end'], boundary)
                    self.assertNotIn(following, context['local_text'])
                    self.assertNotIn('Ultramarine', context['local_text'])

    def test_unselected_same_level_sibling_bounds_previous_candidate(self):
        titles = ['First Scientific Subject', 'Unselected Scientific Subject', 'Third Scientific Subject']
        containers = [{'page': index + 1, 'text': title + '\n' + body_for(title)}
                      for index, title in enumerate(titles)]
        flat = seg._flatten(containers)
        nodes = [seg.OutlineNode(1, title, index + 1, ('Science',)) for index, title in enumerate(titles)]
        rows = seg.build_subtopics([self.candidate(nodes[0], nodes, flat),
                                   self.candidate(nodes[2], nodes, flat, 2)], flat, containers)
        self.assertEqual(rows[0].char_end, flat.text.index(titles[1]))
        self.assertNotIn('Unselected', rows[0].classifier_context['local_text'])

    def test_missing_immediate_boundary_never_uses_later_heading_or_reference(self):
        for missing in ('absent', 'wrong_page', 'prose_only', 'duplicate'):
            with self.subTest(missing=missing):
                title, boundary = 'Catalysis Science', 'Following Program'
                boundary_text = {'absent': 'Other text', 'wrong_page': 'Other text',
                                 'prose_only': 'See Following Program for more information.',
                                 'duplicate': 'Following Program\nFollowing Program'}[missing]
                containers = [{'page': 1, 'text': title + '\n' + body_for(title)},
                              {'page': 2, 'text': boundary_text},
                              {'page': 3, 'text': 'Following Program\n' + self.LEAK},
                              {'page': 4, 'text': 'Later Program\n' + self.LEAK}]
                flat = seg._flatten(containers)
                nodes = [seg.OutlineNode(1, title, 1, ('Science',)),
                         seg.OutlineNode(0, boundary, 2), seg.OutlineNode(0, 'Later Program', 4)]
                candidate = self.candidate(nodes[0], nodes, flat)
                self.assertEqual(candidate.scope_end, candidate.offset)
                self.assertIn('span_length', seg.acceptance_failures([candidate], flat))
                self.assertTrue(flat.misses)

    def test_ambiguous_current_bookmark_cannot_leave_an_unbounded_span(self):
        title = 'Catalysis Science'
        flat = seg._flatten([{'page': 1, 'text': title + '\n' + body_for(title)}])
        node = seg.OutlineNode(1, title, 1, ('Science',))
        candidate = self.candidate(node, [node, node], flat)
        self.assertEqual(candidate.scope_end, candidate.offset)

    def test_parent_local_context_excludes_children_and_following_parent(self):
        parent = seg.OutlineNode(0, 'Science Office', 1)
        child = seg.OutlineNode(1, 'Catalysis Science', 1, (parent.title,))
        following = seg.OutlineNode(0, 'Following Office', 1)
        text = 'Science Office\nOwn introductory mission.\nCatalysis Science\nResearch in catalysis.\nFollowing Office\n' + self.LEAK
        containers = [{'page': 1, 'text': text}, {'page': 2, 'text': 'Appendix alpha.'},
                      {'page': 3, 'text': 'Appendix beta.'}]
        flat = seg._flatten(containers)
        row = seg.build_subtopics([self.candidate(parent, [parent, child, following], flat)], flat, containers)[0]
        self.assertEqual(row.char_end, text.index(following.title))
        self.assertEqual(row.classifier_context['char_end'], text.index(child.title))
        self.assertEqual(row.classifier_context['child_headings'], [child.title])
        self.assertIn('Own introductory mission', row.classifier_context['local_text'])
        self.assertNotIn('Research in catalysis', row.classifier_context['local_text'])
        self.assertNotIn('Ultramarine', row.summary)

    def test_missing_child_keeps_parent_classifier_text_empty(self):
        parent = seg.OutlineNode(0, 'Science Office', 1)
        child = seg.OutlineNode(1, 'Missing Child Science', 1, (parent.title,))
        containers = [{'page': 1, 'text': 'Science Office\nUndeclared research prose.'}]
        flat = seg._flatten(containers)
        row = seg.build_subtopics([self.candidate(parent, [parent, child], flat)], flat, containers)[0]
        self.assertEqual(row.classifier_context['local_text'], '')
        self.assertEqual(row.classifier_context['char_end'], row.char_start)

    def gap_fixture(self, first_page, child_page, *, unselected=False, missing_parent=False):
        previous = seg.OutlineNode(2, 'Previous Scientific Subject', first_page, ('Science', 'Old Program'))
        parent = seg.OutlineNode(1, 'New Scientific Program', first_page, ('Science',))
        following = seg.OutlineNode(2, 'Next Scientific Subject', child_page, ('Science', parent.title))
        third = seg.OutlineNode(2, 'Third Scientific Subject', child_page + 1, following.chain)
        texts = {first_page: previous.title + '\n' + body_for('previous subject') + '\n' +
                 ('Unknown Heading' if missing_parent else parent.title) + '\nParent introductory material.',
                 child_page: following.title + '\n' + body_for('next subject'),
                 child_page + 1: third.title + '\n' + body_for('third subject')}
        entries = [previous, parent]
        if unselected:
            entries.append(seg.OutlineNode(2, 'Unselected Scientific Subject', first_page + 1, following.chain))
            texts[first_page + 1] = 'Unselected Scientific Subject\n' + body_for('unselected subject')
        entries += [following, third]
        containers = [{'page': page, 'text': texts.get(page, 'Parent introduction continued.')}
                      for page in range(first_page, child_page + 2)]
        flat = seg._flatten(containers)
        candidates = [self.candidate(node, entries, flat, ordinal)
                      for ordinal, node in enumerate((previous, following, third), 1)]
        return candidates, flat, containers

    def test_declared_parent_material_explains_both_real_page_gaps(self):
        for parent_page, child_page in ((77, 84), (53, 55)):
            with self.subTest(parent_page=parent_page):
                candidates, flat, containers = self.gap_fixture(parent_page, child_page)
                self.assertEqual(seg.acceptance_failures(candidates, flat), ())
                rows = seg.build_subtopics(candidates, flat, containers)
                self.assertNotIn('Parent introduct', rows[0].classifier_context['local_text'])
                self.assertEqual(rows[0].char_end, candidates[1].intro_start)

    def test_unexplained_gap_and_missing_parent_are_still_rejected(self):
        for options in ({'unselected': True}, {'missing_parent': True}):
            with self.subTest(options=options):
                candidates, flat, _containers = self.gap_fixture(77, 84, **options)
                self.assertTrue(seg.acceptance_failures(candidates, flat))
                if options.get('unselected'):
                    self.assertIn('page_gap', seg.acceptance_failures(candidates, flat))

    def test_ordinal_outline_path_caps_final_child_at_unselected_parent(self):
        titles = ['Topic Area 1 Catalytic Chemistry', 'Topic Area 2 Photon Materials', 'Topic Area 3 Plasma Science']
        pages = [[heading('Science Program'), line('Program mission.')]]
        pages += [[heading(title), line(body_for(title))] for title in titles]
        pages.append([heading('Following Program'), line(self.LEAK)])
        outline = [('Science Program', 0, 0)] + [(title, index + 1, 1) for index, title in enumerate(titles)]
        outline.append(('Following Program', 4, 0))
        containers = containers_from(pages)
        flat = seg._flatten(containers)
        outcome = seg._layer_outline(build_pdf(pages, outline=outline), containers, flat, monotonic() + 20, ())
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome[0], 'outline')
        rows = seg.build_subtopics(outcome[3], flat, containers)
        self.assertEqual(rows[-1].char_end, flat.text.index('Following Program'))
        self.assertIsNone(rows[-1].own_deadline)

    def test_structural_outline_path_keeps_scope_and_selection_continuity_separate(self):
        titles = ('Catalysis Science Research', 'Photon Materials Chemistry', 'Plasma Physics Frontiers',
                  'Quantum Sensing Devices', 'Biological Systems Science', 'Molecular Reaction Dynamics')
        entries, containers = [], []
        for group, parent in enumerate(('Physical Sciences', 'Biological Sciences')):
            page = 1 if group == 0 else 5
            entries.append(seg.OutlineNode(0, parent, page))
            containers.append({'page': page, 'text': parent + '\nParent introduction.'})
            for index, title in enumerate(titles[group * 3:group * 3 + 3]):
                page += 1 if group == 0 or index else 4
                entries.append(seg.OutlineNode(1, title, page, (parent,)))
                containers.append({'page': page, 'text': title + '\n' + body_for(title)})
        flat = seg._flatten(containers)
        outcome = seg._structural_from_outline(entries, flat, ())
        self.assertIsNotNone(outcome)
        self.assertEqual(len(outcome[3]), 6)
        rows = seg.build_subtopics(outcome[3], flat, containers)
        self.assertEqual(rows[2].char_end, flat.text.index('Biological Sciences'))
        self.assertNotIn('Parent introduction', rows[2].classifier_context['local_text'])

    def test_non_outline_spans_keep_existing_next_selected_heading_bounds(self):
        containers = [{'page': 1, 'text': 'First Subject\n' + body_for('first')},
                      {'page': 2, 'text': 'Second Subject\n' + body_for('second')}]
        flat = seg._flatten(containers)
        candidates = [seg._Candidate(str(i), i, str(i), name, flat.text.index(name), i, None)
                      for i, name in enumerate(('First Subject', 'Second Subject'), 1)]
        rows = seg.build_subtopics(candidates, flat, containers)
        self.assertEqual(rows[0].char_end, candidates[1].offset)
        self.assertEqual(rows[1].char_end, len(flat.text))

    def test_scope_clamps_do_not_recalculate_unrelated_final_span_estimate(self):
        from dataclasses import replace
        candidates = [seg._Candidate(str(index), index, str(index), 'Scientific Subject',
                                     offset, index, None)
                      for index, offset in enumerate((0, 500, 1000), 1)]
        original = seg._span_bounds(candidates, 5000)
        candidates[0] = replace(candidates[0], scope_end=250)
        corrected = seg._span_bounds(candidates, 5000)
        self.assertEqual(corrected[0], (0, 250))
        self.assertEqual(corrected[-1], original[-1])
