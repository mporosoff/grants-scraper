"""Local, subject-qualified notice facts; no network or publication side effects.

The retained source structure establishes boundaries. These readers support
explicit funding-notice fields and clauses, not arbitrary English inference.
Unknown qualifiers remain unknown rather than becoming an asserted obligation.
"""
import re

SEMANTIC_VERSIONS = {
    "amounts": "award-basis-11", "cost_share": "cost-obligation-1",
    "sections": "substantive-section-2", "components": "component-owner-3",
    "limits": "submission-subject-1", "status": "notice-subject-2",
}


def substantive_spans(container):
    """Original offsets excluding known TOCs and repeated physical furniture."""
    text = container.get("text") or ""
    toc = container.get("toc") or re.search(r"^\s*table of contents\s*$", text[:1200], re.I | re.M)
    # The NOAA template puts its entire outline and real executive-summary
    # fields on one physical page. The repeated plain heading plus its first
    # native field proves the end of the outline, including in legacy structure.
    resume = re.search(r'(?m)^\s*Executive Summary\s*\n\s*Federal Agency Name\s*$', text) if toc else None
    if toc and not resume:
        return
    blocks = container.get("structure") or []
    if blocks and container.get("page") is None:
        for block in blocks:
            if block.get("kind") == "heading" or block.get("toc"):
                continue
            if any(c.get("nested_table") for c in block.get("cells", [])):
                continue
            yield tuple(block["span"])
        return
    excluded = [b["span"] for b in blocks if b.get("repeated_header") or (b.get("toc") and not resume)]
    cursor = resume.start() if resume else 0
    for start, end in sorted(excluded):
        if start > cursor:
            yield cursor, start
        cursor = max(cursor, end)
    if cursor < len(text):
        yield cursor, len(text)


def clauses(containers):
    """Sentence/field boundaries retain wrapped PDF lines and decimal amounts."""
    for container in containers:
        text = container["text"]
        for start, end in substantive_spans(container):
            piece = text[start:end]
            cursor = 0
            for boundary in re.finditer(r"(?<!\d)[.!?](?=\s+[A-Z])|\n\s*\n|[;•▪]", piece):
                stop = boundary.end()
                if piece[cursor:stop].strip():
                    yield container, start + cursor, start + stop
                cursor = stop
            if piece[cursor:].strip():
                yield container, start + cursor, end


def _fact(api, opportunity_id, kind, label, value, display, container, document, stamp, start, end, family, **qualifiers):
    fact = api.make_fact(opportunity_id, kind, label, value, display,
                         api.citation_for(container, document, start, end, stamp))
    fact.update(parser_version=SEMANTIC_VERSIONS[family], **qualifiers)
    _update_fact_id(api, opportunity_id, fact)
    return fact


def _update_fact_id(api, opportunity_id, fact):
    fact['id'] = api.evidence_id(opportunity_id, fact['type'], fact['label'],
        {'value': fact['value'], **{key: fact.get(key) for key in ('subject', 'stage', 'track', 'cycle',
            'basis', 'cost_basis', 'currency', 'obligation')},
            **{key: fact[key] for key in ('funding_basis', 'estimate_kind', 'applicant_condition') if fact.get(key)}}, fact['citation'])


MONEY = r"\$\s*\d[\d,]*(?:\.\d+)?(?:\s*(?:thousand|million|billion|(?<=\d)[KMB]|(?-i:[KMB])(?!\.)))?\b"
AWARD = r"(?:per[\s-]?(?:grant\s+)?award|each\s+award|individual\s+awards?|award\s+(?:amount|range|floor|ceiling|maximum|minimum)|(?:minimum|maximum)\s+(?:Federal\s+share\s+per\s+(?:grant\s+)?award|award)|grant\s+amount|total\s+cost\s+caps?)"
COMPLIANCE = re.compile(r"\b(?:lobbying|disclosure|SF[\s-]*LLL|procurement\s+threshold|simplified\s+acquisition)\b", re.I)


def funding_track(container, position):
    """An explicit local funding heading, never a reference to a nearby topic."""
    text = container['text']
    headings = list(re.finditer(r'(?m)^[ \t]*(?P<label>(?:Topic Area|Track)\s+[A-Z0-9]+)\s*:', text[:position], re.I))
    if not headings:
        return None
    heading = headings[-1]
    # A new numbered section ends a funding heading's ownership. Bullet-list
    # topic inventories never establish this heading in the first place.
    if re.search(r'(?m)^[ \t]*\d+\.\s+[A-Z]', text[heading.end():position]):
        return None
    return heading


def _spanning_funding_rows(container, text, header):
    """Use retained PDF columns to bound a vertically centered field label.

    The value column can begin above the label's baseline. Adjacent left-column
    fields delimit that one table row; page-wide proximity is not ownership.
    Return original-text offsets, without synthesizing or moving source text.
    """
    rows = container.get('layout_rows') or []
    candidates = [(index, cell) for index, row in enumerate(rows) for cell in row.get('cells', [])
                  if cell.get('text') == 'Award amount range']
    if len(candidates) != 1 or header.group().strip(' :\n\r\t').casefold() != 'award amount range':
        return None
    index, cell = candidates[0]
    column = cell.get('column_start')
    if type(column) is not int or len(rows[index].get('cells') or []) != 3:
        return None
    boundaries = []
    for indices in (range(index - 1, -1, -1), range(index + 1, len(rows))):
        boundary = next((c for i in indices for c in rows[i].get('cells', [])
                         if type(c.get('column_start')) is int and abs(c['column_start'] - column) <= 2), None)
        if not boundary:
            return None
        pattern = r'\s+'.join(re.escape(part) for part in boundary['text'].split())
        matches = list(re.finditer(pattern, text))
        if len(matches) != 1:
            return None
        boundaries.append(matches[0])
    upper, lower = boundaries
    if not upper.end() < header.start() < lower.start():
        return None
    start = text.find('\n', upper.end())
    if start < 0 or start >= header.start():
        return None
    return start + 1, lower.start()


def _native_money_facts(api, opportunity_id, container, document, stamp):
    """Owned funding fields/tables; return consumed source spans as well.

    A repeated component/track label owns each value. A stacked min/max table
    is accepted only with both headers and exactly two complete values in its
    row. Partial rows never shift a later dollar amount into an empty cell.
    """
    facts, consumed = [], []

    def emit(lo, hi, begin, end, *, track=None, basis='total_project', estimated=False, cost_basis='unspecified', estimate_kind=None, applicant_condition=None, funding_basis=None):
        if (lo is None and hi is None) or (lo is not None and hi is not None and lo > hi):
            return
        display = (f'{api.format_money(lo)}–{api.format_money(hi)}' if lo is not None and hi is not None
                   else f'Up to {api.format_money(hi)}' if hi is not None else f'From {api.format_money(lo)}')
        if basis == 'per_budget_period':
            display += ' per budget period'
        if track:
            display = f'{track}: {display}'
        if estimate_kind == 'typical_range':
            display = 'Typical range: ' + display
        if applicant_condition:
            display += ' — ' + applicant_condition
        if funding_basis == 'optional_supplement':
            display = 'Optional grant administration funding: ' + display
        facts.append(_fact(api, opportunity_id, 'award_range', 'Per-award amount',
            {'minimum': lo, 'maximum': hi}, display, container, document, stamp, begin, end,
            'amounts', subject='award', currency='USD', basis=basis, cost_basis=cost_basis,
            track=track, estimated=estimated, field_authority='official_notice_field',
            **({'estimate_kind': estimate_kind} if estimate_kind else {}),
            **({'applicant_condition': applicant_condition} if applicant_condition else {}),
            **({'funding_basis': funding_basis} if funding_basis else {})))

    for begin, end in substantive_spans(container):
        text = container['text'][begin:end]
        # Adjacent CDC floor/ceiling fields explicitly repeat the same project
        # period unit. Blank PDF lines do not turn these into unrelated awards.
        # An intervening track, different unit, or missing value prevents pairing.
        paired_bounds = re.compile(rf'\bAward (?P<first>Floor|Ceiling)\s*:\s*(?P<a>{MONEY})\s+Per Project Period\s+'
            rf'Award (?P<second>Floor|Ceiling)\s*:\s*(?P<b>{MONEY})\s+Per Project Period\b', re.I)
        for row in paired_bounds.finditer(text):
            if row['first'].lower() == row['second'].lower():
                continue
            values = {row[name].lower(): api.parse_money(*api.MONEY_RE.search(row[value]).groups())
                      for name, value in [('first', 'a'), ('second', 'b')]}
            if values['floor'] > values['ceiling']:
                continue
            emit(values['floor'], values['ceiling'], begin + row.start(), begin + row.end())
            consumed.append((begin + row.start(), begin + row.end()))
        # CDC's component rows repeat under separately named min/max fields.
        fields = list(re.finditer(r'\b(?P<bound>Maximum|Minimum) award amount per budget period\s*:', text, re.I))
        component_values = {}
        for index, field in enumerate(fields):
            stop = fields[index + 1].start() if index + 1 < len(fields) else len(text)
            tail = text[field.end():stop]
            row = re.match(rf'\s*(?:Component\s+[A-Z0-9]+\s*:\s*(?:{MONEY}|TBD|unknown|not announced)\s*;?\s*)+', tail, re.I)
            if not row:
                continue
            for value in re.finditer(rf'(Component\s+[A-Z0-9]+)\s*:\s*({MONEY})', row.group(), re.I):
                token = api.MONEY_RE.search(value.group(2))
                amount = api.parse_money(*token.groups())
                slot = component_values.setdefault(value.group(1), {})
                slot[field.group('bound').casefold()] = amount
                slot.setdefault('start', begin + field.start())
                slot['end'] = begin + field.end() + value.end()
            consumed.append((begin + field.start(), begin + field.end() + row.end()))
        for track, values in component_values.items():
            emit(values.get('minimum'), values.get('maximum'), values['start'], values['end'],
                 track=track, basis='per_budget_period')

        # The same CDC table also states program totals. Their component and
        # budget-period units cannot be inferred from the per-award rows below.
        for header in re.finditer(r'\bExpected total program funding (?P<period>over the performance period|per budget period)\s*:', text, re.I):
            row = re.match(rf'\s*(?:Component\s+[A-Z0-9]+\s*:\s*{MONEY}\s*;?\s*)+', text[header.end():], re.I)
            if not row:
                continue
            for value in re.finditer(rf'(Component\s+[A-Z0-9]+)\s*:\s*({MONEY})', row.group(), re.I):
                amount = api.parse_money(*api.MONEY_RE.search(value.group(2)).groups())
                basis = 'program_per_budget_period' if header.group('period').casefold() == 'per budget period' else 'program_total'
                display = f'{value.group(1)}: {api.format_money(amount)}' + (' per budget period' if basis == 'program_per_budget_period' else ' over the performance period')
                facts.append(_fact(api, opportunity_id, 'program_funding', 'Program funding', amount,
                    display, container, document, stamp, begin + header.start(), begin + header.end() + value.end(),
                    'amounts', subject='program', currency='USD', basis=basis, track=value.group(1)))
            consumed.append((begin + header.start(), begin + header.end() + row.end()))

        # The ADCMS sentence declares both endpoints before the common owner.
        paired = re.compile(rf'\bminimum of\s+(?P<low>{MONEY})\s+and\s+(?:a\s+)?maximum of\s+'
                            rf'(?P<high>{MONEY})\s+award amount for each\b', re.I)
        for row in paired.finditer(text):
            lo, hi = [api.parse_money(*api.MONEY_RE.search(row.group(k)).groups()) for k in ('low', 'high')]
            emit(lo, hi, begin + row.start(), begin + row.end())
            consumed.append((begin + row.start(), begin + row.end()))

        # A range with an immediate per-award owner can carry a separate
        # named project area. Never merge ranges across these suffix labels.
        ranges = re.compile(r'\b(?:(?P<estimate>(?:estimated|anticipated|approximate)(?:\s+funding)?\s+|'
            r'(?:the\s+)?amount\s+of\s+funding\s+is\s+(?:expected|anticipated)\s+to\s+be\s+))?'
            rf'(?:between|range\s+(?:of|from)|funding range of)\s+'
            rf'(?P<low>{MONEY})\s*(?:and|to|[-–—])\s*(?P<high>{MONEY})\s*'
            r'(?:(?:of funding is anticipated )?for each award|per award|each)\b'
            r'(?:\s+for\s+(?P<track>Project Area\s+[A-Z0-9]+(?:[-–][A-Z0-9]+)?))?', re.I)
        previous_range = None
        for row in ranges.finditer(text):
            lo, hi = [api.parse_money(*api.MONEY_RE.search(row.group(k)).groups()) for k in ('low', 'high')]
            estimated = bool(row.group('estimate') or re.search(r'\banticipated\b', row.group(), re.I))
            # A coordinated list shares its explicit range qualifier. Other
            # intervening prose or a field boundary cannot transfer it.
            if previous_range and re.fullmatch(r'\s*,?\s*and\s*', text[previous_range[0]:row.start()], re.I):
                estimated = estimated or previous_range[1]
            emit(lo, hi, begin + row.start(), begin + row.end(), track=row.group('track'),
                 estimated=estimated)
            previous_range = (row.end(), estimated)
            consumed.append((begin + row.start(), begin + row.end()))

        typical = re.compile(rf'\btypical(?:,\s*|\s+)(?:awarded\s+)?(?:awards?|grants?|cooperative agreements?)\s+'
            rf'(?:will\s+)?range from\s+(?P<low>{MONEY})\s+to\s+(?P<high>{MONEY}),?\s+with a maximum award of\s+(?P<cap>{MONEY})', re.I)
        for row in typical.finditer(text):
            lo, hi, cap = [api.parse_money(*api.MONEY_RE.search(row.group(k)).groups()) for k in ('low', 'high', 'cap')]
            if lo > hi or hi > cap:
                continue
            emit(lo, hi, begin + row.start(), begin + row.end(), estimated=True, estimate_kind='typical_range')
            emit(None, cap, begin + row.start(), begin + row.end())
            consumed.append((begin + row.start(), begin + row.end()))

        # HUD explicitly repeats its short program code on each bound.
        coded = {}
        for row in re.finditer(rf'\b(?P<bound>Minimum|Maximum) (?P<track>[A-Z]{{2,}}(?:-[A-Z]+)+) '
                               rf'award amount is\s+(?P<value>{MONEY})', text):
            values = coded.setdefault(row.group('track'), {})
            values[row.group('bound').lower()] = api.parse_money(*api.MONEY_RE.search(row.group('value')).groups())
            values.setdefault('start', begin + row.start())
            values['end'] = begin + row.end()
            consumed.append((begin + row.start(), begin + row.end()))
        for track, values in coded.items():
            emit(values.get('minimum'), values.get('maximum'), values['start'], values['end'], track=track)

        # A source can explicitly state both an annual and whole-award cap in
        # the same sentence. Each unit belongs to its adjacent monetary value.
        for row in re.finditer(rf'\bmaximum of\s+(?P<annual>{MONEY})\s+per year\s+and\s+(?:a\s+)?'
                               rf'maximum of\s+(?P<total>{MONEY})\s+per award\b', text, re.I):
            headings = list(re.finditer(r'\b([A-Z][A-Za-z &-]{1,60})\s*:\s*Up to\b', text[:row.start()]))
            track = headings[-1].group(1) if headings else None
            for key, basis in [('annual', 'per_year'), ('total', 'total_project')]:
                emit(None, api.parse_money(*api.MONEY_RE.search(row.group(key)).groups()),
                     begin + row.start(), begin + row.end(), basis=basis, track=track)
                if basis == 'per_year':
                    facts[-1]['display_value'] += ' per year'
            consumed.append((begin + row.start(), begin + row.end()))

        # Separate initial and optional renewal project budgets. This explicit
        # funding-request field does not license harvesting other budget prose.
        renewal = re.compile(rf'\bFunding requests must be for[^$]{{0,140}}maximum budget of\s+'
            rf'(?P<initial>{MONEY})\s+total for the first[^$]{{0,60}}and an optional renewal project award '
            rf'maximum budget of\s+(?P<renewal>{MONEY})\s+total for an additional\b', re.I)
        for row in renewal.finditer(text):
            for key, track in [('initial', 'Initial project'), ('renewal', 'Optional renewal')]:
                emit(None, api.parse_money(*api.MONEY_RE.search(row.group(key)).groups()),
                     begin + row.start(), begin + row.end(), track=track)
            consumed.append((begin + row.start(), begin + row.end()))

        # Parallel NSF Track fields, including equal caps in distinct tracks.
        for row in re.finditer(rf'\b(?P<track>Track\s+[A-Z0-9]+)\s*:\s*maximum\s+'
                               rf'(?P<value>{MONEY})\s+per award\b', text, re.I):
            emit(None, api.parse_money(*api.MONEY_RE.search(row.group('value')).groups()),
                 begin + row.start(), begin + row.end(), track=row.group('track'))
            consumed.append((begin + row.start(), begin + row.end()))

        # NSF's adjacent funding-history exception belongs to the explicitly
        # named track, with its condition retained verbatim. An intervening
        # paragraph, field or unowned maximum cannot inherit that track.
        conditional_track = re.compile(
            rf'\b(?P<track>Track\s+[A-Z0-9]+) projects have a maximum award of\s+'
            rf'(?P<ordinary>{MONEY})\s+for up to (?:\d+|one|two|three|four|five) years\. '
            r'(?P<condition>Institutions that have not received [A-Z][A-Z &-]{1,35} funding '
            r'in the past \d+ years) are eligible for a maximum of\s+'
            rf'(?P<conditional>{MONEY})\s+for up to (?:\d+|one|two|three|four|five) years\.', re.I)
        for row in conditional_track.finditer(text):
            for key in ('ordinary', 'conditional'):
                emit(None, api.parse_money(*api.MONEY_RE.search(row.group(key)).groups()),
                     begin + row.start(), begin + row.end(), track=row.group('track'),
                     applicant_condition=re.sub(r'\s+', ' ', row.group('condition')) if key == 'conditional' else None)
            consumed.append((begin + row.start(), begin + row.end()))

        # IES separates optional administrative support from the research
        # award. Preserve both declared units and the eligibility condition;
        # never sum them into a fabricated universal award ceiling.
        supplement = re.compile(r'\bOptional\s+Funding\s+for\s+Grant\s+Administration\s*'
            r'\(for\s+(?P<track>[A-Za-z][A-Za-z\s-]{1,80}?)\s+Applications\s+Only\)\s*'
            r'(?P<condition>[A-Za-z][A-Za-z\s0-9-]{1,180}?)\s+may\s+request\s+additional\s+funding\s+'
            r'for\s+grant\s+administration\s*\(up\s+to\s+'
            rf'(?P<annual>{MONEY})\s+per\s+year\s+and\s+(?P<total>{MONEY})\s+total\s+'
            r'in\s+direct\s+and\s+indirect\s+costs\)', re.I)
        for row in supplement.finditer(text):
            track = re.sub(r'\s+', ' ', row.group('track')).strip() + ' applications'
            condition = re.sub(r'\s+', ' ', row.group('condition')).strip()
            for key, basis in [('annual', 'per_year'), ('total', 'total_project')]:
                emit(None, api.parse_money(*api.MONEY_RE.search(row.group(key)).groups()),
                     begin + row.start(), begin + row.end(), track=track, basis=basis, cost_basis='total',
                     applicant_condition=condition, funding_basis='optional_supplement')
                if basis == 'per_year':
                    facts[-1]['display_value'] += ' (per year)'
            consumed.append((begin + row.start(), begin + row.end()))

        # Declared funding tables repeat a track and a complete amount/range.
        # Stop at the first non-row; a clipped last row cannot lend its value.
        field = re.compile(r'\b(?:Approximate Maximum Award Amount|Award amount range)\s*:?\s*', re.I)
        row_pattern = re.compile(rf'(?P<track>[A-Z][A-Za-z0-9\s()/&–—-]{{0,75}}?)\s*[–—:]?\s*'
            rf'(?P<low>{MONEY})(?:\s*[-–—]\s*(?P<high>{MONEY}))?\s*')
        for header in field.finditer(text):
            spanning = _spanning_funding_rows(container, text, header)
            cursor, stop = spanning if spanning else (header.end(), len(text))
            while cursor < stop:
                while cursor < stop and text[cursor].isspace():
                    cursor += 1
                if cursor == header.start():
                    cursor = header.end()
                row = row_pattern.match(text, cursor, stop)
                if not row:
                    break
                track = re.sub(r'\s+', ' ', row.group('track')).strip(' –—:')
                if re.search(r'\b(?:award|funding|year|duration|months?|must|may|will|of)\b', track, re.I):
                    break
                lo = api.parse_money(*api.MONEY_RE.search(row.group('low')).groups())
                hi = api.parse_money(*api.MONEY_RE.search(row.group('high')).groups()) if row.group('high') else None
                emit(lo if hi is not None else None, hi if hi is not None else lo,
                     begin + min(header.start(), row.start()), begin + max(header.end(), row.end()), track=track,
                     estimated=header.group().lower().startswith('approximate'))
                consumed.append((begin + row.start(), begin + row.end()))
                cursor = row.end()

        # NIFA enumerated maximum fields: lettered rows are not money units.
        for header in re.finditer(r'\bMaximum Award Amount\(s\)\s*:', text, re.I):
            cursor = header.end()
            item = re.compile(rf'\s*[a-z]\.\s*Including indirect costs\s*:\s*(?P<value>{MONEY})'
                              r'(?:\s+for\s+(?P<track>[A-Z][A-Za-z -]{0,60}?)(?=\s+[a-z]\.\s|[.;…]|$))?', re.I)
            while row := item.match(text, cursor):
                emit(None, api.parse_money(*api.MONEY_RE.search(row.group('value')).groups()),
                     begin + header.start(), begin + row.end(), track=row.group('track'), cost_basis='total')
                consumed.append((begin + row.start(), begin + row.end()))
                cursor = row.end()

        # USDA cover: two consecutive headings precede their ordered values.
        stacked = re.compile(rf'\bANTICIPATED PROGRAM FUNDING\s*:\s*AVERAGE INDIVIDUAL AWARD RANGE\s*:\s*'
                             rf'(?P<program>{MONEY})\s+(?P<low>{MONEY})\s*[-–—]\s*(?P<high>{MONEY})', re.I)
        for row in stacked.finditer(text):
            lo, hi = [api.parse_money(*api.MONEY_RE.search(row.group(k)).groups()) for k in ('low', 'high')]
            emit(lo, hi, begin + row.start(), begin + row.end(), estimated=True)
            consumed.append((begin + row.start(), begin + row.end()))

        # USDA duration/start/end/minimum/maximum table, retained reading order.
        for headers in re.finditer(r'\bMinimum award\s+Maximum award\b', text, re.I):
            tail = text[headers.end():]
            # Recognized table ownership blocks fallback even if the row is
            # incomplete. An unrelated amount cannot fill the missing cell.
            stop = re.search(r'\n\s*\n|(?<!\d)[.!?](?=\s+[A-Z])', tail)
            consumed.append((begin + headers.start(), begin + headers.end() + (stop.start() if stop else len(tail))))
            row = re.match(rf'(?P<context>[^$]{{0,240}})(?P<low>{MONEY})\s+(?P<high>{MONEY})', tail, re.I)
            if not row or not re.search(r'\b(?:years?|months?)\b', row.group('context'), re.I):
                continue
            # A second header, paragraph, or missing-value marker breaks the row.
            if re.search(r'\n\s*\n|\b(?:unknown|TBD|not announced)\b|:', row.group('context'), re.I):
                continue
            lo, hi = [api.parse_money(*api.MONEY_RE.search(row.group(k)).groups()) for k in ('low', 'high')]
            emit(lo, hi, begin + headers.start(), begin + headers.end() + row.end())
            consumed.append((begin + headers.start(), begin + headers.end() + row.end()))

    return facts, consumed


def amount_facts(api, opportunity_id, containers, document, stamp):
    facts, seen = [], set()
    consumed = {}
    for container in containers:
        native, spans = _native_money_facts(api, opportunity_id, container, document, stamp)
        facts.extend(native)
        consumed[id(container)] = spans
    for container, start, end in clauses(containers):
        clause = container["text"][start:end]
        if COMPLIANCE.search(clause):
            continue
        # Matching each monetary token to its own prefix/suffix prevents the
        # preceding program total from borrowing a later "per award" label.
        tokens = list(api.MONEY_RE.finditer(clause))
        if not tokens:
            continue
        accepted = []
        for n, token in enumerate(tokens):
            if any(lo <= start + token.start() < hi for lo, hi in consumed[id(container)]):
                continue
            before = clause[tokens[n - 1].end() if n else 0:token.start()]
            after = clause[token.end():tokens[n + 1].start() if n + 1 < len(tokens) else len(clause)]
            prefix = before[-220:]
            suffix = after[:160]
            amount = api.parse_money(token.group(1), token.group(2))
            if not amount:
                continue
            # An increment/conditional reporting threshold is not a ceiling.
            # The owned condition remains disqualifying when its form list is
            # separated by a bullet from the amount (as in USDA/FAS notices).
            if re.search(r'\bincrements\s+of\s*$|\bif\b[^$]*\b(?:over|exceeds?)\s*$', prefix, re.I):
                continue
            if re.match(r'\s*per award\s*,\s*of which\b', prefix, re.I):
                continue
            if re.search(r'\b(?:previous years?|prior awards?|historical)\b[^.:]*$', prefix, re.I):
                continue
            owned_after = bool(re.match(r"\s*(?:in\s+(?:total|direct)\s+costs?\s+)?per\s+(?:grant\s+)?award\b", suffix, re.I))
            owned_before = bool(re.search(AWARD, prefix, re.I) or re.search(
                r"(?:application.s|project.s)\s+(?:total|direct)\s+costs?\b|\bcost\s+cap\s*:", prefix, re.I))
            # NSF's explicit track funding field assigns support to each
            # proposal. A general program-support paragraph is not this field.
            owned_before = owned_before or bool(re.search(
                r'\bTrack\s+[A-Z0-9]+\s+proposals\s+may\s+receive\s+support\s+of\s+(?:up\s+to\s+)?$', prefix, re.I))
            owned_before = owned_before or bool(re.search(
                r'\bAwards\s+(?:are\s+)?(?:(?:anticipated|expected)\s+to\s+)?range\s+from\s*$', prefix, re.I))
            owned_before = owned_before or bool(re.search(r'\b(?:minimum|maximum)\b[^$]{0,80}$', prefix, re.I)
                and re.search(r'\baward\s+amount\s+for\s+each\b', suffix, re.I))
            if re.fullmatch(r'\s*per\s+award\s+and\s*', prefix, re.I):
                owned_before = False
            # Second endpoint inherits only within an explicit local range.
            range_endpoint = bool(accepted and re.fullmatch(r"\s*(?:to|through|[-–—])\s*", before, re.I) or
                accepted and re.fullmatch(r"\s*and\s*", before, re.I)
                and re.search(r"\b(?:between|from|range)\b", clause[:tokens[0].start()], re.I))
            program = bool(re.search(r"\b(?:program|allot|available\s+funding|total\s+funding)\b", prefix, re.I))
            program = program or bool(re.match(r'\s*to\s+fund\s+(?:approximately\s+)?\d+\b', suffix, re.I))
            fiscal = re.match(r'\s+in\s+(FY\s+\d{4})\b', suffix, re.I)
            program = program or bool(fiscal and re.fullmatch(r'\s+in\s+FY\s+\d{4}\s+and\s*', before, re.I)
                and re.search(r'\bprogram\b', clause[:tokens[0].start()], re.I))
            track_endpoint = bool(accepted and re.search(r'\btotal\s+cost\s+caps\s+of\b|\baward amount will not exceed\b', clause, re.I)
                and re.match(r'\s*(?:per\s+award\s+)?(?:combined\s+)?for\s+', suffix, re.I)
                and not re.search(r'\b(?:of\s+which|base\s+award|total\s+funding|allot)\b', before, re.I))
            if not (owned_after or owned_before or range_endpoint or track_endpoint):
                if program:
                    program_basis = 'program_per_budget_period' if re.search(r'\bper budget period\b', prefix, re.I) else 'program_total'
                    heading = funding_track(container, start + token.start())
                    track = heading.group('label') if heading else None
                    federal = bool(re.search(r'\bFederal\s+Funds\s*[–—:-]\s*(?:Up\s+to\s+)?$', prefix, re.I))
                    display = api.format_money(amount) + (' per budget period' if program_basis == 'program_per_budget_period' else '')
                    if federal:
                        display += ' in federal funds'
                    if track:
                        display = track + ': ' + display
                    if fiscal:
                        display = fiscal.group(1) + ': ' + display
                    fact = _fact(api, opportunity_id, "program_funding", "Program funding", amount, display,
                        container, document, stamp, start + token.start(), start + token.end(),
                        "amounts", subject="program", currency="USD", basis=program_basis,
                        **({'cycle': fiscal.group(1)} if fiscal else {}),
                        **({'track': track} if track else {}), **({'funding_basis': 'federal_share'} if federal else {}))
                    if heading:
                        fact['track_citation'] = api.citation_for(container, document, heading.start(), heading.end(), stamp)
                    facts.append(fact)
                continue
            if program and not owned_after and not re.search(AWARD, prefix, re.I):
                continue
            bound = "minimum" if re.search(r"\b(?:minimum|floor|at least)\b", prefix, re.I) else "maximum" if re.search(
                r"\b(?:maximum|ceiling|cap|caps|up\s+to|not\s+(?:to\s+)?exceed)\b", prefix, re.I) else None
            accepted.append((amount, bound, token))
        if not accepted:
            continue
        track_limits = []
        for index, (amount, bound, token) in enumerate(accepted):
            stop = accepted[index + 1][2].start() if index + 1 < len(accepted) else len(clause)
            qualifier = re.match(r'\s*(?:per\s+award\s+)?(?:combined\s+)?for\s+(?:(?:the|a)\s+)?(.+?)(?:\s*[,;]?\s*(?:or|and)\s*$|[;]|$)', clause[token.end():stop].rstrip('.'), re.I | re.S)
            if not qualifier:
                preceding = clause[max(0, token.start() - 220):token.start()]
                qualifier = re.search(r'\bfund\s+(?:approximately\s+)?(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+([^$]+?)\s+applications\s+with\s+total\s+cost\s+caps\s+of\s*$', preceding, re.I | re.S)
            if qualifier:
                track = re.split(r',\s*(?:and\s+)?approximately\b|\s*\(additional\b', qualifier.group(1), flags=re.I)[0]
                track = re.sub(r'\s*,?\s*per\s+award\s*$', '', re.sub(r'\s+', ' ', track), flags=re.I).strip(' ,;')
                # Duration/fiscal descriptions cannot become track names.
                if not re.search(r'\b(?:years?|months?|annually|budget period)\b', track, re.I):
                    track_limits.append((amount, bound, token, track))
        if len(track_limits) == len(accepted) and len(track_limits) > 1:
            for amount, bound, token, track in track_limits:
                if (None, amount, 'total_project', 'total', track, None) in seen:
                    continue
                seen.add((None, amount, 'total_project', 'total', track, None))
                facts.append(_fact(api, opportunity_id, 'award_range', 'Per-award amount',
                    {'minimum': amount if bound == 'minimum' else None, 'maximum': None if bound == 'minimum' else amount},
                    f"{track}: {'From' if bound == 'minimum' else 'Up to'} {api.format_money(amount)}",
                    container, document, stamp, start + token.start(), min(end, start + token.end() + len(track) + 9),
                    'amounts', subject='award', currency='USD', basis='total_project', cost_basis='total', track=track,
                    # The source may estimate the program appropriation or
                    # number of awards while stating definite individual caps.
                    estimated=bool(re.search(r'\b(?:estimated|anticipated|approximate)\s+total\s+cost\s+caps?\s+of\s*$',
                        clause[:accepted[0][2].start()], re.I))))
            continue
        minimum = next((v for v, bound, _ in accepted if bound == "minimum"), None)
        maximum = next((v for v, bound, _ in accepted if bound == "maximum"), None)
        if len(accepted) == 2 and (re.search(r"\b(?:between|from|range)\b", clause, re.I) or
            re.fullmatch(r"\s*(?:to|through|[-–—])\s*", clause[accepted[0][2].end():accepted[1][2].start()], re.I)):
            minimum, maximum = accepted[0][0], accepted[1][0]
        elif len(accepted) == 1 and minimum is None:
            maximum = accepted[0][0]
        elif len(accepted) > 2 or (len(accepted) == 2 and (minimum is None or maximum is None)):
            # Distinct track ceilings require distinct source clauses/rows.
            continue
        if minimum and maximum and minimum > maximum:
            continue
        # Qualifiers belong to the accepted amount's own field, not a previous
        # program appropriation or a following amount with a different basis.
        first_index = tokens.index(accepted[0][2])
        last_index = tokens.index(accepted[-1][2])
        local_start = tokens[first_index - 1].end() if first_index else 0
        local_end = tokens[last_index + 1].start() if last_index + 1 < len(tokens) else len(clause)
        # The following field's label belongs to its own value. It cannot
        # relabel the accepted range as a historical average or annual amount.
        boundary = re.search(r'\b(?:Average\s+(?:amount|individual|one year)|(?:Maximum|Minimum)\s+award|'
            r'Award\s+(?:Floor|Ceiling|Budget)|Expected\s+(?:amount|funding))\b',
            clause[accepted[-1][2].end():local_end], re.I)
        if boundary:
            local_end = accepted[-1][2].end() + boundary.start()
        local = clause[local_start:local_end]
        owner = list(re.finditer(AWARD, local[:accepted[0][2].start() - local_start], re.I))
        if owner:
            lead = re.search(r'\b(?:Average\s+(?:One Year\s+)?|Typical\s+)$', local[:owner[-1].start()], re.I)
            local = local[lead.start() if lead else owner[-1].start():]
        basis = ("initial_budget_period" if re.search(r"\b(?:for|during) the (?:first|initial) budget period\b", local, re.I)
                 else "per_budget_period" if re.search(r'\bper\s+budget\s+period\b', local, re.I)
                 else "per_year" if re.search(r"\bper\s+year\b|\bone year award amount\b", local, re.I) else "total_project")
        costs = "direct" if re.search(r"\bdirect\s+cost", local, re.I) and not re.search(r"\b(?:total|indirect)\s+cost", local, re.I) else "total" if re.search(r"\btotal\s+cost", local, re.I) else "unspecified"
        funding_basis = 'federal_share' if all(re.search(r'\bFederal\s+Funds\s*[–—:-]\s*(?:Up\s+to\s+)?$',
            clause[max(0, token.start() - 60):token.start()], re.I) for _, _, token in accepted) else None
        if re.match(r'\s+in\s+federal\s+funds\b', clause[accepted[-1][2].end():local_end], re.I):
            funding_basis = 'federal_share'
        track_match = re.search(r"(?:for|under)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9 &–—/-]{0,45}\s+(?:Option|Track))\b", local, re.I)
        track = track_match.group(1).strip() if track_match else None
        if track is None:
            track_match = re.search(r'\b(Track\s+[A-Z0-9]+)\s+proposals\s+may\s+receive\s+support\b', clause, re.I)
            track = track_match.group(1) if track_match else None
        if track is None:
            track_match = re.search(r'\b(Track\s+[A-Z0-9]+)\s+projects have a maximum award\b', clause, re.I)
            track = track_match.group(1) if track_match else None
        if track is None:
            label = re.match(r'\s*((?:[A-Z][A-Za-z-]*\s+){1,5}(?:awards|grants))\s*:', clause)
            if label and not re.search(r'\b(?:Number|Expected|Anticipated|Individual|Total)\b', label.group(1)):
                track = label.group(1)
        if track is None:
            label = re.search(r'\baward(?: amount)? for (?:the )?([^$.;]{1,100}?)\s+'
                r'(?:has\s+been\s+(?:increased|reduced)\s+to|to)\s*$', clause[:accepted[0][2].start()], re.I)
            if label:
                track = re.sub(r'\s+', ' ', label.group(1)).strip()
        if track is None and len(accepted) == 1:
            suffix = clause[accepted[0][2].end():]
            owner = re.match(r'\s*per award\s+for\s+(?:(?:the|a)\s+)?(.+?)[.;]?$', suffix, re.I)
            if owner:
                candidate = owner.group(1).strip(' ,;.')
                if not candidate.endswith('…'):
                    track = candidate
            if track is None:
                code = re.search(r'\b([A-Z]{2,}(?:-[A-Z0-9]+)+)\s+applications\s+with total cost caps\b', clause)
                track = code.group(1) if code else None
        if track is None:
            track_match = re.search(r'Application Submissions with\s+(?:the\s+)?([^:\n]+)\s*:', clause, re.I)
            track = track_match.group(1).strip() if track_match else None
        heading = funding_track(container, start + accepted[0][2].start()) if track is None else None
        if heading:
            track = heading.group('label')
        estimate_kind = ('average' if re.search(r'\baverage\b', local, re.I) else 'typical_range'
                         if re.search(r'\btypical(?:ly)?\b', local, re.I) else None)
        key = (minimum, maximum, basis, costs, track, funding_basis)
        if key in seen:
            continue
        seen.add(key)
        display = f"{api.format_money(minimum)}–{api.format_money(maximum)}" if minimum and maximum and minimum != maximum else f"Up to {api.format_money(maximum)}" if maximum else f"From {api.format_money(minimum)}"
        if basis == "per_year":
            display += " per year"
        elif basis == "initial_budget_period":
            display += " for the first budget period"
        elif basis == 'per_budget_period':
            display += ' per budget period'
        if costs == "direct":
            display += " in direct costs"
        if funding_basis == 'federal_share':
            display += " in federal funds"
        if track:
            display = f"{track}: {display}"
        if estimate_kind:
            display = ('Average amount: ' if estimate_kind == 'average' else 'Typical range: ') + display.removeprefix('Up to ')
        fact = _fact(api, opportunity_id, "award_range", "Per-award amount", {"minimum": minimum, "maximum": maximum},
            display, container, document, stamp, start + accepted[0][2].start(), start + accepted[-1][2].end(), "amounts",
            subject="award", currency="USD", basis=basis, cost_basis=costs, track=track,
            **({'funding_basis': funding_basis} if funding_basis else {}),
            **({'estimate_kind': estimate_kind} if estimate_kind else {}),
            estimated=bool(estimate_kind or re.search(r"\b(?:estimated|anticipat\w*|approximately|expects?)\b", local, re.I)))
        if heading:
            fact['track_citation'] = api.citation_for(container, document, heading.start(), heading.end(), stamp)
        facts.append(fact)
    supplement_tracks = {re.sub(r'\s+(?:grants|applications)$', '', (f.get('track') or '').casefold())
                         for f in facts if f.get('funding_basis') == 'optional_supplement'}
    for fact in facts:
        name = re.sub(r'\s+(?:grants|applications)$', '', (fact.get('track') or '').casefold())
        if fact.get('type') == 'award_range' and not fact.get('funding_basis') and name and name in supplement_tracks:
            fact['funding_basis'] = 'base_award'
            fact['display_value'] = 'Base award — ' + fact['display_value']
            _update_fact_id(api, opportunity_id, fact)
    return facts


def cost_share_facts(api, opportunity_id, containers, document, stamp):
    facts, seen = [], set()
    # The question mark is part of the field label, not a prose boundary.
    for container in containers:
        for start, end in substantive_spans(container):
            for match in re.finditer(r'\bCost Sharing Required\?\s*(Yes|No)\b', container['text'][start:end], re.I):
                value = match.group(1).casefold() == 'yes'
                rule = 'required' if value else 'not_required'
                if rule in seen:
                    continue
                seen.add(rule)
                facts.append(_fact(api, opportunity_id, 'cost_share', 'Cost sharing', value,
                    'Required' if value else 'Not required', container, document, stamp,
                    start + match.start(), start + match.end(), 'cost_share', subject='cost_share',
                    obligation=rule, negated=not value))
    for container, start, end in clauses(containers):
        clause = container["text"][start:end]
        if not api.COST_SHARE_RE.search(clause):
            continue
        normalized = re.sub(r"\s+", " ", clause).strip()
        # A short "Cost Sharing" heading can precede the actual same-named
        # field. Evaluate the owned assertion, not only the first occurrence.
        after = next((normalized[m.end():] for m in api.COST_SHARE_RE.finditer(normalized)
                      if re.match(r"\s*(?:is\s+|are\s+)?(?:not|optional|required|mandatory|must)\b", normalized[m.end():], re.I)), "")
        obligation, value, display = "unknown", None, None
        native_answer = re.search(r'\bcost sharing required\?\s*(Yes|No)\b', normalized, re.I)
        if not native_answer and re.search(r'\bcost sharing required\?', normalized, re.I):
            continue
        if native_answer:
            value = native_answer.group(1).casefold() == 'yes'
            obligation, display = ('required', 'Required') if value else ('not_required', 'Not required')
        elif re.search(r"\bvoluntary\s+committed\s+cost\s+sharing\s+is\s+prohibited\b", normalized, re.I):
            obligation, value, display = "voluntary_committed_prohibited", False, "Voluntary committed cost sharing prohibited"
        elif re.search(r"^\s*(?:is\s+|are\s+)?(?:not\s+(?:an?\s+eligibility\s+requirement|required)|optional|not\s+mandatory)\b", after, re.I) or re.search(r"\bno\s+cost\s+sharing\s+(?:is\s+)?required\b", normalized, re.I):
            obligation, value, display = "not_required", False, "Not required"
        elif re.search(r"^\s*(?:is\s+|are\s+)?(?:required|mandatory|must\s+be\s+provided)\b", after, re.I):
            obligation, value, display = "required", True, "Required"
        if display and re.search(r"\b(?:if|unless|only\s+(?:for|when))\b", normalized, re.I):
            obligation, value, display = "conditional", None, "Conditional — verify the cited rule"
        key = obligation
        if display and key not in seen:
            seen.add(key)
            facts.append(_fact(api, opportunity_id, "cost_share", "Cost sharing", value, display,
                container, document, stamp, start, end, "cost_share", subject="cost_share",
                obligation=obligation, negated=obligation in {"not_required", "voluntary_committed_prohibited"}))
    return facts


def heading_excerpt(api, opportunity_id, containers, document, stamp, *, fact_type, label, heading_pattern):
    candidates = []
    for container in containers:
        text = container["text"]
        section = container.get("section") or ""
        owned_section = bool(heading_pattern.search(section))
        for start, end in substantive_spans(container):
            piece = text[start:end]
            if owned_section:
                candidates.append((0, container, start, end))
            # A PDF heading is a bounded line, not any mention in body prose.
            for line in re.finditer(r"[^\n]+", piece):
                raw = line.group().strip()
                if (len(raw) <= 140 and heading_pattern.search(raw)
                    and not re.search(r"\.{3,}|\||\b(?:see|refer|must|please|below|requirements[.]|in mind)\b", raw, re.I)
                    and re.fullmatch(r"(?:[A-Z0-9]+[.\s]*)*[^.!?]+", raw)):
                    candidates.append((1, container, start + line.end(), end))
            # Explicit substantive eligibility sentences remain supported even
            # when a minimal source has no heading tree.
            if fact_type == "eligibility_excerpt":
                match = re.search(r"\bEligible\s+applicants?\s+(?:include|are|must)\b", piece, re.I)
                if match:
                    candidates.append((2, container, start + match.start(), end))
            elif fact_type == "review_criteria":
                match = re.search(r"\b(?:Applications?|Proposals?)\s+will\s+be\s+(?:evaluated|reviewed)\s+(?:on|using|based\s+on)\b|\bReviewers\s+will\s+consider\b", piece, re.I)
                if match:
                    candidates.append((2, container, start + match.start(), end))
    for ownership, container, start, end in sorted(candidates, key=lambda c: c[0]):
        piece = container["text"][start:end]
        excerpt = re.sub(r"\s+", " ", piece[:700]).strip()
        if len(excerpt) < 60 or (ownership == 2 and not re.search(r"\b(?:may|must|will|are|is|include|includes|eligible|consider|criteria)\b", excerpt, re.I)):
            continue
        if re.search(r"^(?:Please\s+)?(?:see|refer)\b|^standard\s+(?:NSF\s+)?merit\s+review\s+criteria\s+apply", excerpt, re.I):
            continue
        return _fact(api, opportunity_id, fact_type, label, excerpt[:320], excerpt[:220] + ("…" if len(excerpt) > 220 else ""),
            container, document, stamp, start, min(end, start + 420), "sections", subject="applicant_eligibility" if fact_type == "eligibility_excerpt" else "application_review")
    return None


COMPONENTS = {
    "White paper": r"white\s+papers?", "Research narrative": r"research\s+narrative",
    "Project narrative": r"project\s+narrative", "Technical narrative": r"technical\s+narrative",
    "PI resume": r"(?:PI\s+)?r[eé]sum[eé]s?", "Abstract": r"abstract", "Cover sheet": r"cover\s+(?:sheet|page)",
}
NUMBER = r"(?:\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten)"
NUMBERS = {word: i for i, word in enumerate("zero one two three four five six seven eight nine ten".split())}


INSTITUTIONAL_LIMIT_RE = re.compile(
    rf'\b(?:institution|organization|university)\s+(?:(?:may|can)\s+submit\s+|is\s+limited\s+to\s+)'
    rf'(?:only\s+|no\s+more\s+than\s+|at\s+most\s+|a\s+maximum\s+of\s+)?{NUMBER}\s+(?:applications?|proposals?|submissions?)\b|'
    rf'\b{NUMBER}\s+(?:applications?|proposals?|submissions?)\s+(?:(?:may|can)\s+be\s+submitted\s+)?per\s+(?:institution|organization|university)\b|'
    rf'\bLimit on Number of Proposals per Organization\s*:\s*{NUMBER}\b', re.I)


def institutional_limit_signal(text):
    """Synopsis flag requires an owned institution; a PI rule is separate."""
    match = INSTITUTIONAL_LIMIT_RE.search(text or '')
    return match.group() if match else None


def component_facts(api, opportunity_id, containers, document, stamp):
    facts, seen = [], set()
    names = {**{k: v.pattern for k, v in api.APPLICATION_COMPONENTS.items()}, **COMPONENTS}
    previous = None
    for container, start, end in clauses(containers):
        clause = container["text"][start:end]
        matches = sorted((m.start(), m.end(), name) for name, pattern in names.items() for m in re.finditer(pattern, clause, re.I))
        if not matches and previous and previous[0] is container and len(previous[3]) == 1:
            previous_start, previous_end = previous[1:3]
            name = previous[3][0][2]
            gap = container['text'][previous_end:start]
            if (name == 'Data management plan' and not gap.strip() and '\n\n' not in gap
                and re.match(r'\s*(?:It|This plan)\s+will\s+be\s+requested\s+only\s+after\s+(?:a\s+)?recommendation\s+for\s+funding', clause, re.I)):
                key = ('application_component', name, 'post_recommendation', 'conditional')
                if key not in seen:
                    seen.add(key)
                    facts.append(_fact(api, opportunity_id, 'application_component', name, name,
                        name + ' (conditional after funding recommendation)', container, document, stamp,
                        previous_start, end, 'components', subject=name, stage='post_recommendation', obligation='conditional'))
        previous = (container, start, end, matches)
        for index, (begin, stop, name) in enumerate(matches):
            local_end = matches[index + 1][0] if index + 1 < len(matches) else len(clause)
            local_start = matches[index - 1][1] if index else 0
            local = clause[begin:local_end]
            prefix = clause[local_start:begin]
            stage, obligation = "application", "unknown"
            if re.search(r"\bonly\s+after|\bif\s+recommended\s+for\s+funding", prefix + local, re.I):
                stage, obligation = "post_recommendation", "conditional"
            elif re.search(r"\bdo\s+not\s+(?:submit|include)\s+(?:(?:an?|the)\s+)?"
                           r"(?:copy\s+of\s+(?:the\s+)?(?:[A-Z][a-z]*\s+){0,8}(?:\([A-Z]{2,12}\)\s+)?)?$", prefix, re.I):
                obligation = "prohibited"
            elif re.search(r"\boptional\b", local, re.I):
                obligation = "optional"
            elif re.search(r'\b(?:if|when)\b|\bas\s+applicable\b', prefix + local, re.I):
                obligation = 'conditional'
            elif (re.search(r"\b(?:must|required)\b", local, re.I)
                  or (re.search(r"\b(?:must\s+include|include|submit)\b", prefix, re.I)
                      and not re.search(r'\bdo\s+not\s+(?:submit|include)\b', prefix, re.I))):
                obligation = "required"
            if name == "White paper":
                stage = "white_paper"
            cap = re.search(rf"\b(?:limited\s+to|not\s+(?:to\s+)?exceed|maximum(?:\s+of)?)\s+({NUMBER})\s+(?:single[\s-]sided\s+)?pages?\b|\b({NUMBER})[\s-]+page\s+limit\b|\b({NUMBER})(?:\s*\(\d+\))?\s+pages?\s+or\s+less\b", local, re.I)
            if cap:
                raw = next(group for group in cap.groups() if group).casefold()
                limit = int(raw) if raw.isdigit() else NUMBERS[raw]
                parenthesized = re.search(r'\((\d+)\)', cap.group())
                if parenthesized and int(parenthesized.group(1)) != limit:
                    cap = None
            if cap:
                key = ("page_limit", name, limit, stage)
                if key not in seen:
                    seen.add(key)
                    tail = clause[begin + cap.end():]
                    exclusion = re.match(r'\s*[,;(]?\s*((?:excluding|not including|exclusive of|including)\b[^.;]+)', tail, re.I)
                    facts.append(_fact(api, opportunity_id, "page_limit", f"{name} page limit", limit, f"{name}: {limit} pages",
                        container, document, stamp, start + begin, start + local_end, "components", subject=name,
                        stage=stage, obligation=obligation, exclusions=exclusion.group(1).strip()[:240] if exclusion else None))
            key = ("application_component", name, stage, obligation)
            if key not in seen and (obligation != "unknown" or cap):
                seen.add(key)
                facts.append(_fact(api, opportunity_id, "application_component", name, name,
                    f"{name} ({obligation.replace('_', ' ')})", container, document, stamp, start + local_start, start + local_end,
                    "components", subject=name, stage=stage, obligation=obligation))
    return facts


def limit_facts(api, opportunity_id, containers, document, stamp):
    facts, seen = [], set()
    for container in containers:
        blocks = container.get('structure') or []
        for index, block in enumerate(blocks):
            label = re.fullmatch(r'Limit on Number of Proposals per (Organization|PI(?:\s+or\s+co[\s-]?PI)?)\s*:\s*(.*)', block['text'], re.I)
            if not label:
                continue
            subject = 'organization' if label.group(1).casefold() == 'organization' else 'investigator'
            value = label.group(2).strip()
            value_block = block
            if not value and index + 1 < len(blocks) and blocks[index + 1].get('kind') in {'paragraph', 'list_item'}:
                value_block = blocks[index + 1]
                value = value_block['text']
            unlimited = bool(re.fullmatch(r'There are no restrictions or limits\.?|No limit\.?|None\.?', value, re.I))
            if not unlimited and not re.fullmatch(r'\d{1,3}', value):
                continue
            limit = None if unlimited else int(value)
            if (subject, limit) in seen:
                continue
            seen.add((subject, limit))
            kind = ('institutional_submission_policy' if subject == 'organization' else 'investigator_submission_policy') if unlimited else (
                'limited_submission' if subject == 'organization' else 'investigator_submission_limit')
            fact = _fact(api, opportunity_id, kind, 'Institutional submission rule' if subject == 'organization' else 'PI/co-PI submission rule',
                {'unlimited': True, 'maximum': None} if unlimited else limit,
                f'No {subject} submission limit' if unlimited else f'{limit} per {subject}',
                container, document, stamp, block['span'][0], value_block['span'][1], 'limits', subject=subject)
            facts.append(fact)
    for container, start, end in clauses(containers):
        clause = container["text"][start:end]
        for subject, owner in [("organization", r"institution|organization|university"),
                               ("investigator", r"principal\s+investigator|co[\s-]?PI|PI")]:
            # Explicitly named owner, never "applicant" or a nearby team size.
            patterns = [rf"\b(?:{owner})\b.{{0,90}}?\b(?:limited\s+to|no\s+more\s+than|at\s+most)\s+({NUMBER})\s+(?:applications?|proposals?|submissions?)\b",
                        rf"\b({NUMBER})\s+(?:applications?|proposals?|submissions?).{{0,40}}?\bper\s+(?:{owner})\b",
                        rf"\blimit\s+on\s+(?:the\s+)?number\s+of\s+proposals\s+per\s+(?:{owner})\s*:\s*({NUMBER})\b"]
            match = next((m for pattern in patterns if (m := re.search(pattern, clause, re.I | re.S))), None)
            if match:
                raw = match.group(1).casefold()
                limit = int(raw) if raw.isdigit() else NUMBERS[raw]
                if (subject, limit) in seen:
                    continue
                seen.add((subject, limit))
                facts.append(_fact(api, opportunity_id, "limited_submission" if subject == "organization" else "investigator_submission_limit",
                    "Institutional submission limit" if subject == "organization" else "PI/co-PI submission limit", limit,
                    f"{limit} per {subject}", container, document, stamp, start + match.start(), start + match.end(), "limits", subject=subject))
    return facts


def status_facts(api, opportunity_id, containers, document, stamp):
    facts, seen = [], set()
    owner = r"(?:this|the\s+current)\s+(?:notice|solicitation|funding\s+opportunity|announcement|NOFO|FOA)"
    patterns = [("cancelled", rf"\b{owner}\s+(?:is|has\s+been)\s+(?:cancelled|canceled|withdrawn)\b"),
                ("superseded", rf"\b{owner}\s+(?:(?:is|has\s+been)\s+)?(?:superseded|replaced)\s+by\b"),
                ("amended", rf"\b{owner}\s+(?:is|has\s+been)\s+(?:amended|revised)\b"),
                ("recurring", r"\bopen\s+until\s+superseded\b|\bapplications?\s+(?:are\s+)?accepted\s+on\s+a\s+(?:rolling|continuing)\s+basis\b|\bthis\s+program\s+recurs\s+annually\b")]
    for container, start, end in clauses(containers):
        clause = container["text"][start:end]
        for status, pattern in patterns:
            match = re.search(pattern, clause, re.I)
            if match and status not in seen and not re.search(r"\b(?:if|unless)\b", clause[:match.start()], re.I):
                seen.add(status)
                facts.append(_fact(api, opportunity_id, "status_signal", f"Solicitation {status}", status, f"Solicitation {status}",
                    container, document, stamp, start + match.start(), start + match.end(), "status", subject="current_solicitation", status_signal=status))
    return facts
