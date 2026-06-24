"""Completeness review workflow for one policy extraction."""

from pathlib import Path
from typing import Any

from .config import Settings
from .file_utils import relative_to_project
from .json_utils import load_json
from .llm_client import LLMClient
from .workflow_utils import save_without_overwrite, validate_or_log


def review_policy_extraction(
    extraction_path: Path,
    document_text: str,
    client: LLMClient,
    settings: Settings,
) -> tuple[dict[str, Any], Path]:
    """Review, validate, and persist completeness findings."""
    extraction = load_json(extraction_path)
    result = client.generate(
        "review",
        {
            "document_text": document_text,
            "extraction": extraction,
            "extraction_path": relative_to_project(extraction_path, settings),
        },
    )
    validate_or_log(
        result,
        settings.schemas_dir / "policy_review.schema.json",
        "policy-review",
        settings,
    )
    name = extraction_path.name.replace(".rules.json", ".review.json")
    saved = save_without_overwrite(settings.reviews_dir / name, result)
    return result, saved
