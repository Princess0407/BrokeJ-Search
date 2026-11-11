from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader

from brokej_search.career_profile.schemas import ExtractedDocument, ExtractedLink
from brokej_search.core.exceptions import InvalidDocumentError


class DocumentExtractor(Protocol):
    name: str
    version: str

    def extract(self, path: Path) -> ExtractedDocument: ...


class PdfDocumentExtractor:
    name = "pypdf"
    version = "1"

    def __init__(self, max_bytes: int = 10_000_000, max_pages: int = 20) -> None:
        self.max_bytes = max_bytes
        self.max_pages = max_pages

    def extract(self, path: Path) -> ExtractedDocument:
        path = path.resolve(strict=True)
        raw = path.read_bytes()
        if not raw.startswith(b"%PDF-"):
            raise InvalidDocumentError("The uploaded file is not a PDF")
        if len(raw) > self.max_bytes:
            raise InvalidDocumentError("PDF exceeds the configured size limit")
        try:
            reader = PdfReader(path)
        except Exception as exc:
            raise InvalidDocumentError("PDF could not be parsed") from exc
        if reader.is_encrypted:
            raise InvalidDocumentError("Encrypted PDFs are not supported")
        if len(reader.pages) > self.max_pages:
            raise InvalidDocumentError("PDF exceeds the configured page limit")

        pages: list[str] = []
        links: list[ExtractedLink] = []
        warnings: list[str] = []
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(text)
            for annotation_ref in page.get("/Annots", []):
                try:
                    annotation = annotation_ref.get_object()
                    action = annotation.get("/A")
                    uri = action.get("/URI") if action else None
                    if uri:
                        links.append(ExtractedLink(url=str(uri), page_number=number))
                except (AttributeError, TypeError, KeyError):
                    warnings.append(f"Unreadable link annotation on page {number}")
        combined = "\n\f\n".join(pages).strip()
        if not combined:
            raise InvalidDocumentError("PDF contains no extractable text; OCR is required")
        return ExtractedDocument(
            text=combined,
            pages=pages,
            links=links,
            page_count=len(pages),
            sha256=hashlib.sha256(raw).hexdigest(),
            byte_size=len(raw),
            warnings=warnings,
        )
