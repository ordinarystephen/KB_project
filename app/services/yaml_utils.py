"""YAML persistence for human-editable per-policy KBs.

YAML is the canonical, human-edited format for per-policy KBs and merge candidates.
Validation still runs on the loaded Python dict against the JSON Schemas, so the
schema is the single source of truth regardless of on-disk format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _require_yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - dependency present in target runtime
        raise RuntimeError("pyyaml is required for YAML persistence") from exc
    return yaml


def dump_yaml(payload: dict[str, Any]) -> str:
    """Serialize a dict to human-friendly YAML, preserving key order."""
    yaml = _require_yaml()
    return yaml.safe_dump(
        payload, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100
    )


def load_yaml_str(text: str) -> dict[str, Any]:
    """Parse a YAML document into a dict."""
    yaml = _require_yaml()
    payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError("Expected a YAML mapping at the document root")
    return payload


def save_yaml(path: Path, payload: dict[str, Any]) -> Path:
    """Write UTF-8 YAML atomically enough for the local-file workflow."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(dump_yaml(payload), encoding="utf-8")
    temporary.replace(path)
    return path


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from disk."""
    return load_yaml_str(path.read_text(encoding="utf-8"))
