// Immutable Funding Finder catalog for deterministic browser tests. The
// production tokenizer builds this fixture's real search index at load time,
// so E2E coverage exercises the current search implementation without
// borrowing opportunities from the daily catalog.
(() => {
  const openOpportunity = (record) => ({
    agency_code: "TEST",
    agency: "Frozen fixture agency",
    status: "posted",
    open_date: "2026-01-01",
    close_date: "2099-12-31",
    archive_date: "2100-01-31",
    applicant_types: ["Public and private institutions of higher education"],
    funding_categories: ["Science and Technology and other Research and Development"],
    funding_instruments: ["Grant"],
    award_floor: 10000,
    award_ceiling: 500000,
    expected_awards: 5,
    url: `https://www.grants.gov/search-results-detail/${record.opportunity_id}`,
    source_type: "Federal",
    source_facet: "Grants.gov",
    ...record,
  });

  const coreOpportunities = [
    openOpportunity({
      opportunity_id: "361187",
      opportunity_number: "PAR-26-114",
      title: "Lasker Clinical Research Scholar's Program (Si2/R00 Clinical Trial Optional)",
      agency_code: "HHS-NIH11",
      agency: "National Institutes of Health",
      description: "Frozen NIH exact-opportunity mapping example for clinical research.",
      topic_areas: ["Clinical research"],
      disciplines: ["Medical and Health"],
    }),
    openOpportunity({
      opportunity_id: "361526",
      opportunity_number: "DE-FOA-0003612",
      title: "The Genesis Mission",
      agency_code: "PAMS-SC",
      agency: "Office of Science",
      description: "Frozen DOE Office of Science exact-FOA mapping example for energy research.",
      topic_areas: ["Energy"],
      disciplines: ["Engineering and Physical Sciences"],
    }),
    openOpportunity({
      opportunity_id: "363616",
      opportunity_number: "26-518",
      title: "Engineering (ENG): Chemical, Bioengineering, Energy, and Transport Systems (CBET)",
      agency_code: "NSF",
      agency: "U.S. National Science Foundation",
      description: "Frozen NSF program-group example covering catalysis science and membrane separation research.",
      topic_areas: ["Catalysis and reaction engineering", "Separations and membranes"],
      disciplines: ["Engineering and Physical Sciences"],
    }),
    openOpportunity({
      opportunity_id: "fixture-hydrogen-catalysis",
      opportunity_number: "TEST-HYDROGEN",
      title: "Hydrogen Catalysis Science Initiative",
      description: "Fundamental hydrogen catalysis science, catalytic reaction engineering, and carbon conversion research.",
      topic_areas: ["Catalysis and reaction engineering", "Hydrogen"],
      disciplines: ["Engineering and Physical Sciences"],
    }),
    openOpportunity({
      opportunity_id: "fixture-catalytic-materials",
      opportunity_number: "TEST-CATALYTIC-MATERIALS",
      title: "Catalytic Materials Research",
      description: "Scientific research on catalytic materials, surface chemistry, and reaction pathways.",
      topic_areas: ["Catalysis and reaction engineering", "Materials science"],
      disciplines: ["Engineering and Physical Sciences"],
    }),
    openOpportunity({
      opportunity_id: "fixture-carbon-capture",
      opportunity_number: "TEST-CARBON-CAPTURE",
      title: "Carbon Capture and Conversion Science",
      description: "Carbon dioxide capture, catalytic conversion, separations, and process science research.",
      topic_areas: ["Carbon capture", "Catalysis and reaction engineering"],
      disciplines: ["Engineering and Physical Sciences"],
    }),
    openOpportunity({
      opportunity_id: "fixture-membrane-separation",
      opportunity_number: "TEST-MEMBRANES",
      title: "Membrane Separation Science",
      description: "Molecular membrane separation science for hydrogen purification and carbon capture.",
      topic_areas: ["Separations and membranes"],
      disciplines: ["Engineering and Physical Sciences"],
    }),
    openOpportunity({
      opportunity_id: "fixture-science-workforce",
      opportunity_number: "TEST-SCIENCE-WORKFORCE",
      title: "Regional Science Workforce Workshop",
      agency: "Frozen public diplomacy agency",
      description: "Training and public engagement for regional science educators and students.",
      topic_areas: ["Education and workforce"],
      disciplines: [],
    }),
    openOpportunity({
      opportunity_id: "fixture-forecasted-catalysis",
      opportunity_number: "TEST-FORECASTED-CATALYSIS",
      title: "Forecasted Catalysis Science Program",
      status: "forecasted",
      description: "A forecasted program for catalysis science and catalytic reaction engineering research.",
      topic_areas: ["Catalysis and reaction engineering"],
      disciplines: ["Engineering and Physical Sciences"],
    }),
    openOpportunity({
      opportunity_id: "fixture-electrochemical-conversion",
      opportunity_number: "TEST-ELECTROCHEMICAL-CONVERSION",
      title: "Electrochemical Carbon Conversion",
      description: "Carbon dioxide utilization, low carbon fuels synthesis, process intensification, and surface reaction kinetics.",
      topic_areas: ["Carbon conversion", "Electrochemistry"],
      disciplines: ["Engineering and Physical Sciences"],
    }),
  ];

  const fillerOpportunities = Array.from(
    { length: 1000 - coreOpportunities.length },
    (_value, index) => ({
      opportunity_id: `fixture-archived-padding-${String(index + 1).padStart(4, "0")}`,
      opportunity_number: "",
      title: "",
      agency_code: "TEST",
      agency: "",
      status: "archived",
      close_date: "2020-01-01",
      archive_date: "2020-02-01",
      description: "",
      topic_areas: [],
      disciplines: [],
    }),
  );
  const opportunities = [...coreOpportunities, ...fillerOpportunities];
  const tokenize = globalThis.FUNDING_SEARCH_QUERY?.tokenize || (value => (
    String(value || "").toLowerCase().match(/[a-z0-9][a-z0-9+.-]*/g) || []
  ));

  const postings = new Map();
  const documentLengths = opportunities.map((record, documentId) => {
    const weightedTerms = new Map();
    [
      [record.title, 7],
      [record.opportunity_number, 7],
      [record.agency, 3],
      [(record.topic_areas || []).join(" "), 5],
      [(record.disciplines || []).join(" "), 4],
      [(record.funding_categories || []).join(" "), 3],
      [(record.funding_instruments || []).join(" "), 2],
      [(record.applicant_types || []).join(" "), 1],
      [record.eligibility_text, 1],
      [record.description, 1],
      [record.document_search_text, 1],
    ].forEach(([value, weight]) => {
      const counts = new Map();
      tokenize(value || "").forEach(term => (
        counts.set(term, (counts.get(term) || 0) + 1)
      ));
      counts.forEach((count, term) => (
        weightedTerms.set(term, (weightedTerms.get(term) || 0) + count * weight)
      ));
    });
    weightedTerms.forEach((frequency, term) => {
      if (!postings.has(term)) postings.set(term, []);
      postings.get(term).push(documentId, frequency);
    });
    return [...weightedTerms.values()].reduce((sum, value) => sum + value, 0) || 1;
  });
  const maximumDocumentFrequency = Math.max(1, Math.floor(opportunities.length * .8));
  const compactPostings = Object.fromEntries([...postings]
    .filter(([_term, values]) => values.length / 2 <= maximumDocumentFrequency)
    .sort(([left], [right]) => left.localeCompare(right)));
  const statusCounts = opportunities.reduce((counts, record) => {
    counts[record.status] = (counts[record.status] || 0) + 1;
    return counts;
  }, {});
  const facetDefinitions = {
    source: ["source_facet", "source"],
    source_type: ["source_type"],
    discipline: ["disciplines"],
    topic: ["topic_areas"],
    agency: ["agency"],
    eligibility: ["applicant_types"],
    funding_instrument: ["funding_instruments"],
  };
  const facets = Object.fromEntries(Object.keys(facetDefinitions).map(name => [name, {}]));
  opportunities.forEach(record => Object.entries(facetDefinitions).forEach(([name, fields]) => {
    const raw = fields.map(field => record[field]).find(value => value != null);
    const values = Array.isArray(raw) ? raw : [raw];
    [...new Set(values.filter(Boolean))].forEach(value => {
      facets[name][value] = (facets[name][value] || 0) + 1;
    });
  }));

  globalThis.GRANT_CATALOG = {
    schema_version: 3,
    generated_at: "2026-09-01T12:00:00Z",
    record_count: opportunities.length,
    status_counts: statusCounts,
    facets,
    opportunities,
    search_index: {
      algorithm: "bm25",
      document_count: opportunities.length,
      document_lengths: documentLengths,
      average_document_length: documentLengths.reduce((sum, value) => sum + value, 0) / opportunities.length,
      postings: compactPostings,
    },
  };
})();
