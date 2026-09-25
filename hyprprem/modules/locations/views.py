"""Locations' pages and routes: the rack elevation and Contents tabs, the
rack position tab other records get, the dashboard widget, and the JSON
routes for placing things in racks."""
from flask import Blueprint, abort, jsonify, render_template, request

from hyprprem.core import present, records
from hyprprem.core.fields import Invalid
from hyprprem.core.models import Entity
from hyprprem.models import db
from hyprprem.permissions import role
from hyprprem.registry import current as registry

from . import racks
from .models import FACES, RackMount

bp = Blueprint("locations", __name__)

LOCATION_TYPES = ("site", "building", "room", "rack", "shelf")
#: Things that are places, not equipment: they hold what goes in a rack, and
#: don't go in one themselves. A shelf is both.
NOT_MOUNTABLE = ("site", "building", "room", "rack")


# ———— Tabs ————

def elevation_tab(rack: Entity) -> str:
    lay = racks.layout(rack)
    mounted = {m.entity_id for m in lay["mounts"] if m.entity_id}
    unplaced = [e for e in Entity.live().filter(Entity.location_id == rack.id).order_by(Entity.name)
                if e.id not in mounted]
    return render_template("locations/elevation.html", rack=rack, lay=lay, faces=FACES,
                           unplaced=present.views(unplaced))


def elevation_count(rack: Entity):
    lay = racks.layout(rack)
    return len(lay["problems"]) or None


def contents_tab(place: Entity) -> str:
    reg = registry()
    children = (Entity.live().filter(Entity.location_id == place.id, Entity.type.in_(reg.enabled_type_keys()))
                .order_by(Entity.type, Entity.name).all())
    groups = []
    for v in present.views(children):
        if not groups or groups[-1]["type"] != v.etype:
            groups.append({"type": v.etype, "items": []})
        groups[-1]["items"].append(v)
    # What can be added here: the location types that allow this one as
    # their parent. Other records name their place in their own form.
    addable = [t for t in reg.enabled_types() if t.location and t.located_in and place.type in t.located_in]
    return render_template("locations/contents.html", place=place, groups=groups, addable=addable,
                           total=len(children))


def contents_count(place: Entity):
    return Entity.live().filter(Entity.location_id == place.id).count() or None


def position_tab(entity: Entity) -> str:
    mount = RackMount.query.filter_by(entity_id=entity.id).first()
    return render_template("locations/position.html", entity=entity, mount=mount,
                           faces=dict(FACES), path=present.path_label(mount.rack.location_id) if mount else "")


def has_mount(entity: Entity) -> bool:
    return entity.type not in NOT_MOUNTABLE and \
        db.session.query(RackMount.id).filter_by(entity_id=entity.id).first() is not None


# ———— Dashboard ————

def rack_space_widget() -> str:
    rows = []
    for rack in Entity.live().filter(Entity.type == "rack").order_by(Entity.name).limit(12):
        lay = racks.layout(rack)
        rows.append({"rack": rack, "used": lay["used"], "height": lay["height"],
                     "percent": round(100 * lay["used"] / lay["height"]) if lay["height"] else 0,
                     "problems": len(lay["problems"]), "path": present.path_label(rack.location_id)})
    return render_template("locations/widget.html", rows=rows)


def conflicts_filter(query):
    return query.filter(Entity.id.in_(racks.conflicted_rack_ids()))


# ———— Placing things in racks ————

def _rack_or_404(rack_id: int) -> Entity:
    rack = records.live(rack_id)
    if rack is None or rack.type != "rack":
        abort(404, description="There is no such rack.")
    return rack


def _int(data, key, label, low=1, high=100):
    try:
        value = int(data.get(key))
    except (TypeError, ValueError):
        raise Invalid(f"{label} must be a whole number.") from None
    if not low <= value <= high:
        raise Invalid(f"{label} must be between {low} and {high}.")
    return value


def _mount_json(m: RackMount) -> dict:
    return {"id": m.id, "rack_id": m.rack_id, "entity_id": m.entity_id, "label": m.label, "name": m.name,
            "position_u": m.position_u, "height_u": m.height_u, "face": m.face, "note": m.note}


def _position_text(m: RackMount) -> str:
    return f"{m.rack.name}, {m.units_label}, {dict(FACES)[m.face].lower()}"


@bp.route("/racks/<int:rack_id>/elevation")
@role("viewer")
def elevation_json(rack_id):
    """The rack's units and what occupies them, for scripts."""
    rack = _rack_or_404(rack_id)
    lay = racks.layout(rack)
    return jsonify(rack={"id": rack.id, "name": rack.name, "height_u": lay["height"],
                         "numbering": lay["numbering"], "used_u": lay["used"]},
                   mounts=[_mount_json(m) for m in lay["mounts"]],
                   conflicts=[{"mount_id": m.id, "problems": p} for m, p in lay["problems"]])


@bp.route("/racks/<int:rack_id>/mounts", methods=["POST"])
@role("editor")
def mount_create(rack_id):
    """Place a record (``entity_id``) or a labeled item (``label``) at
    ``position_u`` (its lowest unit), ``height_u`` units tall, on the
    ``face`` front, rear or full. A record already in a rack moves. Overlaps
    are accepted and flagged, so a rack can be written down as it is."""
    rack = _rack_or_404(rack_id)
    data = request.get_json(silent=True) or {}
    try:
        height, _ = racks.height_of(rack.id)
        position = _int(data, "position_u", "The position", 1, height)
        size = _int(data, "height_u", "The height", 1, height)
        face = data.get("face") or "front"
        if face not in dict(FACES):
            raise Invalid("The face is front, rear or full depth.")
        entity = None
        if data.get("entity_id"):
            entity = records.live(data["entity_id"])
            if entity is None:
                raise Invalid("That record no longer exists.")
            if entity.type in NOT_MOUNTABLE:
                raise Invalid(f"A {registry().type(entity.type).label.lower()} doesn't go in a rack.")
        label = " ".join(str(data.get("label") or "").split())[:120]
        if entity is None and not label:
            raise Invalid("Choose a record, or name what goes there.")
        if entity is not None:
            old = RackMount.query.filter_by(entity_id=entity.id).first()
            if old is not None:
                db.session.delete(old)
            etype = registry().type(entity.type)
            if entity.location_id != rack.id and (etype.located_in is None or "rack" in etype.located_in):
                records.update(entity, {"location_id": rack.id})
        mount = RackMount(rack_id=rack.id, entity_id=entity.id if entity else None, label="" if entity else label,
                          position_u=position, height_u=size, face=face,
                          note=" ".join(str(data.get("note") or "").split())[:200])
        db.session.add(mount)
        db.session.flush()
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    change = [{"field": "rack", "label": "Rack position", "old": "", "new": _position_text(mount)}]
    records.audit(rack, "mounted", [{**change[0], "new": f"{mount.name}, {mount.units_label}"}])
    if entity is not None:
        records.audit(entity, "mounted", change)
    db.session.commit()
    lay = racks.layout(rack)
    problems = next((p for m, p in lay["problems"] if m.id == mount.id), [])
    return jsonify(ok=True, mount=_mount_json(mount), problems=problems)


@bp.route("/mounts/<int:mount_id>/delete", methods=["POST"])
@role("editor")
def mount_delete(mount_id):
    mount = db.get_or_404(RackMount, mount_id)
    snapshot = {k: v for k, v in _mount_json(mount).items() if k not in ("id", "rack_id", "name")}
    text = _position_text(mount)
    records.audit(mount.rack, "unmounted", [{"field": "rack", "label": "Rack position",
                                             "old": f"{mount.name}, {mount.units_label}", "new": ""}])
    if mount.entity is not None:
        records.audit(mount.entity, "unmounted", [{"field": "rack", "label": "Rack position",
                                                   "old": text, "new": ""}])
    rack_id = mount.rack_id
    db.session.delete(mount)
    db.session.commit()
    return jsonify(ok=True, undo={"url": f"/locations/racks/{rack_id}/mounts", "body": snapshot})

