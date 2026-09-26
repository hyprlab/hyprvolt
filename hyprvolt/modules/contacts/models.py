"""Contacts' one detail table, shared by vendors, people and contracts."""
from hyprvolt.core.models import EntityDetail
from hyprvolt.models import db


class ContactDetail(EntityDetail, db.Model):
    __tablename__ = "contact_details"

    website = db.Column(db.String(500))          # vendors
    support_phone = db.Column(db.String(40))
    support_email = db.Column(db.String(200))
    support_url = db.Column(db.String(500))
    account_number = db.Column(db.String(120))
    address = db.Column(db.Text)
    organization = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="SET NULL"), index=True)  # people
    role = db.Column(db.String(120))
    email = db.Column(db.String(200))
    phone = db.Column(db.String(40))
    mobile = db.Column(db.String(40))
    vendor = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="SET NULL"), index=True)        # contracts
    kind = db.Column(db.String(20))
    number = db.Column(db.String(120))
    starts = db.Column(db.Date)
    ends = db.Column(db.Date, index=True)
    auto_renew = db.Column(db.Boolean)
    notice_days = db.Column(db.Integer)
    cost = db.Column(db.Float)
    billing = db.Column(db.String(10))
