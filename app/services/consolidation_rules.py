"""Deterministic mechanics for Part 4: normalize, dedup, stable ids, fold, finalize.

This layer owns everything mechanical and trustworthy. The LLM owns semantic judgment only:
near-duplicate *candidates* come from the similarity service (human-folded), and conflict/grouping
comes from the LLM ``group`` operation. The brittle name-similarity conflict matcher is gone.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

RULE_TYPES = {
    "threshold",
    "documentation_requirement",
    "approval_requirement",
    "exception_requirement",
    "eligibility",
    "prohibition",
    "calculation",
    "timing_requirement",
    "monitoring_requirement",
    "covenant_requirement",
    "collateral_requirement",
    "risk_rating_requirement",
    "borrower_requirement",
    "guarantor_requirement",
    "qualitative_review",
    "definition_only",
    "retrieval_only",
}
SEVERITIES = {
    "hard_stop",
    "exception_required",
    "documentation_gap",
    "approval_gap",
    "soft_warning",
    "guidance",
    "definition_only",
}
READINESS_VALUES = {
    "ready_for_build",
    "needs_human_review",
    "needs_policy_owner_review",
    "not_implementable_as_code",
    "retrieval_only",
}
APPLICABILITY_FIELDS = ("products", "portfolios", "borrower_types", "transaction_types", "regions")
RELATIONSHIP_TYPES = {"coincides", "conflicts", "refines", "overlaps", "complements"}


# ---- public API -----------------------------------------------------------------------


def prepare_rules(policy_kbs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize every approved KB's rules, exact-dedup, and assign stable ids."""
    rules = [_normalize_rule(rule) for kb in policy_kbs for rule in kb.get("rules", [])]
    rules = _deduplicate(rules)
    rules.sort(key=lambda rule: rule["rule_id"])
    return rules


def apply_folds(
    rules: list[dict[str, Any]], fold_ops: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Apply human fold decisions: merge source rules into their target, keep target id."""
    by_id = {rule["rule_id"]: rule for rule in rules}
    removed: set[str] = set()
    for op in fold_ops:
        target_id = op["target_id"]
        target = by_id.get(target_id)
        if target is None:
            continue
        for source_id in op.get("source_ids", []):
            source = by_id.get(source_id)
            if source is None or source_id == target_id:
                continue
            _merge_rules(target, source)
            removed.add(source_id)
    return [rule for rule in rules if rule["rule_id"] not in removed]


def assemble_final_kb(
    rules: list[dict[str, Any]],
    rule_groups_raw: list[dict[str, Any]],
    *,
    created_from_documents: list[str],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Attach validated groups, enforce readiness, and build the final KB dict."""
    rules = deepcopy(rules)
    groups = _attach_groups(rules, rule_groups_raw)
    for rule in rules:
        _enforce_readiness(rule)
    rules.sort(key=lambda rule: rule["rule_id"])
    documents = sorted(set(created_from_documents))
    ambiguities = sorted(
        {
            flag
            for rule in rules
            for flag in rule["ambiguities_or_review_flags"]
            if "conflict" in flag.lower() or "overlap" in flag.lower()
        }
    )
    return {
        "schema_version": "1.0.0",
        "knowledge_base_name": "credit_policy_rules_kb",
        "created_from_documents": documents,
        "rules": rules,
        "rule_groups": groups,
        "provenance": provenance,
        "processing_summary": {
            "total_rules": len(rules),
            "total_rule_groups": len(groups),
            "deterministic_rules": sum(
                bool(rule["condition_logic"].get("conditions")) for rule in rules
            ),
            "documentation_check_rules": sum(
                rule["rule_type"] == "documentation_requirement" for rule in rules
            ),
            "approval_check_rules": sum(
                rule["rule_type"] == "approval_requirement" for rule in rules
            ),
            "exception_rules": sum(bool(rule["exception_condition"]) for rule in rules),
            "rules_needing_human_review": sum(
                rule["implementation_readiness"] == "needs_human_review" for rule in rules
            ),
            "rules_needing_policy_owner_review": sum(
                rule["implementation_readiness"] == "needs_policy_owner_review" for rule in rules
            ),
            "rules_ready_for_build": sum(
                rule["implementation_readiness"] == "ready_for_build" for rule in rules
            ),
            "main_takeaways": [
                f"Consolidated {len(rules)} checkable rules and {len(groups)} relationship "
                f"groups from {len(documents)} documents."
            ],
            "major_conflicts_or_ambiguities": ambiguities,
            "recommended_next_steps": [
                "Complete human review before using the KB for credit checks."
            ],
        },
    }


def rule_signature_text(rule: dict[str, Any]) -> str:
    """Stable natural-language text for a rule, used by the similarity service."""
    return _normalized_text(
        " ".join(
            [
                rule.get("rule_name", ""),
                rule.get("requirement", ""),
                rule.get("check_objective", ""),
            ]
        )
    )


# ---- normalization --------------------------------------------------------------------


def _normalize_rule(source: dict[str, Any]) -> dict[str, Any]:
    rule = deepcopy(source)
    flags = list(rule.get("ambiguities_or_review_flags", []))
    rule_type = rule.get("rule_type", "qualitative_review")
    if rule_type not in RULE_TYPES:
        flags.append(f"Unrecognized rule_type '{rule_type}' normalized to qualitative_review.")
        rule_type = "qualitative_review"
    severity = rule.get("severity", "guidance")
    if severity not in SEVERITIES:
        flags.append(f"Unrecognized severity '{severity}' normalized to guidance.")
        severity = "guidance"
    readiness = rule.get("implementation_readiness", "needs_human_review")
    if readiness not in READINESS_VALUES:
        flags.append(
            f"Unrecognized implementation_readiness '{readiness}' normalized to needs_human_review."
        )
        readiness = "needs_human_review"

    source_ids = rule.get("source_rule_ids") or ([rule["rule_id"]] if rule.get("rule_id") else [])
    source_ids = sorted({value for value in source_ids if value})
    normalized = {
        "rule_id": "",
        "source_rule_ids": source_ids,
        "group_ids": [],
        "rule_name": rule.get("rule_name", "Unnamed rule"),
        "rule_type": rule_type,
        "policy_source": _normalize_policy_source(rule.get("policy_source", {})),
        "applies_to": {
            field: _unique(rule.get("applies_to", {}).get(field, []))
            for field in APPLICABILITY_FIELDS
        },
        "requirement": rule.get("requirement", ""),
        "check_objective": rule.get("check_objective", ""),
        "credit_documentation_fields_needed": _unique(
            rule.get("credit_documentation_fields_needed", [])
        ),
        "condition_logic": rule.get("condition_logic") or {"logic_type": "all", "conditions": []},
        "evidence_required": _unique(rule.get("evidence_required", [])),
        "pass_condition": rule.get("pass_condition", ""),
        "fail_condition": rule.get("fail_condition", ""),
        "exception_condition": rule.get("exception_condition", ""),
        "severity": severity,
        "expected_output": rule.get("expected_output")
        or {"pass_message": "", "fail_message": "", "exception_message": ""},
        "test_cases": _unique(rule.get("test_cases", [])),
        "ambiguities_or_review_flags": _unique(flags),
        "human_review_status": rule.get("human_review_status", "pending_review"),
        "implementation_readiness": readiness,
    }
    normalized["rule_id"] = _stable_rule_id(normalized)
    return normalized


def _normalize_policy_source(source: Any) -> dict[str, Any]:
    if isinstance(source, list):
        sources = [_source_fields(item) for item in source if isinstance(item, dict)]
    elif isinstance(source, dict):
        additional = source.get("additional_sources", [])
        sources = [_source_fields(source)] + [
            _source_fields(item) for item in additional if isinstance(item, dict)
        ]
    else:
        sources = [_source_fields({})]
    sources = _unique(sources)
    primary = sources[0] if sources else _source_fields({})
    if len(sources) > 1:
        primary["additional_sources"] = sources[1:]
    return primary


def _source_fields(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_id": source.get("policy_id", ""),
        "policy_name": source.get("policy_name", ""),
        "policy_version": source.get("policy_version", ""),
        "document_name": source.get("document_name", ""),
        "section": source.get("section", ""),
        "page": source.get("page"),
        "quote": source.get("quote", ""),
    }


def _stable_rule_id(rule: dict[str, Any]) -> str:
    return f"cpr-{hashlib.sha256(_signature(rule).encode('utf-8')).hexdigest()[:12]}"


def _signature(rule: dict[str, Any]) -> str:
    core = {
        "rule_type": rule["rule_type"],
        "requirement": _normalized_text(rule["requirement"]),
        "applies_to": rule["applies_to"],
        "fields": sorted(rule["credit_documentation_fields_needed"]),
        "condition_logic": rule["condition_logic"],
        "evidence": sorted(rule["evidence_required"]),
        "pass_condition": _normalized_text(rule["pass_condition"]),
        "fail_condition": _normalized_text(rule["fail_condition"]),
        "exception_condition": _normalized_text(rule["exception_condition"]),
    }
    return json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---- dedup / fold merge ---------------------------------------------------------------


def _deduplicate(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_signature: dict[str, dict[str, Any]] = {}
    for rule in rules:
        signature = _signature(rule)
        if signature not in by_signature:
            by_signature[signature] = rule
            continue
        _merge_rules(by_signature[signature], rule)
    return list(by_signature.values())


def _merge_rules(target: dict[str, Any], other: dict[str, Any]) -> None:
    target["source_rule_ids"] = sorted(set(target["source_rule_ids"] + other["source_rule_ids"]))
    target["policy_source"] = _merge_sources(target["policy_source"], other["policy_source"])
    for key in (
        "credit_documentation_fields_needed",
        "evidence_required",
        "test_cases",
        "ambiguities_or_review_flags",
        "group_ids",
    ):
        target[key] = _unique(target[key] + other[key])
    for field in APPLICABILITY_FIELDS:
        target["applies_to"][field] = _unique(
            target["applies_to"][field] + other["applies_to"][field]
        )
    target["human_review_status"] = _merge_review_status(
        target["human_review_status"], other["human_review_status"]
    )
    target["implementation_readiness"] = _more_cautious_readiness(
        target["implementation_readiness"], other["implementation_readiness"]
    )


def _merge_sources(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    sources = [_source_fields(first)] + first.get("additional_sources", [])
    sources += [_source_fields(second)] + second.get("additional_sources", [])
    sources = _unique([_source_fields(source) for source in sources])
    result = sources[0]
    if len(sources) > 1:
        result["additional_sources"] = sources[1:]
    return result


# ---- groups + readiness ---------------------------------------------------------------


def _attach_groups(
    rules: list[dict[str, Any]], rule_groups_raw: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {rule["rule_id"]: rule for rule in rules}
    groups: list[dict[str, Any]] = []
    for raw in rule_groups_raw:
        members = _unique([rid for rid in raw.get("member_rule_ids", []) if rid in by_id])
        if len(members) < 2:
            continue  # a group needs at least two surviving members
        relationship = raw.get("relationship_type", "overlaps")
        if relationship not in RELATIONSHIP_TYPES:
            relationship = "overlaps"
        group = {
            "group_id": _stable_group_id(members, relationship),
            "theme": raw.get("theme", "Related rules"),
            "relationship_type": relationship,
            "member_rule_ids": sorted(members),
            "rationale": raw.get("rationale", ""),
            "human_review_status": raw.get("human_review_status", "pending_review"),
        }
        groups.append(group)
        for member in members:
            rule = by_id[member]
            rule["group_ids"] = _unique(rule["group_ids"] + [group["group_id"]])
            if relationship == "conflicts":
                rule["implementation_readiness"] = "needs_policy_owner_review"
                rule["ambiguities_or_review_flags"] = _unique(
                    rule["ambiguities_or_review_flags"]
                    + [f"Possible policy conflict flagged in group {group['group_id']}."]
                )
    groups.sort(key=lambda group: group["group_id"])
    return groups


def _stable_group_id(members: list[str], relationship: str) -> str:
    payload = json.dumps([sorted(members), relationship], sort_keys=True)
    return f"grp-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def _enforce_readiness(rule: dict[str, Any]) -> None:
    flags = rule["ambiguities_or_review_flags"]
    has_conflict = any("conflict" in flag.lower() for flag in flags)
    source = rule["policy_source"]
    has_source_support = bool(
        source.get("policy_name") and source.get("document_name") and source.get("quote")
    )
    has_check_logic = bool(
        rule["credit_documentation_fields_needed"]
        and rule["condition_logic"].get("conditions")
        and rule["pass_condition"]
        and rule["fail_condition"]
    )
    if has_conflict:
        rule["implementation_readiness"] = "needs_policy_owner_review"
    elif rule["implementation_readiness"] == "ready_for_build" and (
        not has_source_support or not has_check_logic or flags
    ):
        rule["implementation_readiness"] = "needs_human_review"
    if not has_source_support:
        rule["ambiguities_or_review_flags"] = _unique(
            flags + ["Missing source support; human review is required."]
        )
    if not has_check_logic:
        rule["ambiguities_or_review_flags"] = _unique(
            rule["ambiguities_or_review_flags"]
            + ["Missing check logic or required document fields; human review is required."]
        )


def _merge_review_status(first: str, second: str) -> str:
    return first if first == second else "pending_review"


def _more_cautious_readiness(first: str, second: str) -> str:
    rank = {
        "ready_for_build": 0,
        "needs_human_review": 1,
        "retrieval_only": 2,
        "not_implementable_as_code": 3,
        "needs_policy_owner_review": 4,
    }
    return max((first, second), key=lambda value: rank[value])


def _unique(items: list[Any]) -> list[Any]:
    result = []
    seen = set()
    for item in items:
        marker = json.dumps(item, sort_keys=True, ensure_ascii=True)
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()
