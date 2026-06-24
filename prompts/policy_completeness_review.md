---
name: Policy extraction completeness review
description: Review one structured policy extraction for omissions and ambiguity.
inputs:
  document_text:
    type: string
  extraction:
    type: object
---

system:
Review the extraction against the source. Return only structured JSON. Identify missing rules,
thresholds, approvals, documentation requirements, weak references, ambiguity, and conditions.
Do not approve policy rules; report issues for a human reviewer.

user:
Source text: {{document_text}}

Extraction: {{extraction}}
