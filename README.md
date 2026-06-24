# Credit Policy Rules Knowledge Base Workbench

A portable Streamlit application that turns policy documents into structured, human-reviewable
credit-documentation rules. It saves per-policy extracts and completeness reviews, then consolidates
selected extracts into a minimal rules-only knowledge base.

LLM output is never treated as approved policy. New rules default to `pending_review` and
`needs_human_review`.

## Structure

```text
app/streamlit_app.py              Streamlit UI
app/services/                     Tested file, document, LLM, and workflow services
data/source_documents/            Uploaded source files
data/extracted_text/              Extracted plain text
knowledge_base/policy_extracts/   Per-policy rule JSON
knowledge_base/reviews/           Completeness-review JSON
knowledge_base/consolidated/      Final rules-only KB
knowledge_base/logs/              Errors and invalid model outputs
prompts/                          Version-controlled prompt templates
schemas/                          JSON Schemas for every structured output
tests/fixtures/                   Fake policies and expected-output fixtures
tests/test_e2e_smoke.py           Complete offline file-workflow smoke test
```

All paths are resolved relative to the repository. Runtime documents and outputs stay inside the
checkout but are ignored by Git by default because workplace policy files may be sensitive. Remove
the relevant `.gitignore` entries only when your data-handling rules explicitly permit committing
those artifacts.

## Install and run

Python 3.11 or newer and `uv` are required by the project standard.

```bash
uv sync --dev
KB_LLM_MODE=simulated uv run streamlit run app/streamlit_app.py
```

For a pip-managed environment such as an existing Domino `.venv`:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
KB_LLM_MODE=simulated streamlit run app/streamlit_app.py
```

Simulated mode is the default. It uses deterministic fake outputs and needs no credentials, network,
Azure service, or real policy document.

## Offline validation

Run every functionality test and the full two-document smoke workflow with:

```bash
KB_LLM_MODE=simulated uv run pytest
```

The smoke test saves two fake uploads, extracts text, creates and validates two rule extracts, creates
and validates two reviews, consolidates the extracts, and validates the exact final path and shape.
It never opens a browser or calls Azure.

Optional static checks:

```bash
uv run ruff check .
uv run ruff format --check .
```

## Output workflow

1. Uploads are versioned rather than silently overwritten and saved in `data/source_documents/`.
2. Text is saved in `data/extracted_text/`; PDF and DOCX can use Azure Document Intelligence.
3. Each validated extraction is saved as `knowledge_base/policy_extracts/{slug}.rules.json`.
4. Each validated review is saved as `knowledge_base/reviews/{slug}.review.json`.
5. Consolidation archives a prior result and writes the canonical file:
   `knowledge_base/consolidated/credit_policy_rules_kb.json`.

During consolidation, exact duplicates receive one content-stable rule ID while retaining every
source rule ID and structured policy reference. Similar rules remain separate with overlap flags.
Possible conflicts remain unresolved, are flagged on each affected rule, and are downgraded to
`needs_policy_owner_review`. Summary counts are recalculated after these safeguards run.

Invalid structured output is not coerced. It is preserved under `knowledge_base/logs/`, and the
validation error is surfaced to the UI.

The final KB contains only `schema_version`, `knowledge_base_name`, `created_from_documents`,
checkable `rules[]`, and `processing_summary`. It excludes logs, review history, UI state, broad
policy summaries, and non-checkable definition/retrieval content.

## Real Azure mode

No API keys are supported. Azure OpenAI and Document Intelligence both use one cached
`DefaultAzureCredential` chain, allowing Domino's configured environment, CLI, or managed identity
to authenticate.

Set these variables in the target environment:

```bash
export KB_LLM_MODE=azure
export AZURE_OPENAI_ENDPOINT='https://<resource>.openai.azure.com/'
export AZURE_OPENAI_DEPLOYMENT='gpt-4o'
export OPENAI_API_VERSION='2025-04-01-preview'
export AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT='https://<resource>.cognitiveservices.azure.com/'
uv run streamlit run app/streamlit_app.py
```

TXT and Markdown inputs are read directly. In the UI, enable Azure Document Intelligence for PDF or
DOCX extraction. Azure calls are deliberately outside automated tests; complete a separate
deployment acceptance check in Domino once credentials and endpoints are available.

## Porting to Domino

Clone the GitHub repository into the Domino workspace, use Python 3.11+, install from
`pyproject.toml` with `uv sync`, configure the environment variables above, and start Streamlit from
the repository root. No user-specific paths, local secrets, database, or external vector store are
required.

This first version uses a direct, linear workflow rather than LangGraph because it has no agentic
routing or tool loop. MLflow tracing is also not initialized in offline mode; enable workplace
tracing during Domino integration when the approved tracking URI and experiment are known.
