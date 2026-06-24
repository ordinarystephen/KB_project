# Credit Policy KB Pipeline Redesign — Design

- **Date:** 2026-06-24
- **Status:** Approved (verbal), implementation in progress
- **Topic:** Make the knowledge base optimal for downstream use (credit-document conformance checking with policy + page citation)

## Goal

The KB feeds a separate downstream AI application that checks credit documents and must be able to say
*"this does not conform with XYZ policy, page 2."* That requires: (a) reliable per-rule provenance
(policy id/name + section + page + quote), (b) cross-policy relationships the downstream app can reason
over, and (c) a human-reviewable authoring format.

## Pipeline (4 parts, 2 human gates)

```
Part 1 EXTRACT     source doc → Azure DI (markdown+pages) → LLM extract
                   → policy_kbs/<slug>.kb.yaml (status: draft)

Part 2 VERIFY      LLM re-reads source vs draft → verifications/<slug>.verification.json
                   → KB status: verified

Part 3 ENRICH      LLM gap-fills draft using verification findings (adds/corrects rules it can
                   support from source; leaves uncertain items as follow_up_items)
                   → KB status: enriched

   👤 GATE 1        human resolves follow_up_items in the YAML, then Approve → status: approved

Part 4 CONSOLIDATE (operates on all approved KBs)
   4a  deterministic: normalize + exact-dedup + assign stable cpr-<hash> ids
   4b  probabilistic: similarity scoring → merge_candidates/<run>.candidates.yaml
   👤 GATE 2        human sets decision: keep_separate | fold_into:<id> per candidate
   4c  apply folds → LLM relationship grouping over stable ids → finalize (counts, provenance)
                   → consolidated/credit_policy_rules_kb.json
```

**Division of labour:** the LLM does the thinking it is uniquely good at (gap-fill reasoning in Part 3;
cross-policy *coincidence / conflict / grouping by relevance* in 4c). Deterministic code owns the
mechanical work (exact dedup, stable ids, counts, schema validation, applying human fold decisions).
The LLM never renumbers ids or counts; code never judges semantic similarity. This removes the
double-work in the current consolidation.

## Artifacts & directory layout

```
knowledge_base/
  policy_kbs/<slug>.kb.yaml              canonical per-policy KB (YAML, human-edited); status in front-matter
  verifications/<slug>.verification.json Part 2 completeness diagnostic (feeds Part 3)
  merge_candidates/<run>.candidates.yaml Part 4b near-duplicate fold candidates (Gate 2)
  consolidated/credit_policy_rules_kb.json final downstream KB (JSON)
  logs/                                  invalid-output quarantine (unchanged)
data/
  source_documents/, extracted_text/     unchanged
  document_manifest.json                 unchanged
```

One canonical YAML per policy. `status: draft → verified → enriched → approved` is the state machine;
the human advances it via app button or by editing the `status:` line. **No file moving.**

## Schemas (collapse today's 3 → cleaner 3)

1. **`policy_kb.schema.json`** (NEW; replaces `extracted_policy_rules.schema.json`) — per-policy artifact
   across its whole life. Top level: `schema_version`, `policy` (id, name, version, document_name,
   content_hash, source_file_path, extracted_text_path), `status`, `rules[]` (in the final rule shape
   so Part 4 is a *merge* not a remap), `follow_up_items[]`, `provenance` (model, prompt_version,
   generated_at, stage_history).
2. **`policy_verification.schema.json`** (rename of `policy_review.schema.json`) — Part 2 findings.
3. **`credit_policy_rules_kb.schema.json`** (MODIFY) — adds `rule_groups[]` and `provenance`; strengthens
   `policy_source` with required `policy_id` and page.

### Rule shape (shared by per-policy KB and final KB)

`rule_id`, `source_rule_ids[]`, `rule_name`, `rule_type`, `policy_source`, `applies_to`, `requirement`,
`check_objective`, `credit_documentation_fields_needed[]`, `condition_logic`, `evidence_required[]`,
`pass_condition`, `fail_condition`, `exception_condition`, `severity`, `expected_output`, `test_cases[]`,
`ambiguities_or_review_flags[]`, `human_review_status`, `implementation_readiness`. Final-KB rules also
carry `group_ids[]` (back-references into `rule_groups`).

### Citation contract — `policy_source`

`policy_id` (NEW, stable) · `policy_name` · `policy_version` · `document_name` · `section` · `page`
(reliably populated via DI markdown page anchors) · `quote` · `additional_sources[]`.
`policy_id` + `page` + `quote` is exactly what the downstream checker cites.

### Final-KB additions

```yaml
rule_groups:
  - group_id: grp-<hash>
    theme: "Financial-statement documentation thresholds"
    relationship_type: coincides | conflicts | refines | overlaps | complements
    member_rule_ids: [cpr-…, cpr-…]
    rationale: "<LLM explanation>"
    human_review_status: pending_review
provenance:
    generated_at, model_deployment, prompt_versions,
    source_policy_kbs: [{policy_id, file, content_hash, approved_at}]
```

## Similarity backend (Part 4b) — swappable

- **azure mode:** Azure OpenAI embeddings + cosine similarity; pairs above a threshold (default 0.86)
  become candidates.
- **simulated / fallback mode:** deterministic token-set ratio (no Azure, keeps the e2e test offline,
  and is the documented fallback when no embeddings deployment exists).

Interface: `similarity_backend(rules) -> list[candidate_cluster]`. Selected by `KB_LLM_MODE` /
embeddings-deployment presence.

## Human workflow & runbook

`docs/RUNBOOK.md` documents the state table below; the app shows the matching "what you do" line as a
context hint per item (same source of truth).

| `status:` | Look at | Do | Result |
|---|---|---|---|
| `draft` | the KB rules | click **Verify** | `verified` |
| `verified` | `verifications/<slug>.verification.json` | read, click **Enrich** | `enriched` |
| `enriched` | KB `follow_up_items[]` | resolve/edit, click **Approve** | `approved` |
| `approved` | — | eligible for Part 4 | — |

Part 4: **Find merge candidates** → edit `decision:` in the candidates file → **Consolidate**.
Only manual edits: resolving `follow_up_items` before approval, and setting `decision:` on candidates.

## File-by-file code changes

**New**
- `schemas/policy_kb.schema.json`
- `app/services/yaml_utils.py` — YAML load/dump + `yaml_to_validated_dict` boundary (validates loaded
  dict against existing JSON Schemas).
- `app/services/prompt_utils.py` — parse Prompty front-matter, split `system:`/`user:`, substitute `{{…}}`.
- `app/services/enrichment_service.py` — Part 3.
- `app/services/similarity_service.py` — Part 4b candidate generation + swappable backend.
- `app/services/status.py` — per-policy status state machine + next-action hints (shared by app + runbook).
- `docs/RUNBOOK.md`

**Modified**
- `app/services/document_loader.py` — DI `output_content_format=MARKDOWN`, page anchors carried into text.
- `app/services/llm_client.py` — render prompts via `prompt_utils`; structured outputs
  (`with_structured_output`, json_schema); ops `extract|verify|enrich|group_relationships` (+ embeddings
  provider); `SimulatedLLMClient` stand-ins incl. deterministic embeddings/similarity.
- `app/services/extraction_service.py` — Part 1 → draft `*.kb.yaml`.
- `app/services/review_service.py` → `verification_service.py` — Part 2 → JSON diagnostic.
- `app/services/consolidation_service.py` — Part 4 orchestration (4a/4b/4c), provenance, gate enforcement.
- `app/services/consolidation_rules.py` — keep deterministic normalize/dedup/ids/counts; add apply-folds
  and attach-rule_groups; drop instructions duplicated by the LLM.
- `app/services/config.py` — new dirs (policy_kbs, verifications, merge_candidates), prompt-version capture.
- `app/streamlit_app.py` — 4 explicit parts + 2 gates + status hints + YAML browse/edit.
- `schemas/credit_policy_rules_kb.schema.json` — rule_groups, provenance, policy_id, page.
- `prompts/*` — rewrite extraction/verification + new enrichment + grouping; explicit page-citation and
  reasoning instructions.

**Removed/retired**
- `schemas/extracted_policy_rules.schema.json` (folded into `policy_kb.schema.json`).
- `schemas/policy_review.schema.json` (renamed).

## Testing strategy

- **e2e smoke (simulated, offline):** two fake policies through all 4 parts + both gates; assert YAML
  round-trips, statuses advance, merge candidates produced, fold decision applied, final KB has
  `rule_groups` + `provenance` + page-bearing `policy_source`, and the exact final path/shape.
- **unit:** yaml round-trip + validation; prompt rendering substitution; exact-dedup + stable id;
  similarity candidate generation (deterministic backend); apply-folds; provenance assembly; status
  state machine transitions.
- Azure-only paths (real DI markdown, real embeddings, structured-output invoke) remain outside automated
  tests by project convention; covered by a separate Domino deployment check.

## Dependencies

- Add `pyyaml>=6.0` to `pyproject.toml` + `requirements.txt`.
- Azure embeddings reuse `langchain-openai` (already present) + the existing AAD token provider; requires
  an embeddings deployment env var (`AZURE_OPENAI_EMBEDDING_DEPLOYMENT`) only in azure mode.

## Non-goals / deferred

- MLflow tracing (still deferred to Domino integration, per current README).
- Structured `condition_logic` operands and a controlled `applies_to` vocabulary — valuable later, but
  out of scope for this pass (rules remain LLM-checkable natural language + fields).
