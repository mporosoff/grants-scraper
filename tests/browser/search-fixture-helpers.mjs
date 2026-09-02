export function buildCatalog(records, queryApi, { schemaVersion = 3 } = {}) {
  const opportunities = records.map(record => ({
    document_search_text: "",
    funding_categories: [],
    topic_areas: [],
    disciplines: [],
    ...record,
  }));
  const postings = {};
  const documentLengths = [];
  opportunities.forEach((record, documentId) => {
    const values = [
      record.title,
      record.opportunity_number,
      record.agency,
      record.description,
      record.document_search_text,
      ...(record.document_program_areas || []),
      ...(record.program_area_labels || []),
      ...(record.topic_areas || []),
      ...(record.disciplines || []),
      ...(record.funding_categories || []),
    ].filter(Boolean).join(" ");
    const counts = new Map();
    queryApi.tokenize(values).forEach(term => counts.set(term, (counts.get(term) || 0) + 1));
    documentLengths.push([...counts.values()].reduce((sum, value) => sum + value, 0));
    for (const [term, frequency] of counts) {
      if (!postings[term]) postings[term] = [];
      postings[term].push(documentId, frequency);
    }
  });
  return {
    schema_version: schemaVersion,
    opportunities,
    record_count: opportunities.length,
    search_index: {
      algorithm: "bm25",
      postings,
      document_count: opportunities.length,
      document_lengths: documentLengths,
      average_document_length: documentLengths.reduce((sum, value) => sum + value, 0)
        / Math.max(1, opportunities.length),
    },
  };
}

export function buildChildCatalog(records, queryApi, retrievalApi) {
  const indexed = buildCatalog(records, queryApi, { schemaVersion: 1 });
  const recordIds = records.map(record => String(record.subtopic_id));
  const sidecar = {
    schema_version: 1,
    records: Object.fromEntries(records.map(record => [
      String(record.parent_id),
      { subtopics: records.filter(candidate => candidate.parent_id === record.parent_id) },
    ])),
    search_index: {
      ...indexed.search_index,
      record_ids: recordIds,
    },
  };
  return retrievalApi.createChildCatalog(sidecar);
}

export function rollup(retrievalApi, parentCatalog, childCatalog, parentEngine, childEngine, query) {
  const parentDirect = parentEngine.score(query, { evidence: true });
  const childDirect = childEngine.score(query, { evidence: true });
  const rows = retrievalApi.rollupScores({
    parentCatalog,
    childCatalog,
    parentDirect,
    parentProfile: { scores: new Float64Array(parentCatalog.opportunities.length) },
    childDirect,
    childProfile: { scores: new Float64Array(childCatalog.opportunities.length) },
    eligibilityBonuses: new Float64Array(parentCatalog.opportunities.length),
  }).rows;
  rows.sort((left, right) => (
    Number(left.evidenceTier || 99) - Number(right.evidenceTier || 99)
    || right.relevance - left.relevance
    || left.id.localeCompare(right.id)
  ));
  return rows;
}
