"""Background job worker — a daemon poller thread started per process.

Each gunicorn worker process starts one poller. They share the ``jobs`` table and
claim work with an atomic compare-and-swap (see ``services.jobs.claim_one``), so
running two pollers is safe: at most one runs any given job. A poller that dies
(worker restart) leaves a stale ``running`` row that ``reap_stale`` requeues.

Disabled under tests (``WORKER_ENABLED=False``) — tests drive the job functions
directly, deterministically, without a live thread.
"""
from __future__ import annotations

import logging
import os
import threading
import time

_LOGGER = logging.getLogger("homehoard.worker")

IDLE_POLL_S = 2.0     # sleep when there's nothing to do
_started_pid = None
_lock = threading.Lock()


def start_worker(app) -> None:
    """Start the poller once for THIS process (idempotent).

    Keyed on the PID, not a plain bool: threads don't survive fork(), so if the app
    were ever created before a gunicorn fork (``--preload``) a bool would make the
    forked workers think a poller is running when it isn't. The PID guard restarts
    the poller in each real worker process.
    """
    global _started_pid
    if not app.config.get("WORKER_ENABLED", True):
        return
    with _lock:
        if _started_pid == os.getpid():
            return
        _started_pid = os.getpid()
    threading.Thread(target=_loop, args=(app,), name="hh-job-worker",
                     daemon=True).start()
    _LOGGER.info("job worker started")


def _loop(app) -> None:
    from .services.jobs import claim_one, reap_stale, run_job
    while True:
        worked = False
        try:
            with app.app_context():
                reap_stale()
                job = claim_one()
                if job is not None:
                    run_job(job)
                    worked = True
        except Exception:  # noqa: BLE001 - the poller must never die on one bad job
            _LOGGER.exception("worker loop error")
        if not worked:
            time.sleep(IDLE_POLL_S)
