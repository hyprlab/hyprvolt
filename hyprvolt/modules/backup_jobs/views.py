"""Backup jobs' runs, status, tabs, filters and widget.

A job's status follows its runs: its latest result, or Overdue once it has
gone half an interval past due without a success. A run is reported by the
backup script itself (``POST /backup_jobs/<id>/runs`` with an API token)
or recorded by hand in the Runs tab; the worker's hourly pass marks what has
fallen behind. Paused and retired jobs keep the status a person gave them.
"""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, g, jsonify, render_template, request
from flask_login import current_user
from sqlalchemy import func

from hyprvolt.core import present, records
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity, Relationship
from hyprvolt.models import db, utcnow
from hyprvolt.permissions import role

from .models import BackupJobDetail, BackupRun

bp = Blueprint("backup_jobs", __name__)

STATUSES = (("new", "Not run yet"), ("ok", "Succeeding"), ("warning", "Warnings"), ("failing", "Failing"),
            ("stale", "Overdue"), ("paused", "Paused"), ("retired", "Retired"))
RESULTS = (("success", "Succeeded"), ("warning", "Succeeded with warnings"), ("failed", "Failed"))
RESULT_LABELS = dict(RESULTS)
STATUS_FOR = {"success": "ok", "warning": "warning", "failed": "failing"}
#: Statuses a person set that runs don't change.
HELD = ("paused", "retired")
TROUBLE = ("failing", "stale")
DEFAULT_HOURS = 24
#: Overdue once this many intervals have passed without a success.
GRACE = 1.5
KEEP_RUNS = 200
SHOWN_RUNS = 20


def _detail(entity_id) -> BackupJobDetail | None:
    return db.session.get(BackupJobDetail, entity_id)


def overdue_after(d: BackupJobDetail | None) -> timedelta:
    return timedelta(hours=GRACE * ((d.interval_hours if d else None) or DEFAULT_HOURS))


def last_success(job_id) -> datetime | None:
    return (db.session.query(func.max(BackupRun.at))
            .filter(BackupRun.job_id == job_id, BackupRun.result != "failed").scalar())


def latest(job_id) -> BackupRun | None:
    return BackupRun.query.filter_by(job_id=job_id).order_by(BackupRun.at.desc(), BackupRun.id.desc()).first()


def health(job: Entity) -> str | None:
    """The status the runs call for, or None with no runs to go on."""
    run = latest(job.id)
    if run is None:
        return None
    if run.result == "failed":
        return "failing"
    success = last_success(job.id)
    if success is None or utcnow() - success > overdue_after(_detail(job.id)):
        return "stale"
    return STATUS_FOR[run.result]


def sync_status(job: Entity, user=None) -> bool:
    """Bring a job's status in line with its runs, through ``records`` so
    the history says so. Returns whether it changed."""
    if job.status in HELD:
        return False
    wanted = health(job)
    if wanted is None or wanted == job.status:
        return False
    records.update(job, {"status": wanted}, user)
    return True


def refresh() -> int:
    """The worker's job: mark what has fallen behind, and keep each job's
    newest runs only."""
    changed = 0
    for job in Entity.live().filter(Entity.type == "backup_job", Entity.status.notin_(HELD)):
        changed += sync_status(job)
    for job_id, n in (db.session.query(BackupRun.job_id, func.count(BackupRun.id))
                      .group_by(BackupRun.job_id).having(func.count(BackupRun.id) > KEEP_RUNS)):
        keep = (db.session.query(BackupRun.id).filter_by(job_id=job_id)
                .order_by(BackupRun.at.desc(), BackupRun.id.desc()).limit(KEEP_RUNS))
        changed += (BackupRun.query.filter(BackupRun.job_id == job_id, BackupRun.id.notin_(keep))
                    .delete(synchronize_session=False))
    return changed


# ———— Filters and the widget ————

def trouble(query):
    return query.filter(Entity.type == "backup_job", Entity.status.in_(TROUBLE))


def never_run(query):
    return query.filter(Entity.type == "backup_job", Entity.status == "new")


def _last_successes(ids) -> dict[int, datetime]:
    if not ids:
        return {}
    return dict(db.session.query(BackupRun.job_id, func.max(BackupRun.at))
                .filter(BackupRun.job_id.in_(ids), BackupRun.result != "failed").group_by(BackupRun.job_id))


def widget() -> str:
    jobs = (Entity.live().filter(Entity.type == "backup_job", Entity.archived.is_(False),
                                 Entity.status != "retired").order_by(Entity.name).all())
    counts = {key: 0 for key, _ in STATUSES}
    for job in jobs:
        counts[job.status] = counts.get(job.status, 0) + 1
    problems = [j for j in jobs if j.status in TROUBLE]
    problems.sort(key=lambda j: (j.status != "failing", j.name.lower()))
    return render_template("backup_jobs/widget.html", total=len(jobs), counts=counts, labels=dict(STATUSES),
                           rows=present.views(problems[:8]), more=max(len(problems) - 8, 0),
                           success=_last_successes([j.id for j in problems[:8]]))


# ———— Tabs ————

def runs_tab(job: Entity) -> str:
    d = _detail(job.id)
    runs = (BackupRun.query.filter_by(job_id=job.id).order_by(BackupRun.at.desc(), BackupRun.id.desc())
            .limit(SHOWN_RUNS).all())
    total = BackupRun.query.filter_by(job_id=job.id).count()
    return render_template("backup_jobs/runs.html", job=job, d=d, runs=runs, total=total, results=RESULTS,
                           labels=RESULT_LABELS, success=last_success(job.id),
                           grace_hours=round(overdue_after(d).total_seconds() / 3600),
                           command=report_command(job))


def report_command(job: Entity) -> str:
    url = request.host_url.rstrip("/") + f"/backup_jobs/{job.id}/runs"
    return (f'curl -fsS -X POST {url} -H "Authorization: Bearer $HYPRVOLT_TOKEN" '
            """-H "Content-Type: application/json" -d '{"result": "success"}'""")


def _jobs_for(entity: Entity) -> list[Entity]:
    ids = [r.source_id for r in Relationship.query.filter_by(kind="backs_up", target_id=entity.id)]
    if not ids:
        return []
    return Entity.live().filter(Entity.id.in_(ids), Entity.type == "backup_job").order_by(Entity.name).all()


def backed_up(entity: Entity) -> bool:
    return entity.type != "backup_job" and bool(_jobs_for(entity))


def backups_tab(entity: Entity) -> str:
    jobs = _jobs_for(entity)
    return render_template("backup_jobs/backups.html", entity=entity, rows=present.views(jobs),
                           success=_last_successes([j.id for j in jobs]), labels=dict(STATUSES))


def backups_count(entity: Entity):
    return len(_jobs_for(entity)) or None


# ———— Runs ————

def _job(entity_id) -> Entity:
    job = records.live(entity_id)
    if job is None or job.type != "backup_job":
        abort(404, description="There is no such backup job.")
    return job


def _when(raw) -> datetime:
    """When a run finished: now, or an ISO date and time (UTC unless it
    says otherwise), not in the future."""
    if raw in (None, ""):
        return utcnow()
    try:
        at = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError:
        raise Invalid("The time must be a date and time, such as 2026-09-27T02:14:00Z.") from None
    if at.tzinfo is not None:
        at = at.astimezone(timezone.utc).replace(tzinfo=None)
    if at > utcnow() + timedelta(minutes=5):
        raise Invalid("A run can't have finished in the future.")
    return at


def _who() -> str:
    token = g.get("api_token")
    return (token.name if token is not None else current_user.display_name)[:120]


def run_json(r: BackupRun) -> dict:
    return {"id": r.id, "job_id": r.job_id, "at": r.at.isoformat() + "Z", "result": r.result, "note": r.note,
            "by": r.by_name}


def add_run(job: Entity, data: dict, by_name: str = "", user=None) -> BackupRun:
    """``result`` (success, warning or failed), with ``note`` and ``at``."""
    result = str(data.get("result") or "").strip().lower()
    if result not in RESULT_LABELS:
        raise Invalid("The result must be success, warning or failed.")
    note = " ".join(str(data.get("note") or "").split())
    if len(note) > 300:
        raise Invalid("A note is limited to 300 characters.")
    run = BackupRun(job_id=job.id, at=_when(data.get("at")), result=result, note=note, by_name=by_name)
    db.session.add(run)
    db.session.flush()
    sync_status(job, user)
    return run


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.route("/<int:entity_id>/runs", methods=["POST"])
@role("editor")
def run_create(entity_id):
    """Report a run. Also Undo for a removed one."""
    job = _job(entity_id)
    try:
        run = add_run(job, _body(), _who())
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    db.session.commit()
    return jsonify(ok=True, run=run_json(run), status=job.status)


@bp.route("/<int:entity_id>/runs")
@role("viewer")
def run_list(entity_id):
    job = _job(entity_id)
    runs = BackupRun.query.filter_by(job_id=job.id).order_by(BackupRun.at.desc(), BackupRun.id.desc()).all()
    return jsonify(runs=[run_json(r) for r in runs], status=job.status)


@bp.route("/runs/<int:run_id>/delete", methods=["POST"])
@role("editor")
def run_delete(run_id):
    run = db.session.get(BackupRun, run_id)
    job = records.live(run.job_id) if run else None
    if run is None or job is None:
        abort(404, description="There is no such run.")
    body = {"result": run.result, "note": run.note, "at": run.at.isoformat() + "Z"}
    db.session.delete(run)
    db.session.flush()
    sync_status(job)
    db.session.commit()
    return jsonify(ok=True, undo={"url": f"/backup_jobs/{job.id}/runs", "body": body})
