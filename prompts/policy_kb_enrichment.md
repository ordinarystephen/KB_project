---
name: Policy KB enrichment
description: Gap-fill a per-policy KB using verification findings, grounded in the source.
inputs:
  document_text:
    type: string
  policy_kb:
    type: object
  verification:
    type: object
---

system:
Improve the per-policy KB by addressing the verification findings, using ONLY the source document as
evidence. Return the full "rules" array and a "follow_up_items" array.

Rules:
- Add or correct rules ONLY when the source supports them with an exact quote and a section/page. Keep
  the same rule shape and the same policy_source discipline (policy_id + page + verbatim quote).
- Do not invent requirements or resolve genuine ambiguity. Anything you cannot support from the source
  becomes an OPEN follow_up_item describing exactly what a human must check or decide.
- Preserve existing well-supported rules; never weaken a stricter requirement.
- Keep human_review_status "pending_review" and implementation_readiness conservative.

user:
Source document (Azure DI Markdown):
{{document_text}}

Current per-policy KB:
{{policy_kb}}

Verification findings to address:
{{verification}}
