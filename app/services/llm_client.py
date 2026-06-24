"""Swappable deterministic and Azure OpenAI structured-output clients.

Operations:
- ``extract``  (Part 1): policy text -> draft rules + follow-up items
- ``verify``   (Part 2): re-read source vs draft -> completeness findings
- ``enrich``   (Part 3): gap-fill the draft using the verification findings
- ``group``    (Part 4c): cross-policy relationship grouping over stable rule ids

The LLM returns only the content it generates; deterministic services own provenance, ids, dedup,
fold application, and schema validation.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from .config import Settings


def _safe_schema_title(title: str) -> str:
    """OpenAI's json_schema response-format name must match ^[a-zA-Z0-9_-]+$.

    Schema ``title`` values may contain spaces (e.g. "Policy Completeness Verification"); sanitize
    them so the Azure Structured Outputs request is accepted.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(title)).strip("_")
    return cleaned or "schema"


class LLMClient(ABC):
    """Provider-neutral interface for the workflow operations and embeddings."""

    @abstractmethod
    def generate(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a structured response for a named workflow operation."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors. Only the Azure client implements this."""
        raise NotImplementedError("Embeddings are not available for this client")


# --------------------------------------------------------------------------------------
# Simulated (offline) client
# --------------------------------------------------------------------------------------


def _sim_policy_source(
    meta: dict[str, Any], document: dict[str, Any], *, section: str, page: int, quote: str
) -> dict[str, Any]:
    return {
        "policy_id": meta["policy_id"],
        "policy_name": meta["policy_name"],
        "policy_version": meta.get("policy_version") or "simulated-v1",
        "document_name": document["document_name"],
        "section": section,
        "page": page,
        "quote": quote,
    }


def _sim_applies_to() -> dict[str, list]:
    return {
        "products": ["sample_credit"],
        "portfolios": [],
        "borrower_types": [],
        "transaction_types": [],
        "regions": [],
    }


def _sim_threshold_rule(meta: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": f"{meta['policy_id']}-rule-001",
        "rule_name": "Financial statement required above sample threshold",
        "rule_type": "threshold",
        "policy_source": _sim_policy_source(
            meta,
            document,
            section="2. Thresholds",
            page=2,
            quote=(
                "Applications above 100,000 sample units must include a current borrower "
                "financial statement."
            ),
        ),
        "applies_to": _sim_applies_to(),
        "requirement": (
            "Applications above 100,000 sample units require a current borrower "
            "financial statement."
        ),
        "check_objective": (
            "Check whether a current financial statement is attached when the requested amount "
            "exceeds 100,000 sample units."
        ),
        "credit_documentation_fields_needed": [
            "requested_amount",
            "borrower_financial_statement",
            "exception_approval",
        ],
        "condition_logic": {
            "logic_type": "all",
            "conditions": ["requested_amount > 100000", "borrower_financial_statement is present"],
        },
        "evidence_required": ["borrower_financial_statement"],
        "pass_condition": (
            "A current borrower financial statement is attached when requested_amount "
            "exceeds 100,000."
        ),
        "fail_condition": (
            "requested_amount exceeds 100,000 and no current borrower financial statement "
            "is attached."
        ),
        "exception_condition": (
            "Pass with exception when Senior Reviewer approval evidence is attached."
        ),
        "severity": "documentation_gap",
        "expected_output": {
            "pass_message": "Policy check passed.",
            "fail_message": "Required financial statement is missing.",
            "exception_message": "Policy check passed with documented exception.",
        },
        "test_cases": [
            {"name": "financial statement present above threshold", "expected": "pass"},
            {"name": "financial statement missing above threshold", "expected": "fail"},
        ],
        "ambiguities_or_review_flags": [],
        "human_review_status": "pending_review",
        "implementation_readiness": "needs_human_review",
    }


def _sim_common_rule(
    meta: dict[str, Any], document: dict[str, Any], *, variant: str
) -> dict[str, Any]:
    if variant == "a":
        requirement = "The credit memo must state the borrower name and requested amount."
        quote = "every sample credit memo must state the requested amount and borrower name"
        section = "1. Documentation"
    else:
        requirement = (
            "The credit memo must clearly state the borrower name and the requested amount."
        )
        quote = "each credit memo must clearly state the borrower name and the requested amount"
        section = "A. Memo Contents"
    return {
        "rule_id": f"{meta['policy_id']}-rule-002",
        "rule_name": "Credit memo must identify borrower and amount",
        "rule_type": "documentation_requirement",
        "policy_source": _sim_policy_source(meta, document, section=section, page=1, quote=quote),
        "applies_to": _sim_applies_to(),
        "requirement": requirement,
        "check_objective": (
            "Check whether the credit memo states the borrower name and the requested amount."
        ),
        "credit_documentation_fields_needed": ["borrower_name", "requested_amount"],
        "condition_logic": {
            "logic_type": "all",
            "conditions": ["borrower_name is present", "requested_amount is present"],
        },
        "evidence_required": ["credit_memo"],
        "pass_condition": "The credit memo states both the borrower name and the requested amount.",
        "fail_condition": "The credit memo is missing the borrower name or the requested amount.",
        "exception_condition": "",
        "severity": "documentation_gap",
        "expected_output": {
            "pass_message": "Policy check passed.",
            "fail_message": "Required policy evidence is missing or insufficient.",
            "exception_message": "Policy check passed with documented exception.",
        },
        "test_cases": [
            {"name": "borrower and amount present", "expected": "pass"},
            {"name": "borrower or amount absent", "expected": "fail"},
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
        if operation == "verify":
            return self._verify(payload)
        if operation == "enrich":
            return self._enrich(payload)
        if operation == "group":
            return self._group(payload)
        raise ValueError(f"Unsupported LLM operation: {operation}")

    def _extract(self, payload: dict[str, Any]) -> dict[str, Any]:
        meta = payload["policy_metadata"]
        document = payload["document"]
        is_alpha = "100,000" in payload["document_text"]
        rules = []
        if is_alpha:
            rules.append(_sim_threshold_rule(meta, document))
        rules.append(_sim_common_rule(meta, document, variant="a" if is_alpha else "b"))
        return {"rules": rules, "follow_up_items": []}

    def _verify(self, payload: dict[str, Any]) -> dict[str, Any]:
        policy_kb = payload["policy_kb"]
        rules = policy_kb.get("rules", [])
        weak = [rule["rule_id"] for rule in rules if not rule["policy_source"].get("quote")]
        # Simulate one genuine completeness gap so Part 3 has something to fold in.
        missing_docs = (
            [
                {
                    "description": "Signed credit memo retention period is not captured as a rule.",
                    "suggested_rule_type": "timing_requirement",
                }
            ]
            if rules
            else []
        )
        ready = not weak and bool(rules)
        return {
            "schema_version": "1.0.0",
            "reviewed_policy_kb": payload["reviewed_policy_kb"],
            "missing_rules": [],
            "missing_thresholds": [],
            "missing_approval_requirements": [],
            "missing_documentation_requirements": missing_docs,
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
                "main_takeaways": ["Simulated completeness verification completed."],
                "potential_gaps": [item["description"] for item in missing_docs],
                "high_priority_reviewer_issues": [],
                "ready_for_consolidation": ready,
                "usable_for_credit_documentation_checks": ready,
                "recommended_next_steps": ["Resolve follow-up items before approval."],
            },
        }

    def _enrich(self, payload: dict[str, Any]) -> dict[str, Any]:
        policy_kb = payload["policy_kb"]
        verification = payload["verification"]
        rules = [dict(rule) for rule in policy_kb.get("rules", [])]
        follow_ups: list[dict[str, Any]] = list(policy_kb.get("follow_up_items", []))
        for index, gap in enumerate(verification.get("missing_documentation_requirements", []), 1):
            follow_ups.append(
                {
                    "item_id": f"fu-{index:03d}",
                    "kind": "missing_documentation_requirement",
                    "description": gap.get("description", "Unspecified documentation gap."),
                    "related_rule_id": None,
                    "status": "open",
                    "resolution": None,
                }
            )
        return {"rules": rules, "follow_up_items": follow_ups}

    def _group(self, payload: dict[str, Any]) -> dict[str, Any]:
        rules = payload["rules"]
        if len(rules) < 2:
            return {"rule_groups": []}
        members = [rule["rule_id"] for rule in rules]
        return {
            "rule_groups": [
                {
                    "theme": "Sample credit documentation requirements",
                    "relationship_type": "complements",
                    "member_rule_ids": members,
                    "rationale": (
                        "Both rules check the same sample credit memo from complementary angles "
                        "(threshold-driven evidence and baseline memo contents)."
                    ),
                    "human_review_status": "pending_review",
                }
            ]
        }


# --------------------------------------------------------------------------------------
# Azure OpenAI client
# --------------------------------------------------------------------------------------

_PROMPT_NAMES = {
    "extract": "policy_rule_extraction.md",
    "verify": "policy_completeness_review.md",
    "enrich": "policy_kb_enrichment.md",
    "group": "policy_kb_consolidation.md",
}

_GROUP_SCHEMA = {
    "title": "rule_groups",
    "type": "object",
    "additionalProperties": False,
    "required": ["rule_groups"],
    "properties": {"rule_groups": {"type": "array"}},
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
        from .proxy_utils import ensure_direct_connection

        ensure_direct_connection(self.settings.azure_openai_endpoint)
        return AzureChatOpenAI(
            azure_endpoint=self.settings.azure_openai_endpoint,
            azure_deployment=self.settings.azure_openai_deployment,
            azure_ad_token_provider=get_cognitive_services_token_provider(),
            api_version=self.settings.azure_openai_api_version,
            temperature=0,
        )

    def _context(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation == "extract":
            document = payload["document"]
            return {
                "document_metadata": {
                    **payload["policy_metadata"],
                    "document_name": document["document_name"],
                },
                "document_text": payload["document_text"],
            }
        if operation == "verify":
            return {"document_text": payload["document_text"], "policy_kb": payload["policy_kb"]}
        if operation == "enrich":
            return {
                "document_text": payload["document_text"],
                "policy_kb": payload["policy_kb"],
                "verification": payload["verification"],
            }
        if operation == "group":
            return {"rules": payload["rules"]}
        raise ValueError(f"Unsupported LLM operation: {operation}")

    def _output_schema(self, operation: str) -> dict[str, Any]:
        from .json_utils import load_json

        if operation in {"extract", "enrich"}:
            # Guide the model with the real nested rule shape (reusing the per-policy schema's
            # definitions) so it returns complete, validatable rule objects. strict=False, so the
            # minItems/minLength constraints are guidance and the normalization layer is the net.
            kb_schema = load_json(self.settings.schemas_dir / "policy_kb.schema.json")
            return {
                "title": "policy_kb_content",
                "type": "object",
                "additionalProperties": False,
                "required": ["rules", "follow_up_items"],
                "properties": {
                    "rules": {"type": "array", "items": {"$ref": "#/$defs/rule"}},
                    "follow_up_items": {"type": "array", "items": {"$ref": "#/$defs/followUpItem"}},
                },
                "$defs": kb_schema["$defs"],
            }
        if operation == "group":
            return _GROUP_SCHEMA
        if operation == "verify":
            return load_json(self.settings.schemas_dir / "policy_verification.schema.json")
        raise ValueError(f"Unsupported LLM operation: {operation}")

    def generate(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        from .prompt_utils import render_prompt

        try:
            prompt_path = self.settings.prompts_dir / _PROMPT_NAMES[operation]
        except KeyError as exc:
            raise ValueError(f"Unsupported LLM operation: {operation}") from exc
        system, user = render_prompt(
            prompt_path.read_text(encoding="utf-8"), self._context(operation, payload)
        )
        # Structured Outputs (json_schema) is preferred over the deprecated json_object mode for
        # gpt-4o; strict=False keeps full JSON-Schema constraints usable (authoritative validation
        # still runs deterministically in the services). The response-format name is derived from
        # the schema title, which must be sanitized to OpenAI's allowed character set.
        schema = self._output_schema(operation)
        schema = {**schema, "title": _safe_schema_title(schema.get("title", operation))}
        structured = self._create_llm().with_structured_output(
            schema, method="json_schema", strict=False
        )
        result = structured.invoke([("system", system), ("user", user)])
        if not isinstance(result, dict):
            raise ValueError("Azure OpenAI returned a non-object structured response")
        return result

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.settings.azure_openai_embedding_deployment:
            raise ValueError("AZURE_OPENAI_EMBEDDING_DEPLOYMENT is required for embeddings")
        from langchain_openai import AzureOpenAIEmbeddings

        from .azure_auth import get_cognitive_services_token_provider
        from .proxy_utils import ensure_direct_connection

        ensure_direct_connection(self.settings.azure_openai_endpoint)
        embeddings = AzureOpenAIEmbeddings(
            azure_endpoint=self.settings.azure_openai_endpoint,
            azure_deployment=self.settings.azure_openai_embedding_deployment,
            azure_ad_token_provider=get_cognitive_services_token_provider(),
            api_version=self.settings.azure_openai_api_version,
        )
        return embeddings.embed_documents(texts)


def create_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_mode == "simulated":
        return SimulatedLLMClient()
    if settings.llm_mode == "azure":
        return AzureOpenAILLMClient(settings)
    raise ValueError("KB_LLM_MODE must be 'simulated' or 'azure'")
