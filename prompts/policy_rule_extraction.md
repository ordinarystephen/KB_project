---
name: Credit policy rule extraction
description: Extract checkable credit-documentation rules from one policy.
inputs:
  document_text:
    type: string
  document_metadata:
    type: object
---

system:
You extract policy rules for human review. Return only JSON matching the supplied schema. Never
invent policy meaning or source quotations. Every rule defaults to pending_review and
needs_human_review. Focus on rules that can be checked against credit documentation.

user:
Document metadata: {{document_metadata}}

Document text:
{{document_text}}
