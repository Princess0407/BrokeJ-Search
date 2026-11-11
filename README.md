# BrokeJ-Search

BrokeJ-Search is a local-first backend for evidence-backed career profiles, permitted job discovery, and explainable job-fit evaluation. It implements Milestones 1–3 as a Python modular monolith. It does not tailor resumes, submit applications, or provide a frontend.

## Implemented

- PDF resume extraction with validation, section parsing, hyperlink capture, and ambiguity reporting.
- Immutable profile snapshots with separate experience, projects, education, contributions, achievements, skills, evidence, and independently versioned preferences.
- Evidence queries connecting skills to work statements and source fragments without inventing proficiency.
- Idempotent ingestion, profile comparison, completeness reports, and explicit unknown preferences.
- Greenhouse, Lever, and Ashby public job-board connectors against documented response formats.
- Source registry, pagination, checkpoints, durable retries, rate-limit handling, overlap leases, and failure isolation.
- Common jobs, raw source appearances, field origins, conservative deduplication, and lifecycle events.
- Deterministic job requirement extraction and separate qualification, eligibility, growth, preference, and evidence-confidence assessments.
- Optional, candidate-authorized public GitHub evidence with bounded repository inspection and attribution uncertainty.
- Resume project/work claim reconciliation with candidate correction notes.
- Deterministic recommendation critic and a curated 30-case regression benchmark.
- Manual CLI, recurring APScheduler worker, thin FastAPI adapter, reversible migrations, and SQLite backups.

The three connectors are protocol/fixture tested. Ordinary tests never call live providers. LinkedIn, Indeed, Wellfound, YC, and social scraping are not implemented.

## Requirements and installation

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)

```bash
uv sync --all-groups
cp .env.example .env
uv run alembic upgrade head
uv run brokej --help
```

Default data is stored under `data/`. Databases, copied resumes, generated profile exports, `.env`, and contact details are excluded from Git.

## Configuration

Settings use the `BROKEJ_` prefix:

| Variable | Default | Purpose |
| --- | --- | --- |
| `BROKEJ_DATABASE_URL` | `sqlite:///./data/brokej.db` | SQLAlchemy database URL |
| `BROKEJ_SOURCE_STORAGE` | `./data/sources` | Private content-addressed source copies |
| `BROKEJ_LOG_LEVEL` | `INFO` | Structured log level |
| `BROKEJ_HTTP_TIMEOUT_SECONDS` | `20` | Connector timeout |
| `BROKEJ_DISCOVERY_USER_AGENT` | local application identifier | Provider user agent |
| `BROKEJ_DISCOVERY_INTERVAL_MINUTES` | `1440` | Recurring discovery interval |
| `BROKEJ_SCHEDULER_TIMEZONE` | `UTC` | Scheduler timezone |

Connector identifiers and non-secret settings are stored in the database. The implemented public GET connectors require no provider credentials.

## Career profile

```bash
uv run brokej profile ingest --candidate primary --resume Resume-5.pdf
uv run brokej profile show --candidate primary
uv run brokej profile validate --candidate primary
uv run brokej profile evidence --candidate primary --skill Python
```

`profile show` omits contact fields by default. Use `--private` only in a trusted local terminal. Re-importing an identical semantic profile records a no-op ingestion and does not duplicate entities or create a profile version. A changed resume creates a new immutable version.

```bash
uv run brokej profile diff --candidate primary --from 1 --to 2
```

Resume claims are `resume_extracted`; hyperlinks remain resume-provided evidence until independently verified. Missing eligibility, location, compensation, authorization, and arrangement preferences stay explicitly unknown.

## Discovery sources

Register board identifiers explicitly; BrokeJ-Search does not crawl for company boards:

```bash
uv run brokej discovery source-add \
  --name example-greenhouse --type greenhouse --board example --company "Example Inc"
uv run brokej discovery source-add \
  --name example-lever --type lever --board example --company "Example Inc" --region global
uv run brokej discovery source-add \
  --name example-ashby --type ashby --board example --company "Example Inc"

uv run brokej discovery source-list
uv run brokej discovery source-disable --source-id SOURCE_UUID
uv run brokej discovery source-enable --source-id SOURCE_UUID
```

The board value is the Greenhouse board token, Lever site name, or Ashby job-board name. Lever supports `global` and `eu` regions. Provider-specific rate/page settings are available through the service/API `config` object.

```bash
uv run brokej discovery run
uv run brokej discovery run --source-id SOURCE_UUID
uv run brokej discovery worker
```

One failed source creates a durable retry record without rolling back successful sources. A successful full-board omission must happen twice before a listing can expire.

## API

The API is local-only by default because external authentication is not part of these milestones:

```bash
uv run brokej serve --host 127.0.0.1 --port 8000
```

Routes include health/readiness, profile ingestion/retrieval/completeness/evidence, discovery source/run status, job list/detail, job requirement extraction, candidate/job assessment, GitHub association consent/disable, and claim reconciliation/correction. The service API also exposes GitHub sync for callers that provide an HTTP client. OpenAPI documentation is available at `/docs`. Do not bind publicly until authentication and transport security are added.

An assessment is generated with `POST /candidates/{candidate_id}/jobs/{job_id}/assessment`. GitHub association is candidate opt-in through `PUT /candidates/{candidate_id}/github` with username/profile URL, `authorized`, and optional `ownership_confirmed`; `DELETE` disables it. `POST /candidates/{candidate_id}/github/reconciliations` refreshes findings, and `PATCH /candidates/{candidate_id}/github/reconciliations/{id}` records a candidate correction/note. The flow never requests private repository access.

## Database operations

```bash
uv run alembic current
uv run alembic upgrade head
uv run alembic downgrade -1
uv run brokej db backup --output /tmp/brokej-backup.db
uv run brokej db verify-backup --input /tmp/brokej-backup.db
```

The backup command uses SQLite's online backup API. Resume source files live separately under `BROKEJ_SOURCE_STORAGE`; back them up with equivalent private-file permissions in production.

## Development and tests

```bash
uv run pytest
uv run pytest --cov=brokej_search
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Tests use migrated, file-backed temporary SQLite databases and mocked HTTP. They cover PDF parsing, evidence, idempotent versions, preferences, provider fixtures, pagination, retries, malformed payloads, deduplication, provenance, restart checkpoints, lifecycle, requirements, eligibility, growth, GitHub limits/opt-out, benchmark consistency, migrations, and API boundaries.

## Troubleshooting

- **PDF has no extractable text:** OCR is required; the parser does not guess from images.
- **Source returns 403/404:** verify its board identifier and Lever region. Non-retryable 4xx responses are not hammered.
- **Source repeatedly returns 429/5xx:** inspect `source_runs` and `retry_items`; lower the schedule/rate.
- **Source is busy:** wait for the active run or its ten-minute crash-recovery lease.
- **Jobs do not immediately expire:** transient failures and one successful omission cannot expire a listing.

## Known limitations

- Parsing is deterministic and conservative for conventional heading/bullet resumes; OCR and arbitrary layouts are deferred.
- Public ATS endpoints mostly provide full-board snapshots, not true incremental cursors.
- Current connectors do not guess skills or eligibility requirements from prose.
- Requirement extraction and scoring are deterministic heuristics. The 30-case benchmark measures consistency with authored expectations, not universal accuracy or confidence calibration.
- GitHub inspection is public-only, opt-in, bounded, and mocked in tests; no live sync, OAuth, private repository access, or code execution is included.
- SQLite targets one small worker. PostgreSQL portability is designed but not exercised here.
- External API authentication, remote encrypted backup transport, and live provider smoke tests are deployment work.

See [the technical design](docs/technical_design.md), [data model](docs/data_model.md), [source capability matrix](docs/source_capabilities.md), and [implementation report](docs/implementation_report.md).
