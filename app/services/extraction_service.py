"""Part 1: extract a draft per-policy KB from one source document."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings
from .document_loader import DocumentRecord
from .file_utils import stable_slug
from .llm_client import LLMClient
from .normalization import normalize_follow_up_items, normalize_policy_rules
from .policy_kb_store import archive_if_protected, build_policy_kb, save_policy_kb


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
    # Normalize raw model output into schema-valid rules (fills structural defaults, forces
    # authoritative citation identity) so a live extraction never hard-fails validation.
    rules, extra_follow_ups = normalize_policy_rules(
        content.get("rules"), policy_meta, document.document_name
    )
    follow_ups = normalize_follow_up_items(content.get("follow_up_items")) + extra_follow_ups
    kb = build_policy_kb(
        document.as_dict(), policy_meta, {"rules": rules, "follow_up_items": follow_ups}, settings
    )
    path = settings.policy_kbs_dir / f"{policy_id}.kb.yaml"
    # Never silently overwrite verified/enriched/approved human work on a re-extract.
    archive_if_protected(path)
    saved = save_policy_kb(path, kb, settings)
    return kb, saved
