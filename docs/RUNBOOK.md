# Human Review Runbook

This workbench turns policy documents into a single, citable, downstream-ready knowledge base in
four parts with two human gates. **You never move files.** Each per-policy KB carries a `status:`
field in its YAML — that field is the state machine. You advance it with an app button or by editing
the `status:` line yourself.

## The four parts

| Part | What it does | Artifact |
|---|---|---|
| 1. Extract | Azure DI (Markdown + page anchors) → LLM draft rules | `knowledge_base/policy_kbs/<slug>.kb.yaml` (`status: draft`) |
| 2. Verify | LLM re-reads the source vs. the draft, lists gaps | `knowledge_base/verifications/<slug>.verification.json` |
| 3. Enrich | LLM gap-fills the draft; leaves uncertainties as `follow_up_items` | same `*.kb.yaml` (`status: enriched`) |
| 4. Consolidate | dedup + similarity + your folds + LLM grouping → one KB | `knowledge_base/consolidated/credit_policy_rules_kb.json` |

## Gate 1 — per-policy lifecycle

Work one policy KB at a time in **Part C** of the app. The app shows the next action for the current
`status:`.

| `status:` | Look at | What you do | Becomes |
|---|---|---|---|
| `draft` | the draft rules | click **Verify (Part 2)** | `verified` |
| `verified` | `verifications/<slug>.verification.json` | read it, click **Enrich (Part 3)** | `enriched` |
| `enriched` | `follow_up_items[]` in the KB | resolve/edit them in the YAML, click **Approve** | `approved` |
| `approved` | — | nothing; it is eligible for Part 4 | — |

**Resolving a follow-up item** (status `enriched`): open `policy_kbs/<slug>.kb.yaml`, and for each entry
in `follow_up_items` either fix the relevant rule or write a `resolution:` and set `status: resolved`.
Then Approve. Approval is not blocked by open items — it is your judgment — but the app warns you.

## Gate 2 — fold near-duplicates, then consolidate

Run **Part D** of the app on two or more **approved** KBs.

1. Click **4a/4b — Find merge candidates**. This writes
   `knowledge_base/merge_candidates/<run>.candidates.yaml`. Exact duplicates are already merged
   automatically; this file lists rules that are only *similar* (slight wording differences) and may be
   worth folding together.
2. **Edit the worksheet.** Each candidate looks like:
   ```yaml
   - candidate_id: cand-01
     similarity: 0.93
     decision: keep_separate     # change to: fold
     fold_into: null             # when folding, set to one member rule_id below
     members:
       - rule_id: cpr-782af44e1ab6
         rule_name: Credit memo must identify borrower and amount
         policy_id: policy-a
       - rule_id: cpr-f3f9a1450147
         rule_name: Credit memo must identify borrower and amount
         policy_id: policy-b
   ```
   To fold: set `decision: fold` and `fold_into:` to the `rule_id` of the member you want to keep. The
   other members are merged into it (their source ids, citations, and applicability are preserved). To
   keep them separate, leave `decision: keep_separate`. The worksheet snapshots the rules as they were
   when you clicked **Find merge candidates**, so to change a rule's wording either edit its
   `policy_kbs/<slug>.kb.yaml` *before* finding candidates (or re-run **Find merge candidates** after
   editing to refresh the snapshot), or refine the surviving rule in the final KB after consolidation.
3. Click **4c — Apply folds & consolidate**. Your fold decisions are applied deterministically, the LLM
   groups the remaining rules by cross-policy relationship (coincides / conflicts / refines / overlaps /
   complements), and the final KB is written (the previous one is archived).

## What the downstream app gets

`credit_policy_rules_kb.json` contains `rules[]` (each with a `policy_source` carrying `policy_id`,
`section`, `page`, and an exact `quote`), `rule_groups[]` (the cross-policy relationships), and
`provenance` (which approved KBs, their content hashes, and approval times produced this KB). That is
what lets the downstream checker say *"this does not conform with XYZ policy, page 2."*
