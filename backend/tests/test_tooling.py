"""AI tooling: confidence-gated auto-categorize, cluster proposals, review queue,
and in-context-learning feedback. No live vendor calls (a fake provider is injected).
"""
from app.extensions import db
from app.models import AiSuggestion, Group, Item, Label, User
from app.services import jobs


def _gid(app):
    with app.app_context():
        return db.session.query(User).filter_by(email="t@t.com").first().group_id


class _FakeProvider:
    """Returns a fixed JSON response and records every prompt it sees."""

    def __init__(self, response):
        self.response = response
        self.prompts = []

    def complete_json(self, prompt, system="", max_tokens=4096):
        self.prompts.append(prompt)
        return self.response


def _use_provider(monkeypatch, provider):
    monkeypatch.setattr("app.services.ai.registry.get_provider", lambda config=None: provider)


def _run(kind, gid):
    jobs.enqueue(kind, gid)
    jobs.run_job(jobs.claim_one())


def test_categorize_auto_applies_high_confidence_existing_label(auth_client, app, monkeypatch):
    gid = _gid(app)
    with app.app_context():
        db.session.add(Label(name="Tools", group_id=gid))
        db.session.add(Item(name="Cordless drill", group_id=gid))
        db.session.commit()
        _use_provider(monkeypatch, _FakeProvider(
            {"label": "Tools", "confidence": 0.95, "rationale": "it's a tool"}))

        _run("categorize", gid)

        item = db.session.query(Item).filter_by(name="Cordless drill").first()
        assert "Tools" in [lb.name for lb in item.labels]  # auto-applied
        acc = db.session.query(AiSuggestion).filter_by(status="accepted").all()
        assert len(acc) == 1 and acc[0].kind == "categorize"


def test_categorize_queues_low_confidence_or_new_label(auth_client, app, monkeypatch):
    gid = _gid(app)
    with app.app_context():
        db.session.add(Item(name="Mystery widget", group_id=gid))
        db.session.commit()
        _use_provider(monkeypatch, _FakeProvider(
            {"label": "Gadgets", "confidence": 0.4, "rationale": "guessing"}))

        _run("categorize", gid)

        item = db.session.query(Item).filter_by(name="Mystery widget").first()
        assert item.labels == []  # NOT auto-applied
        pend = db.session.query(AiSuggestion).filter_by(status="pending").all()
        assert len(pend) == 1 and pend[0].label == "Gadgets"


def test_categorize_new_label_high_confidence_still_queues(auth_client, app, monkeypatch):
    # High confidence but the label doesn't exist yet → review, never auto-create.
    gid = _gid(app)
    with app.app_context():
        db.session.add(Item(name="Tent", group_id=gid))
        db.session.commit()
        _use_provider(monkeypatch, _FakeProvider(
            {"label": "Camping", "confidence": 0.99, "rationale": "outdoors"}))

        _run("categorize", gid)

        assert db.session.query(AiSuggestion).filter_by(status="pending").count() == 1
        assert db.session.query(Label).count() == 0  # no label auto-created


def test_accept_categorize_suggestion_applies_label(auth_client, app):
    gid = _gid(app)
    with app.app_context():
        item = Item(name="Rope", group_id=gid)
        db.session.add(item)
        db.session.flush()
        s = AiSuggestion(kind="categorize", status="pending", label="Camping",
                         confidence=0.4, item_id=item.id, group_id=gid)
        db.session.add(s)
        db.session.commit()
        sid, iid = s.id, item.id

    r = auth_client.post(f"/api/v1/suggestions/{sid}/accept")
    assert r.status_code == 200
    with app.app_context():
        item = db.session.get(Item, iid)
        assert "Camping" in [lb.name for lb in item.labels]  # label created + attached
        assert db.session.get(AiSuggestion, sid).status == "accepted"


def test_reject_suggestion(auth_client, app):
    gid = _gid(app)
    with app.app_context():
        s = AiSuggestion(kind="categorize", status="pending", label="Nope",
                         confidence=0.3, group_id=gid)
        db.session.add(s)
        db.session.commit()
        sid = s.id
    assert auth_client.post(f"/api/v1/suggestions/{sid}/reject").status_code == 200
    with app.app_context():
        assert db.session.get(AiSuggestion, sid).status == "rejected"


def test_cluster_job_creates_pending_proposals(auth_client, app, monkeypatch):
    gid = _gid(app)
    with app.app_context():
        for n in ("Tent", "Sleeping bag", "Frying pan"):
            db.session.add(Item(name=n, group_id=gid))
        db.session.commit()
        _use_provider(monkeypatch, _FakeProvider(
            {"clusters": [{"name": "Camping gear", "indices": [0, 1], "confidence": 0.9}]}))

        _run("cluster", gid)

        pend = db.session.query(AiSuggestion).filter_by(kind="cluster", status="pending").all()
        assert len(pend) == 1 and pend[0].label == "Camping gear"


def test_accept_cluster_labels_all_members(auth_client, app):
    import json
    gid = _gid(app)
    with app.app_context():
        a = Item(name="Tent", group_id=gid)
        b = Item(name="Sleeping bag", group_id=gid)
        db.session.add_all([a, b])
        db.session.flush()
        s = AiSuggestion(kind="cluster", status="pending", label="Camping",
                         confidence=0.9, payload=json.dumps({"itemIds": [a.id, b.id]}),
                         group_id=gid)
        db.session.add(s)
        db.session.commit()
        sid, aid, bid = s.id, a.id, b.id

    assert auth_client.post(f"/api/v1/suggestions/{sid}/accept").status_code == 200
    with app.app_context():
        for iid in (aid, bid):
            assert "Camping" in [lb.name for lb in db.session.get(Item, iid).labels]


def test_icl_examples_feed_into_prompt(auth_client, app, monkeypatch):
    from app.models import utcnow
    gid = _gid(app)
    with app.app_context():
        db.session.add(Item(name="Hatchet", group_id=gid))
        db.session.add(AiSuggestion(kind="categorize", status="accepted", label="Tools",
                                    confidence=0.9, group_id=gid, resolved_at=utcnow()))
        db.session.add(AiSuggestion(kind="categorize", status="rejected", label="Kitchen",
                                    confidence=0.5, group_id=gid, resolved_at=utcnow()))
        db.session.commit()
        fake = _FakeProvider({"label": "Tools", "confidence": 0.5})
        _use_provider(monkeypatch, fake)

        _run("categorize", gid)

        assert any("ACCEPTED" in p and "REJECTED" in p for p in fake.prompts)


def test_categorize_job_errors_without_provider(auth_client, app):
    gid = _gid(app)
    with app.app_context():
        db.session.add(Item(name="Thing", group_id=gid))
        db.session.commit()
        job = jobs.enqueue("categorize", gid)
        jobs.run_job(jobs.claim_one())
        from app.models import Job
        assert db.session.get(Job, job.id).status == "error"  # no AI provider configured


def test_delete_item_with_suggestion_succeeds(auth_client, app):
    # After auto-categorize, every item has an accepted suggestion pointing at it;
    # deleting the item must cascade the suggestion, not 500 on the FK.
    gid = _gid(app)
    with app.app_context():
        item = Item(name="Disposable", group_id=gid)
        db.session.add(item)
        db.session.flush()
        db.session.add(AiSuggestion(kind="categorize", status="accepted", label="X",
                                    confidence=0.9, item_id=item.id, group_id=gid))
        db.session.commit()
        iid = item.id

    assert auth_client.delete(f"/api/v1/items/{iid}").status_code in (200, 204)
    with app.app_context():
        assert db.session.query(AiSuggestion).filter_by(item_id=iid).count() == 0


def test_categorize_malformed_confidence_completes(auth_client, app, monkeypatch):
    gid = _gid(app)
    with app.app_context():
        db.session.add(Item(name="Thing", group_id=gid))
        db.session.commit()
        # A hallucinated non-numeric confidence must not abort the whole job.
        _use_provider(monkeypatch, _FakeProvider({"label": "Tools", "confidence": "high"}))

        _run("categorize", gid)

        from app.models import Job
        job = db.session.query(Job).filter_by(kind="categorize").first()
        assert job.status == "done"  # coerced to 0.0, queued, not crashed
        assert db.session.query(AiSuggestion).filter_by(status="pending").count() == 1


def test_suggestion_cross_group_404(auth_client, app):
    with app.app_context():
        other = Group(name="Other", currency="usd")
        db.session.add(other)
        db.session.flush()
        s = AiSuggestion(kind="categorize", status="pending", label="X", group_id=other.id)
        db.session.add(s)
        db.session.commit()
        sid = s.id
    assert auth_client.post(f"/api/v1/suggestions/{sid}/accept").status_code == 404
