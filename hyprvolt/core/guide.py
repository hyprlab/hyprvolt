"""The site setup guide: a site documented a step at a time, from the site
itself out to the endpoints and the cables between them.

The steps come from the turned-on modules (``Module.setup``, SetupStep in
manifest.py), in their ``order``: Locations asks for the site and its rooms,
Network for the internet connection and subnets, Hardware for the gear,
the servers and the endpoints, and so on. Each step is a list of rows, one
record a row: what is recorded already, each field saved as it changes
(``records.update``), and a blank row at the end that becomes a record
(``records.create``) once it has a name. Rows are deleted in place, asked
first, with Undo. A step of places that hold each other is a tree instead.
The site chosen in the first step (``?site=``) is where the later steps'
records are placed by default.
"""
from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from markupsafe import Markup

from ..models import db
from ..permissions import role
from ..registry import current as registry
from . import fields as F
from . import records
from .fields import Invalid
from .models import Entity

bp = Blueprint("guide", __name__)

def _steps():
    return registry().setup_steps()


def _step_or_404(key):
    step = next((s for s in _steps() if s.key == key), None)
    if step is None:
        abort(404, description="There is no such step.")
    return step


def _kinds(step):
    reg = registry()
    return [k for k in step.kinds if reg.type(k.type) is not None]


# ———— The site the guide is about ————

def _scope():
    """The site of ``?site=``; or, when there is one site, that one;
    ``?new=1`` is none, for a new site."""
    keys = [k.type for s in _steps() if s.scope for k in s.kinds]
    if not keys or request.args.get("new"):
        return None
    given = records.live(request.args.get("site", type=int) or 0)
    if given is not None and given.type in keys:
        return given
    sites = Entity.live().filter(Entity.type.in_(keys)).limit(2).all()
    return sites[0] if len(sites) == 1 else None


def _places(scope) -> list[tuple[int, str]]:
    """The site and every location inside it, labeled with the path below
    the site and what it is: "Main House › Basement (room)", "Garage
    (building)", "Hyprlab (site)"."""
    if scope is None:
        return []
    reg = registry()
    location_types = [t.key for t in reg.location_types()]

    def kind(e):
        etype = reg.type(e.type)
        return f" ({etype.text()})" if etype else ""
    everything = {e.id: e for e in Entity.live().filter(Entity.type.in_(location_types))}

    def path(e):
        names, seen = [], set()
        while e is not None and e.id not in seen:
            seen.add(e.id)
            names.append(e.name)
            if e.id == scope.id:
                return list(reversed(names))
            e = everything.get(e.location_id)
        return None
    out = []
    for e in everything.values():
        p = path(e) if e.id != scope.id else None
        if p:
            out.append((e.id, " › ".join(p[1:]), kind(e)))
    out.sort(key=lambda o: o[1].lower())
    return [(scope.id, scope.name + kind(scope))] + [(i, text + k) for i, text, k in out]


def _inside(entity, scope, place_ids) -> bool:
    """In the site, or in no place at all (so a row set to no place stays
    in its step rather than vanishing from it)."""
    etype = registry().type(entity.type)
    if scope is None or etype is None or etype.located_in == () or entity.location_id is None:
        return True
    return entity.location_id in place_ids or entity.id == scope.id


# ———— A step's columns ————

def _records_of(types) -> list[tuple[int, str]]:
    reg = registry()
    keys = [k for k in types if k in reg.enabled_type_keys()]
    rows = Entity.live().filter(Entity.type.in_(keys)).order_by(Entity.name).all() if keys else []
    return [(e.id, e.name) for e in rows]


def _field_choices(fields) -> list:
    """The records a column's ref fields can point at, once each: by name,
    or under each kind's heading when there are several kinds. Choices
    that aren't records (``Field.also``) come first."""
    from .views import _ref_choices
    seen, flat, groups = set(), [], {}
    fixed = list(dict.fromkeys(c for f in fields for c in f.also))
    seen.update(value for value, _ in fixed)
    for f in fields:
        for c in _ref_choices(f):
            for value, label in (c["options"] if isinstance(c, dict) else [c]):
                if value not in seen:
                    seen.add(value)
                    (groups.setdefault(c["label"], []) if isinstance(c, dict) else flat).append((value, label))
    if not groups:
        return fixed + sorted(flat, key=lambda c: str(c[1]).lower())
    return fixed + [{"label": label, "options": options} for label, options in groups.items()] + flat


def in_site(entities, scope) -> list:
    """Those of ``entities`` in the site, or in no place."""
    if scope is None:
        return list(entities)
    place_ids = {i for i, _ in _places(scope)}
    return [e for e in entities if _inside(e, scope, place_ids)]


def _in_site(choices, scope) -> list:
    """Choices of records, (id, label) or groups of them ({"label",
    "options"}), only those in the site or in no place: the equipment of
    this site a UPS can power, not another's."""
    if scope is None:
        return choices
    place_ids = {i for i, _ in _places(scope)}
    ids = {o[0] for c in choices for o in (c["options"] if isinstance(c, dict) else [c])}
    keep = {e.id for e in Entity.query.filter(Entity.id.in_(ids)) if _inside(e, scope, place_ids)}
    out = []
    for c in choices:
        if isinstance(c, dict):
            options = [o for o in c["options"] if o[0] in keep]
            if options:
                out.append({**c, "options": options})
        elif c[0] in keep:
            out.append(c)
    return out


def columns(step, scope) -> list[dict]:
    """What each row asks for: {"name", "label", "kind" (text, number,
    select, multi, check), "choices", "placeholder", "required", "default"}. A
    field none of the step's types has, or a section that doesn't apply to
    them, is left out."""
    reg = registry()
    kinds = _kinds(step)
    types = [reg.type(k.type) for k in kinds]
    cols = []
    if len(kinds) > 1:
        cols.append({"name": "_kind", "label": "Kind", "kind": "select", "required": True,
                     "choices": [(str(i), k.label) for i, k in enumerate(kinds)]})
    for sf in step.fields:
        col = {"name": sf.name, "label": sf.label, "kind": sf.kind, "placeholder": sf.placeholder,
               "required": False, "choices": None, "default": "", "newline": sf.newline}
        if sf.name == "name":
            # A row of kinds of which some have a hostname: "Name or hostname".
            label = next((t.name_label for t in types if t.name_label != "Name"), "Name")
            col.update(label=sf.label or label, kind="text", required=True)
        elif sf.name == "location_id":
            places = _places(scope)
            if not places:
                continue
            col.update(label=sf.label or "Where", kind="select", choices=places, default=places[0][0])
        elif sf.name.startswith("f."):
            fields = [f for t in types for f in t.fields if f.key == sf.name[2:]]
            if not fields:
                continue
            f = fields[0]
            col["label"] = sf.label or (f"{f.label} ({f.unit})" if f.unit else f.label)
            col["unit"] = f.unit
            col["suggest"] = f.suggest
            col["switch"] = f.switch
            if f.shown_when:
                col["when"] = ("f." + f.shown_when[0], F.when_value(f.shown_when[1]))
            col["required"] = f.required and all(any(x.key == f.key for x in t.fields) for t in types)
            if f.kind == "select":
                col.update(kind="select", choices=f.choices())
            elif f.kind == "ref":
                col.update(kind="select", choices=_field_choices(fields))
            elif f.kind in ("speed", "cidr", "iprange"):
                col.update(kind=f.kind, prefills=f.prefills)
            elif f.kind in ("integer", "number"):
                col.update(kind="number", default=f.default if f.default is not None else "")
            elif f.kind == "boolean":
                col.update(kind="check")
            else:
                col["kind"] = "text"
        elif sf.name.startswith("s."):
            key, name = sf.name.split(".")[1], sf.name.split(".", 2)[2]
            section = next((s for t in types for s in reg.form_sections(t) if s.key == key), None)
            if section is None:
                continue
            if sf.kind == "check":
                col.update(kind="check", confirm_off=sf.confirm_off)
            elif sf.kind == "place":
                col.update(kind="select", choices=_places(scope))
            elif section.choices is not None and sf.kind == "multi":
                col.update(kind="multi", choices=_in_site(section.choices(name), scope))
            elif section.choices is not None and section.choices(name) is not None:
                col.update(kind="select", choices=section.choices(name))
            elif sf.types:
                col.update(kind="select", choices=_records_of(sf.types))
        elif sf.choices is not None:
            col.update(kind="select", choices=sf.choices(scope))
        if sf.shown_when:
            col["when"] = col["follows"] = (sf.shown_when[0], str(sf.shown_when[1]))
        if sf.relabel:
            col["relabel"] = (sf.relabel[0], str(sf.relabel[1]), sf.relabel[2])
        if sf.kinds and len(kinds) > 1:
            # Only in rows of those kinds: shown as the row's kind is chosen.
            col["when"] = ("_kind", " ".join(str(i) for i, k in enumerate(kinds) if k.label in sf.kinds))
            col["only"] = {i for i, k in enumerate(kinds) if k.label in sf.kinds}
        cols.append(col)
    return cols


def _count(step, scope) -> int:
    """How many of the step's records (or rows) the site has."""
    if step.save is not None:
        return len(step.rows(scope)) if step.rows else 0
    return len(_found(step, scope))


def _found(step, scope) -> list[Entity]:
    """The records of a step of records, in this site."""
    kinds = _kinds(step)
    rows = Entity.live().filter(Entity.type.in_({k.type for k in kinds})).order_by(Entity.name).all()
    place_ids = {i for i, _ in _places(scope)}
    out = []
    for e in rows:
        if not _inside(e, scope, place_ids):
            continue
        # A kind that is a preset of its type (an internet connection is a
        # network of the kind wan) lists only its own.
        detail = records.detail_of(e)
        if any(k.type == e.type and all(getattr(detail, n[2:], None) == v for n, v in k.values.items()
                                        if n.startswith("f."))
               for k in kinds):
            out.append(e)
    if step.joined is not None:
        # Shown in another's row: a MoCA pair is one row.
        inside = {j.id for e in out for j in step.joined(e)}
        out = [e for e in out if e.id not in inside]
    return out


# ———— A step of records that hold each other: the tree ————

def tree(step, scope) -> dict | None:
    """The site and the step's records under it, each where it is:
    {"entity", "type", "accepts" [kinds it can hold], "becomes" [the
    step's kinds it can be made, its own first: those a place above it can
    hold (tree_kind moves it there)], "children", "root",
    "inside" (how many of the step's records are in it, at any depth),
    "holds" (how many other records, such as racks and servers, are)}.
    A record whose place is outside the site, or gone, isn't in it."""
    if scope is None:
        return None
    reg = registry()
    kinds = _kinds(step)

    def accepts(type_key):
        return [k for k in kinds if reg.type(k.type).located_in is None or type_key in reg.type(k.type).located_in]

    def fits(type_key, parent_key):
        inside = reg.type(type_key).located_in
        return inside is None or parent_key in inside

    def becomes(e, above):
        own = reg.type(e.type)
        return [own] + [reg.type(k.type) for k in kinds if k.type != e.type and k.type in own.becomes
                        and any(fits(k.type, a.type) for a in above)]
    rows = Entity.live().filter(Entity.type.in_({k.type for k in kinds})).all()
    below = {}
    for e in rows:
        below.setdefault(e.location_id, []).append(e)
    order = {k.type: n for n, k in enumerate(kinds)}
    others = dict(db.session.query(Entity.location_id, db.func.count(Entity.id))
                  .filter(Entity.deleted_at.is_(None), Entity.type.notin_({k.type for k in kinds}))
                  .group_by(Entity.location_id).all())

    def node(e, root=False, seen=(), above=()):
        children = [node(c, seen=seen + (e.id,), above=(e,) + above) for c in
                    sorted(below.get(e.id, []), key=lambda c: (order.get(c.type, 9), c.name.lower()))
                    if c.id not in seen]
        etype = reg.type(e.type)
        count = {}                      # type key -> how many, at any depth
        for c in children:
            count[c["type"].key] = count.get(c["type"].key, 0) + 1
            for t, n in c["count"].items():
                count[t] = count.get(t, 0) + n
        words = [f"{n} {reg.type(t).text(n != 1)}" for t, n in sorted(count.items(), key=lambda x: order.get(x[0], 9))]
        return {"entity": e, "type": etype, "accepts": accepts(e.type), "children": children, "root": root,
                "becomes": becomes(e, above) if above else [etype],
                "count": count, "inside": " and ".join(words),
                "holds": others.get(e.id, 0) + sum(c["holds"] for c in children)}
    return node(scope, root=True)


def _subtree(step, entity) -> list[Entity]:
    """A record of a tree step and the step's records in it, at any depth,
    the deepest first."""
    types = {k.type for k in _kinds(step)}
    out, todo = [], [entity]
    while todo:
        e = todo.pop()
        if any(e.id == x.id for x in out):
            continue
        out.append(e)
        todo += Entity.live().filter(Entity.location_id == e.id, Entity.type.in_(types)).all()
    return list(reversed(out))


def _tree_html(step, scope) -> str:
    return render_template("partials/guide_tree.html", step=step, tree=tree(step, scope), scope=scope)


# ———— A step of rows: each a record, saved as it changes ————

def _kind_index(step, entity) -> int:
    """Which of the step's kinds a record is: its type, and a preset it has
    (a switch is network gear of the kind switch)."""
    kinds = _kinds(step)
    detail = records.detail_of(entity)
    for i, k in enumerate(kinds):
        if k.type == entity.type and all(getattr(detail, n[2:], None) == v for n, v in k.values.items()
                                         if n.startswith("f.")):
            return i
    return next((i for i, k in enumerate(kinds) if k.type == entity.type), 0)


def _row(step, cols, entity) -> dict:
    """A record as a row: {"id", "label", "values" {column: value},
    "absent" (columns its type doesn't have: a printer has no Used by),
    "blocked" {column: (title, text)}: a box that can't be unticked, and
    why (a hypervisor with VMs on it)}."""
    reg = registry()
    etype = reg.type(entity.type)
    own = records.own_values(entity)
    sections = {s.key: s for s in reg.form_sections(etype)}
    held, values, absent, blocked = {}, {}, set(), {}
    for c in cols:
        n = c["name"]
        if n == "_kind":
            values[n] = str(_kind_index(step, entity))
        elif n == "name":
            values[n] = entity.name
        elif n == "location_id":
            values[n] = entity.location_id or ""
        elif n.startswith("f."):
            if n[2:] not in own:
                absent.add(n)
            values[n] = "" if own.get(n[2:]) is None else own[n[2:]]
        elif n.startswith("s."):
            _, key, name = n.split(".", 2)
            section = sections.get(key)
            if section is None:
                absent.add(n)
            elif section.values is not None:
                held.setdefault(key, section.values(entity) or {})
                values[n] = held[key].get(name, "")
                if c.get("confirm_off") and held[key].get(name + "_blocked"):
                    blocked[n] = held[key][name + "_blocked"]
    gone = {"f." + k for k in F.hidden_keys(etype.fields, own)}
    kind = int(values["_kind"]) if "_kind" in values else 0
    gone |= {c["name"] for c in cols if "only" in c and kind not in c["only"]}
    gone |= _not_followed(cols, values, gone)
    return {"id": entity.id, "label": entity.name, "values": values, "absent": absent, "text": {}, "locked": (),
            "blocked": blocked,
            "hidden": {c["name"] for c in cols if c["name"] in gone}}


def _shown_as(value) -> str:
    """A column's value as app.js compares it: a box is "1" or "0"."""
    if value is True or value is False:
        return "1" if value else "0"
    return "" if value is None else str(value)


def _not_followed(cols, values, gone) -> set:
    """The columns shown only while another has a value (SetupField
    shown_when), where it hasn't, or where that one is hidden itself."""
    out = set()
    for c in cols:
        if "follows" in c:
            name, wanted = c["follows"]
            if name in gone | out or _shown_as(values.get(name, "")) not in wanted.split(" "):
                out.add(c["name"])
    return out


def rows_of(step, cols, scope) -> list[dict]:
    """The step's rows, one a record (or for a step with its own save, what
    its ``rows`` gives)."""
    if step.save is not None:
        return list(step.rows(scope)) if step.rows else []
    found = ([scope] if scope is not None else []) if step.scope else _found(step, scope)
    rows = [_row(step, cols, e) for e in found]
    kinds = _kinds(step)
    if step.grouped and len(kinds) > 1:
        # Under a heading for each kind, in the kinds' order: modems before
        # routers before switches.
        for r in rows:
            r["group"] = kinds[int(r["values"].get("_kind") or 0)].heading()
        order = {k.heading(): i for i, k in enumerate(kinds)}
        rows.sort(key=lambda r: order[r["group"]])
    return rows


def _truthy(value) -> bool:
    return value in (True, "1", "on", "true")


def create_row(step, cols, values, scope, user=None):
    """A new row, made: the record, or what the step's ``save`` makes."""
    if step.save is not None:
        step.save(values, scope, user)
        return None
    kinds = _kinds(step)
    try:
        kind = kinds[int(values.get("_kind") or 0)]
    except (TypeError, ValueError, IndexError):
        raise Invalid("Choose what it is.") from None
    data = dict(kind.values)
    for c in cols:
        value = values.get(c["name"])
        if c["name"] == "_kind":
            continue
        if c["kind"] == "check":
            data[c["name"]] = _truthy(value)
        elif value not in (None, ""):
            data[c["name"]] = value
    return records.create(kind.type, data, user)


def _record_of(step, row_id):
    entity = records.live(row_id)
    if entity is None or entity.type not in {k.type for k in _kinds(step)}:
        abort(404, description="That record no longer exists.")
    return entity


def update_row(step, cols, row_id, name, value, user=None) -> None:
    """One field of a row, saved. A new kind is a new preset, or a new type
    where the record's type can become it (a router into a firewall)."""
    if step.save is not None:
        if step.update is None:
            raise Invalid("This can't be changed here; delete it and add it again.")
        step.update(row_id, {name: value}, user)
        return
    entity = _record_of(step, row_id)
    col = next((c for c in cols if c["name"] == name), None)
    if col is None:
        raise Invalid("That can't be changed here.")
    if name == "_kind":
        try:
            kind = _kinds(step)[int(value)]
        except (TypeError, ValueError, IndexError):
            raise Invalid("Choose what it is.") from None
        data = dict(kind.values)
        if kind.type != entity.type:
            data["type"] = kind.type
    else:
        data = {name: _truthy(value) if col["kind"] == "check" else value}
    records.update(entity, data, user)


def delete_row(step, row_id) -> dict:
    """A row, deleted; returns its Undo."""
    if step.save is not None:
        if step.delete is None:
            raise Invalid("This can't be deleted here.")
        return step.delete(row_id)
    entity = _record_of(step, row_id)
    gone = [entity] + (list(step.joined(entity)) if step.joined is not None else [])
    for e in gone:
        records.delete(e)
    if len(gone) > 1:
        return {"url": url_for("guide.tree_restore", key=step.key), "body": {"ids": [e.id for e in gone]}}
    return {"url": url_for("api.entity_restore", entity_id=entity.id), "body": {}}


def _new_hidden(step, cols) -> set:
    """The columns the blank row starts without: those that follow a value
    the first kind doesn't start with (a static address, while Dynamic)."""
    kinds = _kinds(step)
    if not kinds:
        return set()
    etype = registry().type(kinds[0].type)
    values = {f.key: f.default for f in etype.fields}
    values.update({n[2:]: v for n, v in kinds[0].values.items() if n.startswith("f.")})
    gone = {"f." + k for k in F.hidden_keys(etype.fields, values)}
    gone |= {c["name"] for c in cols if "only" in c and 0 not in c["only"]}
    starts = {c["name"]: False if c["kind"] == "check" else c.get("default", "") for c in cols}
    gone |= _not_followed(cols, starts, gone)
    return {c["name"] for c in cols if c["name"] in gone}


def _rows_html(step, scope) -> str:
    cols = columns(step, scope)
    rows = rows_of(step, cols, scope)
    after = Markup(step.after(scope)) if step.after is not None and rows else ""
    return render_template("partials/guide_rows.html", step=step, cols=cols, rows=rows, after=after,
                           scope=scope, new=not (step.scope and scope is not None), new_hidden=_new_hidden(step, cols),
                           site={"site": scope.id} if scope is not None else {})


# ———— Pages ————

def _url(key, scope, **args):
    if scope is not None:
        args["site"] = scope.id
    return url_for("guide.step", key=key, **args) if key != "done" else url_for("guide.done", **args)


def _page(html):
    """The guide on a page of its own, without the app around it."""
    return render_template("guide.html", page_html=Markup(html))


def _groups(steps) -> list[dict]:
    """The steps under their group headings, in order, each group with its
    ``plan``: what its steps cover, as the overview says it ("Site,
    buildings, rooms, and racks")."""
    out = []
    for n, s in enumerate(steps):
        if not out or out[-1]["label"] != s.group:
            out.append({"label": s.group, "steps": []})
        out[-1]["steps"].append((n, s))
    for g in out:
        words = [w.strip() for _, s in g["steps"] for w in (s.plan or s.title.lower()).split(",")]
        text = words[0] if len(words) == 1 else " and ".join(words) if len(words) == 2 else \
            ", ".join(words[:-1]) + ", and " + words[-1]
        g["plan"] = text[:1].upper() + text[1:]
    return out


@bp.route("/site-setup")
@role("editor")
def start():
    """What the guide covers, before its first step. A new install comes
    here straight from creating the admin account."""
    steps = _steps()
    if not steps:
        abort(404, description="No module has a setup step.")
    reg = registry()
    fresh = Entity.live().filter(Entity.type.in_(reg.enabled_type_keys())).first() is None
    seed = fresh and current_user.is_admin and any(m.seed for m in reg.enabled_modules())
    return _page(render_template("partials/guide.html", intro=True, done=False, steps=steps, groups=_groups(steps),
                                 scope=_scope(), fresh=fresh, seed=seed, url=_url))


@bp.route("/site-setup/done")
@role("editor")
def done():
    scope = _scope()
    summary = [{"step": s, "count": _count(s, scope)} for s in _steps() if not s.scope]
    reg = registry()
    diagram = reg.is_enabled("diagram") and reg.module("diagram") is not None
    # What modules offer to do with the site now: the knowledge base's runbook.
    finishes = [{"finish": f, "made": f.made(scope) if f.made else None}
                for f in reg.setup_finishes()] if scope is not None else []
    return _page(render_template("partials/guide.html", done=True, steps=_steps(), groups=_groups(_steps()),
                                 scope=scope, summary=summary, diagram=diagram, finishes=finishes, url=_url))


def _open(entity):
    """A record in the app, its sheet open over its module's list."""
    return url_for("main.module_list", module_id=entity.module, open=entity.id)


@bp.route("/site-setup/finish/<key>", methods=["POST"])
@role("editor")
def finish(key):
    """Do what a module offers on the last page (SetupFinish), for the site
    of ``?site=``, and open the record it made; one made before is opened."""
    scope = _scope()
    f = next((f for f in registry().setup_finishes() if f.key == key), None)
    if f is None or scope is None:
        abort(404, description="There is nothing to do for that site.")
    entity = f.made(scope) if f.made else None
    if entity is None:
        found = [{"group": s.group, "title": s.title, "records": _found(s, scope)}
                 for s in _steps() if not s.scope and s.save is None]
        try:
            entity = f.make(scope, [x for x in found if x["records"]], None)
        except Invalid as err:
            db.session.rollback()
            abort(400, description=str(err))
        db.session.commit()
    return redirect(_open(entity))


@bp.route("/site-setup/<key>/tree")
@role("editor")
def tree_part(key):
    """A tree step's tree alone, redrawn after each change."""
    current = _step_or_404(key)
    if not current.tree:
        abort(404)
    return _tree_html(current, _scope())


@bp.route("/site-setup/<key>/tree/<int:entity_id>/delete", methods=["POST"])
@role("editor")
def tree_delete(key, entity_id):
    """Delete a place of a tree step and the step's places in it (a building
    and its rooms), all at once; one Undo brings them all back."""
    current = _step_or_404(key)
    entity = records.live(entity_id)
    if not current.tree or entity is None or entity.type not in {k.type for k in _kinds(current)}:
        abort(404, description="There is no such place.")
    gone = _subtree(current, entity)
    for e in gone:
        records.delete(e)
    db.session.commit()
    return jsonify(ok=True, deleted=len(gone),
                   undo={"url": url_for("guide.tree_restore", key=key), "body": {"ids": [e.id for e in gone]}})


@bp.route("/site-setup/<key>/tree/<int:entity_id>/kind", methods=["POST"])
@role("editor")
def tree_kind(key, entity_id):
    """``type``: make a place of a tree step another of the step's kinds (a
    room that is really a building), all at once or not at all. It moves up
    to the nearest place above it that can hold the new kind (a building
    goes to the site), and the step's places in it that the new kind can't
    hold (a building's rooms, when it becomes a room) move out beside it.
    Anything else in it that can't stay (a rack in a room) refuses it."""
    current = _step_or_404(key)
    kinds = {k.type for k in _kinds(current)}
    entity = records.live(entity_id)
    if not current.tree or entity is None or entity.type not in kinds:
        abort(404, description="There is no such place.")
    reg = registry()
    new = reg.type(str(_body().get("type") or ""))
    if new is None or new.key not in kinds or new.key == entity.type:
        return jsonify(error="Choose another kind of place."), 400

    def fits(type_key, place):
        inside = reg.type(type_key).located_in
        return inside is None or place.type in inside
    place = entity.location
    while place is not None and not fits(new.key, place):
        place = place.location
    if place is None:
        return jsonify(error=f"Nothing above {entity.name} can hold a {new.text()}."), 400
    moved = [c for c in Entity.live().filter(Entity.location_id == entity.id, Entity.type.in_(kinds))
             if reg.type(c.type).located_in is not None and new.key not in reg.type(c.type).located_in]
    try:
        for c in moved:
            records.update(c, {"location_id": place.id}, current_user)
        records.update(entity, {"type": new.key, "location_id": place.id}, current_user)
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    db.session.commit()
    return jsonify(ok=True, moved=[c.name for c in moved])


@bp.route("/site-setup/<key>/tree/restore", methods=["POST"])
@role("editor")
def tree_restore(key):
    """Undo of a delete that took several records at once: ``tree_delete``
    (a building and its rooms), or a row with records joined to it (a MoCA
    pair). They come back where they were."""
    _step_or_404(key)
    ids = (request.get_json(silent=True) or {}).get("ids") or []
    for e in Entity.query.filter(Entity.id.in_([i for i in ids if isinstance(i, int)])):
        records.restore(e)
    db.session.commit()
    return jsonify(ok=True)


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _row_step(key):
    step = _step_or_404(key)
    if step.tree:
        abort(404)
    return step


@bp.route("/site-setup/<key>/rows")
@role("editor")
def rows_part(key):
    """A step's rows alone, redrawn after a row is added or deleted."""
    return _rows_html(_row_step(key), _scope())


@bp.route("/site-setup/<key>/rows", methods=["POST"])
@role("editor")
def row_create(key):
    """``values``: a new row's, by column. The site's own step answers with
    where to go next: the same step, about the new site."""
    step, scope = _row_step(key), _scope()
    try:
        made = create_row(step, columns(step, scope), _body().get("values") or {}, scope)
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    db.session.commit()
    if step.scope and made is not None:
        return jsonify(ok=True, go=_url(step.key, made))
    return jsonify(ok=True, notices=records.notices())


@bp.route("/site-setup/<key>/rows/<int:row_id>", methods=["POST"])
@role("editor")
def row_update(key, row_id):
    """``name`` and ``value``: one field of a row, saved. The answer has the
    value as kept (a subnet mask of /29 is kept as 255.255.255.248), for the
    row to show."""
    step, scope = _row_step(key), _scope()
    data, cols = _body(), columns(step, scope)
    name = str(data.get("name") or "")
    try:
        update_row(step, cols, row_id, name, data.get("value"))
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    db.session.commit()
    if step.save is None and name.startswith(("f.", "name")):
        kept = _row(step, cols, _record_of(step, row_id))["values"].get(name)
        return jsonify(ok=True, value=kept, notices=records.notices())
    return jsonify(ok=True, notices=records.notices())


@bp.route("/site-setup/<key>/rows/<int:row_id>/delete", methods=["POST"])
@role("editor")
def row_delete(key, row_id):
    try:
        undo = delete_row(_row_step(key), row_id)
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    db.session.commit()
    return jsonify(ok=True, undo=undo)


@bp.route("/site-setup/<key>")
@role("editor")
def step(key):
    steps = _steps()
    current = _step_or_404(key)
    index = steps.index(current)
    scope = _scope()
    body = (_tree_html(current, scope) if scope is not None else "") if current.tree else _rows_html(current, scope)
    extra = Markup(current.extra(scope)) if current.extra is not None else ""
    sites = _records_of({k.type for k in _kinds(current)}) if current.scope else []
    return _page(render_template(
        "partials/guide.html", done=False, steps=steps, groups=_groups(steps), step=current, index=index,
        scope=scope, body=Markup(body), sites=sites, extra=extra,
        back=steps[index - 1].key if index else None,
        following=steps[index + 1].key if index + 1 < len(steps) else "done", url=_url))
