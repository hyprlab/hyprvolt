"""The site setup guide: a site documented a step at a time, from the site
itself out to the endpoints and the cables between them.

The steps come from the turned-on modules (``Module.setup``, SetupStep in
manifest.py), in their ``order``: Locations asks for the site and its rooms,
Network for the internet connection and subnets, Hardware for the gear,
the servers and the endpoints, and so on. Each step is a short form of rows,
one record a row, with as many rows as the person wants; every row is made
through ``records.create``, as the record form would, and a step is saved
whole or not at all. The site chosen in the first step (``?site=``) is where
the later steps' records are placed by default.
"""
from flask import Blueprint, abort, redirect, render_template, request, url_for
from markupsafe import Markup

from ..models import db
from ..permissions import role
from ..registry import current as registry
from . import present, records, shell
from .fields import Invalid
from .models import Entity

bp = Blueprint("guide", __name__)

#: The most rows one save takes.
MAX_ROWS = 50


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
    """The site of ``?site=``; or, when there is one site, that one."""
    keys = [k.type for s in _steps() if s.scope for k in s.kinds]
    if not keys:
        return None
    given = records.live(request.args.get("site", type=int) or 0)
    if given is not None and given.type in keys:
        return given
    sites = Entity.live().filter(Entity.type.in_(keys)).limit(2).all()
    return sites[0] if len(sites) == 1 else None


def _places(scope) -> list[tuple[int, str]]:
    """The site and every location inside it, labeled with the path below
    the site: "Basement › Rack 1"."""
    if scope is None:
        return []
    location_types = [t.key for t in registry().location_types()]
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
    out = [(scope.id, scope.name)]
    for e in everything.values():
        p = path(e) if e.id != scope.id else None
        if p:
            out.append((e.id, " › ".join(p[1:])))
    return [out[0]] + sorted(out[1:], key=lambda o: o[1].lower())


def _inside(entity, scope, place_ids) -> bool:
    etype = registry().type(entity.type)
    if scope is None or etype is None or etype.located_in == ():
        return True
    return entity.location_id in place_ids or entity.id == scope.id


# ———— A step's columns ————

def _records_of(types) -> list[tuple[int, str]]:
    reg = registry()
    keys = [k for k in types if k in reg.enabled_type_keys()]
    rows = Entity.live().filter(Entity.type.in_(keys)).order_by(Entity.name).all() if keys else []
    return [(e.id, e.name) for e in rows]


def _field_choices(fields) -> list[tuple]:
    from .views import _ref_choices
    seen, out = set(), []
    for f in fields:
        for value, label in _ref_choices(f):
            if value not in seen:
                seen.add(value)
                out.append((value, label))
    return sorted(out, key=lambda c: str(c[1]).lower())


def columns(step, scope) -> list[dict]:
    """What each row asks for: {"name", "label", "kind" (text, number,
    select, check), "choices", "placeholder", "required", "default"}. A
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
               "required": False, "choices": None, "default": ""}
        if sf.name == "name":
            col.update(label=sf.label or "Name", kind="text", required=True)
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
            col["required"] = f.required and all(any(x.key == f.key for x in t.fields) for t in types)
            if f.kind == "select":
                col.update(kind="select", choices=list(f.options))
            elif f.kind == "ref":
                col.update(kind="select", choices=_field_choices(fields))
            elif f.kind in ("integer", "number"):
                col.update(kind="number", default=f.default if f.default is not None else "")
            elif f.kind == "boolean":
                col.update(kind="check")
            else:
                col["kind"] = "text"
        elif sf.name.startswith("s."):
            key = sf.name.split(".")[1]
            if not any(s.key == key for t in types for s in reg.form_sections(t)):
                continue
            if sf.types:
                choices = _records_of(sf.types)
                col.update(kind="select", choices=choices)
        elif sf.choices is not None:
            col.update(kind="select", choices=sf.choices(scope))
        cols.append(col)
    return cols


def _existing(step, scope) -> list:
    """What the step has made already, in this site: records, or for a step
    with its own save, lines of text."""
    if step.save is not None:
        return list(step.existing(scope)) if step.existing else []
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
    return present.views(out)


# ———— Saving a step ————

def _rows(form) -> list[dict]:
    """The rows sent: fields named "r<n>|<name>", in the order of n."""
    rows = {}
    for key, value in form.items(multi=False):
        head, sep, name = key.partition("|")
        if sep and head[:1] == "r" and head[1:].isdigit():
            rows.setdefault(int(head[1:]), {})[name] = value.strip()
    return [rows[n] for n in sorted(rows)][:MAX_ROWS]


def _filled(row, cols) -> bool:
    """A row counts once it has a name, or in a step of other rows (a
    cable), anything chosen or typed; what a row starts with (the site, the
    first kind) doesn't count."""
    if any(c["name"] == "name" for c in cols):
        return bool(row.get("name"))
    return any(row.get(c["name"]) and str(row.get(c["name"])) != str(c.get("default", ""))
               for c in cols if c["kind"] != "check" and c["name"] != "_kind")


def save(step, cols, rows, scope, user) -> list:
    """Make every filled row, or none: raises Invalid naming the row."""
    kinds = _kinds(step)
    made = []
    for n, row in enumerate(rows, 1):
        if not _filled(row, cols):
            continue
        try:
            if step.save is not None:
                step.save(row, scope, user)
                made.append(row)
                continue
            try:
                kind = kinds[int(row.get("_kind") or 0)]
            except (ValueError, IndexError):
                raise Invalid("Choose what it is.") from None
            data = dict(kind.values)
            for c in cols:
                if c["name"] == "_kind":
                    continue
                value = row.get(c["name"], "")
                if c["kind"] == "check":
                    data[c["name"]] = value in ("1", "on", "true")
                elif value != "":
                    data[c["name"]] = value
            made.append(records.create(kind.type, data, user))
        except Invalid as err:
            what = row.get("name") or f"row {n}"
            raise Invalid(f"{what[:1].upper()}{what[1:]}: {err}") from None
    return made


# ———— Pages ————

def _url(key, scope, **args):
    if scope is not None:
        args["site"] = scope.id
    return url_for("guide.step", key=key, **args) if key != "done" else url_for("guide.done", **args)


def _page(html, title="Set up a site"):
    from ..main import _admin_context      # the shell's settings window, as every page has
    return render_template("app.html", page="module", page_html=Markup(html), title=title,
                           **shell.context(special="guide"), **_admin_context())


@bp.route("/site-setup")
@role("editor")
def start():
    steps = _steps()
    if not steps:
        abort(404, description="No module has a setup step.")
    return redirect(url_for("guide.step", key=steps[0].key, **request.args))


@bp.route("/site-setup/done")
@role("editor")
def done():
    scope = _scope()
    summary = [{"step": s, "count": len(_existing(s, scope))} for s in _steps() if not s.scope]
    reg = registry()
    diagram = reg.is_enabled("diagram") and reg.module("diagram") is not None
    return _page(render_template("partials/guide.html", done=True, steps=_steps(), scope=scope,
                                 summary=summary, diagram=diagram, url=_url))


@bp.route("/site-setup/<key>", methods=["GET", "POST"])
@role("editor")
def step(key):
    steps = _steps()
    current = _step_or_404(key)
    index = steps.index(current)
    scope = _scope()
    cols = columns(current, scope)
    rows, error, count = None, "", 0
    if request.method == "POST":
        rows = _rows(request.form)
        chosen = records.live(request.form.get("existing", type=int) or 0) if current.scope else None
        try:
            made = save(current, cols, rows, scope, None)
        except Invalid as err:
            db.session.rollback()
            error = str(err)
        else:
            db.session.commit()
            if current.scope:
                scope = next((m for m in made if isinstance(m, Entity)), None) or chosen or scope
            if request.form.get("then") == "more":
                return redirect(_url(current.key, scope, added=len(made)))
            following = steps[index + 1].key if index + 1 < len(steps) else "done"
            return redirect(_url(following, scope))
    count = request.args.get("added", type=int) or 0
    choices = _records_of({k.type for k in _kinds(current)}) if current.scope else []
    return _page(render_template(
        "partials/guide.html", done=False, steps=steps, step=current, index=index, scope=scope, cols=cols,
        rows=rows or [{}], error=error, added=count, existing=_existing(current, scope), choices=choices,
        back=steps[index - 1].key if index else None,
        following=steps[index + 1].key if index + 1 < len(steps) else "done", url=_url))
