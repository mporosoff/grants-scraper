import { env } from "cloudflare:workers";
import { drizzle } from "drizzle-orm/d1";
import * as schema from "./schema";

const schemaStatements = [
  `CREATE TABLE IF NOT EXISTS faculty_profiles (
    id TEXT PRIMARY KEY,
    owner_email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    academic_title TEXT NOT NULL DEFAULT '',
    career_stage TEXT NOT NULL DEFAULT 'unknown',
    years_since_doctorate INTEGER,
    synopsis TEXT NOT NULL,
    topics TEXT NOT NULL DEFAULT '',
    methods TEXT NOT NULL DEFAULT '',
    application_areas TEXT NOT NULL DEFAULT '',
    future_directions TEXT NOT NULL DEFAULT '',
    exclude_topics TEXT NOT NULL DEFAULT '',
    group_website TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  )`,
  `CREATE TABLE IF NOT EXISTS opportunities (
    id TEXT PRIMARY KEY,
    opportunity_number TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    agency TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    eligibility_text TEXT NOT NULL DEFAULT '',
    career_stage_signal TEXT NOT NULL DEFAULT '',
    close_date TEXT NOT NULL DEFAULT '',
    close_date_note TEXT NOT NULL DEFAULT '',
    rolling INTEGER NOT NULL DEFAULT 0,
    award_ceiling TEXT NOT NULL DEFAULT '',
    award_floor TEXT NOT NULL DEFAULT '',
    total_program_funding TEXT NOT NULL DEFAULT '',
    expected_awards TEXT NOT NULL DEFAULT '',
    duration TEXT NOT NULL DEFAULT '',
    project_start_date TEXT NOT NULL DEFAULT '',
    limited_submission INTEGER NOT NULL DEFAULT 0,
    limited_submission_criteria TEXT NOT NULL DEFAULT '',
    cost_share_required INTEGER NOT NULL DEFAULT 0,
    cost_share_detail TEXT NOT NULL DEFAULT '',
    has_preliminary_stage INTEGER NOT NULL DEFAULT 0,
    preliminary_stage_type TEXT NOT NULL DEFAULT '',
    detail_page TEXT NOT NULL DEFAULT '',
    nofo_pdf_url TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  )`,
  `CREATE TABLE IF NOT EXISTS match_feedback (
    id TEXT PRIMARY KEY,
    owner_email TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS faculty_profiles_owner_email_idx
    ON faculty_profiles(owner_email)`,
  `CREATE UNIQUE INDEX IF NOT EXISTS match_feedback_owner_opportunity_idx
    ON match_feedback(owner_email, opportunity_id)`,
];

export async function ensureSchema() {
  if (!env.DB) {
    throw new Error("Cloudflare D1 binding `DB` is unavailable.");
  }

  await env.DB.batch(
    schemaStatements.map((statement) => env.DB.prepare(statement)),
  );
}

export function getDb() {
  if (!env.DB) {
    throw new Error(
      "Cloudflare D1 binding `DB` is unavailable. Set the `d1` field in .openai/hosting.json to `DB` or let your control plane inject the real binding values before using the database."
    );
  }

  return drizzle(env.DB, { schema });
}
