"""Offline end-to-end smoke test for the complete four-part workflow with both human gates."""

from pathlib import Path

from app.services.consolidation_service import finish_consolidation, start_consolidation
from app.services.document_loader import extract_document, save_uploaded_document
from app.services.enrichment_service import approve_policy_kb, enrich_policy_kb
from app.services.extraction_service import extract_policy_rules
from app.services.file_utils import ensure_output_folders
from app.services.json_utils import load_json
from app.services.llm_client import SimulatedLLMClient
from app.services.policy_kb_store import load_policy_kb, save_policy_kb
from app.services.verification_service import verify_policy_kb
from app.services.yaml_utils import save_yaml

FIXTURES = Path(__file__).parent / "fixtures"


def test_complete_offline_four_part_workflow(settings) -> None:
    ensure_output_folders(settings)
    client = SimulatedLLMClient()
    kb_paths = []

    # Parts 1-3 + Gate 1 for each policy.
    for fixture_name, policy_name in [
        ("sample_policy_alpha.txt", "Fake Policy Alpha"),
        ("sample_policy_beta.txt", "Fake Policy Beta"),
    ]:
        fixture = FIXTURES / fixture_name
        source = save_uploaded_document(fixture.name, fixture.read_bytes(), settings)
        text, document = extract_document(source, settings)
        assert (settings.project_root / document.extracted_text_path).exists()

        kb, kb_path = extract_policy_rules(text, document, policy_name, "v1", client, settings)
        assert kb_path.parent == settings.policy_kbs_dir
        assert kb["status"] == "draft"

        _, verification_path = verify_policy_kb(kb_path, client, settings)
        assert verification_path.parent == settings.verifications_dir
        assert load_policy_kb(kb_path)["status"] == "verified"

        enriched, _ = enrich_policy_kb(kb_path, verification_path, client, settings)
        assert enriched["status"] == "enriched"

        resolved = load_policy_kb(kb_path)
        for item in resolved["follow_up_items"]:
            item["status"] = "resolved"
            item["resolution"] = "Reviewed."
        save_policy_kb(kb_path, resolved, settings)
        approved, _ = approve_policy_kb(kb_path, settings)
        assert approved["status"] == "approved"
        kb_paths.append(kb_path)

    # Part 4a/4b: prepare + similarity candidates.
    rules, worksheet, candidates_path = start_consolidation(kb_paths, client, settings)
    assert candidates_path.parent == settings.merge_candidates_dir
    assert worksheet["candidates"], "expected at least one near-duplicate fold candidate"

    # Gate 2: a human folds the first candidate.
    candidate = worksheet["candidates"][0]
    candidate["decision"] = "fold"
    candidate["fold_into"] = candidate["members"][0]["rule_id"]
    save_yaml(candidates_path, worksheet)

    # Part 4c: apply folds, group, finalize.
    final_kb, final_path = finish_consolidation(candidates_path, client, settings)
    assert final_path == settings.consolidated_dir / "credit_policy_rules_kb.json"
    assert load_json(final_path) == final_kb
    assert set(final_kb) == {
        "schema_version",
        "knowledge_base_name",
        "created_from_documents",
        "rules",
        "rule_groups",
        "provenance",
        "processing_summary",
    }
    assert len(final_kb["created_from_documents"]) == 2
    assert final_kb["processing_summary"]["total_rules"] == 2
    assert final_kb["processing_summary"]["total_rule_groups"] == 1
    # Citation contract reaches the downstream KB.
    assert 2 in {rule["policy_source"]["page"] for rule in final_kb["rules"]}
    assert len(final_kb["provenance"]["source_policy_kbs"]) == 2
