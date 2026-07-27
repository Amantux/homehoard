"""Background job engine: enqueue, atomic claim, run, reap, and the enrich handler.

The worker poller is disabled in tests (WORKER_ENABLED=False); these drive the job
functions directly for determinism. No live vendor calls (enrich.describe is stubbed).
"""
from datetime import timedelta

from app.extensions import db
from app.models import Group, Item, Job, User, utcnow
from app.services import jobs


def _gid(app):
    with app.app_context():
        return db.session.query(User).filter_by(email="t@t.com").first().group_id


def test_enqueue_creates_pending_and_dedups(auth_client, app):
    gid = _gid(app)
    with app.app_context():
        a = jobs.enqueue("enrich", gid)
        b = jobs.enqueue("enrich", gid)  # active one exists → same job
        assert a.id == b.id and a.status == "pending"
        assert db.session.query(Job).filter_by(kind="enrich").count() == 1


def test_enqueue_unknown_kind_raises(app):
    with app.app_context():
        try:
            jobs.enqueue("nope", "g")
            assert False, "expected JobError"
        except jobs.JobError:
            pass


def test_claim_is_atomic_no_double_run(auth_client, app):
    gid = _gid(app)
    with app.app_context():
        jobs.enqueue("enrich", gid)
        first = jobs.claim_one()
        second = jobs.claim_one()  # nothing pending now
        assert first is not None and first.status == "running"
        assert second is None


def test_enrich_job_describes_missing_items(auth_client, app, monkeypatch):
    gid = _gid(app)
    with app.app_context():
        db.session.add_all([Item(name="Drill", group_id=gid),
                            Item(name="Ladder", group_id=gid, search_text="already")])
        db.session.commit()
        monkeypatch.setattr("app.services.enrich.enabled", lambda: True)
        monkeypatch.setattr("app.services.enrich.describe",
                            lambda fields: {"description": "a power tool", "keywords": ["tool"]})

        job = jobs.enqueue("enrich", gid)
        claimed = jobs.claim_one()
        jobs.run_job(claimed)

        done = db.session.get(Job, job.id)
        assert done.status == "done"
        import json
        result = json.loads(done.result)
        assert result["described"] == 1 and result["scanned"] == 1 and result["remaining"] == 0
        drill = db.session.query(Item).filter_by(name="Drill").first()
        assert "power tool" in drill.search_text


def test_enrich_job_errors_when_not_configured(auth_client, app, monkeypatch):
    gid = _gid(app)
    with app.app_context():
        monkeypatch.setattr("app.services.enrich.enabled", lambda: False)
        job = jobs.enqueue("enrich", gid)
        jobs.run_job(jobs.claim_one())
        assert db.session.get(Job, job.id).status == "error"


def test_reap_stale_requeues_dead_running_job(auth_client, app):
    gid = _gid(app)
    with app.app_context():
        j = Job(kind="enrich", group_id=gid, status="running",
                started_at=utcnow() - timedelta(hours=1))
        db.session.add(j)
        db.session.commit()
        assert jobs.reap_stale() == 1
        assert db.session.get(Job, j.id).status == "pending"


def test_reap_stale_spares_a_live_heartbeated_job(auth_client, app):
    # A long-but-live job heartbeats started_at via bump(); it must NOT be reaped
    # (that was the double-run BLOCKER — a sibling worker requeuing a running job).
    gid = _gid(app)
    with app.app_context():
        j = Job(kind="enrich", group_id=gid, status="running", started_at=utcnow())
        db.session.add(j)
        db.session.commit()
        assert jobs.reap_stale() == 0
        assert db.session.get(Job, j.id).status == "running"


def test_only_one_active_job_per_group_kind_is_enforced(auth_client, app):
    from sqlalchemy.exc import IntegrityError
    gid = _gid(app)
    with app.app_context():
        db.session.add(Job(kind="enrich", group_id=gid, status="pending"))
        db.session.commit()
        db.session.add(Job(kind="enrich", group_id=gid, status="running"))
        try:
            db.session.commit()
            assert False, "expected the partial-unique constraint to fire"
        except IntegrityError:
            db.session.rollback()


def test_create_job_forbidden_for_non_owner(app):
    from app.auth import create_token
    with app.app_context():
        g = Group(name="H", currency="usd")
        db.session.add(g)
        db.session.flush()
        member = User(name="M", email="m@x.com", password_hash="x",
                      is_owner=False, group_id=g.id)
        db.session.add(member)
        db.session.commit()
        tok = create_token(member)
    r = app.test_client().post("/api/v1/jobs/enrich",
                               headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403


def test_create_job_endpoint_and_progress(auth_client):
    r = auth_client.post("/api/v1/jobs/enrich")
    assert r.status_code == 202
    jid = r.get_json()["id"]
    poll = auth_client.get(f"/api/v1/jobs/{jid}")
    assert poll.status_code == 200 and poll.get_json()["status"] == "pending"


def test_create_job_unknown_kind_404(auth_client):
    assert auth_client.post("/api/v1/jobs/bogus").status_code == 404


def test_job_get_cross_group_404(auth_client, app):
    with app.app_context():
        other = Group(name="Other", currency="usd")
        db.session.add(other)
        db.session.flush()
        j = Job(kind="enrich", group_id=other.id)
        db.session.add(j)
        db.session.commit()
        jid = j.id
    assert auth_client.get(f"/api/v1/jobs/{jid}").status_code == 404
