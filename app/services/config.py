"""Environment-based application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_float(name: str, default: float) -> float:
    """Read a float env var, falling back to the default on missing/invalid input.

    A misconfigured Domino variable must not crash the app at import time.
    """
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _first_env(names: tuple[str, ...], default: str = "") -> str:
    """Return the first non-empty value among env var aliases.

    Lets the same Domino environment work whether it uses this app's names or the shared
    canonical names (e.g. AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT, AZURE_DOCINTEL_ENDPOINT).
    """
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


@dataclass(frozen=True)
class Settings:
    """Deployment settings with portable, repository-relative defaults."""

    project_root: Path = PROJECT_ROOT
    llm_mode: str = field(default_factory=lambda: os.getenv("KB_LLM_MODE", "azure").lower())
    azure_openai_endpoint: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT", "")
    )
    azure_openai_deployment: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    )
    azure_openai_embedding_deployment: str = field(
        default_factory=lambda: _first_env(
            ("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", "AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
        )
    )
    azure_openai_api_version: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_VERSION", "2025-04-01-preview")
    )
    # In Domino, point this at the local proxy (e.g. https://127.0.0.1:8443); egress to the public
    # *.cognitiveservices.azure.com endpoint is typically blocked.
    document_intelligence_endpoint: str = field(
        default_factory=lambda: _first_env(
            ("AZURE_DOCINTEL_ENDPOINT", "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
        )
    )
    document_intelligence_api_version: str = field(
        default_factory=lambda: os.getenv("DOCINTEL_API_VERSION", "2024-11-30")
    )
    similarity_threshold: float = field(
        default_factory=lambda: _read_float("KB_SIMILARITY_THRESHOLD", 0.86)
    )

    @property
    def source_documents_dir(self) -> Path:
        return self.project_root / "data" / "source_documents"

    @property
    def extracted_text_dir(self) -> Path:
        return self.project_root / "data" / "extracted_text"

    @property
    def policy_kbs_dir(self) -> Path:
        return self.project_root / "knowledge_base" / "policy_kbs"

    @property
    def verifications_dir(self) -> Path:
        return self.project_root / "knowledge_base" / "verifications"

    @property
    def merge_candidates_dir(self) -> Path:
        return self.project_root / "knowledge_base" / "merge_candidates"

    @property
    def consolidated_dir(self) -> Path:
        return self.project_root / "knowledge_base" / "consolidated"

    @property
    def logs_dir(self) -> Path:
        return self.project_root / "knowledge_base" / "logs"

    @property
    def prompts_dir(self) -> Path:
        return self.project_root / "prompts"

    @property
    def schemas_dir(self) -> Path:
        return self.project_root / "schemas"
