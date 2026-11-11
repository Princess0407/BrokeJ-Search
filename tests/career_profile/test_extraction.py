from pathlib import Path

import pytest

from brokej_search.career_profile.extraction import PdfDocumentExtractor
from brokej_search.career_profile.parser import DeterministicResumeParser
from brokej_search.core.exceptions import InvalidDocumentError


def test_pdf_extraction_and_sections(resume_path: Path) -> None:
    document = PdfDocumentExtractor().extract(resume_path)
    profile = DeterministicResumeParser().parse(document)
    assert document.page_count == 1
    assert any("provtrack" in link.url for link in document.links)
    assert {entity.entity_type for entity in profile.entities} == {
        "experience",
        "project",
        "education",
        "contribution",
        "achievement",
    }
    assert len([entity for entity in profile.entities if entity.entity_type == "project"]) == 2
    assert all(profile.email not in issue.values() for issue in profile.issues if profile.email)


def test_invalid_pdf_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "not.pdf"
    source.write_text("not a pdf")
    with pytest.raises(InvalidDocumentError):
        PdfDocumentExtractor().extract(source)
