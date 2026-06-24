"""Streamlit UI for the credit policy rules knowledge-base workflow."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import streamlit as st

# Streamlit may put only the script directory (app/) on sys.path. Add the
# repository root so this entry point works from Domino or any current directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.config import Settings
from app.services.consolidation_service import consolidate_policy_extracts
from app.services.document_loader import extract_document, save_uploaded_document
from app.services.document_loader import SUPPORTED_EXTENSIONS
from app.services.extraction_service import extract_policy_rules
from app.services.file_utils import ensure_output_folders, relative_to_project
from app.services.json_utils import load_json
from app.services.llm_client import create_llm_client
from app.services.metadata_store import load_manifest, upsert_document_metadata
from app.services.review_service import review_policy_extraction


SETTINGS = Settings()


@st.cache_resource
def get_client():
    """Construct one provider client per Streamlit process."""
    return create_llm_client(SETTINGS)


def _json_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.json"))


def _show_summary(summary: dict) -> None:
    st.subheader("Processing summary")
    st.json(summary)


def _record_error(operation: str, error: Exception) -> None:
    SETTINGS.logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = SETTINGS.logs_dir / f"{operation}-{timestamp}.log"
    path.write_text(f"{type(error).__name__}: {error}\n", encoding="utf-8")
    st.error(f"{operation} failed: {error}")
    st.caption(f"Error saved to {relative_to_project(path, SETTINGS)}")


def upload_section() -> None:
    st.header("A. Upload Documents")
    uploads = st.file_uploader(
        "Policy documents",
        type=["pdf", "docx", "txt", "md", "markdown"],
        accept_multiple_files=True,
    )
    policy_name = st.text_input("Policy name (optional)")
    policy_version = st.text_input("Policy version (optional)")
    if st.button("Save uploaded documents", disabled=not uploads):
        for upload in uploads:
            try:
                path = save_uploaded_document(upload.name, upload.getvalue(), SETTINGS)
                upsert_document_metadata(
                    {
                        "document_name": upload.name,
                        "policy_name": policy_name,
                        "policy_version": policy_version,
                        "upload_timestamp": datetime.now(timezone.utc).isoformat(),
                        "source_file_path": relative_to_project(path, SETTINGS),
                        "processing_status": "uploaded",
                    },
                    SETTINGS,
                )
                st.success(f"Saved {relative_to_project(path, SETTINGS)}")
            except Exception as exc:  # noqa: BLE001 - UI boundary logs all errors
                _record_error("upload", exc)
    documents = load_manifest(SETTINGS)["documents"]
    if documents:
        st.dataframe(documents, use_container_width=True)


def extraction_section() -> None:
    st.header("B. Extract Rules")
    sources = sorted(
        path
        for path in SETTINGS.source_documents_dir.glob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    selected = st.selectbox("Uploaded document", sources, format_func=lambda p: p.name)
    policy_name = st.text_input("Extraction policy name", key="extract_policy_name")
    policy_version = st.text_input("Extraction policy version", key="extract_policy_version")
    use_di = st.checkbox(
        "Use Azure Document Intelligence for PDF/DOCX",
        value=SETTINGS.llm_mode == "azure",
        help="TXT and Markdown are read directly. Offline tests never call Azure.",
    )
    if st.button("Extract policy rules", disabled=selected is None):
        try:
            text, document = extract_document(
                selected, SETTINGS, use_document_intelligence=use_di
            )
            result, path = extract_policy_rules(
                text,
                document,
                policy_name,
                policy_version,
                get_client(),
                SETTINGS,
            )
            st.success(f"Saved {relative_to_project(path, SETTINGS)}")
            st.metric("Rules extracted", len(result["rules"]))
            _show_summary(result["processing_summary"])
        except Exception as exc:  # noqa: BLE001
            _record_error("extraction", exc)


def review_section() -> None:
    st.header("C. Review Extraction")
    extracts = _json_files(SETTINGS.policy_extracts_dir)
    selected = st.selectbox("Policy extraction", extracts, format_func=lambda p: p.name)
    if st.button("Run completeness review", disabled=selected is None):
        try:
            extraction = load_json(selected)
            text_path = SETTINGS.project_root / extraction["document"]["extracted_text_path"]
            result, path = review_policy_extraction(
                selected, text_path.read_text(encoding="utf-8"), get_client(), SETTINGS
            )
            st.success(f"Saved {relative_to_project(path, SETTINGS)}")
            _show_summary(result["processing_summary"])
        except Exception as exc:  # noqa: BLE001
            _record_error("review", exc)


def consolidation_section() -> None:
    st.header("D. Consolidate Knowledge Base")
    extracts = _json_files(SETTINGS.policy_extracts_dir)
    selected = st.multiselect("Policy extractions", extracts, format_func=lambda p: p.name)
    if st.button("Consolidate selected policies", disabled=len(selected) < 2):
        try:
            result, path = consolidate_policy_extracts(selected, get_client(), SETTINGS)
            st.success(f"Saved {relative_to_project(path, SETTINGS)}")
            st.metric("Checkable rules", len(result["rules"]))
            _show_summary(result["processing_summary"])
        except Exception as exc:  # noqa: BLE001
            _record_error("consolidation", exc)


def browse_section() -> None:
    st.header("E. Browse Outputs")
    category = st.selectbox(
        "Output type",
        ["Policy extracts", "Reviews", "Consolidated KB"],
    )
    folders = {
        "Policy extracts": SETTINGS.policy_extracts_dir,
        "Reviews": SETTINGS.reviews_dir,
        "Consolidated KB": SETTINGS.consolidated_dir,
    }
    files = _json_files(folders[category])
    selected = st.selectbox("Saved JSON", files, format_func=lambda p: p.name)
    if selected is not None:
        st.code(json.dumps(load_json(selected), indent=2), language="json")


def main() -> None:
    st.set_page_config(page_title="Credit Policy Rules KB", layout="wide")
    ensure_output_folders(SETTINGS)
    st.title("Credit Policy Rules Knowledge Base Workbench")
    st.info(
        "LLM output is a draft for human review, never an approved policy decision. "
        f"Current mode: {SETTINGS.llm_mode}."
    )
    upload_section()
    extraction_section()
    review_section()
    consolidation_section()
    browse_section()


if __name__ == "__main__":
    main()
