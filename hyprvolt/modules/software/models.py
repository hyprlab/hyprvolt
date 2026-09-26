"""Software's tables: one detail table for titles and licenses, and the
installations, which come by the dozen and so are rows, not records."""
from hyprvolt.core.models import Entity, EntityDetail
from hyprvolt.models import db, utcnow


class SoftwareDetail(EntityDetail, db.Model):
    __tablename__ = "software_details"

    category = db.Column(db.String(20))          # titles
    current_version = db.Column(db.String(60))
    license_model = db.Column(db.String(20))
    website = db.Column(db.String(500))
    software = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="SET NULL"), index=True)  # licenses
    kind = db.Column(db.String(20))
    seats = db.Column(db.Integer)
    extra_seats = db.Column(db.Integer)
    purchased = db.Column(db.Date)
    renews = db.Column(db.Date, index=True)
    cost = db.Column(db.Float)


class Installation(db.Model):
    """A title installed on a host, at a version, maybe on a license seat."""
    __tablename__ = "software_installations"
    __table_args__ = (db.UniqueConstraint("software_id", "host_id"),)

    id = db.Column(db.Integer, primary_key=True)
    software_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    host_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    version = db.Column(db.String(60), nullable=False, default="")
    license_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="SET NULL"), index=True)
    installed = db.Column(db.Date)
    note = db.Column(db.String(200), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    software = db.relationship(Entity, foreign_keys=[software_id])
    host = db.relationship(Entity, foreign_keys=[host_id])
    license = db.relationship(Entity, foreign_keys=[license_id])
