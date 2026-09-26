"""Periodic background work.

``run_once`` is called by the thread that ``__init__._start_worker`` starts,
every ``worker_minutes`` (an admin setting whose default is the WORKER_MINUTES
environment variable). Each pass runs the jobs that are due: the core's own
(purging deleted records) and every turned-on module's ``jobs``, each at most
as often as its ``minutes`` asks. It runs in the web process, so jobs stay
short; one that fails is logged and tried again on the next pass, and does
not stop the others.
"""
import logging
import time
from datetime import datetime, timedelta

from flask import Flask

from .manifest import Job
from .models import db, get_setting, set_setting, utcnow

log = logging.getLogger(__name__)


def _purge() -> int:
    from .core.records import purge
    return purge()


def _reminders() -> int:
    from .core.reminders import refresh_all
    return refresh_all()


CORE_JOBS = (Job("purge", _purge, minutes=60), Job("reminders", _reminders, minutes=60))


def jobs():
    """Every job with its full key: ``core.purge``, ``<module>.<key>``."""
    from .registry import current
    out = [("core." + j.key, j) for j in CORE_JOBS]
    for m in current().enabled_modules():
        out += [(f"{m.id}.{j.key}", j) for j in m.jobs]
    return out


def run_once(app: Flask, force: bool = False) -> dict:
    """Run the due jobs; returns {job key: rows touched} for those that ran."""
    ran = {}
    with app.app_context():
        started = time.monotonic()
        try:
            for key, job in jobs():
                last = get_setting(f"job:{key}:last")
                if not force and last and utcnow() - datetime.fromisoformat(last) < timedelta(minutes=job.minutes):
                    continue
                try:
                    ran[key] = job.run() or 0
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    log.exception("job %s failed", key)
                    continue
                set_setting(f"job:{key}:last", utcnow().isoformat())
        finally:
            db.session.remove()
        log.info("background pass: %s in %.2fs", ran or "nothing due", time.monotonic() - started)
    return ran
