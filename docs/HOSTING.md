# Hosting and deployment

## Decision

`mporosoff/grants-scraper` is the source-of-truth repository for application
code, documentation, tests, database migrations, and deployment configuration.

GitHub is not the production database or the host for the Python web
application. GitHub Pages serves static files and cannot run the planned
Django backend. GitHub-hosted Actions runners are temporary machines, so their
filesystems are not durable application storage.

## Intended topology

```text
GitHub repository
    |
    | test and deploy
    v
Python web application  ---->  managed PostgreSQL database
    |
    +----> Grants.gov and other funding sources
    |
    +----> optional object storage for cached NOFO files
```

Faculty use only the web application URL. They do not clone the repository,
install Python, or run ingestion commands.

## What belongs in GitHub

- application and ingestion code
- automated tests
- database schema migrations
- deployment configuration
- non-sensitive documentation
- continuous-integration workflows

## What must stay outside GitHub

- faculty accounts and profile contents
- normalized production grant records
- feedback and match history
- API keys, passwords, and signing secrets
- downloaded NOFO files and other generated datasets

These belong in the deployed application's database, secret store, or object
storage. Committing generated records repeatedly would permanently inflate Git
history and would expose profile data in the public repository.

## Role of GitHub Actions

GitHub Actions should:

- run tests for every proposed change
- build and deploy the application
- optionally trigger a scheduled ingestion job against the deployed service

Actions should not act as the primary database. Every hosted job starts on a
fresh runner and the runner is discarded when the job ends.

## Deployment stages

1. **Development:** run the application locally with SQLite.
2. **Shared pilot:** deploy the same application to a managed Python host with
   PostgreSQL.
3. **Production:** move or retain it on a University-approved service, add UR
   single sign-on, backups, monitoring, and a scheduled worker.

The application should remain deployment-neutral until University hosting
options are confirmed. A container definition can provide the same build on a
commercial platform or a University-managed server.
