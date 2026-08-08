"""Notifier dispatch + the one SSRF guard shared with the notifiers API.

The guard lives here (not in the API blueprint) because a notifier URL must be
validated at the point of USE, not only where it's saved: a URL can arrive via
add-on options / env and bypass the API's create/update check. Both the API and
the dispatcher import `url_is_safe` so there is a single definition.
"""
import ipaddress
import socket
from urllib.parse import urlparse

# Schemes that speak to an arbitrary, user-chosen network host (SSRF-relevant):
# the generic HTTP family plus self-hostable providers (ntfy/mqtt/matrix). For
# these we resolve the host and reject internal targets. Fixed-endpoint provider
# schemes (discord://, tgram://, slack://, …) whose "host" is really an ID/token
# are left alone — but a literal internal IP is blocked for ANY scheme.
_HOST_SCHEMES = {
    "http", "https", "json", "jsons", "xml", "xmls", "form", "forms",
    "ntfy", "ntfys", "mqtt", "mqtts", "matrix", "matrixs",
}


def _is_blocked_ip(ip) -> bool:
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def url_is_safe(url: str) -> bool:
    """Reject notifier URLs that would let the server reach internal hosts
    (SSRF: cloud metadata, RFC1918, loopback, link-local, …)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if not parsed.scheme:
        return False
    host = parsed.hostname

    # A literal internal IP is never allowed, whatever the scheme.
    if host:
        try:
            return not _is_blocked_ip(ipaddress.ip_address(host))
        except ValueError:
            pass  # not an IP literal — fall through to hostname handling

    if parsed.scheme.lower() not in _HOST_SCHEMES:
        return True  # provider scheme with a non-host id/token — leave alone
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False  # unresolvable http-family host → refuse
    return all(not _is_blocked_ip(ipaddress.ip_address(i[4][0])) for i in infos)


def _apprise_send(url: str, title: str, body: str) -> bool:
    """Default sender: deliver one notification via Apprise. Returns False (never
    raises) when Apprise isn't installed or the send fails, so a dead notifier
    can't break the dispatch of the others."""
    try:
        import apprise
    except ImportError:
        return False
    try:
        ap = apprise.Apprise()
        return bool(ap.add(url) and ap.notify(body=body, title=title))
    except Exception:
        return False


def send_to_notifiers(notifiers, *, title, body, sender=None):
    """Send `title`/`body` to each active notifier, re-validating every URL at
    the point of use (config can bypass the API's save-time check). One dead or
    blocked notifier is recorded and skipped, never fatal to the rest.

    `sender(url, title, body) -> bool` is injectable so the loop is testable
    without Apprise or a live network."""
    send = sender or _apprise_send
    results = []
    for n in notifiers:
        url = getattr(n, "url", "") or ""
        if not url_is_safe(url):
            results.append({"id": getattr(n, "id", None), "ok": False,
                            "error": "blocked"})
            continue
        ok = bool(send(url, title, body))
        results.append({"id": getattr(n, "id", None), "ok": ok,
                        "error": None if ok else "send failed"})
    return results
