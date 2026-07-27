"""SSRF guard for a user-supplied LLM base URL.

Ported from the companion Edibl app. The provider base URL / Ollama host is
operator-configurable, so a malicious value could point HomeHoard's server at an
internal service. Block link-local (notably the cloud metadata endpoint
169.254.169.254 / fe80::) while still allowing loopback and private LAN, where a
self-hosted Ollama / SLM server legitimately runs.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def llm_url_ok(url: str) -> tuple[bool, str | None]:
    """Return (ok, error). Blank URL → ok (falls back to the configured default).

    This checks the resolved address now; it is not hardened against DNS-rebinding,
    an acceptable residual for a semi-trusted instance admin configuring their own
    endpoint.
    """
    if not url:
        return True, None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, "base URL must be http or https"
    host = parsed.hostname
    if not host:
        return False, "base URL has no host"
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        # Unresolvable / malformed host: let the real request fail rather than 500.
        return True, None
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        # An IPv4-mapped IPv6 address (::ffff:169.254.169.254) connects to the real
        # IPv4 on a dual-stack host, so test the mapped v4, not the v6 wrapper.
        if addr.version == 6 and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        if addr.is_link_local:
            return False, "base URL host is not allowed"
    return True, None
