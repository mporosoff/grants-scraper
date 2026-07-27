# Weekly email alerts for Funding Finder (GitHub-native)

This folder is a **ready-to-use bundle** for sending weekly email digests of a
saved search. It is kept here for version control, but it is meant to run from a
**separate, private** GitHub repository so that subscriber email addresses are
never stored in the public site repo.

## How it works (plain English)

Once a week, a GitHub Action:

1. clones the public Funding Finder repo (public, so no login needed) to get the
   latest catalog and the shared search code;
2. for each subscriber, re-runs their saved search and keeps only opportunities
   that are **new since their last email** (including undated external-source
   records when Funding Finder first saw them);
3. emails each subscriber a short digest of those new matches;
4. remembers what it sent (in `state.json`) so nobody gets the same item twice.

The search ranks the same way it does on the website, because it reuses the
site's own search index.

## What you need

- A GitHub account (you have one) and the ability to create a **private** repo.
- An SMTP email sender. Two easy options:
  - **University email relay** (ask UR IT for SMTP host/port/username/password), or
  - a free transactional-email account (e.g., Brevo, Mailjet, or a Gmail
    "app password"). Any SMTP server works.

## One-time setup (about 15 minutes)

**1. Create a private repo.** On GitHub: *New repository* → name it
   `grants-scraper-alerts` → set **Private** → Create.

**2. Add these four files** to that repo (copy from this folder):
   - `send_digest.py`
   - `weekly-digest.yml` → put it at `.github/workflows/weekly-digest.yml`
   - `subscriptions.json` → start by copying `subscriptions.example.json` and
     editing it (see below)
   - `state.json` → copy as-is (it just contains `{}`)

**3. Add your email-sending secrets.** In the private repo: *Settings* →
   *Secrets and variables* → *Actions* → *New repository secret*. Add:
   - `SMTP_HOST` (e.g. `smtp.example.edu`)
   - `SMTP_PORT` (usually `587`)
   - `SMTP_USER` (your SMTP username)
   - `SMTP_PASSWORD` (your SMTP password / app password)
   - `SMTP_FROM` (the "from" address, e.g. `funding-finder@example.edu`)

   > These go into GitHub's encrypted secrets — not into any file. The script
   > reads them at run time; they are never printed in logs.

**4. Add subscribers** by editing `subscriptions.json`. Each entry:

   ```json
   {
     "id": "amy-catalysis",
     "email": "amy@example.edu",
     "label": "Amy — catalysis",
     "query": "heterogeneous catalysis hydrogen",
     "filters": { "source_type": ["Federal"], "topic": ["Energy"] },
     "active": true,
     "confirmed": true
   }
   ```

   - `id` — any unique short string.
   - `query` — the search text (leave `""` for a filter-only alert).
   - `filters` — optional; facet names are `source_type`, `source`, `agency`,
     `topic`, `discipline`, `eligibility`, `funding_instrument`,
     `funding_category`, `status`. Values are lists.
   - `confirmed` — set `true` only once the person has agreed to receive email
     (see "Consent" below). Consent fails closed: a missing or false value is
     always skipped.

**5. Test it without sending.** In the private repo: *Actions* →
   *Weekly funding digest* → *Run workflow* → check **Preview only** → *Run*.
   The log shows who would get how many items (emails are masked). When it looks
   right, run it again unchecked to send for real. After that it runs itself
   every Monday.

## Consent & unsubscribe (please read)

Sending unsolicited bulk email is both bad practice and, in many places, against
the law. For this pilot:

- Only add someone after they have **asked** to receive alerts (e.g., they told
  you their saved search). Set `confirmed: true` only then.
- Every email includes a line telling people to **reply to stop or change**
  their alert. Honor those promptly by editing `subscriptions.json`
  (`"active": false` or remove the entry).
- Keep the subscriber list in the **private** repo only.

If this grows beyond a pilot, add an automated double-opt-in (a confirmation
link before the first digest) and a one-click unsubscribe link. The schema
already includes a `confirmed` flag for that path.

## Changing the schedule

Edit the `cron` line in `weekly-digest.yml`. `0 12 * * 1` means Mondays at
12:00 UTC. (GitHub cron is always in UTC.)

## Local dry run (optional, for the curious)

```bash
git clone --depth 1 https://github.com/mporosoff/grants-scraper site
python send_digest.py --site ./site --dry-run
```
