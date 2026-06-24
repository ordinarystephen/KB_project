"""Keep a corporate HTTP(S) proxy from intercepting Azure SDK traffic.

In some Domino setups an outbound proxy (``HTTP_PROXY``/``HTTPS_PROXY``) intercepts calls to the
Azure OpenAI / Document Intelligence endpoints (including localhost gateways) and returns an HTML
block page or a 404, which then surfaces inside the Azure SDK as a ``JSONDecodeError``. Adding the
target hosts to ``NO_PROXY`` before the client is built makes the SDK connect directly.

It only ever bypasses the proxy for **loopback/private** hosts (the local DI proxy and localhost
gateways). A public endpoint such as ``*.openai.azure.com`` is left untouched, because the corporate
proxy may legitimately be the required egress path to reach it.
"""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _is_bypassable(host: str) -> bool:
    """True only for loopback/private hosts; a public host may legitimately need the proxy."""
    if host in _LOOPBACK:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # DNS hostname (e.g. *.openai.azure.com) -- leave proxy routing untouched
    return ip.is_loopback or ip.is_private


def ensure_direct_connection(*endpoints: str) -> None:
    """Add loopback and any loopback/private endpoint hosts to NO_PROXY (idempotent, additive)."""
    hosts = set(_LOOPBACK)
    for endpoint in endpoints:
        if not endpoint:
            continue
        host = urlparse(endpoint).hostname
        if host and _is_bypassable(host):
            hosts.add(host)

    existing: set[str] = set()
    for name in ("NO_PROXY", "no_proxy"):
        existing |= {item.strip() for item in os.environ.get(name, "").split(",") if item.strip()}

    value = ",".join(sorted(existing | hosts))
    os.environ["NO_PROXY"] = value
    os.environ["no_proxy"] = value
