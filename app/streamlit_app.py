"""Streamlit UI for the four-part credit policy rules knowledge-base workflow."""

from __future__ import annotations

import json
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

# Streamlit may put only the script directory (app/) on sys.path. Add the
# repository root so this entry point works from Domino or any current directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.config import Settings
from app.services.consolidation_service import finish_consolidation, start_consolidation
from app.services.document_loader import (
    SUPPORTED_EXTENSIONS,
    extract_document,
    save_uploaded_document,
)
from app.services.enrichment_service import approve_policy_kb, enrich_policy_kb, open_follow_ups
from app.services.extraction_service import extract_policy_rules
from app.services.file_utils import ensure_output_folders, relative_to_project
from app.services.json_utils import load_json
from app.services.llm_client import create_llm_client
from app.services.metadata_store import load_manifest, upsert_document_metadata
from app.services.policy_kb_store import load_policy_kb
from app.services.status import stage_hint
from app.services.verification_service import verify_policy_kb
from app.services.yaml_utils import dump_yaml, load_yaml

SETTINGS = Settings()


@st.cache_resource
def _build_client(mode, endpoint, deployment, embedding, api_version, di_endpoint):
    """Cached per distinct Azure configuration; the args ARE the cache key."""
    return create_llm_client(SETTINGS)


def get_client():
    """Return the client for the active settings, rebuilding it if any Azure setting changed."""
    return _build_client(
        SETTINGS.llm_mode,
        SETTINGS.azure_openai_endpoint,
        SETTINGS.azure_openai_deployment,
        SETTINGS.azure_openai_embedding_deployment,
        SETTINGS.azure_openai_api_version,
        SETTINGS.document_intelligence_endpoint,
    )


def _yaml_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.yaml"))


def _json_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.json"))


def _record_error(operation: str, error: Exception) -> None:
    SETTINGS.logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = SETTINGS.logs_dir / f"{operation}-{timestamp}.log"
    detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    path.write_text(detail, encoding="utf-8")
    st.error(f"{operation} failed: {error}")
    st.caption(f"Error saved to {relative_to_project(path, SETTINGS)}")


def upload_section() -> None:
    st.header("A. Upload documents")
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
                        "upload_timestamp": datetime.now(UTC).isoformat(),
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
    st.header("B. Part 1 — Extract draft KB")
    sources = sorted(
        path
        for path in SETTINGS.source_documents_dir.glob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    selected = st.selectbox("Uploaded document", sources, format_func=lambda p: p.name)
    policy_name = st.text_input("Policy name", key="extract_policy_name")
    policy_version = st.text_input("Policy version", key="extract_policy_version")
    use_di = st.checkbox(
        "Use Azure Document Intelligence for PDF/DOCX",
        value=SETTINGS.llm_mode == "azure",
        help="TXT and Markdown are read directly. Offline tests never call Azure.",
    )
    if st.button("Extract policy rules", disabled=selected is None):
        try:
            text, document = extract_document(selected, SETTINGS, use_document_intelligence=use_di)
            kb, path = extract_policy_rules(
                text, document, policy_name, policy_version, get_client(), SETTINGS
            )
            st.success(f"Saved draft {relative_to_project(path, SETTINGS)}")
            st.metric("Rules extracted", len(kb["rules"]))
        except Exception as exc:  # noqa: BLE001
            _record_error("extraction", exc)


def _kb_label(path: Path) -> str:
    try:
        return f"{path.name}  ·  status: {load_policy_kb(path).get('status', '?')}"
    except Exception:  # noqa: BLE001 - label fallback
        return path.name


def workbench_section() -> None:
    st.header("C. Parts 2–3 — Verify, enrich, approve (Gate 1)")
    kbs = _yaml_files(SETTINGS.policy_kbs_dir)
    selected = st.selectbox("Per-policy KB", kbs, format_func=_kb_label)
    if selected is None:
        st.info("Extract a document in Part 1 to create a per-policy KB.")
        return
    kb = load_policy_kb(selected)
    status = kb.get("status", "draft")
    hint = stage_hint(status)
    st.info(f"**Status `{status}`** — {hint.do}")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Verify (Part 2)", disabled=status not in {"draft", "verified", "enriched"}):
            try:
                _, vpath = verify_policy_kb(selected, get_client(), SETTINGS)
                st.success(f"Saved {relative_to_project(vpath, SETTINGS)}")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                _record_error("verification", exc)
    with col2:
        if st.button("Enrich (Part 3)", disabled=status not in {"verified", "enriched"}):
            try:
                vpath = (
                    SETTINGS.verifications_dir / f"{kb['policy']['policy_id']}.verification.json"
                )
                enrich_policy_kb(selected, vpath, get_client(), SETTINGS)
                st.success("Enriched; resolve follow-ups below, then approve.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                _record_error("enrichment", exc)
    with col3:
        open_items = open_follow_ups(kb)
        if st.button("Approve (Gate 1)", disabled=status != "enriched"):
            try:
                approve_policy_kb(selected, SETTINGS)
                st.success("Approved — eligible for Part 4.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                _record_error("approval", exc)
        if status == "enriched" and open_items:
            st.warning(
                f"{len(open_items)} open follow-up item(s) — resolve in the YAML before approving."
            )

    vpath = SETTINGS.verifications_dir / f"{kb['policy']['policy_id']}.verification.json"
    if vpath.exists():
        with st.expander("Verification findings (Part 2)"):
            st.json(load_json(vpath).get("processing_summary", {}))
    if kb.get("follow_up_items"):
        with st.expander("Follow-up items"):
            st.json(kb["follow_up_items"])
    with st.expander("KB YAML (edit on disk to resolve follow-ups)"):
        st.code(dump_yaml(kb), language="yaml")


def consolidation_section() -> None:
    st.header("D. Part 4 — Consolidate (Gate 2)")
    kbs = _yaml_files(SETTINGS.policy_kbs_dir)
    approved = [p for p in kbs if load_policy_kb(p).get("status") == "approved"]
    st.caption(f"{len(approved)} approved KB(s) available for consolidation.")
    selected = st.multiselect("Approved policy KBs", approved, format_func=lambda p: p.name)
    if st.button("4a/4b — Find merge candidates", disabled=len(selected) < 2):
        try:
            _, worksheet, path = start_consolidation(selected, get_client(), SETTINGS)
            st.success(f"Wrote {relative_to_project(path, SETTINGS)}")
            st.caption(
                "Edit each candidate's `decision:` (keep_separate or fold) and `fold_into:` in "
                "that file, then run 4c below."
            )
            st.metric("Merge candidates", len(worksheet["candidates"]))
        except Exception as exc:  # noqa: BLE001
            _record_error("consolidation-start", exc)

    st.divider()
    worksheets = _yaml_files(SETTINGS.merge_candidates_dir)
    chosen = st.selectbox("Candidate worksheet", worksheets, format_func=lambda p: p.name)
    if st.button("4c — Apply folds & consolidate", disabled=chosen is None):
        try:
            final, path = finish_consolidation(chosen, get_client(), SETTINGS)
            st.success(f"Saved {relative_to_project(path, SETTINGS)}")
            st.metric("Checkable rules", final["processing_summary"]["total_rules"])
            st.metric("Relationship groups", final["processing_summary"]["total_rule_groups"])
            st.json(final["processing_summary"])
        except Exception as exc:  # noqa: BLE001
            _record_error("consolidation-finish", exc)


def browse_section() -> None:
    st.header("E. Browse outputs")
    category = st.selectbox(
        "Output type", ["Policy KBs", "Merge candidates", "Verifications", "Consolidated KB"]
    )
    if category == "Policy KBs":
        files, lang, loader = _yaml_files(SETTINGS.policy_kbs_dir), "yaml", load_yaml
    elif category == "Merge candidates":
        files, lang, loader = _yaml_files(SETTINGS.merge_candidates_dir), "yaml", load_yaml
    elif category == "Verifications":
        files, lang, loader = _json_files(SETTINGS.verifications_dir), "json", load_json
    else:
        files, lang, loader = _json_files(SETTINGS.consolidated_dir), "json", load_json
    selected = st.selectbox("Saved file", files, format_func=lambda p: p.name)
    if selected is not None:
        payload = loader(selected)
        text = dump_yaml(payload) if lang == "yaml" else json.dumps(payload, indent=2)
        st.code(text, language=lang)


def main() -> None:
    st.set_page_config(page_title="Credit Policy Rules KB", layout="wide")
    ensure_output_folders(SETTINGS)
    st.title("Credit Policy Rules Knowledge Base Workbench")
    st.info(
        "LLM output is a draft for human review, never an approved policy decision. "
        f"Current mode: {SETTINGS.llm_mode}. See docs/RUNBOOK.md for the step-by-step process."
    )
    upload_section()
    extraction_section()
    workbench_section()
    consolidation_section()
    browse_section()


if __name__ == "__main__":
    main()
