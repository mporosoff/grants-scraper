import type { OpportunityInput } from "./opportunities";

const SEARCH_URL = "https://api.grants.gov/v1/api/search2";
const DETAIL_URL = "https://api.grants.gov/v1/api/fetchOpportunity";
const DETAIL_PAGE = "https://www.grants.gov/search-results-detail/";
const ATTACHMENT_URL =
  "https://grants.gov/grantsws/rest/opportunity/att/download/";

type JsonRecord = Record<string, unknown>;

async function postJson(url: string, payload: JsonRecord): Promise<JsonRecord> {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "User-Agent": "URochester-GrantMatcher/0.2",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`Grants.gov request failed (${response.status}).`);
  }

  const data = (await response.json()) as JsonRecord;
  if (data.errorcode !== 0 && data.errorcode !== "0") {
    throw new Error(String(data.msg || "Grants.gov returned an API error."));
  }
  return data;
}

function record(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function records(value: unknown): JsonRecord[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is JsonRecord =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

function text(value: unknown): string {
  return value === null || value === undefined ? "" : String(value).trim();
}

function inferDuration(value: unknown): string {
  const source = text(value);
  const match = source.match(
    /\b(?:project|award|performance|budget)\s+(?:period|duration)[^.\n]{0,80}?\b((?:up to|maximum(?: of)?)?\s*\d+(?:\.\d+)?\s*(?:years?|months?))\b/i,
  );
  return match ? text(match[1]).replace(/\s+/g, " ") : "";
}

function preliminaryStage(value: unknown): string {
  const match = text(value).match(
    /\b(concept\s+paper|pre[\s-]?proposal|letter\s+of\s+intent|LOI)\b/i,
  );
  return match ? text(match[1]) : "";
}

function selectPrimaryAttachment(detail: JsonRecord) {
  const attachments = records(detail.synopsisAttachmentFolders).flatMap(
    (folder) =>
      records(folder.synopsisAttachments).map((attachment) => ({
        ...attachment,
        folderType: folder.folderType,
      })),
  );

  const ranked = attachments
    .filter((attachment) => text(attachment.id))
    .sort((left, right) => {
      const rank = (attachment: JsonRecord) => {
        const blob = `${text(attachment.fileName)} ${text(
          attachment.fileDescription,
        )}`.toLowerCase();
        const isPdf =
          blob.includes(".pdf") ||
          text(attachment.mimeType) === "application/pdf";
        const primary = /\b(nofo|foa|rfa|baa)\b/.test(blob) ||
          blob.includes("full announcement") ||
          blob.includes("solicitation");
        const supplemental =
          /faq|appendix|addendum|sample|template|webinar|questions|special notice|topics/.test(
            blob,
          );
        const amendment = blob.includes("amendment");
        return [!isPdf, !primary, supplemental, amendment, blob];
      };
      const a = rank(left);
      const b = rank(right);
      return a.join("|").localeCompare(b.join("|"));
    });

  const first = ranked[0];
  return first ? `${ATTACHMENT_URL}${text(first.id)}` : "";
}

function normalizeDetail(stub: JsonRecord, detail: JsonRecord): OpportunityInput {
  const synopsis = record(detail.synopsis);
  const forecast = record(detail.forecast);
  const source = Object.keys(synopsis).length ? synopsis : forecast;
  const agencyDetails = record(source.agencyDetails);
  const opportunityId = text(detail.id || stub.id);
  const closeDate =
    source.responseDate ||
    source.estApplicationResponseDate ||
    stub.closeDate;
  const closeNote =
    source.responseDateDesc ||
    source.estApplicationResponseDateDesc ||
    "";
  const description = source.synopsisDesc || source.forecastDesc || "";
  const applicantTypes = records(source.applicantTypes)
    .map((applicant) => text(applicant.description))
    .filter(Boolean)
    .join(", ");
  const preliminaryStageType = preliminaryStage(`${description} ${closeNote}`);
  const primaryAttachment = selectPrimaryAttachment(detail);

  return {
    opportunity_id: opportunityId,
    opportunity_number: detail.opportunityNumber || stub.number,
    title: detail.opportunityTitle || stub.title,
    agency:
      agencyDetails.agencyName || source.agencyName || stub.agency || "",
    status: stub.oppStatus || detail.ost || "",
    description,
    eligibility_text: source.applicantEligibilityDesc || applicantTypes,
    close_date: closeDate || "",
    close_date_note: closeNote,
    rolling: /rolling|open\s+until\s+superseded/i.test(text(closeNote)),
    career_stage_signal: `${text(closeNote)} ${text(
      source.applicantEligibilityDesc,
    )}`.slice(0, 1000),
    award_ceiling: source.awardCeiling || "",
    award_floor: source.awardFloor || "",
    total_program_funding: source.estimatedFunding || "",
    expected_number_of_awards: source.numberOfAwards || "",
    duration:
      source.projectPeriod ||
      source.awardDuration ||
      inferDuration(description),
    estimated_project_start:
      source.estimatedProjectStartDate ||
      source.estProjectStartDate ||
      "",
    limited_submission: false,
    limited_submission_criteria: "",
    cost_share_required: Boolean(source.costSharing),
    cost_share_detail: source.costSharing ? "Cost share required" : "",
    has_preliminary_stage: Boolean(preliminaryStageType),
    preliminary_stage_type: preliminaryStageType,
    detail_page: opportunityId ? `${DETAIL_PAGE}${opportunityId}` : "",
    nofo_pdf_url: primaryAttachment,
    primary_document_url:
      primaryAttachment || source.fundingDescLinkUrl || "",
  };
}

export async function fetchLiveOpportunities(
  keywords: string[],
  limit: number,
) {
  const stubs = new Map<string, JsonRecord>();

  for (const keyword of keywords.slice(0, 5)) {
    const remaining = limit - stubs.size;
    if (remaining <= 0) break;
    const response = await postJson(SEARCH_URL, {
      keyword,
      oppStatuses: "forecasted|posted",
      eligibilities: "25|06|20",
      rows: Math.min(remaining, 25),
      startRecordNum: 0,
    });
    for (const hit of records(record(response.data).oppHits)) {
      const id = text(hit.id);
      if (id && !stubs.has(id)) stubs.set(id, hit);
    }
  }

  const details = await Promise.all(
    [...stubs.entries()].slice(0, limit).map(async ([id, stub]) => {
      const response = await postJson(DETAIL_URL, { opportunityId: id });
      return normalizeDetail(stub, record(response.data));
    }),
  );

  return details;
}
