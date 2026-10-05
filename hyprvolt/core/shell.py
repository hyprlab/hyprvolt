"""The shell around every page: the sidebar with its live counts, the "New"
menu, and the settings sections modules add. One call, ``context()``, so the
dashboard and every list render the same frame.
"""
from flask import url_for
from flask_login import current_user
from sqlalchemy import func

from ..models import db
from ..registry import current as registry
from . import access
from .api import tag_counts
from .models import Entity


def type_counts() -> dict[str, int]:
    """Live, unarchived entities per type."""
    rows = access.visible(db.session.query(Entity.type, func.count(Entity.id)).filter(
        Entity.deleted_at.is_(None), Entity.archived.is_(False))).group_by(Entity.type).all()
    return dict(rows)


def module_query(module, archived: bool = False):
    """Live entities of one module, as its sidebar filters see them."""
    query = Entity.live().filter(Entity.type.in_([t.key for t in module.types]))
    return query.filter(Entity.archived.is_(archived))


def context(active_module=None, active_type=None, active_filter=None, active_tag=None,
            special=None, active_page=None) -> dict:
    reg = registry()
    counts = type_counts()
    groups, by_group = [], {}
    for m in reg.enabled_modules():
        pages = [p for p in m.pages if p.sidebar]
        if not m.types and not pages:
            continue    # a module of tabs and panes only (the vault) has no place here
        active = active_module is not None and m.id == active_module.id
        entry = {
            "module": m,
            "count": sum(counts.get(t.key, 0) for t in m.types),
            "active": active,
            "href": url_for("main.module_list", module_id=m.id) if m.types else
            url_for("main.module_page", module_id=m.id, key=pages[0].key),
            "types": [],
            "filters": [],
            # A module of pages alone is one link: its first page.
            "pages": [{"page": p, "active": active and active_page == p.key}
                      for p in pages] if active and (m.types or len(pages) > 1) else [],
            "on_page": active and active_page is not None,
        }
        if entry["active"]:
            if len(m.types) > 1:
                entry["types"] = [{"type": t, "count": counts.get(t.key, 0),
                                   "active": active_type == t.key} for t in m.types]
            for f in m.filters:
                entry["filters"].append({"filter": f, "count": f.apply(module_query(m)).count(),
                                         "active": active_filter == f.key})
            entry["archived"] = module_query(m, archived=True).count() if m.types else 0
        if m.group not in by_group:
            by_group[m.group] = {"label": m.group, "modules": []}
            groups.append(by_group[m.group])
        by_group[m.group]["modules"].append(entry)

    keys = reg.enabled_type_keys()
    deleted = 0
    if current_user.can_edit:
        deleted = access.visible(Entity.query.filter(Entity.deleted_at.isnot(None), Entity.type.in_(keys))).count()
    from . import reminders
    from .. import tokens
    return {
        "nav_due": reminders.count(),
        "my_tokens": tokens.mine(),
        "nav_groups": groups,
        "nav_total": sum(counts.get(k, 0) for k in keys),
        "nav_deleted": deleted,
        "nav_tags": tag_counts(keys),
        "nav_special": special,
        "active_tag": active_tag,
        "new_menu": new_menu(),
        "site_guide": current_user.can_edit and bool(reg.setup_steps()),
        "list_pages": [(m, p) for m in reg.enabled_modules() for p in m.pages if p.from_list],
        "help": help_context(reg),
        "module_panes": [(m, m.settings_pane) for m in reg.enabled_modules()
                         if m.settings_pane and (current_user.is_admin or not m.settings_pane.admin)],
    }


def help_context(reg) -> dict:
    """What the Help window needs: the modules turned on, and the kinds of
    link they and the core have, in that order."""
    from .relations import CORE_KINDS
    modules = reg.enabled_modules()
    kinds = list(CORE_KINDS) + [k for m in modules for k in m.relation_kinds]
    return {"modules": {m.id for m in modules}, "kinds": kinds}


def new_menu() -> list[dict]:
    """What the "New" button offers: every enabled type, grouped by module in
    the sidebar's order, whichever page it is on."""
    if not current_user.can_edit:
        return []
    return [{"module": m, "types": list(m.types), "presets": [p for t in m.types for p in kind_presets(t)]}
            for m in registry().enabled_modules() if m.types]


def kind_presets(etype) -> list[tuple]:
    """The kinds a type comes in, from its "kind" choice, so the New record
    window finds a network device by "switch": (type, value, label), with
    "Other" left out."""
    field = next((f for f in etype.fields if f.key == "kind" and f.kind == "select"), None)
    if field is None:
        return []
    return [(etype, value, label) for value, label in field.options if value and value != "other"]
