"""Class-killer IDOR sweep: every /api/v1 route taking an object id must refuse
(403/404) another household's object. New id parameters must be covered here or
listed in KNOWN_UNCOVERED with a reason, or the sweep fails."""
import io
import re

from app.extensions import db
from app.models import AiSuggestion, ChatSession, Job, User

H = "/api/v1"

# Param names the sweep cannot (yet) build a cross-group object for. Adding a new
# id param anywhere under /api/v1 fails the sweep until it lands here or in _ids().
KNOWN_UNCOVERED = {
    "code": "barcode/identify value, not an object id",
    "kind": "job kind enum, not an object id",
    "path": "static path, not an object id",
    "value": "static path, not an object id",
}

# Routes that may legitimately answer 2xx to another group's id, because the id is
# re-resolved inside the caller's own group (verified by reading each route). A 2xx
# here passes only if none of A's object ids appear in the body.
OWN_SCOPE_2XX = {
    # misc.get_by_asset filters Item by current_group + asset number; asset numbers
    # are per group, so B's request for "000-001" returns B's own item #1.
    f"{H}/assets/<asset_id>": "per-group asset number, resolved in the caller's group",
}


def _tok(client, email):
    client.post(f"{H}/users/register",
                json={"email": email, "password": "pw123456", "name": "X"})
    return client.post(f"{H}/users/login",
                       json={"username": email, "password": "pw123456"}
                       ).get_json()["token"]


def _file(name, body=b"\x89PNG\r\n\x1a\nfake"):
    return {"file": (io.BytesIO(body), name), "type": "photo", "name": name}


def _ids(app, client, a):
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
    notifier = post("/notifiers", json={"name": "n", "url": ""})
    # Jobs, chat sessions and suggestions are created by worker/AI flows; insert
    # the rows directly in A's group.
    uid = client.get(f"{H}/users/self", headers={"Authorization": a}).get_json()["item"]["id"]
    with app.app_context():
        gid = db.session.get(User, uid).group_id
        rows = (Job(kind="enrich", group_id=gid), ChatSession(group_id=gid),
                AiSuggestion(kind="categorize", label="Tools", item_id=item["id"],
                             group_id=gid))
        db.session.add_all(rows)
        db.session.commit()
        job_id, session_id, sugg_id = (r.id for r in rows)
    att, bin_att, video = (x["attachments"][-1] if "attachments" in x else x
                           for x in (att, bin_att, video))  # uploads return the parent
    doc_id = att["document"]["id"]
    return {
        "item_id": item["id"], "bin_id": b["id"], "location_id": loc["id"],
        "label_id": label["id"], "holding_id": holding["id"],
        "attachment_id": att["id"], "entry_id": entry["id"], "tag_id": tag["id"],
        "token_id": token["id"], "document_id": doc_id,
        "_bin_attachment_id": bin_att["id"], "_video_id": video["id"],
        "job_id": job_id, "session_id": session_id, "sugg_id": sugg_id,
        "notifier_id": notifier["id"], "asset_id": item["assetId"],
    }


def _url(rule, ids):
    path = rule.rule
    if path.startswith(f"{H}/bins/"):
        path = path.replace("<attachment_id>", ids["_bin_attachment_id"])
    if path.startswith(f"{H}/videos/"):
        path = path.replace("<attachment_id>", ids["_video_id"])
    # Uncovered params (codes, enums) get a placeholder; the covered id still has
    # to be refused.
    return re.sub(r"<(?:\w+:)?(\w+)>", lambda m: str(ids.get(m.group(1), 1)), path)


def _id_rules(app):
    return [r for r in app.url_map.iter_rules()
            if r.rule.startswith(H + "/") and r.arguments]


def test_every_id_param_is_covered_or_known(app, client):
    ids = _ids(app, client, _tok(client, "sa@x.com"))
    params = {p for r in _id_rules(app) for p in r.arguments}
    unknown = params - set(ids) - set(KNOWN_UNCOVERED)
    assert not unknown, f"new id params need a sweep factory or KNOWN_UNCOVERED: {unknown}"


def test_no_route_reaches_another_groups_object(app, client):
    a, b = _tok(client, "sa@x.com"), _tok(client, "sb@x.com")
    ids, own_b = _ids(app, client, a), _ids(app, client, b)
    # Skip a rule only when NONE of its params are covered: a rule mixing a covered
    # id with a code/enum is still probed on the id.
    rules = [r for r in _id_rules(app) if set(r.arguments) - set(KNOWN_UNCOVERED)]
    a_ids = {v for k, v in ids.items() if isinstance(v, str) and k != "asset_id"}
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
        if r.status_code not in (403, 404) and not (
                rule.rule in OWN_SCOPE_2XX and r.status_code < 300
                and not a_ids & set(re.findall(r"[0-9a-f-]{36}", r.get_data(as_text=True)))):
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
    # 49 rules were probed before job/chat/suggestion/notifier/asset got factories;
    # a filter regression that drops them shows up here.
    assert len(rules) > 49 + 5, len(rules)
    assert not leaks, f"{len(leaks)} cross-group leaks:\n" + "\n".join(leaks)


# Foreign ids smuggled in the BODY of a write to B's own objects. Each must be
# refused (404/422) or, where the route silently drops foreign ids, succeed without
# binding any of A's objects.
BODY_PROBES = [
    ("POST", "/bins", {"name": "x", "locationId": "{location_id}"}),
    ("PUT", "/bins/{own_bin_id}", {"locationId": "{location_id}"}),
    ("POST", "/items", {"name": "x", "binId": "{bin_id}"}),
    ("POST", "/items", {"name": "x", "locationId": "{location_id}"}),
    ("PUT", "/items/{own_item_id}", {"binId": "{bin_id}"}),
    ("PUT", "/items/{own_item_id}", {"locationId": "{location_id}"}),
    ("PUT", "/items/{own_item_id}", {"parentId": "{item_id}"}),
    ("PUT", "/items/{own_item_id}", {"labelIds": ["{label_id}"]}),
    ("POST", "/locations", {"name": "x", "parentId": "{location_id}"}),
    ("PUT", "/locations/{own_location_id}", {"parentId": "{location_id}"}),
    ("POST", "/items/{own_item_id}/holdings", {"binId": "{bin_id}", "quantity": 1}),
]


def _fill(v, ids):
    if isinstance(v, str):
        return v.format(**ids)
    if isinstance(v, list):
        return [_fill(x, ids) for x in v]
    if isinstance(v, dict):
        return {k: _fill(x, ids) for k, x in v.items()}
    return v


def test_foreign_ids_in_body_are_refused(app, client):
    a, b = _tok(client, "sa@x.com"), _tok(client, "sb@x.com")
    ids, own_b = _ids(app, client, a), _ids(app, client, b)
    fmt = {**ids, **{f"own_{k}": v for k, v in own_b.items()}}
    foreign = ("/locations/{location_id}", "/bins/{bin_id}", "/items/{item_id}",
               "/labels/{label_id}")

    def snapshot():
        return [client.get(H + p.format(**ids), headers={"Authorization": a}).get_json()
                for p in foreign]

    before = snapshot()
    a_ids = {v for v in ids.values() if isinstance(v, str)}
    bad = []
    for method, path, body in BODY_PROBES:
        r = client.open(H + path.format(**fmt), method=method,
                        headers={"Authorization": b}, json=_fill(body, ids))
        text = r.get_data(as_text=True)
        bound = a_ids & set(re.findall(r"[0-9a-f-]{36}", text))
        if r.status_code not in (404, 422) and (r.status_code >= 300 or bound):
            bad.append(f"{method} {path} {body} -> {r.status_code} {sorted(bound)}")
    assert not bad, "foreign ids accepted in body:\n" + "\n".join(bad)
    assert snapshot() == before, "A's objects changed under B's body probes"


def test_group_peer_cannot_touch_another_members_notifier(app, client):
    a, c = _tok(client, "sa@x.com"), _tok(client, "sc@x.com")
    ids = _ids(app, client, a)
    with app.app_context():  # make C a member of A's household
        ua, uc = (db.session.query(User).filter_by(email=e).one()
                  for e in ("sa@x.com", "sc@x.com"))
        uc.group_id = ua.group_id
        db.session.commit()
    # Control: C really is in A's group, so a 404 below is the per-user check.
    assert client.get(f"{H}/items/{ids['item_id']}",
                      headers={"Authorization": c}).status_code == 200
    url = f"{H}/notifiers/{ids['notifier_id']}"
    assert client.put(url, headers={"Authorization": c},
                      json={"name": "pwn"}).status_code == 404
    assert client.delete(url, headers={"Authorization": c}).status_code == 404
    mine = client.get(f"{H}/notifiers", headers={"Authorization": a}).get_json()
    assert [n["name"] for n in mine if n["id"] == ids["notifier_id"]] == ["n"]
