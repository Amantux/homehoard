"""MCP tools must ask rather than guess when a name is ambiguous.

The tools reach the app over HTTP, so these stub the ``/resolve`` call and
assert on BEHAVIOUR: on a low-confidence name nothing is written and the
candidates come back for the user to choose from. A tool that "helpfully" acts
on the top candidate is exactly the bug this guards.
"""
import mcp_server

LOW = {
    "confidence": "low",
    "candidates": [
        {"id": "1", "name": "Drill", "labels": ["power tools"],
         "where": "Garage", "description": "corded", "matchedOn": "name"},
        {"id": "2", "name": "Drill bits", "labels": ["consumables"],
         "where": "Workshop", "description": "", "matchedOn": "name"},
    ],
}


def _stub(monkeypatch, resolve_payload):
    """Route /resolve to a canned decision; fail loudly on any write."""
    writes = []

    def fake_get(path, params=None):
        if path == "/resolve":
            return resolve_payload
        raise AssertionError(f"unexpected GET {path}")

    def boom(path, json=None):
        writes.append(path)
        raise AssertionError(f"wrote to {path} on an ambiguous name")

    monkeypatch.setattr(mcp_server, "_get", fake_get)
    monkeypatch.setattr(mcp_server, "_post", boom)
    monkeypatch.setattr(mcp_server, "_patch", boom)
    return writes


def _call(tool, /, **kwargs):
    """Invoke the undecorated function behind an MCP tool."""
    return getattr(tool, "fn", tool)(**kwargs)


# --- impactful tools must not act on a coin-flip ---------------------------

def test_check_out_item_asks_instead_of_checking_out(monkeypatch):
    writes = _stub(monkeypatch, LOW)
    out = _call(mcp_server.check_out_item, name="drill")
    assert writes == []
    assert "Drill" in out and "Drill bits" in out
    assert "Nothing was changed" in out


def test_check_in_item_asks_instead_of_checking_in(monkeypatch):
    writes = _stub(monkeypatch, LOW)
    out = _call(mcp_server.check_in_item, name="drill")
    assert writes == []
    assert "Nothing was changed" in out


def test_move_item_asks_instead_of_moving(monkeypatch):
    writes = _stub(monkeypatch, LOW)
    out = _call(mcp_server.move_item, name_or_id="drill", to_bin="Bin A")
    assert writes == []
    assert "Nothing was changed" in out


def test_update_item_asks_instead_of_editing(monkeypatch):
    writes = _stub(monkeypatch, LOW)
    out = _call(mcp_server.update_item, name_or_id="drill", notes="x")
    assert writes == []
    assert "Nothing was changed" in out


def test_set_checkout_details_asks_instead_of_writing(monkeypatch):
    writes = _stub(monkeypatch, LOW)
    out = _call(mcp_server.set_checkout_details, name_or_id="drill", person="Sam")
    assert writes == []
    assert "Nothing was changed" in out


def test_add_item_placement_asks_instead_of_stocking(monkeypatch):
    writes = _stub(monkeypatch, LOW)
    out = _call(mcp_server.add_item_placement, name_or_id="drill", to_bin="Bin A")
    assert writes == []
    assert "Nothing was changed" in out


def test_describe_item_asks_instead_of_describing(monkeypatch):
    writes = _stub(monkeypatch, LOW)
    out = _call(mcp_server.describe_item, name_or_id="drill")
    assert writes == []
    assert "Nothing was changed" in out


# --- the clarification is actually usable ----------------------------------

def test_clarification_names_where_each_candidate_lives(monkeypatch):
    _stub(monkeypatch, LOW)
    out = _call(mcp_server.check_out_item, name="drill")
    # Location is the disambiguator a person can act on.
    assert "in Garage" in out and "in Workshop" in out
    assert "power tools" in out


def test_get_item_returns_structured_clarification(monkeypatch):
    _stub(monkeypatch, LOW)
    out = _call(mcp_server.get_item, name_or_id="drill")
    assert out["needsClarification"] is True
    assert len(out["candidates"]) == 2
    assert out["candidates"][0]["where"] == "Garage"


def test_ambiguous_bin_stops_a_move(monkeypatch):
    """The destination is resolved too — an ambiguous bin must not be guessed."""
    writes = []

    def fake_get(path, params=None):
        if path == "/resolve" and params.get("type") == "item":
            return {"confidence": "high", "match": {"id": "9", "name": "Drill"}}
        if path == "/resolve" and params.get("type") == "bin":
            return LOW
        raise AssertionError(f"unexpected GET {path}")

    monkeypatch.setattr(mcp_server, "_get", fake_get)
    monkeypatch.setattr(mcp_server, "_post",
                        lambda p, json=None: writes.append(p))
    monkeypatch.setattr(mcp_server, "_patch",
                        lambda p, json=None: writes.append(p))
    out = _call(mcp_server.move_item, name_or_id="Drill", to_bin="bin")
    assert writes == []
    assert "bins" in out and "Nothing was changed" in out


# --- confident matches still act, with no extra friction -------------------

def test_a_confident_match_still_acts(monkeypatch):
    calls = []

    def fake_get(path, params=None):
        assert path == "/resolve"
        return {"confidence": "high", "match": {"id": "9", "name": "Drill"}}

    monkeypatch.setattr(mcp_server, "_get", fake_get)
    monkeypatch.setattr(mcp_server, "_post",
                        lambda p, json=None: calls.append(p) or {})
    out = _call(mcp_server.check_out_item, name="Drill")
    assert calls == ["/items/9/checkout"]
    assert "Drill" in out
