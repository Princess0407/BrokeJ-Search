from __future__ import annotations

import json
from pathlib import Path


def test_benchmark_is_curated_and_complete(fixture_dir: Path) -> None:
    cases = json.loads((fixture_dir / "evaluation_benchmark.json").read_text())
    assert 30 <= len(cases) <= 50
    assert len({case["id"] for case in cases}) == len(cases)
    required = {
        "requirement_classification",
        "evidence_mapping",
        "eligibility",
        "qualification",
        "growth",
        "recommendation",
        "reasoning",
    }
    assert all(required <= case["expected"].keys() for case in cases)
    scenarios = " ".join(case["scenario"].casefold() for case in cases)
    for difficult_case in (
        "mandatory ml",
        "strong public implementation",
        "private repositories",
        "graduation eligibility",
        "dsa-heavy",
        "mathematical foundations",
        "keyword",
    ):
        assert difficult_case in scenarios
