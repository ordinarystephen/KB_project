"""Offline end-to-end smoke test for the complete file-based workflow."""

from pathlib import Path

from app.services.consolidation_service import consolidate_policy_extracts
from app.services.document_loader import extract_document, save_uploaded_document
from app.services.extraction_service import extract_policy_rules
from app.services.file_utils import ensure_output_folders
from app.services.json_utils import load_json
from app.services.llm_client import SimulatedLLMClient
from app.services.review_service import review_policy_extraction


FIXTURES = Path(__file__).parent / "fixtures"


def test_complete_offline_file_workflow(settings) -> None:
    ensure_output_folders(settings)
    client = SimulatedLLMClient()
    extraction_paths = []

    for fixture_name, policy_name in [
        ("sample_policy_alpha.txt", "Fake Policy Alpha"),
        ("sample_policy_beta.txt", "Fake Policy Beta"),
    ]:
        fixture = FIXTURES / fixture_name
        source = save_uploaded_document(fixture.name, fixture.read_bytes(), settings)
        text, document = extract_document(source, settings)
        assert (settings.project_root / document.extracted_text_path).exists()

        extraction, extraction_path = extract_policy_rules(
            text, document, policy_name, "test-v1", client, settings
        )
        extraction_paths.append(extraction_path)
        assert extraction_path.parent == settings.policy_extracts_dir
        assert extraction["processing_summary"]

        review, review_path = review_policy_extraction(
            extraction_path, text, client, settings
        )
        assert review_path.parent == settings.reviews_dir
        assert review["processing_summary"]

    final_kb, final_path = consolidate_policy_extracts(extraction_paths, client, settings)
    assert final_path == settings.consolidated_dir / "credit_policy_rules_kb.json"
    persisted = load_json(final_path)
    assert persisted == final_kb
    assert set(final_kb) == {
        "schema_version",
        "knowledge_base_name",
        "created_from_documents",
        "rules",
        "processing_summary",
    }
    assert len(final_kb["created_from_documents"]) == 2
    assert len(final_kb["rules"]) == 2
    assert final_kb["processing_summary"]["total_rules"] == 2
