"""Final rules-only knowledge-base consolidation workflow."""

from pathlib import Path
from typing import Any, Sequence

from .config import Settings
from .consolidation_rules import finalize_knowledge_base
from .json_utils import load_json
from .llm_client import LLMClient
from .workflow_utils import replace_with_archive, validate_or_log


FINAL_KB_FILENAME = "credit_policy_rules_kb.json"


def consolidate_policy_extracts(
    extraction_paths: Sequence[Path], client: LLMClient, settings: Settings
) -> tuple[dict[str, Any], Path]:
    """Consolidate multiple extracts into the validated minimal final KB."""
    if len(extraction_paths) < 2:
        raise ValueError("Select at least two policy extracts for consolidation")
    extractions = [load_json(path) for path in extraction_paths]
    result = client.generate("consolidate", {"extractions": extractions})
    result = finalize_knowledge_base(result)
    validate_or_log(
        result,
        settings.schemas_dir / "credit_policy_rules_kb.schema.json",
        "kb-consolidation",
        settings,
    )
    saved = replace_with_archive(settings.consolidated_dir / FINAL_KB_FILENAME, result)
    return result, saved
