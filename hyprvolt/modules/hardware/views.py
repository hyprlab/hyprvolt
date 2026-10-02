"""Hardware's sidebar filters (warranties about to end and already over; the
window is the reminder window, core/reminders.py, an admin setting), the
Wireless link and Coax link sections of a wireless bridge and a MoCA
adapter, and the Powers section of a UPS."""
from datetime import date
from functools import partial

from flask import render_template

from hyprvolt.core import records, relations, reminders
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity, Relationship
from hyprvolt.models import db
from hyprvolt.registry import current as registry

from .models import HardwareDetail

#: Statuses that no longer need a warranty, or a reminder.
GONE = ("retired", "disposed")


def warranty_soon(query):
    return reminders.ending_within(query.filter(Entity.status.notin_(GONE)), HardwareDetail,
                                   HardwareDetail.warranty_until)


def warranty_over(query):
    ids = db.session.query(HardwareDetail.entity_id).filter(HardwareDetail.warranty_until < date.today())
    return query.filter(Entity.status.notin_(GONE), Entity.id.in_(ids))


# ———— Gear that comes in pairs: a wireless bridge, a MoCA adapter ————

#: A kind of network gear with one other end, and the link between the two
#: (read the same from both): {kind: (relation, what it is, its section's
#: label, the hint beside the choice)}.
PAIRS = {
    "bridge": ("wireless_link", "wireless bridge", "Wireless link",
               "The bridge this one links to over the air, often in another building. Each end has its own "
               "location and IP address."),
    "moca": ("coax_link", "MoCA adapter", "Coax link",
             "The adapter at the other end of the coax. The two work like one cable: from what is plugged "
             "into this one to what is plugged into that one."),
}


def is_bridge_gear(etype) -> bool:
    return etype.key == "network_device"


def _paired(kind, exclude=None) -> list[Entity]:
    ids = db.session.query(HardwareDetail.entity_id).filter(HardwareDetail.kind == kind)
    query = Entity.live().filter(Entity.type == "network_device", Entity.id.in_(ids))
    if exclude is not None:
        query = query.filter(Entity.id != exclude.id)
    return query.order_by(Entity.name).all()


def _links(entity, relation) -> list[Relationship]:
    """Its links of the pair's kind, either way: one reads the same from both ends."""
    return (Relationship.query.filter(Relationship.kind == relation)
            .filter((Relationship.source_id == entity.id) | (Relationship.target_id == entity.id))
            .order_by(Relationship.id).all())


def other_end(entity, relation="wireless_link"):
    """The bridge, or MoCA adapter, at the other end of this one."""
    for rel in _links(entity, relation):
        other = records.live(rel.target_id if rel.source_id == entity.id else rel.source_id)
        if other is not None:
            return other
    return None


def pair_choices(kind, name) -> list[tuple[int, str]]:
    return [(e.id, e.name) for e in _paired(kind)]


def pair_values(kind, entity) -> dict:
    other = other_end(entity, PAIRS[kind][0])
    return {"other": other.id if other else "", "at": (other.location_id or "") if other else ""}


def far_moca(entity) -> list[Entity]:
    """A MoCA adapter's far end (the later made of the two), shown in the
    site setup guide in its pair's row and deleted with it."""
    if entity.type != "network_device":
        return []
    detail = db.session.get(HardwareDetail, entity.id)
    if detail is None or detail.kind != "moca":
        return []
    other = other_end(entity, "coax_link")
    return [other] if other is not None and other.id > entity.id else []


def _far_end_at(entity, at, user) -> list[dict]:
    """The pair's far end put at a place: moved there, or, with none yet,
    made there (named for this one and the place, with its model) and
    linked over the coax."""
    place = records.live(at)
    if place is None or registry().type(place.type) not in registry().location_types():
        raise Invalid("Choose a place for the other end.")
    other = other_end(entity, "coax_link")
    if other is not None:
        if other.location_id == place.id:
            return []
        records.update(other, {"location_id": place.id}, user)
        return [{"field": "moca_at", "label": "Other end at", "old": "", "new": place.name}]
    detail = db.session.get(HardwareDetail, entity.id)
    made = records.create("network_device", {
        "name": f"{entity.name} ({place.name})", "location_id": place.id, "status": entity.status,
        "f.kind": "moca", "f.manufacturer": detail.manufacturer if detail else "",
        "f.model": detail.model if detail else ""}, user)
    relations.link("coax_link", entity, made, user=user)
    return [{"field": "moca_at", "label": "Other end at", "old": "", "new": f"{made.name}, {place.name}"}]


def pair_form(kind, etype, entity) -> str:
    relation, what, _, hint = PAIRS[kind]
    other = other_end(entity, relation) if entity is not None else None
    return render_template("hardware/pair_form.html", name=f"s.{kind}.other",
                           choices=[(e.id, e.name) for e in _paired(kind, entity)],
                           other_id=other.id if other else None, hint=hint,
                           empty=f"Add the {what} at the other end, then link them here.")


def pair_save(kind, entity, values, user) -> list[dict]:
    """The one at the other end. The link between the two is one, read the
    same from both; another chosen replaces this end's link."""
    if kind == "moca" and values.get("at") not in (None, "", 0, "0"):
        return _far_end_at(entity, values["at"], user)
    if "other" not in values:
        return []
    relation, what, label, _ = PAIRS[kind]
    wanted = None
    if values["other"] not in (None, "", 0, "0"):
        wanted = records.live(values["other"])
        if wanted is None or wanted.id not in {e.id for e in _paired(kind)}:
            raise Invalid(f"Choose a {what} that exists for the other end.")
        if wanted.id == entity.id:
            raise Invalid(f"A {what} links to another, not to itself.")
    current = other_end(entity, relation)
    if (wanted and current and wanted.id == current.id) or (wanted is None and current is None):
        return []
    for rel in _links(entity, relation):
        other_id = rel.target_id if rel.source_id == entity.id else rel.source_id
        if current is not None and other_id == current.id:
            relations.unlink(rel, user)
    if wanted is not None:
        relations.link(relation, entity, wanted, user=user)
    return [{"field": kind, "label": label, "old": current.name if current else "",
             "new": wanted.name if wanted else ""}]


# ———— What a UPS powers ————

def is_ups(etype) -> bool:
    return etype.key == "ups"


def _powerable() -> list[Entity]:
    """Every piece of hardware a UPS can power: all but the UPSes."""
    from . import KINDS
    return (Entity.live().filter(Entity.type.in_([k for k in KINDS if k != "ups"]))
            .order_by(Entity.name).all())


def powers_choices(name) -> list[dict]:
    """The hardware to tick, under each type's name: Servers, then Network gear."""
    from . import KINDS
    reg = registry()
    groups = {}
    for e in _powerable():
        groups.setdefault(e.type, []).append((e.id, e.name))
    return [{"label": reg.type(k).plural, "options": groups[k]} for k in KINDS if k in groups and reg.type(k)]


def _powered(ups) -> str:
    return ",".join(str(e.id) for e in relations.linked("powered_by", ups, "target")) if ups is not None else ""


def powers_values(ups) -> dict:
    return {"list": _powered(ups)}


def powers_form(etype, ups) -> str:
    return render_template("sheet/multi_section.html", name="s.powers.list", label="Powers",
                           choices=powers_choices("list"), value=_powered(ups),
                           hint="The equipment plugged into it. Each is then powered by it, and goes down with it.",
                           empty="No other hardware recorded yet.")


def powers_save(ups, values, user) -> list[dict]:
    """The equipment a UPS powers, ticked: each is powered by it."""
    if "list" not in values:
        return []
    changed = relations.set_linked("powered_by", ups, "target", values["list"], _powerable(), "hardware", user)
    return [{"field": "powers", "label": "Powers", **changed}] if changed else []


bridge_choices, bridge_values, bridge_form, bridge_save = (partial(f, "bridge") for f in (
    pair_choices, pair_values, pair_form, pair_save))
moca_choices, moca_values, moca_form, moca_save = (partial(f, "moca") for f in (
    pair_choices, pair_values, pair_form, pair_save))
