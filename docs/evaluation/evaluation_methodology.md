# Evaluation methodology

Version: benchmark-v1 / evaluation-v1  
Date: 2026-11-11

## Unit under evaluation

One case pairs structured candidate facts with one normalized job. A case records intended requirement criticality, evidence mapping, eligibility, current qualification, growth, recommendation, and rationale in `tests/fixtures/evaluation_benchmark.json`. The fixture is local and deterministic; ordinary tests make no GitHub or job-board requests.

The 30 cases cover backend versus mandatory ML, foundational ML without inference depth, strong public GitHub evidence, resume-only claims, private/unavailable repositories, transferable skills, graduation failure, preferred gaps, ambiguous requirements, DSA-heavy roles, keyword overlap, mathematical research foundations, authorization/location unknowns, experience and degree gates, training, prototypes, empty descriptions, and misleading README claims.

## Scoring semantics

Each requirement is checked against typed evidence. Direct evidence counts as 1.0; partial 0.65; transferable 0.45; self-reported 0.35; unverified 0.15; unknown and contradictory 0. Preferred requirements have one-quarter weight in technical fit. Unknown/ambiguous and trainable requirements receive half weight. Other core requirements receive full weight. This is a transparent engineering heuristic, not a calibrated probability.

Hard eligibility is assessed separately. Failed eligibility produces `ineligible`; unknown eligibility produces `manual_review`. Current qualification and growth potential are distinct. Adjacent foundations can inform growth without satisfying the target requirement.

The rule-based critic checks unresolved eligibility, ambiguous mandatory statements, unsupported core conclusions, and GitHub attribution uncertainty. It cannot invent facts.

## Metrics

The current executable benchmark asserts exact recommendation consistency across all 30 fixtures. The recorded result is 30/30 expected labels (100% fixture consistency). This is an in-sample regression check, not an estimate of real-world recommendation accuracy.

False-positive qualification, false-negative rejection, requirement extraction precision/recall, evidence-attribution accuracy, eligibility accuracy across a representative population, and confidence calibration are not yet statistically measured. Their labels need independent review and broader examples before those metrics are meaningful. The fixture contains expected component fields to support that next step, but the current integration runner specifically asserts the outcome label.

## Limitations

- The benchmark is hand-authored and small; it may reflect implementation assumptions.
- Requirement decomposition is deterministic and misses implicit phrasing.
- Evaluation is heuristic and does not use an employer-specific rubric.
- The seeded benchmark scenarios encode expected labels but do not contain full resumes, full job descriptions, or reviewer adjudication.
- GitHub API integration is mocked in tests; live service behavior and rate limits are not verified here.
- GitHub evidence is opt-in and public-only. Private/confidential work is absent by design.
- No confidence calibration claim is made from 30 examples.

## Running

```sh
.venv/bin/pytest -q tests/evaluation tests/integration/test_evaluation.py
```
