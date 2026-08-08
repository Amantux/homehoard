"""Notifier dispatch + the one SSRF guard shared with the notifiers API.

The guard lives here (not in the API blueprint) because a notifier URL must be
validated at the point of USE, not only where it's saved: a URL can arrive via
add-on options / env and bypass the API's create/update check. Both the API and
the dispatcher import `url_is_safe` so there is a single definition.
"""
import ipaddress
import socket
from urllib.parse import urlparse

# Fail-safe design: the authority of these Apprise schemes is an ID/TOKEN, not a
# network host, so their "hostname" must NOT be DNS-resolved (it isn't a host).
# EVERY OTHER scheme is treated as host-addressed and is resolved-and-checked —
# including self-hostable providers (gotify/mmost/rocket/nextcloud/ntfy/mqtt/
# matrix, the http family) and any scheme we don't recognise. An earlier
# allowlist of host-schemes was the wrong default: a host-addressed provider we
# forgot to list (e.g. gotify://internal-box/token) sailed straight through
# unresolved. A missing token scheme here only fails CLOSED (its token gets
# resolved, fails, and the notifier is refused) — never an SSRF.
_TOKEN_ONLY_SCHEMES = {
    "discord", "tgram", "telegram", "slack", "join", "pover", "pushover",
    "pbul", "pushbullet", "prowl", "gitter", "flock", "webexteams", "msteams",
    "techulus", "pushed", "spush", "twilio", "clicksend", "nexmo", "vonage",
    "sns", "mailgun", "sendgrid", "ses", "pushjet", "faast", "boxcar",
}


def _is_blocked_ip(ip) -> bool:
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def url_is_safe(url: str) -> bool:
    """Reject notifier URLs that would let the server reach internal hosts
    (SSRF: cloud metadata, RFC1918, loopback, link-local, …).

    Residuals (documented, not silently claimed solved): this validates the URL
    at save/dispatch time, but Apprise resolves + connects again at send time, so
    (a) a host that 302-redirects to an internal address and (b) DNS rebinding (a
    public A on our lookup, a private A on Apprise's) both slip past — closing
    either needs pinning the validated IP and forcing the send to it, or a
    no-redirect transport. Acceptable here: notifier URLs are operator-set on a
    trusted household add-on, not arbitrary attacker input."""
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

    if parsed.scheme.lower() in _TOKEN_ONLY_SCHEMES:
        return True  # authority is an id/token, not a network host — don't resolve
    # Everything else is host-addressed: resolve and reject any internal target.
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False  # unresolvable host → refuse (fail closed)
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
