# UR Grant Matcher web application

The faculty-facing application is a Vinext/React site with server routes and a
durable D1 database. It is designed to be opened from a URL; end users do not
need Python or a local installation.

## Workflow

1. A faculty member writes and saves a research profile.
2. The opportunity feed is refreshed from Grants.gov or populated from
   normalized JSON.
3. The match explorer ranks the feed, explains each recommendation, and flags
   eligibility or deadline concerns.
4. The faculty member records useful/not-relevant feedback and can export the
   visible list as CSV.

Workspace identity headers keep each saved profile and its feedback associated
with the signed-in user. Production records stay in D1 rather than GitHub.

## Developer commands

Requires Node.js 22.13 or newer and pnpm.

```powershell
pnpm install
pnpm dev
pnpm test
```

`pnpm test` builds the production worker and then runs product-level source and
render checks. When the database schema changes, generate a migration with:

```powershell
pnpm db:generate
```

The application has no browser-side model key fields. A later semantic matcher
must call one selected provider for both retrieval and reranking from
server-side code, with its single credential kept in the hosting platform's
secret store.
