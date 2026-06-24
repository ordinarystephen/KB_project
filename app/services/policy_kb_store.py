"""Build, persist, and advance the canonical per-policy KB (YAML on disk)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .file_utils import versioned_path
from .workflow_utils import validate_or_log
from .yaml_utils import load_yaml, save_yaml

POLICY_KB_SCHEMA = "policy_kb.schema.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def model_label(settings: Settings) -> str:
    return "simulated" if settings.llm_mode == "simulated" else settings.azure_openai_deployment


def prompt_version(settings: Settings, prompt_name: str) -> str:
    """Short content hash of a prompt file, recorded for reproducibility."""
    data = (settings.prompts_dir / prompt_name).read_bytes()
    return hashlib.sha256(data).hexdigest()[:12]


def build_policy_kb(
    document: dict[str, Any],
    policy_meta: dict[str, Any],
    content: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    """Assemble a draft per-policy KB envelope from the LLM's extract content."""
    now = _now()
    return {
        "schema_version": "1.0.0",
        "status": "draft",
        "policy": {
            "policy_id": policy_meta["policy_id"],
            "policy_name": policy_meta["policy_name"],
            "policy_version": policy_meta.get("policy_version", ""),
            "document_name": document["document_name"],
            "content_hash": document["content_hash"],
            "source_file_path": document["source_file_path"],
            "extracted_text_path": document["extracted_text_path"],
        },
        "rules": content.get("rules", []),
        "follow_up_items": content.get("follow_up_items", []),
        "provenance": {
            "model_deployment": model_label(settings),
            "prompt_versions": {"extract": prompt_version(settings, "policy_rule_extraction.md")},
            "generated_at": now,
            "stage_history": [{"stage": "extract", "at": now, "mode": settings.llm_mode}],
        },
    }


def record_stage(
    kb: dict[str, Any],
    settings: Settings,
    *,
    stage: str,
    status: str,
    prompt_name: str | None = None,
) -> dict[str, Any]:
    """Advance the KB status and append a provenance stage record."""
    now = _now()
    kb["status"] = status
    if prompt_name:
        kb["provenance"]["prompt_versions"][stage] = prompt_version(settings, prompt_name)
    kb["provenance"]["stage_history"].append({"stage": stage, "at": now, "mode": settings.llm_mode})
    return kb


def approved_at(kb: dict[str, Any]) -> str | None:
    times = [
        entry["at"]
        for entry in kb["provenance"]["stage_history"]
        if entry.get("stage") == "approve"
    ]
    return times[-1] if times else None


def save_policy_kb(path: Path, kb: dict[str, Any], settings: Settings) -> Path:
    """Validate against the per-policy schema, then persist as YAML."""
    validate_or_log(kb, settings.schemas_dir / POLICY_KB_SCHEMA, "policy-kb", settings)
    return save_yaml(path, kb)


def load_policy_kb(path: Path) -> dict[str, Any]:
    return load_yaml(path)


def apply_policy_identity(
    rules: list[dict[str, Any]], policy_meta: dict[str, Any], document_name: str
) -> list[dict[str, Any]]:
    """Force each rule's primary policy_source identity to the authoritative values.

    The LLM owns the section/page/quote of a citation, but the policy identity is a known fact;
    overwriting it keeps every citation traceable to the correct policy regardless of model drift.
    """
    for rule in rules:
        source = rule.get("policy_source")
        if isinstance(source, dict):
            source["policy_id"] = policy_meta["policy_id"]
            source["policy_name"] = policy_meta["policy_name"]
            source["document_name"] = document_name
            if not source.get("policy_version"):
                source["policy_version"] = policy_meta.get("policy_version", "")
    return rules


def archive_if_protected(path: Path) -> Path | None:
    """Archive an existing non-draft KB before overwrite so human work is never silently lost.

    Returns the archive path, or None when there was nothing protected to preserve.
    """
    if not path.exists():
        return None
    try:
        existing = load_yaml(path)
    except (ValueError, OSError):
        return None
    if existing.get("status", "draft") == "draft":
        return None
    archive = versioned_path(path.with_name(f"{path.stem}.superseded{path.suffix}"))
    path.replace(archive)
    return archive
