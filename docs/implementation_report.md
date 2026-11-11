# Milestones 1 and 2 implementation report

Status: implemented and fixture-tested locally
Date: 2026-11-11

## Delivered

- Career profile persistence, deterministic PDF ingestion, source provenance, evidence queries, immutable snapshots, preference versions, semantic no-op imports, comparison, and completeness validation.
- Discovery registry, connector contract, public Greenhouse/Lever/Ashby connectors, pagination where documented, checkpoints, bounded retries, isolation, overlap leases, and recurring/manual runs.
- Common jobs, raw appearances, field origins, normalized locations/skills, explainable deduplication, provenance-preserving merges, and listing lifecycle.
- Two reversible Alembic migrations, local CLI, FastAPI adapter, SQLite backup verification, sanitized fixtures, and automated tests.

## Implemented connectors

| Connector | Access | Verification | Limitation |
| --- | --- | --- | --- |
| Greenhouse | Public documented Job Board GET API | Realistic saved fixture and mocked HTTP | Full board; configured token required |
| Lever | Public documented Postings GET API | Mocked pagination and failure cases | No updated-since cursor; site/region required |
| Ashby | Public documented Job Postings GET API | Listed/unlisted, workplace, location, and compensation fixture | Full board; job URL is source identity |

No live provider was contacted. LinkedIn, Indeed, Wellfound, YC, X/Twitter, generic HTML, CAPTCHAs, and authenticated scraping remain unsupported.

## Profile ingestion

The supplied resume was ingested locally as one immutable version. It produced separate experience, project, education, contribution, and achievement records. Work-supported skills received direct resume-extracted evidence; competency-only mentions remained unverified. Unknown preferences were preserved. Contact values and generated data were not committed.

## Database

- `0001`: profile, evidence, preferences, validation, discovery, provenance, deduplication, and lifecycle.
- `0002`: normalized job locations, skill requirements, and field observations.
- `0003`: foreign-key enforcement for each candidate's current profile and preference pointers.
- SQLite foreign keys, WAL, busy timeout, unique constraints, indexes, and lifecycle checks are active.
- ORM types are PostgreSQL-portable; PostgreSQL behavior remains untested.

## Deferred

- Matching/ranking, embeddings, LLM reasoning, tailoring, application automation/tracking, notifications, and user interfaces.
- OCR and general document-layout intelligence.
- External API authentication, hosted deployment, encrypted remote backups, and live connector smoke tests.
- Prose-to-requirement inference beyond deterministic stated fields.

## Final verification

- Tests: **24 passed**, **0 skipped**, 83% aggregate coverage. One non-failing upstream Starlette warning notes that its current `httpx` TestClient integration is deprecated.
- Static checks: Ruff lint passed; Ruff format check passed; mypy passed for all 28 source files.
- Migrations: fresh file-backed SQLite upgrade through `0003` and downgrade to base passed; candidate current-version foreign keys are asserted by the migration test.
- Local ingestion: 10 entities, 51 skills, 37 direct evidence edges; identical re-import was a semantic no-op; normal profile output omitted contact data.
- Discovery: manual zero-source execution completed successfully; provider behavior is covered only by mocked deterministic fixtures.
- Backup: SQLite integrity check returned `ok` and foreign-key check returned zero violations.
- Security/data check: no committed contact literals, secrets, local databases, copied resumes, generated exports, or Git remotes.
