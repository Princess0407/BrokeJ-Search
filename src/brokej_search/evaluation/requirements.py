from __future__ import annotations

import hashlib
import re

from brokej_search.career_profile.normalization import SKILL_ALIASES, normalize_skill
from brokej_search.evaluation.schemas import JobRequirementData, RequirementSource

EXTRACTOR_VERSION = "deterministic-v1"

_LANGUAGES = {
    "c",
    "c++",
    "go",
    "java",
    "javascript",
    "kotlin",
    "python",
    "rust",
    "sql",
    "typescript",
}
_TOOLS = {
    "aws",
    "docker",
    "fastapi",
    "flask",
    "git",
    "kubernetes",
    "linux",
    "pytorch",
    "react",
    "scikit-learn",
    "tensorflow",
}
_ARCHITECTURE = {
    "distributed systems",
    "machine learning",
    "microservices",
    "ml inference",
    "model serving",
    "system design",
}
_COMPETENCIES = sorted(
    set(SKILL_ALIASES) | _LANGUAGES | _TOOLS | _ARCHITECTURE,
    key=len,
    reverse=True,
)
_CANONICAL = {
    "distributed systems": "Distributed Systems",
    "machine learning": "Machine Learning",
    "microservices": "Microservices",
    "ml inference": "ML Inference",
    "model serving": "Model Serving",
    "system design": "System Design",
}
_REQUIREMENT_SIGNAL = re.compile(
    r"\b(required|requirements?|must|should|preferred|nice to have|experience|"
    r"proficien|knowledge|familiar|degree|graduat|authori[sz]|eligible|location|"
    r"remote|hybrid|onsite|responsib|build|design|develop|maintain|train(?:ing|able)?)\b",
    re.I,
)


class RequirementDecomposer:
    """Conservative deterministic extraction; ambiguous text stays ambiguous."""

    version = EXTRACTOR_VERSION

    def decompose(self, source: RequirementSource) -> list[JobRequirementData]:
        candidates: list[tuple[str, str, str | None]] = []
        candidates.extend(
            (skill, f"required_skills:{index}", "required")
            for index, skill in enumerate(source.required_skills)
        )
        candidates.extend(
            (skill, f"preferred_skills:{index}", "preferred")
            for index, skill in enumerate(source.preferred_skills)
        )
        for field, value in (
            ("experience_requirements", source.experience_requirements),
            ("education_requirements", source.education_requirements),
            ("graduation_year_restrictions", source.graduation_year_restrictions),
        ):
            if value and value.strip():
                candidates.append((value.strip(), field, "required"))
        for index, text in enumerate(self._description_units(source.description)):
            if _REQUIREMENT_SIGNAL.search(text):
                candidates.append((text, f"description:{index}", None))
        if source.work_arrangement != "unknown":
            candidates.append((source.work_arrangement, "work_arrangement", None))
        candidates.extend(
            (location, f"locations:{index}", None)
            for index, location in enumerate(source.locations)
        )

        results: list[JobRequirementData] = []
        seen: set[tuple[str, str]] = set()
        for text, reference, stated_level in candidates:
            normalized_text = re.sub(r"\s+", " ", text).strip(" -•\t")
            if not normalized_text:
                continue
            category, competency = self._classify(normalized_text, reference)
            key = (normalized_text.casefold(), category)
            if key in seen:
                continue
            seen.add(key)
            criticality, mandatory = self._criticality(normalized_text, category, stated_level)
            requirement_id = hashlib.sha256(
                f"{reference}\0{normalized_text}\0{category}".encode()
            ).hexdigest()[:24]
            results.append(
                JobRequirementData(
                    id=requirement_id,
                    original_text=normalized_text,
                    normalized_competency=competency,
                    category=category,
                    criticality=criticality,
                    mandatory_status=mandatory,
                    evidence_expected=self._expected_evidence(category),
                    extraction_confidence=0.98 if stated_level else 0.78,
                    source_reference=reference,
                )
            )
        return results

    @staticmethod
    def _description_units(description: str) -> list[str]:
        if not description or not description.strip():
            return []
        return [
            unit.strip()
            for unit in re.split(r"(?:\r?\n|(?<=[.!?;])\s+)", description)
            if unit.strip()
        ]

    @staticmethod
    def _classify(text: str, reference: str) -> tuple[str, str | None]:
        lower = text.casefold()
        if "authoriz" in lower or "sponsor" in lower or "right to work" in lower:
            return "work_authorization", None
        if "graduat" in lower or "class of" in lower:
            return "graduation_eligibility", None
        if "degree" in lower or "bachelor" in lower or "master" in lower or "phd" in lower:
            return "education", None
        if reference == "work_arrangement" or any(
            word in lower for word in ("remote", "hybrid", "onsite", "on-site", "relocat")
        ):
            return "location_work_arrangement", text
        if reference.startswith("locations:"):
            return "location_work_arrangement", text
        if re.search(r"\b\d+\+?\s*(?:years?|yrs?)\b", lower) or "experience" in lower:
            competency = RequirementDecomposer._competency(lower)
            return "experience", competency
        competency = RequirementDecomposer._competency(lower)
        if competency:
            folded = competency.casefold()
            if folded in _LANGUAGES:
                return "programming_language", competency
            if folded in _TOOLS:
                return "framework_tool", competency
            if folded in _ARCHITECTURE:
                return "system_design_architecture", competency
            return "technical_skill", competency
        if reference.startswith(("required_skills:", "preferred_skills:")):
            return "technical_skill", normalize_skill(text)[0]
        if any(word in lower for word in ("build", "design", "develop", "maintain", "responsib")):
            return "responsibility", text
        return "other_eligibility", None

    @staticmethod
    def _competency(lower_text: str) -> str | None:
        for value in _COMPETENCIES:
            if re.search(rf"(?<![\w+.-]){re.escape(value)}(?![\w+.-])", lower_text):
                return _CANONICAL.get(value, normalize_skill(value)[0])
        return None

    @staticmethod
    def _criticality(text: str, category: str, stated: str | None) -> tuple[str, str]:
        lower = text.casefold()
        if stated == "preferred" or re.search(r"\b(preferred|nice to have|bonus)\b", lower):
            return "preferred", "preferred"
        if re.search(r"\b(willing to learn|can be learned|training provided|trainable)\b", lower):
            return "trainable", "unknown"
        eligibility = category in {
            "education",
            "graduation_eligibility",
            "work_authorization",
            "location_work_arrangement",
            "other_eligibility",
        }
        explicit = stated == "required" or bool(
            re.search(r"\b(required|must|only|minimum)\b", lower)
        )
        if (
            category == "experience"
            and explicit
            and re.search(r"\b\d+\+?\s*(?:years?|yrs?)\b", lower)
        ):
            return "hard_eligibility", "mandatory"
        if eligibility and explicit:
            return "hard_eligibility", "mandatory"
        if stated == "required":
            return "core_mandatory", "mandatory"
        if explicit and category in {
            "technical_skill",
            "programming_language",
            "framework_tool",
            "system_design_architecture",
            "experience",
        }:
            return "core_mandatory", "mandatory"
        if explicit:
            return "mandatory_but_ambiguous", "mandatory"
        if category == "responsibility":
            return "mandatory_but_ambiguous", "unknown"
        return "unknown", "unknown"

    @staticmethod
    def _expected_evidence(category: str) -> list[str]:
        if category in {
            "technical_skill",
            "programming_language",
            "framework_tool",
            "system_design_architecture",
        }:
            return ["implemented project", "professional work", "reviewed contribution"]
        if category == "responsibility":
            return ["experience statement", "project outcome"]
        if category == "experience":
            return ["dated professional experience"]
        if category in {"education", "graduation_eligibility"}:
            return ["education record"]
        return ["candidate-confirmed eligibility"]
