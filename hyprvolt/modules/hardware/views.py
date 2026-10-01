"""Hardware's sidebar filters (warranties about to end and already over; the
window is the reminder window, core/reminders.py, an admin setting), the
Wireless link section of a wireless bridge, and the Powers section of a
UPS."""
from datetime import date

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


# ———— A wireless bridge and the one at the other end ————

def is_bridge_gear(etype) -> bool:
    return etype.key == "network_device"


def _bridges(exclude=None) -> list[Entity]:
    ids = db.session.query(HardwareDetail.entity_id).filter(HardwareDetail.kind == "bridge")
    query = Entity.live().filter(Entity.type == "network_device", Entity.id.in_(ids))
    if exclude is not None:
        query = query.filter(Entity.id != exclude.id)
    return query.order_by(Entity.name).all()


def _links(bridge) -> list[Relationship]:
    """Its wireless links, either way: the link reads the same from both ends."""
    return (Relationship.query.filter(Relationship.kind == "wireless_link")
            .filter((Relationship.source_id == bridge.id) | (Relationship.target_id == bridge.id))
            .order_by(Relationship.id).all())


def other_end(bridge):
    for rel in _links(bridge):
        other = records.live(rel.target_id if rel.source_id == bridge.id else rel.source_id)
        if other is not None:
            return other
    return None


def bridge_choices(name) -> list[tuple[int, str]]:
    return [(e.id, e.name) for e in _bridges()]


def bridge_values(bridge) -> dict:
    other = other_end(bridge)
    return {"other": other.id if other else ""}


def bridge_form(etype, bridge) -> str:
    other = other_end(bridge) if bridge is not None else None
    return render_template("hardware/bridge_form.html", bridges=[(e.id, e.name) for e in _bridges(bridge)],
                           other_id=other.id if other else None)


def bridge_save(bridge, values, user) -> list[dict]:
    """The bridge at the other end. The link between two bridges is one,
    read the same from both; another chosen replaces this end's link."""
    if "other" not in values:
        return []
    wanted = None
    if values["other"] not in (None, "", 0, "0"):
        wanted = records.live(values["other"])
        if wanted is None or wanted.id not in {e.id for e in _bridges()}:
            raise Invalid("Choose a wireless bridge that exists for the other end.")
        if wanted.id == bridge.id:
            raise Invalid("A bridge links to another bridge, not to itself.")
    current = other_end(bridge)
    if (wanted and current and wanted.id == current.id) or (wanted is None and current is None):
        return []
    for rel in _links(bridge):
        other_id = rel.target_id if rel.source_id == bridge.id else rel.source_id
        if current is not None and other_id == current.id:
            relations.unlink(rel, user)
    if wanted is not None:
        relations.link("wireless_link", bridge, wanted, user=user)
    return [{"field": "bridge", "label": "Wireless link", "old": current.name if current else "",
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
