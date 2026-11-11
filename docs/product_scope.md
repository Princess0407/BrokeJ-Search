# Product scope

Status: implementation baseline for Milestones 1 and 2
Last reviewed: 2026-11-11

## Purpose

BrokeJ-Search is a resume-first backend that preserves a candidate's career facts and the evidence for them, then collects job listings from permitted sources into a durable, source-traceable store. This phase builds the foundation for later reasoning and application assistance; it does not decide whether a job is a good fit.

The backend is a modular monolith. Its service layer is the product boundary. A command-line adapter, a scheduled worker, and future HTTP, TUI, and GUI clients must all call the same services rather than reimplement business rules.

## Milestone 1 outcomes

Milestone 1 will provide:

- A versioned candidate profile with separate education, employment/internship, project, open-source contribution, achievement, skill, and preference records.
- Evidence edges that explain which work item demonstrates a skill, what the candidate did, which source supports it, and how the evidence is classified.
- Conservative PDF resume ingestion with source locations, extraction status, ambiguity reporting, and pluggable extraction/parser interfaces.
- Canonical skill names and aliases without inferring proficiency from keyword frequency.
- Deterministic, idempotent updates that preserve older versions and never replace candidate-confirmed data with lower-trust extraction.
- Machine-readable completeness and consistency reports that do not block incomplete profiles.
- Read/update service interfaces usable without a frontend.
- An example profile produced from the supplied resume.

## Milestone 2 outcomes

Milestone 2 will provide:

- A connector contract and working Greenhouse, Lever, and Ashby public-job-board connectors tested against saved fixtures.
- A common job schema that preserves original descriptions, source snapshots, source-specific fields, and field-level origin.
- Canonical jobs with one or more source appearances.
- Conservative deterministic deduplication, including a review state for uncertain matches.
- Durable source checkpoints, run history, retry records, rate limiting, and per-source failure isolation.
- Listing lifecycle state and events, distinct from future application state.
- Manual and recurring discovery through the same discovery service.
- Restart-safe persistence in SQLite, with SQLAlchemy models kept portable to PostgreSQL.

## Initial candidate facts and trust boundary

`Resume-5.pdf` is the initial source document. It is not independent verification. Facts extracted from it are stored with `resume_extracted` verification status unless the candidate later confirms them or an external source is deliberately verified.

The initial profile may represent these resume-backed areas:

- Priyanka Tiwari, an Electronics and Communications Engineering undergraduate at Acharya Institute of Technology, with an expected graduation in May 2027.
- A FOSSEE Summer Intern role at IIT Bombay from May through July 2026, associated with ICELang.
- The provtrack and GXU-1 projects.
- Contributions to `aayushch/laya` and `ra3xdh/qucs_s`.
- Microsoft Codess Mentee 2025 and HPAIR 2026 Delegate achievements.
- Technologies explicitly listed in the resume's competency and work sections.

The PDF also contains repository and pull-request hyperlinks. They are retained as resume-provided evidence links; the ingestion step does not imply that their contents or merge status have been independently checked.

Resume claims such as coverage, performance, accuracy, selection rank, pull-request status, and impact remain verbatim source claims with traceability. They are not promoted to independently verified facts.

Contact details are private profile data. Documentation and test assertions should avoid repeating their literal values. Logs must never contain source text, contact fields, API tokens, or full raw job payloads.

## Career preferences represented initially

Confirmed from the implementation brief:

- Target role families: ML Infrastructure Engineering, Inference Engineering, DevOps / Platform Engineering, Backend / Software Engineering, AI Systems Engineering, Embedded ML / Edge AI, and ML Research Internships.
- Interest areas: ML infrastructure/tooling, model serving/inference, AI and agent infrastructure, backend/distributed systems, developer tooling, platform engineering, ML systems, and edge AI.
- Blockchain and Web3 should not be prioritized.
- Compiler and low-level systems roles should not be prioritized merely because supporting experience exists; that experience remains usable as transferable evidence.
- Primarily competitive-programming or algorithm-interview-focused roles should be excluded. A routine mention of algorithms or problem solving is not sufficient for exclusion.

Explicitly unknown until the candidate supplies them:

- Which of internship, full-time, and research opportunities are currently acceptable and their relative priority.
- Remote, hybrid, and onsite constraints.
- Geographic restrictions and relocation willingness.
- Minimum compensation and currency/period.
- Work authorization, sponsorship, and other eligibility.
- Maximum acceptable experience requirements.
- Deadline preferences and availability/start date.
- Academic metrics not present in the resume.

Unknown values are stored as unknown, surfaced by validation, and never guessed by discovery connectors.

## User-visible behavior

### Profile ingestion

1. The caller submits a candidate ID and a PDF path.
2. The service validates the file, stores a content-addressed source copy, extracts text and links, and records extraction diagnostics.
3. The parser emits proposed facts with source fragments and verification status.
4. The merge service applies deterministic trust and identity rules.
5. If the semantic profile is unchanged, the service returns the existing current version and records the no-op ingestion run.
6. If it changed, the service writes one immutable new profile version and a change set in one transaction.
7. Validation returns a report even when the profile is incomplete.

### Discovery

1. The caller selects configured sources or all enabled sources.
2. The service obtains a source lease so two runs cannot overlap for that source.
3. Each connector fetches public listings under its own timeout, rate, retry, and pagination rules.
4. Listings are normalized without guessing missing fields, then upserted with their raw source snapshots.
5. Exact and high-confidence duplicates may join one canonical job; lower-confidence candidates become `potential_duplicate` and remain separate.
6. A connector failure is recorded and scheduled for retry without rolling back successful connectors.
7. Source checkpoints advance only after the corresponding page or response is committed.

## Non-goals

This phase will not implement:

- Job-fit scoring, ranking, recommendations, or candidate-to-job matching.
- Embeddings, a vector database, or an LLM dependency.
- Resume tailoring, LaTeX generation, or application question answering.
- Application submission, application tracking, or application-status fields on job listings.
- Telegram or other notifications and digests.
- A TUI, GUI, dashboard, or frontend-specific business rules.
- CAPTCHA solving, authenticated-site scraping, anti-bot bypasses, or collection forbidden by source terms.
- LinkedIn, Indeed, Wellfound, X/Twitter, or YC scraping in the initial implementation.
- Microservices, message brokers, distributed queues, or multi-candidate tenancy controls beyond clean candidate IDs.

## Acceptance criteria

Milestone 1 is accepted when the supplied PDF produces the expected entity categories, every claimed skill has either an evidence edge or a validation issue, the same PDF is a semantic no-op on re-import, confirmed facts survive lower-trust imports, versions can be compared, and all profile tests pass.

Milestone 2 is accepted when the three initial ATS connectors parse realistic saved fixtures, repeated runs update provenance without duplicating jobs, a failed connector does not block the others, retry and restart behavior is deterministic, lifecycle transitions require positive evidence or repeated checks, and all discovery and migration tests pass.

## Decisions that remain intentionally open

- Candidate confirmation is needed for the unknown preferences listed above.
- Deployment provider, backup destination, retention period, and encryption-at-rest mechanism depend on the eventual host.
- An externally reachable HTTP API needs an authentication decision. Until then, the implementation will expose services and CLI commands, and any development API will bind to loopback only.
- Companies/boards to poll must be configured; the system will not crawl the web to discover arbitrary ATS board identifiers in this phase.
- Repository verification can be added as a separate, explicit source importer later. Resume hyperlinks alone are not authorization to crawl or infer additional facts.
