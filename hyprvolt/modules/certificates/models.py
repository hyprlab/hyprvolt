"""Certificates' detail table: what the certificate says, where to check
it, and how the last check went. What it secures is a link, not a column."""
from hyprvolt.core.models import EntityDetail
from hyprvolt.models import db


class CertificateDetail(EntityDetail, db.Model):
    __tablename__ = "certificate_details"

    names = db.Column(db.Text)
    issuer = db.Column(db.String(200))
    issued = db.Column(db.Date)
    expires = db.Column(db.Date, index=True)
    auto_renew = db.Column(db.Boolean)
    endpoint = db.Column(db.String(300))
    key_type = db.Column(db.String(40))
    serial = db.Column(db.String(100))
    fingerprint = db.Column(db.String(100))
    # The live check's own state, not fields: written by the check alone.
    checked_at = db.Column(db.DateTime)
    check_error = db.Column(db.String(300))
