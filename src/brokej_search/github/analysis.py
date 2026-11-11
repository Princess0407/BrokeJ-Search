from __future__ import annotations

import hashlib
import json
import re
from typing import Any

ANALYSIS_VERSION = "repository-v1"
_SOURCE_SUFFIXES = {".c", ".cpp", ".go", ".java", ".js", ".py", ".rs", ".ts"}
_MANIFESTS = {
    "cargo.toml",
    "go.mod",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
}


def analyze_repository(
    repository: dict[str, Any],
    tree_paths: list[str],
    selected_files: dict[str, str],
    readme: str | None,
) -> dict[str, Any]:
    """Analyze untrusted text as data; never execute or obey repository content."""
    paths = [path.casefold() for path in tree_paths]
    code_paths = [
        path for path in paths if any(path.endswith(suffix) for suffix in _SOURCE_SUFFIXES)
    ]
    has_tests = any(re.search(r"(^|/)(tests?|specs?)(/|$)", path) for path in paths)
    has_ci = any(path.startswith(".github/workflows/") for path in paths)
    manifests = [path for path in paths if path.rsplit("/", 1)[-1] in _MANIFESTS]
    has_docs = any(path.startswith("docs/") for path in paths)
    implementation = "\n".join(selected_files.values()).casefold()
    signals = {
        "code_file_count_observed": len(code_paths),
        "has_tests": has_tests,
        "has_ci": has_ci,
        "has_documentation": has_docs,
        "manifests": manifests[:20],
        "fastapi_implementation": bool(
            re.search(r"\bfastapi\s*\(|from\s+fastapi\b", implementation)
        ),
        "ml_pipeline_implementation": bool(
            re.search(r"\b(fit|predict|inference|training_loop|model\.train)\s*\(", implementation)
        ),
        "fork": bool(repository.get("fork")),
        "archived": bool(repository.get("archived")),
        "readme_present": bool(readme),
    }
    if repository.get("fork"):
        classification = "fork"
    elif not code_paths:
        classification = "documentation_only" if readme or has_docs else "no_meaningful_source"
    elif len(code_paths) < 3 and not has_tests and not manifests:
        classification = "prototype"
    else:
        classification = "substantial_implementation"
    confidence = 0.9 if tree_paths else 0.45
    fingerprint = hashlib.sha256(
        json.dumps(
            {"repository": repository.get("id"), "paths": paths, "signals": signals},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return {
        "analysis_version": ANALYSIS_VERSION,
        "source_hash": fingerprint,
        "purpose": repository.get("description") or (readme[:500] if readme else None),
        "classification": classification,
        "signals": signals,
        "confidence": confidence,
    }


def reconcile_claim(claim: str, analyses: list[dict[str, Any]]) -> tuple[str, str]:
    lower = claim.casefold()
    if not analyses:
        return (
            "unverified",
            "No public repository evidence was available; this does not disprove the claim.",
        )
    signal = (
        "fastapi_implementation"
        if "fastapi" in lower
        else "ml_pipeline_implementation"
        if re.search(r"\b(machine learning|ml |inference|training)\b", lower)
        else None
    )
    if signal and any(analysis.get("signals", {}).get(signal) for analysis in analyses):
        return "supported", f"Selected source files contain {signal.replace('_', ' ')} evidence."
    if signal and any(
        analysis.get("signals", {}).get("code_file_count_observed", 0) for analysis in analyses
    ):
        return (
            "partially_supported",
            "A public implementation exists, but the specific claim was not verified in "
            "selected files.",
        )
    return (
        "unverified",
        "Available public evidence does not establish this claim; private or other evidence "
        "may exist.",
    )
