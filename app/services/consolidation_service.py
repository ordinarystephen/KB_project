"""Part 4: consolidate approved per-policy KBs into the single downstream KB.

Sequence: 4a deterministic normalize+exact-dedup+stable-ids, 4b probabilistic similarity ->
human fold candidates (Gate 2), 4c apply folds -> LLM relationship grouping -> finalize.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .consolidation_rules import apply_folds, assemble_final_kb, prepare_rules
from .file_utils import relative_to_project
from .llm_client import LLMClient
from .policy_kb_store import approved_at, load_policy_kb, model_label, prompt_version
from .similarity_service import find_candidates
from .workflow_utils import replace_with_archive, validate_or_log
from .yaml_utils import load_yaml, save_yaml

FINAL_KB_FILENAME = "credit_policy_rules_kb.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_approved(paths: list[Path], settings: Settings) -> list[dict[str, Any]]:
    kbs = []
    for path in paths:
        kb = load_policy_kb(path)
        if kb.get("status") != "approved":
            raise ValueError(
                f"{path.name} is '{kb.get('status')}', not 'approved'. "
                "Approve every KB before Part 4."
            )
        kbs.append(kb)
    return kbs


def start_consolidation(
    policy_kb_paths: list[Path], client: LLMClient, settings: Settings
) -> tuple[list[dict[str, Any]], dict[str, Any], Path]:
    """Part 4a/4b: prepare rules and write the merge-candidate worksheet for Gate 2."""
    if len(policy_kb_paths) < 2:
        raise ValueError("Select at least two approved policy KBs for consolidation")
    kbs = _load_approved(policy_kb_paths, settings)
    rules = prepare_rules(kbs)
    candidates = find_candidates(rules, client, settings)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    worksheet = {
        "schema_version": "1.0.0",
        "run_id": f"run-{stamp}",
        "similarity_threshold": settings.similarity_threshold,
        "source_policy_kbs": [relative_to_project(path, settings) for path in policy_kb_paths],
        "candidates": candidates,
        # Snapshot of the exact normalized rules the candidates reference. 4c folds against this,
        # so editing a source KB between 4b and 4c cannot silently change ids and drop a fold.
        "prepared_rules": rules,
    }
    path = settings.merge_candidates_dir / f"{worksheet['run_id']}.candidates.yaml"
    save_yaml(path, worksheet)
    return rules, worksheet, path


def fold_ops_from_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate human ``decision: fold`` entries into deterministic fold operations."""
    ops = []
    for candidate in candidates:
        if candidate.get("decision") != "fold":
            continue
        target = candidate.get("fold_into")
        member_ids = [member["rule_id"] for member in candidate.get("members", [])]
        if target in member_ids:
            ops.append(
                {"target_id": target, "source_ids": [mid for mid in member_ids if mid != target]}
            )
    return ops


def finish_consolidation(
    candidates_path: Path, client: LLMClient, settings: Settings
) -> tuple[dict[str, Any], Path]:
    """Part 4c: apply folds, LLM-group, finalize, and write the downstream KB."""
    worksheet = load_yaml(candidates_path)
    paths = [settings.project_root / rel for rel in worksheet["source_policy_kbs"]]
    kbs = _load_approved(paths, settings)

    # Fold against the snapshot the human reviewed; re-derive only if an older worksheet lacks it.
    rules = worksheet.get("prepared_rules") or prepare_rules(kbs)
    rules = apply_folds(rules, fold_ops_from_candidates(worksheet.get("candidates", [])))
    grouped = client.generate("group", {"rules": rules})

    provenance = {
        "generated_at": _now(),
        "model_deployment": model_label(settings),
        "prompt_versions": {"group": prompt_version(settings, "policy_kb_consolidation.md")},
        "source_policy_kbs": [
            {
                "policy_id": kb["policy"]["policy_id"],
                "file": relative_to_project(path, settings),
                "content_hash": kb["policy"]["content_hash"],
                "approved_at": approved_at(kb),
            }
            for kb, path in zip(kbs, paths)
        ],
    }
    final_kb = assemble_final_kb(
        rules,
        grouped.get("rule_groups", []),
        created_from_documents=[kb["policy"]["document_name"] for kb in kbs],
        provenance=provenance,
    )
    validate_or_log(
        final_kb,
        settings.schemas_dir / "credit_policy_rules_kb.schema.json",
        "kb-consolidation",
        settings,
    )
    saved = replace_with_archive(settings.consolidated_dir / FINAL_KB_FILENAME, final_kb)
    return final_kb, saved
