// Synthetic browser-contract data. Never imported by a catalog or team writer.
import { createHash } from "node:crypto";

export function opportunityTeamFixture() {
  const researchers = ["alpha", "beta", "gamma", "delta", "alternative"].map(name => ({
    id: `fixture-${name}`, name: `Fixture ${name}`, home_unit: "Fixture unit",
    status: "active", auto_proposable: true, pool_state: "main", pool_visibility: "visible",
    source_url: `https://example.org/fixture/${name}`, source_checked_date: "2026-09-01",
    claims: [{ claim_id: `fixture-${name}-claim`, revision: 1, status: "active",
      label: "Fixture scientific method", evidence: `Synthetic evidence for fixture ${name}.`,
      evidence_level: "direct", source_urls: [`https://example.org/fixture/${name}`] }],
  }));
  const ids = researchers.map(person => person.id);
  const counts = { total: ids.length, rankable: ids.length, unrankable: 0,
    pool_counts: { main: ids.length, standby: 0, unadmitted: 0 } };
  const digest = value => createHash("sha256").update(JSON.stringify(value)).digest("hex");
  const directory = { schema_version: 1, registry_generation: digest(researchers), researchers, counts };
  function scope(id, parentId, type) {
    return { id, parent_id: parentId, record_type: type, scope_label: id, gate_state: "pass",
      objective: "A synthetic research objective for browser contracts.",
      why_team: "Each fixture researcher contributes a distinct scientific role.", missing_skills: [],
      members: ids.slice(0, 4).map((faculty_id, i) => ({ faculty_id, contribution: `Fixture role ${i + 1}` })),
      roles: ids.slice(0, 4).map((person, i) => ({ id: `role-${i + 1}`, label: `Fixture role ${i + 1}`,
        required: true, coverage: "direct", candidate_ids: [person], alternative_ids: [ids[4]],
        accepted_terms: ["Fixture scientific method"] })),
    };
  }
  const specific = scope("fixture-specific", "fixture-specific", "specific_parent");
  const mixed = scope("fixture-broad:mixed", "fixture-broad", "publishable_child");
  // Both variants fill two roles. Only the alternative has direct first-role
  // evidence; the second role remains an explicitly supported method transfer.
  mixed.members = [ids[0], ids[1]].map(faculty_id => ({ faculty_id, contribution: "Fixture contribution" }));
  mixed.variants = [{ member_ids: [ids[4], ids[1]] }];
  mixed.assembly_version = "complementary-roles-1";
  mixed.roles = [
    { id: "role-1", label: "Fixture wavelength conversion", required: true, coverage: "direct",
      candidate_ids: [ids[0], ids[4]], alternative_ids: [], accepted_terms: [],
      claim_refs: [
        { researcher_id: ids[0], claim_id: researchers[0].claims[0].claim_id, revision: 1, coverage: "method_transfer" },
        { researcher_id: ids[4], claim_id: researchers[4].claims[0].claim_id, revision: 1, coverage: "direct" },
      ] },
    { id: "role-2", label: "Fixture measurement", required: true, coverage: "method_transfer",
      candidate_ids: [ids[1]], alternative_ids: [], accepted_terms: [],
      claim_refs: [{ researcher_id: ids[1], claim_id: researchers[1].claims[0].claim_id, revision: 1, coverage: "method_transfer" }] },
  ];
  const opportunities = [specific, mixed,
    scope("fixture-broad:first", "fixture-broad", "publishable_child"),
    scope("fixture-broad:second", "fixture-broad", "publishable_child"),
    scope("fixture-child-parent:topic", "fixture-child-parent", "publishable_child"),
    scope("fixture-branch-parent:branch", "fixture-branch-parent", "declared_branch"),
  ];
  const generation = digest([directory.registry_generation, opportunities]);
  const data = { schema_version: 1, generation_id: generation,
    researcher_registry_generation: directory.registry_generation,
    source_roster_counts: { total: counts.total, rankable: counts.rankable, unrankable: counts.unrankable },
    pool_counts: counts.pool_counts, scope_count: opportunities.length, opportunities, faculty: [] };
  const index = { schema_version: 1, generation_id: generation, scope_count: opportunities.length,
    scopes: opportunities.map(({ id, parent_id, record_type }) => ({ id, parent_id, record_type })) };
  return { data, index, directory };
}
