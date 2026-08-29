(function (global) {
  "use strict";

  // This is the small, roster-independent configuration used for researchers
  // entered manually or resolved through ORCID. Keep it eager so those paths do
  // not depend on the lazy Hajim faculty-match graph.
  global.FUNDING_TEAM_MATCH_CONFIG = Object.freeze({
    schema_version: 1,
    theme_lexicon: {
      "Catalysis and reaction engineering": [
        "catalyst", "catalytic", "catalysis", "electrocataly", "photocataly",
        "reaction engineering", "reaction kinetics", "water-gas shift",
        "hydrogenation", "dehydrogenation", "reforming"
      ],
      "Energy": [
        "energy conversion", "energy storage", "fuel cell", "biofuel", "battery",
        "electrochem", "solar fuel", "photovolta", "combustion", "hydrogen production",
        "electrolyzer", "renewable energy", "clean energy", "energy efficiency"
      ],
      "Carbon management": [
        "carbon dioxide", "carbon capture", "carbon utilization", "decarboniz",
        "sequestrat", "direct air capture", "syngas", "co2 reduction", "co2 conversion",
        "negative emissions", "carbon-neutral"
      ],
      "Materials science": [
        "advanced materials", "polymer", "nanomaterial", "thin film", "crystalline",
        "metal-organic framework", "composite", "coating", "graphene", "2d material",
        "semiconductor", "nanoparticle", "self-assembl", "soft matter", "functional materials"
      ],
      "Separations and membranes": [
        "membrane", "gas separation", "adsorb", "adsorption", "sorbent", "filtration",
        "distillation", "chromatograph", "ion exchange", "desalinat", "solvent extraction"
      ],
      "Manufacturing": [
        "advanced manufactur", "additive manufactur", "3d printing", "fabrication",
        "roll-to-roll", "process intensification", "scale-up", "smart manufactur",
        "biomanufactur", "process control"
      ],
      "Artificial intelligence and machine learning": [
        "machine learning", "deep learning", "neural network", "artificial intelligence",
        "data-driven", "autonomous experiment", "digital twin", "surrogate model",
        "high-throughput screening"
      ],
      "Quantum science": [
        "quantum computing", "quantum material", "quantum sensing", "quantum information",
        "quantum chemistry"
      ],
      "Biology and biotechnology": [
        "biotechnology", "microbial", "synthetic biology", "enzyme", "bioreactor",
        "metabolic engineering", "fermentation", "biocataly", "biopolymer", "biomaterial",
        "bioprocess", "cell culture", "protein engineering", "genome"
      ],
      "Environmental science": [
        "environmental remediation", "pollution", "emissions", "bioremediation",
        "air quality", "contaminant", "ecosystem", "circular economy", "recycling", "upcycling"
      ],
      "Water": [
        "water treatment", "wastewater", "drinking water", "desalinat", "water purification",
        "water resources", "water quality"
      ],
      "Public health": [
        "clinical trial", "drug delivery", "therapeutic", "pharmaceutical", "vaccine",
        "diagnostic", "medical countermeasure"
      ],
      "Infectious disease": [
        "antibiotic", "antimicrobial", "pathogen", "infection", "antifungal", "antiviral",
        "biosurveillance"
      ],
      "Climate change": [
        "climate change", "greenhouse gas", "global warming", "climate resilience"
      ],
      "Space and aeronautics": [
        "aerospace", "spacecraft", "aeronautic", "propulsion", "in situ resource", "lunar",
        "planetary"
      ]
    },
    bridge_themes: [
      {
        label: "CO₂ conversion and utilization",
        domains: ["Catalysis and reaction engineering", "Carbon management"],
        terms: ["co2 utilization", "co2 conversion", "co2 reduction", "carbon utilization", "e-fuels", "fuels from co2", "co2 hydrogenation"]
      },
      {
        label: "Data-driven catalyst discovery",
        domains: ["Artificial intelligence and machine learning", "Catalysis and reaction engineering"],
        terms: ["catalyst discovery", "catalyst screening", "machine learning", "high-throughput", "autonomous"]
      },
      {
        label: "AI for materials discovery",
        domains: ["Artificial intelligence and machine learning", "Materials science"],
        terms: ["materials discovery", "materials genome", "autonomous experiment", "materials acceleration", "inverse design"]
      },
      {
        label: "Carbon capture materials",
        domains: ["Separations and membranes", "Carbon management"],
        terms: ["carbon capture", "direct air capture", "co2 separation", "capture sorbent", "point-source capture"]
      },
      {
        label: "Electrochemical energy conversion",
        domains: ["Energy", "Catalysis and reaction engineering"],
        terms: ["electrolysis", "electrolyzer", "fuel cell", "electrocataly", "hydrogen production"]
      },
      {
        label: "Energy storage materials",
        domains: ["Energy", "Materials science"],
        terms: ["battery", "energy storage", "solid-state electrolyte", "electrode material"]
      },
      {
        label: "Biomaterials and biomanufacturing",
        domains: ["Biology and biotechnology", "Materials science"],
        terms: ["biomaterial", "biomanufactur", "biopolymer", "bioprocess", "tissue engineering", "bioink"]
      },
      {
        label: "Sustainable polymers and plastics upcycling",
        domains: ["Materials science", "Environmental science"],
        terms: ["plastic", "upcycling", "recycling", "circular economy", "biodegradable", "depolymerization"]
      },
      {
        label: "Smart and digital manufacturing",
        domains: ["Manufacturing", "Artificial intelligence and machine learning"],
        terms: ["digital twin", "smart manufacturing", "process optimization", "advanced manufacturing", "cyber-physical"]
      },
      {
        label: "Environmental biotechnology",
        domains: ["Biology and biotechnology", "Environmental science"],
        terms: ["bioremediation", "wastewater", "antimicrobial resistance", "microbiome", "environmental microbial"]
      },
      {
        label: "Water treatment and separations",
        domains: ["Separations and membranes", "Environmental science"],
        terms: ["water treatment", "desalination", "pfas", "contaminant removal", "water reuse"]
      }
    ],
    agency_scope: [
      {
        label: "Office of Naval Research / Navy labs",
        pattern: "office of naval research|naval research lab|nswc|navsea|\\bonr\\b",
        domains: ["Materials science", "Energy", "Manufacturing", "Artificial intelligence and machine learning"]
      },
      {
        label: "Army research (ARL / ARO / DEVCOM / ERDC)",
        pattern: "army research (?:laboratory|office)|devcom|army combat capabilities|acc apg|engineer research and development|\\berdc\\b|\\baro\\b|\\barl\\b",
        domains: ["Materials science", "Energy", "Manufacturing", "Artificial intelligence and machine learning", "Environmental science"]
      },
      {
        label: "Air Force research (AFOSR / AFRL)",
        pattern: "air force (?:office of scientific research|research laboratory)|afosr|afrl",
        domains: ["Materials science", "Energy", "Manufacturing", "Artificial intelligence and machine learning", "Space and aeronautics"]
      },
      {
        label: "DARPA",
        pattern: "\\bdarpa\\b|defense advanced research",
        domains: ["Materials science", "Manufacturing", "Energy", "Artificial intelligence and machine learning", "Biology and biotechnology"]
      },
      {
        label: "DOE Office of Science / ARPA-E",
        pattern: "office of science|arpa-e|advanced research projects agency - energy|national energy technology|golden field office",
        domains: ["Energy", "Materials science", "Catalysis and reaction engineering", "Carbon management", "Artificial intelligence and machine learning", "Quantum science", "Biology and biotechnology", "Separations and membranes"]
      },
      {
        label: "NASA",
        pattern: "\\bnasa\\b",
        domains: ["Space and aeronautics", "Materials science", "Energy", "Manufacturing", "Artificial intelligence and machine learning"]
      }
    ],
    broad_pattern: "broad agency announcement|\\bbaa\\b|continuation of solicitation|office of science financial assistance|long[\\s-]?range|research announcement|\\broses\\b|omnibus|unsolicited proposal|open topic|financial assistance program"
  });
})(globalThis);
