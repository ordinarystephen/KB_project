"""Swappable deterministic and Azure OpenAI structured-output clients."""

from abc import ABC, abstractmethod
import json
from pathlib import Path
from typing import Any

from .config import Settings


class LLMClient(ABC):
    """Small provider-neutral interface for the three workflow operations."""

    @abstractmethod
    def generate(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a structured response for a named workflow operation."""


def _policy_source(payload: dict[str, Any], quote: str) -> dict[str, Any]:
    metadata = payload.get("policy_metadata", {})
    document = payload["document"]
    return {
        "policy_name": metadata.get("policy_name") or Path(document["document_name"]).stem,
        "policy_version": metadata.get("policy_version", "simulated-v1"),
        "document_name": document["document_name"],
        "section": "Simulated requirements",
        "page": None,
        "quote": quote,
    }


def _base_rule(payload: dict[str, Any], index: int) -> dict[str, Any]:
    document = payload["document"]
    doc_id = document["document_id"]
    is_alpha = "100,000" in payload["document_text"]
    if is_alpha:
        name = "Financial statement required above sample threshold"
        rule_type = "threshold"
        requirement = "Applications above 100,000 sample units require a financial statement."
        fields = ["requested_amount", "borrower_financial_statement", "exception_approval"]
        quote = (
            "Applications above 100,000 sample units must include a current borrower "
            "financial statement."
        )
        severity = "documentation_gap"
        exception_condition = (
            "Pass with exception when Senior Reviewer approval evidence is attached."
        )
    else:
        name = "Credit memo must identify borrower and amount"
        rule_type = "documentation_requirement"
        requirement = "The credit memo must state the borrower name and requested amount."
        fields = ["borrower_name", "requested_amount"]
        quote = "every sample credit memo [must] state the requested amount and borrower name"
        severity = "documentation_gap"
        exception_condition = ""
    return {
        "rule_id": f"{doc_id}-rule-{index:03d}",
        "rule_name": name,
        "rule_type": rule_type,
        "policy_source": _policy_source(payload, quote),
        "applies_to": {
            "products": ["sample_credit"],
            "portfolios": [],
            "borrower_types": [],
            "transaction_types": [],
            "regions": [],
        },
        "requirement": requirement,
        "normalized_requirement": requirement,
        "check_objective": f"Check whether {name.lower()}.",
        "credit_documentation_fields_needed": fields,
        "condition_logic": {"logic_type": "all", "conditions": [requirement]},
        "evidence_required": fields[1:],
        "approval_required": is_alpha,
        "approver_roles": ["Senior Reviewer"] if is_alpha else [],
        "exceptions": [exception_condition] if exception_condition else [],
        "pass_condition": (
            "All required fields and evidence are present and satisfy the requirement."
        ),
        "fail_condition": (
            "One or more required fields or evidence are missing or do not satisfy the "
            "requirement."
        ),
        "exception_condition": exception_condition,
        "severity": severity,
        "expected_output": {
            "pass_message": "Policy check passed.",
            "fail_message": "Required policy evidence is missing or insufficient.",
            "exception_message": "Policy check passed with documented exception.",
        },
        "source_references": [_policy_source(payload, quote)],
        "implementation_notes": [],
        "test_cases": [
            {"name": "required evidence present", "expected": "pass"},
            {"name": "required evidence absent", "expected": "fail"},
        ],
        "ambiguities_or_review_flags": [],
        "human_review_status": "pending_review",
        "implementation_readiness": "needs_human_review",
    }


class SimulatedLLMClient(LLMClient):
    """Deterministic offline implementation used by tests and demos."""

    def generate(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation == "extract":
            return self._extract(payload)
        if operation == "review":
            return self._review(payload)
        if operation == "consolidate":
            return self._consolidate(payload)
        raise ValueError(f"Unsupported LLM operation: {operation}")

    def _extract(self, payload: dict[str, Any]) -> dict[str, Any]:
        rule = _base_rule(payload, 1)
        metadata = payload.get("policy_metadata", {})
        document = payload["document"]
        return {
            "schema_version": "1.0.0",
            "extraction_run_id": f"extract-{document['content_hash'][:12]}",
            "document": document,
            "policy_metadata": {
                "policy_name": metadata.get("policy_name") or Path(document["document_name"]).stem,
                "document_name": document["document_name"],
                "policy_version": metadata.get("policy_version", "simulated-v1"),
                "effective_date": "",
                "owner": "",
                "business_domain": "credit",
                "extraction_date": "simulated",
                "extraction_limitations": ["Generated by deterministic simulated mode."],
            },
            "rules": [rule],
            "definitions": [],
            "unresolved_questions_for_policy_owner": [],
            "sections_not_extracted": [],
            "quality_control_summary": {
                "number_of_rules_extracted": 1,
                "number_of_rules_with_ambiguity": 0,
                "number_of_threshold_rules": int(rule["rule_type"] == "threshold"),
                "number_of_exception_rules": int(bool(rule["exception_condition"])),
                "overall_completeness_assessment": "Suitable for simulated workflow testing.",
            },
            "processing_summary": {
                "main_takeaways": [rule["rule_name"]],
                "important_rules_identified": [rule["rule_id"]],
                "key_thresholds_or_limits": (
                    ["100,000 sample units"] if rule["rule_type"] == "threshold" else []
                ),
                "approval_requirements": rule["approver_roles"],
                "documentation_requirements": rule["credit_documentation_fields_needed"],
                "major_ambiguities": [],
                "recommended_next_steps": ["Complete human policy review."],
            },
        }

    def _review(self, payload: dict[str, Any]) -> dict[str, Any]:
        extraction = payload["extraction"]
        weak = [
            rule["rule_id"]
            for rule in extraction["rules"]
            if not rule.get("source_references")
        ]
        ready = not weak and bool(extraction["rules"])
        return {
            "schema_version": "1.0.0",
            "reviewed_extraction": payload["extraction_path"],
            "missing_rules": [],
            "missing_thresholds": [],
            "missing_approval_requirements": [],
            "missing_documentation_requirements": [],
            "weak_source_references": weak,
            "ambiguous_rules": [],
            "rules_needing_split": [],
            "rules_needing_policy_owner_review": [],
            "non_checkable_rules": [],
            "rules_missing_conditions": [],
            "rules_missing_fields": [],
            "ready_for_consolidation": ready,
            "usable_for_credit_documentation_checks": ready,
            "processing_summary": {
                "main_takeaways": ["Simulated completeness review completed."],
                "potential_gaps": weak,
                "high_priority_reviewer_issues": [],
                "ready_for_consolidation": ready,
                "usable_for_credit_documentation_checks": ready,
                "recommended_next_steps": ["Complete human review before implementation."],
            },
        }

    def _consolidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        extractions = payload["extractions"]
        rules = []
        for extraction in extractions:
            for source_rule in extraction["rules"]:
                if not _is_checkable(source_rule):
                    continue
                flags = " ".join(source_rule.get("ambiguities_or_review_flags", [])).lower()
                readiness = source_rule.get("implementation_readiness", "needs_human_review")
                if "conflict" in flags:
                    readiness = "needs_policy_owner_review"
                rules.append(_to_final_rule(source_rule, len(rules) + 1, readiness))
        documents = [extraction["document"]["document_name"] for extraction in extractions]
        conflicts = [
            rule["rule_id"]
            for extraction in extractions
            for rule in extraction["rules"]
            if "conflict" in " ".join(rule.get("ambiguities_or_review_flags", [])).lower()
        ]
        return {
            "schema_version": "1.0.0",
            "knowledge_base_name": "credit_policy_rules_kb",
            "created_from_documents": documents,
            "rules": rules,
            "processing_summary": {
                "total_rules": len(rules),
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
                    rule["implementation_readiness"] == "needs_human_review"
                    for rule in rules
                ),
                "rules_needing_policy_owner_review": sum(
                    rule["implementation_readiness"] == "needs_policy_owner_review"
                    for rule in rules
                ),
                "rules_ready_for_build": sum(
                    rule["implementation_readiness"] == "ready_for_build"
                    for rule in rules
                ),
                "main_takeaways": [
                    f"Consolidated {len(rules)} checkable rules from "
                    f"{len(documents)} documents."
                ],
                "major_conflicts_or_ambiguities": conflicts,
                "recommended_next_steps": [
                    "Complete human review before using rules for decisions."
                ],
            },
        }


def _is_checkable(rule: dict[str, Any]) -> bool:
    return bool(
        rule.get("credit_documentation_fields_needed")
        and rule.get("pass_condition")
        and rule.get("fail_condition")
        and rule.get("policy_source")
        and rule.get("rule_type") not in {"definition_only", "retrieval_only"}
    )


def _to_final_rule(
    source: dict[str, Any], index: int, readiness: str
) -> dict[str, Any]:
    policy_source = source["policy_source"]
    return {
        "rule_id": f"cpr-{index:04d}",
        "source_rule_ids": [source["rule_id"]],
        "rule_name": source["rule_name"],
        "rule_type": source["rule_type"],
        "policy_source": {
            "policy_name": policy_source.get("policy_name", ""),
            "policy_version": policy_source.get("policy_version", ""),
            "document_name": policy_source.get("document_name", ""),
            "section": policy_source.get("section", ""),
            "page": policy_source.get("page"),
            "quote": policy_source.get("quote", ""),
        },
        "applies_to": source["applies_to"],
        "requirement": source["requirement"],
        "check_objective": source["check_objective"],
        "credit_documentation_fields_needed": source["credit_documentation_fields_needed"],
        "condition_logic": source["condition_logic"],
        "evidence_required": source["evidence_required"],
        "pass_condition": source["pass_condition"],
        "fail_condition": source["fail_condition"],
        "exception_condition": source["exception_condition"],
        "severity": source["severity"],
        "expected_output": source["expected_output"],
        "test_cases": source["test_cases"],
        "human_review_status": source.get("human_review_status", "pending_review"),
        "implementation_readiness": readiness,
    }


class AzureOpenAILLMClient(LLMClient):
    """AAD-authenticated Azure OpenAI implementation for the target environment."""

    def __init__(self, settings: Settings):
        if not settings.azure_openai_endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT is required in azure mode")
        self.settings = settings

    def _create_llm(self):
        """Construct per call so deployment context changes are respected."""
        from langchain_openai import AzureChatOpenAI

        from .azure_auth import get_cognitive_services_token_provider

        return AzureChatOpenAI(
            azure_endpoint=self.settings.azure_openai_endpoint,
            azure_deployment=self.settings.azure_openai_deployment,
            azure_ad_token_provider=get_cognitive_services_token_provider(),
            api_version=self.settings.azure_openai_api_version,
            temperature=0,
            model_kwargs={"response_format": {"type": "json_object"}},
        )

    def generate(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        prompt_names = {
            "extract": "policy_rule_extraction.md",
            "review": "policy_completeness_review.md",
            "consolidate": "policy_kb_consolidation.md",
        }
        schema_names = {
            "extract": "extracted_policy_rules.schema.json",
            "review": "policy_review.schema.json",
            "consolidate": "credit_policy_rules_kb.schema.json",
        }
        try:
            prompt_path = self.settings.prompts_dir / prompt_names[operation]
            schema_path = self.settings.schemas_dir / schema_names[operation]
        except KeyError as exc:
            raise ValueError(f"Unsupported LLM operation: {operation}") from exc
        system_prompt = prompt_path.read_text(encoding="utf-8")
        system_prompt += "\n\nRequired JSON Schema:\n"
        system_prompt += schema_path.read_text(encoding="utf-8")
        response = self._create_llm().invoke(
            [
                ("system", system_prompt),
                ("user", json.dumps(payload, ensure_ascii=False)),
            ]
        )
        result = json.loads(response.content)
        if not isinstance(result, dict):
            raise ValueError("Azure OpenAI returned a non-object JSON response")
        return result


def create_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_mode == "simulated":
        return SimulatedLLMClient()
    if settings.llm_mode == "azure":
        return AzureOpenAILLMClient(settings)
    raise ValueError("KB_LLM_MODE must be 'simulated' or 'azure'")
