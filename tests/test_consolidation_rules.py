"""Unit tests for the deterministic Part-4 engine and similarity service."""

from app.services.consolidation_rules import apply_folds, assemble_final_kb, prepare_rules
from app.services.json_utils import validate_json
from app.services.llm_client import SimulatedLLMClient
from app.services.similarity_service import find_candidates


def _rule(
    rule_id,
    *,
    requirement="The memo states the borrower name and amount.",
    name="Rule",
    policy_id="pol",
    rule_type="documentation_requirement",
    fields=("borrower_name",),
):
    return {
        "rule_id": rule_id,
        "rule_name": name,
        "rule_type": rule_type,
        "policy_source": {
            "policy_id": policy_id,
            "policy_name": f"Policy {policy_id}",
            "policy_version": "v1",
            "document_name": f"{policy_id}.txt",
            "section": "1",
            "page": 1,
            "quote": "verbatim quote",
        },
        "applies_to": {
            "products": [],
            "portfolios": [],
            "borrower_types": [],
            "transaction_types": [],
            "regions": [],
        },
        "requirement": requirement,
        "check_objective": "objective",
        "credit_documentation_fields_needed": list(fields),
        "condition_logic": {"logic_type": "all", "conditions": [requirement]},
        "evidence_required": ["evidence"],
        "pass_condition": "pass",
        "fail_condition": "fail",
        "exception_condition": "",
        "severity": "documentation_gap",
        "expected_output": {"pass_message": "p", "fail_message": "f", "exception_message": ""},
        "test_cases": [],
        "ambiguities_or_review_flags": [],
        "human_review_status": "pending_review",
        "implementation_readiness": "needs_human_review",
    }


def _provenance():
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "model_deployment": "simulated",
        "prompt_versions": {},
        "source_policy_kbs": [],
    }


def test_exact_duplicates_merge_and_preserve_sources() -> None:
    rules = prepare_rules(
        [{"rules": [_rule("a-1", policy_id="a")]}, {"rules": [_rule("b-1", policy_id="b")]}]
    )
    assert len(rules) == 1
    assert set(rules[0]["source_rule_ids"]) == {"a-1", "b-1"}
    assert rules[0]["rule_id"].startswith("cpr-")
    assert rules[0]["policy_source"]["additional_sources"]


def test_apply_folds_merges_target_and_sources() -> None:
    rules = prepare_rules(
        [
            {
                "rules": [
                    _rule("a-1", requirement="The memo states borrower and amount.", policy_id="a")
                ]
            },
            {
                "rules": [
                    _rule(
                        "b-1",
                        requirement="The memo clearly states the borrower and amount.",
                        policy_id="b",
                    )
                ]
            },
        ]
    )
    assert len(rules) == 2
    target, other = rules[0]["rule_id"], rules[1]["rule_id"]
    folded = apply_folds(rules, [{"target_id": target, "source_ids": [other]}])
    assert len(folded) == 1
    assert set(folded[0]["source_rule_ids"]) == {"a-1", "b-1"}


def test_conflict_group_downgrades_readiness(settings) -> None:
    rules = prepare_rules(
        [
            {"rules": [_rule("a-1", requirement="Threshold is 100000.", policy_id="a")]},
            {"rules": [_rule("b-1", requirement="Threshold is 250000.", policy_id="b")]},
        ]
    )
    ids = [rule["rule_id"] for rule in rules]
    groups_raw = [
        {
            "theme": "Conflicting thresholds",
            "relationship_type": "conflicts",
            "member_rule_ids": ids,
            "rationale": "Different thresholds for the same standard.",
            "human_review_status": "pending_review",
        }
    ]
    final = assemble_final_kb(
        rules, groups_raw, created_from_documents=["a.txt", "b.txt"], provenance=_provenance()
    )
    validate_json(final, settings.schemas_dir / "credit_policy_rules_kb.schema.json")
    assert all(
        rule["implementation_readiness"] == "needs_policy_owner_review" for rule in final["rules"]
    )
    assert final["rule_groups"][0]["relationship_type"] == "conflicts"
    assert all(group_id for rule in final["rules"] for group_id in rule["group_ids"])


def test_groups_with_fewer_than_two_valid_members_are_dropped(settings) -> None:
    rules = prepare_rules([{"rules": [_rule("a-1", policy_id="a")]}])
    groups_raw = [
        {
            "theme": "Dangling",
            "relationship_type": "overlaps",
            "member_rule_ids": [rules[0]["rule_id"], "cpr-does-not-exist"],
            "rationale": "",
            "human_review_status": "pending_review",
        }
    ]
    final = assemble_final_kb(
        rules, groups_raw, created_from_documents=["a.txt"], provenance=_provenance()
    )
    assert final["rule_groups"] == []


def test_similarity_flags_only_near_duplicates(settings) -> None:
    rules = prepare_rules(
        [
            {
                "rules": [
                    _rule(
                        "a-1",
                        name="Memo identifies borrower",
                        requirement="The memo states the borrower name and amount.",
                        policy_id="a",
                    )
                ]
            },
            {
                "rules": [
                    _rule(
                        "b-1",
                        name="Memo identifies borrower",
                        requirement="The memo clearly states the borrower name and the amount.",
                        policy_id="b",
                    )
                ]
            },
            {
                "rules": [
                    _rule(
                        "c-1",
                        name="Financial statement threshold",
                        requirement="Loans over 100000 require a financial statement.",
                        rule_type="threshold",
                        policy_id="c",
                        fields=("requested_amount",),
                    )
                ]
            },
        ]
    )
    candidates = find_candidates(rules, SimulatedLLMClient(), settings)
    assert len(candidates) == 1
    assert len(candidates[0]["members"]) == 2
