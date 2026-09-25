"""The Documents tab every record has: the documents attached to it, and
the ones that mention it with [[its-slug]]."""
from flask import render_template

from hyprprem.core import present
from hyprprem.core.markdown import excerpt
from hyprprem.core.models import Entity, Relationship
from hyprprem.models import db


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
    from hyprprem.core.markdown import slugs_in
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
