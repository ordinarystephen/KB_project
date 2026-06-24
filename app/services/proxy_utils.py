"""Keep a corporate HTTP(S) proxy from intercepting Azure SDK traffic.

In some Domino setups an outbound proxy (``HTTP_PROXY``/``HTTPS_PROXY``) intercepts calls to the
Azure OpenAI / Document Intelligence endpoints (including localhost gateways) and returns an HTML
block page or a 404, which then surfaces inside the Azure SDK as a ``JSONDecodeError``. Adding the
target hosts to ``NO_PROXY`` before the client is built makes the SDK connect directly.

This only ever *relaxes* proxying for specific hosts (loopback is always safe); it never forces a
proxy on. If your network genuinely requires the proxy to reach a public ``*.azure.com`` endpoint,
that host should not be passed here.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def ensure_direct_connection(*endpoints: str) -> None:
    """Add loopback and the given endpoint hosts to NO_PROXY (idempotent, additive)."""
    hosts = set(_LOOPBACK)
    for endpoint in endpoints:
        if not endpoint:
            continue
        host = urlparse(endpoint).hostname
        if host:
            hosts.add(host)

    existing: set[str] = set()
    for name in ("NO_PROXY", "no_proxy"):
        existing |= {item.strip() for item in os.environ.get(name, "").split(",") if item.strip()}

    value = ",".join(sorted(existing | hosts))
    os.environ["NO_PROXY"] = value
    os.environ["no_proxy"] = value
