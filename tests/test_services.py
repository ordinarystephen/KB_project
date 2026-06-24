from pathlib import Path

from app.services.consolidation_service import consolidate_policy_extracts
from app.services.document_loader import extract_document, save_uploaded_document
from app.services.extraction_service import extract_policy_rules
from app.services.file_utils import ensure_output_folders
from app.services.json_utils import load_json, save_json, validate_json
from app.services.llm_client import SimulatedLLMClient
from app.services.review_service import review_policy_extraction


FIXTURES = Path(__file__).parent / "fixtures"


def _process_fixture(name: str, policy_name: str, settings):
    fixture = FIXTURES / name
    source = save_uploaded_document(fixture.name, fixture.read_bytes(), settings)
    text, document = extract_document(source, settings)
    extraction, path = extract_policy_rules(
        text, document, policy_name, "v1", SimulatedLLMClient(), settings
    )
    return text, extraction, path


def test_extraction_output_defaults_and_validation(settings) -> None:
    ensure_output_folders(settings)
    _, extraction, path = _process_fixture("sample_policy_alpha.txt", "Alpha", settings)
    validate_json(extraction, settings.schemas_dir / "extracted_policy_rules.schema.json")
    assert path.exists()
    assert extraction["processing_summary"]
    assert all(rule["human_review_status"] == "pending_review" for rule in extraction["rules"])
    assert all(
        rule["implementation_readiness"] == "needs_human_review"
        for rule in extraction["rules"]
    )


def test_review_output_validation_and_summary(settings) -> None:
    ensure_output_folders(settings)
    text, _, extraction_path = _process_fixture(
        "sample_policy_alpha.txt", "Alpha", settings
    )
    review, review_path = review_policy_extraction(
        extraction_path, text, SimulatedLLMClient(), settings
    )
    validate_json(review, settings.schemas_dir / "policy_review.schema.json")
    assert review_path.exists()
    assert review["processing_summary"]


def test_consolidation_is_minimal_and_preserves_sources(settings) -> None:
    ensure_output_folders(settings)
    _, alpha, alpha_path = _process_fixture("sample_policy_alpha.txt", "Alpha", settings)
    _, beta, beta_path = _process_fixture("sample_policy_beta.txt", "Beta", settings)
    result, output_path = consolidate_policy_extracts(
        [alpha_path, beta_path], SimulatedLLMClient(), settings
    )
    validate_json(result, settings.schemas_dir / "credit_policy_rules_kb.schema.json")
    expected = load_json(FIXTURES / "expected_consolidated_shape.json")
    assert set(expected["required_top_level_keys"]) == set(result)
    assert not set(expected["forbidden_top_level_keys"]) & set(result)
    assert output_path.name == "credit_policy_rules_kb.json"
    assert result["processing_summary"]["total_rules"] == 2
    source_ids = {rule["rule_id"] for rule in alpha["rules"] + beta["rules"]}
    consolidated_source_ids = {
        source_id for rule in result["rules"] for source_id in rule["source_rule_ids"]
    }
    assert source_ids == consolidated_source_ids
    assert all(rule["policy_source"]["document_name"] for rule in result["rules"])
    assert all(rule["credit_documentation_fields_needed"] for rule in result["rules"])


def test_unresolved_conflict_is_not_ready_for_build(settings) -> None:
    ensure_output_folders(settings)
    _, extraction, path = _process_fixture("sample_policy_alpha.txt", "Alpha", settings)
    extraction["rules"][0]["implementation_readiness"] = "ready_for_build"
    extraction["rules"][0]["ambiguities_or_review_flags"] = ["Unresolved conflict"]
    save_json(path, extraction)
    second_path = settings.policy_extracts_dir / "alpha-copy.rules.json"
    save_json(second_path, extraction)
    result, _ = consolidate_policy_extracts(
        [path, second_path], SimulatedLLMClient(), settings
    )
    assert all(
        rule["implementation_readiness"] != "ready_for_build" for rule in result["rules"]
    )


def test_exact_duplicates_merge_and_preserve_every_source(settings) -> None:
    ensure_output_folders(settings)
    _, extraction, first_path = _process_fixture(
        "sample_policy_alpha.txt", "Alpha", settings
    )
    duplicate = load_json(first_path)
    duplicate["document"]["document_name"] = "sample-policy-alpha-copy.txt"
    duplicate["rules"][0]["rule_id"] = "copy-rule-001"
    duplicate["rules"][0]["policy_source"] = {
        **duplicate["rules"][0]["policy_source"],
        "policy_name": "Alpha Successor",
        "document_name": "sample-policy-alpha-copy.txt",
        "quote": "The same fictional requirement appears in a successor policy.",
    }
    second_path = settings.policy_extracts_dir / "alpha-successor.rules.json"
    save_json(second_path, duplicate)

    result, _ = consolidate_policy_extracts(
        [first_path, second_path], SimulatedLLMClient(), settings
    )

    assert len(result["rules"]) == 1
    merged = result["rules"][0]
    assert set(merged["source_rule_ids"]) == {
        extraction["rules"][0]["rule_id"],
        "copy-rule-001",
    }
    assert merged["policy_source"]["additional_sources"][0]["policy_name"] == (
        "Alpha Successor"
    )


def test_stable_ids_do_not_depend_on_input_order(settings) -> None:
    ensure_output_folders(settings)
    _, _, alpha_path = _process_fixture("sample_policy_alpha.txt", "Alpha", settings)
    _, _, beta_path = _process_fixture("sample_policy_beta.txt", "Beta", settings)
    forward, _ = consolidate_policy_extracts(
        [alpha_path, beta_path], SimulatedLLMClient(), settings
    )
    reverse, _ = consolidate_policy_extracts(
        [beta_path, alpha_path], SimulatedLLMClient(), settings
    )
    assert [rule["rule_id"] for rule in forward["rules"]] == [
        rule["rule_id"] for rule in reverse["rules"]
    ]


def test_conflicting_rules_remain_separate_and_require_policy_owner(settings) -> None:
    ensure_output_folders(settings)
    _, _, first_path = _process_fixture("sample_policy_alpha.txt", "Alpha", settings)
    conflicting = load_json(first_path)
    rule = conflicting["rules"][0]
    rule["rule_id"] = "conflicting-rule-001"
    rule["requirement"] = (
        "Applications above 200,000 sample units require a financial statement."
    )
    rule["condition_logic"]["conditions"] = [rule["requirement"]]
    rule["policy_source"]["quote"] = (
        "Applications above 200,000 sample units require a financial statement."
    )
    second_path = settings.policy_extracts_dir / "alpha-conflict.rules.json"
    save_json(second_path, conflicting)

    result, _ = consolidate_policy_extracts(
        [first_path, second_path], SimulatedLLMClient(), settings
    )

    assert len(result["rules"]) == 2
    assert all(
        rule["implementation_readiness"] == "needs_policy_owner_review"
        for rule in result["rules"]
    )
    assert all(
        any("conflict" in flag.lower() for flag in rule["ambiguities_or_review_flags"])
        for rule in result["rules"]
    )
    assert result["processing_summary"]["rules_needing_policy_owner_review"] == 2


def test_explicit_human_review_status_is_preserved(settings) -> None:
    ensure_output_folders(settings)
    _, extraction, first_path = _process_fixture(
        "sample_policy_alpha.txt", "Alpha", settings
    )
    extraction["rules"][0]["human_review_status"] = "approved"
    save_json(first_path, extraction)
    _, _, beta_path = _process_fixture("sample_policy_beta.txt", "Beta", settings)

    result, _ = consolidate_policy_extracts(
        [first_path, beta_path], SimulatedLLMClient(), settings
    )

    alpha_rule = next(
        rule
        for rule in result["rules"]
        if extraction["rules"][0]["rule_id"] in rule["source_rule_ids"]
    )
    assert alpha_rule["human_review_status"] == "approved"


def test_near_duplicates_stay_separate_with_overlap_flags(settings) -> None:
    ensure_output_folders(settings)
    _, _, first_path = _process_fixture("sample_policy_alpha.txt", "Alpha", settings)
    overlapping = load_json(first_path)
    rule = overlapping["rules"][0]
    rule["rule_id"] = "overlapping-rule-001"
    rule["rule_name"] = "Financial statement required over sample threshold"
    rule["check_objective"] = "Check the alternate fictional financial statement rule."
    rule["requirement"] = "Some applications require a recent financial statement."
    rule["condition_logic"]["conditions"] = [rule["requirement"]]
    second_path = settings.policy_extracts_dir / "alpha-overlap.rules.json"
    save_json(second_path, overlapping)

    result, _ = consolidate_policy_extracts(
        [first_path, second_path], SimulatedLLMClient(), settings
    )

    assert len(result["rules"]) == 2
    assert all(
        any("overlap" in flag.lower() for flag in rule["ambiguities_or_review_flags"])
        for rule in result["rules"]
    )
    assert all(
        rule["implementation_readiness"] != "ready_for_build" for rule in result["rules"]
    )
