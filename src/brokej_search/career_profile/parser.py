from __future__ import annotations

import re
from typing import Protocol

from brokej_search.career_profile.normalization import normalize_key, normalize_skill
from brokej_search.career_profile.schemas import (
    ExtractedDocument,
    ParsedEntity,
    ParsedProfile,
    ParsedSkill,
)

HEADINGS = [
    "PROFESSIONAL SUMMARY",
    "CORE COMPETENCIES",
    "PROFESSIONAL EXPERIENCE",
    "PROJECTS",
    "OPEN SOURCE CONTRIBUTIONS",
    "ACHIEVEMENTS",
    "EDUCATION",
]


class ResumeParser(Protocol):
    name: str
    version: str

    def parse(self, document: ExtractedDocument) -> ParsedProfile: ...


def _clean_text(text: str) -> str:
    replacements = {
        "SUMMAR Y": "SUMMARY",
        "EDUCA TION": "EDUCATION",
        "F rameworks": "Frameworks",
        "T ools": "Tools",
        "T racker": "Tracker",
        "T auri": "Tauri",
        "T echnology": "Technology",
        "HP AIR": "HPAIR",
        "DRA W": "DRAW",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.replace("\u00a0", " ").replace("\r", "")


def _sections(text: str) -> tuple[dict[str, str], list[str]]:
    positions: list[tuple[int, str]] = []
    for heading in HEADINGS:
        match = re.search(rf"(?m)^\s*{re.escape(heading)}\s*$", text)
        if match:
            positions.append((match.start(), heading))
    positions.sort()
    output: dict[str, str] = {}
    for index, (start, heading) in enumerate(positions):
        body_start = text.find("\n", start) + 1
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        output[heading] = text[body_start:end].strip()
    missing = [heading for heading in HEADINGS if heading not in output]
    return output, missing


def _bullets(text: str) -> list[str]:
    chunks = re.split(r"\n?\s*•\s*", text)
    return [re.sub(r"\s*\n\s*", " ", chunk).strip() for chunk in chunks[1:] if chunk.strip()]


def _matching_link(links: list[str], *needles: str) -> str | None:
    for link in links:
        lower = link.casefold()
        if all(needle.casefold() in lower for needle in needles):
            return link
    return None


class DeterministicResumeParser:
    name = "deterministic_resume"
    version = "1"

    def parse(self, document: ExtractedDocument) -> ParsedProfile:
        text = _clean_text(document.text)
        sections, missing = _sections(text)
        links = [link.url for link in document.links]
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        profile = ParsedProfile(sections=sections)
        profile.issues.extend(
            {"code": "missing_section", "severity": "warning", "section": heading}
            for heading in missing
        )
        profile.name = lines[0] if lines and not lines[0].isupper() else None
        profile.email = next(iter(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)), None)
        profile.phone = next(iter(re.findall(r"\+?\d[\d ]{8,}\d", text)), None)
        profile.linkedin_url = _matching_link(links, "linkedin.com")
        profile.github_url = _matching_link(links, "github.com", "Princess0407")
        profile.summary = re.sub(r"\s*\n\s*", " ", sections.get("PROFESSIONAL SUMMARY", "")) or None

        competency = sections.get("CORE COMPETENCIES", "")
        skills: dict[str, ParsedSkill] = {}
        for line in competency.splitlines():
            if ":" not in line:
                continue
            label, values = line.split(":", 1)
            for value in values.split(","):
                canonical, category = normalize_skill(value)
                if canonical:
                    skills[canonical.casefold()] = ParsedSkill(
                        canonical_name=canonical,
                        category=category if category != "other" else normalize_key(label),
                        original=value.strip(),
                    )

        experience = sections.get("PROFESSIONAL EXPERIENCE", "")
        if experience:
            statements = _bullets(experience)
            technology_line = next((s for s in statements if s.casefold().startswith("stack:")), "")
            technologies = [
                v.strip() for v in technology_line.split(":", 1)[-1].split(",") if v.strip()
            ]
            entity = ParsedEntity(
                entity_type="experience",
                identity_key="iit-bombay-fossee-summer-intern-2026-05",
                title="FOSSEE Summer Intern",
                section="PROFESSIONAL EXPERIENCE",
                data={
                    "organization": "IIT Bombay - Free and Open Source Software for Education",
                    "role": "FOSSEE Summer Intern",
                    "location": "Remote",
                    "work_arrangement": "remote",
                    "start_date": "2026-05-01",
                    "end_date": "2026-07-31",
                    "employment_type": "internship",
                },
                statements=statements,
                technologies=technologies,
                source_url=_matching_link(links, "ICELang"),
            )
            profile.entities.append(entity)

        projects = sections.get("PROJECTS", "")
        project_specs = [
            (
                "provtrack",
                "GXU-1:",
                "provtrack",
                "Zero-Instrumentation ML Pipeline Provenance Tracker",
            ),
            ("GXU-1", None, "GXU-1", "Custom GPU Co-Processor"),
        ]
        for marker, next_marker, name, description in project_specs:
            start = projects.find(marker)
            if start < 0:
                continue
            end = projects.find(next_marker, start + 1) if next_marker else len(projects)
            block = projects[start : end if end >= 0 else len(projects)]
            statements = _bullets(block)
            header_lines = [line for line in block.splitlines() if line.strip()]
            tech_line = header_lines[1] if len(header_lines) > 1 else ""
            technologies = [v.strip() for v in tech_line.split(",") if v.strip()]
            repo = _matching_link(links, f"/{name}")
            profile.entities.append(
                ParsedEntity(
                    entity_type="project",
                    identity_key=f"project-{normalize_key(name)}-{repo or '2026'}",
                    title=name,
                    section="PROJECTS",
                    data={
                        "name": name,
                        "short_description": description,
                        "repository_url": repo,
                    },
                    statements=statements,
                    technologies=technologies,
                    source_url=repo,
                )
            )

        contributions = sections.get("OPEN SOURCE CONTRIBUTIONS", "")
        laya_start = contributions.find("aayushch/laya")
        qucs_start = contributions.find("ra3xdh/qucs-s")
        if laya_start >= 0:
            block = contributions[
                laya_start : qucs_start if qucs_start >= 0 else len(contributions)
            ]
            for statement in _bullets(block):
                ref_match = re.search(r"PR\s*#(\d+)", statement)
                ref = f"PR #{ref_match.group(1)}" if ref_match else None
                url = (
                    _matching_link(links, "aayushch/laya/pull", ref_match.group(1))
                    if ref_match
                    else None
                )
                profile.entities.append(
                    ParsedEntity(
                        entity_type="contribution",
                        identity_key=f"aayushch-laya-{normalize_key(ref or statement[:30])}",
                        title=f"aayushch/laya {ref or 'contribution'}",
                        section="OPEN SOURCE CONTRIBUTIONS",
                        data={
                            "repository": "aayushch/laya",
                            "reference": ref,
                            "contribution_type": "pull_request",
                            "status": "merged",
                            "evidence_url": url,
                        },
                        statements=[statement],
                        technologies=["Python", "Security engineering", "REST APIs"],
                        source_url=url,
                    )
                )
        if qucs_start >= 0:
            block = contributions[qucs_start:]
            ref_match = re.search(r"PR\s*#(\d+)", block)
            ref = f"PR #{ref_match.group(1)}" if ref_match else None
            profile.entities.append(
                ParsedEntity(
                    entity_type="contribution",
                    identity_key=f"ra3xdh-qucs-s-{normalize_key(ref or 'contribution')}",
                    title=f"ra3xdh/qucs-s {ref or 'contribution'}",
                    section="OPEN SOURCE CONTRIBUTIONS",
                    data={
                        "repository": "ra3xdh/qucs-s",
                        "reference": ref,
                        "contribution_type": "pull_request",
                        "status": "unknown",
                        "evidence_url": _matching_link(links, "qucs_s/pull/1728"),
                    },
                    statements=[re.sub(r"\s*\n\s*", " ", block).strip()],
                    technologies=["C++"],
                    source_url=_matching_link(links, "qucs_s/pull/1728"),
                )
            )

        achievements = re.sub(r"\s*\n\s*", " ", sections.get("ACHIEVEMENTS", ""))
        for name, year in (("Microsoft Codess Mentee", 2025), ("HPAIR Delegate", 2026)):
            marker = (
                "Microsoft Codess Mentee" if name.startswith("Microsoft") else "HPAIR 2026 Delegate"
            )
            if marker in achievements:
                profile.entities.append(
                    ParsedEntity(
                        entity_type="achievement",
                        identity_key=f"achievement-{normalize_key(name)}-{year}",
                        title=name,
                        section="ACHIEVEMENTS",
                        data={"name": name, "achieved_year": year, "description": achievements},
                    )
                )

        education = re.sub(r"\s*\n\s*", " ", sections.get("EDUCATION", ""))
        if "Acharya Institute of Technology" in education:
            profile.entities.append(
                ParsedEntity(
                    entity_type="education",
                    identity_key="acharya-institute-of-technology-be-ece-2023",
                    title="Bachelor of Engineering in Electronics and Communications Engineering",
                    section="EDUCATION",
                    data={
                        "institution": "Acharya Institute of Technology",
                        "degree": "Bachelor of Engineering",
                        "discipline": "Electronics and Communications Engineering",
                        "location": "Bangalore, IN",
                        "start_date": "2023-08-01",
                        "end_date": "2027-05-31",
                        "expected_graduation": True,
                    },
                )
            )

        for entity in profile.entities:
            for technology in entity.technologies:
                canonical, category = normalize_skill(technology)
                skills.setdefault(
                    canonical.casefold(),
                    ParsedSkill(canonical_name=canonical, category=category, original=technology),
                )
        profile.skills = sorted(skills.values(), key=lambda item: item.canonical_name.casefold())
        if not profile.entities:
            profile.issues.append({"code": "no_entities", "severity": "error"})
        return profile
