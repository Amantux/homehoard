"""How-to videos on items and maintenance tasks: links, uploads, boundaries."""
import io

import pytest

from app.services.videos import VideoError, embed_url, normalize_url, video_mime


def _item(auth_client, name="Drill"):
    return auth_client.post("/api/v1/items", json={"name": name}).get_json()["id"]


def _task(auth_client, item_id, name="Change the filter"):
    return auth_client.post(f"/api/v1/items/{item_id}/maintenance",
                            json={"name": name}).get_json()["id"]


def _mp4(name="clip.mp4"):
    # A real player is not involved; the server decides by extension, on purpose.
    return {"file": (io.BytesIO(b"\x00\x00\x00\x20ftypisom fake"), name)}


# --- link validation -------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "vbscript:msgbox",
    "notaurl",
    "",
    # These carry a netloc, so the "does it look like a web address" check
    # passes them and ONLY the scheme allowlist rejects them. Without one of
    # these the parametrize was vacuous: deleting the scheme check left every
    # other case still failing on the empty netloc.
    "javascript://example.com/%0aalert(1)",
    "data://example.com/x",
    "jAvAsCrIpT://example.com/%0aalert(1)",
])
def test_a_non_http_link_is_refused(auth_client, bad):
    """These end up in an href. A scheme allowlist, not a blocklist, so a
    scheme nobody has thought of yet is refused by not being listed."""
    rid = _item(auth_client)

    r = auth_client.post(f"/api/v1/items/{rid}/videos", json={"url": bad})

    assert r.status_code == 422


def test_credentials_are_stripped_from_a_pasted_link():
    assert normalize_url("https://user:pw@youtu.be/abc") == "https://youtu.be/abc"


def test_a_link_is_stored_and_returned(auth_client):
    rid = _item(auth_client)

    r = auth_client.post(f"/api/v1/items/{rid}/videos",
                    json={"url": "https://youtu.be/dQw4w9WgXcQ", "title": "Technique"})

    assert r.status_code == 201
    body = r.get_json()
    assert body["title"] == "Technique"
    assert body["url"] == "https://youtu.be/dQw4w9WgXcQ"
    assert body["streamUrl"] is None      # a link has nothing to stream


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=abc123", "https://www.youtube-nocookie.com/embed/abc123"),
    ("https://youtu.be/abc123", "https://www.youtube-nocookie.com/embed/abc123"),
    ("https://vimeo.com/123456789", "https://player.vimeo.com/video/123456789"),
])
def test_known_providers_get_an_embed_url(url, expected):
    assert embed_url(url) == expected


def test_an_unknown_host_is_not_embeddable():
    """The server decides what may be framed; the UI never builds an embed URL
    from a raw address."""
    assert embed_url("https://example.com/clip.mp4") is None


@pytest.mark.parametrize("hostile", [
    "https://youtu.be/abc/../../evil?x=1",
    "https://youtu.be/abc?a=b",
    "https://www.youtube.com/watch?v=abc/../evil",
])
def test_a_provider_id_cannot_redirect_the_iframe(hostile):
    """An id carrying / or ? would point the frame somewhere else on the
    provider's domain. Asserts the PROPERTY — the id contains nothing that can
    change the target — rather than a hand-computed expected string."""
    out = embed_url(hostile)

    if out is None:
        return
    prefix = "https://www.youtube-nocookie.com/embed/"
    assert out.startswith(prefix)
    video_id = out[len(prefix):]
    assert all(c.isalnum() or c in "-_" for c in video_id)


# --- uploads ---------------------------------------------------------------

def test_an_upload_is_stored_and_streamable(auth_client):
    rid = _item(auth_client)

    created = auth_client.post(f"/api/v1/items/{rid}/videos", data=_mp4(),
                          content_type="multipart/form-data").get_json()

    assert created["streamUrl"] is not None
    assert created["url"] is None
    played = auth_client.get(created["streamUrl"].replace("/api/v1", "/api/v1"))
    assert played.status_code == 200
    assert played.headers["Content-Type"].startswith("video/mp4")


def test_a_non_video_upload_is_refused(auth_client):
    """Nothing stops a user uploading anything; the point is that the server
    never agrees to serve it back inline."""
    rid = _item(auth_client)

    r = auth_client.post(f"/api/v1/items/{rid}/videos",
                    data={"file": (io.BytesIO(b"<html>hi"), "payload.html")},
                    content_type="multipart/form-data")

    assert r.status_code == 422


def test_the_served_content_type_comes_from_the_allowlist_not_the_filename(auth_client):
    """A file called clip.mp4 full of HTML must still be served as video/mp4,
    so it cannot execute in the app's origin."""
    rid = _item(auth_client)
    created = auth_client.post(f"/api/v1/items/{rid}/videos",
                          data={"file": (io.BytesIO(b"<html><script>x</script>"), "clip.mp4")},
                          content_type="multipart/form-data").get_json()

    played = auth_client.get(created["streamUrl"])

    assert played.headers["Content-Type"].startswith("video/mp4")


def test_a_range_request_is_answered_so_the_player_can_seek(auth_client):
    rid = _item(auth_client)
    created = auth_client.post(f"/api/v1/items/{rid}/videos", data=_mp4(),
                          content_type="multipart/form-data").get_json()

    r = auth_client.get(created["streamUrl"], headers={"Range": "bytes=0-3"})

    assert r.status_code == 206
    assert r.headers["Content-Range"].startswith("bytes 0-3/")


@pytest.mark.parametrize("name", ["a.mp4", "a.WEBM", "a.mov"])
def test_known_video_extensions_are_playable(name):
    assert video_mime(name)


def test_an_unknown_extension_is_not_playable():
    assert video_mime("a.html") is None


# --- the invariant ---------------------------------------------------------

def test_a_video_cannot_be_both_a_file_and_a_link():
    from app.models import Attachment
    from app.services import videos

    with pytest.raises(VideoError):
        videos.validate(Attachment(item_id="i", url="https://x/y", document_id="d"))


def test_a_video_must_be_one_or_the_other():
    from app.models import Attachment
    from app.services import videos

    with pytest.raises(VideoError):
        videos.validate(Attachment(item_id="i"))


def test_a_video_must_have_exactly_one_parent():
    """item / bin / maintenance entry — never two, never none."""
    from app.models import Attachment
    from app.services import videos

    with pytest.raises(VideoError):
        videos.validate(Attachment(url="https://x/y"))
    with pytest.raises(VideoError):
        videos.validate(Attachment(item_id="i", maintenance_entry_id="m",
                                   url="https://x/y"))


# --- listing, deleting, tenancy -------------------------------------------

def _videos_of(auth_client, item_id):
    """Videos ride along in the item payload's attachments, like every other
    attachment — there is no separate listing endpoint to keep in sync."""
    item = auth_client.get(f"/api/v1/items/{item_id}").get_json()
    return [a for a in item["attachments"] if a["type"] == "video"]


def test_a_video_appears_on_its_item(auth_client):
    rid = _item(auth_client)

    auth_client.post(f"/api/v1/items/{rid}/videos",
                     json={"url": "https://youtu.be/abc123", "title": "How it works"})

    got = _videos_of(auth_client, rid)
    assert [v["title"] for v in got] == ["How it works"]


def test_a_video_on_a_task_appears_on_that_task_only(auth_client):
    """The whole point of the per-task placement: the right clip is present
    when a job comes due, not every clip for the appliance."""
    rid = _item(auth_client)
    task_a = _task(auth_client, rid, "Change the filter")
    task_b = _task(auth_client, rid, "Sharpen the blade")

    auth_client.post(f"/api/v1/items/{rid}/maintenance/{task_a}/videos",
                     json={"url": "https://youtu.be/filter", "title": "Filter"})

    entries = auth_client.get(f"/api/v1/items/{rid}/maintenance").get_json()["entries"]
    by_id = {e["id"]: e for e in entries}
    assert [v["title"] for v in by_id[task_a]["videos"]] == ["Filter"]
    assert by_id[task_b]["videos"] == []
    # ...and a task video is not also an item attachment
    assert _videos_of(auth_client, rid) == []


def test_deleting_a_video_removes_it(auth_client):
    rid = _item(auth_client)
    vid = auth_client.post(f"/api/v1/items/{rid}/videos",
                      json={"url": "https://example.com/x"}).get_json()["id"]

    assert auth_client.delete(f"/api/v1/videos/{vid}").status_code == 204
    assert _videos_of(auth_client, rid) == []


