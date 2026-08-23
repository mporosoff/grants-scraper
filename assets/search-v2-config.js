(() => {
  "use strict";
  globalThis.FUNDING_SEARCH_V2_CONFIG = Object.freeze({
    "schema_version": 2,
    "contract_version": "search-v2-iteration2-1",
    "asset_version": "search-v2-phase2r-iteration2-20260822",
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
          "solvent extraction",
          "ion exchange",
          "hydrometallurgy",
          "leaching",
          "refining",
          "recycling",
          "resource recovery"
        ]
      },
      "ionic-liquid-extraction": {
        "role": "method",
        "controlled_relationship": "ionic-liquid extraction is a specialization of chemical separation and extraction"
      }
    },
    "concept_families": [
      {
        "canonical_id": "rare-earth-elements",
        "relationship_type": "bounded_material_family",
        "query_forms": [
          "REE",
          "REEs",
          "rare earth elements",
          "lanthanides",
          "scandium",
          "yttrium"
        ],
        "source_rationale": "USGS and DOE critical-minerals usage treats the lanthanide series plus scandium and yttrium as the bounded rare-earth family.",
        "observed_need": [
          "hold_ree_03",
          "hold_ree_05",
          "hold_ree_06"
        ],
        "directionality": "named member to rare-earth family only",
        "transitive": false
      },
      {
        "canonical_id": "separations",
        "relationship_type": "bounded_operation_family",
        "query_forms": [
          "separation",
          "extraction",
          "solvent extraction",
          "ion exchange",
          "recovery",
          "purification",
          "hydrometallurgy",
          "leaching",
          "refining",
          "recycling",
          "resource recovery",
          "processing"
        ],
        "source_rationale": "The existing BES, Genesis critical-minerals, and CPS source scopes group these chemical separation, extraction, processing, and resource-recovery operations.",
        "observed_need": [
          "hold_ree_01",
          "hold_ree_03",
          "hold_ree_04"
        ],
        "directionality": "specialized operation to separation-processing family only",
        "transitive": false
      },
      {
        "canonical_id": "maternal-health",
        "relationship_type": "bounded_clinical_population_family",
        "query_forms": [
          "maternal mortality",
          "maternity",
          "obstetric care"
        ],
        "source_rationale": "Rural MOMS explicitly funds maternity and obstetric care access; maternal mortality is a bounded maternal-health outcome rather than a generic health synonym.",
        "observed_need": [
          "hold_health_01"
        ],
        "directionality": "maternal mortality or obstetric/maternity care to maternal-health only",
        "transitive": false
      },
      {
        "canonical_id": "rural-care-context",
        "relationship_type": "bounded_population_context",
        "query_forms": [
          "rural communities",
          "rural areas",
          "rural care"
        ],
        "source_rationale": "Rural MOMS explicitly limits its care-access scope to rural areas and collaborative networks.",
        "observed_need": [
          "hold_health_01"
        ],
        "directionality": "rural population/location wording to rural-care context only",
        "transitive": false
      },
      {
        "canonical_id": "drought-resilience",
        "relationship_type": "bounded_trait_relationship",
        "query_forms": [
          "drought tolerant",
          "drought resilience",
          "abiotic stress tolerance"
        ],
        "source_rationale": "Drought tolerance is a bounded plant abiotic-stress trait; AFRI source evidence explicitly covers plant traits and biotic/abiotic stresses.",
        "observed_need": [
          "hold_ag_01"
        ],
        "directionality": "drought tolerance to plant abiotic-stress resilience only",
        "transitive": false
      },
      {
        "canonical_id": "crop-genetics",
        "relationship_type": "bounded_organism_method_family",
        "query_forms": [
          "crop genetics",
          "plant genetics",
          "plant breeding",
          "crop genomics"
        ],
        "source_rationale": "AFRI authoritative source scope covers plant production, plant breeding, genetics/genomics, traits, and crop systems.",
        "observed_need": [
          "hold_ag_01"
        ],
        "directionality": "crop genetics/breeding to plant genetics scope only",
        "transitive": false
      },
      {
        "canonical_id": "energy-storage",
        "relationship_type": "bounded_technology_family",
        "query_forms": [
          "energy storage",
          "grid storage"
        ],
        "source_rationale": "SCALEUP official source evidence identifies energy-storage and grid technologies.",
        "observed_need": [
          "hold_energy_01"
        ],
        "directionality": "storage technology to energy-storage family only",
        "transitive": false
      },
      {
        "canonical_id": "long-duration",
        "relationship_type": "bounded_technology_property",
        "query_forms": [
          "long duration",
          "long-duration"
        ],
        "source_rationale": "The adjudicated SCALEUP scope contains long-duration energy storage; administrative project duration is expressly excluded.",
        "observed_need": [
          "hold_energy_01"
        ],
        "directionality": "long duration modifies the energy-storage technology only",
        "transitive": false
      },
      {
        "canonical_id": "foundation-models",
        "relationship_type": "bounded_ai_target_family",
        "query_forms": [
          "foundation model",
          "foundation models"
        ],
        "source_rationale": "Genesis publishes a Composable and Modular Foundation Models child under AI for Scientific Reasoning.",
        "observed_need": [
          "hold_ai_01"
        ],
        "directionality": "foundation-model wording to the AI model family only",
        "transitive": false
      },
      {
        "canonical_id": "security-resilience",
        "relationship_type": "bounded_ai_property_family",
        "query_forms": [
          "secure",
          "security",
          "adversarial robustness",
          "resilience"
        ],
        "source_rationale": "Genesis publishes AI adversarial robustness/resilience and real-time attack mitigation children; generic institutional security does not satisfy this property.",
        "observed_need": [
          "hold_ai_01"
        ],
        "directionality": "security property to technical AI robustness only when paired with an AI/model target",
        "transitive": false
      },
      {
        "canonical_id": "catalyst-design",
        "query_forms": [
          "catalyst design",
          "catalyst discovery",
          "catalyst optimization",
          "catalyst screening"
        ],
        "relationship_type": "bounded_target_operation_family",
        "directionality": "listed scientific catalyst-development operations only",
        "source_rationale": "Catalyst design, discovery, optimization, and screening are established names for closely bounded catalyst-development operations; generic uses of catalyst are excluded.",
        "observed_need": [
          "adv_chem_02",
          "361526:g-12"
        ],
        "transitive": false
      },
      {
        "canonical_id": "high-performance-computing",
        "query_forms": [
          "high-performance computing",
          "high performance computing",
          "supercomputing"
        ],
        "relationship_type": "bounded_technology_synonym_family",
        "directionality": "listed computing technology forms only",
        "source_rationale": "High-performance computing and supercomputing are established equivalent technology labels in program scope.",
        "observed_need": [
          "m5_ai_04"
        ],
        "transitive": false
      },
      {
        "canonical_id": "earth-system",
        "relationship_type": "bounded_scientific_system",
        "query_forms": [
          "Earth system",
          "Sun-Earth system"
        ],
        "source_rationale": "Geospace explicitly supports research on the coupled Sun-Earth system.",
        "observed_need": [
          "hold_space_02"
        ],
        "directionality": "Earth-system compound to coupled Earth/near-space systems only",
        "transitive": false
      },
      {
        "canonical_id": "chemical-processes",
        "relationship_type": "bounded_process_family",
        "query_forms": [
          "chemical elements",
          "chemical processes"
        ],
        "source_rationale": "The adjudicated Geospace anchor explicitly covers chemical processes in the coupled Sun-Earth system; administrative program-element text is excluded.",
        "observed_need": [
          "hold_space_02"
        ],
        "directionality": "chemical-elements intent to explicit coupled-system chemical-process scope only",
        "transitive": false
      },
      {
        "canonical_id": "pfas-contamination",
        "relationship_type": "bounded_contaminant_family",
        "query_forms": [
          "PFAS",
          "PFOA",
          "PFOS",
          "perfluoroalkyl substances"
        ],
        "source_rationale": "The existing guarded PFAS vocabulary identifies the contaminant family without treating generic water, cancer, or membrane language as PFAS evidence.",
        "observed_need": [
          "hold_env_01"
        ],
        "directionality": "named PFAS-family evidence to PFAS contamination only",
        "transitive": false
      },
      {
        "canonical_id": "membrane-treatment",
        "relationship_type": "bounded_environmental_method_family",
        "query_forms": [
          "membrane treatment",
          "membrane purification",
          "membrane separation"
        ],
        "source_rationale": "DWPR and CPS authoritative scopes cover membrane-based water treatment, purification, and separation.",
        "observed_need": [
          "hold_env_01"
        ],
        "directionality": "membrane method to treatment/separation scope only",
        "transitive": false
      },
      {
        "canonical_id": "rare-disease-molecular-genomics",
        "relationship_type": "bounded_biomedical_compound",
        "query_forms": [
          "rare disease molecular",
          "rare genetic disorder genomics"
        ],
        "source_rationale": "GREGoRi explicitly funds molecular technologies and genomic/genetic methods for rare-disease diagnosis.",
        "observed_need": [
          "hold_ree_08"
        ],
        "directionality": "rare-disease molecular/genomic intent only",
        "transitive": false
      },
      {
        "canonical_id": "education-innovation",
        "relationship_type": "bounded_nonchemical_compound",
        "query_forms": [
          "innovation catalyst",
          "innovative education strategy"
        ],
        "source_rationale": "In an education query, catalyst denotes an innovation/change role rather than chemical catalysis.",
        "observed_need": [
          "hold_chem_02"
        ],
        "directionality": "only when paired with explicit student/education context",
        "transitive": false
      },
      {
        "canonical_id": "student-success",
        "relationship_type": "bounded_education_outcome",
        "query_forms": [
          "student success",
          "student retention and graduation"
        ],
        "source_rationale": "S-STEM and LSAMP explicitly fund student success, retention, pathways, and graduation.",
        "observed_need": [
          "hold_chem_02"
        ],
        "directionality": "education outcome only",
        "transitive": false
      },
      {
        "canonical_id": "single-cell-biology",
        "relationship_type": "bounded_biological_method",
        "query_forms": [
          "single cell",
          "single-cell",
          "cellular physiology"
        ],
        "source_rationale": "The Mathers scope explicitly includes cellular physiology and basic cell biology.",
        "observed_need": [
          "hold_bio_01"
        ],
        "directionality": "single-cell query method to cellular-biology scope only",
        "transitive": false
      },
      {
        "canonical_id": "cancer-immunology",
        "relationship_type": "bounded_disease_mechanism",
        "query_forms": [
          "cancer immunology",
          "tumor immunity"
        ],
        "source_rationale": "The Mathers scope explicitly includes both cancer biology and immunology.",
        "observed_need": [
          "hold_bio_01"
        ],
        "directionality": "cancer plus immune mechanism only",
        "transitive": false
      },
      {
        "canonical_id": "electrocatalysis",
        "relationship_type": "bounded_electrochemical_method",
        "query_forms": [
          "electrocatalytic",
          "electrocatalysis"
        ],
        "source_rationale": "The ARL Electrochemistry child explicitly funds electrochemical redox reactions and electrocatalysis.",
        "observed_need": [
          "hold_chem_01"
        ],
        "directionality": "electrocatalytic method to electrochemistry child scope only",
        "transitive": false
      },
      {
        "canonical_id": "ammonia-synthesis",
        "relationship_type": "bounded_chemical_target_operation",
        "query_forms": [
          "ammonia synthesis",
          "electrochemical ammonia production"
        ],
        "source_rationale": "The adjudicated ARL result treats electrocatalytic ammonia synthesis as a redox/catalysis specialization of its Electrochemistry child.",
        "observed_need": [
          "hold_chem_01"
        ],
        "directionality": "ammonia synthesis to electrochemical redox/catalysis scope only",
        "transitive": false
      },
      {
        "canonical_id": "high-temperature-materials",
        "relationship_type": "bounded_material_property",
        "query_forms": [
          "high temperature composites",
          "high-temperature structural materials"
        ],
        "source_rationale": "The ARL Super-Materials child explicitly funds structural materials at high temperature under dynamic thermal conditions.",
        "observed_need": [
          "hold_defense_01"
        ],
        "directionality": "high-temperature structural/composite materials only",
        "transitive": false
      },
      {
        "canonical_id": "hypersonic-environment",
        "relationship_type": "bounded_defense_environment",
        "query_forms": [
          "hypersonic environment",
          "extreme dynamic thermal environment"
        ],
        "source_rationale": "The adjudicated ARL anchor maps hypersonic operation to the Super-Materials child's high-temperature, highly dynamic extreme-environment scope.",
        "observed_need": [
          "hold_defense_01"
        ],
        "directionality": "hypersonic to high-temperature dynamic extreme environments only",
        "transitive": false
      }
    ],
    "controlled_relationships": [
      {
        "canonical_id": "ree-subset-critical-minerals",
        "relationship_type": "subset_of",
        "from": "rare-earth-elements",
        "to": "critical-minerals",
        "source_rationale": "DOE/USGS critical-minerals classification used by the Genesis and CPS authoritative scopes.",
        "observed_need": [
          "hold_ree_01",
          "hold_ree_03",
          "hold_ree_04",
          "hold_ree_05",
          "hold_ree_06"
        ],
        "directionality": "from rare-earth family to critical-minerals scope only",
        "transitive": false
      },
      {
        "canonical_id": "ree-operations-separation-processing",
        "relationship_type": "specialization_of",
        "from": "rare-earth separation and recovery operations",
        "to": "separations",
        "source_rationale": "BES Separation Science, Genesis Extraction and Processing Technologies, and CPS separations scope.",
        "observed_need": [
          "hold_ree_01",
          "hold_ree_03",
          "hold_ree_04"
        ],
        "directionality": "specialized operation to funded separation-processing scope only",
        "transitive": false
      },
      {
        "canonical_id": "drought-abiotic-stress",
        "relationship_type": "specialization_of",
        "from": "drought-resilience",
        "to": "plant abiotic-stress resilience",
        "source_rationale": "AFRI official source evidence on plant traits and biotic/abiotic stresses.",
        "observed_need": [
          "hold_ag_01"
        ],
        "directionality": "drought trait to plant abiotic-stress scope only",
        "transitive": false
      }
    ],
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
      },
      {
        "query": "rare earth recycling",
        "concept_ids": [
          "rare-earth-elements",
          "separations"
        ]
      },
      {
        "query": "lanthanide ion exchange",
        "concept_ids": [
          "rare-earth-elements",
          "separations"
        ]
      },
      {
        "query": "REE hydrometallurgy",
        "concept_ids": [
          "rare-earth-elements",
          "separations"
        ]
      },
      {
        "query": "yttrium separation",
        "concept_ids": [
          "rare-earth-elements",
          "separations"
        ]
      },
      {
        "query": "scandium recovery",
        "concept_ids": [
          "rare-earth-elements",
          "separations"
        ]
      },
      {
        "query": "maternal mortality rural communities",
        "concept_ids": [
          "maternal-health",
          "rural-care-context"
        ]
      },
      {
        "query": "drought tolerant crop genetics",
        "concept_ids": [
          "drought-resilience",
          "crop-genetics"
        ]
      },
      {
        "query": "long duration energy storage",
        "concept_ids": [
          "long-duration",
          "energy-storage"
        ]
      },
      {
        "query": "secure foundation models",
        "concept_ids": [
          "security-resilience",
          "foundation-models"
        ]
      },
      {
        "query": "AI catalyst design",
        "concept_ids": [
          "artificial-intelligence",
          "catalyst-design"
        ]
      },
      {
        "query": "trustworthy artificial intelligence",
        "concept_ids": [
          "literal:trustworthy",
          "artificial-intelligence"
        ]
      },
      {
        "query": "high performance computing",
        "concept_ids": [
          "high-performance-computing"
        ]
      },
      {
        "query": "Earth system chemical elements",
        "concept_ids": [
          "earth-system",
          "chemical-processes"
        ]
      },
      {
        "query": "membrane PFAS treatment",
        "concept_ids": [
          "membrane-treatment",
          "pfas-contamination"
        ]
      },
      {
        "query": "rare disease molecular elements",
        "concept_ids": [
          "rare-disease-molecular-genomics"
        ]
      },
      {
        "query": "innovation catalyst student success",
        "concept_ids": [
          "education-innovation",
          "student-success"
        ]
      },
      {
        "query": "single cell cancer immunology",
        "concept_ids": [
          "single-cell-biology",
          "cancer-immunology"
        ]
      },
      {
        "query": "electrocatalytic ammonia synthesis",
        "concept_ids": [
          "electrocatalysis",
          "ammonia-synthesis"
        ]
      },
      {
        "query": "high temperature hypersonic composites",
        "concept_ids": [
          "high-temperature-materials",
          "hypersonic-environment"
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
      },
      {
        "id": "rural-moms-maternal-rural-care",
        "parent_id": "363582",
        "supported_query_concepts": [
          "maternal-health",
          "rural-care-context"
        ],
        "required_query_concepts": [
          "maternal-health",
          "rural-care-context"
        ],
        "authoritative_scope": {
          "kind": "parent_program_scope",
          "record_id": "363582",
          "label": "Rural MOMS — Rural Maternity and Obstetrics Care Access",
          "source_url": "https://www.grants.gov"
        },
        "controlled_relationships": [
          "maternal mortality is a maternal-health outcome within maternity and obstetric care",
          "rural communities are the population and delivery context explicitly funded by Rural MOMS"
        ]
      },
      {
        "id": "afri-drought-crop-genetics",
        "parent_id": "360205",
        "supported_query_concepts": [
          "drought-resilience",
          "crop-genetics"
        ],
        "required_query_concepts": [
          "drought-resilience",
          "crop-genetics"
        ],
        "authoritative_scope": {
          "kind": "authoritative_parent_source_scope",
          "record_id": "360205",
          "label": "AFRI — Plant Production, Breeding, Genetics, Traits, and Abiotic Stress",
          "source_url": "https://www.nifa.usda.gov"
        },
        "controlled_relationships": [
          "drought tolerance is a bounded plant abiotic-stress resilience trait",
          "crop genetics is contained in AFRI plant breeding, genetics, genomics, and trait scope"
        ]
      },
      {
        "id": "scaleup-long-duration-energy-storage",
        "parent_id": "356623",
        "supported_query_concepts": [
          "long-duration",
          "energy-storage"
        ],
        "required_query_concepts": [
          "long-duration",
          "energy-storage"
        ],
        "authoritative_scope": {
          "kind": "authoritative_parent_source_scope",
          "record_id": "356623",
          "label": "SCALEUP — Grid-Scale and Energy-Storage Technologies",
          "source_url": "https://arpa-e-foa.energy.gov"
        },
        "controlled_relationships": [
          "long-duration energy storage is contained in the adjudicated SCALEUP grid-scale energy-storage technology scope",
          "administrative project duration is not scientific long-duration evidence"
        ]
      },
      {
        "id": "genesis-secure-foundation-models",
        "parent_id": "361526",
        "supported_query_concepts": [
          "security-resilience",
          "foundation-models"
        ],
        "required_query_concepts": [
          "security-resilience",
          "foundation-models"
        ],
        "authoritative_scope": {
          "kind": "publication_eligible_child_scope",
          "record_id": "361526:c-19+361526:a-20",
          "label": "Genesis — Composable and Modular Foundation Models; AI Adversarial Robustness and Resilience",
          "source_url": "https://grants.gov/grantsws/rest/opportunity/att/download/350588"
        },
        "controlled_relationships": [
          "the foundation-model target is explicit in publication-eligible child 361526:c-19",
          "the secure and resilient AI property is explicit in publication-eligible child 361526:a-20"
        ]
      },
      {
        "id": "cps-ai-catalyst-design",
        "parent_id": "362061",
        "supported_query_concepts": [
          "artificial-intelligence",
          "catalyst-design"
        ],
        "required_query_concepts": [
          "artificial-intelligence",
          "catalyst-design"
        ],
        "authoritative_scope": {
          "kind": "authoritative_parent_source_scope",
          "record_id": "362061",
          "label": "CPS — Catalysis, Process Design, and AI/ML Optimization",
          "source_url": "https://www.nsf.gov"
        },
        "controlled_relationships": [
          "CPS explicitly combines catalysis, process design and optimization, artificial intelligence, and machine learning within one published program scope"
        ]
      },
      {
        "id": "genesis-ai-catalyst-design",
        "parent_id": "361526",
        "supported_query_concepts": [
          "artificial-intelligence",
          "catalyst-design"
        ],
        "required_query_concepts": [
          "artificial-intelligence",
          "catalyst-design"
        ],
        "authoritative_scope": {
          "kind": "publication_eligible_child_scope",
          "record_id": "361526:g-12",
          "label": "Genesis — Electrochemical Energy Conversion Catalyst Discovery and Scale up",
          "source_url": "https://grants.gov/grantsws/rest/opportunity/att/download/350588"
        },
        "controlled_relationships": [
          "Genesis is explicitly AI-centered and its publication-eligible catalyst-discovery child establishes the bounded scientific target and operation"
        ]
      },
      {
        "id": "pesose-secure-open-source-foundation-models",
        "parent_id": "361333",
        "supported_query_concepts": [
          "security-resilience",
          "foundation-models"
        ],
        "required_query_concepts": [
          "security-resilience",
          "foundation-models"
        ],
        "authoritative_scope": {
          "kind": "authoritative_parent_source_scope",
          "record_id": "361333",
          "label": "PESOSE — Secure Open-Source Machine-Learning Model Ecosystems",
          "source_url": "https://www.nsf.gov/funding/opportunities/pesose-pathways-enable-secure-open-source-ecosystems"
        },
        "controlled_relationships": [
          "PESOSE explicitly funds safety and security for open-source machine-learning model ecosystems",
          "foundation models are a bounded subclass of the funded open-source machine-learning model scope; this direction is not reversed"
        ]
      },
      {
        "id": "pesose-dcl-secure-foundation-models",
        "parent_id": "vpr-email:NSF26-015",
        "supported_query_concepts": [
          "security-resilience",
          "foundation-models"
        ],
        "required_query_concepts": [
          "security-resilience",
          "foundation-models"
        ],
        "authoritative_scope": {
          "kind": "authoritative_parent_source_scope",
          "record_id": "vpr-email:NSF26-015",
          "label": "NSF 26-015 — AI Agent Ecosystems through PESOSE",
          "source_url": "https://www.nsf.gov/funding/opportunities/pesose-pathways-enable-secure-open-source-ecosystems"
        },
        "controlled_relationships": [
          "the DCL explicitly routes AI-agent ecosystem proposals through PESOSE's secure open-source model scope",
          "the relationship is bounded to secure open-source AI model ecosystems"
        ]
      },
      {
        "id": "geospace-earth-system-chemical-processes",
        "parent_id": "356536",
        "supported_query_concepts": [
          "earth-system",
          "chemical-processes"
        ],
        "required_query_concepts": [
          "earth-system",
          "chemical-processes"
        ],
        "authoritative_scope": {
          "kind": "parent_program_scope",
          "record_id": "356536",
          "label": "Geospace — Coupled Sun–Earth Chemical Processes",
          "source_url": "https://www.nsf.gov"
        },
        "controlled_relationships": [
          "Geospace explicitly funds chemical processes in the coupled Sun-Earth system",
          "administrative program-element wording does not establish chemical-process scope"
        ]
      },
      {
        "id": "dwpr-pfas-membrane-treatment",
        "parent_id": "363375",
        "supported_query_concepts": [
          "pfas-contamination",
          "membrane-treatment"
        ],
        "required_query_concepts": [
          "pfas-contamination"
        ],
        "authoritative_scope": {
          "kind": "parent_program_scope",
          "record_id": "363375",
          "label": "DWPR — PFAS-Contaminated Water Membrane Treatment Research",
          "source_url": "https://www.usbr.gov/research/dwpr"
        },
        "controlled_relationships": [
          "the adjudicated DWPR source scope covers PFAS-contaminated water treatment",
          "membrane treatment is contained in the program's laboratory and pilot-scale purification scope"
        ]
      },
      {
        "id": "cps-pfas-membrane-treatment",
        "parent_id": "362061",
        "supported_query_concepts": [
          "pfas-contamination",
          "membrane-treatment"
        ],
        "required_query_concepts": [
          "pfas-contamination"
        ],
        "authoritative_scope": {
          "kind": "parent_program_scope",
          "record_id": "362061",
          "label": "Chemical Process Systems — PFAS Chemical Processes and Membrane Separations",
          "source_url": "https://www.nsf.gov/funding/pgm_summ.jsp?pims_id=506547"
        },
        "controlled_relationships": [
          "the adjudicated CPS scope covers PFAS chemical-process research",
          "membrane treatment is a specialization of the program's separation-process scope"
        ]
      },
      {
        "id": "gregori-technology-rare-disease-molecular",
        "parent_id": "359280",
        "supported_query_concepts": [
          "rare-disease-molecular-genomics"
        ],
        "required_query_concepts": [
          "rare-disease-molecular-genomics"
        ],
        "authoritative_scope": {
          "kind": "parent_program_scope",
          "record_id": "359280",
          "label": "GREGoRi Technology Integration — Molecular Methods for Rare-Disease Diagnosis",
          "source_url": "https://grants.nih.gov"
        },
        "controlled_relationships": [
          "molecular technologies and genomic causal-gene methods satisfy the bounded rare-disease molecular intent"
        ]
      },
      {
        "id": "gregori-innovation-rare-disease-molecular",
        "parent_id": "359644",
        "supported_query_concepts": [
          "rare-disease-molecular-genomics"
        ],
        "required_query_concepts": [
          "rare-disease-molecular-genomics"
        ],
        "authoritative_scope": {
          "kind": "parent_program_scope",
          "record_id": "359644",
          "label": "GREGoRi Innovation — Molecular and Computational Rare-Disease Diagnosis",
          "source_url": "https://grants.nih.gov"
        },
        "controlled_relationships": [
          "innovative experimental and computational molecular/genomic diagnosis satisfies the bounded rare-disease intent"
        ]
      },
      {
        "id": "sstem-education-innovation-student-success",
        "parent_id": "357498",
        "supported_query_concepts": [
          "education-innovation",
          "student-success"
        ],
        "required_query_concepts": [
          "education-innovation",
          "student-success"
        ],
        "authoritative_scope": {
          "kind": "parent_program_scope",
          "record_id": "357498",
          "label": "S-STEM — Evidence-Based Innovation for Student Success",
          "source_url": "https://www.nsf.gov"
        },
        "controlled_relationships": [
          "innovation catalyst is interpreted non-chemically in explicit student-success context"
        ]
      },
      {
        "id": "lsamp-education-innovation-student-success",
        "parent_id": "359104",
        "supported_query_concepts": [
          "education-innovation",
          "student-success"
        ],
        "required_query_concepts": [
          "education-innovation",
          "student-success"
        ],
        "authoritative_scope": {
          "kind": "parent_program_scope",
          "record_id": "359104",
          "label": "LSAMP — Innovative Strategies for STEM Student Success",
          "source_url": "https://www.nsf.gov"
        },
        "controlled_relationships": [
          "innovative sustained strategies and explicit student-success outcomes satisfy the complete education intent"
        ]
      },
      {
        "id": "mathers-single-cell-cancer-immunology",
        "parent_id": "vpr-email:infoready-2028504",
        "supported_query_concepts": [
          "single-cell-biology",
          "cancer-immunology"
        ],
        "required_query_concepts": [
          "single-cell-biology",
          "cancer-immunology"
        ],
        "authoritative_scope": {
          "kind": "parent_program_scope",
          "record_id": "vpr-email:infoready-2028504",
          "label": "Mathers Foundation — Cellular Physiology, Cancer Biology, and Immunology",
          "source_url": "https://www.mathersfoundation.org"
        },
        "controlled_relationships": [
          "single-cell research is contained within explicit cellular-physiology scope",
          "cancer biology and immunology are both explicit"
        ]
      },
      {
        "id": "arl-electrocatalytic-ammonia",
        "parent_id": "344592",
        "supported_query_concepts": [
          "electrocatalysis",
          "ammonia-synthesis"
        ],
        "required_query_concepts": [
          "electrocatalysis",
          "ammonia-synthesis"
        ],
        "authoritative_scope": {
          "kind": "publication_eligible_child",
          "record_id": "344592:ab-0025",
          "label": "ARL Electrochemistry — Redox Reactions and Electrocatalysis",
          "source_url": "https://www.arl.army.mil"
        },
        "controlled_relationships": [
          "electrocatalytic ammonia synthesis is a bounded electrochemical redox and catalysis specialization"
        ]
      },
      {
        "id": "arl-hypersonic-high-temperature-composites",
        "parent_id": "344592",
        "supported_query_concepts": [
          "high-temperature-materials",
          "hypersonic-environment"
        ],
        "required_query_concepts": [
          "high-temperature-materials",
          "hypersonic-environment"
        ],
        "authoritative_scope": {
          "kind": "publication_eligible_child",
          "record_id": "344592:ab-0081",
          "label": "ARL Super-Materials — High-Temperature Dynamic Extreme Environments",
          "source_url": "https://www.arl.army.mil"
        },
        "controlled_relationships": [
          "hypersonic materials operation is contained in high-temperature highly dynamic extreme-environment scope"
        ]
      }
    ],
    "broader_program_fits": [
      {
        "id": "gregori-coordination-broader-molecular-rare-disease-fit",
        "parent_id": "359279",
        "supported_query_concepts": [
          "rare-disease-molecular-genomics"
        ],
        "required_query_concepts": [
          "rare-disease-molecular-genomics"
        ],
        "published_scope": {
          "kind": "authoritative_parent_source_scope",
          "record_id": "359279",
          "label": "GREGoRi Coordination and Data Center",
          "source_url": "https://grants.nih.gov"
        },
        "rationale": "The center supports the rare-disease genomics program but funds coordination and data infrastructure rather than the molecular research itself."
      }
    ],
    "scope_entailment_score": 1,
    "scope_entailment_requires_complete_scientific_query": true,
    "evidence_tiers": {
      "A": "exact identifier or publication-eligible child with complete explicit intent",
      "B": "complete authoritative child or program-scope entailment",
      "C": "complete contextual parent title or description evidence",
      "D": "explicitly designated broader-program fit",
      "E": "partial or weak discovery evidence; never primary"
    },
    "primary_admission": {
      "concise_query_minimum_groups": 2,
      "concise_query_maximum_groups": 5,
      "require_complete_substantive_intent": true,
      "citation_source_may_independently_admit": false,
      "generic_topic_or_agency_may_independently_admit": false
    }
  });
})();
