# Milestones 1–3 implementation report

Status: Milestone 3 implemented and fixture-tested locally
Date: 2026-11-11

## Milestone 3 delivered

- Deterministic job requirement decomposition from normalized listing fields and description text, preserving wording, IDs, categories, criticality, evidence expectations, confidence, and source references.
- Evidence-based evaluation maps requirements to the current profile and evidence graph. It separates technical fit, project/experience relevance, responsibility alignment, eligibility, interest, freshness, evidence confidence, growth, and recommendation.
- Hard eligibility gates independently. Confirmed graduation, degree, or dated experience failures produce `ineligible`; unknown conditions produce `manual_review`.
- Recommendations persist requirement evidence matches, growth, critic flags, explanations, and an immutable result snapshot. Repeated assessment for the same profile/job/source/engine is idempotent.
- GitHub analysis is optional and candidate-authorized. Public REST sync supports conditional profile fetch, repository pagination/metadata/languages/topics, bounded tree and selected-file inspection, README metadata, bounded PR/issue/review search, local caching, transient retry, and rate-limit stop behavior.
- Resume project/work claims can be reconciled against repository signals, with account ownership uncertainty retained. Candidates can correct a finding's classification and add a note through the service/API.
- Repository code and README text are untrusted, never executed, and not retained. Forks and account ownership uncertainty remain visible. Popularity does not affect qualification.
- A 30-case deterministic benchmark passes all expected recommendation labels. This is fixture consistency, not population accuracy.

### Milestone 3 migration

- `0004`: GitHub association/repository/contribution/analysis, claim reconciliation, job requirements, qualification assessment/evidence matches, growth, recommendation, and benchmark result records.
- Migrations `0001`–`0003` remain unchanged. Fresh SQLite upgrade/downgrade is tested.

### Milestone 3 limitations

- No OAuth/private repository access, stored credentials, live GitHub check, cloning, source execution, or broad downloads.
- GitHub search is bounded to first pages; API attribution is not proof of authorship of all repository code.
- Claim reconciliation is conservative and phrase-limited; it does not independently verify project scale or authorship.
- Disabling GitHub stops future sync/evaluation use; deletion/retention controls for prior snapshots are not implemented.
- Requirement extraction and fit heuristics are conservative. Current hard checks cover explicit graduation years, degree terms, and dated experience. Authorization/location remain unknown absent matching candidate preference data.

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

## Milestones 1 and 2 verification

- Tests: **24 passed**, **0 skipped**, 83% aggregate coverage. One non-failing upstream Starlette warning notes that its current `httpx` TestClient integration is deprecated.
- Static checks: Ruff lint passed; Ruff format check passed; mypy passed for all 28 source files.
- Migrations: fresh file-backed SQLite upgrade through `0003` and downgrade to base passed; candidate current-version foreign keys are asserted by the migration test.
- Local ingestion: 10 entities, 51 skills, 37 direct evidence edges; identical re-import was a semantic no-op; normal profile output omitted contact data.
- Discovery: manual zero-source execution completed successfully; provider behavior is covered only by mocked deterministic fixtures.
- Backup: SQLite integrity check returned `ok` and foreign-key check returned zero violations.
- Security/data check: no committed contact literals, secrets, local databases, copied resumes, generated exports, or Git remotes.

## Milestone 3 verification

- Full suite: **44 passed**, **0 skipped**, coverage **86%** across 2,768 statements.
- Ruff lint and format passed; mypy passed for all 36 source files.
- Fresh SQLite migration integration upgraded through `0004` and downgraded to base.
- Git whitespace check passed. No live GitHub calls were made.
- Migration integration test upgraded a fresh SQLite database through `0004` and downgraded to base.
- Git whitespace check passed. No live GitHub calls were made.
