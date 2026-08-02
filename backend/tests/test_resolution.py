"""Confidence-tiered resolution: rank on labels/description, act only when sure.

Resolving "drill" to an item is a guess, and acting on a wrong guess moves,
checks out, or edits the wrong thing. These tests pin the two halves of that
contract: the RANKING (a stronger kind of evidence wins, and tags/descriptions
count) and the CONFIDENCE gate (act on one when sure, otherwise hand back
candidates and change nothing).
"""
from app.services import resolve


def _label(client, item_id, name):
    """Attach a label to an item, creating it if needed."""
    lbl = client.post("/api/v1/labels", json={"name": name}).get_json()
    item = client.get(f"/api/v1/items/{item_id}").get_json()
    client.put(
        f"/api/v1/items/{item_id}",
        json={"name": item["name"], "labelIds": [lbl["id"]]},
    )
    return lbl


# --- scoring ---------------------------------------------------------------

def test_stronger_evidence_kind_outranks_weaker():
    rows = [
        {"id": "d", "name": "Cordless Drill Charger"},          # contains
        {"id": "a", "name": "Drill"},                            # exact
        {"id": "c", "name": "Drill Press"},                      # prefix
        {"id": "b", "name": "Screwdriver", "labels": ["drill"]},  # exact label
    ]
    order = [row["id"] for row, _s, _m in resolve.rank(rows, "drill")]
    assert order == ["a", "c", "d", "b"]


def test_a_label_only_match_is_found_and_explained():
    rows = [{"id": "x", "name": "Impact Driver", "labels": ["power tools"]}]
    (_row, score, matched_on), = resolve.rank(rows, "power tools")
    assert matched_on == "label"
    assert score == resolve.SCORE_EXACT_LABEL


def test_a_description_only_match_is_found_and_explained():
    rows = [{"id": "x", "name": "Box", "description": "spare fuses for the van"}]
    (_row, _score, matched_on), = resolve.rank(rows, "fuses")
    assert matched_on == "description"


def test_notes_are_searched_like_the_description():
    rows = [{"id": "x", "name": "Box", "notes": "holds the winter tyres"}]
    (_row, score, _m), = resolve.rank(rows, "tyres")
    assert score == resolve.SCORE_DESCRIPTION


def test_evidence_kind_beats_evidence_count():
    """One name match outranks a pile of weaker label/description hits."""
    many = {"id": "many", "name": "Box",
            "labels": ["drilling", "drill bits", "drills"],
            "description": "drill drill drill"}
    one = {"id": "one", "name": "Drill Press"}
    order = [row["id"] for row, _s, _m in resolve.rank([many, one], "drill")]
    assert order[0] == "one"


# --- confidence gate -------------------------------------------------------

def test_lone_match_is_confident():
    assert resolve.decide([{"id": "a", "name": "Drill"}], "drill")["confidence"] == "high"


def test_unique_exact_name_wins_over_other_matches():
    rows = [{"id": "a", "name": "Drill"}, {"id": "b", "name": "Drill bits"}]
    decision = resolve.decide(rows, "drill")
    assert decision["confidence"] == "high"
    assert decision["match"]["id"] == "a"


def test_items_sharing_a_name_are_never_guessed_between():
    rows = [{"id": "a", "name": "Drill"}, {"id": "b", "name": "Drill"}]
    assert resolve.decide(rows, "drill")["confidence"] == "low"


def test_substring_leader_alone_is_not_confident():
    """"drill" inside two longer names is weak evidence of intent."""
    rows = [{"id": "a", "name": "Cordless Drill Charger"},
            {"id": "b", "name": "Hammer Drill Case"}]
    assert resolve.decide(rows, "drill")["confidence"] == "low"


def test_low_confidence_returns_between_three_and_five_candidates():
    rows = [{"id": str(i), "name": f"Drill {i}"} for i in range(9)]
    decision = resolve.decide(rows, "drill")
    assert decision["confidence"] == "low"
    assert 3 <= len(decision["candidates"]) <= 5


def test_candidates_carry_labels_location_and_why_they_matched():
    rows = [
        {"id": "a", "name": "Drill", "labels": ["power tools"],
         "where": "Garage", "description": "corded"},
        {"id": "b", "name": "Drill", "labels": ["consumables"],
         "where": "Workshop", "description": "bits"},
    ]
    candidates = resolve.decide(rows, "drill")["candidates"]
    assert [c["where"] for c in candidates] == ["Garage", "Workshop"]
    assert candidates[0]["labels"] == ["power tools"]
    assert all(c["matchedOn"] == "name" for c in candidates)


def test_nothing_matching_is_none_not_low():
    assert resolve.decide([{"id": "a", "name": "Drill"}], "kettle")["confidence"] == "none"


# --- the endpoint both processes share -------------------------------------

def test_resolve_endpoint_is_confident_on_a_unique_exact_name(auth_client):
    auth_client.post("/api/v1/items", json={"name": "Drill"})
    auth_client.post("/api/v1/items", json={"name": "Drill bits"})
    r = auth_client.get("/api/v1/resolve?q=Drill").get_json()
    assert r["confidence"] == "high"
    assert r["match"]["name"] == "Drill"


def test_resolve_endpoint_takes_an_id_as_an_unambiguous_handle(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Drill"}).get_json()
    auth_client.post("/api/v1/items", json={"name": "Drill"})  # same name
    r = auth_client.get(f"/api/v1/resolve?q={item['id']}").get_json()
    assert r["confidence"] == "high"
    assert r["matchedOn"] == "id"
    assert r["match"]["id"] == item["id"]


def test_resolve_endpoint_asks_when_two_things_share_a_name(auth_client):
    auth_client.post("/api/v1/items", json={"name": "Drill"})
    auth_client.post("/api/v1/items", json={"name": "Drill"})
    r = auth_client.get("/api/v1/resolve?q=drill").get_json()
    assert r["confidence"] == "low"
    assert len(r["candidates"]) == 2


def test_resolve_endpoint_finds_an_item_by_its_label(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Impact Driver"}).get_json()
    _label(auth_client, item["id"], "power tools")
    r = auth_client.get("/api/v1/resolve?q=power tools").get_json()
    assert r["confidence"] == "high"
    assert r["match"]["name"] == "Impact Driver"
    assert r["matchedOn"] == "label"


def test_resolve_endpoint_resolves_bins_and_locations_too(auth_client):
    auth_client.post("/api/v1/locations", json={"name": "Garage"})
    r = auth_client.get("/api/v1/resolve?q=Garage&type=location").get_json()
    assert r["confidence"] == "high"
    assert r["match"]["name"] == "Garage"


def test_resolve_endpoint_rejects_an_unknown_type(auth_client):
    assert auth_client.get("/api/v1/resolve?q=x&type=teapot").status_code == 400


def test_resolve_endpoint_requires_a_query(auth_client):
    assert auth_client.get("/api/v1/resolve?q=").status_code == 400


# --- search ranking (the signal that used to be discarded) -----------------

def test_search_ranks_an_exact_name_above_an_incidental_mention(auth_client):
    box = auth_client.post("/api/v1/items", json={"name": "A Box"}).get_json()
    auth_client.put(
        f"/api/v1/items/{box['id']}",
        json={"name": "A Box", "description": "holds the drill"},
    )
    auth_client.post("/api/v1/items", json={"name": "Drill"})
    results = auth_client.get("/api/v1/search?q=drill").get_json()["results"]
    # Alphabetically "A Box" sorts first; by relevance the real drill wins.
    assert results[0]["name"] == "Drill"
    assert results[0]["matchedOn"] == "name"
    assert results[1]["matchedOn"] == "description"
