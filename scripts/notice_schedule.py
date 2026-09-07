"""Source-native submission fields and typed event identity.

Only the supported field structures admit multiple dates. Narrative fallback
keeps its independent, conservative local-ownership contract.
"""
import re
from urllib.parse import urlparse
from scripts.notice_semantics import clauses

SCHEDULE_VERSION = "submission-fields-20"
FIELD_LABEL = re.compile(r'^(?:Required\s+|Optional\s+)?(?:Full\s+(?:Application|Proposal)|Application|Proposal|'
    r'Concept\s+(?:Paper|Outline)|White\s+Paper|Letter\s+of\s+Intent|Pre[\s-]Application(?:\s*\([^)]{1,30}\))?)'
    r'\s+(?:Submission\s+)?(?:Deadline|Due\s+Date)(?:\(s\)|s)?\s*(?:\([^)]{1,100}\))?\s*:', re.I)
STAGES = [
    ("letter_of_intent", r"letters?\s+of\s+(?:intent|interest)|(?-i:LOIs?)"),
    ("concept_paper", r"concept\s+(?:papers?|outlines?)|(?-i:CPs?)"),
    ("white_paper", r"white\s+papers?"),
    ("preproposal", r"pre[\s-]?proposals?|preliminary\s+proposals?"),
    ("preapplication", r"pre[\s-]?applications?|solution\s+(?:summar(?:y|ies)|videos?)"),
    ("application", r"(?:full\s+)?(?:applications?|proposals?)|(?-i:FAs?)"),
]


def stage_for(label):
    if re.search(r"\b(?:review|award|start|expiration|verification|questions?|webinar|invitation\s+to|package\s+available)\b", label, re.I):
        return None
    for stage, pattern in STAGES:
        if re.search(rf"\b(?:{pattern})\b", label, re.I):
            return stage
    return None


def obligation(label):
    if re.search(r"\b(?:not\s+required|optional|not\s+mandatory)\b", label, re.I):
        return "optional", False
    if re.search(r"\b(?:required|mandatory|must\s+(?:submit|provide|receive))\b", label, re.I):
        return "required", True
    return "unknown", None


def preliminary_requirement(text, stage_label):
    """Tri-state synopsis fallback, scoped to the actually mentioned stage."""
    stage = stage_for(stage_label or '')
    pattern = next((pattern for name, pattern in STAGES if name == stage), None)
    if not pattern or stage == 'application':
        return None
    subject = rf'(?:{pattern})'
    values = set()
    for sentence in re.split(r'[.;\n]', text or ''):
        if re.search(rf'\b{subject}\s+(?:is\s+|are\s+)?(?:not\s+required|optional)\b|'
                     rf'\b(?:although|while)\s+not\s+required,\s*{subject}\b|\boptional\s+{subject}\b', sentence, re.I):
            values.add(False)
        elif re.search(rf'\b(?:required|mandatory)\s+{subject}\b|\b{subject}\s+(?:is\s+|are\s+)?(?:required|mandatory)\b|'
                       rf'\bmust\s+submit\s+(?:an?\s+)?{subject}\b', sentence, re.I):
            values.add(True)
    return next(iter(values)) if len(values) == 1 else None


def value_only(api, text):
    """A native date value may contain date lists and owned clocks, not prose."""
    masked = api.DATE_RE.sub('', text)
    masked = api.TIME_RE.sub('', masked)
    masked = re.sub(r'\b(?:by|at|and|ET|CT|MT|PT|UTC|GMT)\b', '', masked, flags=re.I)
    return not re.search(r'[^\s,;:.()\[\]–—-]', masked)


def clock_key(clock, zone):
    clock = re.sub(r'[.\s]', '', clock or '').casefold()
    clock = re.sub(r'^(\d{1,2})(am|pm)$', r'\1:00\2', clock)
    zone = (zone or '').casefold()
    zone = {'eastern': 'et', 'central': 'ct', 'mountain': 'mt', 'pacific': 'pt'}.get(zone, zone)
    return clock, zone


def ambiguous_value_tail(api, text):
    """Shared scalar-field guard, using the established replacement grammar."""
    boundary = next(api._deadline_boundaries(text, 0, len(text)), None)
    tail = text[:boundary[0]] if boundary else text
    return bool(re.search(api._REPLACEMENT_LINK, tail, re.I)
                or len(list(api.TIME_RE.finditer(tail))) > 1
                or (api._REQUIREMENT.search(tail) and not api._balanced_deadline_field(tail)))


def field_events(api, opportunity_id, container, document, stamp, *, label, start, end, field_id=None, clock_label=None, application_class=None):
    stage = stage_for(label)
    if not stage:
        return []
    text = container['text'][start:end]
    dates = list(api.DATE_RE.finditer(text))
    unknown = not dates and bool(re.fullmatch(r'\s*(?:TBD|to be (?:determined|announced)|not (?:announced|listed)|unknown)\s*', text, re.I))
    if not dates and not unknown:
        return []
    clocks = list(api.TIME_RE.finditer(text))
    clocks += list(api.TIME_RE.finditer(clock_label or label))
    invalid_alias = (any(not api._clock_extent(text, m)[1] for m in api.TIME_RE.finditer(text))
                     or any(not api._clock_extent(clock_label or label, m)[1] for m in api.TIME_RE.finditer(clock_label or label)))
    clock_values = {clock_key(m.group(1), api.deadline_timezone(m)): (m.group(1), api.deadline_timezone(m)) for m in clocks}
    clock, zone = next(iter(clock_values.values())) if len(clock_values) == 1 and not invalid_alias else (None, None)
    if clock and re.search(r"submitting\s+organization.s\s+local\s+time|submitter.s\s+local\s+time|local\s+time\s+of\s+(?:the\s+)?applicant\s+organization", clock_label or label, re.I):
        zone = "applicant_local"
    rule, required = obligation(label)
    if application_class is None:
        application_class = ('resubmission' if re.search(r'\bresubmissions?\b', label, re.I)
                             else 'new' if re.search(r'\bnew\s+applications?\b', label, re.I) else 'unspecified')
    cycle = re.search(r'\b(?:FY|Fiscal Year)\s*(20\d{2})\b', label, re.I)
    track = re.search(r'\bTrack\s+([A-Z0-9]+)\b', label, re.I)
    if unknown:
        citation = api.citation_for(container, document, start, end, stamp)
        citation.setdefault('structural_reference', {}).update(field_label=label[:180], field_id=field_id)
        return [api.make_fact(opportunity_id, 'submission_requirement', 'Submission date not announced', None,
            'Date not announced', citation, deadline_kind=stage, stage=stage, date=None, time=None, timezone=None,
            required=required, obligation=rule, application_class=application_class or 'unspecified',
            cycle='FY' + cycle.group(1) if cycle else None, track=track.group(1) if track else None, field_authority='official_notice_field', parser_version=SCHEDULE_VERSION)]
    facts = []
    for match in dates:
        value = api.parse_document_date(match.group())
        if not value:
            continue
        citation = api.citation_for(container, document, start + match.start(), start + match.end(), stamp)
        citation.setdefault('structural_reference', {}).update(field_label=label[:180], field_id=field_id)
        # A field label is actual retained source context, not new verification.
        label_text = next((title for kind, title, _ in api.DEADLINE_KINDS if kind == stage), 'Submission deadline')
        fact = api.make_fact(opportunity_id, 'deadline', label_text, value,
            value + (f" · {clock}" if clock else '') + (f" {zone}" if zone else ''), citation,
            deadline_kind=stage, date=value, time=clock, timezone=zone, required=required,
            obligation=rule, subject='submission', stage=stage, application_class=application_class or 'unspecified',
            cycle='FY' + cycle.group(1) if cycle else None, track=track.group(1) if track else None, invitation_required=None, prerequisite=None,
            parser_version=SCHEDULE_VERSION, field_authority='official_notice_field', clock_conflict=len(clock_values) > 1 or invalid_alias)
        facts.append(fact)
    return facts


def _nih_fields(api, opportunity_id, containers, document, stamp):
    fields = {}
    rows = {}
    for container in containers:
        for block in container.get('structure') or []:
            row = next((a for a in reversed(block.get('ancestors', []))
                        if a.get('data-index') is not None and 'row' in a.get('class', '').split()), None)
            if row:
                rows.setdefault(row['data-index'], []).append((container, block))
            native = next((a for a in reversed(block.get('ancestors', [])) if a.get('data-element-id') and a.get('data-section-code') == 'KD'), None)
            if not native:
                continue
            field = fields.setdefault(native['data-element-id'], {'label': None, 'values': []})
            if native.get('data-element-has-label') == 'true':
                field['values'].append((container, block))
            elif re.search(r'datalabel|heading4', native.get('class', '')):
                field['label'] = block['text']
    # Older NIH notices use sibling label/value columns within one indexed row.
    # Match the retained parent row, never the nearest unlabeled date column.
    for blocks in rows.values():
        labels = [(b, a) for _, b in blocks for a in b.get('ancestors', [])
                  if a.get('data-section-code') == 'KD' and a.get('data-element-id')
                  and 'datalabel' in a.get('class', '').split()]
        if len(labels) != 1:
            continue
        label, native = labels[0]
        values = [(c, b) for c, b in blocks if any('datacolumn' in a.get('class', '').split()
                                                 for a in b.get('ancestors', []))]
        if values:
            fields[native['data-element-id']] = {'label': label['text'], 'values': values}
    facts = []
    for identifier, field in fields.items():
        label = field['label'] or ''
        if not re.search(r'due\s+date|deadline', label, re.I) or not stage_for(label):
            continue
        has_resubmission_field = any(re.search(r'Resubmissions?\s+ONLY\s+Application\s+Due', b['text'], re.I)
                                     for _, b in field['values'])
        shared_clocks = [(c, b) for c, b in field['values'] if re.match(
            r'All applications are due by\s+', b['text'], re.I) and api.TIME_RE.search(b['text'])]
        clock_label = ' '.join(b['text'] for _, b in shared_clocks) or None
        for container, block in field['values']:
            text = block['text']
            begin, end = block['span']
            resubmission = re.search(r'Resubmissions?\s+ONLY\s+Application\s+Due\s+Date\(s\)\s*:', text, re.I)
            classification = 'new' if has_resubmission_field else 'unspecified'
            owned_label = label
            if resubmission:
                owned_label = resubmission.group()
                begin += resubmission.end()
                classification = 'resubmission'
            elif re.search(r'\bresubmissions?\b', text, re.I):
                # Mixed class prose without the supported explicit subfield.
                continue
            first_due = re.match(r'The first Application Due Date is\s+', text, re.I)
            if first_due:
                begin += first_due.end()
            value = container['text'][begin:end]
            dates = list(api.DATE_RE.finditer(value))
            if not dates or value[:dates[0].start()].strip():
                continue
            last = dates[0]
            for candidate in dates[1:]:
                if not value_only(api, value[last.end():candidate.start()]):
                    break
                last = candidate
            tail = value[last.end():]
            trailing_clock = re.match(r'\s*[,;]?\s*(?:by\s+|at\s+)?' + api.TIME_RE.pattern, tail, re.I)
            end = begin + last.end() + (trailing_clock.end() if trailing_clock else 0)
            found = field_events(api, opportunity_id, container, document, stamp,
                label=owned_label, start=begin, end=end, field_id=identifier, application_class=classification,
                clock_label=clock_label)
            if len(shared_clocks) == 1:
                c, b = shared_clocks[0]
                for fact in found:
                    if fact.get('time'):
                        fact['clock_citation'] = api.citation_for(c, document, *b['span'], stamp)
            facts.extend(found)
    return facts


def _table_fields(api, opportunity_id, containers, document, stamp):
    facts = []
    for container in containers:
        for block in container.get('structure') or []:
            if block.get('kind') != 'table_row' or block.get('is_header'):
                continue
            cells = block.get('cells') or []
            if any(c.get('colspan') != 1 or c.get('rowspan') != 1 or c.get('nested_table') for c in cells):
                continue
            label = cells[0]['text'] if cells else ''
            headers = block.get('header_rows') or []
            headers = headers[-1] if headers else []
            offset = block['span'][0]
            for index, cell in enumerate(cells):
                column_label = headers[index]['text'] if len(headers) == len(cells) else ''
                owned_label = label if stage_for(label) else column_label
                if stage_for(owned_label) and (re.search(r'\b(?:deadline|due|submission)\b', owned_label + ' ' + column_label, re.I)
                    or any(re.search(r'\b(?:deadline|due)\b', h['text'], re.I) for h in headers)):
                    required_cells = [cells[n]['text'] for n, h in enumerate(headers) if len(headers) == len(cells)
                                      and re.fullmatch(r'required\??', h['text'], re.I)]
                    requirement = (' Required' if required_cells == ['Yes'] else ' Optional' if required_cells == ['No'] else '')
                    if value_only(api, cell['text']) or re.fullmatch(r'TBD|to be (?:determined|announced)|unknown', cell['text'], re.I):
                        facts.extend(field_events(api, opportunity_id, container, document, stamp, label=owned_label + requirement,
                            start=offset, end=offset + len(cell['text']), field_id=f"{block['table_id']}:{block['row']}:{index}"))
                offset += len(cell['text']) + 3
    return facts


def _nih_key_dates_table(api, opportunity_id, containers, document, stamp):
    """Read NIH's spanning due-date header and its application-class columns.

    The neighboring review/award header never owns submission values. Header
    spans, the native table identity, and a single owned cell prove each fact.
    """
    facts = []
    for container in containers:
        blocks = container.get('structure') or []
        clocks = [b for b in blocks if re.fullmatch(
            r'All applications are due by\s+.+local time of applicant organization\.', b['text'], re.I)
            and any(a.get('data-section-code') == 'KD' for a in b.get('ancestors', []))]
        for block in blocks:
            if (block.get('kind') != 'table_row' or block.get('is_header')
                or not any(a.get('tag') == 'table' and a.get('id') == 'keyDatesContentTable'
                           for a in block.get('ancestors', []))
                or not any(a.get('data-section-code') == 'KD' for a in block.get('ancestors', []))):
                continue
            headers = block.get('header_rows') or []
            cells = block.get('cells') or []
            if len(headers) != 2 or any(c.get('rowspan') != 1 or c.get('nested_table') for row in headers + [cells] for c in row):
                continue
            offset = block['span'][0]
            for cell in cells:
                start, end = offset, offset + len(cell['text'])
                offset = end + 3
                if cell.get('colspan') != 1:
                    continue
                path = [[h for h in row if h.get('column', -1) <= cell.get('column', -2)
                         < h.get('column', -1) + (h.get('colspan') or 0)] for row in headers]
                if any(len(matches) != 1 for matches in path):
                    continue
                parent, leaf = [matches[0] for matches in path]
                if parent['text'] != 'Application Due Dates' or leaf.get('colspan') != 1:
                    continue
                classification = ('new' if leaf['text'] == 'New' else 'resubmission'
                    if re.fullmatch(r'Renewal\s*/\s*Resubmission\s*/\s*Revision\s*\(as allowed\)', leaf['text'], re.I) else None)
                if not classification:
                    continue  # An AIDS-specific or unknown class is not general entry.
                value = cell['text']
                if value.rstrip().endswith('*'):
                    if not any(b['text'] == 'The following table includes NIH standard due dates marked with an asterisk.' for b in blocks):
                        continue
                    value = value.rstrip().rstrip('*').rstrip()
                if not value_only(api, value) or len(list(api.DATE_RE.finditer(value))) != 1:
                    continue
                found = field_events(api, opportunity_id, container, document, stamp,
                    label=parent['text'] + ': ' + leaf['text'], start=start, end=end,
                    field_id=f"{block['table_id']}:{block['row']}:{cell['column']}",
                    application_class=classification, clock_label=' '.join(b['text'] for b in clocks))
                for fact in found:
                    fact['citation']['structural_reference']['column_header'] = leaf['text']
                    if len(clocks) == 1 and fact.get('time'):
                        fact['clock_citation'] = api.citation_for(container, document, *clocks[0]['span'], stamp)
                facts.extend(found)
    return facts


def _pdf_key_dates(api, opportunity_id, containers, document, stamp):
    """NIH/FDA's printed Key Dates fields, including a continuation page.

    Only the contiguous value prefix of an explicitly labeled submission field
    is read. Review/start/expiration fields and prose end ownership.
    """
    active = []
    for index, container in enumerate(containers):
        if container.get('page') is None or not re.search(r'(?m)^\s*Key Dates\s*$', container['text']):
            continue
        for candidate in containers[index:index + 3]:
            text = candidate['text']
            stop = re.search(r'(?m)^\s*(?:Required Application Instructions|Table of Contents)\s*$', text)
            active.append((candidate, text[:stop.start()] if stop else text))
            if stop:
                break
        break
    if not active:
        return []
    has_resubmissions = any(re.search(r'Resubmissions ONLY Application Due\s+Date', text, re.I) for _, text in active)
    label_pattern = re.compile(r'(?im)(?:^\s*(?P<ordinary>Letter\s+of\s+Intent\s+Due\s+Date(?:\(s\))?|Application\s+Due\s+Date(?:\(s\))?)'
        r'|(?P<resubmission>Resubmissions ONLY Application Due\s+Date\(s\)))\s*:?\s*')
    facts = []
    submission_clocks = [(c, m) for c, text in active for m in re.finditer(
        r'(?:Applications must\s+be submitted to and validated successfully by Grants\.gov no later than|All applications are due by)\s+'
        + api.TIME_RE.pattern + r'(?:\s+local\s+time\s+of\s+(?:the\s+)?applicant\s+organization)?', text, re.I)]
    paired_cycles = {}
    for container, text in active:
        for field in label_pattern.finditer(text):
            label = field.group('ordinary') or field.group('resubmission')
            value = text[field.end():]
            # CDC's source template leaves an explanatory sentence between a
            # real field label and its date-list value. Skip only that template
            # sentence; all subsequent values still require contiguous ownership.
            boilerplate = re.match(r'(?:The LOI date will generate once the Synopsis is published if Days or a Date are entered\.'
                r'|Application Due Date will be submitted as: date based on the value specified for Due Date for\s+Applications)\s*', value)
            value_start = field.end() + (boilerplate.end() if boilerplate else 0)
            value = text[value_start:]
            if stage_for(label) == 'letter_of_intent':
                # FDA's printed LOI field explicitly pairs the preliminary
                # date with its application cycle. "Not applicable for" is
                # not a second source of an application deadline.
                paired = re.match(r'(?:Not applicable for\s+' + api.DATE_RE.pattern
                    + r'\s+application due date\.\s*)?', value, re.I)
                cursor = paired.end()
                pair_pattern = re.compile(r'(?P<loi>' + api.DATE_RE.pattern + r'),?\s+for\s+(?P<full>'
                    + api.DATE_RE.pattern + r')\s+application due date\.\s*', re.I)
                pairs = []
                while (pair := pair_pattern.match(value, cursor)):
                    pairs.append(pair)
                    cursor = pair.end()
                if pairs:
                    for pair in pairs:
                        cycle = api.parse_document_date(pair['full'])
                        found = field_events(api, opportunity_id, container, document, stamp, label=label,
                            start=value_start + pair.start('loi'), end=value_start + pair.end('loi'),
                            field_id=f"pdf-key-dates-pair:{container['page']}:{pair.start()}")
                        for fact in found:
                            if not cycle or fact['date'] >= cycle:
                                continue
                            fact['cycle'] = cycle
                            fact['cycle_citation'] = api.citation_for(container, document,
                                value_start + pair.start(), value_start + pair.end(), stamp)
                            paired_cycles[cycle] = fact['cycle_citation']
                            facts.append(fact)
                    container.setdefault('_native_field_values', []).append((value_start, value_start + cursor))
                    continue
            dates = list(api.DATE_RE.finditer(value))
            previous_end = 0
            field_facts = []
            field_end = field.end()
            for match in dates:
                between = re.sub(r'\bOptional\b', '', value[previous_end:match.start()], flags=re.I)
                if not value_only(api, between):
                    break
                start = value_start + match.start()
                tail = value[match.end():]
                clock = re.match(r'\s*[,;]?\s*(?:by\s+|at\s+)?' + api.TIME_RE.pattern, tail, re.I)
                optional = re.match(r'\s*\(Optional\)', tail, re.I)
                end = value_start + match.end() + (clock.end() if clock else optional.end() if optional else 0)
                owned_label = label + (' Optional' if optional else '')
                found = field_events(api, opportunity_id, container, document, stamp, label=owned_label,
                    start=start, end=end, field_id=f"pdf-key-dates:{container['page']}:{field.start()}",
                    clock_label=' '.join(m.group() for _, m in submission_clocks) if stage_for(label) == 'application' else None,
                    application_class='resubmission' if field.group('resubmission') else
                        'new' if has_resubmissions and stage_for(label) == 'application' else 'unspecified')
                if stage_for(label) == 'application' and len(submission_clocks) == 1:
                    c, clock_source = submission_clocks[0]
                    for fact in found:
                        if fact.get('time'):
                            fact['clock_citation'] = api.citation_for(c, document, clock_source.start(), clock_source.end(), stamp)
                field_facts.extend(found)
                field_end = end
                previous_end = match.end()
            prefix = text[value_start:field_end]
            clocks = list(api.TIME_RE.finditer(prefix))
            # A single clock following the entire contiguous date list owns
            # that list. Do not spread an intermediate row's clock forward.
            if len(clocks) == 1 and clocks[0].start() >= previous_end:
                for fact in field_facts:
                    if not fact.get('time'):
                        fact['time'], fact['timezone'] = clocks[0].group(1), api.deadline_timezone(clocks[0])
                        fact['display_value'] = fact['date'] + f" · {fact['time']}" + (f" {fact['timezone']}" if fact['timezone'] else '')
                        fact['clock_citation'] = api.citation_for(container, document,
                            value_start + clocks[0].start(), value_start + clocks[0].end(), stamp)
            facts.extend(field_facts)
    for fact in facts:
        if fact['deadline_kind'] == 'application' and fact['date'] in paired_cycles:
            fact['cycle'] = fact['date']
            fact['cycle_citation'] = paired_cycles[fact['date']]
    return facts


def _noaa_annual_dates(api, opportunity_id, containers, document, stamp):
    """NOAA executive-summary Dates: submission list vs project-start pairs."""
    facts = []
    for container in containers:
        text = container['text']
        if container.get('page') is None or not re.search(r'NOAA NOFO Page', text[:100]):
            continue
        summary = re.search(r'(?m)^\s*Executive Summary\s*$', text)
        field = re.search(r'(?m)^\s*Dates\s*$', text[summary.end():]) if summary else None
        if not field:
            continue
        start = summary.end() + field.end()
        body = text[start:start + 1800]
        boundary = re.search(r'\n[ \t]*\n', body)
        if boundary:
            body = body[:boundary.start()]
        listing = re.match(r'\s*Applications will be accepted and considered on an annual basis, with due dates of\s+([^.]*)\.', body)
        if not listing or not value_only(api, listing[1]):
            continue
        field_facts = field_events(api, opportunity_id, container, document, stamp, label='Application due dates',
            start=start + listing.start(1), end=start + listing.end(1), field_id=f"noaa-annual:{container['page']}:{start}")
        for clock_field in re.finditer(r'received\s+(?:through\s+www\.grants\.gov\s+)?by\s+(?P<clock>.{1,100}?)\s*on\s+', body, re.I | re.S):
            clock_text = clock_field['clock'].strip()
            clock = api.TIME_RE.match(clock_text)
            if not clock or not api._clock_extent(clock_text, clock)[1]:
                continue
            # Only a full clock field, including an optional matching alias,
            # can own these rows. No material between a clock and its "on".
            clock_end = api._clock_extent(clock_text, clock)[0]
            if clock_text[clock_end:].strip():
                continue
            tail = body[clock_field.end():].split('.', 1)[0]
            dates = []
            scalar = api.DATE_RE.fullmatch(tail.strip())
            if scalar:
                dates = [api.parse_document_date(scalar.group())]
            else:
                pair = re.compile(r'(?P<due>' + api.DATE_RE.pattern + r'),?\s+for projects starting\s+'
                    r'(?:(?:on\s+)?approximately|no earlier than)\s+' + api.DATE_RE.pattern, re.I)
                cursor = 0
                for row in pair.finditer(tail):
                    if not re.fullmatch(r'[\s,;]*(?:and\s+)?', tail[cursor:row.start()], re.I):
                        dates = []
                        break
                    dates.append(api.parse_document_date(row['due']))
                    cursor = row.end()
                if tail[cursor:].strip():
                    dates = []
            for fact in field_facts:
                if fact['date'] not in dates:
                    continue
                fact['time'], fact['timezone'] = clock.group(1), api.deadline_timezone(clock)
                fact['clock_citation'] = api.citation_for(container, document,
                    start + clock_field.start(), start + clock_field.end() + len(tail), stamp)
                fact['display_value'] = fact['date'] + f" · {fact['time']}" + (f" {fact['timezone']}" if fact['timezone'] else '')
        container.setdefault('_native_field_values', []).append((start, start + len(body)))
        facts.extend(field_facts)
    return facts


def _owned_submission_sentences(api, opportunity_id, containers, document, stamp):
    """Explicit receipt sentences in the measured NOAA/EDA/FHWA notices.

    Only an immediate scalar date/clock value is accepted. A named competition
    or application path remains attached to that sentence, not nearby dates.
    """
    weekday = r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
    clock = r'(?:' + api.TIME_RE.pattern + r')(?:\s+local\s+time)?'
    value = r'(?P<value>(?:' + clock + r'\s*,?\s*(?:on\s+)?)?(?:' + weekday + r',\s*)?'
    value += api.DATE_RE.pattern + r'(?:\s*,?\s*(?:at|by)\s+' + clock + r')?)(?:\s*,\s*(?P<postfix_zone>[ECMPA][SD]T)\b)?'
    subjects = r'(?:Full\s+|Complete\s+)?applications|Letters\s+of\s+Intent'
    patterns = [
        re.compile(r'(?P<label>' + subjects + r')(?P<track>\s+for\s+[^.;!?\n]{1,180}?)?\s+'
            r'(?:must|should)\s+be\s+received\s+(?:by\s+the\s+Competition\s+Manager\s+)?(?:by|no later than)\s+' + value, re.I),
        re.compile(r'(?P<label>deadline\s+for\s+applications)(?P<track>\s+submitted\s+under\s+[^.;!?\n]{1,100}?)\s+is\s+' + value, re.I),
    ]
    facts = []
    for container in containers:
        if container.get('page') is None:
            continue
        text = container['text']
        for pattern in patterns:
            for match in pattern.finditer(text):
                track = api.clean_text(match.group('track') or '') or None
                prefix = text[max(0, match.start() - 200):match.start()]
                if (track and (api.DATE_RE.search(track) or api.TIME_RE.search(track))
                    or re.search(r'\b(?:if|when|whether)\s*$', prefix, re.I)):
                    continue
                # Reuse existing replacement/ambiguous-clock protections;
                # this reader never searches onward for a replacement value.
                if ambiguous_value_tail(api, text[match.end():]):
                    container['_deadline_uncertain_component'] = True
                    continue
                found = field_events(api, opportunity_id, container, document, stamp, label=match['label'],
                    start=match.start('value'), end=match.end('value'),
                    field_id=f"receipt-sentence:{container['page']}:{match.start()}")
                fiscal = re.search(r'For\s+(FYs?\s+20\d{2}(?:\s*(?:and|&)\s*20\d{2})?)\s*,\s*$', prefix, re.I)
                heading = re.search(r'(?:^|\(\d+\)\s+)([A-Z][^.\n]{5,150}\s+grant applications)\.\s*$', prefix)
                for fact in found:
                    fact['_receipt_sentence'] = api.clean_text(match.group())
                    if match['postfix_zone'] and fact.get('time') and not fact.get('timezone'):
                        fact['timezone'] = match['postfix_zone'].upper()
                        fact['display_value'] += ' ' + fact['timezone']
                        fact['clock_citation'] = api.citation_for(container, document, match.start('value'), match.end(), stamp)
                    if track:
                        fact['track'] = track
                        fact['track_citation'] = api.citation_for(container, document, match.start(), match.end(), stamp)
                    if fiscal:
                        fact['cycle'] = fiscal[1]
                        fact['cycle_citation'] = api.citation_for(container, document, max(0, match.start() - 200) + fiscal.start(), match.end(), stamp)
                    if not track and heading:
                        fact['track'] = heading[1]
                        fact['track_citation'] = api.citation_for(container, document, max(0, match.start() - 200) + heading.start(), match.end(), stamp)
                container.setdefault('_native_field_values', []).append((match.start('value'), match.end('value')))
                facts.extend(found)
    # A shortened legacy quote can repeat the same complete receipt sentence
    # while omitting its preceding scope heading. It cannot add an unscoped
    # copy when that very sentence is retained with its source-owned scope.
    kept = [f for f in facts if f.get('track') or not any(
        other.get('track') and other['date'] == f['date'] and other['deadline_kind'] == f['deadline_kind']
        and other['citation'].get('page') == f['citation'].get('page')
        and other['_receipt_sentence'] == f['_receipt_sentence']
        for other in facts)]
    for fact in kept:
        fact.pop('_receipt_sentence', None)
    return kept


def _anticipated_cycle_table(api, opportunity_id, containers, document, stamp):
    """Four owned FHWA schedule columns, preserving 'anticipated' explicitly."""
    facts = []
    for container in containers:
        if container.get('page') is None:
            continue
        text = container['text']
        header = re.search(r'Competition\s+Year\s+Anticipated\s+Announcement\s+Date\s+'
            r'Anticipated\s+Application\s+Deadline\s+Anticipated\s+Award\s+Date', text)
        if not header:
            continue
        rows = container.get('layout_rows') or []
        for index, row in enumerate(rows):
            cells = [c.get('text', '') for c in row.get('cells', [])]
            if len(cells) != 4 or not re.fullmatch(r'FY 20\d{2}(?: &)?', cells[0]):
                continue
            cycle, announced, due, award = cells
            if cycle.endswith('&'):
                following = rows[index + 1].get('cells', []) if index + 1 < len(rows) else []
                if len(following) != 1 or not re.fullmatch(r'20\d{2}', following[0]['text']):
                    continue
                cycle += ' ' + following[0]['text']
            if not api.DATE_RE.fullmatch(announced) or not api.DATE_RE.fullmatch(due) or not re.fullmatch(r'(?:Spring|Summer|Fall|Winter) 20\d{2}', award):
                continue
            pattern = r'\s+'.join(re.escape(piece) for piece in (cycle + ' ' + announced + ' ' + due + ' ' + award).split())
            matches = list(re.finditer(pattern, text))
            if len(matches) != 1 or matches[0].start() < header.end():
                continue
            owned = matches[0]
            dates = list(api.DATE_RE.finditer(text, owned.start(), owned.end()))
            if len(dates) != 2:
                continue
            found = field_events(api, opportunity_id, container, document, stamp, label='Application deadline',
                start=dates[1].start(), end=dates[1].end(), field_id=f"anticipated-cycle:{container['page']}:{row['line']}")
            for fact in found:
                fact.update(cycle=cycle, date_qualifier='anticipated', estimated=True)
                fact['label'] = 'Anticipated application deadline'
                fact['display_value'] += ' (anticipated)'
                fact['cycle_citation'] = api.citation_for(container, document, owned.start(), owned.end(), stamp)
                fact['date_qualifier_citation'] = api.citation_for(container, document, header.start(), header.end(), stamp)
            container.setdefault('_native_field_values', []).append((owned.start(), owned.end()))
            facts.extend(found)
    return facts


def _pdf_submission_lists(api, opportunity_id, containers, document, stamp):
    """NIH's current cover and submission-instructions date-list fields."""
    facts = []
    date_list = api.DATE_RE.pattern + r'(?:\s*[,;]\s*' + api.DATE_RE.pattern + r')*'
    for container in containers:
        text = container['text']
        if container.get('page') is None or not re.search(
            r'(?m)^\s*(?:Submission requirements\s+and deadlines|Notice of Funding Opportunity)\s*$', text[:300]):
            continue
        for label in re.finditer(r'(?m)^\s*Application due(?: dates)?\s*:?\s*(?:Due on\s+)?', text):
            value = re.match(date_list, text[label.end():], re.I)
            if not value:
                continue
            end = label.end() + value.end()
            tail = text[end:]
            clock = re.match(r'\s*(?:at|by)\s+' + api.TIME_RE.pattern
                + r'(?:\s+local\s+time\s+of\s+(?:the\s+)?applicant\s+organization)?', tail, re.I)
            if ambiguous_value_tail(api, tail):
                container['_deadline_uncertain_component'] = True
                continue
            found = field_events(api, opportunity_id, container, document, stamp, label='Application due dates',
                start=label.end(), end=end, clock_label=clock.group() if clock else None,
                field_id=f"pdf-submission-list:{container['page']}:{label.start()}")
            if clock:
                for fact in found:
                    fact['clock_citation'] = api.citation_for(container, document, end, end + clock.end(), stamp)
            container.setdefault('_native_field_values', []).append((label.end(), end))
            facts.extend(found)
    return facts


def _pdf_application_rounds(api, opportunity_id, containers, document, stamp):
    """Submission rounds owned by a closing field or an explicit phase list."""
    facts = []
    weekday = r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
    for container in containers:
        text = container['text']
        if container.get('page') is None:
            continue
        for field in re.finditer(r'(?m)^\s*Closing Date Explanation\s*$', text):
            body = text[field.end():field.end() + 1500]
            stop = re.search(r'\n\s*(?:Have Questions\?|Submission Instructions|U\.S\. states)', body)
            body = body[:stop.start()] if stop else body
            # The four named WaterSMART rows are independent field values.
            pattern = re.compile(r'(?m)^\s*(?P<label>(?:First|Second|Third|Fourth) Round):\s*'
                r'(?P<date>' + api.DATE_RE.pattern + r')\s*,\s*' + api.TIME_RE.pattern, re.I)
            for row in pattern.finditer(body):
                found = field_events(api, opportunity_id, container, document, stamp, label='Application deadline:',
                    start=field.end() + row.start('date'), end=field.end() + row.end(),
                    field_id=f"closing:{container['page']}:{field.start()}:{row.start()}")
                for fact in found:
                    fact['cycle'] = row.group('label')
                    fact['cycle_citation'] = api.citation_for(container, document, field.end() + row.start(), field.end() + row.end(), stamp)
                facts.extend(found)
            periods = list(re.finditer(r'(?P<label>first|second) application period will\s+close\s+'
                + weekday + r',\s*(?P<date>' + api.DATE_RE.pattern + r')', body, re.I))
            for row in periods:
                found = field_events(api, opportunity_id, container, document, stamp, label='Application deadline:',
                    start=field.end() + row.start('date'), end=field.end() + row.end('date'),
                    field_id=f"closing:{container['page']}:{field.start()}:{row.start()}")
                # A separately repeated date/clock line can enrich only its own
                # same-date period, never the neighboring period's clock.
                clocks = list(re.finditer(r'(?m)^\s*(?:And\s+)?' + weekday + r',\s*'
                    + re.escape(row.group('date')) + r',\s*' + api.TIME_RE.pattern, body, re.I))
                for fact in found:
                    fact['cycle'] = row.group('label').capitalize() + ' submission period'
                    fact['cycle_citation'] = api.citation_for(container, document, field.end() + row.start(), field.end() + row.end(), stamp)
                    if len(clocks) == 1:
                        clock = api.TIME_RE.search(clocks[0].group())
                        fact['time'], fact['timezone'] = clock.group(1), api.deadline_timezone(clock)
                        fact['display_value'] += f" · {fact['time']} {fact['timezone']}"
                        fact['clock_citation'] = api.citation_for(container, document, field.end() + clocks[0].start(), field.end() + clocks[0].end(), stamp)
                facts.extend(found)
        header = re.search(r'(?P<agency>[A-Z][A-Z0-9-]{1,30}) will evaluate applications in\s+\w+ phases as follows:', text)
        if header:
            body = text[header.end():header.end() + 1400]
            pattern = re.compile(r'(?m)^\s*(?P<label>Phase (?:one|two|three|four) \([1-4]\)):\s*'
                + re.escape(header['agency']) + r' will evaluate applications submitted no later than\s+'
                r'(?P<date>' + api.DATE_RE.pattern + r')\.')
            rows = list(pattern.finditer(body))
            shared = re.search(r'All applications are due by\s+' + api.TIME_RE.pattern + r'\.?\s+on the date\(s\) above', body, re.I)
            for row in rows:
                if row['label'].split()[1] != ('one','two','three','four')[int(re.search(r'\((\d)\)', row['label'])[1])-1]:
                    continue
                found = field_events(api, opportunity_id, container, document, stamp, label='Application deadline:',
                    start=header.end() + row.start('date'), end=header.end() + row.end('date'),
                    field_id=f"application-phase:{container['page']}:{header.end() + row.start()}",
                    clock_label=shared.group() if shared else None)
                for fact in found:
                    fact['cycle'] = row['label']
                    fact['cycle_citation'] = api.citation_for(container, document, header.end() + row.start(), header.end() + row.end(), stamp)
                    if shared and fact.get('time'):
                        fact['clock_citation'] = api.citation_for(container, document, header.end() + shared.start(), header.end() + shared.end(), stamp)
                facts.extend(found)
    return facts


def _labeled_blocks(api, opportunity_id, containers, document, stamp, *, native):
    facts = []
    for container in containers:
        blocks = container.get('structure') or []
        # These sponsors publish real label/value blocks. No generic association
        # across unowned neighboring prose or table columns is permitted.
        pending = None
        for block in blocks:
            text = block['text'].strip()
            if block.get('toc') or block.get('repeated_header') or block.get('kind') == 'table_row':
                pending = None
                continue
            label_match = FIELD_LABEL.match(text)
            if label_match and len(text) < 180:
                pending = text
            if pending and api.DATE_RE.search(text):
                masked = api.DATE_RE.sub('', text)
                masked = api.TIME_RE.sub('', masked)
                # A standalone value, or the same explicit labeled field.
                if ((text == pending and len(list(api.DATE_RE.finditer(text))) == 1
                     and label_match and value_only(api, text[label_match.end():]))
                    or value_only(api, text)):
                    facts.extend(field_events(api, opportunity_id, container, document, stamp, label=pending,
                        start=block['span'][0], end=block['span'][1], field_id=block['block_id']))
                    continue
            if pending and text != pending:
                pending = None
        if native == 'pdf':
            text = container['text']
            # BLM's labeled application rounds share an explicit clock in the
            # same Closing Date Explanation field, bounded by the next field.
            closing = re.search(r'(?im)^Closing Date Explanation\s*\n(?P<body>.*?)(?=\n\s*(?:OMB Control Number|Have Questions|(?!Round\s)[A-Z][A-Za-z ]+:)|\Z)', text, re.S)
            if closing:
                body = closing.group('body')
                shared = re.search(r'Electronically submitted applications must be submitted no later than\s+'
                    r'(?P<clock>[^\n]{1,50}),?\s*on the listed\s+application due dates\.', body, re.I)
                for match in re.finditer(r'(?im)^(?P<round>Round\s+(?:One|Two|Three|\d+))\s+Applications Due:\s*'
                                         r'(?P<date>' + api.DATE_RE.pattern + r')', body):
                    start = closing.start('body') + match.start('date')
                    found = field_events(api, opportunity_id, container, document, stamp,
                        label='Application Due Date:', start=start, end=closing.start('body') + match.end('date'),
                        field_id=f"pdf:{container.get('page')}:{closing.start('body') + match.start()}",
                        clock_label=shared.group('clock').replace(',', ' ') if shared else None)
                    for fact in found:
                        fact['cycle'] = match.group('round')
                        if shared and fact.get('time'):
                            fact['clock_citation'] = api.citation_for(container, document,
                                closing.start('body') + shared.start(), closing.start('body') + shared.end(), stamp)
                    facts.extend(found)
            # CDMRP deadline bullets and CDC required-LOI/application fields.
            pattern = re.compile(r'(?im)(?:^|(?<=[•▪]))[ \t]*(?P<label>(?:Required\s+letter\s+of\s+intent|'
                r'Pre[\s-]?Application(?:/Preproposal)?\s*(?:\((?:Letter of Intent|Preproposal)\))?\s+Submission\s+Deadline|'
                r'(?:Full\s+)?Application(?:\s+submission)?\s*(?:deadline)?))\s*:?[ \t]*(?:\n\s*Due on\s+)?')
            for match in pattern.finditer(text):
                start = match.end()
                tail = text[start:start + 180]
                # Stop before a different bullet/field, even if its date is near.
                tail = re.split(r'[•▪]|\n\s*(?:Expected|Expiration|Invitation|End of|[A-Z][A-Za-z ]+:)', tail, maxsplit=1)[0]
                dates = list(api.DATE_RE.finditer(tail))
                if not dates:
                    continue
                before = tail[:dates[0].start()]
                before = api.TIME_RE.sub('', before)
                if re.search(r'[A-Za-z]', re.sub(r'\b(?:ET|deadline|Due on)\b', '', before, flags=re.I)):
                    continue
                end = start + dates[0].end()
                after = tail[dates[0].end():]
                if ambiguous_value_tail(api, after):
                    container['_deadline_uncertain_component'] = True
                    continue
                clock = re.match(r'\s*(?:at\s+)?' + api.TIME_RE.pattern, after, re.I)
                if clock:
                    end += clock.end()
                found = field_events(api, opportunity_id, container, document, stamp, label=match.group('label'),
                    start=start, end=end, field_id=f"pdf:{container.get('page')}:{match.start()}")
                for fact in found:
                    if re.search(r'Submission requirements\s+and deadlines', text, re.I) and (
                        'Due on' in match.group() or re.match(r'\s*Due on\b', text[start:], re.I)):
                        fact['source_section'] = 'submission_instructions'
                    elif re.search(r'\bKey dates\b', text, re.I):
                        fact['source_section'] = 'key_dates_summary'
                facts.extend(found)
    return facts


# Explicit field labels in the measured PDF cover/Key Dates blocks and ARPA-H
# notice pages. Non-submission labels are boundaries too: their dates cannot
# acquire the next application's label when a cached citation loses line breaks.
_LOCAL_FIELD = re.compile(
    r'(?<![\w-])(?P<label>'
    r'(?:General\s+|Technical\s+|NOFO\s+|FAQ\s+)?Questions?\s+(?:Submission\s+)?Deadline'
    r'|Deadline\s+for\s+Submission\s+of\s+(?:Questions|Applications)'
    r'|Closing\s+Date\s+for\s+Applications'
    r'|Key\s+Dates\s+Applications\s+must\s+be\s+received\s+by'
    r'|(?:actual\s+)?due\s+date\s+for\s+Application\s+Submission\s+in\s+GrantSolutions\s+is'
    r'|Pre[\s-]?proposals?\s+(?:are\s+)?due'
    r'|(?P<period>First|Second|Third)(?:\s+and\s+final)?\s+application\s+submission\s+period\s+due\s+date\s+is'
    r'|Deadline\s+for\s+Letter\s+of\s+Intent(?:\s*\(LOI\))?\s+submission'
    r'|Due\s+Date\s+for\s+(?:Letter\s+of\s+Intent(?:\s*\(LOI\))?|Applications|Informational\s+Conference\s+Call)'
    r'|(?:(?:Not\s+required|Required|Optional)\s+)?(?:Letter\s+of\s+(?:Intent|Interest)|Concept\s+Paper|White\s+Paper)\s+(?:Submission\s+)?Deadline'
    r'|(?:(?:Full\s+)?Applications?|(?:Full\s+)?Proposals?|Solution\s+(?:Summary|Video)|'
    r'Pre[\s-]?Application(?:/Preproposal)?(?:\s*\((?:Letter of Intent|Preproposal)\))?)'
    r'\s+(?:Submission\s+)?(?:Deadline|Due(?:\s+Date)?|Requested\s+by)(?:\(s\))?'
    r'(?:\s*\((?P<scope>[^()\n]{1,160})\))?'
    r'|(?:Publication|NOFO\s+Issuance|Estimated\s+Project\s+Start|Expected\s+(?:Award|Start)|'
    r'(?:Anticipated|Estimated)\s+(?:Award|Performance\s+Period\s+(?:Start|End)))\s+Date'
    r'|Application\s+Package\s+Available|Possible\s+Start\s+Dates|Informational\s+call'
    r'|Notification\s+of\s+Selection\s+for\s+Award|Start\s+Date\s+of\s+Grant'
    r')(?!\w)\s*:?[ \t\r\n]*', re.I)


def _local_cover_fields(api, opportunity_id, containers, document, stamp):
    facts = []
    for container in containers:
        text = container['text']
        labels = list(_LOCAL_FIELD.finditer(text))
        for index, field in enumerate(labels):
            header = (re.search(r'Key Dates\s+Anticipated Schedule of Events\s*\*?\s*'
                r'Event\s+Date\s*\(MM/DD/YEAR\)\s+Time\s*\(Local Eastern Time\)',
                text[max(0, field.start() - 420):field.start()], re.I)
                if container.get('page') is not None else None)
            if api.SUBMISSION_GROUP_PREFIX_RE.search(text[max(0, field.start() - 100):field.start()]):
                continue  # The existing grouped-field reader owns this form.
            if not (':' in field.group() or field.group('scope') or field.group('period')
                    or len(labels) > 1 or header or field.group('label').lower().startswith('key dates')
                    or re.search(r'Closing Date Explanation|GrantSolutions', text, re.I)):
                # An unstructured sentence is owned by deadline_context. A
                # recognized word inside arbitrary prose is not a native field.
                continue
            start = field.end()
            limit = labels[index + 1].start() if index + 1 < len(labels) else len(text)
            # A complete named field has an immediate value prefix. Never
            # search through intervening prose for a convenient later date.
            value = text[start:limit]
            dates = list(api.DATE_RE.finditer(value))
            if not dates:
                continue
            candidate = dates[0]
            if api._REQUIREMENT.match(value[candidate.end():].lstrip()):
                continue  # Preserve the existing bounded postfix-marker reader.
            prefix = api._without_clocks(value[:candidate.start()])
            # Measured IES cover fields sometimes print a clock without AM/PM.
            # The immediate, independently labeled date is still proved; the
            # incomplete clock is not. Do not invent the missing meridiem.
            uncertain_clock = re.fullmatch(r'\s*\d{1,2}:[0-5]\d(?::[0-5]\d)?\s+'
                r'(?:Eastern|Central|Mountain|Pacific)\s+Time\s+on\s*', prefix, re.I)
            if uncertain_clock:
                prefix = ''
                container['_deadline_uncertain_component'] = True
            prefix = re.sub(r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|on|by|at)\b', '', prefix, flags=re.I)
            if re.search(r'[^\s,:()\[\]]', prefix) or candidate.start() > 100:
                continue
            # These source fields own at least the immediate value. Even a
            # questions date that is not published must block fallback leakage.
            container.setdefault('_native_field_values', []).append((start, start + candidate.end()))
            stage = stage_for(field.group('label'))
            if not stage:
                continue
            if any(name != stage and re.search(rf'\b(?:{pattern})\s*$', text[max(0, field.start() - 80):field.start()], re.I)
                   for name, pattern in STAGES):
                container['_deadline_uncertain_component'] = True
                continue  # A second, unseparated stage is not field ownership.
            # An explicit field can contain a contiguous date list. Only value
            # separators may join its entries; intervening prose ends the list.
            last = candidate
            for following in dates[1:]:
                if not value_only(api, value[last.end():following.start()]):
                    break
                last = following
            tail = value[candidate.end():]
            boundary = next(api._deadline_boundaries(tail, 0, len(tail)), None)
            local_tail = tail[:boundary[0]] if boundary else tail
            if last is candidate and api.DATE_RE.search(local_tail):
                continue
            if ambiguous_value_tail(api, local_tail):
                container['_deadline_uncertain_component'] = True
                continue  # Keep the same ambiguity guard at the native boundary.
            end = start + last.end()
            tail = value[last.end():]
            clock = re.match(r'\s*[,;]?\s*\(?\s*(?:at\s+|by\s+)?' + api.TIME_RE.pattern, tail, re.I)
            if clock:
                clock_end, valid = api._clock_extent(tail, clock)
                if '(' in clock.group(0).split(clock.group(1), 1)[0]:
                    valid = valid and bool(re.match(r'\s*\)', tail[clock_end:]))
                if valid:
                    end += clock_end
            found = field_events(api, opportunity_id, container, document, stamp,
                label=field.group('label'), start=start, end=end,
                field_id=f"cover:{container.get('page')}:{field.start()}")
            if field.group('period'):
                for fact in found:
                    fact['cycle'] = field.group('period').capitalize() + ' submission period'
                    fact['cycle_citation'] = api.citation_for(container, document, field.start(), field.end(), stamp)
            scope = field.group('scope')
            if scope:
                # Applicant-routing labels are preserved verbatim as source
                # groups, not inferred eligibility or new/resubmission classes.
                if api.DATE_RE.search(scope):
                    continue
                if not api.TIME_RE.search(scope) and not re.fullmatch(r'required|optional', scope, re.I):
                    for fact in found:
                        fact['track'] = scope
                        fact['cycle_citation'] = api.citation_for(container, document, field.start(), field.end(), stamp)
            # ONR's measured schedule table declares one clock column. Its
            # explicit header and proposal row must both survive in the same
            # bounded source block before the header can supply a missing zone.
            if container.get('page') is not None:
                if header:
                    for fact in found:
                        if fact.get('time') and not fact.get('timezone'):
                            fact['timezone'] = 'Eastern'
                            fact['display_value'] += ' Eastern'
                            fact['clock_citation'] = api.citation_for(container, document,
                                max(0, field.start() - 420) + header.start(), max(0, field.start() - 420) + header.end(), stamp)
            facts.extend(found)
    return facts


def _named_phase_and_delivery_fields(api, opportunity_id, containers, document, stamp):
    """USDA's named application phases and NOAA's explicit emailed deadline.

    Both forms retain an owned submission label. No transport address is used
    as a retrieval route, and phase numbers do not imply prerequisites.
    """
    facts = []
    for container in containers:
        text = container['text']
        paper = re.compile(r'\bIf you received a waiver to submit a paper proposal, it must be received by '
            r'(?P<sponsor>[A-Z][A-Za-z ]{1,50}) no later than (?P<date>' + api.DATE_RE.pattern + r')', re.I)
        for match in paper.finditer(text):
            found = field_events(api, opportunity_id, container, document, stamp,
                label='Application deadline:', start=match.start('date'), end=match.end('date'),
                field_id=f"paper-waiver:{container.get('page')}:{match.start()}", application_class='paper_waiver')
            for fact in found:
                fact['track'] = 'Paper submission with waiver'
                fact['obligation'] = 'conditional'
                fact['cycle_citation'] = api.citation_for(container, document, match.start(), match.end(), stamp)
            facts.extend(found)
            container.setdefault('_native_field_values', []).append((match.start('date'), match.end('date')))
        for header in re.finditer(r'\bAPPLICATION DEADLINES?\s*:\s*(?=Phase\s+\d+\s*:)', text, re.I):
            position = header.end()
            for _ in range(12):
                row = re.match(r'(?P<phase>Phase\s+\d+)\s*:\s*(?P<date>' + api.DATE_RE.pattern + r')\s*', text[position:], re.I)
                if not row:
                    break
                start, end = position + row.start('date'), position + row.end('date')
                found = field_events(api, opportunity_id, container, document, stamp,
                    label='Application Deadline:', start=start, end=end, field_id=f"phase:{container.get('page')}:{position}")
                for fact in found:
                    fact['track'] = row.group('phase')
                    fact['cycle_citation'] = api.citation_for(container, document, position, position + row.end(), stamp)
                facts.extend(found)
                container.setdefault('_native_field_values', []).append((start, end))
                position += row.end()
        delivery = re.compile(r'(?P<label>(?:Required\s+)?Pre[\s-]?proposals?)\s+must\s+be\s+received\s+'
            r'(?:via\s+e-mail|by\s+electronic\s+mail)\s+'
            r'(?P<route>[^;\n]{1,130}?[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\)?)\s+by\s+'
            r'(?P<value>' + api.TIME_RE.pattern + r'\s+on\s+' + api.DATE_RE.pattern + r')', re.I)
        for match in delivery.finditer(text):
            if api.DATE_RE.search(match.group('route')) or re.search(r'\b(?:if|when|whether)\s*$', text[max(0, match.start()-30):match.start()], re.I):
                continue
            found = field_events(api, opportunity_id, container, document, stamp,
                label=match.group('label'), start=match.start('value'), end=match.end('value'),
                field_id=f"email-submission:{container.get('page')}:{match.start()}")
            facts.extend(found)
            container.setdefault('_native_field_values', []).append((match.start('value'), match.end('value')))
    return facts


def _pdf_submission_rows(api, opportunity_id, containers, document, stamp):
    """Cover tables with a short stage label, date value and submission URL.

    Retained cells establish ownership even when the label omits 'Due Date'.
    The URL is source context only; it is never fetched by this reader.
    """
    facts = []
    for container in containers:
        if container.get('page') is None:
            continue
        for row in container.get('layout_rows') or []:
            cells = row.get('cells') or []
            if len(cells) != 3:
                continue
            label, value, route = [c.get('text') or '' for c in cells]
            if not re.fullmatch(r'Letter of Intent|Concept Paper|White Paper|Pre[ -]Application', label, re.I):
                continue
            if not api.DATE_RE.fullmatch(value) or not re.fullmatch(r'https://\S+', route):
                continue
            matches = list(re.finditer(re.escape(label) + r'\s+' + re.escape(value), container['text']))
            if len(matches) != 1:
                continue
            end = matches[0].end()
            container.setdefault('_native_field_values', []).append((end - len(value), end))
            facts.extend(field_events(api, opportunity_id, container, document, stamp,
                label=label, start=end - len(value), end=end, field_id=f"pdf-cover-row:{container['page']}:{row['line']}"))
        # Some PDFs split individual digits into separate layout cells. The
        # complete physical text line still proves this three-field row; do
        # not concatenate cells or carry a missing value across another row.
        offset = 0
        for line in container['text'].splitlines(keepends=True):
            row = re.fullmatch(r'\s*(?P<label>Letter of Intent|Concept Paper|White Paper|Pre[ -]Application)\s+'
                r'(?P<value>' + api.DATE_RE.pattern + r')\s+https://\S+\s*', line, re.I)
            if row:
                container.setdefault('_native_field_values', []).append((offset + row.start('value'), offset + row.end('value')))
                facts.extend(field_events(api, opportunity_id, container, document, stamp,
                    label=row.group('label'), start=offset + row.start('value'), end=offset + row.end('value'),
                    field_id=f"pdf-submission-line:{container['page']}:{offset}"))
            offset += len(line)
    return facts


def _pdf_schedule_rows(api, opportunity_id, containers, document, stamp):
    """Measured schedule columns: a complete date/value and a named event.

    EPA prints values before labels. ONR's Event/Date/Time table includes
    recommended submissions among notifications. Physical rows, complete
    labels and a unique matching source span must agree before publishing.
    Flattened legacy quotations cannot reconstruct these column relationships.
    """
    facts = []
    for container in containers:
        text = container['text']
        if container.get('page') is None:
            continue
        rows = container.get('layout_rows') or []
        schedule_header = None
        for row in rows:
            cells = [c.get('text') or '' for c in row.get('cells') or []]
            if cells == ['Event', 'Date', 'Time']:
                schedule_header = row['line']
                continue
            label, value, recommended = None, None, False
            if len(cells) == 2 and FIELD_LABEL.fullmatch(cells[1].rstrip(':') + ':') and value_only(api, cells[0]):
                value, label = cells
                pattern = re.escape(value) + r'\s+' + re.escape(label)
            elif (schedule_header is not None and row['line'] - schedule_header <= 16 and len(cells) == 3
                  and re.fullmatch(r'Recommended (?:White Paper|Full Proposal) Submission', cells[0], re.I)
                  and api.DATE_RE.fullmatch(cells[1]) and api.TIME_RE.fullmatch(cells[2])):
                label, value, clock = cells
                value += ' ' + clock
                recommended = True
                pattern = re.escape(label) + r'\s+(?:Date\s*\*?\s+)?' + re.escape(cells[1]) + r'\s+' + re.escape(clock)
            else:
                continue
            matches = list(re.finditer(pattern, text))
            if len(matches) != 1:
                continue
            owned = matches[0]
            date = api.DATE_RE.search(text, owned.start(), owned.end())
            if not date or len(list(api.DATE_RE.finditer(text, owned.start(), owned.end()))) != 1:
                continue
            start = date.start()
            end = owned.end() if recommended else start + len(value)
            found = field_events(api, opportunity_id, container, document, stamp,
                label=label, start=start, end=end, field_id=f"pdf-schedule-row:{container['page']}:{row['line']}")
            container.setdefault('_native_field_values', []).append((start, end))
            for fact in found:
                if recommended:
                    fact['date_qualifier'] = 'recommended'
                    fact['display_value'] += ' (recommended submission date)'
                    fact['label'] = 'Recommended ' + fact['stage'].replace('_', ' ') + ' submission'
                    fact['date_qualifier_citation'] = api.citation_for(container, document, owned.start(), owned.end(), stamp)
            facts.extend(found)
    return facts


def _arpa_submission_fields(api, opportunity_id, containers, document, stamp, facts):
    """ARPA-H's summary instructions and explicitly topic-labeled package rows.

    These are bounded source structures, not a nearest-stage/date inference.
    A generic submission inherits a stage only from its adjacent named action.
    """
    for container in containers:
        text = container['text']
        summary = re.compile(r'Sign-in required to submit a Solution Summary\.\s*'
            r'Submissions must be submitted by\s+(?P<value>' + api.DATE_RE.pattern +
            r')(?:\s*\((?P<clock>[^()\n]{1,55})\))?', re.I)
        for match in summary.finditer(text):
            end = match.end('clock') if match.group('clock') else match.end('value')
            found = field_events(api, opportunity_id, container, document, stamp,
                label='Solution Summary Due:', start=match.start('value'), end=end,
                field_id=f'arpa-summary:{match.start()}')
            container.setdefault('_native_field_values', []).append((match.start('value'), match.end('value')))
            facts.extend(found)

        # An abbreviated "A summary" has meaning only in this immediately
        # preceding Solution Summary field, never elsewhere in the notice.
        required = re.compile(r'Solution Summary\s+(?:Due|Requested by):?\s*' + api.DATE_RE.pattern +
            r'\s*[.]?\s*(?P<rule>A summary is required to submit a full proposal\.)', re.I)
        for match in required.finditer(text):
            owned_date = api.parse_document_date(api.DATE_RE.search(match.group()).group())
            for fact in facts:
                if (fact.get('deadline_kind') == 'preapplication' and fact.get('date') == owned_date
                    and fact.get('citation', {}).get('page') == container.get('page')):
                    fact.update(required=True, obligation='required', requirement_citation=api.citation_for(
                        container, document, match.start('rule'), match.end('rule'), stamp))

        # The season is explicitly prospective, not an exact calendar date.
        unknown = re.compile(r'Full Proposal Due:\s*Anticipated (?:Spring|Summer|Fall|Winter) 20\d{2}\s*'
            r'(?P<rule>Invited submissions only, details to follow\.)', re.I)
        for match in unknown.finditer(text):
            citation = api.citation_for(container, document, match.start(), match.end(), stamp)
            facts.append(api.make_fact(opportunity_id, 'submission_requirement', 'Full application date not announced',
                None, 'Date not announced; invited submissions only', citation, deadline_kind='application', stage='application',
                date=None, time=None, timezone=None, application_class='unspecified', required=None, obligation='unknown',
                field_authority='official_notice_field', parser_version=SCHEDULE_VERSION, invitation_required=True,
                prerequisite='invitation', prerequisite_citation=api.citation_for(
                    container, document, match.start('rule'), match.end('rule'), stamp)))

        heading = re.compile(r'Technical Presentation Deck, Cost Proposal, and Task Description Document Due:\s*', re.I)
        for field in heading.finditer(text):
            # Each contiguous row owns its own date, clock and topic list. Stop
            # at the first non-row; never borrow a clock from the summary.
            position = field.end()
            for _ in range(12):
                row = re.match(r'(?P<value>' + api.DATE_RE.pattern + r')\s+at\s+' + api.TIME_RE.pattern +
                    r'(?:\s*\(noon\))?\s+for\s+(?P<topics>Topics?\s+\d+(?:\s*,\s*(?:and\s+)?\d+)*)\s*\.', text[position:], re.I)
                if not row:
                    break
                found = field_events(api, opportunity_id, container, document, stamp, label='Proposal Due:',
                    start=position, end=position + row.start('topics'), field_id=f'arpa-package:{field.start()}:{position}')
                for fact in found:
                    fact['track'] = row.group('topics')
                    fact['citation'].setdefault('structural_reference', {})['field_label'] = field.group().strip()
                    fact['cycle_citation'] = api.citation_for(container, document, position,
                        position + row.end(), stamp)
                facts.extend(found)
                container.setdefault('_native_field_values', []).append((position, position + row.end()))
                position += row.end()
                position += len(text[position:]) - len(text[position:].lstrip())


def submission_windows(api, text):
    """Explicit LOI opening/closing pairs in the measured USDA Dates fields."""
    date = rf'(?:{api.MONTH_PATTERN}\.?\s+\d{{1,2}}(?:\s*,\s*|\s+)20\d{{2}}|{api.DATE_RE.pattern})'
    subject = r'(?:LOIs?|Letters of (?:Interest|Intent)(?:\s*\(LOI\))?)'
    pattern = re.compile(rf'\b{subject}\s+(?:can|must)\s+be\s+submitted\s+beginning\s+at\s+'
        rf'(?P<open_clock>{api.TIME_RE.pattern})(?:\s*\(ET\))?\s+on\s+(?P<open>{date})\s*,?\s*'
        rf'(?:and\s+)?until\s+(?P<close_clock>{api.TIME_RE.pattern})\s+on\s+(?P<close>{date})', re.I)
    for match in pattern.finditer(text):
        if re.search(r'\b(?:if|when|whether)\s*$', text[max(0, match.start() - 30):match.start()], re.I):
            continue
        opening, closing = [api.parse_document_date(match.group(key)) for key in ('open', 'close')]
        if not opening or not closing or closing < opening:
            continue
        clock = api.TIME_RE.fullmatch(match.group('close_clock'))
        if clock:
            yield match, opening, closing, clock


def explicit_submission_window_end(api, text):
    """Grants.gov's closing explanation distinguishes entry from processing.

    The named portal submission and final acceptance cutoff must both be
    explicitly stated in this one structured note. This never changes dates.
    """
    closing = list(re.finditer(r'\bClosing Date for this funding opportunity is\s+(' + api.DATE_RE.pattern + r')', text, re.I))
    actual = list(re.finditer(r'\bactual due date for Application Submission in GrantSolutions is\s+(' + api.DATE_RE.pattern + r')', text, re.I))
    if len(closing) != 1 or len(actual) != 1 or closing[0].end() >= actual[0].start():
        return None
    between = text[closing[0].end():actual[0].start()]
    if not re.search(r'funding opportunity closes and applications can no longer be accepted', between, re.I):
        return None
    end, entry = [api.parse_document_date(m.group(1)) for m in (closing[0], actual[0])]
    return (end, entry) if end and entry and entry < end else None


def _submission_windows(api, opportunity_id, containers, document, stamp):
    facts = []
    for container in containers:
        for match, opening, closing, clock in submission_windows(api, container['text']):
            citation = api.citation_for(container, document, match.start(), match.end(), stamp)
            citation.setdefault('structural_reference', {}).update(field_label='Letter of Intent submission window',
                field_id=f"submission-window:{container.get('page')}:{match.start()}")
            facts.append(api.make_fact(opportunity_id, 'deadline', 'Letter of intent deadline', closing,
                closing + f" · {clock.group(1)}" + (f" {api.deadline_timezone(clock)}" if clock.group(2) else ''), citation,
                deadline_kind='letter_of_intent', date=closing, time=clock.group(1), timezone=api.deadline_timezone(clock),
                subject='submission', stage='letter_of_intent', required=None, obligation='unknown',
                application_class='unspecified', window_start=opening, field_authority='official_notice_field',
                invitation_required=None, prerequisite=None, parser_version=SCHEDULE_VERSION))
            container.setdefault('_native_field_values', []).append((match.start(), match.end()))
    return facts


def consolidate_final_period_aliases(api, facts):
    """An explicitly final named period can qualify its unclocked cutoff copy."""
    kept = []
    for fact in facts:
        if (fact.get('type') != 'deadline' or fact.get('deadline_kind') != 'application'
            or any(fact.get(k) is not None for k in ('time', 'timezone', 'required', 'cycle', 'track'))
            or fact.get('application_class') not in (None, 'unspecified')):
            kept.append(fact)
            continue
        citation = fact.get('citation') or {}
        closing = list(re.finditer(r'\bfinal closing date of\s+(' + api.DATE_RE.pattern + r')', citation.get('quote') or '', re.I))
        candidates = [other for other in facts if other is not fact and other.get('type') == 'deadline'
            and other.get('deadline_kind') == 'application' and other.get('date') == fact.get('date')
            and other.get('required') is None and other.get('track') is None
            and other.get('application_class') in (None, 'unspecified')
            and other.get('field_authority') == 'official_notice_field'
            and all(other.get('citation', {}).get(k) == citation.get(k) for k in ('document_url', 'sha256'))
            and re.fullmatch(r'(?:First|Second|Third) and final application submission period due date is',
                (other.get('citation', {}).get('structural_reference') or {}).get('field_label', ''), re.I)]
        if not (len(closing) == 1 and api.parse_document_date(closing[0].group(1)) == fact.get('date') and len(candidates) == 1):
            kept.append(fact)
    return kept


def consolidate_preliminary_aliases(facts):
    """An explicit 'Pre-Application (Preproposal/LOI)' names one source stage.

    Drop only a redundant clockless generic cover copy from the identical
    document/date/scope. Distinct or contradictory values remain independent.
    """
    aliases = []
    for fact in facts:
        if fact.get('type') != 'deadline' or fact.get('field_authority') != 'official_notice_field':
            continue
        citation = fact.get('citation') or {}
        label = (citation.get('structural_reference') or {}).get('field_label') or citation.get('quote') or ''
        match = re.search(r'\bPre[\s-]?Application(?:/Preproposal)?\s*\((?:Letter of Intent|Preproposal)\)', label, re.I)
        if match and stage_for(match.group()) == fact.get('deadline_kind'):
            aliases.append(fact)
    result = []
    for fact in facts:
        if (fact.get('type') == 'deadline' and fact.get('deadline_kind') == 'preapplication'
            and fact.get('field_authority') == 'official_notice_field' and not fact.get('time') and not fact.get('timezone')):
            citation = fact.get('citation') or {}
            matches = [other for other in aliases if fact.get('date') == other.get('date')
                and citation.get('sha256') and all(citation.get(key) == other.get('citation', {}).get(key) for key in ('sha256', 'document_url'))
                and all((fact.get(key) or 'unspecified') == (other.get(key) or 'unspecified') for key in ('application_class', 'cycle', 'track'))
                and (fact.get('required') is None or fact.get('required') == other.get('required'))]
            if len({other['deadline_kind'] for other in matches}) == 1:
                continue
        result.append(fact)
    return result


def _nsf_submission_component(api, opportunity_id, containers, document, stamp):
    """Read NSF's explicit current-program date cards, never recurrence prose.

    A parent item owns its submission stage; each nested date item owns its
    date/window and program descriptions. Sidebar contents stay isolated.
    """
    items, clocks = {}, []
    for container in containers:
        if container.get('source_component') != 'nsf_submission_fields':
            continue
        for block in container.get('structure', []):
            ancestors = block.get('ancestors', [])
            classes = set().union(*(set(a.get('class', '').split()) for a in ancestors))
            if 'program-due-dates__due-by-time-text' in classes:
                clocks.append((container, block))
            item = next((a for a in ancestors if 'program-due-dates__item' in a.get('class', '').split()), None)
            if not item or not item.get('source_position'):
                continue
            owner = items.setdefault(tuple(item['source_position']), {'labels': [], 'rows': {}})
            if 'program-due-dates__sub-type' in classes:
                owner['labels'].append((container, block))
                continue
            row = next((a for a in ancestors if 'program-due-dates__due-date-item' in a.get('class', '').split()), item)
            fields = owner['rows'].setdefault(tuple(row['source_position']), {'dates': [], 'tracks': []})
            for key, suffix in [('dates', 'date-type'), ('tracks', 'desc')]:
                if 'program-due-dates__' + suffix in classes:
                    fields[key].append((container, block))
    clock_text = clocks[0][1]['text'] if len(clocks) == 1 else ''
    facts = []
    for owner in items.values():
        if len(owner['labels']) != 1:
            continue
        label_container, label_block = owner['labels'][0]
        label = label_block['text']
        if not re.fullmatch(r'(?:Full proposal|Letter of intent|Preliminary proposal)(?: accepted anytime)?', label, re.I):
            continue
        for row_id, row in owner['rows'].items():
            tracks = row['tracks'] or [(None, None)]
            if len(row['dates']) != 1:
                # Scoped rolling facts retain their actual program and label.
                if row['dates'] or not label.lower().endswith(' accepted anytime'):
                    continue
                values = [(None, None)]
                opening = None
                container, block = label_container, label_block
            else:
                container, block = row['dates'][0]
                text = block['text']
                shape = re.fullmatch(r'(.+?)\s+-\s+(Window|Deadline date)', text, re.I)
                dates = list(api.DATE_RE.finditer(shape[1])) if shape else []
                if not shape or not value_only(api, shape[1]) or len(dates) != (2 if shape[2].lower() == 'window' else 1):
                    container['_deadline_uncertain_component'] = True
                    continue
                parsed = [api.parse_document_date(m.group()) for m in dates]
                if not all(parsed) or parsed[-1] < parsed[0]:
                    container['_deadline_uncertain_component'] = True
                    continue
                opening = parsed[0] if len(parsed) == 2 else None
                values = field_events(api, opportunity_id, container, document, stamp, label=label,
                    start=block['span'][0] + dates[-1].start(), end=block['span'][0] + dates[-1].end(),
                    clock_label=clock_text, field_id='nsf-date:' + str(row_id), application_class='new')
            for track_container, track_block in tracks:
                for value in values:
                    if value == (None, None):
                        citation = api.citation_for(container, document, *block['span'], stamp)
                        value = api.make_fact(opportunity_id, 'submission_requirement', 'Submission accepted anytime', None,
                            'Accepted anytime', citation, deadline_kind=stage_for(label), stage=stage_for(label),
                            date=None, time=None, timezone=None, required=None, obligation='unknown', application_class='new',
                            rolling=True, rolling_citation=citation, field_authority='official_notice_field', parser_version=SCHEDULE_VERSION)
                    fact = dict(value)
                    fact['track'] = track_block['text'] if track_block else None
                    if track_block:
                        fact['track_citation'] = api.citation_for(track_container, document, *track_block['span'], stamp)
                    if opening:
                        fact['window_start'] = opening
                    if fact.get('time') and len(clocks) == 1:
                        fact['clock_citation'] = api.citation_for(clocks[0][0], document, *clocks[0][1]['span'], stamp)
                    facts.append(fact)
    return facts


def extract_native(api, opportunity_id, containers, document, stamp, review_queue=None):
    host = (urlparse(document.get('url') or '').hostname or '').casefold()
    facts = _nsf_submission_component(api, opportunity_id, containers, document, stamp) if host in {'www.nsf.gov', 'nsf.gov'} else []
    containers = [c for c in containers if c.get('source_component') != 'nsf_submission_fields']
    facts.extend(_table_fields(api, opportunity_id, containers, document, stamp))
    if host == 'grants.nih.gov':
        facts.extend(_nih_fields(api, opportunity_id, containers, document, stamp))
        facts.extend(_nih_key_dates_table(api, opportunity_id, containers, document, stamp))
    if host in {'www.nsf.gov', 'nsf.gov', 'eere-exchange.energy.gov', 'arpa-e-foa.energy.gov'}:
        facts.extend(_labeled_blocks(api, opportunity_id, containers, document, stamp, native='html'))
    if host in {'www.nsf.gov', 'nsf.gov'}:
        facts.extend(_nsf_concept_cycles(api, opportunity_id, containers, document, stamp))
    has_pdf = any(c.get('page') is not None for c in containers)
    if has_pdf:
        facts.extend(_noaa_annual_dates(api, opportunity_id, containers, document, stamp))
        facts.extend(_pdf_submission_lists(api, opportunity_id, containers, document, stamp))
        facts.extend(_pdf_application_rounds(api, opportunity_id, containers, document, stamp))
        facts.extend(_named_phase_and_delivery_fields(api, opportunity_id, containers, document, stamp))
        facts.extend(_submission_windows(api, opportunity_id, containers, document, stamp))
        facts.extend(_pdf_submission_rows(api, opportunity_id, containers, document, stamp))
        facts.extend(_pdf_schedule_rows(api, opportunity_id, containers, document, stamp))
        facts.extend(_pdf_key_dates(api, opportunity_id, containers, document, stamp))
        facts.extend(_labeled_blocks(api, opportunity_id, containers, document, stamp, native='pdf'))
        owned = {(f['deadline_kind'], f['date']) for f in facts}
        facts.extend(f for f in _owned_submission_sentences(api, opportunity_id, containers, document, stamp)
                     if (f['deadline_kind'], f['date']) not in owned)
        owned = {(f['deadline_kind'], f['date']) for f in facts}
        facts.extend(f for f in _anticipated_cycle_table(api, opportunity_id, containers, document, stamp)
                     if (f['deadline_kind'], f['date']) not in owned)
    if has_pdf or host in {'arpa-h.gov', 'www.arpa-h.gov', 'simonsfoundation.org', 'www.simonsfoundation.org'}:
        owned = {(f['deadline_kind'], f['date']) for f in facts}
        # The more specific table/row reader retains application class/cycle
        # ownership. A cover-field fallback cannot create an unclassified copy.
        facts.extend(f for f in _local_cover_fields(api, opportunity_id, containers, document, stamp)
                     if (f['deadline_kind'], f['date']) not in owned)
    if host in {'arpa-h.gov', 'www.arpa-h.gov'}:
        _arpa_submission_fields(api, opportunity_id, containers, document, stamp, facts)
    for fact in facts:
        # Assign complete event identities before any diagnostic references.
        fact['id'] = api.evidence_id(opportunity_id, fact['type'], fact['label'],
            {key: fact.get(key) for key in ('date', 'deadline_kind', 'application_class', 'cycle', 'track')}, fact['citation'])
    # CDC's detailed submission instructions and key-date summary are separately
    # identified structures. Prefer the instructions while disclosing a conflict.
    instructions = {(f['deadline_kind'], f['application_class']): f for f in facts
                    if f.get('source_section') == 'submission_instructions'}
    kept = []
    for fact in facts:
        detailed = instructions.get((fact['deadline_kind'], fact['application_class']))
        if detailed and fact.get('source_section') == 'key_dates_summary' and fact['date'] != detailed['date']:
            if review_queue is not None:
                review_queue.append({'type': 'deadline_source_conflict', 'status': 'needs_review',
                    'label': 'Submission instructions conflict with the notice summary; verify the cited dates',
                    'evidence_ids': [detailed['id']], 'withheld_fact_ids': [fact['id']],
                    'deadline_kind': fact['deadline_kind'],
                    'alternate_date': fact['date'], 'alternate_citation': fact['citation']})
            continue
        kept.append(fact)
    # Deduplicate identical fields while preserving class/track distinctions.
    unique = {}
    clock_conflicts = set()
    for fact in kept:
        key = (fact['deadline_kind'], fact['date'], fact['application_class'], fact.get('cycle'), fact.get('track'))
        if fact.pop('clock_conflict', False):
            clock_conflicts.add(key)
        prior = unique.get(key)
        if prior is None or (not prior['time'] and fact['time']) or (
                prior.get('time') and fact.get('time') and not prior.get('timezone') and fact.get('timezone')
                and clock_key(prior['time'], None) == clock_key(fact['time'], None)):
            unique[key] = fact
        elif prior['required'] is None and fact['required'] is not None:
            prior['required'], prior['obligation'] = fact['required'], fact['obligation']
        if prior and prior.get('time') and fact.get('time'):
            left, right = clock_key(prior['time'], prior.get('timezone')), clock_key(fact['time'], fact.get('timezone'))
            if left[0] != right[0] or (left[1] and right[1] and left[1] != right[1]):
                clock_conflicts.add(key)
    for key in clock_conflicts:
        fact = unique[key]
        fact['time'], fact['timezone'], fact['display_value'] = None, None, fact['date']
        if review_queue is not None:
            review_queue.append({'type': 'deadline_evidence_withheld', 'status': 'needs_review',
                'label': 'Conflicting source clocks were withheld; verify the official submission time',
                'evidence_ids': [fact['id']]})
    facts = list(unique.values())
    apply_requirements(api, opportunity_id, facts, containers, document, stamp)
    return consolidate_preliminary_aliases(facts)


def _nsf_concept_cycles(api, opportunity_id, containers, document, stamp):
    """NSF's explicit concept-outline date / fiscal-cycle pairs, not date proximity."""
    facts = []
    for container in containers:
        for block in container.get('structure') or []:
            text = block['text']
            if not re.search(r'\bmust submit a Concept Outline\b', text, re.I):
                continue
            pairs = list(re.finditer(r'\bby\s+(?P<date>' + api.DATE_RE.pattern + r')\s+for proposal submission for the '
                r'(?:Fiscal Year\s*\(FY\)|FY)\s+(?P<cycle>20\d{2})\s+cycle\b', text, re.I))
            # Every date in this owned clause must be one of its explicit pairs.
            if not pairs or len(pairs) != len(list(api.DATE_RE.finditer(text))):
                continue
            for pair in pairs:
                start = block['span'][0] + pair.start('date')
                end = block['span'][0] + pair.end('date')
                found = field_events(api, opportunity_id, container, document, stamp,
                    label='Required Concept Outline Submission Deadline:', start=start, end=end, field_id=block['block_id'])
                for fact in found:
                    fact['cycle'] = 'FY' + pair.group('cycle')
                    fact['cycle_citation'] = api.citation_for(container, document,
                        block['span'][0] + pair.start(), block['span'][0] + pair.end(), stamp)
                facts.extend(found)
    return facts


def apply_requirements(api, opportunity_id, facts, containers, document, stamp):
    """Explicit source-stage obligations; no notice-wide search for 'must'."""
    requirements = {}
    rolling = {}
    invitation = None
    for container, start, end in clauses(containers):
        text = container['text'][start:end]
        if len(text) > 1200:
            continue
        for stage, pattern in STAGES[:-1]:
            subject = rf'(?:{pattern})'
            anytime = re.search(rf'\b{subject}\s+may\s+be\s+submitted\s+at\s+any\s+time\b', text, re.I)
            if anytime:
                rolling[stage] = api.citation_for(container, document, start + anytime.start(), start + anytime.end(), stamp)
            positive = re.search(rf'\b(?:required|mandatory)\s+{subject}\b|\b{subject}\s+(?:submission\s+)?(?:(?:is|are)\s+)?required\b|'
                rf'\bmust\s+(?:submit|provide)\s+(?:an?\s+)?{subject}\b|'
                rf'\bSubmitting\s+(?:an?\s+)?{subject}\s+(?:presentation\s+slide\s+deck\s+)?is\s+required\b', text, re.I)
            negative = re.search(rf'\b{subject}\s+(?:(?:is|are)\s+)?(?:non[ -]binding\s+and\s+)?(?:optional|not\s+required)\b|'
                rf'\b(?:although|while)\s+not\s+required,\s*{subject}\b', text, re.I)
            match = negative or positive
            if match and re.search(r'\b(?:if|when|whether)\s+(?:an?\s+|the\s+)?$', text[:match.start()], re.I):
                # Generic process guidance ("if concept papers are not
                # required") does not establish this call's obligation.
                continue
            if match and not re.search(r'\b(?:only\s+if|unless|not\s+required\s+to)\b', text, re.I):
                requirements.setdefault(stage, []).append((not bool(negative), api.citation_for(
                    container, document, start + match.start(), start + match.end(), stamp)))
        match = re.search(r'\bmust\s+receive\s+an?\s+invitation\s+to\s+submit\s+(?:an?\s+)?full\s+application\b', text, re.I)
        if not match:
            match = re.search(r'\ban invitation from NSF must be received before submitting a full proposal\b', text, re.I)
        if match:
            invitation = api.citation_for(container, document, start + match.start(), start + match.end(), stamp)
        # Supported NSF submission component: the notice explicitly requires
        # uploading the program officer's permission, not merely contacting one.
        permission = re.search(r'\bUpload the Concept Outline PO Concurrence email that indicates '
            r'PO permission to submit a full proposal\b', text, re.I)
        if permission:
            invitation = api.citation_for(container, document, start + permission.start(), start + permission.end(), stamp)
    for fact in facts:
        stage = fact['deadline_kind']
        candidates = requirements.get(stage, [])
        if not candidates and stage in {'preproposal', 'letter_of_intent'}:
            # The native label itself explicitly names the alias.
            label = (fact.get('citation', {}).get('structural_reference') or {}).get('field_label', '')
            if re.search(r'Pre[\s-]?Application(?:/Preproposal)?\s*\(', label, re.I):
                candidates = requirements.get('preapplication', [])
        if candidates:
            values = {value for value, _ in candidates}
            if fact.get('required') is not None:
                values.add(fact['required'])
            if len(values) == 1:
                value, citation = candidates[0]
                if fact.get('required') is None or fact['required'] == value:
                    fact.update(required=value, obligation='required' if value else 'optional', requirement_citation=citation)
            else:
                fact.update(required=None, obligation='unknown', requirement_conflict=True,
                            requirement_citations=[citation for _, citation in candidates[:2]])
        if stage == 'application' and invitation:
            fact.update(invitation_required=True, prerequisite='invitation', prerequisite_citation=invitation)
    if invitation and not any(f.get('type') == 'submission_requirement' and f.get('stage') == 'application'
                              and f.get('invitation_required') for f in facts):
        # A source-only permission requirement also governs a current full date
        # supplied by the structured feed, independently of historical rows.
        facts.append(api.make_fact(opportunity_id, 'submission_requirement', 'Full application invitation requirement', None,
            'Invitation required for full submission', invitation, deadline_kind='application', stage='application',
            subject='submission', date=None, time=None, timezone=None, required=None, obligation='unknown',
            application_class='unspecified', invitation_required=True, prerequisite='invitation',
            prerequisite_citation=invitation, parser_version=SCHEDULE_VERSION))
    represented = {fact['deadline_kind'] for fact in facts}
    for stage, candidates in requirements.items():
        if stage in represented:
            continue
        values = {value for value, _ in candidates}
        required = next(iter(values)) if len(values) == 1 else None
        citation = candidates[0][1]
        facts.append(api.make_fact(opportunity_id, 'submission_requirement',
            stage.replace('_', ' ').capitalize() + ' requirement', None,
            'May be submitted at any time' if stage in rolling else 'Submission date not established', citation,
            deadline_kind=stage, stage=stage, subject='submission', date=None, time=None, timezone=None,
            required=required, obligation='required' if required is True else 'optional' if required is False else 'unknown',
            application_class='unspecified', invitation_required=None, prerequisite=None,
            parser_version=SCHEDULE_VERSION, requirement_citation=citation,
            **({'rolling': True, 'rolling_citation': rolling[stage]} if stage in rolling else {})))
