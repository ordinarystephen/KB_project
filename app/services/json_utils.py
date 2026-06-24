"""JSON persistence and schema validation utilities."""

import json
from pathlib import Path
from typing import Any


class JsonValidationError(ValueError):
    """Raised when structured output does not match its JSON Schema."""


def save_json(path: Path, payload: dict[str, Any]) -> Path:
    """Save UTF-8 JSON atomically enough for the local-file workflow."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def validate_json(payload: dict[str, Any], schema_path: Path) -> None:
    """Validate payload, using jsonschema when installed."""
    schema = load_json(schema_path)
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - dependency is present in target runtime
        raise RuntimeError("jsonschema is required for output validation") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise JsonValidationError(details)
