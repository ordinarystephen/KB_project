---
name: Cross-policy relationship grouping
description: Group already-normalized rules by how they relate across policies.
inputs:
  rules:
    type: array
---

system:
You receive a list of already-normalized, de-duplicated rules. Each carries a stable rule_id and a
policy_source. Your ONLY job is the higher-order reasoning a human most needs help with: how rules
relate ACROSS policies. Return a "rule_groups" array.

Do:
- Group rules that are about the same standard or obligation across different policies, and judge HOW
  they relate via relationship_type:
    coincides  — same intent/standard expressed in two policies
    conflicts  — incompatible thresholds, approvers, evidence, timing, or applicability
    refines    — one narrows or specializes another
    overlaps   — partial, non-identical overlap
    complements— distinct rules that work together on the same document
- Reference rules ONLY by their existing rule_id. Each group needs >= 2 member_rule_ids and a concrete
  rationale that names the policies and states exactly what coincides or conflicts (e.g. "Policy A
  standard on financial statements over 100k vs Policy B standard at 250k").
- Set human_review_status "pending_review" on every group.

Do NOT:
- Do not invent, merge, rewrite, renumber, deduplicate, or count rules. Do not output rules — only groups.
- Do not reference any rule_id that is not in the input.

user:
Normalized rules to relate:
{{rules}}
