"""Maintenance's detail table, for windows and changes alike. What each
affects is a link ("affects"), not a column."""
from hyprvolt.core.models import EntityDetail
from hyprvolt.models import db


class MaintenanceDetail(EntityDetail, db.Model):
    __tablename__ = "maintenance_details"

    # Maintenance windows
    starts = db.Column(db.DateTime, index=True)
    ends = db.Column(db.DateTime)
    impact = db.Column(db.String(10))
    owner = db.Column(db.String(200))
    announced = db.Column(db.Boolean)
    plan = db.Column(db.Text)
    # Changes
    at = db.Column(db.DateTime, index=True)
    kind = db.Column(db.String(20))
    done_by = db.Column(db.String(200))
    window = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="SET NULL"), index=True)
    details = db.Column(db.Text)
