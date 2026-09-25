"""Hardware's one detail table, shared by every hardware type: each type
uses the columns it needs and leaves the rest empty."""
from hyprvolt.core.models import EntityDetail
from hyprvolt.models import db


class HardwareDetail(EntityDetail, db.Model):
    __tablename__ = "hardware_details"

    manufacturer = db.Column(db.String(120))
    model = db.Column(db.String(120))
    serial = db.Column(db.String(120), index=True)
    asset_tag = db.Column(db.String(60), index=True)

    purchase_date = db.Column(db.Date)
    price = db.Column(db.Float)
    vendor = db.Column(db.String(120))
    warranty_until = db.Column(db.Date, index=True)

    kind = db.Column(db.String(30))            # network gear: switch, router, …; servers: form factor
    category = db.Column(db.String(80))        # peripherals: "Monitor", "KVM switch"
    cpu = db.Column(db.String(200))
    cpu_cores = db.Column(db.Integer)
    ram_gb = db.Column(db.Integer)
    storage = db.Column(db.Text)               # disks, one per line
    nics = db.Column(db.Text)                  # network ports, one per line
    ports = db.Column(db.Integer)              # network gear: how many ports
    managed = db.Column(db.Boolean)
    wifi = db.Column(db.String(60))
    drive_bays = db.Column(db.Integer)
    capacity_tb = db.Column(db.Float)
    capacity_va = db.Column(db.Integer)
    runtime_min = db.Column(db.Integer)
    battery_due = db.Column(db.Date)
    power_w = db.Column(db.Integer)
    os = db.Column(db.String(120))
    assigned_to = db.Column(db.String(120))
