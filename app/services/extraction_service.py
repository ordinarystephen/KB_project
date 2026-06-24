"""Part 1: extract a draft per-policy KB from one source document."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings
from .document_loader import DocumentRecord
from .file_utils import stable_slug
from .llm_client import LLMClient
from .policy_kb_store import build_policy_kb, save_policy_kb


def extract_policy_rules(
    text: str,
    document: DocumentRecord,
    policy_name: str,
    policy_version: str,
    client: LLMClient,
    settings: Settings,
) -> tuple[dict[str, Any], Path]:
    """Generate, validate, and persist one draft per-policy KB (status: draft)."""
    resolved_name = policy_name.strip() or Path(document.document_name).stem
    policy_id = stable_slug(resolved_name)
    policy_meta = {
        "policy_id": policy_id,
        "policy_name": resolved_name,
        "policy_version": policy_version.strip(),
    }
    content = client.generate(
        "extract",
        {
            "document_text": text,
            "document": document.as_dict(),
            "policy_metadata": policy_meta,
        },
    )
    for rule in content.get("rules", []):
        rule["human_review_status"] = "pending_review"
        rule.setdefault("implementation_readiness", "needs_human_review")
    kb = build_policy_kb(document.as_dict(), policy_meta, content, settings)
    path = settings.policy_kbs_dir / f"{policy_id}.kb.yaml"
    saved = save_policy_kb(path, kb, settings)
    return kb, saved
