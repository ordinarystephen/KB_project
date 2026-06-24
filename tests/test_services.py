"""Per-stage service tests for the four-part pipeline (simulated mode)."""

from pathlib import Path

import pytest

from app.services.consolidation_service import finish_consolidation, start_consolidation
from app.services.document_loader import extract_document, save_uploaded_document
from app.services.enrichment_service import approve_policy_kb, enrich_policy_kb
from app.services.extraction_service import extract_policy_rules
from app.services.file_utils import ensure_output_folders
from app.services.json_utils import load_json, validate_json
from app.services.llm_client import SimulatedLLMClient
from app.services.policy_kb_store import approved_at, load_policy_kb, save_policy_kb
from app.services.verification_service import verify_policy_kb
from app.services.yaml_utils import save_yaml

FIXTURES = Path(__file__).parent / "fixtures"
POLICY_KB_SCHEMA = "policy_kb.schema.json"


def _extract(fixture_name: str, policy_name: str, settings, client) -> tuple[dict, Path]:
    source = save_uploaded_document(fixture_name, (FIXTURES / fixture_name).read_bytes(), settings)
    text, document = extract_document(source, settings)
    return extract_policy_rules(text, document, policy_name, "v1", client, settings)


def _run_to_approved(fixture_name: str, policy_name: str, settings, client) -> Path:
    kb, kb_path = _extract(fixture_name, policy_name, settings, client)
    verify_policy_kb(kb_path, client, settings)
    verification = settings.verifications_dir / f"{kb['policy']['policy_id']}.verification.json"
    enrich_policy_kb(kb_path, verification, client, settings)
    resolved = load_policy_kb(kb_path)
    for item in resolved["follow_up_items"]:
        item["status"] = "resolved"
        item["resolution"] = "Reviewed; no change required."
    save_policy_kb(kb_path, resolved, settings)
    approve_policy_kb(kb_path, settings)
    return kb_path


def test_extraction_creates_validated_draft(settings) -> None:
    ensure_output_folders(settings)
    kb, path = _extract("sample_policy_alpha.txt", "Alpha", settings, SimulatedLLMClient())
    validate_json(kb, settings.schemas_dir / POLICY_KB_SCHEMA)
    assert path.suffix == ".yaml" and path.parent == settings.policy_kbs_dir
    assert kb["status"] == "draft"
    assert kb["policy"]["policy_id"] == "alpha"
    assert all(rule["human_review_status"] == "pending_review" for rule in kb["rules"])
    assert all(rule["implementation_readiness"] == "needs_human_review" for rule in kb["rules"])


def test_status_advances_through_lifecycle(settings) -> None:
    ensure_output_folders(settings)
    client = SimulatedLLMClient()
    kb, kb_path = _extract("sample_policy_alpha.txt", "Alpha", settings, client)
    assert kb["status"] == "draft"
    verify_policy_kb(kb_path, client, settings)
    assert load_policy_kb(kb_path)["status"] == "verified"
    verification = settings.verifications_dir / f"{kb['policy']['policy_id']}.verification.json"
    enriched, _ = enrich_policy_kb(kb_path, verification, client, settings)
    assert enriched["status"] == "enriched"
    approved, _ = approve_policy_kb(kb_path, settings)
    assert approved["status"] == "approved"
    assert approved_at(approved) is not None


def test_verification_writes_findings_and_enrichment_adds_follow_ups(settings) -> None:
    ensure_output_folders(settings)
    client = SimulatedLLMClient()
    kb, kb_path = _extract("sample_policy_alpha.txt", "Alpha", settings, client)
    verification, vpath = verify_policy_kb(kb_path, client, settings)
    validate_json(verification, settings.schemas_dir / "policy_verification.schema.json")
    assert vpath.exists()
    enriched, _ = enrich_policy_kb(kb_path, vpath, client, settings)
    assert enriched["follow_up_items"]
    assert any(item["status"] == "open" for item in enriched["follow_up_items"])


def test_consolidation_rejects_unapproved_kb(settings) -> None:
    ensure_output_folders(settings)
    client = SimulatedLLMClient()
    approved = _run_to_approved("sample_policy_alpha.txt", "Alpha", settings, client)
    _, draft = _extract("sample_policy_beta.txt", "Beta", settings, client)
    with pytest.raises(ValueError):
        start_consolidation([approved, draft], client, settings)


def _consolidate(settings, client, *, fold: bool):
    alpha = _run_to_approved("sample_policy_alpha.txt", "Policy Alpha", settings, client)
    beta = _run_to_approved("sample_policy_beta.txt", "Policy Beta", settings, client)
    _, worksheet, cand_path = start_consolidation([alpha, beta], client, settings)
    if fold and worksheet["candidates"]:
        candidate = worksheet["candidates"][0]
        candidate["decision"] = "fold"
        candidate["fold_into"] = candidate["members"][0]["rule_id"]
        save_yaml(cand_path, worksheet)
    return finish_consolidation(cand_path, client, settings), worksheet


def test_full_pipeline_produces_citable_validated_kb(settings) -> None:
    ensure_output_folders(settings)
    (final, final_path), worksheet = _consolidate(settings, SimulatedLLMClient(), fold=True)
    validate_json(final, settings.schemas_dir / "credit_policy_rules_kb.schema.json")
    assert final_path.name == "credit_policy_rules_kb.json"
    assert load_json(final_path) == final

    expected = load_json(FIXTURES / "expected_consolidated_shape.json")
    assert set(expected["required_top_level_keys"]) == set(final)
    assert not set(expected["forbidden_top_level_keys"]) & set(final)

    # Citation contract: a rule cites page 2, and every rule carries policy_id + quote.
    assert 2 in {rule["policy_source"]["page"] for rule in final["rules"]}
    assert all(rule["policy_source"]["policy_id"] for rule in final["rules"])
    assert all(rule["policy_source"]["quote"] for rule in final["rules"])

    # Provenance preserves source content hashes for both policies.
    sources = final["provenance"]["source_policy_kbs"]
    assert len(sources) == 2
    assert all(source["content_hash"] for source in sources)

    # Groups only reference surviving rule ids.
    rule_ids = {rule["rule_id"] for rule in final["rules"]}
    for group in final["rule_groups"]:
        assert set(group["member_rule_ids"]) <= rule_ids
    assert final["processing_summary"]["total_rule_groups"] == len(final["rule_groups"])


def test_fold_merges_near_duplicates_and_preserves_sources(settings) -> None:
    ensure_output_folders(settings)
    (folded, _), worksheet = _consolidate(settings, SimulatedLLMClient(), fold=True)
    (separate, _), _ = _consolidate(settings, SimulatedLLMClient(), fold=False)
    assert worksheet["candidates"], "expected a near-duplicate candidate"
    assert len(folded["rules"]) < len(separate["rules"])
    merged = [rule for rule in folded["rules"] if len(rule["source_rule_ids"]) > 1]
    assert merged and len(merged[0]["source_rule_ids"]) == 2


def test_stable_ids_do_not_depend_on_input_order(settings) -> None:
    ensure_output_folders(settings)
    client = SimulatedLLMClient()
    alpha = _run_to_approved("sample_policy_alpha.txt", "Policy Alpha", settings, client)
    beta = _run_to_approved("sample_policy_beta.txt", "Policy Beta", settings, client)
    forward, _, _ = start_consolidation([alpha, beta], client, settings)
    reverse, _, _ = start_consolidation([beta, alpha], client, settings)
    assert [r["rule_id"] for r in forward] == [r["rule_id"] for r in reverse]
