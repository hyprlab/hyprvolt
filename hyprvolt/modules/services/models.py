"""Services' detail table. What a service runs on and its domain are fields
kept as links, so the dependency view follows them; ``host`` holds only
"cloud", for a service that runs on no record of yours."""
from hyprvolt.core.models import EntityDetail
from hyprvolt.models import db


class ServiceDetail(EntityDetail, db.Model):
    __tablename__ = "service_details"

    kind = db.Column(db.String(20))
    host = db.Column(db.String(20))
    url = db.Column(db.String(500))
    ports = db.Column(db.String(200))
    users = db.Column(db.String(200))
    criticality = db.Column(db.String(10), index=True)
