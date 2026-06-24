"""Shared validation, error capture, and overwrite protection."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .file_utils import stable_slug, versioned_path
from .json_utils import JsonValidationError, save_json, validate_json


def validate_or_log(
    payload: dict[str, Any], schema_path: Path, operation: str, settings: Settings
) -> None:
    """Validate structured output and preserve invalid payloads for diagnosis."""
    try:
        validate_json(payload, schema_path)
    except (JsonValidationError, RuntimeError) as exc:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        debug_path = settings.logs_dir / f"{stable_slug(operation)}-{stamp}.invalid.json"
        save_json(debug_path, payload)
        raise JsonValidationError(f"{exc}; invalid output saved to {debug_path}") from exc


def save_without_overwrite(path: Path, payload: dict[str, Any]) -> Path:
    """Save to a versioned path so prior processing results remain available."""
    return save_json(versioned_path(path), payload)


def replace_with_archive(path: Path, payload: dict[str, Any]) -> Path:
    """Keep the canonical final filename while archiving any prior result."""
    if path.exists():
        archive_path = versioned_path(path.with_name(f"{path.stem}.previous{path.suffix}"))
        path.replace(archive_path)
    return save_json(path, payload)
