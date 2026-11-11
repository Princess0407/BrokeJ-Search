# Technical design

Status: proposed implementation design
Last reviewed: 2026-11-11

## Architecture

BrokeJ-Search will start as one Python application with three adapters around shared services:

```text
PDF / CLI / scheduled worker / future HTTP clients
                         |
                  application services
              /                              \
     career profile domain              discovery domain
              \                              /
                repositories + unit of work
                         |
               SQLAlchemy + SQLite/PostgreSQL
```

No domain service imports a CLI, scheduler, FastAPI, or terminal package. Connectors translate remote payloads at the boundary; repositories translate database rows at the persistence boundary.

## Proposed repository layout

Only directories with implementation will be created.

```text
src/brokej_search/
├── cli.py
├── core/
│   ├── config.py
│   ├── exceptions.py
│   ├── logging.py
│   └── time.py
├── career_profile/
│   ├── schemas.py
│   ├── ingestion.py
│   ├── extraction.py
│   ├── normalization.py
│   ├── merge.py
│   ├── validation.py
│   └── service.py
├── discovery/
│   ├── schemas.py
│   ├── connectors/
│   │   ├── base.py
│   │   ├── greenhouse.py
│   │   ├── lever.py
│   │   └── ashby.py
│   ├── normalization.py
│   ├── deduplication.py
│   ├── retry.py
│   ├── lifecycle.py
│   ├── scheduler.py
│   └── service.py
└── database/
    ├── base.py
    ├── models.py
    ├── repositories.py
    └── unit_of_work.py
alembic/
tests/
├── fixtures/
├── career_profile/
├── discovery/
└── integration/
examples/
└── profile.json
```

## Runtime and dependencies

Target Python 3.12+ even though the current workspace has Python 3.13.5. This keeps deployment options broader while using current typing and standard-library features.

Runtime dependencies will be limited to:

- `pydantic` and `pydantic-settings` for boundary schemas and environment configuration.
- `SQLAlchemy` 2.x and `alembic` for persistence and migrations.
- `pypdf` for PDF text, page, metadata, and annotation-link extraction.
- `httpx` for timeout-aware asynchronous connector requests.
- `APScheduler` for the hosted recurring worker adapter.
- `FastAPI` and `uvicorn` provide the implemented thin local HTTP adapter; the domain does not depend on them.

The CLI uses `argparse`; connector tests use `httpx.MockTransport`; deduplication uses normalized tokens and the standard library. No extra CLI framework, retry library, HTML parser, task queue, vector store, or database driver is needed for the initial SQLite implementation.

Development dependencies: `pytest`, `pytest-cov`, `ruff`, and `mypy`. Tests use temporary file-backed SQLite databases, never an in-memory database.

## Configuration

`Settings` reads `BROKEJ_*` environment variables and an optional local `.env` file. `.env.example` contains no credentials.

Core settings:

- `BROKEJ_DATABASE_URL`, defaulting to `sqlite:///./data/brokej.db`.
- `BROKEJ_SOURCE_STORAGE`, defaulting to `./data/sources`.
- `BROKEJ_LOG_LEVEL`.
- `BROKEJ_HTTP_TIMEOUT_SECONDS`.
- `BROKEJ_DISCOVERY_USER_AGENT` with an honest application identifier.
- `BROKEJ_SCHEDULER_TIMEZONE`, defaulting to UTC.
- `BROKEJ_DISCOVERY_INTERVAL_MINUTES`.
- Per-source settings stored in the database: connector type, board/site identifier, enabled flag, minimum request interval, page limit, and optional filters.

Provider credentials remain optional and are never stored in source metadata or emitted in logs. The three initial public GET connectors require no credentials.

## Career profile pipeline

### Extraction contracts

```python
class DocumentExtractor(Protocol):
    def extract(self, path: Path) -> ExtractedDocument: ...

class ResumeParser(Protocol):
    def parse(self, document: ExtractedDocument) -> ParsedProfile: ...
```

`PdfDocumentExtractor` validates the `%PDF-` signature, size and page limits, encryption state, extractable text, and page count. It emits page text, document metadata, links, and extraction warnings. Password-protected, image-only, malformed, or text-empty PDFs fail with a typed error or an explicit `needs_ocr` status; OCR is not silently attempted in this phase.

The first parser is conservative and deterministic:

1. Normalize Unicode whitespace without changing source text.
2. detect known section headings;
3. segment entries using heading, date, bullet, and link layout signals;
4. retain unparsed lines and ambiguity diagnostics;
5. create proposed entities and statements;
6. map exact, case-folded skill aliases to a small versioned catalog;
7. link skill mentions to the nearest work statement and source fragment;
8. classify isolated competency-list mentions as `unverified` unless another statement supplies evidence.

The source fragment always retains the original extracted value. Normalization never rewrites source evidence.

### Merge and versioning

An ingestion request is deterministic for `(candidate_id, source_sha256, parser_name, parser_version)`.

Each parsed entity receives a stable identity key, for example:

- experience: normalized organization + role + start date;
- project: normalized name + repository URL when present;
- education: institution + degree + discipline + start date;
- contribution: repository + pull-request/issue reference;
- skill: canonical skill catalog ID.

Merge precedence, highest first:

1. candidate-confirmed value;
2. independently verified source value;
3. existing resume-extracted value;
4. new resume-extracted value;
5. unknown.

Equal values coalesce and gain source provenance. A lower-trust conflict never overwrites a higher-trust value. Equal-trust conflicts retain the current value and create a review issue. Default imports merge additions. Explicit `replace_resume_source` mode retires facts supported only by the superseded resume when they disappear, but candidate-confirmed facts survive.

The service constructs a canonical JSON representation with stable key ordering and hashes it. If the semantic hash equals the current version, no profile version is created. Otherwise it writes a complete immutable relational snapshot and change set in one transaction. Historical versions and source records are never mutated.

### Validation

Validation is a pure service returning a Pydantic report with severity, code, entity reference, field, message, and suggested action. Checks include:

- missing or partial dates;
- end before start and overlapping/contradictory date claims;
- missing role, organization, contribution, or project descriptions;
- duplicate identity keys;
- profile skills with no evidence edge;
- proficiency without a candidate-confirmed source;
- ambiguous section/entity assignments;
- source fragments that could not be mapped;
- missing preference categories;
- invalid or unreachable-looking link syntax (without making network calls).

Warnings do not prevent profile creation. Structural database errors and invalid source files do.

## Evidence graph

The graph is relational, not a separate graph database:

```text
Candidate -> ProfileVersion -> ProfileSkill
                              |       |
                              |       +-- EvidenceEdge -- SourceFragment
                              |                 |
                              +---------- ProfileEntity
                                                |
                                      EntityStatement
```

An evidence edge includes a classification (`direct`, `partial`, `transferable`, `candidate_confirmed`, `unverified`, or `unknown`), an explanation of what the candidate did, a verification status, and exact source references. Classification describes relevance; verification describes trust; candidate-provided proficiency is a separate nullable field.

This supports future questions without adding ranking logic: “why is Python claimed?”, “which work demonstrates it?”, “is that direct or transferable?”, and “which source asserted it?”.

## Discovery contracts

```python
class JobConnector(ABC):
    connector_type: str

    @abstractmethod
    async def fetch(self, checkpoint: Checkpoint | None) -> AsyncIterator[ConnectorPage]: ...

    @abstractmethod
    def normalize(self, item: Mapping[str, Any], context: SourceContext) -> JobObservation: ...
```

`ConnectorPage` contains source items, a next checkpoint, response validators such as ETag/Last-Modified when supplied, and fetch metadata. `JobObservation` contains common fields plus `FieldObservation` entries that say whether each value was `source_stated`, `parser_extracted`, or `model_inferred`. This phase never emits `model_inferred` values.

Source implementations know URLs and payload schemas. The orchestration service alone owns transactions, deduplication, lifecycle, retries, and checkpoints.

### Initial connector behavior

- Greenhouse: fetch the public board jobs endpoint with `content=true`; use posting ID as source ID and retain internal job ID as metadata. The public list has no documented cursor, so unchanged response/job hashes prevent reprocessing.
- Lever: fetch JSON pages using `skip` and `limit`; support global and EU base URLs; use posting ID as source ID.
- Ashby: fetch the public job-board endpoint with compensation enabled; only listed, published jobs are persisted. The documented public payload has no separate job ID, so the normalized job URL is the source identity. The endpoint returns a full board response, so hashes provide incremental processing.

All requests use explicit connect/read/write/pool timeouts, a configured request interval, bounded response size, and HTTPS. Redirects are allowed only to HTTPS. Connector-provided HTML is retained as source data and converted to conservative plain text for search; it is never rendered by this backend.

### Reliability and checkpoints

- Retry network failures, HTTP 408, 429, and 5xx responses only.
- Respect `Retry-After`; otherwise use exponential backoff with bounded jitter.
- Attempt at most three times in a run, then create/update a durable retry record.
- Do not retry other 4xx responses until configuration changes.
- Commit normalized observations and the page checkpoint together.
- Update `last_attempted_at` before fetch and `last_successful_at` only after the source completes.
- Give each source run a database lease with an expiry; a crashed process can be recovered after the lease expires.
- Keep one source run transactionally independent from every other source.

SQLite runs in foreign-key mode with WAL, a busy timeout, and short transactions. One process may schedule concurrent HTTP fetches, but database writes are serialized. PostgreSQL can later allow more write concurrency without changing service contracts.

## Deduplication

Deduplication is explainable and conservative.

1. `(source_id, source_job_id)` updates the same source appearance.
2. An exact canonical application URL may merge when it contains a job-specific path or ID; generic company application URLs do not.
3. Otherwise score independent signals: normalized company, normalized title, normalized location set, description token similarity, and compatible posting dates.
4. Auto-merge only when at least two strong identity signals agree and no signal conflicts.
5. Flag intermediate confidence as `potential_duplicate` while preserving two canonical jobs.
6. Store every decision, signal, threshold version, outcome, and confidence.

URL normalization removes known tracking parameters and fragments, lowercases scheme/host, normalizes default ports and trailing slashes, and preserves meaningful path/query identifiers. Title similarity alone can never merge jobs. No embeddings or model calls are used.

Merging adds a source appearance to the surviving canonical job; it does not delete raw provenance. A later review can reverse the relationship because the source observations remain intact.

## Listing lifecycle

Canonical listing states are `discovered`, `active`, `potential_duplicate`, `expired`, `unavailable`, and `archived`. Every transition creates an event with reason, source, and timestamp.

- New observations start `discovered` and become `active` after successful persistence/validation.
- Explicit source closure or a confirmed 404/410 on a job-specific URL can make an appearance unavailable.
- A single timeout, 429, 5xx, or source-wide failure never expires a job.
- A job becomes `expired` only after all source appearances are explicitly closed/unavailable or after a configurable number of successful source checks omit it beyond a grace period.
- `archived` is a manual retention action, not an application status.

## Scheduling and manual execution

`DiscoveryService.run(source_ids)` is the only discovery entry point. The CLI calls it for manual runs. An APScheduler adapter invokes it on an interval in a long-lived worker. Schedules and run state live in application tables rather than the APScheduler job store, so restart behavior is derived from durable `next_due_at`, checkpoints, retry records, and source leases.

Initial CLI surface:

```text
brokej db upgrade
brokej profile ingest --candidate ID --resume PATH
brokej profile show --candidate ID [--version N]
brokej profile diff --candidate ID --from N --to N
brokej profile validate --candidate ID [--version N] --json
brokej discovery source add --type TYPE --name NAME --board BOARD
brokej discovery run [--source NAME]
brokej discovery worker
```

Commands return nonzero only for execution failures; validation warnings are returned in JSON and do not make ingestion fail.

## Logging, privacy, and security

Logs are structured JSON with run, connector, candidate, and source IDs. They exclude resume text, contact data, raw job bodies, credentials, and authorization headers. Exceptions are mapped to stable error codes at adapters.

Source files are copied atomically to content-addressed storage with restrictive permissions. Filenames supplied by users are metadata only, never storage paths. File size/page limits and path resolution prevent oversized-file and traversal issues. HTML is treated as untrusted text. SQLAlchemy parameters prevent SQL injection.

Backups consist of a consistent SQLite backup plus `data/sources`; a restore test will open the database, run integrity/foreign-key checks, and verify source checksums. Host-specific encryption and remote backup transport remain deployment decisions.

## Test strategy

Unit tests cover parsing, normalization, merge precedence, validation codes, source mappers, URL canonicalization, deduplication thresholds, lifecycle transitions, and retry classification.

Integration tests cover:

- Alembic upgrade from an empty file-backed SQLite database and downgrade to base.
- Supplied-resume ingestion, evidence traversal, no-op re-import, update/version diff, and confirmed-value protection.
- Greenhouse, Lever, and Ashby fixture pagination/normalization with `httpx.MockTransport`.
- One connector failing while others commit.
- Interrupted page processing and restart from the last committed checkpoint.
- Durable retry recovery and expired source leases.
- Repeated discovery preserving one canonical job and multiple provenance records.
- Database backup and restore integrity.

Tests never call live providers. A separate opt-in smoke command may be added later, but it cannot be part of the required suite or the claim that a connector works.

## Deliberate trade-offs

- Full immutable relational profile snapshots duplicate a modest amount of profile data, but make history, comparisons, rollback inspection, and deterministic reads simple.
- Public ATS endpoints often lack true incremental cursors. The implementation still fetches those small board payloads, then avoids reparsing unchanged responses/items via validators and hashes.
- SQLite supports the expected single-user workload. Repository and migration conventions avoid SQLite-only types so PostgreSQL remains a deployment change, not a domain rewrite.
- A relational evidence graph is sufficient for current traversal patterns and avoids a graph database.
- Conservative parsing creates review issues rather than an apparently complete but fabricated profile.
