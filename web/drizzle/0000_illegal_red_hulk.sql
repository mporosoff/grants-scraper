CREATE TABLE `faculty_profiles` (
	`id` text PRIMARY KEY NOT NULL,
	`owner_email` text NOT NULL,
	`name` text NOT NULL,
	`academic_title` text DEFAULT '' NOT NULL,
	`career_stage` text DEFAULT 'unknown' NOT NULL,
	`years_since_doctorate` integer,
	`synopsis` text NOT NULL,
	`topics` text DEFAULT '' NOT NULL,
	`methods` text DEFAULT '' NOT NULL,
	`application_areas` text DEFAULT '' NOT NULL,
	`future_directions` text DEFAULT '' NOT NULL,
	`exclude_topics` text DEFAULT '' NOT NULL,
	`group_website` text DEFAULT '' NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `faculty_profiles_owner_email_idx` ON `faculty_profiles` (`owner_email`);--> statement-breakpoint
CREATE TABLE `match_feedback` (
	`id` text PRIMARY KEY NOT NULL,
	`owner_email` text NOT NULL,
	`profile_id` text NOT NULL,
	`opportunity_id` text NOT NULL,
	`decision` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `match_feedback_owner_opportunity_idx` ON `match_feedback` (`owner_email`,`opportunity_id`);--> statement-breakpoint
CREATE TABLE `opportunities` (
	`id` text PRIMARY KEY NOT NULL,
	`opportunity_number` text DEFAULT '' NOT NULL,
	`title` text NOT NULL,
	`agency` text DEFAULT '' NOT NULL,
	`status` text DEFAULT '' NOT NULL,
	`description` text DEFAULT '' NOT NULL,
	`eligibility_text` text DEFAULT '' NOT NULL,
	`career_stage_signal` text DEFAULT '' NOT NULL,
	`close_date` text DEFAULT '' NOT NULL,
	`award_ceiling` text DEFAULT '' NOT NULL,
	`limited_submission` integer DEFAULT false NOT NULL,
	`cost_share_required` integer DEFAULT false NOT NULL,
	`has_preliminary_stage` integer DEFAULT false NOT NULL,
	`detail_page` text DEFAULT '' NOT NULL,
	`nofo_pdf_url` text DEFAULT '' NOT NULL,
	`imported_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
