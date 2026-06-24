"""Environment-based application configuration."""

from dataclasses import dataclass, field
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    """Deployment settings with portable, repository-relative defaults."""

    project_root: Path = PROJECT_ROOT
    llm_mode: str = field(
        default_factory=lambda: os.getenv("KB_LLM_MODE", "azure").lower()
    )
    azure_openai_endpoint: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT", "")
    )
    azure_openai_deployment: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    )
    azure_openai_api_version: str = field(
        default_factory=lambda: os.getenv(
            "OPENAI_API_VERSION", "2025-04-01-preview"
        )
    )
    document_intelligence_endpoint: str = field(
        default_factory=lambda: os.getenv(
            "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", ""
        )
    )

    @property
    def source_documents_dir(self) -> Path:
        return self.project_root / "data" / "source_documents"

    @property
    def extracted_text_dir(self) -> Path:
        return self.project_root / "data" / "extracted_text"

    @property
    def policy_extracts_dir(self) -> Path:
        return self.project_root / "knowledge_base" / "policy_extracts"

    @property
    def reviews_dir(self) -> Path:
        return self.project_root / "knowledge_base" / "reviews"

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
