"""Normalize raw LLM output into schema-valid artifacts before validation/persistence.

A live model frequently omits structurally-required fields (``condition_logic.logic_type``,
``expected_output`` messages, verification ``processing_summary`` keys). Rather than fail the whole
extraction/verification, fill safe structural defaults and flag any missing *content* so the draft
saves and the human sees exactly what to complete.
"""

from __future__ import annotations

from typing import Any

from .consolidation_rules import (
    APPLICABILITY_FIELDS,
    READINESS_VALUES,
    RULE_TYPES,
    SEVERITIES,
)


def _text(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else default


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _follow_up(related: str, kind: str, description: str) -> dict[str, Any]:
    return {
        "item_id": f"fu-{kind}-{related}",
        "kind": kind,
        "description": description,
        "related_rule_id": related,
        "status": "open",
        "resolution": None,
    }


def normalize_policy_rule(
    rule: Any, index: int, policy_meta: dict[str, Any], document_name: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a schema-valid per-policy rule plus any follow-ups for missing content."""
    rule = rule if isinstance(rule, dict) else {}
    flags = [
        flag for flag in _list(rule.get("ambiguities_or_review_flags")) if isinstance(flag, str)
    ]
    follow_ups: list[dict[str, Any]] = []

    rule_id = _text(rule.get("rule_id")) or f"{policy_meta['policy_id']}-rule-{index:03d}"
    name = _text(rule.get("rule_name"))
    if not name:
        name = "Unnamed rule"
        flags.append(f"Rule {rule_id} was missing a name; placeholder inserted.")
    requirement = _text(rule.get("requirement"))
    if not requirement:
        requirement = "Requirement not captured; complete from source."
        follow_ups.append(
            _follow_up(
                rule_id, "missing_requirement", f"Rule {rule_id} is missing its requirement."
            )
        )
    rule_type = (
        rule.get("rule_type") if rule.get("rule_type") in RULE_TYPES else "qualitative_review"
    )
    severity = rule.get("severity") if rule.get("severity") in SEVERITIES else "guidance"
    readiness = (
        rule.get("implementation_readiness")
        if rule.get("implementation_readiness") in READINESS_VALUES
        else "needs_human_review"
    )

    source = rule.get("policy_source") if isinstance(rule.get("policy_source"), dict) else {}
    applies = rule.get("applies_to") if isinstance(rule.get("applies_to"), dict) else {}
    condition = rule.get("condition_logic") if isinstance(rule.get("condition_logic"), dict) else {}
    expected = rule.get("expected_output") if isinstance(rule.get("expected_output"), dict) else {}

    policy_source = {
        "policy_id": policy_meta["policy_id"],
        "policy_name": policy_meta["policy_name"],
        "policy_version": _text(source.get("policy_version"))
        or _text(policy_meta.get("policy_version")),
        "document_name": document_name,
        "section": _text(source.get("section")),
        "page": source.get("page") if isinstance(source.get("page"), int) else None,
        "quote": _text(source.get("quote")),
    }
    additional = source.get("additional_sources")
    if isinstance(additional, list) and additional:
        policy_source["additional_sources"] = additional

    normalized = {
        "rule_id": rule_id,
        "rule_name": name,
        "rule_type": rule_type,
        "policy_source": policy_source,
        "applies_to": {field: _list(applies.get(field)) for field in APPLICABILITY_FIELDS},
        "requirement": requirement,
        "check_objective": _text(rule.get("check_objective")) or requirement,
        "credit_documentation_fields_needed": _list(rule.get("credit_documentation_fields_needed")),
        "condition_logic": {
            "logic_type": _text(condition.get("logic_type")) or "all",
            "conditions": _list(condition.get("conditions")),
        },
        "evidence_required": _list(rule.get("evidence_required")),
        "pass_condition": _text(rule.get("pass_condition")),
        "fail_condition": _text(rule.get("fail_condition")),
        "exception_condition": _text(rule.get("exception_condition")),
        "severity": severity,
        "expected_output": {
            "pass_message": _text(expected.get("pass_message")),
            "fail_message": _text(expected.get("fail_message")),
            "exception_message": _text(expected.get("exception_message")),
        },
        "test_cases": _list(rule.get("test_cases")),
        "ambiguities_or_review_flags": flags,
        "human_review_status": "pending_review",
        "implementation_readiness": readiness,
    }
    return normalized, follow_ups


def normalize_policy_rules(
    rules: Any, policy_meta: dict[str, Any], document_name: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_rules: list[dict[str, Any]] = []
    extra_follow_ups: list[dict[str, Any]] = []
    for index, rule in enumerate(_list(rules), 1):
        normalized, follow_ups = normalize_policy_rule(rule, index, policy_meta, document_name)
        normalized_rules.append(normalized)
        extra_follow_ups.extend(follow_ups)
    return normalized_rules, extra_follow_ups


def normalize_follow_up_items(items: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(_list(items), 1):
        item = raw if isinstance(raw, dict) else {}
        normalized.append(
            {
                "item_id": _text(item.get("item_id")) or f"fu-{index:03d}",
                "kind": _text(item.get("kind")) or "general",
                "description": _text(item.get("description")) or "Unspecified follow-up item.",
                "related_rule_id": item.get("related_rule_id")
                if isinstance(item.get("related_rule_id"), str)
                else None,
                "status": item.get("status")
                if item.get("status") in {"open", "resolved"}
                else "open",
                "resolution": item.get("resolution")
                if isinstance(item.get("resolution"), str)
                else None,
            }
        )
    return normalized


_VERIFICATION_ARRAYS = (
    "missing_rules",
    "missing_thresholds",
    "missing_approval_requirements",
    "missing_documentation_requirements",
    "weak_source_references",
    "ambiguous_rules",
    "rules_needing_split",
    "rules_needing_policy_owner_review",
    "non_checkable_rules",
    "rules_missing_conditions",
    "rules_missing_fields",
)


def normalize_verification(result: Any) -> dict[str, Any]:
    """Fill the structurally-required verification fields a live model may omit."""
    result = result if isinstance(result, dict) else {}
    summary = (
        result.get("processing_summary")
        if isinstance(result.get("processing_summary"), dict)
        else {}
    )
    ready = bool(result.get("ready_for_consolidation"))
    usable = bool(result.get("usable_for_credit_documentation_checks"))
    normalized = {
        "schema_version": "1.0.0",
        "reviewed_policy_kb": _text(result.get("reviewed_policy_kb")) or "unknown",
        "ready_for_consolidation": ready,
        "usable_for_credit_documentation_checks": usable,
        "processing_summary": {
            "main_takeaways": _list(summary.get("main_takeaways")),
            "potential_gaps": _list(summary.get("potential_gaps")),
            "high_priority_reviewer_issues": _list(summary.get("high_priority_reviewer_issues")),
            "ready_for_consolidation": ready,
            "usable_for_credit_documentation_checks": usable,
            "recommended_next_steps": _list(summary.get("recommended_next_steps")),
        },
    }
    for key in _VERIFICATION_ARRAYS:
        normalized[key] = _list(result.get(key))
    return normalized
