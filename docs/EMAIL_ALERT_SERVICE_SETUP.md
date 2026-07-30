# Funding Finder account and alert service

The public search can remain on GitHub Pages. Accounts, subscriptions, private
RSS URLs, and email delivery should live in a small separate service so no
email address, profile, token, or provider credential enters the public
repository.

## Recommended MVP

Use **Supabase Auth + Postgres + scheduled Edge Functions**, with **Resend or
Postmark** for transactional email. This is the shortest route to:

- email magic-link accounts;
- row-level security for each user's profile and saved searches;
- a weekly scheduled job;
- confirmation and unsubscribe endpoints;
- private, tokenized RSS feeds; and
- delivery/bounce records without maintaining a server.

The existing private GitHub Actions digest remains a suitable invitation-only
pilot. Move to the service when users need self-service signup, multiple saved
searches, or account-managed preferences.

## Other viable options

| Option | Best fit | Tradeoff |
|---|---|---|
| Cloudflare Workers + D1 + Resend | Lowest-cost, globally distributed service | You build more auth/account behavior yourself or add an auth vendor |
| Azure Functions + Entra External ID + Azure SQL/Table Storage + Azure Communication Services | University-managed identity, procurement, and governance | More setup and administrative overhead |
| AWS Lambda + Cognito + DynamoDB + SES | Existing AWS organization | More components and SES deliverability setup |
| Private GitHub Actions + SMTP | Small, manually approved pilot | No self-service accounts; subscriber JSON and state require operator care |

## Service boundary

```text
GitHub Pages application
        |
        | HTTPS: sign in, save search, manage alerts
        v
Account/alert API + database
        |
        | scheduled weekly job
        +----> public opportunities.js
        +----> public feeds/changes.json
        +----> shared scripts/alert_match.py logic
        |
        +----> Resend/Postmark ----> user email
        |
        +----> private /rss/{opaque-token}.xml
```

The service should fetch the published catalog and change feed at the start of
each run. It should never scrape source sites itself. This preserves one
currentness and matching implementation.

## Minimal data model

Use UUID primary keys and store unsubscribe/RSS tokens only as hashes.

```sql
create table profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  research_summary text,
  expertise_terms text[] not null default '{}',
  applicant_context text,
  career_stage text,
  timezone text not null default 'America/New_York',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table saved_searches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  query text not null default '',
  filters jsonb not null default '{}',
  frequency text not null default 'weekly'
    check (frequency in ('weekly', 'off')),
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table subscriptions (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  confirmed_at timestamptz,
  unsubscribed_at timestamptz,
  unsubscribe_token_hash text not null,
  rss_token_hash text not null,
  provider_contact_id text
);

create table delivery_state (
  saved_search_id uuid primary key references saved_searches(id) on delete cascade,
  last_success_at timestamptz,
  notified_opportunity_ids jsonb not null default '[]',
  notified_event_ids jsonb not null default '[]',
  last_catalog_generated_at timestamptz
);

create table delivery_log (
  id uuid primary key default gen_random_uuid(),
  saved_search_id uuid references saved_searches(id) on delete set null,
  provider_message_id text,
  status text not null,
  item_count integer not null default 0,
  created_at timestamptz not null default now()
);
```

Enable row-level security on the first four tables. A signed-in user may read
and update only rows whose `user_id` is their Auth user ID. The scheduled
worker uses a server-side service-role secret. Never expose that secret in the
browser.

## Endpoints

- `POST /subscriptions` — create/update a subscription and send a confirmation
  email.
- `GET /confirm?token=...` — record double opt-in.
- `GET /unsubscribe?token=...` — one-click global unsubscribe.
- `GET/POST/PATCH/DELETE /saved-searches` — account-managed searches.
- `POST /alerts/test` — signed-in preview or test delivery with a strict rate
  limit.
- `GET /rss/{token}.xml` — personalized Atom/RSS output. Use an opaque,
  revocable token; do not encode the email address or query in the URL.
- `POST /webhooks/email` — record delivered, bounced, complained, and
  suppressed events from the email provider.

## Weekly job

1. Acquire a run lock so two schedules cannot send duplicate mail.
2. Download `data/opportunities.js` and `feeds/changes.json` from the public
   site; abort if the catalog is stale or fails schema validation.
3. Load confirmed, enabled subscriptions in bounded pages.
4. Run each saved search through the same matching/currentness rules in
   `scripts/alert_match.py`.
5. Select unseen new matches and relevant change events. Change events include
   deadline changes, amendments, entry into the 30-day closing window, and
   closure/removal.
6. Render one digest per user, grouping multiple saved searches to avoid email
   fatigue.
7. Send with a stable idempotency key such as
   `user-id + week-start + catalog-generated-at`.
8. Update watermarks only after the provider accepts the message.
9. Process bounce/complaint webhooks and suppress future sends immediately.

The personalized RSS endpoint runs the same matcher and runtime expiration
gate but returns the most recent matching records and change events. Cache it
briefly (for example, 15 minutes) and allow users to rotate the token.

## Setup sequence

1. Create the Supabase project in the institution-approved region.
2. Enable email magic-link authentication and configure the production site
   and callback URLs.
3. Apply the schema, row-level-security policies, and indexes on
   `saved_searches(user_id, enabled)` and `delivery_log(created_at)`.
4. Verify a sending domain with Resend or Postmark; configure SPF, DKIM, and a
   dedicated return path.
5. Store `PUBLIC_CATALOG_URL`, `PUBLIC_CHANGE_FEED_URL`,
   `EMAIL_PROVIDER_API_KEY`, `EMAIL_FROM`, and the service-role key as
   server-side secrets.
6. Deploy confirmation, unsubscribe, saved-search, RSS, webhook, and digest
   functions.
7. Schedule the digest function weekly. Start with a small internal cohort and
   a dry-run/preview mode.
8. Add the account UI to Funding Finder only after the API is deployed:
   “Sign in,” “Save this search,” alert frequency, profile/interests, private
   RSS link, and unsubscribe/delete-account controls.
9. Test confirmation, duplicate-run idempotency, deadline changes, expired
   record exclusion, bounce suppression, unsubscribe, token rotation, and
   account deletion.
10. Add operational alerts for stale catalogs, failed digest runs, high bounce
    rate, and email-provider rejection.

## Privacy and deliverability requirements

- Require recorded double opt-in; a missing consent flag must fail closed.
- Put a working one-click unsubscribe link in every message.
- Do not store CV files or full CV text in the alert service. A short,
  user-edited research summary and explicit interest terms are sufficient.
- Encrypt provider secrets, use least-privilege service keys, and retain
  delivery logs for a defined period.
- Publish a privacy notice covering stored profile fields, retention,
  subprocessors, account deletion, and the fact that official opportunities
  must still be verified.
- Send slowly during the pilot, monitor bounces/complaints, and do not move to
  self-service signup until the sending domain has established a good
  reputation.
