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
    assert r.status_code == 403 and r.get_json() == {"error": "this API key is read-only"}
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
