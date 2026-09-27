"""Backup jobs' tables: the job's detail, and its runs.

Runs come nightly, so they are rows of this module's own, not fields: a
record's history would drown in them. The job's status follows its runs
(``views.sync_status``) and that change alone reaches the history.
"""
from hyprvolt.core.models import Entity, EntityDetail
from hyprvolt.models import db, utcnow


class BackupJobDetail(EntityDetail, db.Model):
    __tablename__ = "backup_job_details"

    tool = db.Column(db.String(20))
    schedule = db.Column(db.String(200))
    interval_hours = db.Column(db.Integer)
    retention = db.Column(db.String(200))
    offsite = db.Column(db.String(200))
    encrypted = db.Column(db.Boolean)
    restore_tested = db.Column(db.Date)
    restore_due = db.Column(db.Date, index=True)


class BackupRun(db.Model):
    """One run of a job, as a script reported it or a person recorded it."""
    __tablename__ = "backup_runs"
    __table_args__ = (db.Index("ix_backup_runs_job_at", "job_id", "at"),)

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    at = db.Column(db.DateTime, nullable=False, default=utcnow)
    result = db.Column(db.String(10), nullable=False)
    note = db.Column(db.String(300), nullable=False, default="")
    by_name = db.Column(db.String(120), nullable=False, default="")

    job = db.relationship(Entity)
