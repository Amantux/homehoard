"""job.error is returned to clients, so a raw library exception must be redacted.

A DB driver echoes its DSN (password included) in connection errors; a handler
that lets one escape must not publish it through GET /api/v1/jobs/<id>.
"""
from app.extensions import db
from app.models import Job
from app.services import jobs


def _run(app, monkeypatch, gid, exc):
    def handler(job):
        raise exc

    monkeypatch.setitem(jobs._HANDLERS, "test_boom", handler)
    with app.app_context():
        job = jobs.enqueue("test_boom", gid)
        jobs.run_job(jobs.claim_one())
        stored = db.session.get(Job, job.id)
        return stored.id, stored.status, stored.error


def test_raw_exception_is_redacted_in_job_error(auth_client, app, monkeypatch, gid):
    jid, status, error = _run(
        app, monkeypatch, gid,
        Exception("connect postgresql://u:hunter2@db/x failed"))
    assert status == "error"
    assert "hunter2" not in error
    assert "[redacted]" in error  # the message is kept, only the secret goes

    body = auth_client.get(f"/api/v1/jobs/{jid}").get_json()
    assert body["status"] == "error"
    assert "hunter2" not in body["error"]


def test_job_error_message_arrives_verbatim(auth_client, app, monkeypatch, gid):
    _, status, error = _run(app, monkeypatch, gid, jobs.JobError("Nothing to import"))
    assert status == "error"
    assert error == "Nothing to import"
