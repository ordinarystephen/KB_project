"""Repository-local upload metadata manifest."""

from pathlib import Path
from typing import Any

from .config import Settings
from .json_utils import load_json, save_json


def manifest_path(settings: Settings) -> Path:
    return settings.project_root / "data" / "document_manifest.json"


def load_manifest(settings: Settings) -> dict[str, Any]:
    path = manifest_path(settings)
    if not path.exists():
        return {"schema_version": "1.0.0", "documents": []}
    return load_json(path)


def upsert_document_metadata(record: dict[str, Any], settings: Settings) -> Path:
    """Add or replace metadata for a source path and persist the manifest."""
    manifest = load_manifest(settings)
    documents = manifest["documents"]
    documents[:] = [
        item for item in documents if item["source_file_path"] != record["source_file_path"]
    ]
    documents.append(record)
    return save_json(manifest_path(settings), manifest)
