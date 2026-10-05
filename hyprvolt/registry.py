"""Finds the modules, checks their manifests, and wires them into the app.

Discovery imports every subpackage of the packages in ``MODULE_PACKAGES``
(``hyprvolt.modules`` in production) and takes its ``module`` attribute.
Nothing else has to be edited to add a module.

A manifest that fails validation is left out and its error is shown in
Settings > Modules; with ``MODULES_STRICT`` (the tests) it raises instead.
Its tables still exist, because its models were imported: a module that is
left out or turned off keeps its data.

Two orders matter and they are different on purpose:

* **Migration order** is fixed: modules sorted so that each comes after the
  modules it ``requires``, ties broken by id. It never depends on anything an
  admin can change, so an install always runs the same steps in the same
  order.
* **Sidebar order** is cosmetic: ``group`` and ``order``.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
import re
from pathlib import Path

from flask import Blueprint, Flask, abort, current_app, g, request
from jinja2 import ChoiceLoader, FileSystemLoader
from werkzeug.routing import BaseConverter

from .core.catalogs import CATALOGS
from .core.relations import CORE_KINDS
from .manifest import (FIELD_KINDS, IMPACTS, EntityType, Field, FormSection, Job, ListFilter, Module, Page,
                       Pane, RelationKind, SetupField, SetupFinish, SetupKind, SetupStep, Step, Tab, Widget)

log = logging.getLogger(__name__)

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
#: First path segments the core uses; a module mounted there would shadow it.
RESERVED = {"all", "e", "api", "admin", "search", "settings", "setup", "login", "logout",
            "register", "static", "healthz", "account", "attachments", "dashboard", "core"}
#: Names every entity already has; a type field can't reuse them.
CORE_FIELDS = {"id", "name", "slug", "status", "location", "location_id", "tags", "notes",
               "type", "module", "archived", "custom", "fields"}

EXTENSION = "hyprvolt.registry"
SETTING = "module:{}:enabled"


class ManifestError(Exception):
    pass


class Registry:
    def __init__(self):
        self.modules: dict[str, Module] = {}     # migration order
        self.errors: dict[str, str] = {}         # package or id -> why it was left out
        self.types: dict[str, EntityType] = {}
        self.kinds: dict[str, RelationKind] = {k.key: k for k in CORE_KINDS}

    # ———— Lookups ————

    def module(self, module_id: str) -> Module | None:
        return self.modules.get(module_id)

    def type(self, key: str) -> EntityType | None:
        return self.types.get(key)

    def sidebar_order(self, modules=None) -> list[Module]:
        """Modules by group, then within their group: in the order an admin
        set in Settings > Modules, and otherwise by each module's ``order``.
        Anything the saved order doesn't name (a new module, a new group)
        follows what it does, in the default order."""
        modules = list(self.modules.values()) if modules is None else modules
        saved_groups, saved_modules = self.saved_order()
        default = {}
        for m in sorted(self.modules.values(), key=lambda m: m.order):
            default.setdefault(m.group, len(default))

        def group_rank(group):
            return (0, saved_groups.index(group)) if group in saved_groups else (1, default.get(group, 0))

        def rank(m):
            own = (0, saved_modules.index(m.id)) if m.id in saved_modules else (1, m.order, m.name)
            return (group_rank(m.group), own)
        return sorted(modules, key=rank)

    def saved_order(self) -> tuple[list[str], list[str]]:
        """The sidebar's groups and modules as an admin ordered them, read
        once per request; two empty lists until one does."""
        if not _has_g():
            return [], []       # outside the app (a test of the registry alone)
        cached = g.get("_sidebar_order")
        if cached is not None:
            return cached
        import json
        from .models import get_setting
        out = []
        for key in ("sidebar:groups", "sidebar:modules"):
            try:
                value = json.loads(get_setting(key) or "[]")
            except ValueError:
                value = []
            out.append([x for x in value if isinstance(x, str)] if isinstance(value, list) else [])
        g._sidebar_order = (out[0], out[1])
        return g._sidebar_order

    # ———— Enabled or not ————

    def enabled_ids(self) -> set[str]:
        """The modules turned on, read once per request. Turned on unless an
        admin has turned them off, or turned off a module they require; a
        core module can't be."""
        cached = g.get("_enabled_modules") if _has_g() else None
        if cached is not None:
            return cached
        ids = self.switched_on()
        # Migration order puts requirements first, so one pass settles it.
        for mid, m in self.modules.items():
            if mid in ids and any(r not in ids for r in m.requires):
                ids.discard(mid)
        if _has_g():
            g._enabled_modules = ids
        return ids

    def switched_on(self) -> set[str]:
        """The modules whose own switch is on, whatever they require."""
        from .models import Setting
        off = {row.key.split(":")[1] for row in Setting.query.filter(Setting.key.like("module:%:enabled"))
               if row.value == "0"}
        return {mid for mid, m in self.modules.items() if m.core or mid not in off}

    def is_enabled(self, module_id: str) -> bool:
        return module_id in self.enabled_ids()

    def enabled_modules(self) -> list[Module]:
        on = self.enabled_ids()
        return self.sidebar_order([m for m in self.modules.values() if m.id in on])

    def enabled_types(self) -> list[EntityType]:
        return [t for m in self.enabled_modules() for t in m.types]

    def enabled_type_keys(self) -> list[str]:
        return [t.key for t in self.enabled_types()]

    def location_types(self) -> list[EntityType]:
        return [t for t in self.enabled_types() if t.location]

    def migration_steps(self):
        for m in self.modules.values():
            for step in m.migrations:
                yield m, step

    def sheet_tabs(self, entity) -> list[tuple[Module, Tab]]:
        """Module tabs for an entity: its type's own, then any a module adds
        to other modules' types."""
        tabs = []
        etype = self.type(entity.type)
        if etype:
            tabs += [(self.modules[etype.module], t) for t in etype.tabs]
        for m in self.enabled_modules():
            tabs += [(m, t) for t in m.sheet_tabs]
        return [(m, t) for m, t in tabs if t.when is None or t.when(entity)]

    def ref_types(self, f: Field) -> list[str]:
        """The type keys a ref field may point at: its types, then every
        type with its trait."""
        keys = list(f.types)
        if f.trait:
            keys += [k for k, t in self.types.items() if f.trait in t.traits and k not in keys]
        return keys

    def setup_steps(self) -> list[SetupStep]:
        """The site setup guide's steps from turned-on modules, in order."""
        return sorted((s for m in self.enabled_modules() for s in m.setup), key=lambda s: s.order)

    def setup_finishes(self) -> list[SetupFinish]:
        return [f for m in self.enabled_modules() for f in m.setup_finish]

    def form_sections(self, etype: EntityType) -> list[FormSection]:
        """What turned-on modules add to the form of ``etype``."""
        return [s for m in self.enabled_modules() for s in m.form_sections
                if s.when is None or s.when(etype)]


def _has_g() -> bool:
    from flask import has_app_context
    return has_app_context()


def current() -> Registry:
    return current_app.extensions[EXTENSION]


# ———— Discovery ————

def discover(packages, strict: bool = False) -> Registry:
    reg = Registry()
    found: list[Module] = []
    for package_name in packages:
        package = importlib.import_module(package_name)
        for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda i: i.name):
            if not info.ispkg or info.name.startswith("_"):
                continue
            full = f"{package_name}.{info.name}"
            try:
                manifest = getattr(importlib.import_module(full), "module", None)
                if not isinstance(manifest, Module):
                    raise ManifestError("it exports no `module = Module(...)`.")
                manifest.package = full
                found.append(manifest)
            except Exception as err:   # a broken module must not take the app down
                _fail(reg, full, err, strict)
    load(reg, found, strict)
    return reg


def load(reg: Registry, manifests: list[Module], strict: bool = False) -> Registry:
    """Validate manifests into ``reg``: each on its own first, then against
    each other, then in migration order."""
    accepted = []
    for m in manifests:
        problems = validate(m, reg)
        if problems:
            _fail(reg, m.id or m.package, ManifestError("; ".join(problems)), strict)
            continue
        _accept(reg, m)
        accepted.append(m)

    # Cross-module checks, repeated until stable: dropping one module can
    # leave another without something it requires.
    while True:
        dropped = False
        for m in list(accepted):
            problems = cross_check(m, reg)
            if problems:
                _fail(reg, m.id, ManifestError("; ".join(problems)), strict)
                _reject(reg, m)
                accepted.remove(m)
                dropped = True
        if not dropped:
            break

    try:
        ordered = migration_order(accepted)
    except ManifestError as err:
        for m in accepted:
            _reject(reg, m)
        _fail(reg, "modules", err, strict)
        ordered = []
    reg.modules = {m.id: m for m in ordered}
    return reg


def _fail(reg: Registry, name: str, err: Exception, strict: bool) -> None:
    if strict:
        raise ManifestError(f"{name}: {err}") from err
    reg.errors[name] = str(err)
    log.error("module %s left out: %s", name, err)


def _accept(reg: Registry, m: Module) -> None:
    reg.modules[m.id] = m
    for t in m.types:
        object.__setattr__(t, "module", m.id)
        reg.types[t.key] = t
    for k in m.relation_kinds:
        reg.kinds[k.key] = k


def _reject(reg: Registry, m: Module) -> None:
    reg.modules.pop(m.id, None)
    for t in m.types:
        reg.types.pop(t.key, None)
    for k in m.relation_kinds:
        reg.kinds.pop(k.key, None)


def validate(m: Module, reg: Registry) -> list[str]:
    """What is wrong with one manifest, on its own and against the modules
    already accepted. An empty list means it is fine."""
    p = []
    if not isinstance(m.id, str) or not ID_RE.match(m.id):
        return [f"the id {m.id!r} must be 2 to 31 lower-case letters, digits or underscores"]
    if m.id in RESERVED:
        p.append(f"the id {m.id!r} is reserved by the core")
    if m.id in reg.modules:
        p.append(f"the id {m.id!r} is already taken by {reg.modules[m.id].package}")
    if not (m.name or "").strip():
        p.append("it has no name")
    if m.icon and ("<script" in m.icon.lower() or re.search(r"\son\w+\s*=", m.icon)):
        p.append("the icon may only hold SVG shapes")

    seen_types = set()
    for t in m.types:
        if not isinstance(t, EntityType):
            p.append(f"{t!r} is not an EntityType")
            continue
        p += _check_type(t, reg, seen_types)
        seen_types.add(t.key)

    kinds = set()
    for k in m.relation_kinds:
        if not isinstance(k, RelationKind):
            p.append(f"{k!r} is not a RelationKind")
        elif k.key in reg.kinds or k.key in kinds:
            p.append(f"the relationship kind {k.key!r} already exists")
        elif k.impact not in IMPACTS:
            p.append(f"the relationship kind {k.key!r} has impact {k.impact!r}; use one of {', '.join(IMPACTS)}")
        kinds.add(getattr(k, "key", None))

    steps = set()
    for s in m.migrations:
        if not isinstance(s, Step) or not callable(s.run):
            p.append(f"{s!r} is not a Step")
        elif s.id in steps:
            p.append(f"the migration step {s.id!r} appears twice")
        steps.add(getattr(s, "id", None))

    for items, cls, what in ((m.filters, ListFilter, "filter"), (m.widgets, Widget, "widget"),
                             (m.jobs, Job, "job"), (m.sheet_tabs, Tab, "sheet tab"), (m.pages, Page, "page")):
        keys = set()
        for item in items:
            if not isinstance(item, cls):
                p.append(f"{item!r} is not a {cls.__name__}")
            elif item.key in keys:
                p.append(f"the {what} {item.key!r} appears twice")
            keys.add(getattr(item, "key", None))
    others = {s.key for o in reg.modules.values() for s in o.form_sections}
    for section in m.form_sections:
        if not isinstance(section, FormSection) or not callable(section.render) or not callable(section.save):
            p.append(f"{section!r} is not a FormSection with render and save functions")
        elif not ID_RE.match(section.key or ""):
            p.append(f"the form section key {section.key!r} must be lower-case letters, digits or underscores")
        elif section.key in others:
            p.append(f"the form section {section.key!r} already exists")
        others.add(getattr(section, "key", None))
    own = {t.key for t in m.types if isinstance(t, EntityType)}
    others = {s.key for o in reg.modules.values() for s in o.setup}
    for finish in m.setup_finish:
        if not isinstance(finish, SetupFinish) or not callable(finish.make) or not ID_RE.match(finish.key or ""):
            p.append(f"{finish!r} is not a SetupFinish with a lower-case key and a make function")
    for step in m.setup:
        if not isinstance(step, SetupStep):
            p.append(f"{step!r} is not a SetupStep")
            continue
        if not ID_RE.match(step.key or "") or step.key in others:
            p.append(f"the setup step {step.key!r} needs a lower-case key no other step has")
        others.add(step.key)
        if bool(step.kinds) == (step.save is not None):
            p.append(f"the setup step {step.key!r} needs either kinds of record or a save function")
        elif step.save is not None and not callable(step.rows):
            p.append(f"the setup step {step.key!r} saves rows of its own, so it needs a rows function")
        for k in step.kinds:
            if not isinstance(k, SetupKind) or k.type not in own:
                p.append(f"the setup step {step.key!r} makes {getattr(k, 'type', k)!r}, not one of the module's types")
        if not all(isinstance(f, SetupField) for f in step.fields):
            p.append(f"the setup step {step.key!r} has a field that is not a SetupField")
    for page in m.pages:
        if isinstance(page, Page) and (not ID_RE.match(page.key or "") or not callable(page.render)):
            p.append(f"the page {page.key!r} needs a lower-case key and a render function")
    for job in m.jobs:
        if isinstance(job, Job) and job.minutes < 1:
            p.append(f"the job {job.key!r} must run at most every minute")
    if m.settings_pane is not None and not isinstance(m.settings_pane, Pane):
        p.append("settings_pane is not a Pane")
    if m.search is not None and not callable(m.search):
        p.append("search is not callable")
    if m.seed is not None and not callable(m.seed):
        p.append("seed is not callable")
    if m.blueprint is not None:
        p += _check_blueprint(m, reg)
    return p


def _check_type(t: EntityType, reg: Registry, siblings: set) -> list[str]:
    p = []
    if not isinstance(t.key, str) or not ID_RE.match(t.key):
        return [f"the type key {t.key!r} must be 2 to 31 lower-case letters, digits or underscores"]
    if t.key in reg.types or t.key in siblings:
        p.append(f"the type {t.key!r} already exists")
    if not t.label or not t.plural:
        p.append(f"the type {t.key!r} needs a label and a plural")
    if not t.statuses or any(not isinstance(s, tuple) or len(s) != 2 for s in t.statuses):
        p.append(f"the type {t.key!r} needs statuses as (value, label) pairs")
    if any(isinstance(f, Field) and not f.relation for f in t.fields) and t.detail is None:
        p.append(f"the type {t.key!r} has fields but no detail model to keep them in")
    if not isinstance(t.traits, tuple) or not all(isinstance(x, str) for x in t.traits):
        p.append(f"the traits of {t.key!r} must be a tuple of words")
    if t.name_from and t.name_from not in {getattr(f, "key", None) for f in t.fields}:
        p.append(f"the type {t.key!r} takes its name from {t.name_from!r}, which is not one of its fields")
    if t.check is not None and not callable(t.check):
        p.append(f"the check of {t.key!r} is not callable")
    if t.overview is not None and not callable(t.overview):
        p.append(f"the overview of {t.key!r} is not callable")
    columns = set()
    if t.detail is not None:
        table = getattr(t.detail, "__table__", None)
        if table is None or "entity_id" not in table.c:
            p.append(f"the detail model of {t.key!r} must be a table keyed by entity_id (use EntityDetail)")
        else:
            columns = set(table.c.keys())
    keys = set()
    for f in t.fields:
        if not isinstance(f, Field):
            p.append(f"{f!r} in {t.key!r} is not a Field")
            continue
        where = f"the field {t.key}.{f.key}"
        if not FIELD_RE.match(f.key or ""):
            p.append(f"{where} needs a lower-case key")
        if f.key in CORE_FIELDS:
            p.append(f"{where} reuses a name every entity already has")
        if f.key in keys:
            p.append(f"{where} appears twice")
        keys.add(f.key)
        if f.kind not in FIELD_KINDS:
            p.append(f"{where} has the unknown kind {f.kind!r}")
        if f.kind == "select" and not f.options:
            p.append(f"{where} is a select with no options")
        if f.groups and (f.kind != "select" or not {v for _, values in f.groups for v in values}
                         <= {v for v, _ in f.options}):
            p.append(f"{where} groups its options, so it must be a select and group only options it has")
        if f.kind == "ref" and not f.types and not f.trait:
            p.append(f"{where} is a ref that names no types and no trait")
        if f.remind is not None and (not callable(f.remind) or not f.expires):
            p.append(f"{where} has a remind that isn't a function of an expiring date")
        if f.suggest and (f.kind != "text" or f.suggest not in CATALOGS):
            p.append(f"{where} suggests names, so it must be text and name a catalog in core/catalogs.py")
        if f.prefills and f.kind != "cidr":
            p.append(f"{where} fills in other fields from a subnet, so it must be a cidr")
        if f.switch and (f.kind != "boolean" or len(f.switch) != 2):
            p.append(f"{where} is a switch, so it must be a boolean with an off and an on label")
        if f.shown_when and (len(f.shown_when) != 2 or f.shown_when[0] not in keys):
            p.append(f"{where} is shown when another field has a value; name one of the type's fields before it")
        if f.hides and (f.kind != "select" or any(not set(when) <= {v for v, _ in f.options} | {""}
                                                  for _, when in f.hide_rules())):
            p.append(f"{where} hides form sections, so it must be a select and hides_when some of its options "
                     "(or \"\" for none chosen)")
        if f.relation and f.kind != "ref":
            p.append(f"{where} is kept as a link, so it must be a ref")
        if f.also and f.kind != "ref":
            p.append(f"{where} has choices besides records, so it must be a ref")
        if columns and f.key not in columns and (not f.relation or f.also):
            p.append(f"{where} has no column in {t.detail.__tablename__}")
    tabs = set()
    for tab in t.tabs:
        if not isinstance(tab, Tab) or not callable(tab.render):
            p.append(f"a tab of {t.key!r} is not a Tab with a render function")
        elif tab.key in tabs:
            p.append(f"the tab {tab.key!r} of {t.key!r} appears twice")
        tabs.add(getattr(tab, "key", None))
    return p


def _check_blueprint(m: Module, reg: Registry) -> list[str]:
    bp = m.blueprint
    if not isinstance(bp, Blueprint):
        return ["blueprint is not a Flask Blueprint"]
    if bp.name != m.id:
        return [f"the blueprint must be named {m.id!r}, like the module"]
    # Register it on a scratch app to see its views before the real one does:
    # a view with no role is refused here, not discovered in production.
    from .permissions import undeclared_routes
    scratch = Flask("manifest-check")
    try:
        scratch.register_blueprint(bp, url_prefix=f"/{m.id}")
    except Exception as err:
        return [f"its blueprint can't be registered: {err}"]
    missing = undeclared_routes(scratch, prefix=f"{m.id}.")
    if missing:
        return ["these routes declare no role (add @role(...)): " + ", ".join(missing)]
    return []


def cross_check(m: Module, reg: Registry) -> list[str]:
    p = []
    for need in m.requires:
        if need not in reg.modules:
            p.append(f"it requires the module {need!r}, which is not loaded")
    for t in m.types:
        for f in t.fields:
            for target in f.types:
                if target not in reg.types:
                    p.append(f"the field {t.key}.{f.key} points at the unknown type {target!r}")
            if f.relation and f.relation not in reg.kinds:
                p.append(f"the field {t.key}.{f.key} is kept as the unknown link kind {f.relation!r}")
        for key in t.becomes:
            other = reg.types.get(key)
            if other is None:
                p.append(f"{t.key!r} becomes the unknown type {key!r}")
            elif other.module != t.module or other.detail is not t.detail or other.name_from != t.name_from:
                p.append(f"{t.key!r} becomes {key!r}, which is kept differently (module, detail or name)")
        for parent in t.located_in or ():
            other = reg.types.get(parent)
            if other is None:
                p.append(f"{t.key!r} may be located in the unknown type {parent!r}")
            elif not other.location:
                p.append(f"{t.key!r} may be located in {parent!r}, which is not a location type")
    return p


def migration_order(modules: list[Module]) -> list[Module]:
    """Each module after the ones it requires; among those ready at any
    point, the lowest id first. A newcomer never reorders the modules already
    there relative to each other, since none of them can require it."""
    by_id = {m.id: m for m in modules}
    waiting = {m.id: {r for r in m.requires if r in by_id} for m in modules}
    ready = sorted(i for i, needs in waiting.items() if not needs)
    ordered = []
    while ready:
        mid = ready.pop(0)
        ordered.append(by_id[mid])
        del waiting[mid]
        for other, needs in waiting.items():
            if mid in needs:
                needs.discard(mid)
                if not needs:
                    ready.append(other)
        ready.sort()
    if waiting:
        raise ManifestError("the modules require each other in a circle: " + ", ".join(sorted(waiting)))
    return ordered


# ———— Wiring ————

def init_app(app: Flask, reg: Registry) -> None:
    app.extensions[EXTENSION] = reg

    class ModuleConverter(BaseConverter):
        # Only a known module id matches /<module:mod>, so the generic list
        # route never swallows another path.
        regex = "(?:" + "|".join(re.escape(i) for i in sorted(reg.modules, key=len, reverse=True)) + ")" \
            if reg.modules else "(?!x)x"

    app.url_map.converters["module"] = ModuleConverter

    loaders = [app.jinja_loader]
    for m in reg.modules.values():
        folder = Path(importlib.import_module(m.package).__file__).parent / "templates" if m.package else None
        if folder and folder.is_dir():
            loaders.append(FileSystemLoader(str(folder)))
        if m.blueprint is not None:
            app.register_blueprint(m.blueprint, url_prefix=f"/{m.id}")
    app.jinja_loader = ChoiceLoader(loaders)

    @app.before_request
    def hide_disabled_modules():
        # A turned-off module's own pages and API answer as if it weren't
        # installed. Its data is untouched.
        if request.blueprint in reg.modules and not reg.is_enabled(request.blueprint):
            abort(404)
