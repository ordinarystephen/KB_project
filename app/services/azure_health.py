"""Azure configuration readiness — the Streamlit analog of a /health endpoint + preflight.

Turns a 3-layers-deep auth failure into a launch-time message: which required variables are missing,
whether Document Intelligence is pointed at the local Domino proxy, and a loud warning if a pinned
``AZURE_OPENAI_AD_TOKEN`` is present (it bypasses credential rotation and fails once it expires).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from .config import Settings

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_local(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


def azure_status(settings: Settings) -> dict:
    """Report Azure config readiness without contacting Azure (safe to call at launch)."""
    required = {
        "AZURE_OPENAI_ENDPOINT": settings.azure_openai_endpoint,
        "AZURE_OPENAI_DEPLOYMENT": settings.azure_openai_deployment,
        "OPENAI_API_VERSION": settings.azure_openai_api_version,
    }
    warnings: list[str] = []
    if os.getenv("AZURE_OPENAI_AD_TOKEN"):
        warnings.append(
            "AZURE_OPENAI_AD_TOKEN is set: a pinned token bypasses credential rotation and will "
            "fail when it expires. Unset it and let DefaultAzureCredential supply rotating tokens."
        )
    if os.getenv("AZURE_OPENAI_API_KEY"):
        warnings.append(
            "AZURE_OPENAI_API_KEY is set but unused (this app uses AAD bearer tokens). "
            "Unset it to avoid confusion."
        )

    di_endpoint = settings.document_intelligence_endpoint
    return {
        "mode": settings.llm_mode,
        "credential_chain": "DefaultAzureCredential",
        "token_scope": "https://cognitiveservices.azure.com/.default",
        "azure_openai_endpoint": settings.azure_openai_endpoint or "(unset)",
        "embedding_deployment": settings.azure_openai_embedding_deployment
        or "(unset — similarity falls back to deterministic)",
        "document_intelligence_endpoint": di_endpoint or "(unset)",
        "document_intelligence_api_version": settings.document_intelligence_api_version,
        "document_intelligence_via_local_proxy": bool(di_endpoint) and _is_local(di_endpoint),
        "missing_required": [name for name, value in required.items() if not value],
        "warnings": warnings,
    }
