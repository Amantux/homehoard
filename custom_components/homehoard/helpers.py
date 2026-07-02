from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def build_base_url(host: str, port: int) -> str:
    """Normalize a user/discovery-supplied host + port into a base URL."""
    host = (host or "").strip()
    if not host:
        host = "http://127.0.0.1"
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    parsed = urlparse(host)
    netloc = parsed.netloc
    if ":" not in netloc:
        netloc = f"{netloc}:{port}"
    parsed = parsed._replace(netloc=netloc, path="")
    return urlunparse(parsed).rstrip("/")


def build_url(host: str, port: int, path: str) -> str:
    return build_base_url(host, port) + path
