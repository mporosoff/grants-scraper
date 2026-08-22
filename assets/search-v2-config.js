(() => {
  "use strict";
  globalThis.FUNDING_SEARCH_V2_CONFIG = Object.freeze({
    "schema_version": 2,
    "contract_version": "search-v2-track-b-2",
    "asset_version": "search-v2-phase2-1-20260822",
    "compatibility": {
      "query_api_contract_version": 3,
      "retrieval_api_contract_version": 3,
      "parent_catalog_schema_version": 3,
      "child_catalog_schema_version": 1,
      "search_index_algorithm": "bm25",
      "evidence_schema_version": 2
    },
    "protected_concepts": {
      "rare-earth-elements": {
        "role": "target",
        "accepted_explicit_evidence": [
          "REE or REEs with rare-earth technical context",
          "rare earth or rare-earth element phrase",
          "lanthanide or lanthanides",
          "scandium",
          "yttrium"
        ],
        "forbidden_shortcuts": [
          "earth alone",
          "element alone",
          "scattered rare plus earth",
          "generic critical minerals alone",
          "generic agency, discipline, topic, or category metadata"
        ]
      },
      "separations": {
        "role": "method",
        "accepted_query_forms": [
          "separation",
          "separations",
          "extraction",
          "processing",
          "recovery",
          "purification",
          "solvent extraction"
        ]
      },
      "ionic-liquid-extraction": {
        "role": "method",
        "controlled_relationship": "ionic-liquid extraction is a specialization of chemical separation and extraction"
      }
    },
    "query_contract_cases": [
      {
        "query": "REE",
        "concept_ids": [
          "rare-earth-elements"
        ]
      },
      {
        "query": "REEs",
        "concept_ids": [
          "rare-earth-elements"
        ]
      },
      {
        "query": "R.E.E.",
        "concept_ids": [
          "rare-earth-elements"
        ]
      },
      {
        "query": "rare-earth elements",
        "concept_ids": [
          "rare-earth-elements"
        ]
      },
      {
        "query": "REE separations",
        "concept_ids": [
          "rare-earth-elements",
          "separations"
        ]
      },
      {
        "query": "lanthanide separation",
        "concept_ids": [
          "rare-earth-elements",
          "separations"
        ]
      },
      {
        "query": "solvent extraction of REEs",
        "concept_ids": [
          "separations",
          "rare-earth-elements"
        ]
      },
      {
        "query": "ionic liquids for REE extraction",
        "concept_ids": [
          "ionic-liquid-extraction",
          "rare-earth-elements",
          "separations"
        ]
      },
      {
        "query": "critical mineral separations",
        "concept_ids": [
          "critical-minerals",
          "separations"
        ]
      }
    ],
    "authoritative_scope_entailments": [
      {
        "id": "doe-bes-separation-science-ree",
        "parent_id": "360678",
        "supported_query_concepts": [
          "rare-earth-elements",
          "separations",
          "ionic-liquid-extraction"
        ],
        "required_query_concepts": [
          "rare-earth-elements",
          "separations"
        ],
        "authoritative_scope": {
          "kind": "controlled_program_area",
          "record_id": "360678:rss",
          "label": "Basic Energy Sciences — Separation Science",
          "source_url": "https://science.osti.gov"
        },
        "controlled_relationships": [
          "rare-earth separation is a specialization of separation science",
          "ionic-liquid extraction is a specialization of chemical separation"
        ]
      },
      {
        "id": "genesis-critical-minerals-extraction-ree",
        "parent_id": "361526",
        "supported_query_concepts": [
          "rare-earth-elements",
          "separations",
          "ionic-liquid-extraction"
        ],
        "required_query_concepts": [
          "rare-earth-elements",
          "separations"
        ],
        "authoritative_scope": {
          "kind": "publication_eligible_child",
          "record_id": "361526:d-3",
          "label": "Securing America’s Critical Minerals Supply — Extraction and Processing Technologies",
          "source_url": "https://grants.gov/grantsws/rest/opportunity/att/download/350588"
        },
        "controlled_relationships": [
          "rare-earth elements are a subset of critical minerals",
          "rare-earth separation is an extraction, processing, or recovery operation",
          "ionic-liquid extraction is a specialization of extraction and processing"
        ]
      },
      {
        "id": "nsf-cps-critical-minerals-separations-ree",
        "parent_id": "362061",
        "supported_query_concepts": [
          "rare-earth-elements",
          "separations",
          "ionic-liquid-extraction"
        ],
        "required_query_concepts": [
          "rare-earth-elements",
          "separations"
        ],
        "authoritative_scope": {
          "kind": "parent_program_scope",
          "record_id": "362061",
          "label": "Chemical Process Systems — Critical Minerals and Separations",
          "source_url": "https://www.nsf.gov/funding/pgm_summ.jsp?pims_id=506547"
        },
        "controlled_relationships": [
          "rare-earth elements are a subset of critical minerals",
          "rare-earth separation is contained within chemical separation processes",
          "ionic-liquid extraction is a specialization of chemical separation"
        ]
      }
    ],
    "scope_entailment_score": 1,
    "scope_entailment_requires_complete_scientific_query": true
  });
})();
