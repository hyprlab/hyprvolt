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

from ..models import int_setting
from ..permissions import role
from ..registry import current as registry
from . import attachments as files
from . import fields as F
from . import present, records, relations
from .api import entity_or_404
from .markdown import render as markdown
from .models import Attachment, AuditLog, Entity

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
    n_files = Attachment.query.filter_by(entity_id=entity.id, deleted_at=None).count()
    out.append(SheetTab("attachments", "Attachments", attachments_tab, n_files))
    out.append(SheetTab("history", "History", history_tab))
    out += [SheetTab(t.key, t.label, t.render, t.count(entity) if t.count else None)
            for m, t in extensions if not m.core]
    return out


@bp.route("/e/<int:entity_id>/sheet")
@role("viewer")
def sheet(entity_id):
    entity = entity_or_404(entity_id, deleted_ok=True)
    tabs = tabs_for(entity)
    key = request.args.get("tab") or "overview"
    tab = next((t for t in tabs if t.key == key), tabs[0])
    etype = registry().type(entity.type)
    return render_template(
        "sheet/sheet.html", entity=entity, etype=etype, tabs=tabs, tab=tab,
        panel=Markup(tab.render(entity)), crumbs=present.crumbs(entity.location_id),
        status=records.status_label(entity), icon=present.icon(etype),
        purge_days=int_setting("purge_days", 30),
    )


# ———— Tabs ————

def overview_tab(entity: Entity) -> str:
    etype = registry().type(entity.type)
    n_own = len(etype.fields) if etype else 0
    groups, prose, custom = [], [], []
    for n, (f, value) in enumerate(records.field_values(entity)):
        is_custom = n >= n_own
        if f.kind == "markdown":
            prose.append((f, markdown(value or "")))
            continue
        item = {"field": f, "value": value, "shown": F.display(f, value, records.live),
                "link": F.href(f, value),
                "ref": records.live(value) if f.kind == "ref" and value else None}
        if is_custom:
            custom.append(item)
            continue
        if not groups or groups[-1]["label"] != f.group:
            groups.append({"label": f.group, "items": []})
        groups[-1]["items"].append(item)
    return render_template("sheet/overview.html", entity=entity, etype=etype, groups=groups, prose=prose,
                           custom=custom, notes=markdown(entity.notes or ""),
                           crumbs=present.crumbs(entity.location_id),
                           status=records.status_label(entity))


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
                           dependents=dependents, needs=needs,
                           n_dependents=relations.count(dependents), n_needs=relations.count(needs))


def attachments_tab(entity: Entity) -> str:
    rows = Attachment.query.filter_by(entity_id=entity.id, deleted_at=None).order_by(Attachment.created_at.desc()).all()
    return render_template("sheet/attachments.html", entity=entity, rows=rows, human_size=files.human_size,
                           limit_mb=int_setting("max_upload_mb", 25))


ACTIONS = {"created": "created it", "edited": "edited", "archived": "archived it", "unarchived": "unarchived it",
           "deleted": "deleted it", "restored": "restored it", "purged": "purged it", "linked": "linked",
           "unlinked": "unlinked", "attached": "attached", "detached": "removed"}


def hide_secret_lines(rows):
    """The vault's history lines (a secret added, changed, revealed) name a
    secret; only people with access to secrets see them."""
    if getattr(current_user, "sees_secrets", False):
        return rows
    return [r for r in rows if not r.action.endswith(" a secret")]


def history_tab(entity: Entity) -> str:
    rows = hide_secret_lines(AuditLog.query.filter_by(entity_id=entity.id)
                             .order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(300).all())
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
    own = records.own_values(entity) if entity else {}
    values = records.custom_values(entity) if entity else {}
    fields = []
    for f in etype.fields:
        value = own.get(f.key) if entity else _preset(f)
        if f.kind == "number" and isinstance(value, float) and value.is_integer():
            value = int(value)   # 850, not 850.0
        fields.append({"field": f, "name": "f." + f.key, "value": value,
                       "choices": _ref_choices(f, entity) if f.kind == "ref" else None})
    custom = []
    for cf in records.custom_fields(etype.key):
        f = F.custom_field(cf)
        custom.append({"field": f, "name": "c." + cf.key, "value": F.from_text(f, values.get(cf.id, "")),
                       "choices": None})
    location_id = entity.location_id if entity else request.args.get("location_id", type=int)
    sections = [{"section": s, "html": Markup(s.render(etype, entity))} for s in reg.form_sections(etype)]
    return render_template(
        "sheet/form.html", entity=entity, etype=etype, fields=fields, custom=custom, sections=sections,
        locations=_location_choices(etype, entity), location_id=location_id,
        attach_to=request.args.get("attach_to", type=int), name=request.args.get("name", ""),
        link=request.args.get("link", ""),
        tags=", ".join(entity.tag_names) if entity else "", can_admin=current_user.is_admin,
    )
