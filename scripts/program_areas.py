"""Controlled program-area vocabulary for evidence-backed discoverability.

Some agencies bundle many program areas into one broad "umbrella" announcement
whose Grants.gov text is generic. The clearest example: DOE Office of Science
posts a single "Continuation of Solicitation for the Office of Science Financial
Assistance Program" (DE-FOA-0003600) that actually funds Basic Energy Sciences
(catalysis, materials, chemistry...), Advanced Scientific Computing, Fusion,
etc. -- but those words appear only in the **PDF**, never in the catalog text,
so a keyword search for "catalysis" cannot find it.

``scripts/discoverability.py`` handles this with a hand-maintained per-FOA
lexicon keyed off catalog text. This module generalizes that: it lists a
controlled vocabulary of program-area terms, and the document-evidence extractor
scans the *official notice text* for them. A term is attached to a record only
when it genuinely appears in that record's official PDF/HTML -- so the added
searchable terms and Topic tags are evidence-backed (with a page/section
citation kept in the evidence cache), never invented, and never presented as an
official FOA requirement.

Each entry is ``(label, topics, pattern)``:
  * ``label``   short canonical term added to the record's ``document_search_text``
  * ``topics``  Topic-facet tags to attach (must match the catalog topic
                vocabulary exactly; ``[]`` means "searchable but no clean topic")
  * ``pattern`` case-insensitive regex recognizing the area in notice text

Extend ``_ENTRIES`` to cover more agencies/programs.
"""

from __future__ import annotations

import re

# label, topic tags, recognizer pattern
_ENTRIES: list[tuple[str, list[str], str]] = [
    ("catalysis", ["Catalysis and reaction engineering"],
     r"\bcatalys(?:is|es)\b|"
     r"\bcatalytic (?:reaction|process|conversion|activity|material|system|"
     r"site|mechanism|chemistry|engineering|technology|performance)\b|"
     r"\b(?:electro|photo|thermo)catalys\w*"),
    ("chemical sciences", ["Catalysis and reaction engineering"],
     r"chemical sciences|synthetic chemistry|physical chemistry|molecular chemistry|combustion"),
    ("materials science", ["Materials science"],
     r"materials science|condensed matter|materials discovery|materials by design"),
    ("separations", ["Separations and membranes"],
     r"\bseparations\b|separation science|membrane separation|gas separation|"
     r"chemical separation|molecular separation|isotope separation|reactive separation"),
    ("rare earth elements", ["Materials science"],
     r"rare[- ]earth elements?|\blanthanides?\b|\bscandium\b|\byttrium\b"),
    ("critical minerals", ["Materials science"],
     r"critical minerals?|critical materials?"),
    ("ionic liquids", ["Separations and membranes"],
     r"ionic liquids?"),
    ("solvent extraction", ["Separations and membranes"],
     r"solvent extraction|liquid[- ]liquid extraction"),
    ("hydrometallurgy", ["Separations and membranes", "Materials science"],
     r"hydrometallurg\w*|selective leaching|ion exchange|adsorptive separation"),
    ("quantum science", ["Quantum science"],
     r"quantum information|quantum computing|quantum science|quantum materials|\bqubit"),
    ("fusion energy", ["Energy"],
     r"fusion energy|plasma physics|magnetic confinement|inertial confinement"),
    ("advanced computing", ["Data science", "Artificial intelligence and machine learning"],
     r"advanced scientific computing|exascale|high[- ]performance computing|scientific machine learning"),
    ("artificial intelligence", ["Artificial intelligence and machine learning", "Data science"],
     r"artificial intelligence|machine learning|deep learning|foundation model"),
    ("biological and environmental research", ["Biology and biotechnology", "Environmental science"],
     r"biological and environmental research|genomic science|systems biology|bioenergy research"),
    ("hydrogen", ["Energy"],
     r"hydrogen production|clean hydrogen|water electrolysis|hydrogen fuel"),
    ("carbon management", ["Carbon management", "Climate change"],
     r"carbon capture|carbon management|direct air capture|carbon storage|carbon utilization|decarboniz"),
    ("energy storage", ["Energy"],
     r"energy storage|grid[- ]scale storage|batter(?:y|ies)|electrochemical storage"),
    ("solar energy", ["Energy"],
     r"photovoltaic|solar energy|concentrating solar"),
    ("advanced manufacturing", ["Manufacturing"],
     r"advanced manufacturing|industrial decarboniz|process intensification|smart manufacturing"),
    ("microelectronics", ["Materials science", "Manufacturing"],
     r"microelectronics|semiconductor|integrated circuit"),
    ("cybersecurity", ["Cybersecurity"],
     r"cybersecurity|cyber-physical security|secure control systems"),
    ("water", ["Water"],
     r"water treatment|desalination|water reuse|water resources"),
    ("high energy physics", [],
     r"high energy physics|particle physics|accelerator science"),
    ("nuclear physics", [],
     r"nuclear physics|isotope production|radiochemistry"),
]

# Public: (label, topics, compiled_pattern)
ENTRIES: list[tuple[str, list[str], re.Pattern]] = [
    (label, topics, re.compile(pattern, re.IGNORECASE))
    for label, topics, pattern in _ENTRIES
]


def topics_for(labels) -> list[str]:
    """Return the de-duplicated Topic tags implied by the given program labels."""
    wanted = set(labels)
    result: list[str] = []
    for label, topics, _ in ENTRIES:
        if label in wanted:
            for topic in topics:
                if topic not in result:
                    result.append(topic)
    return result
