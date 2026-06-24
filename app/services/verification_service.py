"""Part 2: verify a draft KB against its source policy (completeness check)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings
from .file_utils import relative_to_project
from .json_utils import save_json
from .llm_client import LLMClient
from .policy_kb_store import load_policy_kb, record_stage, save_policy_kb
from .workflow_utils import validate_or_log


def verify_policy_kb(
    policy_kb_path: Path,
    client: LLMClient,
    settings: Settings,
) -> tuple[dict[str, Any], Path]:
    """Produce a completeness diagnostic and advance the KB to status: verified."""
    kb = load_policy_kb(policy_kb_path)
    text_path = settings.project_root / kb["policy"]["extracted_text_path"]
    document_text = text_path.read_text(encoding="utf-8")

    result = client.generate(
        "verify",
        {
            "document_text": document_text,
            "policy_kb": kb,
            "reviewed_policy_kb": relative_to_project(policy_kb_path, settings),
        },
    )
    # The path is an authoritative fact, not the model's to decide: override any value it returned.
    result["reviewed_policy_kb"] = relative_to_project(policy_kb_path, settings)
    validate_or_log(
        result,
        settings.schemas_dir / "policy_verification.schema.json",
        "policy-verification",
        settings,
    )
    verification_path = (
        settings.verifications_dir / f"{kb['policy']['policy_id']}.verification.json"
    )
    saved = save_json(verification_path, result)

    record_stage(
        kb, settings, stage="verify", status="verified", prompt_name="policy_completeness_review.md"
    )
    save_policy_kb(policy_kb_path, kb, settings)
    return result, saved
