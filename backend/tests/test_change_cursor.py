"""GET /changes — the cheap cursor the SPA polls to know WHEN to refetch.

Background writers (MCP, HA services, the chat assistant) change the database
without the browser knowing. The SPA polls this instead of the data: same
cursor -> nothing to do; a new cursor -> bump dataVersion and let every open
view quiet-refresh. So the only contract that matters is: the cursor MOVES when
data changes, and holds still when it doesn't.
"""


def test_cursor_moves_when_an_item_changes(auth_client):
    before = auth_client.get("/api/v1/changes").get_json()["cursor"]

    auth_client.post("/api/v1/items", json={"name": "Drill"})
    after = auth_client.get("/api/v1/changes").get_json()["cursor"]

    assert after != before, "creating an item did not move the cursor"


def test_cursor_holds_still_when_nothing_changes(auth_client):
    auth_client.post("/api/v1/items", json={"name": "Drill"})
    a = auth_client.get("/api/v1/changes").get_json()["cursor"]
    b = auth_client.get("/api/v1/changes").get_json()["cursor"]

    assert a == b, "polling alone moved the cursor (would refetch forever)"


def test_cursor_moves_for_the_other_hot_tables_too(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Drill"}).get_json()
    c0 = auth_client.get("/api/v1/changes").get_json()["cursor"]

    auth_client.post("/api/v1/locations", json={"name": "Shed"})
    c1 = auth_client.get("/api/v1/changes").get_json()["cursor"]
    assert c1 != c0

    auth_client.post(f"/api/v1/items/{item['id']}/checkout", json={"person": "Sam"})
    c2 = auth_client.get("/api/v1/changes").get_json()["cursor"]
    assert c2 != c1


def test_cursor_requires_auth(client):
    assert client.get("/api/v1/changes").status_code == 401
