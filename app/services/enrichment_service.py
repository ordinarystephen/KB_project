"""Part 3: LLM gap-fill — fold verification findings into the per-policy KB."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings
from .json_utils import load_json
from .llm_client import LLMClient
from .policy_kb_store import load_policy_kb, record_stage, save_policy_kb


def enrich_policy_kb(
    policy_kb_path: Path,
    verification_path: Path,
    client: LLMClient,
    settings: Settings,
) -> tuple[dict[str, Any], Path]:
    """Enrich the KB using the verification findings; advance to status: enriched.

    The LLM adds/corrects rules it can support from the source and records anything uncertain as
    open ``follow_up_items`` for the human to resolve before approval.
    """
    kb = load_policy_kb(policy_kb_path)
    verification = load_json(verification_path)
    text_path = settings.project_root / kb["policy"]["extracted_text_path"]
    document_text = text_path.read_text(encoding="utf-8")

    content = client.generate(
        "enrich",
        {
            "document_text": document_text,
            "policy_kb": kb,
            "verification": verification,
        },
    )
    for rule in content.get("rules", []):
        rule.setdefault("human_review_status", "pending_review")
        rule.setdefault("implementation_readiness", "needs_human_review")
    kb["rules"] = content.get("rules", kb["rules"])
    kb["follow_up_items"] = content.get("follow_up_items", kb["follow_up_items"])
    record_stage(
        kb, settings, stage="enrich", status="enriched", prompt_name="policy_kb_enrichment.md"
    )
    saved = save_policy_kb(policy_kb_path, kb, settings)
    return kb, saved


def approve_policy_kb(policy_kb_path: Path, settings: Settings) -> tuple[dict[str, Any], Path]:
    """Gate 1: lock the KB for consolidation (status: approved).

    Returns the KB and the count of still-open follow-up items so the caller can warn; approval is
    the human's responsibility and is not blocked.
    """
    kb = load_policy_kb(policy_kb_path)
    record_stage(kb, settings, stage="approve", status="approved")
    saved = save_policy_kb(policy_kb_path, kb, settings)
    return kb, saved


def open_follow_ups(kb: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in kb.get("follow_up_items", []) if item.get("status") == "open"]
