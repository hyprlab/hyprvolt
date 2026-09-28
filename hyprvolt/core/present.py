"""What the templates need to show entities, gathered in as few queries as
possible: a page of cards loads each type's detail rows once, and the
location breadcrumbs come from one index of every location per request.
"""
from flask import g

from ..models import db
from ..registry import current as registry
from . import fields as F
from . import records
from .models import Entity


def location_index() -> dict[int, tuple[str, int | None]]:
    """id -> (name, parent id) for every live location, once per request."""
    if "_locations" not in g:
        keys = [t.key for t in registry().location_types()]
        rows = db.session.query(Entity.id, Entity.name, Entity.location_id).filter(
            Entity.deleted_at.is_(None), Entity.type.in_(keys)).all() if keys else []
        g._locations = {i: (name, parent) for i, name, parent in rows}
    return g._locations


def crumbs(location_id) -> list[tuple[int, str]]:
    """[(id, name)], outermost first, starting from ``location_id``."""
    index, chain, seen = location_index(), [], set()
    while location_id in index and location_id not in seen and len(chain) < 12:
        seen.add(location_id)
        name, parent = index[location_id]
        chain.append((location_id, name))
        location_id = parent
    return list(reversed(chain))


def path_label(location_id, sep=" › ") -> str:
    return sep.join(name for _, name in crumbs(location_id))


def icon(etype) -> str:
    if etype is None:
        return ""
    if etype.icon:
        return etype.icon
    module = registry().module(etype.module)
    return module.icon if module else ""


def details_for(entities) -> dict[int, object]:
    """entity id -> detail row, one query per type on the page."""
    by_type: dict[str, list[int]] = {}
    for e in entities:
        by_type.setdefault(e.type, []).append(e.id)
    out = {}
    for type_key, ids in by_type.items():
        etype = registry().type(type_key)
        if etype is None or etype.detail is None:
            continue
        for row in etype.detail.query.filter(etype.detail.entity_id.in_(ids)):
            out[row.entity_id] = row
    return out


class View:
    """One entity as a card or a list row shows it."""

    def __init__(self, entity: Entity, detail=None, linked=None, image=None):
        self.entity = entity
        self.image = image
        self.id = entity.id
        self.name = entity.name
        self.etype = registry().type(entity.type)
        self.type_label = self.etype.label if self.etype else entity.type
        self.status = dict(self.etype.statuses).get(entity.status, entity.status) if self.etype else entity.status
        self.icon = icon(self.etype)
        self.path = path_label(entity.location_id) if entity.location_id else ""
        self.tags = entity.tag_names
        self.archived = entity.archived
        self.deleted = entity.deleted_at is not None
        self.updated_at = entity.updated_at
        self.card_facts, self.list_facts = [], []
        for f in self.etype.fields if self.etype else ():
            if not (f.card or f.list):
                continue
            if f.relation:
                value = (linked or {}).get(f.key)
            else:
                value = getattr(detail, f.key, None) if detail is not None else None
            if value in (None, ""):
                continue
            shown = F.display(f, value, records.live)
            if f.card:
                self.card_facts.append((f.label, shown))
            if f.list:
                self.list_facts.append((f.label, shown))
        self.dek = self.path
        if not self.dek and detail is not None:
            # No location to show: the start of the first Markdown field (a
            # document's body) says more than nothing.
            from .markdown import excerpt
            prose = next((f for f in (self.etype.fields if self.etype else ()) if f.kind == "markdown"), None)
            if prose is not None:
                self.dek = excerpt(getattr(detail, prose.key, "") or "", 160)

    @property
    def summary(self) -> str:
        """The list row's second column: where it is, then its key facts."""
        parts = [self.path] if self.path else []
        parts += [v for _, v in self.list_facts]
        return " · ".join(parts)


def linked_for(entities) -> dict[int, dict[str, int]]:
    """entity id -> the values of its fields kept as links, one query per
    type on the page that has any shown in a card or a row."""
    by_type: dict[str, list[int]] = {}
    for e in entities:
        by_type.setdefault(e.type, []).append(e.id)
    out = {}
    for type_key, ids in by_type.items():
        etype = registry().type(type_key)
        if etype is not None and any(f.relation and (f.card or f.list) for f in etype.fields):
            out.update(records.linked_values(ids, etype))
    return out


def views(entities) -> list[View]:
    from .images import featured_of
    details, linked, pictures = details_for(entities), linked_for(entities), featured_of(entities)
    return [View(e, details.get(e.id), linked.get(e.id), pictures.get(e.id)) for e in entities]
