"""Document persistence and text extraction, with optional Azure Document Intelligence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings
from .file_utils import relative_to_project, stable_stem, versioned_path

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    document_name: str
    source_file_path: str
    document_type: str
    content_hash: str
    upload_timestamp: str
    extracted_text_path: str
    processing_status: str = "text_extracted"

    def as_dict(self) -> dict[str, str]:
        """Return only fields defined by the extraction JSON document contract."""
        return {
            "document_id": self.document_id,
            "document_name": self.document_name,
            "source_file_path": self.source_file_path,
            "document_type": self.document_type,
            "content_hash": self.content_hash,
            "upload_timestamp": self.upload_timestamp,
            "extracted_text_path": self.extracted_text_path,
        }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def save_uploaded_document(
    filename: str, content: bytes, settings: Settings, *, allow_versioning: bool = True
) -> Path:
    """Persist uploaded bytes under the repository using a sanitized stable name."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported document type: {suffix or '<none>'}")
    destination = settings.source_documents_dir / f"{stable_stem(filename)}{suffix}"
    if allow_versioning:
        destination = versioned_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return destination


def _read_local(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - target dependency
            raise RuntimeError("pypdf is required for local PDF extraction") from exc
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError as exc:  # pragma: no cover - target dependency
            raise RuntimeError("python-docx is required for local DOCX extraction") from exc
        return "\n".join(paragraph.text for paragraph in Document(path).paragraphs)
    raise ValueError(f"Unsupported document type: {suffix}")


def _read_with_document_intelligence(content: bytes, endpoint: str) -> str:
    """Extract structure-preserving Markdown using Azure Document Intelligence.

    Markdown output (``output_content_format=MARKDOWN``) keeps headings, tables, and page anchors
    (``<!-- PageNumber -->`` / ``<!-- PageBreak -->``) so the LLM can cite the section and page each
    rule comes from. Microsoft recommends Markdown for LLM/RAG consumption of the layout model.
    """
    if not endpoint:
        raise ValueError("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT is required")
    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.ai.documentintelligence.models import (
            AnalyzeDocumentRequest,
            DocumentContentFormat,
        )
    except ImportError as exc:  # pragma: no cover - target dependency
        raise RuntimeError("Azure Document Intelligence dependencies are not installed") from exc

    from .azure_auth import get_azure_credential

    credential = get_azure_credential()
    client = DocumentIntelligenceClient(endpoint=endpoint, credential=credential)
    poller = client.begin_analyze_document(
        "prebuilt-layout",
        AnalyzeDocumentRequest(bytes_source=content),
        output_content_format=DocumentContentFormat.MARKDOWN,
    )
    result = poller.result()
    return result.content or ""


def extract_document(
    path: Path, settings: Settings, *, use_document_intelligence: bool = False
) -> tuple[str, DocumentRecord]:
    """Extract and persist text, returning it with portable source metadata."""
    if not path.exists():
        raise FileNotFoundError(path)
    content = path.read_bytes()
    content_hash = hashlib.sha256(content).hexdigest()
    if use_document_intelligence and path.suffix.lower() not in {".txt", ".md", ".markdown"}:
        text = _read_with_document_intelligence(content, settings.document_intelligence_endpoint)
    else:
        text = _read_local(path)
    if not text.strip():
        raise ValueError(f"No readable text extracted from {path.name}")
    text_path = settings.extracted_text_dir / f"{stable_stem(path.name)}.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(text, encoding="utf-8")
    record = DocumentRecord(
        document_id=f"doc-{content_hash[:12]}",
        document_name=path.name,
        source_file_path=relative_to_project(path, settings),
        document_type=path.suffix.lower().lstrip("."),
        content_hash=content_hash,
        upload_timestamp=_utc_now(),
        extracted_text_path=relative_to_project(text_path, settings),
    )
    return text, record
