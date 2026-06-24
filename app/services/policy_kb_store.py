"""Build, persist, and advance the canonical per-policy KB (YAML on disk)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings
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
