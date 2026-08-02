"""How-to videos: link validation, the attachment invariant, and safe serving.

Videos reuse the existing ``Attachment`` row rather than getting a table of
their own — an attachment is already "a thing hanging off an item", and a second
parallel system is how the surfaces drift apart.

Three rules live here, in one place, because every write path needs all of them:

1. A stored link is **http(s) only**. The server never fetches this URL; the
   browser renders it, so the risk is a ``javascript:`` or ``data:`` address
   becoming an ``href``. This is deliberately NOT
   ``services.ai.url_guard.llm_url_ok`` — that is an SSRF guard which
   intentionally permits loopback and private LAN so a local Ollama works, which
   is the opposite of what is wanted here.
2. An attachment is either a file or a link, and belongs to exactly one parent.
3. Only a known video type is ever served **inline**; everything else keeps
   downloading, so a user-uploaded file can never be rendered as active content.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse

# Served inline; anything else downloads. The Content-Type sent to the browser
# comes from THIS map, never from the uploaded filename — that is what stops a
# file called "clip.mp4" full of HTML from executing in the app's origin.
VIDEO_MIME_BY_EXT = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".ogv": "video/ogg",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
}

MAX_URL_LENGTH = 2048
MAX_TITLE_LENGTH = 255


class VideoError(ValueError):
    """Invalid video input. Carries a message safe to return to the caller."""


def normalize_url(raw: str) -> str:
    """Validate and normalize an external video link.

    Returns the cleaned URL, or raises :class:`VideoError` with a message that
    says what to do — the caller turns it into a 422.
    """
    value = (raw or "").strip()
    if not value:
        raise VideoError("a video link is required")
    if len(value) > MAX_URL_LENGTH:
        raise VideoError(f"that link is longer than {MAX_URL_LENGTH} characters")

    parsed = urlparse(value)
    # Scheme allowlist, not a blocklist: "javascript", "data", "vbscript",
    # "file" and anything invented later are all rejected by not being listed.
    if parsed.scheme.lower() not in ("http", "https"):
        raise VideoError("the link must start with http:// or https://")
    if not parsed.netloc:
        raise VideoError("that does not look like a web address")
    # Strip any credentials someone pasted from a private link; they would end
    # up rendered in an href and stored in the database.
    netloc = parsed.netloc.rsplit("@", 1)[-1]
    return urlunparse(parsed._replace(scheme=parsed.scheme.lower(), netloc=netloc))


def video_mime(filename: str) -> str | None:
    """The inline Content-Type for this filename, or None if it is not a video."""
    return VIDEO_MIME_BY_EXT.get(os.path.splitext(filename or "")[1].lower())


def validate(attachment) -> None:
    """The one-file-or-one-link, one-parent invariant.

    Raises :class:`VideoError`. Enforced here rather than by a database
    constraint so a bad request is a 422 with a sentence, not an
    IntegrityError surfacing as a 500.
    """
    has_url = bool((attachment.url or "").strip())
    has_doc = attachment.document_id is not None
    if has_url == has_doc:
        raise VideoError("a video must be either an uploaded file or a link, not both")

    parents = [attachment.item_id, attachment.bin_id, attachment.maintenance_entry_id]
    if sum(1 for p in parents if p) != 1:
        raise VideoError("a video must belong to exactly one item, bin or task")


def embed_url(url: str) -> str | None:
    """A same-page embed URL for the providers we allow framing, else None.

    Only YouTube and Vimeo are recognised, because those are the two hosts the
    Content-Security-Policy permits in ``frame-src``. Anything else is rendered
    as a plain link that opens in a new tab — the CSP would block its iframe
    anyway, and silently showing an empty box is worse than an honest link.
    """
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return None
    host = parsed.netloc.lower().removeprefix("www.")
    if host in ("youtube.com", "m.youtube.com"):
        # ?v=ID
        for part in parsed.query.split("&"):
            key, _, value = part.partition("=")
            if key == "v" and value:
                return f"https://www.youtube-nocookie.com/embed/{_safe_id(value)}"
        return None
    if host == "youtu.be":
        vid = parsed.path.lstrip("/")
        return f"https://www.youtube-nocookie.com/embed/{_safe_id(vid)}" if vid else None
    if host == "vimeo.com":
        vid = parsed.path.lstrip("/").split("/")[0]
        return f"https://player.vimeo.com/video/{_safe_id(vid)}" if vid.isdigit() else None
    return None


def _safe_id(value: str) -> str:
    """Keep only characters a provider id can contain.

    The result is interpolated into a URL the page will frame, so a value
    carrying ``/`` or ``?`` could otherwise point the iframe somewhere else on
    the provider's domain.
    """
    return "".join(c for c in value if c.isalnum() or c in "-_")[:64]
