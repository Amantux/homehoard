"""Search must survive how PEOPLE actually type, not how SQL LIKE works.

A 46-item persona run showed the most natural queries failing: 'battery' found
nothing (batteries != %battery%), 'screwdriver phillips' found nothing (LIKE
needs the words contiguous and ordered), 'dewalt drill' found nothing (brand
and noun are not adjacent in the name). For an app whose whole promise is
"where is it", these are the core queries.
"""


def _seed(c):
    for name in ("AA batteries", "Phillips screwdriver #2",
                 "DeWalt 20V MAX XR Brushless Cordless Hammer Drill",
                 "HDMI cable"):
        c.post("/api/v1/items", json={"name": name})


def _names(c, q):
    from urllib.parse import quote
    return [r["name"] for r in c.get(f"/api/v1/search?q={quote(q)}").get_json()["results"]]


def test_singular_finds_the_plural(auth_client):
    _seed(auth_client)
    assert any("batteries" in n for n in _names(auth_client, "battery"))


def test_words_out_of_order_still_match(auth_client):
    _seed(auth_client)
    assert any("Phillips screwdriver" in n
               for n in _names(auth_client, "screwdriver phillips"))


def test_brand_and_noun_apart_in_the_name(auth_client):
    _seed(auth_client)
    assert any("DeWalt" in n for n in _names(auth_client, "dewalt drill"))


def test_every_word_must_match_not_any(auth_client):
    """AND semantics: 'hdmi drill' should find nothing, not everything."""
    _seed(auth_client)
    assert _names(auth_client, "hdmi drill") == []


def test_trailing_s_typo_still_finds_it(auth_client):
    _seed(auth_client)
    assert any("batteries" in n for n in _names(auth_client, "batterys"))
