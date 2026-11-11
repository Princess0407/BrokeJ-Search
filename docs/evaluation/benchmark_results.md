# Benchmark results

Run date: 2026-11-11  
Benchmark: `benchmark-v1` (30 curated deterministic cases)  
Engine: `evaluation-v1`

## Results

| Metric | Result | Scope |
| --- | ---: | --- |
| Curated cases present | 30 | Fixture validation |
| Expected recommendation labels matched | 30/30 (100%) | Deterministic seeded integration run |
| Live GitHub requests | 0 | GitHub behavior is mocked |
| False-positive qualification rate | Not measured | No independent population sample |
| False-negative rejection rate | Not measured | No independent population sample |
| Requirement extraction precision/recall | Not measured | Gold labels are fixture expectations, not independent annotations |
| Evidence attribution accuracy | Not measured | No separately adjudicated attribution set |
| Confidence calibration | Not measured | 30 cases are insufficient and labels are not probabilistic |

Cases cover backend/ML mismatch, transferable foundations, GitHub and resume evidence, unavailable private work, preferred gaps, ambiguous descriptions, DSA, mathematical foundations, explicit hard gates, and no-evidence cases. Every case stores component expectations and rationale; the executable integration assertion currently checks exact recommendation consistency.

The result means that the current deterministic engine reproduces these authored expectations. It does not establish general candidate-ranking accuracy, fairness, or suitability for automated hiring decisions. Do not use it as an application decision without human review.

Reproduce with:

```sh
.venv/bin/pytest -q tests/integration/test_evaluation.py::test_curated_benchmark_recommendations tests/evaluation/test_benchmark.py
```
