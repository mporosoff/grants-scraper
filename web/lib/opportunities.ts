import { eq } from "drizzle-orm";
import { ensureSchema, getDb } from "@/db";
import { opportunities } from "@/db/schema";

export type OpportunityInput = Record<string, unknown>;

function stringValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.filter(Boolean).join(", ");
  return String(value).trim();
}

function booleanValue(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  return ["true", "yes", "y", "1"].includes(stringValue(value).toLowerCase());
}

function safeUrl(value: unknown): string {
  const text = stringValue(value);
  if (!text) return "";
  try {
    const url = new URL(text);
    return url.protocol === "http:" || url.protocol === "https:"
      ? url.toString()
      : "";
  } catch {
    return "";
  }
}

export function normalizeOpportunity(record: OpportunityInput) {
  const rawId =
    record.opportunity_id ??
    record.id ??
    record.opportunity_number ??
    record.number;
  const id = stringValue(rawId);
  const title = stringValue(record.title ?? record.opportunity_title);

  if (!id || !title) {
    throw new Error("Each opportunity requires an id and title.");
  }

  return {
    id,
    opportunityNumber: stringValue(
      record.opportunity_number ?? record.number,
    ),
    title,
    agency: stringValue(record.agency ?? record.agency_name),
    status: stringValue(record.status ?? record.oppStatus),
    description: stringValue(
      record.description ?? record.synopsis_description,
    ),
    eligibilityText: stringValue(
      record.eligibility_text ?? record.applicant_eligibility_description,
    ),
    careerStageSignal: stringValue(record.career_stage_signal),
    closeDate: stringValue(record.close_date ?? record.response_date),
    awardCeiling: stringValue(record.award_ceiling),
    limitedSubmission: booleanValue(record.limited_submission),
    costShareRequired: booleanValue(record.cost_share_required),
    hasPreliminaryStage: booleanValue(record.has_preliminary_stage),
    detailPage: safeUrl(record.detail_page),
    nofoPdfUrl: safeUrl(
      record.nofo_pdf_url ?? record.primary_document_url,
    ),
    importedAt: new Date().toISOString(),
  };
}

export async function saveOpportunities(records: OpportunityInput[]) {
  await ensureSchema();
  const db = getDb();
  let saved = 0;

  for (const rawRecord of records.slice(0, 500)) {
    const record = normalizeOpportunity(rawRecord);
    const existing = await db
      .select({ id: opportunities.id })
      .from(opportunities)
      .where(eq(opportunities.id, record.id))
      .limit(1);

    if (existing.length) {
      await db
        .update(opportunities)
        .set(record)
        .where(eq(opportunities.id, record.id));
    } else {
      await db.insert(opportunities).values(record);
    }
    saved += 1;
  }

  return saved;
}
