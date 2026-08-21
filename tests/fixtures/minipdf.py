"""Build small PDFs with real font variation, using no new dependency.

Layer C reads per-character ``fontname`` and ``size`` from ``pdfplumber``, so
testing it needs a PDF whose text is genuinely set in more than one face.
``pypdf.PdfWriter`` -- which tests/test_document_evidence.py uses -- cannot
author that: it assembles pages and metadata but does not lay down text with a
chosen font.

The way out is the **base-14 fonts**. Helvetica, Helvetica-Bold, Times-Roman
and Times-Bold are built into every conforming PDF consumer and require no
embedded font program, so a page can reference ``/BaseFont /Helvetica-Bold``
and get a real, resolvable font name for about a hundred bytes. ``pdfminer.six``
reports it verbatim:

    fontname='Helvetica-Bold'  size=14.0  'Topic Area 1 Electrocatalysis'
    fontname='Helvetica'       size=11.0  'Ordinary body prose...'

That is genuine typographic variation through the real ``pdfplumber`` stack,
which is what Layer C needs, so **no PDF-generating library is added to
requirements-dev.txt or anywhere else**. See docs/TOPIC_LAYER_PLAN.md §9.3
("Dev dependencies") and §18.1 item B3.

Output is byte-deterministic: no timestamps, no document ID, fixed object
order. The same call always produces the same bytes.
"""

from __future__ import annotations

import io


# key -> base-14 font name. Bold faces are what BOLD_RE must recognize.
FONTS = {
    "F1": "Helvetica",
    "F2": "Helvetica-Bold",
    "F3": "Times-Roman",
    "F4": "Times-Bold",
}

PAGE_WIDTH, PAGE_HEIGHT = 612, 792
TOP_MARGIN = 720
LINE_HEIGHT = 16


def line(text, font="F1", size=11):
    """One text line, positioned automatically by :func:`build_pdf`."""
    return {"text": text, "font": font, "size": size}


def heading(text, size=14):
    """A bold line, which is the signal Layer C actually keys on."""
    return line(text, font="F2", size=size)


def _escape(text):
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("(", r"\(")
        .replace(")", r"\)")
    )


def build_pdf(pages, outline=None):
    """Assemble a PDF from ``pages``: a list of lists of line dicts.

    ``outline`` is an optional list of ``(title, page_index, level)`` tuples
    written as a real bookmark tree, so Layer A can be exercised too. Level 1
    entries are nested under the most recent level 0 entry.
    """
    pages = [list(page) for page in pages]
    page_count = len(pages)

    # Object numbering: 1 catalog, 2 pages, then (page, content) per page,
    # then the four fonts, then any outline objects.
    page_ids = [3 + index * 2 for index in range(page_count)]
    content_ids = [pid + 1 for pid in page_ids]
    first_font = 3 + 2 * page_count
    font_ids = {key: first_font + index for index, key in enumerate(sorted(FONTS))}
    next_id = first_font + len(FONTS)

    font_refs = " ".join(f"/{key} {font_ids[key]} 0 R" for key in sorted(FONTS))
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)

    objects = {}
    objects[1] = None       # filled in below, once the outline root is known
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>"

    for index, items in enumerate(pages):
        body = ["BT"]
        cursor = TOP_MARGIN
        for item in items:
            body.append(
                f"/{item['font']} {item['size']} Tf "
                f"1 0 0 1 72 {cursor} Tm ({_escape(item['text'])}) Tj"
            )
            cursor -= LINE_HEIGHT
        body.append("ET")
        stream = "\n".join(body)
        objects[page_ids[index]] = (
            f"<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << {font_refs} >> >> "
            f"/Contents {content_ids[index]} 0 R >>"
        )
        objects[content_ids[index]] = (
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
        )

    for key in sorted(FONTS):
        objects[font_ids[key]] = (
            f"<< /Type /Font /Subtype /Type1 /BaseFont /{FONTS[key]} >>"
        )

    outline_root = None
    if outline:
        outline_root = next_id
        next_id += 1
        entries = []
        for title, page_index, level in outline:
            entries.append(
                {
                    "id": next_id,
                    "title": title,
                    "page": page_ids[page_index],
                    "level": level,
                    "children": [],
                }
            )
            next_id += 1
        # Nest level-1 entries under the preceding level-0 entry.
        top, current_parent = [], None
        for entry in entries:
            if entry["level"] == 0:
                top.append(entry)
                current_parent = entry
            elif current_parent is not None:
                current_parent["children"].append(entry)
            else:
                top.append(entry)

        def emit(items, parent_id):
            for position, entry in enumerate(items):
                parts = [
                    f"/Title ({_escape(entry['title'])})",
                    f"/Parent {parent_id} 0 R",
                    f"/Dest [{entry['page']} 0 R /Fit]",
                ]
                if position:
                    parts.append(f"/Prev {items[position - 1]['id']} 0 R")
                if position + 1 < len(items):
                    parts.append(f"/Next {items[position + 1]['id']} 0 R")
                if entry["children"]:
                    parts.append(f"/First {entry['children'][0]['id']} 0 R")
                    parts.append(f"/Last {entry['children'][-1]['id']} 0 R")
                    parts.append(f"/Count {len(entry['children'])}")
                objects[entry["id"]] = "<< " + " ".join(parts) + " >>"
                emit(entry["children"], entry["id"])

        emit(top, outline_root)
        objects[outline_root] = (
            f"<< /Type /Outlines /First {top[0]['id']} 0 R "
            f"/Last {top[-1]['id']} 0 R /Count {len(top)} >>"
        )

    objects[1] = (
        "<< /Type /Catalog /Pages 2 0 R"
        + (f" /Outlines {outline_root} 0 R" if outline_root else "")
        + " >>"
    )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = out.tell()
        out.write(f"{number} 0 obj\n{objects[number]}\nendobj\n".encode("latin-1"))

    highest = max(objects)
    xref = out.tell()
    out.write(f"xref\n0 {highest + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for number in range(1, highest + 1):
        out.write(f"{offsets.get(number, 0):010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {highest + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def containers_from(pages):
    """The page-indexed containers extract_containers() would have produced."""
    return [
        {
            "page": index,
            "section": None,
            "anchor": None,
            "text": "\n".join(item["text"] for item in page),
        }
        for index, page in enumerate(pages, start=1)
    ]
