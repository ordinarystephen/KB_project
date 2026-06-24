"""Safe, stable file naming and repository folder management."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from .config import Settings


def stable_slug(value: str) -> str:
    """Return a deterministic filesystem-safe lowercase slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "document"


def stable_stem(filename: str) -> str:
    """Return a stable slug derived from a filename without its final suffix."""
    return stable_slug(Path(filename).stem)


def ensure_output_folders(settings: Settings) -> list[Path]:
    """Create and return all runtime output folders."""
    folders: Iterable[Path] = (
        settings.source_documents_dir,
        settings.extracted_text_dir,
        settings.policy_kbs_dir,
        settings.verifications_dir,
        settings.merge_candidates_dir,
        settings.consolidated_dir,
        settings.logs_dir,
    )
    result = list(folders)
    for folder in result:
        folder.mkdir(parents=True, exist_ok=True)
    return result


def versioned_path(path: Path) -> Path:
    """Avoid silent overwrite by adding a numeric suffix when needed."""
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}.v{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def relative_to_project(path: Path, settings: Settings) -> str:
    """Return a portable POSIX path relative to the repository root."""
    return path.resolve().relative_to(settings.project_root.resolve()).as_posix()
