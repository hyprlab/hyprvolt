"""The JSON API for entities, tags and custom fields.

The web interface and scripts use the same routes. Reads need a viewer,
writes an editor, custom field definitions an admin; failures answer
``{"error": "..."}`` written for a person, like every JSON route in the app.
A response to something that can be taken back carries ``undo``: the URL
and body that take it back, which the interface offers as Undo.
"""
import json
import re

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user
from sqlalchemy import func

from ..manifest import CUSTOM_KINDS
from ..models import db
from ..permissions import role
from ..registry import current as registry
from . import fields as F
from . import records
from .fields import Invalid
from .models import AuditLog, CustomField, CustomValue, Entity, Tag, entity_tags

bp = Blueprint("api", __name__, url_prefix="/api")


def like(query: str) -> str:
    """A LIKE pattern that matches ``query`` literally."""
    return "%" + query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def entity_or_404(entity_id: int, deleted_ok: bool = False) -> Entity:
    entity = db.session.get(Entity, entity_id)
    etype = registry().type(entity.type) if entity else None
    if entity is None or etype is None or not registry().is_enabled(etype.module):
        abort(404, description="There is no such record.")
    if entity.deleted_at is not None and not deleted_ok:
        abort(404, description="That record was deleted.")
    return entity


def to_json(entity: Entity, full: bool = True) -> dict:
    etype = registry().type(entity.type)
    out = {
        "id": entity.id,
        "module": entity.module,
        "type": entity.type,
        "type_label": etype.label if etype else entity.type,
        "name": entity.name,
        "slug": entity.slug,
        "status": entity.status,
        "status_label": records.status_label(entity),
        "location": {"id": entity.location.id, "name": entity.location.name}
        if entity.location and entity.location.deleted_at is None else None,
        "tags": entity.tag_names,
        "archived": entity.archived,
        "deleted": entity.deleted_at is not None,
        "updated_at": entity.updated_at.isoformat() + "Z",
        "url": f"/e/{entity.id}",
    }
    if full:
        out["notes"] = entity.notes
        out["created_at"] = entity.created_at.isoformat() + "Z"
        out["path"] = [{"id": c.id, "name": c.name} for c in records.crumbs(entity)]
        detail = records.detail_of(entity)
        out["fields"] = {f.key: F.to_json(f, getattr(detail, f.key, None) if detail else None)
                         for f in (etype.fields if etype else ())}
        values = records.custom_values(entity)
        out["custom"] = {}
        for cf in records.custom_fields(entity.type):
            f = F.custom_field(cf)
            out["custom"][cf.key] = F.to_json(f, F.from_text(f, values.get(cf.id, "")))
    return out


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description="Send the record as a JSON object.")
    return data


def _fail(err: Invalid):
    db.session.rollback()
    return jsonify(error=str(err)), 400


# ———— Entities ————

@bp.route("/entities")
@role("viewer")
def entity_list():
    """Live entities of turned-on modules, filtered by ``type``, ``module``,
    ``tag``, ``location`` and ``q``, newest change first. ``limit`` up to 500,
    ``offset`` to page."""
    reg = registry()
    query = Entity.live().filter(Entity.type.in_(reg.enabled_type_keys()))
    if request.args.get("type"):
        query = query.filter(Entity.type.in_(request.args["type"].split(",")))
    if request.args.get("module"):
        query = query.filter(Entity.module == request.args["module"])
    if request.args.get("archived") not in ("1", "all"):
        query = query.filter(Entity.archived.is_(False))
    if request.args.get("tag"):
        query = query.filter(Entity.tags.any(func.lower(Tag.name) == request.args["tag"].lower()))
    if request.args.get("location", type=int):
        query = query.filter(Entity.location_id == request.args.get("location", type=int))
    q = (request.args.get("q") or "").strip()
    if q:
        query = query.filter(Entity.search_text.like(like(q), escape="\\"))
    limit = min(max(request.args.get("limit", 100, type=int), 1), 500)
    offset = max(request.args.get("offset", 0, type=int), 0)
    rows = query.order_by(Entity.updated_at.desc(), Entity.id.desc()).offset(offset).limit(limit).all()
    return jsonify(entities=[to_json(e, full=False) for e in rows])


@bp.route("/entities/<int:entity_id>")
@role("viewer")
def entity_get(entity_id):
    return jsonify(entity=to_json(entity_or_404(entity_id, deleted_ok=True)))


@bp.route("/entities", methods=["POST"])
@role("editor")
def entity_create():
    data = _body()
    try:
        entity = records.create(data.get("type") or "", data)
        attach_to = data.get("attach_to")
        if attach_to:
            _attach_new(entity, attach_to)
    except Invalid as err:
        return _fail(err)
    db.session.commit()
    return jsonify(ok=True, entity=to_json(entity))


def _attach_new(entity: Entity, target_id) -> None:
    """A document written from another record's Documents tab: link it."""
    from .relations import link
    target = records.live(target_id)
    if target is None:
        raise Invalid("The record to attach it to no longer exists.")
    link("documented_by", target, entity)


@bp.route("/entities/<int:entity_id>", methods=["POST"])
@role("editor")
def entity_update(entity_id):
    entity = entity_or_404(entity_id)
    try:
        records.update(entity, _body())
    except Invalid as err:
        return _fail(err)
    db.session.commit()
    return jsonify(ok=True, entity=to_json(entity))


@bp.route("/entities/<int:entity_id>/archive", methods=["POST"])
@role("editor")
def entity_archive(entity_id):
    entity = entity_or_404(entity_id)
    archived = bool((request.get_json(silent=True) or {}).get("archived", True))
    records.set_archived(entity, archived)
    db.session.commit()
    return jsonify(ok=True, entity=to_json(entity), undo={
        "url": f"/api/entities/{entity.id}/archive", "body": {"archived": not archived},
    })


@bp.route("/entities/<int:entity_id>/delete", methods=["POST"])
@role("editor")
def entity_delete(entity_id):
    entity = entity_or_404(entity_id)
    records.delete(entity)
    db.session.commit()
    return jsonify(ok=True, undo={"url": f"/api/entities/{entity.id}/restore", "body": {}})


@bp.route("/entities/<int:entity_id>/restore", methods=["POST"])
@role("editor")
def entity_restore(entity_id):
    entity = entity_or_404(entity_id, deleted_ok=True)
    records.restore(entity)
    db.session.commit()
    return jsonify(ok=True, entity=to_json(entity))


@bp.route("/entities/<int:entity_id>/history")
@role("viewer")
def entity_history(entity_id):
    entity_or_404(entity_id, deleted_ok=True)
    rows = AuditLog.query.filter_by(entity_id=entity_id).order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(200)
    return jsonify(history=[{
        "at": r.at.isoformat() + "Z", "user": r.user_name, "action": r.action, "changes": r.changes,
    } for r in rows])


# ———— Tags ————

def tag_counts(type_keys=None) -> list[tuple[str, int]]:
    """Tags in use on live, unarchived entities, with how many carry each."""
    keys = type_keys if type_keys is not None else registry().enabled_type_keys()
    rows = (db.session.query(Tag.name, func.count(Entity.id))
            .join(entity_tags, entity_tags.c.tag_id == Tag.id)
            .join(Entity, Entity.id == entity_tags.c.entity_id)
            .filter(Entity.deleted_at.is_(None), Entity.archived.is_(False), Entity.type.in_(keys))
            .group_by(Tag.id).order_by(func.lower(Tag.name)).all())
    return [(name, count) for name, count in rows]


@bp.route("/tags")
@role("viewer")
def tags():
    return jsonify(tags=[{"name": n, "count": c} for n, c in tag_counts()])


# ———— Custom fields ————

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def _field_json(cf: CustomField) -> dict:
    return {"id": cf.id, "entity_type": cf.entity_type, "key": cf.key, "label": cf.label,
            "kind": cf.kind, "options": cf.options, "position": cf.position}


@bp.route("/custom-fields")
@role("viewer")
def custom_field_list():
    query = CustomField.query
    if request.args.get("type"):
        query = query.filter_by(entity_type=request.args["type"])
    return jsonify(fields=[_field_json(cf) for cf in query.order_by(CustomField.entity_type, CustomField.position)])


def _custom_options(data, kind) -> str:
    if kind != "select":
        return "[]"
    raw = data.get("options") or []
    if isinstance(raw, str):
        raw = raw.split("\n") if "\n" in raw else raw.split(",")
    options = []
    for o in raw:
        o = " ".join(str(o).split())[:80]
        if o and o not in options:
            options.append(o)
    if not options:
        raise Invalid("A choice list needs at least one option.")
    return json.dumps(options)


@bp.route("/custom-fields", methods=["POST"])
@role("admin")
def custom_field_create():
    data = _body()
    etype = registry().type(data.get("entity_type") or "")
    if etype is None:
        return jsonify(error="Choose a kind of record for the field."), 400
    label = " ".join((data.get("label") or "").split())[:80]
    if not label:
        return jsonify(error="Give the field a label."), 400
    kind = data.get("kind") or "text"
    if kind not in CUSTOM_KINDS:
        return jsonify(error="Choose text, number, date, choice list, address or yes/no."), 400
    key = records.slugify(label).replace("-", "_")[:40]
    if not KEY_RE.match(key):
        key = "field_" + key
    taken = {f.key for f in etype.fields} | {cf.key for cf in records.custom_fields(etype.key)}
    base, n = key, 2
    while key in taken or key in ("name", "slug", "status", "notes", "tags", "location"):
        key = f"{base}_{n}"
        n += 1
    try:
        options = _custom_options(data, kind)
    except Invalid as err:
        return _fail(err)
    position = (db.session.query(func.max(CustomField.position)).filter_by(entity_type=etype.key).scalar() or 0) + 1
    cf = CustomField(entity_type=etype.key, key=key, label=label, kind=kind, options_json=options, position=position)
    db.session.add(cf)
    db.session.commit()
    return jsonify(ok=True, field=_field_json(cf))


@bp.route("/custom-fields/<int:field_id>", methods=["POST"])
@role("admin")
def custom_field_update(field_id):
    """Rename a field, change its options or move it. Its kind stays: the
    values already stored were checked against it."""
    cf = db.get_or_404(CustomField, field_id)
    data = _body()
    if "label" in data:
        label = " ".join((data.get("label") or "").split())[:80]
        if not label:
            return jsonify(error="Give the field a label."), 400
        cf.label = label
    if "options" in data and cf.kind == "select":
        try:
            cf.options_json = _custom_options(data, cf.kind)
        except Invalid as err:
            return _fail(err)
    if "position" in data:
        cf.position = int(data["position"])
    db.session.commit()
    return jsonify(ok=True, field=_field_json(cf))


@bp.route("/custom-fields/<int:field_id>/delete", methods=["POST"])
@role("admin")
def custom_field_delete(field_id):
    """Remove a field and its values. Undo puts both back."""
    cf = db.get_or_404(CustomField, field_id)
    snapshot = _field_json(cf)
    snapshot["values"] = {v.entity_id: v.value for v in CustomValue.query.filter_by(field_id=cf.id)}
    db.session.delete(cf)
    db.session.flush()
    for entity in Entity.query.filter(Entity.id.in_(list(snapshot["values"]))):
        records.reindex(entity)
    db.session.commit()
    return jsonify(ok=True, undo={"url": "/api/custom-fields/restore", "body": snapshot})


@bp.route("/custom-fields/restore", methods=["POST"])
@role("admin")
def custom_field_restore():
    data = _body()
    etype = registry().type(data.get("entity_type") or "")
    key = data.get("key") or ""
    if etype is None or not KEY_RE.match(key) or data.get("kind") not in CUSTOM_KINDS:
        return jsonify(error="Nothing to restore."), 400
    if CustomField.query.filter_by(entity_type=etype.key, key=key).first():
        return jsonify(error="A field with that name exists again."), 409
    cf = CustomField(entity_type=etype.key, key=key, label=str(data.get("label") or key)[:80],
                     kind=data["kind"], options_json=json.dumps(list(data.get("options") or [])),
                     position=int(data.get("position") or 0))
    db.session.add(cf)
    db.session.flush()
    live_ids = {i for (i,) in db.session.query(Entity.id).filter(
        Entity.id.in_([int(k) for k in (data.get("values") or {})]))}
    for entity_id, value in (data.get("values") or {}).items():
        if int(entity_id) in live_ids:
            db.session.add(CustomValue(entity_id=int(entity_id), field_id=cf.id, value=str(value)))
    db.session.commit()
    for entity in Entity.query.filter(Entity.id.in_(live_ids)):
        records.reindex(entity)
    db.session.commit()
    return jsonify(ok=True, field=_field_json(cf))
