"""Periodic background work.

``run_once`` is called by the thread that ``__init__._start_worker`` starts,
every ``worker_minutes`` (an admin setting whose default is the WORKER_MINUTES
environment variable). It runs in the web process, so keep it short and let it
fail loudly: the caller logs the traceback and tries again next cycle.

Replace the body with whatever the app does on a schedule: fetch, prune, send,
reconcile. If the work grows past a few seconds or needs more than one process,
move it to its own container rather than growing this thread.
"""
import logging
import time

from flask import Flask

from .models import db

log = logging.getLogger(__name__)


def run_once(app: Flask) -> None:
    with app.app_context():
        started = time.monotonic()
        try:
            touched = _work()
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.remove()
        log.info("background pass: %d rows in %.2fs", touched, time.monotonic() - started)


def _work() -> int:
    """The actual work. Returns the number of rows it changed, for the log."""
    return 0
