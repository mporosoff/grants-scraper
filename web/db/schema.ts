import { sql } from "drizzle-orm";
import {
  integer,
  sqliteTable,
  text,
  uniqueIndex,
} from "drizzle-orm/sqlite-core";

export const facultyProfiles = sqliteTable(
  "faculty_profiles",
  {
    id: text("id").primaryKey(),
    ownerEmail: text("owner_email").notNull(),
    name: text("name").notNull(),
    academicTitle: text("academic_title").notNull().default(""),
    careerStage: text("career_stage").notNull().default("unknown"),
    yearsSinceDoctorate: integer("years_since_doctorate"),
    synopsis: text("synopsis").notNull(),
    topics: text("topics").notNull().default(""),
    methods: text("methods").notNull().default(""),
    applicationAreas: text("application_areas").notNull().default(""),
    futureDirections: text("future_directions").notNull().default(""),
    excludeTopics: text("exclude_topics").notNull().default(""),
    groupWebsite: text("group_website").notNull().default(""),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    uniqueIndex("faculty_profiles_owner_email_idx").on(table.ownerEmail),
  ],
);

export const opportunities = sqliteTable("opportunities", {
  id: text("id").primaryKey(),
  opportunityNumber: text("opportunity_number").notNull().default(""),
  title: text("title").notNull(),
  agency: text("agency").notNull().default(""),
  status: text("status").notNull().default(""),
  description: text("description").notNull().default(""),
  eligibilityText: text("eligibility_text").notNull().default(""),
  careerStageSignal: text("career_stage_signal").notNull().default(""),
  closeDate: text("close_date").notNull().default(""),
  closeDateNote: text("close_date_note").notNull().default(""),
  rolling: integer("rolling", { mode: "boolean" }).notNull().default(false),
  awardCeiling: text("award_ceiling").notNull().default(""),
  awardFloor: text("award_floor").notNull().default(""),
  totalProgramFunding: text("total_program_funding").notNull().default(""),
  expectedAwards: text("expected_awards").notNull().default(""),
  duration: text("duration").notNull().default(""),
  projectStartDate: text("project_start_date").notNull().default(""),
  limitedSubmission: integer("limited_submission", { mode: "boolean" })
    .notNull()
    .default(false),
  limitedSubmissionCriteria: text("limited_submission_criteria")
    .notNull()
    .default(""),
  costShareRequired: integer("cost_share_required", { mode: "boolean" })
    .notNull()
    .default(false),
  costShareDetail: text("cost_share_detail").notNull().default(""),
  hasPreliminaryStage: integer("has_preliminary_stage", { mode: "boolean" })
    .notNull()
    .default(false),
  preliminaryStageType: text("preliminary_stage_type").notNull().default(""),
  detailPage: text("detail_page").notNull().default(""),
  nofoPdfUrl: text("nofo_pdf_url").notNull().default(""),
  importedAt: text("imported_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const matchFeedback = sqliteTable(
  "match_feedback",
  {
    id: text("id").primaryKey(),
    ownerEmail: text("owner_email").notNull(),
    profileId: text("profile_id").notNull(),
    opportunityId: text("opportunity_id").notNull(),
    decision: text("decision").notNull(),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    uniqueIndex("match_feedback_owner_opportunity_idx").on(
      table.ownerEmail,
      table.opportunityId,
    ),
  ],
);
