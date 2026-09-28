"""Locations' tables: one detail table for every location type (a column
each type uses or leaves empty), and the rack mounts."""
from hyprvolt.core.models import Entity, EntityDetail
from hyprvolt.models import db, utcnow


class LocationDetail(EntityDetail, db.Model):
    __tablename__ = "location_details"

    code = db.Column(db.String(40))          # a short name: "HQ", "B2", "SRV"
    address = db.Column(db.Text)             # sites: the street lines
    city = db.Column(db.String(120))
    region = db.Column(db.String(120))       # a state, province or county
    postal_code = db.Column(db.String(20))
    country = db.Column(db.String(120))
    floor = db.Column(db.String(40))         # rooms
    height_u = db.Column(db.Integer)         # racks, and shelves that go in one
    numbering = db.Column(db.String(10))     # racks: "bottom" (U1 at the bottom) or "top"
    depth_mm = db.Column(db.Integer)         # racks


FACES = (("front", "Front"), ("rear", "Rear"), ("full", "Full depth"))


class RackMount(db.Model):
    """Something in a rack: a record, or just a label (a patch panel, a
    blanking plate) for what isn't worth a record of its own.
    ``position_u`` is the lowest unit it occupies."""
    __tablename__ = "rack_mounts"

    id = db.Column(db.Integer, primary_key=True)
    rack_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    label = db.Column(db.String(120), nullable=False, default="")
    position_u = db.Column(db.Integer, nullable=False)
    height_u = db.Column(db.Integer, nullable=False, default=1)
    face = db.Column(db.String(5), nullable=False, default="front")
    note = db.Column(db.String(200), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    rack = db.relationship(Entity, foreign_keys=[rack_id])
    entity = db.relationship(Entity, foreign_keys=[entity_id])

    @property
    def top_u(self) -> int:
        return self.position_u + self.height_u - 1

    @property
    def units_label(self) -> str:
        return f"U{self.position_u}" if self.height_u == 1 else f"U{self.position_u}–{self.top_u}"

    @property
    def name(self) -> str:
        return self.entity.name if self.entity is not None else self.label
