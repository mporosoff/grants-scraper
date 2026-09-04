import { PRODUCTION_PROMPTS } from "../assets/ai-prompts.mjs";

export { PRODUCTION_PROMPTS };

export const BENCHMARK_VERSION = "ai-model-benchmark-v2";

export const MODEL_CONFIG = Object.freeze({
  luna: Object.freeze({
    id: "gpt-5.6-luna",
    input_usd_per_million_tokens: 0.20,
    output_usd_per_million_tokens: 1.20,
  }),
  gemma: Object.freeze({
    id: "@cf/google/gemma-4-26b-a4b-it",
    input_usd_per_million_tokens: 0.10,
    output_usd_per_million_tokens: 0.30,
  }),
});

const promptVersion = "result-aware-chat-v2";

export const BENCHMARK_CASES = Object.freeze([
  Object.freeze({
    id: "enhance-phrase-expansion",
    feature: "Enhance with AI",
    operation: "search_plan",
    title: "Expand a specific catalysis project without generic retrieval terms",
    system: PRODUCTION_PROMPTS.search_plan,
    user: JSON.stringify({
      task: "Create independent alternative phrases for local retrieval from the current funding-opportunity catalog.",
      researcher_profile: {
        research_description: "I study electrochemical carbon dioxide conversion with single-atom catalysts to produce value-added chemicals.",
        expertise_keywords: "chemical engineering; catalysis; operando spectroscopy; density functional theory",
        applicant_context: "Faculty investigator at a public research university",
        career_stage: "Tenured faculty",
      },
      current_keyword_search: "electrochemical CO2 conversion catalysts",
      active_filters: { agency: ["DOE", "NSF"], status: ["open"] },
      prompt_version: promptVersion,
    }),
    estimated_output_tokens: 300,
    checks: {
      minimum_search_terms: 5,
      forbidden_exact_search_terms: ["research", "science", "technology", "health", "innovation", "energy"],
    },
  }),
  Object.freeze({
    id: "enhance-candidate-assessment",
    feature: "Enhance with AI",
    operation: "refinement_shortlist",
    title: "Keep eligibility constraints ahead of topical similarity",
    system: PRODUCTION_PROMPTS.refinement_shortlist,
    user: JSON.stringify({
      task: "Assess which locally qualified new opportunities are most worth adding to the ordinary results.",
      researcher_profile: {
        research_description: "I study electrochemical carbon dioxide conversion and heterogeneous catalysis.",
        expertise_keywords: "electrocatalysis; carbon management; reaction mechanisms",
        applicant_context: "Faculty investigator at a public research university",
        career_stage: "Tenured faculty",
      },
      search_interpretation: "Catalytic and electrochemical routes for carbon management.",
      avoid_concepts: ["student-only fellowships"],
      candidate_opportunities: [
        {
          id: "DOE-CATALYSIS-01",
          title: "Catalysis Science for Carbon Conversion",
          workflow_tier: "strong",
          eligibility: ["U.S. institutions of higher education"],
          eligibility_note: "U.S. institutions of higher education may apply.",
          deadline: "2027-02-12",
          description: "Supports fundamental catalysis and mechanistic studies for carbon conversion.",
        },
        {
          id: "GRAD-FELLOWSHIP-02",
          title: "Graduate Student Energy Fellowship",
          workflow_tier: "strong",
          eligibility: ["Graduate students"],
          eligibility_note: "Only currently enrolled graduate students may apply as individuals.",
          deadline: "2027-01-10",
          description: "Includes electrochemical carbon dioxide conversion research.",
        },
        {
          id: "NSF-ELECTROCHEM-03",
          title: "Electrochemical Systems",
          workflow_tier: "strong",
          eligibility: ["Institutions of higher education"],
          eligibility_note: "Institutions of higher education may submit proposals.",
          deadline: "not listed",
          description: "Fundamental electrochemical reaction and transport science.",
        },
      ],
      prompt_version: promptVersion,
    }),
    estimated_output_tokens: 650,
    checks: {
      allowed_result_ids: ["DOE-CATALYSIS-01", "GRAD-FELLOWSHIP-02", "NSF-ELECTROCHEM-03"],
      ineligible_result_ids: ["GRAD-FELLOWSHIP-02"],
    },
  }),
  Object.freeze({
    id: "results-chat-missing-deadline",
    feature: "Chat with results",
    operation: "result_chat",
    title: "Compare supplied deadlines and state when one is not listed",
    system: PRODUCTION_PROMPTS.result_chat,
    user: JSON.stringify({
      researcher_profile: {
        research_description: "I study recovery and reuse of critical materials from lithium-ion batteries.",
        expertise_keywords: "battery recycling; circular materials; resource recovery",
      },
      result_context: "top 2 current search results",
      current_results: [
        {
          id: "DOE-BATT-100",
          title: "Battery Materials and Recycling",
          workflow_tier: "strong",
          deadline: "2027-03-15",
          document_evidence: {
            facts: [{
              evidence_id: "DOE-BATT-100:deadline",
              type: "deadline",
              label: "Application deadline",
              display_value: "March 15, 2027",
              citation: { quote: "Applications are due March 15, 2027." },
            }],
          },
        },
        {
          id: "NSF-BATT-200",
          title: "Sustainable Materials Systems",
          workflow_tier: "potential",
          deadline: "not listed",
          potential_evidence: "Includes circular materials and resource recovery.",
          document_evidence: null,
        },
      ],
      conversation: [{
        role: "user",
        text: "Compare the deadlines and keep only opportunities with a confirmed deadline.",
      }],
      latest_question: "Compare the deadlines and keep only opportunities with a confirmed deadline.",
      prompt_version: promptVersion,
    }),
    estimated_output_tokens: 350,
    checks: {
      allowed_result_ids: ["DOE-BATT-100", "NSF-BATT-200"],
      allowed_evidence_ids: ["DOE-BATT-100:deadline"],
      required_text: ["not listed"],
      expected_result_action: "focus",
      expected_focus_ids: ["DOE-BATT-100"],
    },
  }),
  Object.freeze({
    id: "nofo-chat-conflicting-deadline",
    feature: "Chat with NOFO",
    operation: "notice_chat",
    title: "Prefer the uploaded notice over stale catalog metadata",
    system: PRODUCTION_PROMPTS.notice_chat,
    user: JSON.stringify({
      task: "Answer the latest question about the uploaded funding notice.",
      uploaded_notice: {
        file_name: "sample-nofo.pdf",
        page_count: 4,
        pages_read: 4,
        text_truncated: false,
        document_text: "[Page 1]\nProgram overview.\n[Page 2]\nApplications must be submitted by 5:00 p.m. Eastern Time on April 18, 2027.\n[Page 3]\nEligible applicants are accredited U.S. institutions of higher education. Cost sharing is not required.\n[Page 4]\nReview criteria include scientific merit and feasibility.",
      },
      matched_catalog_record: {
        id: "SAMPLE-001",
        title: "Sample Funding Notice",
        deadline: "2027-04-01",
        source: "catalog snapshot",
      },
      conversation: [{
        role: "user",
        text: "What is the deadline, who is eligible, and is cost sharing required?",
      }],
      latest_question: "What is the deadline, who is eligible, and is cost sharing required?",
      prompt_version: "uploaded-nofo-chat-v1",
    }),
    estimated_output_tokens: 350,
    checks: {
      required_text: ["April 18, 2027", "not required", "institutions of higher education"],
      required_any_text: ["conflict", "different close date"],
      forbidden_text: ["April 1, 2027 is the deadline"],
      required_page_references: [2, 3],
    },
  }),
  Object.freeze({
    id: "institution-translate-bes-count",
    feature: "Ask about this institution",
    operation: "institution_question_translation",
    title: "Translate a deterministic DOE BES count question",
    system: PRODUCTION_PROMPTS.institution_question_translation,
    user: JSON.stringify({
      institution: "Example State University",
      current_filters: {
        agency: "all",
        program: "",
        topic: "",
        pi: "",
        program_officer: "",
        year_start: "",
        year_end: "",
      },
      question: "How many DOE Basic Energy Sciences awards did Example State University receive from 2021 through 2025?",
    }),
    estimated_output_tokens: 180,
    checks: {
      expected_fields: {
        agency: "DOE",
        program: "BES",
        year_start: "2021",
        year_end: "2025",
        answer_intent: "count",
        narrative_needed: false,
      },
    },
  }),
  Object.freeze({
    id: "program-officer-plan-topic-investigators",
    feature: "Ask about a Program Officer snapshot",
    operation: "program_officer_question_plan",
    title: "Preserve investigator intent while bounding a quantum-sensing topic",
    system: PRODUCTION_PROMPTS.program_officer_question_plan,
    user: JSON.stringify({
      question: "Which investigators work on quantum sensing?",
      locked_scope: {
        source: "NSF",
        exact_source_display_name: "Doe, Jane A.",
        year_preset: "recent5",
        year_start: 2022,
        year_end: 2026,
      },
    }),
    estimated_output_tokens: 180,
    checks: {
      expected_fields: { intent: "investigators" },
      required_text: ["quantum", "sensing"],
      forbidden_text: ["\"intent\":\"topical\"", "\"as\""],
    },
  }),
  Object.freeze({
    id: "program-officer-answer-bounded-evidence",
    feature: "Ask about a Program Officer snapshot",
    operation: "program_officer_evidence_answer",
    title: "Synthesize only the selected Program Officer award evidence",
    system: PRODUCTION_PROMPTS.program_officer_evidence_answer,
    user: JSON.stringify({
      question: "Which investigators work on quantum sensing?",
      locked_scope: {
        source: "NSF",
        exact_source_display_name: "Doe, Jane A.",
        year_preset: "recent5",
        year_start: 2022,
        year_end: 2026,
      },
      deterministic_retrieval_plan: {
        intent: "investigators",
        concepts: ["quantum", "sensing"],
        phrases: ["quantum sensing"],
        exclusions: [],
      },
      public_award_evidence: [{
        evidence_id: "NSF:QS-100",
        snapshot_position: 7,
        source: "NSF",
        award_id: "QS-100",
        title: "Quantum sensing with defect centers",
        program: "Engineering",
        program_office: "Directorate for Engineering",
        year: 2025,
        investigators: ["A. Researcher"],
        institution: "Example State University",
        abstract_excerpt: "Develops defect-center quantum sensors for precision measurements.",
        deterministic_score: 481,
        matched_fields: ["title", "abstract"],
      }],
    }),
    estimated_output_tokens: 260,
    checks: {
      allowed_evidence_ids: ["NSF:QS-100"],
      required_text: ["quantum", "A. Researcher"],
      forbidden_text: ["recommended", "complete portfolio", "leading expert"],
    },
  }),
  Object.freeze({
    id: "institution-narrative-bounded-evidence",
    feature: "Ask about this institution",
    operation: "institution_narrative",
    title: "Synthesize a theme without introducing unsupported awards or people",
    system: PRODUCTION_PROMPTS.institution_narrative,
    user: JSON.stringify({
      question: "What research theme connects these catalysis awards?",
      institution: { canonical_name: "Example State University", id: "https://ror.org/example" },
      visible_filters: {
        agency: "DOE",
        program: "BES",
        topic: "catalysis",
        pi: "",
        program_officer: "",
        year_start: "",
        year_end: "",
      },
      answer_intent: "narrative",
      public_award_evidence: [
        {
          evidence_id: "DOE:AWARD-1",
          source: "DOE",
          award_id: "AWARD-1",
          title: "Operando Studies of Single-Atom Catalysts",
          program: "BES",
          year: "2025",
          investigators: ["A. Researcher"],
          abstract_excerpt: "Studies active sites and reaction mechanisms during carbon dioxide conversion.",
        },
        {
          evidence_id: "DOE:AWARD-2",
          source: "DOE",
          award_id: "AWARD-2",
          title: "Dynamic Interfaces in Electrocatalysis",
          program: "BES",
          year: "2024",
          investigators: ["B. Scientist"],
          abstract_excerpt: "Examines evolving catalyst interfaces under reaction conditions.",
        },
        {
          evidence_id: "DOE:AWARD-3",
          source: "DOE",
          award_id: "AWARD-3",
          title: "Quantum Algorithms for Materials",
          program: "BES",
          year: "2023",
          investigators: ["C. Investigator"],
          abstract_excerpt: "Develops algorithms for electronic structure calculations.",
        },
      ],
      evidence_truncated: false,
    }),
    estimated_output_tokens: 300,
    checks: {
      allowed_evidence_ids: ["DOE:AWARD-1", "DOE:AWARD-2", "DOE:AWARD-3"],
      required_text: ["catal"],
      forbidden_text: ["recommended collaborator", "leading expert", "contact"],
    },
  }),
]);

export function gradeBenchmarkOutput(testCase, output) {
  const checks = testCase.checks || {};
  const problems = [];
  const serialized = JSON.stringify(output).toLowerCase();
  for (const text of checks.required_text || []) {
    if (!serialized.includes(String(text).toLowerCase())) problems.push(`missing_text:${text}`);
  }
  for (const text of checks.forbidden_text || []) {
    if (serialized.includes(String(text).toLowerCase())) problems.push(`forbidden_text:${text}`);
  }
  if (checks.required_any_text && !checks.required_any_text.some(text => serialized.includes(String(text).toLowerCase()))) {
    problems.push(`missing_any_text:${checks.required_any_text.join("|")}`);
  }
  if (checks.minimum_search_terms && (output.search_terms?.length || 0) < checks.minimum_search_terms) {
    problems.push(`too_few_search_terms:${output.search_terms?.length || 0}`);
  }
  const forbiddenSearchTerms = new Set((checks.forbidden_exact_search_terms || []).map(value => value.toLowerCase()));
  for (const term of output.search_terms || []) {
    if (forbiddenSearchTerms.has(String(term).trim().toLowerCase())) problems.push(`generic_search_term:${term}`);
  }
  const allowedResultIds = new Set(checks.allowed_result_ids || []);
  const resultIds = [
    ...(output.matches || []).map(item => item?.id),
    ...(output.referenced_result_ids || []),
    ...(output.focus_result_ids || []),
  ].filter(Boolean);
  for (const id of resultIds) {
    if (allowedResultIds.size && !allowedResultIds.has(id)) problems.push(`unknown_result_id:${id}`);
  }
  for (const id of checks.ineligible_result_ids || []) {
    if ((output.matches || []).some(item => item?.id === id)) problems.push(`ineligible_result_id:${id}`);
  }
  const allowedEvidenceIds = new Set(checks.allowed_evidence_ids || []);
  const evidenceIds = [
    ...(output.citation_evidence_ids || []),
    ...(output.claims || []).flatMap(claim => claim?.evidence_ids || []),
  ];
  for (const id of evidenceIds) {
    if (allowedEvidenceIds.size && !allowedEvidenceIds.has(id)) problems.push(`unknown_evidence_id:${id}`);
  }
  for (const claim of output.claims || []) {
    if (!Array.isArray(claim?.evidence_ids) || !claim.evidence_ids.length) problems.push("uncited_narrative_claim");
  }
  for (const page of checks.required_page_references || []) {
    if (!(output.page_references || []).includes(page)) problems.push(`missing_page_reference:${page}`);
  }
  for (const [field, expected] of Object.entries(checks.expected_fields || {})) {
    if (output[field] !== expected) problems.push(`field_mismatch:${field}:${JSON.stringify(output[field])}`);
  }
  if (checks.expected_result_action && output.result_action !== checks.expected_result_action) {
    problems.push(`result_action_mismatch:${output.result_action}`);
  }
  if (checks.expected_focus_ids) {
    const actual = [...(output.focus_result_ids || [])].sort();
    const expected = [...checks.expected_focus_ids].sort();
    if (JSON.stringify(actual) !== JSON.stringify(expected)) problems.push(`focus_ids_mismatch:${actual.join(",")}`);
  }
  return { passed: problems.length === 0, problems };
}
