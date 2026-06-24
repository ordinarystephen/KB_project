from pathlib import Path

from app.services.document_loader import extract_document, save_uploaded_document
from app.services.file_utils import ensure_output_folders, stable_slug, stable_stem, versioned_path
from app.services.json_utils import load_json, save_json


def test_output_folder_creation(settings) -> None:
    folders = ensure_output_folders(settings)
    assert folders
    assert all(folder.is_dir() for folder in folders)


def test_stable_file_naming() -> None:
    assert stable_slug("Policy Name 2026!") == "policy-name-2026"
    assert stable_stem("Policy Name.v2.PDF") == "policy-name-v2"


def test_versioned_path_avoids_overwrite(tmp_path: Path) -> None:
    original = tmp_path / "policy.rules.json"
    original.touch()
    assert versioned_path(original).name == "policy.rules.v2.json"


def test_json_save_and_load(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "sample.json"
    save_json(path, {"ok": True})
    assert load_json(path) == {"ok": True}


def test_document_loading_from_fixture(settings) -> None:
    fixture = Path(__file__).parent / "fixtures" / "sample_policy_alpha.txt"
    saved = save_uploaded_document(fixture.name, fixture.read_bytes(), settings)
    text, record = extract_document(saved, settings)
    assert "Fake Lending Policy Alpha" in text
    assert Path(settings.project_root / record.extracted_text_path).exists()
    assert record.source_file_path.startswith("data/source_documents/")
