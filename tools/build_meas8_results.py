"""Build MEAS-8's deterministic results artifact from adjudicated observations.

The live probes record changing network observations under ``.work/meas8``.
This module freezes the adjudicated measurements, source hashes, calculations,
and dispositions that are fit to commit.  It never performs network access and
does not alter the production catalog, parser, ranking, or generated site.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRAME_PATH = ROOT / "evaluation" / "meas8_frame.json"
RESULTS_PATH = ROOT / "evaluation" / "meas8_results.json"
FRAME_COMMIT = "16b765f5a39ce7963667bc28b54da09ff5bdf519"


NO_LIST = {
    "353633": "No applicant-selectable ordinary subject list; named areas and questions are illustrative.",
    "356018": "No applicant-selectable ordinary subject list in the notice or current attachment surface.",
    "357003": "No applicant-selectable ordinary subject list in the notice or current attachment surface.",
    "358864": "No applicant-selectable ordinary subject list in the primary attachment.",
    "348599": "No applicant-selectable ordinary subject list in the NSF notice.",
    "329432": "No applicant-selectable ordinary subject list in the NSF program page.",
    "342747": "No applicant-selectable ordinary subject list in the NSF solicitation.",
    "326841": "PDF plus two DOCX attachments were read; none contains a genuine list. The DOCX files are forms, not a format falsifier.",
    "363535": "Eight stated priorities are scope guidance rather than distinct applicant-selectable fundable subdivisions; XLSX/DOCX files are forms.",
    "362071": "Single program and objective, not a selectable subject hierarchy.",
    "362099": "Single demonstration program and objective, not a selectable subject hierarchy.",
    "363425": "Required regional-center activities are deliverables, not fundable subject subdivisions.",
    "363040": "Single project objective, not a selectable subject hierarchy.",
}

NON_SUBJECT = {
    "338558": "LAOF/CIF facility and delivery programs are participation mechanisms under DEC-11.",
    "362983": "International and domestic indemnity are coverage/participation mechanisms under DEC-11.",
    "332125": "Planning and Local Technical Assistance are program/mechanism structure under DEC-11.",
}

UNMEASURABLE = {
    "351240": ("client_rendered_application", "SAM page fetched but yielded zero notice text; current detail exposed no attachments."),
    "nyserda:PON3982": ("client_rendered_application", "Official detail route returned only a 599-character login/application shell."),
    "nyserda:RFQL5548": ("client_rendered_application", "Official detail route returned only a 599-character login/application shell."),
    "nyserda:PON6037-PhaseII": ("client_rendered_application", "Official detail route returned only a 599-character login/application shell."),
    "nyserda:RFP18": ("client_rendered_application", "Official detail route returned only a 599-character login/application shell."),
    "362393": ("source_selection_mismatch", "The selected NASA route resolved to a general terms PDF, not the NIAC notice; live detail exposed no attachment."),
    "363101": ("changed_application_page", "The official route returned a generic 1,559-character JFSP landing page and live detail exposed no attachment."),
    "363102": ("changed_application_page", "The official route returned a generic 1,559-character JFSP landing page and live detail exposed no attachment."),
}

SOURCE_OBSERVATIONS = {
    "353633": ("2e09c2f96c46466925a141c6624cc355cf2ad42fc8a50a668c162caf189fff6a", 68771, "https://grants.nih.gov/grants/guide/pa-files/PAR-24-153.html"),
    "356018": ("f891508cc9afaa672d823e6498d595ba0406cbba439039b8b79a913f7fe86818", 52705, "https://grants.nih.gov/grants/guide/pa-files/PAR-24-269.html"),
    "357003": ("c0be3e4bb9ecfcdae8b2cf19d99cf03e17c9e9ef13c48392f9a532e5e6f27e56", 42574, "https://grants.nih.gov/grants/guide/pa-files/PAR-25-175.html"),
    "358864": ("17ccdd429813f97e2c3bb80033d7eff9da0e663a618d3fb70b5be34a7ccb96c8", 75272, "https://grants.gov/grantsws/rest/opportunity/att/download/351485"),
    "348599": ("fbbb0149c7e23024d63e49d0015edd682f7dc9c135d8b3fe39dd23812729a32d", 52004, "https://www.nsf.gov/publications/pub_summ.jsp?ods_key=nsf23598"),
    "329432": ("949371e8c32feee7bcf4ae2f0acd14cdf676038ea490d95e14d2c24b78588671", 6141, "https://www.nsf.gov/funding/pgm_summ.jsp?pims_id=505704"),
    "338558": ("dca26783b9a93a82b437c6b42f5214e5144b5e9d95cd27a6bd1a36d6a57d1b9d", 5967, "https://www.nsf.gov/funding/pgm_summ.jsp?pims_id=506047"),
    "342747": ("11917c6b9d7bea19dbb153376f9d42c5334e4ce70b8820b67435ab87166d6e6a", 64192, "https://www.nsf.gov/publications/pub_summ.jsp?ods_key=nsf22621"),
    "351240": ("213738b20afbc0b837683c108a430635f340b14604ac97aae5751eae9a0918e3", 0, "https://sam.gov/opp/f6dac217c58545578b6dff242335e997/view"),
    "343725": ("dcc28795dc8ef5253966d3029b80d1c90dd4f3c477f8c54ba340398245e054b3", 306760, "https://grants.gov/grantsws/rest/opportunity/att/download/343209"),
    "326841": ("686a4b24f5f44dcc7a566cc4aadb45ed0c994ea6906bcdeec0d8ad34e7a501f2", 14546, "https://grants.gov/grantsws/rest/opportunity/att/download/298398"),
    "362268": ("e42fd281ebc850c809844f228dbc4b6da167dda2e744170b3ee05dceeacaa36e", 119631, "https://grants.gov/grantsws/rest/opportunity/att/download/351813"),
    "nyserda:PON3982": ("d39bdc331d941e3a6ad0cb485363d751d65edf9c33c5b15c1c05ba74fb36279b", 599, "https://portal.nyserda.ny.gov/CORE_Solicitation_Detail_Page?%20SolicitationId=a0rt000000MdOBsAAN"),
    "nyserda:RFQL5548": ("f7373d77fa1b7da0220091f606771c6fde5b6a38ce2407f97ee0218f3eb74752", 599, "https://portal.nyserda.ny.gov/CORE_Solicitation_Detail_Page?%20SolicitationId=a0r8z000000Dk3yAAC"),
    "nyserda:PON6037-PhaseII": ("4ff831846a8099eb207c5ede6c90e1f0fe4deb78224ee4c6a48390af3327335b", 599, "https://portal.nyserda.ny.gov/CORE_Solicitation_Detail_Page?%20SolicitationId=a0rcr00000iqxxLAAQ"),
    "nyserda:RFP18": ("2a053ae3a789fa7b931fd15786ad8baaa49b0c18f45c8104f88a55c9a2d03a50", 599, "https://portal.nyserda.ny.gov/CORE_Solicitation_Detail_Page?%20SolicitationId=a0rt000001GOHEzAAP"),
    "362393": ("b40918532c5ab5b39032b8663e820ecb0e7696c25c9409b6916dc4ac53d085b2", 318391, "https://www.nasa.gov/wp-content/uploads/2025/03/gcam-mar-2025.pdf?emrc=982b64"),
    "363101": ("f2bc52a02df939fb1ff9d1441b8397ce9684cd99f97ad630d83a23ecc8b62e91", 1559, "https://www.firescience.gov/"),
    "363102": ("fc24521197519aacb1ebd119d8970b308a1122e92cb4de0a41ae79537c14b3f0", 1559, "https://www.firescience.gov/"),
    "363479": ("fcf056cf4cab1cff660d9d8219804416ca8c699fb33326cd06b091dae5d9a9b6", 84574, "https://grants.gov/grantsws/rest/opportunity/att/download/354401"),
    "363535": ("9c2d5d053e948fbd6486f3eaa6d27df7152c6809fa76e7dc3af51ca098e1dc82", 50390, "https://grants.gov/grantsws/rest/opportunity/att/download/354500"),
    "362983": ("9652dcbd702fa9a91062d9b09e995d6e421f7f3f19e6fb1588bab6782f06e6b6", 14026, "https://www.arts.gov/impact/arts-and-artifacts-indemnity-program"),
    "358955": ("6314ba155e4302ac9b4dd60a2f969aaae7a62899ac295ca3a0d39cbec59d13e3", 180165, "https://grants.gov/grantsws/rest/opportunity/att/download/347648"),
    "362071": ("0195c78b06bb3678d60eca4898a43891a9d03815dd8f5f65f6ced04dc72ef8df", 103203, "https://grants.gov/grantsws/rest/opportunity/att/download/354106"),
    "362099": ("87f212e85e66cf9ac5b10993c5914349e34ce0f120bf0880b2960b1b1398dac3", 81530, "https://grants.gov/grantsws/rest/opportunity/att/download/354598"),
    "332125": ("4e0dccbcf5d84aa759687d1ee5da936cfc4994843735a5ae712ee069a90faf9d", 65414, "https://grants.gov/grantsws/rest/opportunity/att/download/325601"),
    "363425": ("5a4d9dfdd32df4e4ade01a60b888f0435370893a00d96abb24e52afae05242f4", 197598, "https://grants.gov/grantsws/rest/opportunity/att/download/354298"),
    "363040": ("745c8dcfd649aa7f2f9e49c168a2f4cecf31ebf55da5c72add35d4799bb90fba", 82350, "https://grants.gov/grantsws/rest/opportunity/att/download/353549"),
}

TRUTH_POSITIVES = {
    "343725": {
        "quote": "The scope of the DHA Military Infectious Diseases (MID) portfolio relates to...",
        "section": "II.A.1-II.A.9",
        "children": [
            "Military Infectious Diseases", "Combat Casualty Care", "Traumatic Brain Injury",
            "Psychological Health", "Sensory Systems", "Musculoskeletal Injury",
            "Environmental Exposures", "Directed Energy/Radiation Health", "DOD Working Dogs",
        ],
        "production": {"candidates": 9, "method": "outline_structural", "confidence": "medium", "cov4_calls": 9, "cov4_errors": 0, "cov4_accept": 9, "review_only": 9, "publishable": 0},
    },
    "362268": {
        "quote": "The table below lists the FY26 PRCRP Topic Areas and strategic goals in each PRCRP portfolio category.",
        "section": "FY26 PRCRP Topic Areas",
        "children": [
            "Bladder cancer", "Blood cancers", "Brain cancer", "Colorectal cancer",
            "Endometrial cancer", "Esophageal cancer", "Germ cell cancers", "Glioblastoma",
            "Liver cancer", "Lymphoma", "Mesothelioma", "Metastatic cancers", "Myeloma",
            "Neuroblastoma", "Neuroendocrine Tumors", "Pediatric, adolescent, and young adult cancers",
            "Pediatric brain tumors", "Sarcoma", "Stomach cancer", "Thyroid cancer",
        ],
        "production": {"candidates": 0, "method": None, "confidence": None, "cov4_calls": 0, "review_only": 0, "publishable": 0},
    },
    "363479": {
        "quote": "Projects must focus on one or more of the Educational Need Areas listed below...",
        "section": "Educational Need Areas",
        "children": [
            "Curriculum Development for Promoting Student Career Opportunities",
            "Faculty Preparation and Enhancement for Teaching",
            "Facilitating Interaction with Other Academic Institutions",
        ],
        "production": {"candidates": 0, "method": None, "confidence": None, "cov4_calls": 0, "review_only": 0, "publishable": 0},
    },
    "358955": {
        "quote": "This NOFO seeks applications for measurement science and standards research in the areas described by each MSE Grant Program below.",
        "section": "Section I.1-I.13",
        "children": [
            "Associate Director for Innovation and Industry Services (ADIIS) Grant Program",
            "Associate Director for Laboratory Programs (ADLP) Grant Program",
            "CHIPS Research & Development Program Office (CRDO) Grant Program",
            "Communications Technology Laboratory (CTL) Grant Program",
            "Engineering Laboratory (EL) Grant Program", "Fire Research (FR) Grant Program",
            "Information Technology Laboratory (ITL) Grant Program",
            "International and Academic Affairs Office (IAAO) Grant Program",
            "Material Measurement Laboratory (MML) Grant Program",
            "NIST Center for Neutron Research (NCNR) Grant Program",
            "Physical Measurement Laboratory (PML) Grant Program",
            "Special Programs Office (SPO) Grant Program",
            "Standards Coordination Office (SCO) Grant Program",
        ],
        "production": {"candidates": 0, "method": None, "confidence": None, "cov4_calls": 0, "review_only": 0, "publishable": 0},
    },
}


def _b1(status, current, captured, note, **extra):
    return {"status": status, "current_actionable_parents": current, "captured_parents": captured, "note": note, **extra}


ARM_B_RESULTS = {
    "doe-office-science": {
        "b1": _b1("captured", 1, 1, "DE-FOA-0003600 is current and captured."),
        "b2": {"truth_children": 68, "deterministic_candidates": 69, "accepted_subject_children": 68, "review_only": 68, "publishable": 0, "note": "DEC-11 correctly removes Public-Private Partnerships as a mechanism."},
        "b3": {"queries": 3, "retrieved_top_50": 3, "ranks": [2, 6, 2], "rules": ["doe-basic-energy-sciences", "doe-office-of-science-umbrella"]},
        "gap_classes": [], "disposition": "NONE",
        "evidence": [{"sha256": "60cffb3796f5ff5cbc7eabf76db8d425fac6ef18eae3c9014011ad3d0cafc3ea", "name": "DE-FOA-0003600.000001.pdf"}],
    },
    "doe-genesis": {
        "b1": _b1("captured", 1, 1, "DE-FOA-0003612 is current and captured."),
        "b2": {"top_level_truth_children": 21, "top_level_recovered": 21, "top_level_review_only": 21, "top_level_publishable": 0, "deeper_focus_area_truth": 98, "deeper_focus_area_recovered": 0, "note": "The Phase I workbook contains 98 distinct focus-area labels grouped under 21 challenges."},
        "b3": {"frozen_queries": 3, "frozen_retrieved_top_50": 0, "focus_queries": 98, "focus_retrieved_top_50": 11, "focus_retrieved_top_10": 3, "median_retrieved_rank": 15},
        "gap_classes": ["FORMAT_DEPTH", "DISCOVERABILITY"], "disposition": "PROMOTE_BEFORE_P9", "obligation": "DEC-22",
        "evidence": [{"sha256": "67cb16539b46e114a6e33ca0bd7f876fb08d614a61d0b821ffc5cea098281db3", "name": "DE-FOA-0003612.000003.pdf"}, {"sha256": "a2e36829b1c6f1ece1db19e6baf854fb1eff34a41d79efbb6bc60a646a9e3517", "name": "Genesis Mission Phase I Application Template v2.xlsx"}],
    },
    "doe-arpa-e": {
        "b1": _b1("captured_and_deduplicated", 2, 2, "Live adapter returned 11 rows: 9 expired and 2 current; both current rows deduplicated against Grants.gov.", adapter_rows=11, external_considered=2, external_added=0, duplicate_identity=2),
        "b2": {"truth_children": 7, "recovered": 7, "review_only": 7, "publishable": 0, "note": "SCALEUP has seven low-confidence numbered children; IGNIITE has no ordinary subject list."},
        "b3": {"queries": 2, "retrieved_top_50": 2, "ranks": [1, 1], "rules": ["doe-energy-efficiency-renewable"]},
        "gap_classes": [], "disposition": "NONE",
    },
    "doe-eere": {
        "b1": _b1("no_current_actionable_parent", 0, 0, "Live adapter returned 12 rows and all were expired.", adapter_rows=12, external_added=0),
        "b2": {"status": "not_applicable_no_current_parent"},
        "b3": {"status": "configured_rule_not_exercisable_on_current_case", "rules": ["doe-energy-efficiency-renewable"]},
        "gap_classes": [], "disposition": "NONE",
    },
    "doe-netl-hgeo": {
        "b1": _b1("captured_and_deduplicated", 3, 3, "Official HGEO and NETL pages list the same three current parents; all three are already captured through Grants.gov.", external_added=0, parent_ids=["363065", "363302", "363594"]),
        "b2": {"truth_children": 12, "recovered": 0, "review_only": 0, "publishable": 0, "by_parent": {"363065": 4, "363302": 5, "363594": 3}},
        "b3": {"queries": 4, "retrieved_top_50": 2, "ranks": [1, None, None, 11]},
        "gap_classes": ["SEGMENTATION", "DISCOVERABILITY"], "disposition": "PROMOTE_BEFORE_P9", "obligation": "DEC-20",
        "evidence": [{"sha256": "bd02be187cea06956cb4b337c731e222cba7093c0e26854445324383b76945d1", "name": "DE-FOA-0003627 amendment 3"}, {"sha256": "41a0087dd15dabc35245432b143f6b2c0bbb4083bf0a906f91b1b516eaf2f6dd", "name": "DE-FOA-0003634 Part 2"}, {"sha256": "2e4b3f79516007c7f2190ab68e1b4aef7ef867045272c63f7cf93c8975fea183", "name": "DE-FOA-0003215 Part 2"}],
    },
    "doe-critical-minerals": {
        "b1": _b1("no_current_standard_funding_parent", 0, 0, "Current office name is CMEI; its server-rendered open-funding table is empty. Other rows are notices, RFIs, or fellowships."),
        "b2": {"status": "not_applicable_no_current_parent"}, "b3": {"status": "not_applicable_no_current_parent"},
        "gap_classes": [], "disposition": "NONE",
    },
    "doe-office-electricity": {
        "b1": _b1("edge_mechanism_source_gap", 2, 0, "STEP Prize and an OE test-facility provider voucher are current but are prize/voucher mechanisms, not standard academic NOFOs."),
        "b2": {"status": "not_applicable_parent_source_gap"}, "b3": {"status": "parents_absent"},
        "gap_classes": ["SOURCE_INGESTION"], "disposition": "DEFER_POST_P11",
    },
    "doe-nuclear-energy": {
        "b1": _b1("standard_parent_captured_edge_rfa_absent", 2, 1, "The standard licensing grant parent is captured; a rolling industry facility RFA is outside the present standard academic surface."),
        "b2": {"truth_children": 2, "recovered": 0, "note": "The two-topic list is intentionally rejected by the minimum-three safety floor."},
        "b3": {"queries": 1, "retrieved_top_50": 1, "ranks": [1]},
        "gap_classes": ["SEGMENTATION", "SOURCE_INGESTION"], "disposition": "DEFER_POST_P11",
    },
    "arpa-h": {
        "b1": _b1("source_gap", 11, 0, "The official ARPA-H page lists four programs, two initiatives, the 2026 SBIR/STTR solicitation, and four rolling mission-office ISOs; none is in the catalog."),
        "b2": {"status": "not_measurable_until_parents_are_ingested"},
        "b3": {"exact_official_title_catalog_matches": 0, "note": "Opaque program/ISO parents cannot be discovered because they are absent."},
        "gap_classes": ["SOURCE_INGESTION", "DISCOVERABILITY"], "disposition": "PROMOTE_BEFORE_P9", "obligation": "DEC-19",
    },
    "nasa-roses": {
        "b1": _b1("adapter_healthy_refresh_due", 63, 10, "Live Table 3 had 69 rows: 6 overview and 63 elements. Ten matched the committed catalog; of 53 unmatched, 51 were inactive and two were actionable. The enabled adapter emits those two on refresh.", live_rows=69, overview_rows=6, element_rows=63, unmatched=53, actionable_unmatched=2, inactive_unmatched=51),
        "b2": {"status": "native_table3_path_verified", "actionable_unmatched_elements": 2},
        "b3": {"status": "native_element_titles_supply_discoverability_text_after_refresh"},
        "gap_classes": [], "disposition": "NONE_REFRESH_EXISTING_ADAPTER",
    },
    "nasa-nspires-open-list": {
        "b1": _b1("unmeasurable_client_rendered_list", None, None, "TLS succeeds with the existing narrow legacy-cipher policy and certificate/hostname verification. The 62,315-character search shell contains no server-rendered solicitations; no stable public list endpoint was established."),
        "b2": {"status": "unmeasurable"}, "b3": {"status": "not_applicable_without_verified_net_new_parent"},
        "gap_classes": ["APPLICATION_LAYER"], "disposition": "WONTFIX_UNTIL_FALSIFIED",
    },
    "dod-muri": {
        "b1": _b1("captured_arbitrary_parent_not_muri_truth", 1, 1, "344592 is a current ARL foundational BAA, but its current topic attachment is not a MURI topic list."),
        "b2": {"muri_truth_children": 0, "arl_truth_children": 82, "arl_recovered": 0, "note": "The current ARL topic PDF contains 82 unique ARL-BAA identifiers. MURI appears only as an award mechanism/team exception in amendments."},
        "b3": {"queries": 4, "retrieved_top_50": 3, "ranks": [None, 3, 1, 14], "rules": ["army-research-lab-foundational-baa"]},
        "gap_classes": ["SEGMENTATION", "DISCOVERABILITY"], "disposition": "PROMOTE_BEFORE_P9", "obligation": "DEC-21",
        "evidence": [{"sha256": "c9ab5dd5a95c0f40f68fa4af8b4600c4534e26a15f09a16662e53fb795ba8b24", "name": "Current Research Topics for DEVCOM ARL BAA 9 Dec2024.pdf"}],
    },
    "dod-army-tdac": {
        "b1": _b1("captured", 1, 1, "The long-lived parent is captured."),
        "b2": {"truth_children": 14, "recovered": 14, "confidence": "high", "review_only": 0, "publishable": 14},
        "b3": {"queries": 2, "retrieved_top_50": 0, "ranks": [None, None]},
        "gap_classes": ["DISCOVERABILITY"], "disposition": "ASSIGN_P9_P10",
    },
    "dod-onr": {
        "b1": _b1("captured", 1, 1, "The current long-range BAA is captured."),
        "b2": {"status": "no_safe_record_level_ordinary_list_adjudicated", "production_candidates": 0},
        "b3": {"queries": 3, "retrieved_top_50": 3, "ranks": [2, 4, 10], "rules": ["onr-long-range-baa"]},
        "gap_classes": [], "disposition": "NONE",
    },
    "dod-darpa": {
        "b1": _b1("captured", 1, 1, "The current MMoMA parent is captured."),
        "b2": {"truth_children": 4, "recovered": 4, "confidence": "low", "review_only": 4, "publishable": 0},
        "b3": {"queries": 3, "retrieved_top_50": 2, "ranks": [11, 26, None]},
        "gap_classes": ["REVIEW_STORAGE", "DISCOVERABILITY"], "disposition": "ASSIGN_P9_P10",
    },
    "dod-afosr": {
        "b1": _b1("captured", 1, 1, "The current AFOSR research-interest BAA is captured."),
        "b2": {"truth_children": 36, "recovered": 0, "note": "A.1-A.4 contain 36 ordinary subject portfolios; the three A.5 regional offices are organizational and excluded by DEC-11."},
        "b3": {"queries": 3, "retrieved_top_50": 0, "ranks": [None, None, None]},
        "gap_classes": ["SEGMENTATION", "DISCOVERABILITY"], "disposition": "DEFER_POST_P11",
        "evidence": [{"sha256": "c73cb79cc9831e59f5bdf552ffc737b857c9f75fce2cfb4a78dbec481c37bc2f", "name": "FA955026S0001 AFOSR Open BAA.pdf"}],
    },
    "noaa-baas": {
        "b1": _b1("captured", 5, 5, "All five frozen FY2024-2026 office BAAs are captured."),
        "b2": {"truth_children": 0, "note": "No distinct internal ordinary subject list was established at a useful record level."},
        "b3": {"frozen_queries": 3, "retrieved_top_50": 3, "ranks": [1, 1, 1], "rules": ["noaa-national-weather-service-baa", "noaa-nesdis-star-baa", "noaa-fisheries-baa"], "extra_diagnostic": "A non-frozen STEM education query missed; an extra ocean-acidification query ranked its parent first."},
        "gap_classes": [], "disposition": "NONE",
    },
}


RECOMMENDATIONS = [
    {"gap_id": "M8-G01", "surface": "ARPA-H official public opportunity list", "class": "SOURCE_INGESTION", "effect_size": "11/11 current official parents absent", "repeatability": "single authoritative current list with stable program/ISO structure", "risk": "bounded source adapter; currentness and identity risk", "decision": "PROMOTE_BEFORE_P9", "owner": "DEC-19 / P9.0", "gate": "Reconcile all 11 frozen current official rows with dates and stable IDs, deduplicate against Grants.gov, and add zero false parents.", "reversal_or_stop": "Stop if the official page cannot supply stable identity/currentness without SAM-only data."},
    {"gap_id": "M8-G02", "surface": "HGEO/NETL current NOFO children", "class": "SEGMENTATION_DISCOVERABILITY", "effect_size": "3/3 current parents; 12/12 useful children missed", "repeatability": "three current parents on one official hierarchy", "risk": "bounded source-specific mapping; portal office labels are stale", "decision": "PROMOTE_BEFORE_P9", "owner": "DEC-20 / P9.0", "gate": "Recover the 4/5/3 adjudicated children for the three hashed parents with source provenance and zero added mechanisms.", "reversal_or_stop": "Stop if successor notices do not preserve applicant-selectable topic/subtopic structure."},
    {"gap_id": "M8-G03", "surface": "DEVCOM ARL current topic attachment", "class": "SEGMENTATION_DISCOVERABILITY", "effect_size": "82/82 current ARL topic IDs missed", "repeatability": "long-lived parent with versioned current topic attachment", "risk": "large child count and attachment succession", "decision": "PROMOTE_BEFORE_P9", "owner": "DEC-21 / P9.0", "gate": "Recover exactly the 82 unique ARL-BAA topic IDs from the frozen hash, preserve attachment version provenance, and introduce zero MURI topics.", "reversal_or_stop": "Stop if the current-topic attachment loses unique stable topic IDs or ceases to be applicant-selectable."},
    {"gap_id": "M8-G04", "surface": "Genesis Phase I focus-area workbook", "class": "FORMAT_DEPTH_DISCOVERABILITY", "effect_size": "98/98 deeper focus areas not stored; 87/98 fail top-50 retrieval", "repeatability": "98 rows under all 21 challenge groups in one authoritative workbook", "risk": "spreadsheet semantics and child-depth explosion", "decision": "PROMOTE_BEFORE_P9", "owner": "DEC-22 / P9.0", "gate": "A narrow Genesis handler must reproduce 21 group counts totaling 98, preserve group relationships, and make at least 95/98 exact focus labels retrieve the parent in top 50 without changing generic spreadsheet policy.", "reversal_or_stop": "Stop if the workbook rows are not selectable focus areas in the live application path."},
    {"gap_id": "M8-G05", "surface": "Arm A generic missed-list shapes", "class": "SEGMENTATION", "effect_size": "3/20 measurable records; 36 children", "repeatability": "three unrelated one-off forms", "risk": "high generic-regex safety surface", "decision": "WONTFIX_UNTIL_FALSIFIED", "owner": "post-P11 measurement", "gate": "No generic family change.", "reversal_or_stop": "Reverse only after a pre-frozen sample finds at least two additional current documents sharing one bounded shape and a candidate rule meets the existing precision/safety gates."},
    {"gap_id": "M8-G06", "surface": "AFOSR coded research-interest outline", "class": "SEGMENTATION_DISCOVERABILITY", "effect_size": "36 ordinary portfolios missed; 0/3 exact queries retrieved", "repeatability": "one current BAA", "risk": "coded outline overlaps organizational sections", "decision": "DEFER_POST_P11", "owner": "post-P11 measurement", "gate": "No Fm6 expansion now.", "reversal_or_stop": "Reverse after a second current revision or independent authoritative notice repeats the bounded A.1-A.4 subject shape without A.5 offices."},
    {"gap_id": "M8-G07", "surface": "Office of Electricity edge mechanisms", "class": "SOURCE_INGESTION", "effect_size": "2 current prize/voucher parents absent", "repeatability": "two non-NOFO mechanisms", "risk": "scope expansion outside standard academic funding", "decision": "DEFER_POST_P11", "owner": "post-P11 source-scope review", "gate": "No adapter now.", "reversal_or_stop": "Reverse on a current standard research NOFO or an explicit product decision to include prizes/vouchers."},
    {"gap_id": "M8-G08", "surface": "Nuclear two-topic list and rolling industry RFA", "class": "SEGMENTATION_SOURCE_INGESTION", "effect_size": "2 intentional-floor children; one industry RFA absent", "repeatability": "one current case each", "risk": "loosening minimum-three floor harms precision", "decision": "DEFER_POST_P11", "owner": "post-P11 source-scope review", "gate": "Do not loosen the floor.", "reversal_or_stop": "Reverse after a pre-frozen repeated two-topic population passes a dedicated precision gate or the RFA enters academic scope."},
    {"gap_id": "M8-G09", "surface": "TDAC and DARPA recovered children", "class": "REVIEW_STORAGE_DISCOVERABILITY", "effect_size": "18 recovered children; 14 publishable and 4 review-only", "repeatability": "existing bounded handlers", "risk": "identity, review, and search indexing", "decision": "ASSIGN_P9_P10", "owner": "P9 storage / P10 review", "gate": "Persist provenance and review state; index approved child titles; preserve low-confidence review-only status."},
    {"gap_id": "M8-G10", "surface": "NSPIRES open-list residual", "class": "APPLICATION_LAYER", "effect_size": "unknown; list not server-rendered", "repeatability": "transport succeeds but no stable list endpoint", "risk": "fragile browser/session automation", "decision": "WONTFIX_UNTIL_FALSIFIED", "owner": "future source measurement", "gate": "No adapter now.", "reversal_or_stop": "Reverse only when a stable public authoritative list exposes at least two net-new current actionable parents under normal client behavior."},
    {"gap_id": "M8-G11", "surface": "generic Word/OOXML extraction", "class": "FORMAT", "effect_size": "0 falsifiers in Arm A; DOCX files were forms", "repeatability": "none", "risk": "broad format surface", "decision": "WONTFIX_UNTIL_FALSIFIED", "owner": "future measurement", "gate": "Keep existing policy.", "reversal_or_stop": "Reverse on a hashed current DOCX containing a genuine missed applicant-selectable list."},
    {"gap_id": "M8-G12", "surface": "generic spreadsheet extraction", "class": "FORMAT", "effect_size": "0 generic falsifiers; Genesis is a named exception", "repeatability": "budget/template sheets only outside Genesis", "risk": "broad tabular false positives", "decision": "WONTFIX_UNTIL_FALSIFIED", "owner": "future measurement", "gate": "Keep generic policy; DEC-22 is narrow.", "reversal_or_stop": "Reverse on at least two independently sampled authoritative spreadsheets with the same bounded selectable-list shape."},
    {"gap_id": "M8-G13", "surface": "program_taxonomy source surface", "class": "SOURCE_INGESTION", "effect_size": "zero current actionable parents established", "repeatability": "none", "risk": "taxonomy is not funding truth", "decision": "WONTFIX_UNTIL_FALSIFIED", "owner": "future source measurement", "gate": "No adapter now.", "reversal_or_stop": "Reverse when a stable authoritative external child population adds at least two current actionable parents not otherwise reachable."},
]


def _wilson(successes, n, z=1.959963984540054):
    if not n:
        return [None, None]
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return [round(centre - margin, 6), round(centre + margin, 6)]


def _arm_a_records(frame):
    rows = []
    for stratum in frame["arm_a"]["strata"]:
        weight = stratum["selection_weight_per_record"]
        for frozen in stratum["records"]:
            rid = frozen["opportunity_id"]
            sha256, chars, url = SOURCE_OBSERVATIONS[rid]
            base = {
                "opportunity_id": rid,
                "title": frozen["title"],
                "stratum": stratum["name"],
                "selection_weight": weight,
                "source_observation": {"url": url, "sha256": sha256, "truth_text_characters": chars},
            }
            if rid in TRUTH_POSITIVES:
                positive = TRUTH_POSITIVES[rid]
                recovered = positive["production"]["candidates"] > 0
                base.update({"measurement_state": "truth_positive", "truth_child_count": len(positive["children"]), "recovered": recovered, **positive})
            elif rid in UNMEASURABLE:
                layer, note = UNMEASURABLE[rid]
                base.update({"measurement_state": "unmeasurable", "failure_layer": layer, "truth_child_count": None, "recovered": None, "adjudication_note": note})
            elif rid in NON_SUBJECT:
                base.update({"measurement_state": "measurable_non_subject_structure", "truth_child_count": 0, "recovered": False, "adjudication_note": NON_SUBJECT[rid]})
            else:
                base.update({"measurement_state": "measurable_no_list", "truth_child_count": 0, "recovered": False, "adjudication_note": NO_LIST[rid]})
            rows.append(base)
    return rows


def _arm_a_summary(frame, rows):
    measurable = [row for row in rows if row["measurement_state"] != "unmeasurable"]
    positives = [row for row in measurable if row["measurement_state"] == "truth_positive"]
    missed = [row for row in positives if not row["recovered"]]
    recovered = [row for row in positives if row["recovered"]]
    weighted_measurable = sum(row["selection_weight"] for row in measurable)
    weighted_positive = sum(row["selection_weight"] for row in positives)
    weighted_missed = sum(row["selection_weight"] for row in missed)
    weighted_recovered = sum(row["selection_weight"] for row in recovered)
    population = frame["arm_a"]["eligible_population"]
    unknown = population - weighted_measurable
    child_total = sum(row["truth_child_count"] for row in positives)
    recovered_children = sum(row["truth_child_count"] for row in recovered)
    by_stratum = {}
    for stratum in frame["arm_a"]["strata"]:
        subset = [row for row in rows if row["stratum"] == stratum["name"]]
        by_stratum[stratum["name"]] = {
            "eligible_population": stratum["eligible_population"],
            "sample_size": len(subset),
            "measurable": sum(row["measurement_state"] != "unmeasurable" for row in subset),
            "truth_positive": sum(row["measurement_state"] == "truth_positive" for row in subset),
            "missed_truth_positive": sum(row["measurement_state"] == "truth_positive" and not row["recovered"] for row in subset),
        }
    return {
        "sample_denominator": len(rows), "measurable_records": len(measurable), "unmeasurable_records": len(rows) - len(measurable),
        "truth_positive_records": len(positives), "missed_truth_positive_records": len(missed), "recovered_truth_positive_records": len(recovered),
        "truth_children": child_total, "recovered_truth_children": recovered_children, "missed_truth_children": child_total - recovered_children,
        "production_candidates": 9, "cov4_calls": 9, "cov4_errors": 0, "cov4_accept": 9, "review_only_children": 9, "publishable_children": 0,
        "unweighted_descriptive": {
            "truth_positive_rate_among_measurable": round(len(positives) / len(measurable), 6),
            "truth_positive_wilson_95": _wilson(len(positives), len(measurable)),
            "miss_rate_among_measurable": round(len(missed) / len(measurable), 6),
            "miss_wilson_95": _wilson(len(missed), len(measurable)),
            "record_recovery_among_observed_positives": round(len(recovered) / len(positives), 6),
            "child_recovery_among_observed_children": round(recovered_children / child_total, 6),
            "warning": "Wilson intervals are descriptive only; the primary frame uses unequal stratum weights.",
        },
        "weighted": {
            "eligible_population": population, "measurable_population_equivalent": round(weighted_measurable, 6), "unknown_population_equivalent": round(unknown, 6),
            "truth_positive_population_equivalent": round(weighted_positive, 6), "missed_population_equivalent": round(weighted_missed, 6), "recovered_population_equivalent": round(weighted_recovered, 6),
            "truth_positive_rate_among_measurable": round(weighted_positive / weighted_measurable, 6),
            "miss_rate_among_measurable": round(weighted_missed / weighted_measurable, 6),
            "record_recovery_among_observed_positives": round(weighted_recovered / weighted_positive, 6),
            "full_frame_truth_prevalence_identification_bounds": [round(weighted_positive / population, 6), round((weighted_positive + unknown) / population, 6)],
            "full_frame_miss_prevalence_identification_bounds": [round(weighted_missed / population, 6), round((weighted_missed + unknown) / population, 6)],
            "point_estimate_policy": "No full-frame point estimate: every DOE residual and the NASA residual were unmeasurable; unknowns are not zeros.",
        },
        "by_stratum": by_stratum,
    }


def build_results():
    frame = json.loads(FRAME_PATH.read_text(encoding="utf-8"))
    arm_a_rows = _arm_a_records(frame)
    frozen_case_ids = [case["case_id"] for case in frame["arm_b"]["cases"]]
    if set(frozen_case_ids) != set(ARM_B_RESULTS):
        raise RuntimeError("Arm B result keys do not match the frozen frame")
    return {
        "schema_version": 1,
        "purpose": "MEAS-8 measurement-only two-arm hierarchy, format, source, and discoverability audit",
        "measured_at": "2026-08-20",
        "catalog_commit": frame["catalog_commit"],
        "frame_commit": FRAME_COMMIT,
        "frame_path": "evaluation/meas8_frame.json",
        "production_change_policy": "No production parser, source adapter, catalog, ranking, generated site, or publication behavior changed in MEAS-8.",
        "method": {
            "live_rederivation": "Current Grants.gov detail/attachment lists and named official sources were re-read; committed hashes identify the measured bytes.",
            "truth_reading": "PDF, HTML, DOCX, and XLSX were read out of band for adjudication only.",
            "production_probe": "Existing source selection, referenced-source refusal, deterministic segmentation, candidate construction, and final confidence gate were invoked in production order.",
            "cov4_policy": "Cov4 ran only on the one Arm A record that produced candidates, using the configured model, one repeat, and nine calls. Credentials and raw model responses are not stored.",
            "discoverability_probe": "Exact production browser ranking was replayed against the frozen committed catalog with tools/meas8_query_probe.mjs.",
            "unmeasurable_policy": "Client-rendered, changed, mismatched, unsupported, and unreachable source states remain unknown and are never converted to zero.",
            "arm_separation": "Arm A is the only prevalence denominator. Arm B is purposive and has no prevalence estimate or confidence interval.",
        },
        "arm_a": {"records": arm_a_rows, "summary": _arm_a_summary(frame, arm_a_rows)},
        "arm_b": {"case_count": len(frozen_case_ids), "questions": frame["arm_b"]["questions"], "cases": [{"case_id": case_id, **ARM_B_RESULTS[case_id]} for case_id in frozen_case_ids]},
        "cross_cutting_obligations": {
            "MEAS-4": {"status": "CLOSED", "finding": "344592 does not contain MURI topic truth. It contains 82 current ARL topics, tracked separately by DEC-21; no SAM adapter is justified by the MURI hypothesis."},
            "MEAS-6": {"status": "HUMAN_BLOCKER", "finding": "No SAM.gov API credential was available. Public official-source evidence supports the ARPA-H gap, but MEAS-8 does not claim a complete SAM-only universe."},
            "DEBT-6": {"status": "CLOSED", "finding": "Reachability layers were reclassified: NASA and NSF transport works under existing narrow policy; NYSERDA and NSPIRES are application/client-rendering conditions; NIAC is source selection; SAM evidence remains credential/client limited."},
            "DEBT-10": {"status": "SATISFIED_FOR_MEAS8", "finding": "All attachment counts used here were re-derived from live Grants.gov details; stale census counts were not treated as current truth."},
            "DEBT-11": {"status": "CLOSED", "finding": "Both arms, routes, and queries were committed at the frame commit before outcomes; no case or sample replacement occurred."},
            "NSPIRES_OPEN_LIST": {"status": "WONTFIX_UNTIL_FALSIFIED", "reversal_condition": "Stable public authoritative list plus at least two verifiable net-new current actionable parents."},
            "WORD_OOXML": {"status": "WONTFIX_UNTIL_FALSIFIED", "reversal_condition": "A hashed current DOCX with a genuine missed applicant-selectable list."},
            "GENERIC_SPREADSHEET": {"status": "WONTFIX_UNTIL_FALSIFIED", "finding": "No generic falsifier; Genesis is a narrow named exception under DEC-22."},
            "PROGRAM_TAXONOMY": {"status": "WONTFIX_UNTIL_FALSIFIED", "reversal_condition": "Stable authoritative external child population with at least two current actionable parents not otherwise reachable."},
        },
        "recommendations": RECOMMENDATIONS,
        "next": "P9.0 - re-key the hierarchy identity model from slug-only to canonical `opportunity_id` (`DEC-16`, `BUG-14`, `DEBT-13`) and resolve the pre-storage MEAS-8 decisions/correctness obligations before changing storage shape.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    rendered = json.dumps(build_results(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.write:
        RESULTS_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    if args.check and RESULTS_PATH.read_text(encoding="utf-8") != rendered:
        raise SystemExit("evaluation/meas8_results.json does not match the deterministic builder")
    if not args.write and not args.check:
        print(rendered, end="")


if __name__ == "__main__":
    main()
