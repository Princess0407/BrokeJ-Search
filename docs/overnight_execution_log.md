# Overnight execution log

Date: 2026-11-11
Mode: local autonomous implementation; no remote operations

## Repository and bootstrap

- Re-read the five approved documents and inspected the resume/workspace.
- Initialized local Git on `main` with project-local identity `BrokeJ-Search Local <local@brokej-search.invalid>`; no remote was added.
- Added the Python package, uv lock, environment template, private-data ignores, structured configuration/logging, SQLAlchemy runtime, and Alembic.
- Initial installation exposed a missing README build input; added it and resumed.

## Persistence

- Added Migration 0001 with candidate sources/fragments, immutable profile entities/subtypes, statements, skills/evidence, preference versions, validation reports, discovery runs/checkpoints/leases/retries, jobs/provenance, dedup decisions, and lifecycle events.
- Found and fixed an Alembic transaction bug: a SQLite PRAGMA autobegan a transaction, causing the version row to roll back while DDL persisted. The environment now commits the PRAGMA before Alembic starts its transaction.
- Added Migration 0002 instead of rewriting 0001, normalizing job locations, skill requirements, and field-level observations.
- Added Migration 0003 for candidate current-version foreign keys. Its SQLite batch migration temporarily disables foreign-key checks while rebuilding the referenced table, then re-enables and verifies them.
- Verified fresh upgrade and downgrade against file-backed temporary SQLite.

## Milestone 1

- Implemented validated PDF extraction with page text and annotation hyperlinks.
- Implemented deterministic section/entity parsing and skill normalization for the supplied conventional resume.
- Implemented content-addressed, permission-restricted source copies under ignored local storage.
- Implemented immutable profile snapshots, independently versioned preferences, semantic no-op ingestion, profile retrieval/diff, evidence traversal, and completeness validation.
- Local ingestion produced 10 typed entities, 51 skills, and 37 direct evidence edges. Competency-only skills remained unverified. Contact values were not logged or documented.

## Milestone 2

- Implemented the common async connector interface and bounded retries for network errors, 408, 429, and 5xx.
- Implemented Greenhouse, Lever (pagination and EU host), and Ashby public-board mappers against saved fixtures.
- Implemented source registry/enabled state, checkpoints/retries, leases, run history, failure isolation, and successful-check omission tracking.
- Implemented common jobs, raw appearances, explicit field origins, normalized locations/requirements, conservative deduplication, provenance-preserving merges, potential duplicates, and lifecycle events.
- Corrected the recurring scheduler so the interval job runs rather than remaining paused.

## Adapters and verification

- Added CLI commands for migrations/backups, profiles, sources, discovery, and worker startup.
- Added local FastAPI health/readiness, profile, evidence, discovery, and job endpoints.
- Added SQLite online backup and integrity/foreign-key verification.
- First comprehensive run: 21 passed, 2 failed. One test incorrectly expected two jobs where dedup correctly merged the same vacancy; the other exposed the Alembic version transaction defect. Both were corrected at the root.
- Second comprehensive run before Migration 0002: 23 passed with one upstream Starlette/httpx deprecation warning.
- Final run: 24 passed, 0 skipped, 83% coverage; Ruff lint/format and mypy passed. Migration 0003 was current, backup integrity was `ok`, and foreign-key verification had zero violations. One upstream Starlette/httpx deprecation warning remains non-failing.
