"""The Documents tab every record has: the documents attached to it, and
the ones that mention it with [[its-slug]]. And a document's pages: its
path, the pages under it, the pages either side, and what links to it."""
from flask import render_template

from hyprvolt.core import present, records
from hyprvolt.core.fields import Invalid
from hyprvolt.core.markdown import excerpt
from hyprvolt.core.models import Entity, Relationship
from hyprvolt.models import db

#: How deep pages may nest: a manual, its chapters, their sections...
MAX_DEPTH = 8


def attached(entity):
    rows = (db.session.query(Relationship, Entity)
            .join(Entity, Entity.id == Relationship.target_id)
            .filter(Relationship.source_id == entity.id, Relationship.kind == "documented_by",
                    Entity.type == "document", Entity.deleted_at.is_(None))
            .order_by(Entity.name).all())
    return rows


def mentions(entity):
    from . import DocumentBody
    pattern = f"%[[{entity.slug}%"
    rows = (Entity.live().join(DocumentBody, DocumentBody.entity_id == Entity.id)
            .filter(DocumentBody.body.like(pattern), Entity.id != entity.id).order_by(Entity.name).all())
    from hyprvolt.core.markdown import slugs_in
    return [e for e in rows if entity.slug in slugs_in(db.session.get(DocumentBody, e.id).body)]


def count(entity) -> int:
    return len(attached(entity))


def documents_tab(entity) -> str:
    from . import DocumentBody

    def item(doc):
        body = db.session.get(DocumentBody, doc.id)
        return {"view": present.View(doc), "excerpt": excerpt(body.body if body else "")}
    docs = [{"rel": rel, **item(doc)} for rel, doc in attached(entity)]
    attached_ids = {d["view"].id for d in docs}
    mentioned = [item(doc) for doc in mentions(entity) if doc.id not in attached_ids]
    return render_template("documents/tab.html", entity=entity, docs=docs, mentioned=mentioned)


def _body(doc_id):
    from . import DocumentBody
    return db.session.get(DocumentBody, doc_id)


def _text(doc_id) -> str:
    d = _body(doc_id)
    return d.body if d is not None else ""


# ———— Pages ————

def check_parent(entity: Entity, d) -> None:
    """A document can't be its own page, or a page of one of its pages."""
    seen, parent = {entity.id}, d.parent if d is not None else None
    depth = 0
    while parent is not None:
        if parent in seen:
            raise Invalid("A document can't be a page of itself or of one of its own pages.")
        seen.add(parent)
        depth += 1
        if depth >= MAX_DEPTH:
            raise Invalid(f"Pages nest {MAX_DEPTH} deep at most.")
        above = _body(parent)
        parent = above.parent if above is not None else None


def path(entity: Entity) -> list[Entity]:
    """The documents above this one, outermost first, live ones only."""
    chain, seen, d = [], {entity.id}, _body(entity.id)
    while d is not None and d.parent is not None and d.parent not in seen and len(chain) < MAX_DEPTH:
        up = records.live(d.parent)
        if up is None:
            break
        seen.add(up.id)
        chain.append(up)
        d = _body(up.id)
    return list(reversed(chain))


def pages(parent_id) -> list[Entity]:
    """A document's pages in their order: by number, then by name."""
    from . import DocumentBody
    rows = (Entity.live().join(DocumentBody, DocumentBody.entity_id == Entity.id)
            .filter(Entity.type == "document", DocumentBody.parent == parent_id).all())
    order = {e.id: _body(e.id).position for e in rows}
    return sorted(rows, key=lambda e: (order[e.id] is None, order[e.id] or 0, e.name.lower()))


def top_level(query):
    from . import DocumentBody
    under = db.session.query(DocumentBody.entity_id).filter(DocumentBody.parent.isnot(None))
    return query.filter(Entity.type == "document", Entity.id.notin_(under))


def page_overview(entity: Entity) -> tuple[str, str]:
    """Above the Overview, where the page sits; below the body, its own pages
    and the pages either side of it."""
    trail = path(entity)
    siblings = pages(trail[-1].id) if trail else []
    at = next((i for i, e in enumerate(siblings) if e.id == entity.id), None)
    before = siblings[at - 1] if at else None
    after = siblings[at + 1] if at is not None and at + 1 < len(siblings) else None
    children = pages(entity.id)
    above = render_template("documents/path.html", trail=[(e.id, e.name) for e in trail],
                                                    current=entity.name) if trail else ""
    below = render_template("documents/pages.html", entity=entity,
                            children=[{"view": present.View(c), "excerpt": excerpt(_text(c.id), 140)}
                                      for c in children],
                            before=before, after=after) if children or before or after else ""
    return above, below


# ———— Linked from ————

def linked_tab(doc: Entity) -> str:
    return render_template("documents/linked.html", doc=doc,
                           rows=[{"view": present.View(d), "excerpt": excerpt(_text(d.id))} for d in mentions(doc)])


def linked_count(doc: Entity):
    return len(mentions(doc)) or None
