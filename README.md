# Credit Policy Rules Knowledge Base Workbench

A portable Streamlit application that turns policy documents into a single, citable, rules-only
knowledge base for a downstream credit-document conformance checker. It runs in four parts with two
human gates, preserving per-rule provenance (policy id, section, page, and an exact quote) so the
downstream app can say *"this does not conform with XYZ policy, page 2."*

LLM output is never treated as approved policy. New rules default to `pending_review` and
`needs_human_review`. The LLM does the reasoning it is best at (gap-fill and cross-policy
relationship grouping); deterministic code owns the mechanical work (dedup, stable ids, fold
application, counts, and schema validation).

See [docs/RUNBOOK.md](docs/RUNBOOK.md) for the step-by-step human process.

## Structure

```text
app/streamlit_app.py               Streamlit UI (4 parts, 2 human gates)
app/services/                      File, document, LLM, similarity, and workflow services
data/source_documents/             Uploaded source files
data/extracted_text/               Extracted text (Azure DI Markdown for PDF/DOCX)
knowledge_base/policy_kbs/         Canonical per-policy KB (YAML, human-edited)
knowledge_base/verifications/      Per-policy completeness diagnostics (JSON)
knowledge_base/merge_candidates/   Near-duplicate fold worksheets (YAML, Gate 2)
knowledge_base/consolidated/       Final rules-only KB for downstream use (JSON)
knowledge_base/logs/               Errors and invalid model outputs
prompts/                           Version-controlled prompt templates
schemas/                           JSON Schemas for every structured output
docs/RUNBOOK.md                    Step-by-step human review process
tests/test_e2e_smoke.py            Complete offline four-part smoke test
```

All paths are resolved relative to the repository. Runtime documents and outputs stay inside the
checkout but are ignored by Git by default because workplace policy files may be sensitive. Remove
the relevant `.gitignore` entries only when your data-handling rules explicitly permit committing
those artifacts.

## Install and run

Python 3.11 or newer and `uv` are required by the project standard.

```bash
uv sync --dev
uv run streamlit run app/streamlit_app.py
```

For a pip-managed environment such as an existing Domino `.venv`:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

Azure mode is the deployed default. Simulated mode is reserved for automated offline tests and must
be explicitly enabled with `KB_LLM_MODE=simulated`.

## Offline validation

Run every functionality test and the full two-document smoke workflow with:

```bash
KB_LLM_MODE=simulated uv run pytest
```

The smoke test runs two fake policies through all four parts and both human gates: extract → verify →
enrich → approve (Gate 1), then prepare + similarity candidates → fold (Gate 2) → group → consolidate.
It asserts statuses advance, YAML round-trips, a near-duplicate is folded, the final KB carries
`rule_groups`, `provenance`, and page-bearing citations, and the exact final path and shape. It never
opens a browser or calls Azure.

Optional static checks:

```bash
uv run ruff check .
uv run ruff format --check .
```

## Output workflow

The `status:` field in each `knowledge_base/policy_kbs/<slug>.kb.yaml` is the state machine; advance
it with an app button or by editing the line. **No files are moved.** See
[docs/RUNBOOK.md](docs/RUNBOOK.md) for the exact human actions.

1. **Part 1 — Extract.** Azure DI returns structure-preserving Markdown (with page anchors); the LLM
   drafts rules into `<slug>.kb.yaml` (`status: draft`).
2. **Part 2 — Verify.** The LLM re-reads the source against the draft and writes
   `knowledge_base/verifications/<slug>.verification.json` (`status: verified`).
3. **Part 3 — Enrich.** The LLM gap-fills the draft from the source, leaving uncertainties as
   `follow_up_items` (`status: enriched`).
4. **Gate 1.** A human resolves the follow-ups and approves (`status: approved`).
5. **Part 4 — Consolidate** (approved KBs only): (a) deterministic normalize + exact-dedup + stable
   `cpr-<hash>` ids; (b) probabilistic similarity writes near-duplicate fold candidates to
   `knowledge_base/merge_candidates/<run>.candidates.yaml`; (**Gate 2**) a human sets each
   `decision:`; (c) folds are applied, the LLM groups the rules by cross-policy relationship, and the
   canonical `knowledge_base/consolidated/credit_policy_rules_kb.json` is written (prior result
   archived).

Exact duplicates merge into one content-stable rule id while retaining every `source_rule_id` and
policy reference. Conflicts are an LLM relationship judgment (`relationship_type: conflicts`), which
downgrades the affected rules to `needs_policy_owner_review`. Summary counts and provenance are
recomputed deterministically.

Invalid structured output is not coerced. It is preserved under `knowledge_base/logs/`, and the
validation error is surfaced to the UI.

The final KB contains `schema_version`, `knowledge_base_name`, `created_from_documents`, checkable
`rules[]` (each with a `policy_source` carrying `policy_id`, `section`, `page`, and an exact `quote`),
`rule_groups[]` (cross-policy relationships), `provenance` (source KB hashes and approval times), and
`processing_summary`. It excludes logs, review history, UI state, and broad policy summaries.

## Real Azure mode

No API keys are supported. Azure OpenAI and Document Intelligence both use one cached
`DefaultAzureCredential` chain, allowing Domino's configured environment, CLI, or managed identity
to authenticate.

In Domino, the credential chain automatically consumes the identity made available by the runtime,
including managed/workload identity or standard AAD environment credentials such as
`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_CLIENT_SECRET`. Do not place credentials in this
repository or Streamlit code.

Set these variables in the target environment:

```bash
export KB_LLM_MODE=azure
export AZURE_OPENAI_ENDPOINT='https://<resource>.openai.azure.com/'   # real Azure endpoint
export AZURE_OPENAI_DEPLOYMENT='gpt-4o'
export OPENAI_API_VERSION='2025-04-01-preview'
# Document Intelligence in Domino goes through the local proxy; egress to the public
# *.cognitiveservices.azure.com endpoint is typically blocked.
export AZURE_DOCINTEL_ENDPOINT='https://127.0.0.1:8443'
export DOCINTEL_API_VERSION='2024-11-30'
# Optional: enables embedding-based similarity for Part 4b. Without it, a deterministic
# token-set fallback is used, so consolidation still works.
export AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT='text-embedding-3-large'
# Optional: near-duplicate fold threshold (default 0.86).
export KB_SIMILARITY_THRESHOLD='0.86'
uv run streamlit run app/streamlit_app.py
```

**Do not set** `AZURE_OPENAI_API_KEY` (unused — AAD bearer tokens are used) or, especially,
`AZURE_OPENAI_AD_TOKEN` (a pinned token bypasses credential rotation and fails when it expires; let
`DefaultAzureCredential` supply rotating tokens). The app launches an **Azure connection status**
panel that flags missing required variables and warns if either of these is set. Endpoint/deployment
names also accept the SDK-standard aliases `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` and
`AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT`.

Implementation notes for the Azure path:

- Authentication is one cached `DefaultAzureCredential` → bearer-token provider (scope
  `https://cognitiveservices.azure.com/.default`) for both OpenAI and Document Intelligence; the SDK
  reads and refreshes the token (the app never handles a token string).
- The LLM uses Azure OpenAI **Structured Outputs** (`json_schema`), which Microsoft recommends over the
  older `json_object` JSON mode for gpt-4o; deterministic schema validation still runs in the services.
- Document Intelligence uses the `prebuilt-layout` model with `output_content_format=MARKDOWN` (so
  headings and page anchors reach the LLM), the credential object directly, and the pinned
  `DOCINTEL_API_VERSION`. SSL trust for the local proxy comes from the system CA bundle — the code
  never sets `verify=False`.
- Part 4b similarity uses Azure OpenAI embeddings when an embeddings deployment is set, otherwise a
  deterministic token-set fallback.

TXT and Markdown inputs are read directly. In the UI, enable Azure Document Intelligence for PDF or
DOCX extraction. Azure calls (LLM, embeddings, DI) are deliberately outside automated tests; complete a
separate deployment acceptance check in Domino once credentials and endpoints are available.

## Porting to Domino

Clone the GitHub repository into the Domino workspace, use Python 3.11+, install from
`pyproject.toml` with `uv sync`, configure the environment variables above, and start Streamlit from
the repository root. No user-specific paths, local secrets, database, or external vector store are
required.

This first version uses a direct, linear workflow rather than LangGraph because it has no agentic
routing or tool loop. MLflow tracing is also not initialized in offline mode; enable workplace
tracing during Domino integration when the approved tracking URI and experiment are known.
