"""Per-policy rule extraction workflow."""

from pathlib import Path
from typing import Any

from .config import Settings
from .document_loader import DocumentRecord
from .file_utils import stable_slug
from .llm_client import LLMClient
from .workflow_utils import save_without_overwrite, validate_or_log


def extract_policy_rules(
    text: str,
    document: DocumentRecord,
    policy_name: str,
    policy_version: str,
    client: LLMClient,
    settings: Settings,
) -> tuple[dict[str, Any], Path]:
    """Generate, validate, and persist one policy rules extraction."""
    payload = {
        "document_text": text,
        "document": document.as_dict(),
        "policy_metadata": {
            "policy_name": policy_name.strip() or Path(document.document_name).stem,
            "policy_version": policy_version.strip(),
        },
    }
    result = client.generate("extract", payload)
    for rule in result.get("rules", []):
        rule["human_review_status"] = "pending_review"
        rule.setdefault("implementation_readiness", "needs_human_review")
    schema = settings.schemas_dir / "extracted_policy_rules.schema.json"
    validate_or_log(result, schema, "policy-extraction", settings)
    filename = f"{stable_slug(result['policy_metadata']['policy_name'])}.rules.json"
    saved = save_without_overwrite(settings.policy_extracts_dir / filename, result)
    return result, saved
