import shutil
from pathlib import Path

import pytest

from app.services.config import PROJECT_ROOT, Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    shutil.copytree(PROJECT_ROOT / "schemas", tmp_path / "schemas")
    shutil.copytree(PROJECT_ROOT / "prompts", tmp_path / "prompts")
    return Settings(project_root=tmp_path, llm_mode="simulated")
