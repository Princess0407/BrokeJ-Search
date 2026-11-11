# Agent handover

Last updated: 2026-11-11

## Project and current state

BrokeJ-Search is a local modular backend for versioned candidate profiles, evidence graphs, public ATS job discovery, and explainable job fit. Milestones 1–3 are implemented. Current branch is `main`; the Milestone 3 implementation commit is `87611dc` (local only). No push or remote mutation was made.

The current database revision is `0004` (`evidence_based_job_evaluation`). Migrations `0001`–`0003` are preserved; `0004` adds GitHub public evidence and evaluation records.

## Completed functionality

- Career profile ingestion, typed entities, immutable snapshots, separately versioned preferences, evidence graph, validation, and comparison.
- Greenhouse, Lever, and Ashby discovery with normalized jobs, source provenance, deduplication, checkpoints, retry state, scheduler, and FastAPI adapter.
- Deterministic job requirement decomposition with categories, criticality, source references, confidence, and uncertainty.
- Evaluation from profile evidence with direct/partial/transferable/self-reported/unverified/unknown/contradictory distinctions; separate current fit, eligibility, growth, interest, freshness, and evidence confidence.
- Deterministic recommendations and critic. Hard eligibility cannot be offset by other scores. Repeated assessment for a fixed profile/job/engine is idempotent.
- Optional candidate-authorized public GitHub sync, bounded REST inspection, repo/contribution metadata, analysis snapshots, ownership confirmation, rate-limit handling, and cache freshness. No code execution or private repo access.
- Resume project/work claims can be reconciled with available GitHub signals; candidates can override a classification and add explanatory notes.
- FastAPI exposes requirement extraction, candidate/job assessment, GitHub consent/disable, and claim reconciliation/correction routes.
- Thirty curated deterministic benchmark cases and methodology/results.

## Important modules

- `career_profile/service.py`: profile ingestion, snapshots, evidence lookup and validation.
- `discovery/service.py`: source orchestration and job persistence.
- `evaluation/requirements.py`: deterministic requirement extraction.
- `evaluation/service.py`: requirement evidence retrieval, eligibility, scoring, growth, critic, recommendations.
- `github/client.py`: public REST, pagination, retry, rate limits and conditional headers.
- `github/service.py`: candidate consent, sync/cache, repository and contribution persistence.
- `github/analysis.py`: bounded-source structural signals and conservative claim reconciliation helper.
- `database/models.py`: shared profile, discovery, GitHub, and evaluation records.

## Verification status at this checkpoint

Before Milestone 3, the report recorded 24 passing tests and 83% coverage. Current full suite: 44 passed, 0 skipped, 86% coverage (2,768 statements). Ruff lint and formatting passed; mypy passed for 36 source files. Migration integration coverage upgrades through `0004` and downgrades to base. API tests invoke registered route handlers directly because Starlette `TestClient` hung in this Python 3.14 environment; HTTP dispatch is not exercised by those tests.

No live GitHub or job-board requests were made. PostgreSQL behavior remains untested. Git identity is configured (`BrokeJ-Search Local`, `local@brokej-search.invalid`).

## Constraints and limitations

- Do not rewrite migrations `0001`–`0004`; use a new migration.
- No OAuth/private GitHub, application submission, resume tailoring, notifications, or UI in this milestone.
- GitHub REST search and repository inspection are bounded; API attribution does not establish authorship of all code.
- Resume-to-GitHub reconciliation is conservative and phrase-limited; it cannot verify scale or authorship by itself.
- Evaluation is a deterministic heuristic. The 30/30 benchmark result measures consistency with authored labels, not universal accuracy or calibration.
- Unknown authorization/location stays unknown; only explicit graduation/degree/dated-experience checks are currently evaluated as candidate data permits.

## Exact next action

Start with `git status --short --branch` and `git log -1`. Then independently review eligibility/evidence heuristics and expand independently labeled benchmark cases before threshold calibration. Do not add application automation or private GitHub access as part of that review.

## Resume commands

```sh
.venv/bin/alembic upgrade head
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy src
git status --short --branch
```
