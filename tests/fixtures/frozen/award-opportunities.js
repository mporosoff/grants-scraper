// Frozen cross-product examples for Funded Awards browser tests. Funding
// Finder enforces the production catalog's minimum-size invariant, so stable
// filler records keep this fixture on the same startup path without borrowing
// mutable production opportunities.
(() => {
  const mappedOpportunities = [
    {
      opportunity_id: "361187",
      opportunity_number: "PAR-26-114",
      title: "Lasker Clinical Research Scholar's Program (Si2/R00 Clinical Trial Optional)",
      agency_code: "HHS-NIH11",
      agency: "National Institutes of Health",
      status: "posted",
      close_date: "2099-08-28",
      archive_date: "2099-09-28",
      description: "Frozen NIH exact-opportunity mapping example.",
      topic_areas: ["Clinical research"],
      disciplines: ["Medical and Health"],
    },
    {
      opportunity_id: "361526",
      opportunity_number: "DE-FOA-0003612",
      title: "The Genesis Mission",
      agency_code: "PAMS-SC",
      agency: "Office of Science",
      status: "posted",
      close_date: "2099-12-31",
      archive_date: "2100-01-31",
      description: "Frozen DOE Office of Science exact-FOA mapping example.",
      topic_areas: ["Energy"],
      disciplines: ["Engineering and Physical Sciences"],
    },
    {
      opportunity_id: "363616",
      opportunity_number: "26-518",
      title: "Engineering (ENG): Chemical, Bioengineering, Energy, and Transport Systems (CBET)",
      agency_code: "NSF",
      agency: "U.S. National Science Foundation",
      status: "posted",
      close_date: "2099-12-31",
      archive_date: "2100-01-31",
      description: "Frozen NSF reviewed program-group mapping example.",
      topic_areas: ["Catalysis and reaction engineering", "Separations and membranes"],
      disciplines: ["Engineering and Physical Sciences"],
    },
  ];
  const fillerOpportunities = Array.from({ length: 997 }, (_value, index) => ({
    opportunity_id: `fixture-award-padding-${String(index + 1).padStart(4, "0")}`,
    opportunity_number: `FIXTURE-${String(index + 1).padStart(4, "0")}`,
    title: `Frozen catalog padding record ${index + 1}`,
    agency_code: "TEST",
    agency: "Frozen fixture agency",
    status: "posted",
    close_date: "2099-12-31",
    archive_date: "2100-01-31",
    description: "Deterministic padding for Funding Finder catalog validation.",
    topic_areas: [],
    disciplines: [],
  }));
  const opportunities = [...mappedOpportunities, ...fillerOpportunities];
  globalThis.GRANT_CATALOG = {
    schema_version: 3,
    generated_at: "2026-09-01T12:00:00Z",
    record_count: opportunities.length,
    status_counts: { posted: opportunities.length },
    opportunities,
    search_index: {
      algorithm: "bm25",
      document_count: opportunities.length,
      document_lengths: Array(opportunities.length).fill(1),
      average_document_length: 1,
      postings: {},
    },
  };
})();
