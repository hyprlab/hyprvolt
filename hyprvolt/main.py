"""The pages and the palette search.

Two shapes of route live here:

* Pages render the shell (sidebar, topbar, records, dialogs): the dashboard
  at ``/``, one list per module at ``/<module>``, and every record at
  ``/all``. Filters, sort and view are query parameters, so every screen has
  a URL and the back button works. With ``partial=1`` a list returns only the
  records, which is how "Load more" and infinite scroll page: one renderer
  for the list, not a second one in JavaScript.
* Everything else answers JSON to ``fetch`` calls from ``static/js/app.js``,
  behind the session CSRF check in the app factory. Failures return
  ``{"error": "..."}`` with a 4xx status, written for the person reading it.

The records' own JSON API is ``core/api.py``; the sheet and form fragments
are ``core/views.py``. Admin routes are grouped at the end, each behind
``@role("admin")``.
"""
from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from markupsafe import Markup
from sqlalchemy import func

from . import __version__
from .auth import EMAIL_RE, MIN_PASSWORD, siteverify, turnstile_config
from .core import present, shell
from .core.api import like
from .core.models import Entity, Tag
from .models import User, db, get_setting, int_setting, set_setting
from .permissions import ROLES, public, role
from .registry import current as registry

bp = Blueprint("main", __name__)

VIEWS = ("cards", "list")
SORTS = {
    "updated": ("Recently changed", lambda: Entity.updated_at.desc()),
    "name": ("Name, A to Z", lambda: func.lower(Entity.name).asc()),
    "newest": ("Newest first", lambda: Entity.created_at.desc()),
    "oldest": ("Oldest first", lambda: Entity.created_at.asc()),
}


# ———— Health ————

@bp.route("/healthz")
@public
def healthz():
    """Liveness probe for Docker and any proxy in front of it.

    Outside the sign-in requirement and the setup gate, and it touches the
    database, so a healthy answer means the app can serve, not just that the
    port is open.
    """
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:
        return jsonify(ok=False), 503
    return jsonify(ok=True, version=__version__)


# ———— The dashboard ————

@bp.route("/")
@role("viewer")
def index():
    reg = registry()
    counts = shell.type_counts()
    tiles = [{"module": m, "count": sum(counts.get(t.key, 0) for t in m.types),
              "types": [(t, counts.get(t.key, 0)) for t in m.types]}
             for m in reg.enabled_modules() if m.types]
    recent = (Entity.live().filter(Entity.type.in_(reg.enabled_type_keys()))
              .order_by(Entity.updated_at.desc(), Entity.id.desc()).limit(10).all())
    widgets = []
    for m in reg.enabled_modules():
        for w in m.widgets:
            widgets.append({"module": m, "widget": w, "html": Markup(w.render())})
    return render_template("app.html", page="dashboard", tiles=tiles, recent=present.views(recent),
                           widgets=widgets, view="list", can_seed=any(m.seed for m in reg.enabled_modules()),
                           **shell.context(special="dashboard"),
                           **_admin_context())


# ———— Lists ————

def _list_args(module=None):
    reg = registry()
    args = request.args
    type_key = args.get("type") or None
    etype = reg.type(type_key) if type_key else None
    if etype is not None and ((module is not None and etype.module != module.id)
                              or not reg.is_enabled(etype.module)):
        etype = None
    flt = None
    if module and args.get("f"):
        flt = next((f for f in module.filters if f.key == args["f"]), None)
    sort = args.get("sort") if args.get("sort") in SORTS else "updated"
    view = args.get("view") if args.get("view") in VIEWS else current_user.view_mode
    return {
        "etype": etype, "filter": flt, "sort": sort, "view": view if view in VIEWS else "cards",
        "tag": (args.get("tag") or "").strip() or None,
        "q": (args.get("q") or "").strip()[:200] or None,
        "status": (args.get("status") or "").strip() or None,
        "location": args.get("location", type=int),
        "archived": args.get("archived") == "1",
        "deleted": args.get("deleted") == "1" and current_user.can_edit,
        "page_no": max(1, args.get("page", type=int) or 1),
    }


def _list_query(module, a):
    reg = registry()
    keys = [t.key for t in module.types] if module else reg.enabled_type_keys()
    if a["etype"]:
        keys = [a["etype"].key]
    query = Entity.query.filter(Entity.type.in_(keys))
    if a["deleted"]:
        query = query.filter(Entity.deleted_at.isnot(None))
    else:
        query = query.filter(Entity.deleted_at.is_(None), Entity.archived.is_(a["archived"]))
    if a["filter"]:
        query = a["filter"].apply(query)
    if a["tag"]:
        query = query.filter(Entity.tags.any(func.lower(Tag.name) == a["tag"].lower()))
    if a["status"]:
        query = query.filter(Entity.status == a["status"])
    if a["location"]:
        query = query.filter(Entity.location_id == a["location"])
    if a["q"]:
        query = query.filter(Entity.search_text.like(like(a["q"]), escape="\\"))
    order = Entity.deleted_at.desc() if a["deleted"] else SORTS[a["sort"]][1]()
    return query.order_by(order, Entity.id.desc())


def _render_list(module):
    a = _list_args(module)
    per_page = int_setting("items_per_page", 40)
    rows = _list_query(module, a).limit(per_page + 1).offset((a["page_no"] - 1) * per_page).all()
    has_more = len(rows) > per_page
    context = dict(items=present.views(rows[:per_page]), has_more=has_more, module=module, sorts=SORTS,
                   page="list", **a)
    if request.args.get("partial") == "1":
        return render_template("partials/records.html", **context)
    title = (a["etype"].plural if a["etype"] else module.name if module else
             "Recently deleted" if a["deleted"] else "All records")
    if a["archived"]:
        title = "Archived " + (title.lower() if module or a["etype"] else "records")
    if a["filter"]:
        title = a["filter"].label
    context["title"] = title
    context["location_entity"] = db.session.get(Entity, a["location"]) if a["location"] else None
    special = "deleted" if a["deleted"] else ("all" if module is None and not a["tag"] else None)
    return render_template("app.html", **context,
                           **shell.context(active_module=module, active_type=a["etype"].key if a["etype"] else None,
                                           active_filter=a["filter"].key if a["filter"] else None,
                                           active_tag=a["tag"], special=special),
                           **_admin_context())


@bp.route("/all")
@role("viewer")
def all_records():
    return _render_list(None)


@bp.route("/<module:module_id>")
@role("viewer")
def module_list(module_id):
    reg = registry()
    if not reg.is_enabled(module_id) or not reg.module(module_id).types:
        abort(404)
    return _render_list(reg.module(module_id))


@bp.route("/e/<int:entity_id>")
@role("viewer")
def entity_link(entity_id):
    """A stable link to a record: its module's list with the sheet open.
    This is what [[slug]] links, copied links and labels point at."""
    entity = db.session.get(Entity, entity_id)
    if entity is None or not registry().type(entity.type) or not registry().is_enabled(entity.module):
        abort(404)
    return redirect(url_for("main.module_list", module_id=entity.module, open=entity.id))


def _admin_context() -> dict:
    """What the Admin section needs. Empty for anyone else, so the queries never
    run for an ordinary account."""
    if not current_user.is_admin:
        return {}
    return {
        "admin_users": User.query.order_by(User.created_at).all(),
        "admin_stats": {"users": User.query.count(),
                        "records": Entity.query.filter(Entity.deleted_at.is_(None)).count()},
        "inst_worker": int_setting("worker_minutes", 15),
        "inst_per_page": int_setting("items_per_page", 40),
        "inst_purge_days": int_setting("purge_days", 30),
        "inst_upload_mb": int_setting("max_upload_mb", 25),
        "inst_default_role": default_role(),
        "turnstile": _turnstile_status(),
        **_modules_context(),
    }


CUSTOM_KIND_LABELS = {"text": "Text", "number": "Number", "date": "Date", "select": "Choice list",
                      "url": "Web address", "boolean": "Yes or no"}


def _modules_context() -> dict:
    """Settings > Modules and Settings > Custom fields."""
    from .core.models import CustomField
    reg = registry()
    counts = shell.type_counts()
    enabled = reg.enabled_ids()
    modules = [{"module": m, "enabled": m.id in enabled,
                "needs": [reg.module(r).name for r in m.requires if r not in enabled],
                "count": sum(counts.get(t.key, 0) for t in m.types)} for m in reg.sidebar_order()]
    fields: dict[str, list] = {}
    for cf in CustomField.query.order_by(CustomField.position, CustomField.id):
        fields.setdefault(cf.entity_type, []).append(cf)
    return {"admin_modules": modules, "admin_module_errors": sorted(reg.errors.items()),
            "admin_custom_fields": fields, "custom_kind_labels": CUSTOM_KIND_LABELS}


# ———— Search (the Ctrl/Cmd+K palette) ————

@bp.route("/search")
@role("viewer")
def search():
    """Records whose name, slug, notes, tags or field values contain the
    query, grouped by module, then whatever each module's own search adds.
    ``pick=1`` (choosing a record for a link) returns records only, limited to
    ``types``."""
    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        return jsonify(groups=[])
    reg = registry()
    keys = reg.enabled_type_keys()
    if request.args.get("types"):
        keys = [k for k in request.args["types"].split(",") if k in keys]
    rows = (Entity.live().filter(Entity.type.in_(keys))
            .filter(Entity.search_text.like(like(query), escape="\\"))
            .order_by(Entity.archived.asc(), (func.lower(Entity.name) == query.lower()).desc(),
                      Entity.updated_at.desc())
            .limit(30).all())
    exclude = request.args.get("exclude", type=int)
    groups, by_module = [], {}
    for e in rows:
        if e.id == exclude:
            continue
        etype = reg.type(e.type)
        if e.module not in by_module:
            by_module[e.module] = {"label": reg.module(e.module).name, "items": []}
            groups.append(by_module[e.module])
        meta = etype.label
        path = present.path_label(e.location_id) if e.location_id else ""
        by_module[e.module]["items"].append({
            "id": e.id, "title": e.name, "type": e.type,
            "meta": f"{meta} · {path}" if path else meta, "archived": e.archived,
        })
    if request.args.get("pick") != "1":
        for m in reg.enabled_modules():
            if m.search is None:
                continue
            found = m.search(query, 10) or []
            if found:
                groups.append({"label": m.name, "items": [
                    {"id": r.entity_id, "url": r.url, "title": r.title, "meta": r.meta} for r in found]})
    return jsonify(groups=groups)


# ———— Account ————

@bp.route("/settings", methods=["POST"])
@role("viewer")
def settings():
    data = request.get_json(silent=True) or {}
    if "name" in data:
        current_user.name = (data.get("name") or "").strip()[:120] or None
    if data.get("theme") in ("system", "light", "dark"):
        current_user.theme = data["theme"]
    if data.get("view_mode") in VIEWS:
        current_user.view_mode = data["view_mode"]
    if "infinite_scroll" in data:
        current_user.infinite_scroll = bool(data["infinite_scroll"])
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/account/password", methods=["POST"])
@role("viewer")
def change_password():
    data = request.get_json(silent=True) or {}
    if not current_user.check_password(data.get("current", "")):
        return jsonify(error="Current password is wrong."), 403
    new = data.get("new", "")
    if len(new) < MIN_PASSWORD:
        return jsonify(error=f"New passwords need at least {MIN_PASSWORD} characters."), 400
    current_user.set_password(new)
    db.session.commit()
    return jsonify(ok=True)


# ———— Admin ————

def default_role() -> str:
    """The role a new account gets: from sign-up, or from Add user when none
    is chosen."""
    stored = get_setting("default_role")
    return stored if stored in ("viewer", "editor") else "viewer"


INSTANCE_SETTINGS = {
    # key: (lowest, highest, how the error names it)
    "worker_minutes": (0, 1440, "The background interval"),
    "items_per_page": (10, 500, "The page size"),
    "purge_days": (1, 365, "How long deleted records are kept"),
    "max_upload_mb": (1, 2048, "The upload limit"),
}


@bp.route("/admin/instance", methods=["POST"])
@role("admin")
def admin_instance():
    data = request.get_json(silent=True) or {}
    for key, (low, high, label) in INSTANCE_SETTINGS.items():
        if key not in data:
            continue
        try:
            value = int(data[key])
        except (TypeError, ValueError):
            return jsonify(error=f"{label} must be a number."), 400
        if not low <= value <= high:
            return jsonify(error=f"{label} must be between {low} and {high}."), 400
        set_setting(key, str(value))
    if "default_role" in data:
        if data["default_role"] not in ("viewer", "editor"):
            return jsonify(error="New accounts can start as viewers or editors."), 400
        set_setting("default_role", data["default_role"])
    return jsonify(ok=True)


@bp.route("/admin/registration", methods=["POST"])
@role("admin")
def admin_registration():
    open_ = bool((request.get_json(silent=True) or {}).get("open"))
    set_setting("registration_open", "1" if open_ else "0")
    return jsonify(ok=True, open=open_)


def _turnstile_status() -> dict:
    """What the Security section shows. The secret never leaves the server;
    only its last four characters do, so an admin can tell which one is saved."""
    config = turnstile_config()
    stored_site = get_setting("turnstile_site_key") or ""
    stored_secret = get_setting("turnstile_secret_key") or ""
    return {
        "on": config is not None,
        "source": config["source"] if config else None,
        "site_key": config["site_key"] if config else stored_site,
        "secret_hint": (config["secret_key"] if config else stored_secret)[-4:],
    }


@bp.route("/admin/turnstile", methods=["POST"])
@role("admin")
def admin_turnstile():
    """Turn Turnstile on, or change its keys.

    Only after the admin has passed a challenge rendered with the new site key
    and Cloudflare has accepted the answer with the new secret. That proves the
    two keys belong together and that this address is allowed for the widget;
    a wrong pair saved blindly would lock everyone, the admin included, out of
    sign-in.
    """
    data = request.get_json(silent=True) or {}
    site_key = (data.get("site_key") or "").strip()
    secret_key = (data.get("secret_key") or "").strip()
    if not site_key:
        return jsonify(error="Enter the site key."), 400
    if not secret_key:
        # Blank keeps the secret already in force, so changing only the site
        # key doesn't mean pasting the secret again.
        current = turnstile_config() or {}
        secret_key = current.get("secret_key") or get_setting("turnstile_secret_key") or ""
        if not secret_key:
            return jsonify(error="Enter the secret key."), 400
    if len(site_key) > 200 or len(secret_key) > 200:
        return jsonify(error="That doesn't look like a Turnstile key."), 400
    ok, why = siteverify(secret_key, data.get("token") or "")
    if not ok:
        return jsonify(error=why), 400
    set_setting("turnstile_site_key", site_key)
    set_setting("turnstile_secret_key", secret_key)
    set_setting("turnstile_enabled", "1")
    return jsonify(ok=True, status=_turnstile_status())


@bp.route("/admin/turnstile/disable", methods=["POST"])
@role("admin")
def admin_turnstile_disable():
    """Turn Turnstile off. The keys stay saved, so turning it back on is one
    challenge away. The stored "off" also overrides TURNSTILE_* variables."""
    set_setting("turnstile_enabled", "0")
    return jsonify(ok=True, status=_turnstile_status())


@bp.route("/admin/users", methods=["POST"])
@role("admin")
def admin_create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    if len(username) > 80 or not EMAIL_RE.match(username):
        return jsonify(error="Enter a valid email address."), 400
    if len(password) < MIN_PASSWORD:
        return jsonify(error=f"Passwords need at least {MIN_PASSWORD} characters."), 400
    if User.query.filter(func.lower(User.username) == username).first():
        return jsonify(error="An account with that email already exists."), 409
    new_role = data.get("role") or default_role()
    if new_role not in ROLES:
        return jsonify(error="Choose viewer, editor or admin."), 400
    user = User(username=username, role=new_role,
                name=(data.get("name") or "").strip()[:120] or None)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify(ok=True, id=user.id)


@bp.route("/admin/users/<int:user_id>/password", methods=["POST"])
@role("admin")
def admin_reset_password(user_id):
    user = db.get_or_404(User, user_id)
    new = (request.get_json(silent=True) or {}).get("new", "")
    if len(new) < MIN_PASSWORD:
        return jsonify(error=f"Passwords need at least {MIN_PASSWORD} characters."), 400
    user.set_password(new)
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/admin/users/<int:user_id>/role", methods=["POST"])
@role("admin")
def admin_set_role(user_id):
    user = db.get_or_404(User, user_id)
    new_role = (request.get_json(silent=True) or {}).get("role")
    if new_role not in ROLES:
        return jsonify(error="Choose viewer, editor or admin."), 400
    if user.id == current_user.id:
        return jsonify(error="You can't change your own role."), 400
    user.role = new_role
    db.session.commit()
    return jsonify(ok=True, role=user.role)


@bp.route("/admin/users/<int:user_id>/secrets", methods=["POST"])
@role("admin")
def admin_set_secrets(user_id):
    """Grant or take away access to the secrets vault, admins included."""
    user = db.get_or_404(User, user_id)
    user.can_see_secrets = bool((request.get_json(silent=True) or {}).get("allowed"))
    db.session.commit()
    return jsonify(ok=True, allowed=user.can_see_secrets)


@bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@role("admin")
def admin_delete_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        return jsonify(error="You can't delete your own account from here."), 400
    # The documentation they wrote belongs to the instance and stays; the
    # history keeps their name as it was.
    db.session.delete(user)
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/admin/modules/<module_id>", methods=["POST"])
@role("admin")
def admin_module(module_id):
    """Turn a module on or off. Off hides it everywhere and keeps its data,
    and turns off the modules that require it; a built-in module can't be
    turned off."""
    module = registry().module(module_id)
    if module is None:
        return jsonify(error="There is no such module."), 404
    on = bool((request.get_json(silent=True) or {}).get("enabled"))
    if module.core and not on:
        return jsonify(error=f"{module.name} is built in and can't be turned off."), 400
    off = [registry().module(r).name for r in module.requires if not registry().is_enabled(r)]
    if on and off:
        return jsonify(error=f"{module.name} needs {' and '.join(off)}. Turn that on first."), 400
    set_setting(f"module:{module.id}:enabled", "1" if on else "0")
    return jsonify(ok=True, enabled=on)


@bp.route("/admin/seed-demo", methods=["POST"])
@role("admin")
def admin_seed_demo():
    """The dashboard's Load a demo homelab, for an empty instance only."""
    from .demo import DemoError, seed_for_request
    try:
        made = seed_for_request()
    except DemoError as err:
        return jsonify(error=str(err)), 409
    return jsonify(ok=True, records=made)
