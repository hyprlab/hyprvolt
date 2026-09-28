"""The JSON API for entities, tags and custom fields.

The web interface and scripts use the same routes. Reads need a viewer,
writes an editor, custom field definitions an admin; failures answer
``{"error": "..."}`` written for a person, like every JSON route in the app.
A response to something that can be taken back carries ``undo``: the URL
and body that take it back, which the interface offers as Undo.
"""
import json
import re
from urllib.parse import quote

from flask import Blueprint, abort, jsonify, request, send_file
from flask_login import current_user
from sqlalchemy import func

from ..manifest import CUSTOM_KINDS
from ..models import db, utcnow
from ..permissions import role
from ..registry import current as registry
from . import access
from . import attachments as files
from . import fields as F
from . import images, records, relations
from .fields import Invalid
from .models import IMAGE_TYPES, Attachment, AuditLog, CustomField, CustomValue, Entity, Relationship, Tag, entity_tags

bp = Blueprint("api", __name__, url_prefix="/api")


def like(query: str) -> str:
    """A LIKE pattern that matches ``query`` literally."""
    return "%" + query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def entity_or_404(entity_id: int, deleted_ok: bool = False) -> Entity:
    entity = db.session.get(Entity, entity_id)
    etype = registry().type(entity.type) if entity else None
    if entity is None or etype is None or not registry().is_enabled(etype.module) or not access.can_see(entity):
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
        main = images.featured(entity)
        out["image"] = {"attachment_id": main.id, **images.urls(main)} if main else None
        out["path"] = [{"id": c.id, "name": c.name} for c in records.crumbs(entity)]
        values = records.own_values(entity)
        out["fields"] = {f.key: F.to_json(f, values.get(f.key)) for f in (etype.fields if etype else ())}
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
    ``tag``, ``location``, ``slug`` (one or several) and ``q``, newest change first. ``limit`` up to 500,
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
    if request.args.get("slug"):
        query = query.filter(Entity.slug.in_(request.args["slug"].split(",")))
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
        if data.get("link"):
            _link_new(entity, str(data["link"]))
    except Invalid as err:
        return _fail(err)
    db.session.commit()
    return jsonify(ok=True, entity=to_json(entity))


def _attach_new(entity: Entity, target_id) -> None:
    """A document written from another record's Documents tab: link it."""
    target = records.live(target_id)
    if target is None:
        raise Invalid("The record to attach it to no longer exists.")
    relations.link("documented_by", target, entity)


def _link_new(entity: Entity, spec: str) -> None:
    """``kind:id``: the new record <kind> that record, as when a change is
    recorded from the Maintenance tab of what it affects."""
    kind, _, target_id = spec.partition(":")
    target = records.live(target_id)
    if target is None:
        raise Invalid("The record to link it to no longer exists.")
    relations.link(kind, entity, target)


def _by_slug(slug: str) -> Entity | None:
    return Entity.query.filter_by(slug=slug.lower()).first()


@bp.route("/entities/by-slug/<slug>")
@role("viewer")
def entity_by_slug(slug):
    """A record by its slug, as ``GET /entities/<id>`` returns it."""
    entity = _by_slug(slug)
    if entity is None or entity.deleted_at is not None:
        abort(404, description=f"No record has the slug “{slug}”.")
    return jsonify(entity=to_json(entity_or_404(entity.id)))


@bp.route("/entities/by-slug/<slug>", methods=["POST"])
@role("editor")
def entity_upsert(slug):
    """Create or update the record with this slug, so an import can run
    again without making copies. Creating needs ``type`` and ``name``;
    updating takes what ``POST /entities/<id>`` takes. Answers ``created``."""
    data = _body()
    slug = slug.lower()
    if not records.SLUG_RE.match(slug):
        return jsonify(error="A slug is lower-case letters, digits and dashes, starting with a letter or digit."), 400
    entity = _by_slug(slug)
    if entity is not None and not access.can_see(entity):
        return jsonify(error=f"The slug “{slug}” is taken."), 409
    if entity is not None and entity.deleted_at is not None:
        return jsonify(error=f"A deleted record has the slug “{slug}”. Restore it (POST /api/entities/"
                             f"{entity.id}/restore), or choose another slug."), 409
    try:
        if entity is None:
            entity = records.create(data.get("type") or "", {**data, "slug": slug})
            created = True
        else:
            entity_or_404(entity.id)
            if data.get("type") and data["type"] != entity.type:
                return jsonify(error=f"“{slug}” is a {registry().type(entity.type).text()}, "
                                     f"not a {data['type']}."), 400
            records.update(entity, {k: v for k, v in data.items() if k not in ("type", "slug")})
            created = False
    except Invalid as err:
        return _fail(err)
    db.session.commit()
    return jsonify(ok=True, created=created, entity=to_json(entity))


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
    from .views import hide_secret_lines, redact
    rows = redact(hide_secret_lines(AuditLog.query.filter_by(entity_id=entity_id)
                                    .order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(200).all()))
    return jsonify(history=[{
        "at": r.at.isoformat() + "Z", "user": r.user_name, "action": r.action, "changes": r.changes,
    } for r in rows])


# ———— Relationships ————

def _rel_json(item: dict) -> dict:
    rel, other = item["rel"], item["other"]
    return {"id": rel.id, "kind": rel.kind, "label": item["label"], "outgoing": item["outgoing"],
            "note": rel.note, "other": to_json(other, full=False)}


@bp.route("/entities/<int:entity_id>/relationships")
@role("viewer")
def entity_relationships(entity_id):
    entity = entity_or_404(entity_id)
    return jsonify(relationships=[_rel_json(r) for r in relations.for_entity(entity)])


@bp.route("/entities/<int:entity_id>/dependencies")
@role("viewer")
def entity_dependencies(entity_id):
    """``direction=dependents`` (the default: what breaks if this goes down)
    or ``dependencies`` (what this needs)."""
    entity = entity_or_404(entity_id)
    direction = request.args.get("direction", "dependents")
    if direction not in ("dependents", "dependencies"):
        return jsonify(error="direction is dependents or dependencies."), 400
    depth = min(max(request.args.get("depth", 6, type=int), 1), 20)
    return jsonify(tree=relations.tree_json(relations.walk(entity, direction, depth)))


@bp.route("/relationships", methods=["POST"])
@role("editor")
def relationship_create():
    data = _body()
    if "direction" in data:
        # From the sheet's form: "kind:out" reads from this record, "kind:in"
        # the other way round.
        kind, _, direction = str(data.get("kind") or "").partition(":")
        direction = direction or data["direction"]
        here, other = data.get("entity_id"), data.get("other_id")
        if not other:
            return jsonify(error="Choose the record to link to."), 400
        data = {**data, "kind": kind, "source_id": here if direction == "out" else other,
                "target_id": other if direction == "out" else here}
    source, target = records.live(data.get("source_id")), records.live(data.get("target_id"))
    if source is None or target is None:
        return jsonify(error="Both ends of a link must be records that exist."), 400
    try:
        rel = relations.link(data.get("kind") or "", source, target, data.get("note") or "")
    except Invalid as err:
        return _fail(err)
    db.session.commit()
    kind = registry().kinds[rel.kind]
    return jsonify(ok=True, relationship={"id": rel.id, "kind": rel.kind, "label": kind.label,
                                          "source_id": source.id, "target_id": target.id, "note": rel.note})


@bp.route("/relationships/<int:rel_id>/delete", methods=["POST"])
@role("editor")
def relationship_delete(rel_id):
    rel = db.get_or_404(Relationship, rel_id)
    snapshot = relations.unlink(rel)
    db.session.commit()
    return jsonify(ok=True, undo={"url": "/api/relationships", "body": snapshot})


# ———— Attachments ————

def attachment_json(att) -> dict:
    out = {"id": att.id, "entity_id": att.entity_id, "filename": att.filename, "size": att.size,
           "content_type": att.content_type, "sha256": att.sha256,
           "created_at": att.created_at.isoformat() + "Z",
           "url": f"/attachments/{att.id}/{quote(att.filename)}"}
    if att.is_image:
        out.update(images.urls(att))
    return out


@bp.route("/entities/<int:entity_id>/attachments")
@role("viewer")
def attachment_list(entity_id):
    entity_or_404(entity_id)
    entity = entity_or_404(entity_id)
    rows = (Attachment.query.filter_by(entity_id=entity_id, deleted_at=None)
            .filter(Attachment.id != (entity.image_id or 0)).order_by(Attachment.created_at.desc()))
    return jsonify(attachments=[attachment_json(a) for a in rows])


@bp.route("/entities/<int:entity_id>/attachments", methods=["POST"])
@role("editor")
def attachment_upload(entity_id):
    """Multipart, one or more ``file`` parts."""
    entity = entity_or_404(entity_id)
    limit = files.max_bytes()
    if request.content_length and request.content_length > limit + 64 * 1024:
        return jsonify(error=f"Files are limited to {limit // (1024 * 1024)} MB."), 413
    uploads = request.files.getlist("file")
    if not uploads:
        return jsonify(error="Choose a file to attach."), 400
    saved = []
    try:
        for upload in uploads:
            att = files.save(entity, upload, current_user)
            saved.append(att)
            records.audit(entity, "attached", [{"field": "attachment", "label": "Attachment",
                                                "old": "", "new": att.filename}])
    except Invalid as err:
        db.session.flush()
        files.remove_files(attachments=saved)
        return _fail(err)
    db.session.flush()
    records.reindex(entity)
    db.session.commit()
    return jsonify(ok=True, attachments=[attachment_json(a) for a in saved])


def attachment_or_404(att_id: int, deleted_ok: bool = False):
    att = db.session.get(Attachment, att_id)
    if att is None or (att.deleted_at is not None and not deleted_ok):
        abort(404, description="There is no such file.")
    entity_or_404(att.entity_id, deleted_ok=True)
    return att


@bp.route("/attachments/<int:att_id>/delete", methods=["POST"])
@role("editor")
def attachment_delete(att_id):
    """Hidden at once; the file goes with the next purge, so Undo works."""
    att = attachment_or_404(att_id)
    att.deleted_at = utcnow()
    records.audit(att_entity(att), "detached", [{"field": "attachment", "label": "Attachment",
                                                 "old": att.filename, "new": ""}])
    db.session.flush()
    records.reindex(att_entity(att))
    db.session.commit()
    return jsonify(ok=True, undo={"url": f"/api/attachments/{att.id}/restore", "body": {}})


@bp.route("/attachments/<int:att_id>/restore", methods=["POST"])
@role("editor")
def attachment_restore(att_id):
    att = attachment_or_404(att_id, deleted_ok=True)
    if att.deleted_at is not None:
        att.deleted_at = None
        records.audit(att_entity(att), "attached", [{"field": "attachment", "label": "Attachment",
                                                     "old": "", "new": att.filename}])
        db.session.flush()
        records.reindex(att_entity(att))
        db.session.commit()
    return jsonify(ok=True, attachment=attachment_json(att))


def att_entity(att) -> Entity:
    return db.session.get(Entity, att.entity_id)


@bp.route("/entities/<int:entity_id>/image", methods=["POST"])
@role("editor")
def image_set(entity_id):
    """The featured image: upload one as multipart ``file``, or send
    ``{"attachment_id": 12}`` to use an image stored for this record (the
    one an Undo brings back), or ``{"attachment_id": null}`` for none. The
    image replaced comes back with the Undo in the answer."""
    entity = entity_or_404(entity_id)
    if request.files:
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return jsonify(error="Choose an image."), 400
        if (upload.mimetype or "") not in IMAGE_TYPES:
            return jsonify(error="The featured image must be a PNG, JPEG, GIF or WebP image."), 400
        try:
            att = files.save(entity, upload, current_user)
        except Invalid as err:
            return _fail(err)
    else:
        att_id = _body().get("attachment_id")
        att = db.session.get(Attachment, att_id) if type(att_id) is int else None
        if att_id is not None and (att is None or att.entity_id != entity.id):
            return jsonify(error="That image is not stored for this record."), 400
        if att is not None and not att.is_image:
            return jsonify(error="The featured image must be a PNG, JPEG, GIF or WebP image."), 400
    db.session.flush()
    before = entity.image_id
    old = records.set_image(entity, att)
    db.session.flush()
    records.reindex(entity)
    db.session.commit()
    out = {"ok": True, "entity": to_json(entity)}
    if before and (att is None or old is not None):
        out["undo"] = {"url": f"/api/entities/{entity.id}/image", "body": {"attachment_id": before}}
        out["message"] = "Featured image removed" if att is None else "Featured image replaced"
    return jsonify(out)


files_bp = Blueprint("files", __name__)


@files_bp.route("/attachments/<int:att_id>")
@files_bp.route("/attachments/<int:att_id>/<path:name>")
@role("viewer")
def attachment_download(att_id, name=None):
    """The file, under the name it was uploaded with. Images, PDFs and plain
    text open in the browser; anything else downloads. Nothing served from
    here runs script: it is sandboxed unless it is a PDF, which the browser's
    own viewer shows."""
    att = attachment_or_404(att_id)
    path = files.path_for(att)
    if not path.exists():
        abort(404, description="The file is missing from the data directory.")
    inline = att.content_type in files.INLINE and request.args.get("download") != "1"
    resp = send_file(path, mimetype=att.content_type if inline else "application/octet-stream",
                     as_attachment=not inline, download_name=att.filename, etag=att.sha256 or True,
                     max_age=0, conditional=True)
    if att.content_type != "application/pdf" or not inline:
        resp.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp


@files_bp.route("/attachments/<int:att_id>/thumb/<size>")
@role("viewer")
def attachment_thumb(att_id, size):
    """A small copy of an image (``sm`` for cards and galleries, ``lg`` for
    the large view), made the first time it is asked for."""
    att = attachment_or_404(att_id)
    if size not in images.SIZES or not att.is_image:
        abort(404, description="There is no such picture.")
    if not files.path_for(att).exists():
        abort(404, description="The file is missing from the data directory.")
    path = images.thumbnail(att, size)
    if path is None:
        abort(404, description="The picture could not be read.")
    resp = send_file(path, mimetype="image/webp", etag=f"{att.sha256}-{size}" if att.sha256 else True,
                     max_age=0, conditional=True)
    resp.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp


# ———— Tags ————

def tag_counts(type_keys=None) -> list[tuple[str, int]]:
    """Tags in use on live, unarchived entities, with how many carry each."""
    keys = type_keys if type_keys is not None else registry().enabled_type_keys()
    rows = (db.session.query(Tag.name, func.count(Entity.id))
            .join(entity_tags, entity_tags.c.tag_id == Tag.id)
            .join(Entity, Entity.id == entity_tags.c.entity_id)
            .filter(Entity.deleted_at.is_(None), Entity.archived.is_(False), Entity.type.in_(keys),
                    Entity.access.notin_(access.hidden()))
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
