"""Class-killer IDOR sweep: every /api/v1 route taking an object id must refuse
(403/404) another household's object. New id parameters must be covered here or
listed in KNOWN_UNCOVERED with a reason, or the sweep fails."""
import io
import re

H = "/api/v1"

# Param names the sweep cannot (yet) build a cross-group object for. Adding a new
# id param anywhere under /api/v1 fails the sweep until it lands here or in _ids().
KNOWN_UNCOVERED = {
    "asset_id": "per-group asset number, not a row id; looked up via a group filter",
    "code": "barcode/identify value, not an object id",
    "kind": "job kind enum, not an object id",
    "job_id": "jobs are created by background flows, not a plain POST",
    "session_id": "chat sessions need an AI provider to create",
    "sugg_id": "suggestions are produced by AI jobs",
    "notifier_id": "notifier creation needs an outbound target; covered elsewhere",
    "path": "static path, not an object id",
    "value": "static path, not an object id",
}


def _tok(client, email):
    client.post(f"{H}/users/register",
                json={"email": email, "password": "pw123456", "name": "X"})
    return client.post(f"{H}/users/login",
                       json={"username": email, "password": "pw123456"}
                       ).get_json()["token"]


def _file(name, body=b"\x89PNG\r\n\x1a\nfake"):
    return {"file": (io.BytesIO(body), name), "type": "photo", "name": name}


def _ids(client, a):
    """Create one of everything as user A; return {param name: id} plus variants."""
    def post(path, **kw):
        r = client.post(H + path, headers={"Authorization": a}, **kw)
        assert r.status_code in (200, 201), (path, r.status_code, r.get_data(as_text=True))
        return r.get_json()

    loc = post("/locations", json={"name": "Garage"})
    b = post("/bins", json={"name": "B1", "locationId": loc["id"]})
    label = post("/labels", json={"name": "Tools"})
    item = post("/items", json={"name": "Drill", "binId": b["id"]})
    holding = post(f"/items/{item['id']}/holdings", json={"binId": b["id"], "quantity": 2})
    att = post(f"/items/{item['id']}/attachments", data=_file("a.png"),
               content_type="multipart/form-data")
    bin_att = post(f"/bins/{b['id']}/attachments", data=_file("b.png"),
                   content_type="multipart/form-data")
    entry = post(f"/items/{item['id']}/maintenance", json={"name": "Oil change"})
    video = post(f"/items/{item['id']}/videos",
                 data={"file": (io.BytesIO(b"\x00\x00\x00\x20ftypisom fake"), "v.mp4")},
                 content_type="multipart/form-data")
    tag = post("/qr-tags", json={"kind": "item", "targetId": item["id"],
                                  "source": "external", "code": f"SW-{item['id'][:8]}"})
    token = post("/tokens", json={"name": "k"})
    att, bin_att, video = (x["attachments"][-1] if "attachments" in x else x
                           for x in (att, bin_att, video))  # uploads return the parent
    doc_id = att["document"]["id"]
    return {
        "item_id": item["id"], "bin_id": b["id"], "location_id": loc["id"],
        "label_id": label["id"], "holding_id": holding["id"],
        "attachment_id": att["id"], "entry_id": entry["id"], "tag_id": tag["id"],
        "token_id": token["id"], "document_id": doc_id,
        "_bin_attachment_id": bin_att["id"], "_video_id": video["id"],
    }


def _url(rule, ids):
    path = rule.rule
    if path.startswith(f"{H}/bins/"):
        path = path.replace("<attachment_id>", ids["_bin_attachment_id"])
    if path.startswith(f"{H}/videos/"):
        path = path.replace("<attachment_id>", ids["_video_id"])
    return re.sub(r"<(?:\w+:)?(\w+)>", lambda m: str(ids[m.group(1)]), path)


def _id_rules(app):
    return [r for r in app.url_map.iter_rules()
            if r.rule.startswith(H + "/") and r.arguments]


def test_every_id_param_is_covered_or_known(app, client):
    ids = _ids(client, _tok(client, "sa@x.com"))
    params = {p for r in _id_rules(app) for p in r.arguments}
    unknown = params - set(ids) - set(KNOWN_UNCOVERED)
    assert not unknown, f"new id params need a sweep factory or KNOWN_UNCOVERED: {unknown}"


def test_no_route_reaches_another_groups_object(app, client):
    a, b = _tok(client, "sa@x.com"), _tok(client, "sb@x.com")
    ids, own_b = _ids(client, a), _ids(client, b)
    rules = [r for r in _id_rules(app) if not set(r.arguments) & set(KNOWN_UNCOVERED)]
    # Positive control first: the owner can reach every GET, so a 404 from B means
    # "scoped", not "broken route". Then B's probes, DELETEs last — a leaking DELETE
    # would otherwise remove A's object and mask leaks on later routes.
    controls = 0
    for rule in rules:
        if "GET" in rule.methods:
            own = client.get(_url(rule, ids), headers={"Authorization": a})
            assert own.status_code != 404, f"control: owner GET {rule.rule} 404'd"
            controls += 1
    probes = sorted(((m, rule) for rule in rules
                     for m in rule.methods - {"HEAD", "OPTIONS"}),
                    key=lambda p: p[0] == "DELETE")
    leaks = []
    for method, rule in probes:
        kw = {} if method == "GET" else {"json": {}}
        r = client.open(_url(rule, ids), method=method,
                        headers={"Authorization": b}, **kw)
        if r.status_code not in (403, 404):
            leaks.append(f"{method} {rule.rule} -> {r.status_code}")
        # Child routes: B's OWN parent + A's child id must not pass the FK check.
        parent = re.match(r"[^<]*<(?:\w+:)?(\w+)>", rule.rule).group(1)
        if parent in ("item_id", "bin_id") and len(rule.arguments) > 1:
            mixed = {**ids, parent: own_b[parent]}
            r = client.open(_url(rule, mixed), method=method,
                            headers={"Authorization": b}, **kw)
            if r.status_code not in (403, 404):
                leaks.append(f"{method} {rule.rule} (B's parent) -> {r.status_code}")
    swept = len(probes)
    assert swept > 40 and controls > 10, (swept, controls)  # can't pass vacuously
    assert not leaks, f"{len(leaks)} cross-group leaks:\n" + "\n".join(leaks)
