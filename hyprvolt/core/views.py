"""The detail sheet and the record form, as HTML fragments.

``app.js`` fetches these and puts them into the sheet and the form dialog,
the same way paging fetches the list: the server renders every view of a
record (with Jinja's escaping), and the client never builds one from JSON.

The sheet's tabs are Overview, then the type's own tabs, Relationships, the
tabs built-in modules add (Documents), Attachments, History, and last any
tabs other modules add to every record.
"""
from flask import Blueprint, abort, render_template, request
from flask_login import current_user
from markupsafe import Markup

from ..models import db, int_setting
from ..permissions import role
from ..registry import current as registry
from . import attachments as files
from . import fields as F
from . import access, depmap, images, present, records, relations
from .api import entity_or_404
from .markdown import render as markdown
from .models import IMAGE_TYPES, Attachment, AuditLog, Entity

bp = Blueprint("sheet", __name__)


class SheetTab:
    def __init__(self, key, label, render, count=None):
        self.key, self.label, self.render, self.count = key, label, render, count


def tabs_for(entity: Entity) -> list[SheetTab]:
    reg = registry()
    etype = reg.type(entity.type)
    out = [SheetTab("overview", "Overview", overview_tab)]
    if etype:
        out += [SheetTab(t.key, t.label, t.render, t.count(entity) if t.count else None) for t in etype.tabs
                if t.when is None or t.when(entity)]
    rels = relations.for_entity(entity)
    out.append(SheetTab("relationships", "Relationships", relationships_tab, len(rels)))
    extensions = [(m, t) for m in reg.enabled_modules() for t in m.sheet_tabs if t.when is None or t.when(entity)]
    out += [SheetTab(t.key, t.label, t.render, t.count(entity) if t.count else None) for m, t in extensions if m.core]
    n_files = _files(entity).count()
    out.append(SheetTab("attachments", "Attachments", attachments_tab, n_files))
    out.append(SheetTab("history", "History", history_tab))
    out += [SheetTab(t.key, t.label, t.render, t.count(entity) if t.count else None)
            for m, t in extensions if not m.core]
    return out


@bp.route("/e/<int:entity_id>/sheet")
@role("viewer")
def sheet(entity_id):
    """The record with every section, one after another, and ``tab`` the one
    to scroll to; or, for an account that turned that off, with ``tab`` alone."""
    entity = entity_or_404(entity_id, deleted_ok=True)
    tabs = tabs_for(entity)
    key = request.args.get("tab") or "overview"
    tab = next((t for t in tabs if t.key == key), tabs[0])
    etype = registry().type(entity.type)
    scroll = bool(getattr(current_user, "record_scroll", True))
    return render_template(
        "sheet/sheet.html", entity=entity, etype=etype, tabs=tabs, tab=tab, access_short=access.SHORT,
        sections=[(t, Markup(t.render(entity))) for t in (tabs if scroll else [tab])], scroll=scroll, crumbs=present.crumbs(entity.location_id),
        status=records.status_label(entity), icon=present.icon(etype),
        purge_days=int_setting("purge_days", 30), editable=etype is not None and can_edit_here(entity),
    )


@bp.route("/e/<int:entity_id>/card")
@role("viewer")
def card(entity_id):
    """One record as the list shows it (``view=list`` for its row), so the
    list behind the sheet follows an edit made in it."""
    entity = entity_or_404(entity_id, deleted_ok=True)
    view = "list" if request.args.get("view") == "list" else "cards"
    return render_template("partials/records.html", items=present.views([entity]), view=view,
                           has_more=False, page_no=1)


# ———— Tabs ————

def can_edit_here(entity: Entity) -> bool:
    """Whether the reader edits this record in place: an editor, and a
    record that isn't deleted (restore it first)."""
    return bool(getattr(current_user, "can_edit", False)) and entity.deleted_at is None


def overview_tab(entity: Entity) -> str:
    etype = registry().type(entity.type)
    n_own = len(etype.fields) if etype else 0
    editable = etype is not None and can_edit_here(entity)
    edit = edit_items(entity, etype) if editable else {}
    controls = edit.get("fields", []) + edit.get("custom", [])
    groups, prose, custom = [], [], []
    values = records.field_values(entity)
    unshown = F.hidden_keys(etype.fields, {f.key: v for f, v in values[:n_own]}) if etype else set()
    for n, (f, value) in enumerate(values):
        is_custom = n >= n_own
        control = controls[n] if n < len(controls) else None
        if f.kind == "markdown":
            prose.append((f, markdown(value or ""), control))
            continue
        item = {"field": f, "value": value, "shown": F.display(f, value, records.live),
                "link": F.href(f, value), "control": control,
                "ref": records.live(value) if f.kind == "ref" and value else None}
        if is_custom:
            custom.append(item)
            continue
        if not editable and f.key in unshown:
            continue          # shown only while another field has a value it hasn't
        if not groups or groups[-1]["label"] != f.group:
            groups.append({"label": f.group, "items": []})
        groups[-1]["items"].append(item)
    above, below = etype.overview(entity) if etype and etype.overview else ("", "")
    return render_template("sheet/overview.html", entity=entity, etype=etype, groups=groups, prose=prose,
                           featured=images.featured(entity), pictures=images.gallery(entity),
                           image_types=", ".join(IMAGE_TYPES), limit_mb=int_setting("max_upload_mb", 25),
                           above=Markup(above), below=Markup(below),
                           access_label=access.LABELS.get(entity.access or "", "Everyone"),
                           custom=custom, notes=markdown(entity.notes or ""),
                           crumbs=present.crumbs(entity.location_id),
                           status=records.status_label(entity), editable=editable,
                           sections=edit.get("sections", []), locations=edit.get("locations", []),
                           kinds=kinds_for(entity, etype) if editable else [],
                           access_levels=access.choices(current_user) if editable else [])


def relationships_tab(entity: Entity) -> str:
    grouped: list[dict] = []
    for r in relations.for_entity(entity):
        if not grouped or grouped[-1]["label"] != r["label"]:
            grouped.append({"label": r["label"], "items": []})
        grouped[-1]["items"].append({**r, "view": present.View(r["other"])})
    kinds = []
    for k in registry().kinds.values():
        kinds.append((f"{k.key}:out", k.label))
        if k.reverse != k.label:
            kinds.append((f"{k.key}:in", k.reverse))
    dependents = relations.walk(entity, "dependents")
    needs = relations.walk(entity, "dependencies")
    return render_template("sheet/relationships.html", entity=entity, grouped=grouped, kinds=kinds,
                           diagram=Markup(depmap.draw(entity, needs, dependents)),
                           dependents=dependents, needs=needs,
                           n_dependents=relations.count(dependents), n_needs=relations.count(needs))


def attachments_tab(entity: Entity) -> str:
    rows = _files(entity).order_by(Attachment.created_at.desc()).all()
    return render_template("sheet/attachments.html", entity=entity, rows=rows, human_size=files.human_size,
                           limit_mb=int_setting("max_upload_mb", 25))


def _files(entity: Entity):
    """The record's attachments; the featured image has its own place."""
    return Attachment.query.filter_by(entity_id=entity.id, deleted_at=None) \
        .filter(Attachment.id != (entity.image_id or 0))


ACTIONS = {"created": "created it", "edited": "edited", "archived": "archived it", "unarchived": "unarchived it",
           "deleted": "deleted it", "restored": "restored it", "purged": "purged it", "linked": "linked",
           "unlinked": "unlinked", "attached": "attached", "detached": "removed"}


def hide_secret_lines(rows):
    """The vault's history lines (a secret added, changed, revealed) name a
    secret; only people with access to secrets see them."""
    if getattr(current_user, "sees_secrets", False):
        return rows
    return [r for r in rows if not r.action.endswith(" a secret")]


class HistoryLine:
    """A history row as a reader may see it."""
    def __init__(self, row, changes):
        self.at, self.user_name, self.action, self.changes = row.at, row.user_name, row.action, changes


def redact(rows) -> list:
    """History lines that name a record the reader may not see (a link to a
    private document, a field pointing at one) lose that change; a line left
    with nothing to say goes."""
    hidden = access.hidden()
    if not hidden:
        return rows
    ids = {c.get(k) for r in rows for c in r.changes for k in ("ref", "old_ref", "new_ref") if c.get(k)}
    secret = {i for (i,) in db.session.query(Entity.id).filter(Entity.id.in_(ids), Entity.access.in_(hidden))} \
        if ids else set()
    if not secret:
        return rows
    out = []
    for r in rows:
        changes = []
        for c in r.changes:
            if c.get("ref") in secret:
                continue
            c = dict(c)
            for side in ("old", "new"):
                if c.get(side + "_ref") in secret:
                    c[side] = "a restricted record"
            changes.append(c)
        if changes or not r.changes:
            out.append(HistoryLine(r, changes))
    return out


def history_tab(entity: Entity) -> str:
    rows = redact(hide_secret_lines(AuditLog.query.filter_by(entity_id=entity.id)
                                    .order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(300).all()))
    return render_template("sheet/history.html", entity=entity, rows=rows, actions=ACTIONS)


# ———— The form ————

def _location_choices(etype, entity=None) -> list[dict]:
    """Where a record of this type may be, grouped by location type, each
    labeled with its full path so two rooms called "Office" can be told apart."""
    reg = registry()
    if etype.located_in == ():
        return []
    allowed = etype.located_in or [t.key for t in reg.location_types()]
    groups = []
    for key in allowed:
        ltype = reg.type(key)
        if ltype is None or not reg.is_enabled(ltype.module):
            continue
        rows = Entity.live().filter(Entity.type == key).all()
        options = []
        for loc in rows:
            if entity is not None and entity.id is not None and _inside(loc, entity):
                continue
            path = present.path_label(loc.location_id)
            options.append((loc.id, f"{path} › {loc.name}" if path else loc.name))
        options.sort(key=lambda o: o[1].lower())
        if options:
            groups.append({"label": ltype.plural, "options": options})
    return groups


def _inside(loc: Entity, entity: Entity) -> bool:
    """Whether ``loc`` is ``entity`` or somewhere inside it."""
    seen = set()
    while loc is not None and loc.id not in seen:
        if loc.id == entity.id:
            return True
        seen.add(loc.id)
        loc = loc.location
    return False


def _preset(f):
    """A new record's value: ``f.<key>`` in the query string (a button that
    opens the form for a VM on this host), else the field's default."""
    raw = request.args.get("f." + f.key)
    if raw is None:
        return f.default
    if f.kind in ("ref", "integer"):
        return request.args.get("f." + f.key, type=int)
    return raw


def _ref_choices(f, entity=None) -> list[tuple[int, str]]:
    reg = registry()
    keys = [k for k in reg.ref_types(f) if k in reg.enabled_type_keys()]
    rows = Entity.live().filter(Entity.type.in_(keys)).order_by(Entity.name).all()
    # Several kinds of record in one list: say which each is.
    def label(e):
        return f"{e.name} · {reg.type(e.type).label}" if len(keys) > 1 else e.name
    return [(e.id, label(e)) for e in rows if entity is None or e.id != entity.id]


@bp.route("/e/form")
@bp.route("/e/<int:entity_id>/form")
@role("editor")
def form(entity_id=None):
    reg = registry()
    entity = entity_or_404(entity_id) if entity_id else None
    etype = reg.type(entity.type if entity else request.args.get("type", ""))
    if etype is None or not reg.is_enabled(etype.module):
        abort(404, description="There is no such kind of record.")
    # What it can be made instead: a record's form redrawn for another type
    # (?type=building for a room) shows that type's fields, saved as the change.
    kinds = kinds_for(entity, etype)
    as_type = next((t for t in kinds if t.key == request.args.get("type")), etype)
    retyping = as_type is not etype
    etype = as_type
    location_id = entity.location_id if entity else request.args.get("location_id", type=int)
    items = edit_items(entity, etype, retyping)
    return render_template(
        "sheet/form.html", entity=entity, etype=etype, **items, location_id=location_id, kinds=kinds,
        attach_to=request.args.get("attach_to", type=int), name=request.args.get("name", ""),
        link=request.args.get("link", ""), access_levels=access.choices(current_user),
        tags=", ".join(entity.tag_names) if entity else "", can_admin=current_user.is_admin,
    )


def kinds_for(entity: Entity, etype) -> list:
    """The types a record can be made instead, its own among them, in the
    module's order; [] when it can't change."""
    reg = registry()
    if entity is None or not etype.becomes:
        return []
    return [t for t in reg.module(etype.module).types if t.key == etype.key or t.key in etype.becomes]


def edit_items(entity, etype, retyping: bool = False) -> dict:
    """What a record's controls show, for the form and for the Overview an
    editor edits in place: the type's fields, the custom fields and the
    sections other modules add, each {"field", "name", "value", "choices"}."""
    reg = registry()
    own = records.own_values(entity) if entity else {}
    if retyping:
        detail = records.detail_of(entity)
        linked = records.linked_values([entity.id], etype).get(entity.id, {})
        own = {f.key: linked.get(f.key) if f.relation else getattr(detail, f.key, None) if detail else None
               for f in etype.fields}
    values = records.custom_values(entity) if entity else {}
    fields = []
    for f in etype.fields:
        value = own.get(f.key) if entity else _preset(f)
        if retyping and value in (None, ""):
            value = f.default
        if f.kind == "number" and isinstance(value, float) and value.is_integer():
            value = int(value)   # 850, not 850.0
        fields.append({"field": f, "name": "f." + f.key, "value": value,
                       "choices": _ref_choices(f, entity) if f.kind == "ref" else None})
    custom = []
    for cf in records.custom_fields(etype.key):
        f = F.custom_field(cf)
        custom.append({"field": f, "name": "c." + cf.key, "value": F.from_text(f, values.get(cf.id, "")),
                       "choices": None})
    # A field that follows another's value (shown_when) starts hidden unless it has it.
    gone = F.hidden_keys(etype.fields, {item["field"].key: item["value"] for item in fields})
    for item in fields:
        item["hidden"] = item["field"].key in gone
    # A choice can hide another module's section: a tower has no rack position.
    hidden = {k for item in fields for k, when in item["field"].hide_rules() if (item["value"] or "") in when}
    sections = [{"section": s, "html": Markup(s.render(etype, entity)), "hidden": s.key in hidden}
                for s in reg.form_sections(etype)]
    return {"fields": fields, "custom": custom, "sections": sections,
            "locations": _location_choices(etype, entity)}
