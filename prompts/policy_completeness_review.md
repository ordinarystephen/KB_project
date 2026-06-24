---
name: Policy KB completeness verification
description: Verify one per-policy KB against its source for omissions and ambiguity.
inputs:
  document_text:
    type: string
  policy_kb:
    type: object
---

system:
Verify the per-policy KB against the source document. Return only the structured verification fields.
Identify: missing rules, thresholds, approval requirements, and documentation requirements; weak or
unverifiable source references; ambiguous rules; rules that should be split; non-checkable rules; and
rules missing conditions or fields. Do NOT approve rules — report issues for a human reviewer. Set
ready_for_consolidation and usable_for_credit_documentation_checks honestly based on what you find.

user:
Source document (Azure DI Markdown):
{{document_text}}

Per-policy KB under review:
{{policy_kb}}
