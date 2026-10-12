"""The Documents tab every record has: the documents attached to it, and
the ones that mention it with [[its-slug]]. And a document's pages: its
path, the pages under it, the pages either side, and what links to it."""
from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user
from sqlalchemy import func

from hyprvolt.core import access, present, records, relations
from hyprvolt.core.fields import Invalid
from hyprvolt.core.markdown import excerpt
from hyprvolt.core.models import Entity, Relationship
from hyprvolt.models import db
from hyprvolt.permissions import role

bp = Blueprint("documents", __name__)

#: Two documents cross-linked: "see also", the same from both ends.
SEE_ALSO = "see_also"

#: How deep pages may nest: a manual, its chapters, their sections...
MAX_DEPTH = 8


def attached(entity):
    rows = (db.session.query(Relationship, Entity)
            .join(Entity, Entity.id == Relationship.target_id)
            .filter(Relationship.source_id == entity.id, Relationship.kind == "documented_by",
                    Entity.type == "document", Entity.deleted_at.is_(None),
                    Entity.access.notin_(access.hidden()))
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
                            before=before, after=after, access_short=access.SHORT) if children or before or after else ""
    return above, below


# ———— Linked from ————

def _cross_rels(doc: Entity) -> list[Relationship]:
    return Relationship.query.filter(Relationship.kind == SEE_ALSO,
                                     (Relationship.source_id == doc.id) | (Relationship.target_id == doc.id)).all()


def _other_end(rel, doc) -> int:
    return rel.target_id if rel.source_id == doc.id else rel.source_id


def cross_linked(doc: Entity) -> list[Entity]:
    """The documents cross-linked with this one, whichever end it was linked
    from, those the reader may see, by name."""
    found = {}
    for rel in _cross_rels(doc):
        other = records.live(_other_end(rel, doc))
        if other is not None and other.type == "document":
            found[other.id] = other
    return sorted(found.values(), key=lambda e: e.name.lower())


def _documents(doc: Entity) -> list[Entity]:
    """Every other document the reader may see, by name."""
    return (Entity.live().filter(Entity.type == "document", Entity.id != doc.id)
            .order_by(func.lower(Entity.name)).all())


def link_choices(doc: Entity) -> list[tuple[int, str]]:
    """Every other document to tick, a page named with what it is a page of."""
    docs = _documents(doc)
    names = {e.id: e.name for e in docs} | {doc.id: doc.name}
    out = []
    for e in docs:
        d = _body(e.id)
        parent = names.get(d.parent) if d is not None and d.parent else None
        out.append((e.id, f"{e.name} · {parent}" if parent else e.name))
    return out


def set_cross_links(doc: Entity, raw, user=None) -> list[int]:
    """Make the documents ticked (``raw``, ids) the ones cross-linked with
    ``doc``: one no longer ticked is unlinked, one newly ticked linked. A
    link to a document out of sight (deleted, restricted) is left alone.
    Returns the ids linked before, for Undo."""
    offered = {e.id: e for e in _documents(doc)}
    wanted = []
    for i in relations.chosen_ids(raw):
        if i not in offered:
            raise Invalid("Choose documents that exist.")
        wanted.append(offered[i])
    want = {e.id for e in wanted}
    before = [e.id for e in cross_linked(doc)]
    for rel in _cross_rels(doc):
        if _other_end(rel, doc) in offered and _other_end(rel, doc) not in want:
            relations.unlink(rel, user)
    for e in wanted:
        if e.id not in before:
            relations.link(SEE_ALSO, doc, e, user=user)
    return before


def linked_tab(doc: Entity) -> str:
    linked = cross_linked(doc)
    ids = {e.id for e in linked}

    def row(d):
        return {"view": present.View(d), "excerpt": excerpt(_text(d.id))}
    editable = bool(getattr(current_user, "can_edit", False)) and doc.deleted_at is None
    return render_template("documents/linked.html", doc=doc, linked=[row(d) for d in linked],
                           rows=[row(d) for d in mentions(doc) if d.id not in ids], editable=editable,
                           choices=link_choices(doc) if editable else [],
                           value=",".join(str(i) for i in sorted(ids)))


def linked_count(doc: Entity):
    return len({e.id for e in cross_linked(doc)} | {e.id for e in mentions(doc)}) or None


@bp.route("/choices")
@role("viewer")
def choices():
    """Every document the reader may see, for the list a Markdown field opens
    at [[ (app.js): its name, its slug, and what it is a page of. ``exclude``
    leaves out the one being written."""
    docs = Entity.live().filter(Entity.type == "document").order_by(func.lower(Entity.name)).all()
    names = {e.id: e.name for e in docs}
    exclude = request.args.get("exclude", type=int)
    out = []
    for e in docs:
        if e.id == exclude:
            continue
        d = _body(e.id)
        parent = names.get(d.parent) if d is not None and d.parent else None
        out.append({"id": e.id, "name": e.name, "slug": e.slug, "parent": parent or ""})
    return jsonify(documents=out)


@bp.route("/<int:entity_id>/links", methods=["POST"])
@role("editor")
def save_links(entity_id):
    """``ids``: the documents to cross-link with this one, every other
    unlinked. The answer's undo puts back the ones linked before."""
    doc = records.live(entity_id)
    if doc is None or doc.type != "document":
        abort(404)
    data = request.get_json(silent=True) or {}
    try:
        before = set_cross_links(doc, data.get("ids"), current_user._get_current_object())
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    db.session.commit()
    return jsonify(ok=True, undo={"url": f"/documents/{doc.id}/links",
                                  "body": {"ids": ",".join(str(i) for i in before)}})
