"""The one way documentation is written.

Every create, edit, archive, delete, restore and purge goes through here,
whether it comes from the form, the JSON API, an import or ``seed-demo``. That
is what makes the history complete and the search text current: nothing
writes an entity behind this module's back.

Callers commit; a raised ``Invalid`` means nothing should be.
"""
import json
import re
import unicodedata
import uuid

from flask_login import current_user
from sqlalchemy import delete as sql_delete
from sqlalchemy.orm import aliased

from ..models import db, int_setting, utcnow
from ..registry import current as registry
from . import access
from . import fields as F
from .models import AuditLog, CustomField, CustomValue, Entity, Relationship, Tag
from .fields import Invalid

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,118}$")
MAX_TAGS = 30
LABELS = {"name": "Name", "slug": "Slug", "status": "Status", "location": "Location",
          "tags": "Tags", "notes": "Notes", "created_at": "Created", "access": "Visible to"}
CREATED = F.Field("created_at", "Created", "datetime")


# ———— Reading ————

def live(entity_id) -> Entity | None:
    """An entity that exists, isn't deleted, and whose module is turned on."""
    try:
        entity = db.session.get(Entity, int(entity_id))
    except (TypeError, ValueError):
        return None
    if entity is None or entity.deleted_at is not None or not access.can_see(entity):
        return None
    etype = registry().type(entity.type)
    if etype is None or not registry().is_enabled(etype.module):
        return None
    return entity


def detail_of(entity: Entity, create: bool = False):
    etype = registry().type(entity.type)
    if etype is None or etype.detail is None:
        return None
    row = db.session.get(etype.detail, entity.id)
    if row is None and create:
        row = etype.detail(entity_id=entity.id)
        db.session.add(row)
    return row


def custom_fields(type_key: str) -> list[CustomField]:
    return CustomField.query.filter_by(entity_type=type_key).order_by(CustomField.position, CustomField.id).all()


def custom_values(entity: Entity) -> dict[int, str]:
    return {v.field_id: v.value for v in CustomValue.query.filter_by(entity_id=entity.id)}


def linked_values(entity_ids, etype) -> dict[int, dict[str, int]]:
    """entity id -> {field key: target id} for the type's fields that are
    kept as links (``Field.relation``), in one query. The first live target
    of the field's kind and types wins."""
    rel_fields = [f for f in etype.fields if f.relation] if etype else []
    ids = [i for i in entity_ids if i is not None]
    if not rel_fields or not ids:
        return {}
    target = aliased(Entity)
    rows = (db.session.query(Relationship.source_id, Relationship.kind, Relationship.target_id, target.type)
            .join(target, target.id == Relationship.target_id)
            .filter(Relationship.source_id.in_(ids), Relationship.kind.in_({f.relation for f in rel_fields}),
                    target.deleted_at.is_(None))
            .order_by(Relationship.id).all())
    out: dict[int, dict[str, int]] = {}
    for source_id, kind, target_id, target_type in rows:
        for f in rel_fields:
            if f.relation == kind and F.ref_allows(f, target_type):
                out.setdefault(source_id, {}).setdefault(f.key, target_id)
    return out


def own_values(entity: Entity, detail=None, linked=None) -> dict:
    """{field key: value} for the type's own fields, read from the detail
    row or, for a field kept as a link, from the relationships."""
    etype = registry().type(entity.type)
    if etype is None:
        return {}
    if detail is None:
        detail = detail_of(entity)
    if linked is None:
        linked = linked_values([entity.id], etype).get(entity.id, {})
    return {f.key: linked.get(f.key) if f.relation else (getattr(detail, f.key, None) if detail else None)
            for f in etype.fields}


def field_values(entity: Entity) -> list[tuple]:
    """(Field, value) for the type's fields, then its custom fields, in the
    order the Overview shows them."""
    etype = registry().type(entity.type)
    out = []
    values = own_values(entity)
    for f in etype.fields if etype else ():
        out.append((f, values.get(f.key)))
    values = custom_values(entity)
    for cf in custom_fields(entity.type):
        f = F.custom_field(cf)
        out.append((f, F.from_text(f, values.get(cf.id, ""))))
    return out


def crumbs(entity: Entity) -> list[Entity]:
    """The chain of locations above ``entity``, outermost first."""
    chain, seen = [], {entity.id}
    loc = entity.location
    while loc is not None and loc.id not in seen and len(chain) < 12:
        if loc.deleted_at is None:
            chain.append(loc)
        seen.add(loc.id)
        loc = loc.location
    return list(reversed(chain))


def status_label(entity: Entity) -> str:
    etype = registry().type(entity.type)
    return dict(etype.statuses).get(entity.status, entity.status) if etype else entity.status


# ———— Writing ————

def create(type_key: str, data: dict, user=None) -> Entity:
    reg = registry()
    etype = reg.type(type_key)
    if etype is None or not reg.is_enabled(etype.module):
        raise Invalid("There is no such kind of record.")
    entity = Entity(module=etype.module, type=etype.key, name="", slug="", status=etype.statuses[0][0])
    db.session.add(entity)
    changes = _apply(entity, etype, data, creating=True, user=user)
    db.session.flush()
    audit(entity, "created", changes, user)
    return entity


def update(entity: Entity, data: dict, user=None) -> list[dict]:
    etype = registry().type(entity.type)
    if etype is None:
        raise Invalid("This record's module is not installed.")
    changes = _apply(entity, etype, data, creating=False, user=user)
    if changes:
        audit(entity, "edited", changes, user)
    return changes


def set_archived(entity: Entity, archived: bool, user=None) -> None:
    if entity.archived == archived:
        return
    entity.archived = archived
    _touch(entity, user)
    audit(entity, "archived" if archived else "unarchived", [], user)
    _remind(entity)


def delete(entity: Entity, user=None) -> None:
    """Soft: the row stays, hidden, until the purge. Undo is ``restore``."""
    if entity.deleted_at is not None:
        return
    entity.deleted_at = utcnow()
    _touch(entity, user)
    audit(entity, "deleted", [], user)
    _remind(entity)


def restore(entity: Entity, user=None) -> None:
    if entity.deleted_at is None:
        return
    entity.deleted_at = None
    _touch(entity, user)
    audit(entity, "restored", [], user)
    _remind(entity)


def purge(older_than_days: int | None = None) -> int:
    """Delete for good what was deleted more than ``older_than_days`` ago
    (the purge_days instance setting by default), files included."""
    from datetime import timedelta

    from .attachments import remove_files
    from .models import Attachment
    days = int_setting("purge_days", 30) if older_than_days is None else older_than_days
    cutoff = utcnow() - timedelta(days=days)
    files = Attachment.query.filter(Attachment.deleted_at.isnot(None), Attachment.deleted_at <= cutoff).all()
    if files:
        remove_files(attachments=files)
        for att in files:
            db.session.delete(att)
        db.session.flush()
    doomed = Entity.query.filter(Entity.deleted_at.isnot(None), Entity.deleted_at <= cutoff).all()
    if not doomed:
        return len(files)
    ids = [e.id for e in doomed]
    for e in doomed:
        audit(e, "purged", [], None)
    remove_files(ids)
    db.session.flush()
    db.session.expunge_all()
    # Straight SQL: the database's ON DELETE rules take the detail rows,
    # tags, custom values, relationships and attachments with it.
    db.session.execute(sql_delete(Entity).where(Entity.id.in_(ids)))
    return len(ids) + len(files)


def _remind(entity: Entity) -> None:
    from . import reminders
    reminders.refresh(entity)


def _touch(entity: Entity, user) -> None:
    entity.updated_at = utcnow()
    entity.updated_by_id = _user_id(user)


def _user(user):
    if user is not None:
        return user
    if current_user and getattr(current_user, "is_authenticated", False):
        return current_user._get_current_object()
    return None


def _user_id(user):
    who = _user(user)
    return who.id if who else None


def audit(entity: Entity, action: str, changes=None, user=None) -> None:
    who = _user(user)
    db.session.add(AuditLog(
        user_id=who.id if who else None,
        user_name=who.display_name if who else "",
        entity_id=entity.id,
        entity_label=entity.name,
        entity_type=entity.type,
        action=action,
        changes_json=json.dumps(changes or []),
    ))


def _apply(entity: Entity, etype, data: dict, creating: bool, user) -> list[dict]:
    """Check and set everything ``data`` names; return what changed as
    [{"label", "old", "new"}], shown the way the sheet shows it."""
    data = normalize(data)
    changes = []

    def note(key, label, old, new, **refs):
        if old != new and not (creating and new == ""):
            changes.append({"field": key, "label": label, "old": old, "new": new, **refs})

    if etype.name_from:
        if creating:
            entity.name = ""     # set from the field below
    elif creating or "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            raise Invalid("Give it a name.")
        if len(name) > 200:
            raise Invalid("Names are limited to 200 characters.")
        note("name", LABELS["name"], entity.name, name)
        entity.name = name

    if "slug" in data and (data.get("slug") or "").strip():
        slug = data["slug"].strip().lower()
        if not SLUG_RE.match(slug):
            raise Invalid("A slug is lower-case letters, digits and dashes, starting with a letter or digit.")
        clash = Entity.query.filter(Entity.slug == slug, Entity.id != (entity.id or 0)).first()
        if clash:
            raise Invalid(f"The slug “{slug}” is taken by {clash.name}." if access.can_see(clash)
                          else f"The slug “{slug}” is taken.")
        if not creating:
            note("slug", LABELS["slug"], entity.slug, slug)
        entity.slug = slug
    elif creating:
        # A name that comes from a field isn't known yet: a stand-in until then.
        entity.slug = unique_slug(entity.name) if not etype.name_from else "~" + uuid.uuid4().hex

    if "status" in data and data["status"] not in (None, ""):
        values = dict(etype.statuses)
        if data["status"] not in values:
            raise Invalid("Status must be one of: " + ", ".join(values.values()) + ".")
        note("status", LABELS["status"], values.get(entity.status, entity.status), values[data["status"]])
        entity.status = data["status"]

    if "location_id" in data:
        new_loc = _check_location(entity, etype, data["location_id"])
        old_name = entity.location.name if entity.location else ""
        note("location", LABELS["location"], old_name, new_loc.name if new_loc else "")
        entity.location = new_loc

    if "tags" in data:
        names = parse_tags(data["tags"])
        old = ", ".join(entity.tag_names)
        entity.tags = [_tag(n) for n in names]
        note("tags", LABELS["tags"], old, ", ".join(sorted(names, key=str.lower)))

    if "access" in data and (data["access"] or "") != (entity.access or ""):
        _set_access(entity, etype, data["access"] or "", user, note)

    if data.get("created_at") not in (None, ""):
        _set_created(entity, data["created_at"], user, note)

    if "notes" in data:
        notes = (data.get("notes") or "").strip()
        if len(notes) > F.MAX_LONG:
            raise Invalid(f"Notes are limited to {F.MAX_LONG} characters.")
        note("notes", LABELS["notes"], entity.notes or "", notes)
        entity.notes = notes

    db.session.flush()   # an id for the detail and custom rows
    given = data.get("fields") or {}
    if etype.fields and (creating or given):
        detail = detail_of(entity, create=True)
        linked = {} if creating else linked_values([entity.id], etype).get(entity.id, {})
        for f in etype.fields:
            if f.key in given:
                raw = given[f.key]
            elif creating:
                raw = f.default
            else:
                continue
            value = F.parse(f, raw, lookup=live)
            old = linked.get(f.key) if f.relation else getattr(detail, f.key, None)
            # "" and None are both empty: a column's default ("") is no change.
            if old != value and not (old in (None, "") and value in (None, "")):
                refs = {"old_ref": old, "new_ref": value} if f.kind == "ref" else {}
                note("f." + f.key, f.label, F.display(f, old, live), F.display(f, value, live), **refs)
                if f.relation:
                    _relink(entity, f, old, value, user)
                else:
                    setattr(detail, f.key, value)

    given = data.get("custom") or {}
    if given:
        existing = {v.field_id: v for v in CustomValue.query.filter_by(entity_id=entity.id)}
        for cf in custom_fields(etype.key):
            if cf.key not in given:
                continue
            f = F.custom_field(cf)
            value = F.parse(f, given[cf.key])
            text = F.to_text(f, value)
            row = existing.get(cf.id)
            old = row.value if row else ""
            if old == text:
                continue
            note("c." + cf.key, cf.label, F.display(f, F.from_text(f, old)), F.display(f, value))
            if row is None:
                db.session.add(CustomValue(entity_id=entity.id, field_id=cf.id, value=text))
            else:
                row.value = text

    if etype.name_from:
        f = next(f for f in etype.fields if f.key == etype.name_from)
        name = F.display(f, own_values(entity).get(f.key), live)
        if not name:
            raise Invalid(f"{f.label} is required.")
        if name != entity.name:
            if not creating:
                note("name", LABELS["name"], entity.name, name)
            entity.name = name
        if entity.slug.startswith("~"):
            entity.slug = unique_slug(name)
    if etype.check is not None:
        etype.check(entity, detail_of(entity))

    given = data.get("sections") or {}
    for section in registry().form_sections(etype):
        if section.key in given:
            values = given[section.key] if isinstance(given[section.key], dict) else {}
            changes += section.save(entity, values, user) or []
    changes[:] = _merge(changes)

    if changes or creating:
        _touch(entity, user)
        if creating:
            entity.created_by_id = entity.updated_by_id
    db.session.flush()
    reindex(entity)
    _remind(entity)
    return changes


def _set_access(entity: Entity, etype, level: str, user, note) -> None:
    if level not in access.LABELS:
        raise Invalid("Visible to must be everyone, editors or private.")
    if level and not etype.restrictable:
        raise Invalid(f"A {etype.text()} is visible to everyone; only documents can be restricted.")
    who = _user(user)
    if level and who is not None and not access.allows(who, level):
        raise Invalid("That would hide it from you: choose a level you can see.")
    note("access", LABELS["access"], access.LABELS[entity.access or ""], access.LABELS[level])
    entity.access = level


def _set_created(entity: Entity, raw, user, note) -> None:
    """When the record came into being, for records brought in from
    elsewhere (a manual first written in 2019). An admin's call only: it
    rewrites what the history would otherwise say."""
    from . import clock
    who = _user(user)
    if who is None or not getattr(who, "is_admin", False):
        raise Invalid("Only an admin can set when a record was created.")
    when = F.parse(CREATED, raw)
    if when > utcnow():
        raise Invalid("A record can't have been created in the future.")
    if entity.created_at is not None:
        note("created_at", LABELS["created_at"], clock.shown(entity.created_at), clock.shown(when))
    entity.created_at = when


def _relink(entity: Entity, f, old_id, new_id, user) -> None:
    """Point a field kept as a link somewhere else. The record's own history
    has the field change; the other ends get "linked" and "unlinked"."""
    from . import relations
    if old_id is not None:
        for rel in Relationship.query.filter_by(source_id=entity.id, kind=f.relation, target_id=old_id):
            relations.unlink(rel, user, audit_source=False)
    if new_id is not None:
        relations.link(f.relation, entity, live(new_id), user=user, audit_source=False)


def _merge(changes: list[dict]) -> list[dict]:
    """One line per field: a form section may change what the form also
    changed (a rack position moves the location), so keep the first old
    value and the last new one, and drop what ends where it started."""
    out, at = [], {}
    for c in changes:
        if c["field"] in at:
            out[at[c["field"]]]["new"] = c["new"]
            if "new_ref" in c:
                out[at[c["field"]]]["new_ref"] = c["new_ref"]
        else:
            at[c["field"]] = len(out)
            out.append(dict(c))
    return [c for c in out if c["old"] != c["new"]]


def move(entity: Entity, target: Entity | None, user=None) -> list[dict]:
    """Set the location from a form section or a module route: checked like
    the form's, returned as a change for the caller's history line."""
    etype = registry().type(entity.type)
    new_loc = _check_location(entity, etype, target.id if target else None)
    old_name = entity.location.name if entity.location else ""
    if new_loc is entity.location:
        return []
    entity.location = new_loc
    _touch(entity, user)
    return [{"field": "location", "label": LABELS["location"], "old": old_name,
             "new": new_loc.name if new_loc else ""}]


def normalize(data: dict) -> dict:
    """Accept the flat names a form posts (``f.height_u``, ``c.owner``,
    ``s.rack.position_u``) as well as the nested ``fields``, ``custom`` and
    ``sections`` objects the API documents."""
    out = {k: v for k, v in data.items() if not k.startswith(("f.", "c.", "s."))}
    out["fields"] = dict(data.get("fields") or {})
    out["custom"] = dict(data.get("custom") or {})
    sections = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    out["sections"] = {k: dict(v) for k, v in sections.items() if isinstance(v, dict)}
    for k, v in data.items():
        if k.startswith("f."):
            out["fields"][k[2:]] = v
        elif k.startswith("c."):
            out["custom"][k[2:]] = v
        elif k.startswith("s.") and k.count(".") == 2:
            _, section, name = k.split(".")
            out["sections"].setdefault(section, {})[name] = v
    return out


def _check_location(entity: Entity, etype, raw) -> Entity | None:
    if raw in (None, "", 0, "0"):
        return None
    if etype.located_in == ():
        raise Invalid(f"A {etype.text()} has no location.")
    target = live(raw)
    reg = registry()
    ttype = reg.type(target.type) if target else None
    if target is None or ttype is None or not ttype.location:
        raise Invalid("Choose a location that exists.")
    if etype.located_in is not None and target.type not in etype.located_in:
        allowed = ", ".join(reg.type(t).text() for t in etype.located_in if reg.type(t))
        raise Invalid(f"A {etype.text()} can only be in a {allowed}.")
    # Walk up from the new location: meeting this entity means a loop.
    seen, loc = set(), target
    while loc is not None and loc.id not in seen:
        if entity.id is not None and loc.id == entity.id:
            raise Invalid("A location can't be inside itself.")
        seen.add(loc.id)
        loc = loc.location
    return target


def parse_tags(raw) -> list[str]:
    items = raw if isinstance(raw, (list, tuple)) else str(raw or "").split(",")
    names, seen = [], set()
    for item in items:
        name = " ".join(str(item).split())[:60]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    if len(names) > MAX_TAGS:
        raise Invalid(f"A record can have at most {MAX_TAGS} tags.")
    return names


def _tag(name: str) -> Tag:
    tag = Tag.query.filter(Tag.name == name).first()   # NOCASE: "Prod" finds "prod"
    if tag is None:
        tag = Tag(name=name)
        db.session.add(tag)
        db.session.flush()
    return tag


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:100] or "record"


def unique_slug(name: str) -> str:
    base = slugify(name)
    taken = {s for (s,) in db.session.query(Entity.slug).filter(
        (Entity.slug == base) | Entity.slug.like(base + "-%"))}
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def reindex(entity: Entity) -> None:
    """Rebuild what search matches: the name, slug, notes and tags, every
    searchable detail field, every custom field value, and the names and
    words of its attached files."""
    from .models import Attachment
    parts = [entity.name, entity.slug, entity.notes or "", " ".join(entity.tag_names)]
    for f, value in field_values(entity):
        if f.search and value not in (None, ""):
            parts.append(F.display(f, value, live) if f.kind != "boolean" else "")
    if entity.id is not None:
        for name, text in (db.session.query(Attachment.filename, Attachment.text)
                           .filter(Attachment.entity_id == entity.id, Attachment.deleted_at.is_(None))):
            parts += [name, text or ""]
    entity.search_text = " ".join(p for p in parts if p).lower()
