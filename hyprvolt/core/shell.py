"""The shell around every page: the sidebar with its live counts, the "New"
menu, and the settings sections modules add. One call, ``context()``, so the
dashboard and every list render the same frame.
"""
from flask_login import current_user
from sqlalchemy import func

from ..models import db
from ..registry import current as registry
from .api import tag_counts
from .models import Entity


def type_counts() -> dict[str, int]:
    """Live, unarchived entities per type."""
    rows = db.session.query(Entity.type, func.count(Entity.id)).filter(
        Entity.deleted_at.is_(None), Entity.archived.is_(False)).group_by(Entity.type).all()
    return dict(rows)


def module_query(module, archived: bool = False):
    """Live entities of one module, as its sidebar filters see them."""
    query = Entity.live().filter(Entity.type.in_([t.key for t in module.types]))
    return query.filter(Entity.archived.is_(archived))


def context(active_module=None, active_type=None, active_filter=None, active_tag=None,
            special=None) -> dict:
    reg = registry()
    counts = type_counts()
    groups, by_group = [], {}
    for m in reg.enabled_modules():
        if not m.types:
            continue    # a module of tabs and panes only (the vault) has no list
        entry = {
            "module": m,
            "count": sum(counts.get(t.key, 0) for t in m.types),
            "active": active_module is not None and m.id == active_module.id,
            "types": [],
            "filters": [],
        }
        if entry["active"]:
            if len(m.types) > 1:
                entry["types"] = [{"type": t, "count": counts.get(t.key, 0),
                                   "active": active_type == t.key} for t in m.types]
            for f in m.filters:
                entry["filters"].append({"filter": f, "count": f.apply(module_query(m)).count(),
                                         "active": active_filter == f.key})
            entry["archived"] = module_query(m, archived=True).count()
        if m.group not in by_group:
            by_group[m.group] = {"label": m.group, "modules": []}
            groups.append(by_group[m.group])
        by_group[m.group]["modules"].append(entry)

    keys = reg.enabled_type_keys()
    deleted = 0
    if current_user.can_edit:
        deleted = Entity.query.filter(Entity.deleted_at.isnot(None), Entity.type.in_(keys)).count()
    return {
        "nav_groups": groups,
        "nav_total": sum(counts.get(k, 0) for k in keys),
        "nav_deleted": deleted,
        "nav_tags": tag_counts(keys),
        "nav_special": special,
        "active_tag": active_tag,
        "new_menu": new_menu(active_module),
        "module_panes": [(m, m.settings_pane) for m in reg.enabled_modules()
                         if m.settings_pane and (current_user.is_admin or not m.settings_pane.admin)],
    }


def new_menu(active_module=None) -> list[dict]:
    """What the "New" button offers: the page's module's types, or every
    type, grouped by module."""
    if not current_user.can_edit:
        return []
    reg = registry()
    modules = [active_module] if active_module else reg.enabled_modules()
    return [{"module": m, "types": list(m.types)} for m in modules if m.types]
