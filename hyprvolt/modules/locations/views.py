"""Locations' pages and routes: the rack elevation and Contents tabs, the
rack position tab and form section other records get, the dashboard widget,
and the JSON routes for placing things in racks."""
from flask import Blueprint, abort, jsonify, render_template, request

from hyprvolt.core import present, records
from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import Entity
from hyprvolt.models import db
from hyprvolt.permissions import role
from hyprvolt.registry import current as registry

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


def place(entity: Entity, rack: Entity, position: int, size: int, face: str, note: str = "",
          user=None) -> tuple[RackMount | None, list[dict]]:
    """Put a record in a rack, replacing where it was, and move it into the
    rack where its type may be there. Returns the mount (None if nothing
    changed) and the changes for the record's history; the rack's own
    history is written here."""
    if entity.type in NOT_MOUNTABLE:
        raise Invalid(f"A {registry().type(entity.type).text()} doesn't go in a rack.")
    old = RackMount.query.filter_by(entity_id=entity.id).first()
    if old is not None and (old.rack_id, old.position_u, old.height_u, old.face) == (rack.id, position, size, face):
        return None, []
    before = _position_text(old) if old is not None else ""
    if old is not None:
        db.session.delete(old)
    mount = RackMount(rack_id=rack.id, entity_id=entity.id, label="", position_u=position, height_u=size,
                      face=face, note=note or (old.note if old is not None else ""))
    db.session.add(mount)
    db.session.flush()
    changes = [{"field": "rack", "label": "Rack position", "old": before, "new": _position_text(mount)}]
    etype = registry().type(entity.type)
    if entity.location_id != rack.id and (etype.located_in is None or "rack" in etype.located_in):
        changes += records.move(entity, rack, user)
    records.audit(rack, "mounted", [{**changes[0], "old": "", "new": f"{mount.name}, {mount.units_label}"}], user)
    return mount, changes


def unplace(entity: Entity, user=None) -> list[dict]:
    """Take a record out of its rack; its location stays the rack."""
    mount = RackMount.query.filter_by(entity_id=entity.id).first()
    if mount is None:
        return []
    text = _position_text(mount)
    records.audit(mount.rack, "unmounted", [{"field": "rack", "label": "Rack position",
                                             "old": f"{mount.name}, {mount.units_label}", "new": ""}], user)
    db.session.delete(mount)
    return [{"field": "rack", "label": "Rack position", "old": text, "new": ""}]


def _face(data) -> str:
    face = data.get("face") or "front"
    if face not in dict(FACES):
        raise Invalid("The face is front, rear or full depth.")
    return face


# ———— The rack position in a record's form ————

def is_rackmount(etype) -> bool:
    return "rackmount" in etype.traits


def before_retype(entity: Entity, new) -> None:
    """A rack stops being one only when it is empty, and a shelf in a rack
    becomes something that can't be mounted only once it is out, so no
    mount is left pointing at a record that can't have it."""
    if entity.type == "rack" and new.key != "rack":
        n = RackMount.query.filter_by(rack_id=entity.id).count()
        if n:
            raise Invalid("1 thing is mounted in it. Take it out of the rack first." if n == 1 else
                          f"{n} things are mounted in it. Take them out of the rack first.")
    if not is_rackmount(new) and RackMount.query.filter_by(entity_id=entity.id).first() is not None:
        raise Invalid(f"It is mounted in a rack, and a {new.text()} can't be. Take it out of the rack first.")


def rack_form(etype, entity) -> str:
    mount = RackMount.query.filter_by(entity_id=entity.id).first() if entity is not None else None
    rack_id = mount.rack_id if mount else None
    if rack_id is None and entity is None:
        # A new record made from a rack's Contents or Elevation starts there.
        start = records.live(request.args.get("location_id", type=int))
        rack_id = start.id if start is not None and start.type == "rack" else None
    choices = []
    for rack in Entity.live().filter(Entity.type == "rack"):
        path = present.path_label(rack.location_id)
        choices.append((rack.id, f"{path} › {rack.name}" if path else rack.name))
    choices.sort(key=lambda c: c[1].lower())
    return render_template("locations/rack_form.html", mount=mount, rack_id=rack_id, choices=choices, faces=FACES)


def rack_save(entity, values, user) -> list[dict]:
    if values.get("rack_id") in (None, "", 0, "0"):
        return unplace(entity, user)
    rack = records.live(values["rack_id"])
    if rack is None or rack.type != "rack":
        raise Invalid("Choose a rack that exists.")
    height, _ = racks.height_of(rack.id)
    if str(values.get("position_u") or "").strip() == "":
        raise Invalid("Choose the unit it starts at in the rack.")
    position = _int(values, "position_u", "The lowest unit", 1, height)
    size = _int({"height_u": values.get("height_u") or 1}, "height_u", "The height", 1, height)
    return place(entity, rack, position, size, _face(values), user=user)[1]


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
        face = _face(data)
        note = " ".join(str(data.get("note") or "").split())[:200]
        entity = None
        if data.get("entity_id"):
            entity = records.live(data["entity_id"])
            if entity is None:
                raise Invalid("That record no longer exists.")
        label = " ".join(str(data.get("label") or "").split())[:120]
        if entity is None and not label:
            raise Invalid("Choose a record, or name what goes there.")
        if entity is not None:
            mount, changes = place(entity, rack, position, size, face, note)
            if mount is None:
                mount = RackMount.query.filter_by(entity_id=entity.id).first()
            else:
                records.audit(entity, "mounted", changes)
        else:
            mount = RackMount(rack_id=rack.id, label=label, position_u=position, height_u=size, face=face, note=note)
            db.session.add(mount)
            db.session.flush()
            records.audit(rack, "mounted", [{"field": "rack", "label": "Rack position", "old": "",
                                             "new": f"{mount.name}, {mount.units_label}"}])
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    db.session.commit()
    lay = racks.layout(rack)
    problems = next((p for m, p in lay["problems"] if m.id == mount.id), [])
    return jsonify(ok=True, mount=_mount_json(mount), problems=problems)


@bp.route("/mounts/<int:mount_id>/delete", methods=["POST"])
@role("editor")
def mount_delete(mount_id):
    mount = db.get_or_404(RackMount, mount_id)
    _rack_or_404(mount.rack_id)
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

