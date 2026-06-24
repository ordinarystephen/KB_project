"""Regression tests for hardening fixes (Azure-shaped failure modes, data-loss guards)."""

import os
from pathlib import Path

from app.services.document_loader import extract_document, save_uploaded_document
from app.services.enrichment_service import enrich_policy_kb
from app.services.extraction_service import extract_policy_rules
from app.services.file_utils import ensure_output_folders, relative_to_project
from app.services.json_utils import load_json, validate_json
from app.services.llm_client import SimulatedLLMClient
from app.services.policy_kb_store import load_policy_kb
from app.services.proxy_utils import ensure_direct_connection
from app.services.verification_service import verify_policy_kb

FIXTURES = Path(__file__).parent / "fixtures"


def _extract(fixture_name, policy_name, settings, client):
    source = save_uploaded_document(fixture_name, (FIXTURES / fixture_name).read_bytes(), settings)
    text, document = extract_document(source, settings)
    return extract_policy_rules(text, document, policy_name, "v1", client, settings)


class _WrongPathVerifyClient(SimulatedLLMClient):
    """Simulates an Azure model that fills reviewed_policy_kb with a value it cannot know."""

    def _verify(self, payload):
        result = super()._verify(payload)
        result["reviewed_policy_kb"] = "hallucinated/elsewhere.json"
        return result


class _EmptyEnrichClient(SimulatedLLMClient):
    """Simulates an enrichment response that returns no rules."""

    def _enrich(self, payload):
        return {"rules": [], "follow_up_items": []}


class _TamperedIdentityClient(SimulatedLLMClient):
    """Simulates a model that emits the wrong policy identity inside each citation."""

    def _extract(self, payload):
        result = super()._extract(payload)
        for rule in result["rules"]:
            rule["policy_source"]["policy_id"] = "tampered"
            rule["policy_source"]["policy_name"] = "Tampered Name"
            rule["policy_source"]["document_name"] = "tampered.txt"
        return result


class _IncompleteExtractClient(SimulatedLLMClient):
    """Simulates a model that omits most structurally-required rule fields."""

    def _extract(self, payload):
        return {
            "rules": [
                {
                    "rule_name": "Sparse rule",
                    "rule_type": "documentation_requirement",
                    "requirement": "A credit memo is required.",
                    "policy_source": {"section": "1", "page": 3, "quote": "memo required"},
                }
            ],
            "follow_up_items": [{"description": "check this later"}],
        }


class _MinimalVerifyClient(SimulatedLLMClient):
    """Simulates a verification response missing processing_summary and the array fields."""

    def _verify(self, payload):
        return {"ready_for_consolidation": True}


def test_verify_overrides_model_supplied_reviewed_path(settings) -> None:
    ensure_output_folders(settings)
    client = _WrongPathVerifyClient()
    kb, kb_path = _extract("sample_policy_alpha.txt", "Alpha", settings, client)
    result, saved = verify_policy_kb(kb_path, client, settings)
    expected = relative_to_project(kb_path, settings)
    assert result["reviewed_policy_kb"] == expected
    assert load_json(saved)["reviewed_policy_kb"] == expected


def test_enrich_does_not_wipe_rules_on_empty_response(settings) -> None:
    ensure_output_folders(settings)
    client = _EmptyEnrichClient()
    kb, kb_path = _extract("sample_policy_alpha.txt", "Alpha", settings, client)
    original_count = len(kb["rules"])
    assert original_count > 0
    verify_policy_kb(kb_path, client, settings)
    verification = settings.verifications_dir / f"{kb['policy']['policy_id']}.verification.json"
    enriched, _ = enrich_policy_kb(kb_path, verification, client, settings)
    assert len(enriched["rules"]) == original_count


def test_extraction_forces_authoritative_citation_identity(settings) -> None:
    ensure_output_folders(settings)
    kb, _ = _extract("sample_policy_alpha.txt", "Policy Alpha", settings, _TamperedIdentityClient())
    assert kb["policy"]["policy_id"] == "policy-alpha"
    for rule in kb["rules"]:
        source = rule["policy_source"]
        assert source["policy_id"] == "policy-alpha"
        assert source["policy_name"] == "Policy Alpha"
        assert source["document_name"] == kb["policy"]["document_name"]


def test_reextract_archives_non_draft_kb_instead_of_clobbering(settings) -> None:
    ensure_output_folders(settings)
    client = SimulatedLLMClient()
    kb, kb_path = _extract("sample_policy_alpha.txt", "Alpha", settings, client)
    verify_policy_kb(kb_path, client, settings)  # advance off 'draft'
    assert load_policy_kb(kb_path)["status"] == "verified"

    # Re-extract the same policy: prior verified work must be archived, not silently lost.
    _extract("sample_policy_alpha.txt", "Alpha", settings, client)
    archived = list(settings.policy_kbs_dir.glob("*.superseded*.yaml"))
    assert archived, "expected the prior non-draft KB to be archived"
    assert load_policy_kb(kb_path)["status"] == "draft"


def test_extracted_text_paths_do_not_collide_on_slug(settings) -> None:
    ensure_output_folders(settings)
    p1 = save_uploaded_document("Report.txt", b"First document body.\n", settings)
    p2 = save_uploaded_document("Report.md", b"Second different body.\n", settings)
    _, r1 = extract_document(p1, settings)
    _, r2 = extract_document(p2, settings)
    assert r1.extracted_text_path != r2.extracted_text_path
    first_text = (settings.project_root / r1.extracted_text_path).read_text(encoding="utf-8")
    assert first_text.strip() == "First document body."


def test_extraction_normalizes_incomplete_model_rules(settings) -> None:
    ensure_output_folders(settings)
    kb, _ = _extract("sample_policy_alpha.txt", "Alpha", settings, _IncompleteExtractClient())
    validate_json(kb, settings.schemas_dir / "policy_kb.schema.json")  # must not hard-fail
    rule = kb["rules"][0]
    assert rule["rule_id"] == "alpha-rule-001"
    assert rule["condition_logic"]["logic_type"] == "all"
    assert set(rule["expected_output"]) == {"pass_message", "fail_message", "exception_message"}
    assert set(rule["applies_to"]) == {
        "products",
        "portfolios",
        "borrower_types",
        "transaction_types",
        "regions",
    }
    assert rule["policy_source"]["policy_id"] == "alpha"
    assert rule["policy_source"]["page"] == 3
    assert kb["follow_up_items"][0]["status"] == "open"


def test_verification_normalizes_incomplete_summary(settings) -> None:
    ensure_output_folders(settings)
    _, kb_path = _extract("sample_policy_alpha.txt", "Alpha", settings, SimulatedLLMClient())
    result, _ = verify_policy_kb(kb_path, _MinimalVerifyClient(), settings)
    validate_json(result, settings.schemas_dir / "policy_verification.schema.json")
    assert set(result["processing_summary"]) >= {
        "main_takeaways",
        "potential_gaps",
        "high_priority_reviewer_issues",
        "ready_for_consolidation",
        "usable_for_credit_documentation_checks",
        "recommended_next_steps",
    }
    assert result["missing_rules"] == []
    assert result["ready_for_consolidation"] is True


def test_ensure_direct_connection_adds_loopback_and_host(monkeypatch) -> None:
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    ensure_direct_connection("https://myresource.openai.azure.com/")
    no_proxy = os.environ["NO_PROXY"]
    assert "localhost" in no_proxy
    assert "myresource.openai.azure.com" in no_proxy
    assert os.environ["no_proxy"] == no_proxy
