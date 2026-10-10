"""Read-only API keys are enforced centrally (before_request), not only by the
route decorators — a new /api/v1 route with no decorator is still covered."""
from flask import Blueprint

H = "/api/v1"


def _jwt(client):
    client.post(f"{H}/users/register",
                json={"email": "ro@x.com", "password": "pw123456", "name": "X"})
    return client.post(f"{H}/users/login",
                       json={"username": "ro@x.com", "password": "pw123456"}
                       ).get_json()["token"]


def _key(client, jwt, access):
    r = client.post(f"{H}/tokens", headers={"Authorization": jwt},
                    json={"name": access, "scope": "rest", "access": access})
    return f"Bearer {r.get_json()['token']}"


def _bare_route(app):
    bp = Blueprint("ro_probe", __name__)

    @bp.route("/ro-probe", methods=["GET", "POST"])
    def probe():  # deliberately NO auth decorator
        return {"ok": True}

    app.register_blueprint(bp, url_prefix=H)


def test_read_key_blocked_on_decorated_routes(app, client):
    jwt = _jwt(client)
    read = _key(client, jwt, "read")
    r = client.post(f"{H}/labels", json={"name": "x"}, headers={"Authorization": read})
    assert r.status_code == 403 and r.get_json()["error"] == "this API key is read-only"
    assert r.get_json()["requestId"]
    r = client.post(f"{H}/tokens", json={"name": "y"}, headers={"Authorization": read})
    assert r.status_code == 403  # owner_required route


def test_read_key_blocked_on_undecorated_route(app, client):
    _bare_route(app)
    jwt = _jwt(client)
    read, write = _key(client, jwt, "read"), _key(client, jwt, "write")
    assert client.post(f"{H}/ro-probe", headers={"Authorization": read}).status_code == 403
    assert client.get(f"{H}/ro-probe", headers={"Authorization": read}).status_code == 200
    assert client.post(f"{H}/ro-probe", headers={"Authorization": write}).status_code == 200


def test_jwt_user_still_writes(app, client):
    jwt = _jwt(client)
    r = client.post(f"{H}/labels", json={"name": "x"}, headers={"Authorization": jwt})
    assert r.status_code in (200, 201)


def test_bearer_scheme_is_case_insensitive_and_odd_schemes_never_fall_through(app, client):
    """RFC 7235 schemes are case-insensitive. `bearer <read-key>` used to miss the
    `Bearer ` prefix test, fall through to the open-mode user and get WRITE access.
    Any Authorization header that isn't a usable Bearer token is a 401 — it never
    downgrades to ingress/open-mode identity."""
    _bare_route(app)
    jwt = _jwt(client)
    read = _key(client, jwt, "read")
    app.config["DISABLE_AUTH"] = True  # open mode: the fall-through target exists
    for scheme in ("bearer", "BEARER"):
        hdr = {"Authorization": read.replace("Bearer", scheme, 1)}
        r = client.post(f"{H}/labels", json={"name": "x"}, headers=hdr)
        assert r.status_code == 403, (scheme, r.status_code)
        assert client.post(f"{H}/ro-probe", headers=hdr).status_code == 403
        assert client.get(f"{H}/labels", headers=hdr).status_code == 200
    for bad in ("Basic abc", "Bearer", "Bearer   ", "Token xyz"):
        r = client.post(f"{H}/labels", json={"name": "x"},
                        headers={"Authorization": bad})
        assert r.status_code == 401, (bad, r.status_code)
