"""Relationship kinds, and the dependency walk over them.

A kind reads from source to target ("vm1 runs on pve1") and back again with
its reverse label ("pve1 runs vm1"). Its ``impact`` says which end stops
working when the other goes down; the walk follows only those, which is what
answers "what breaks if this goes down?".
"""
from ..manifest import RelationKind
from ..models import db

CORE_KINDS = (
    RelationKind("runs_on", "runs on", "runs", impact="source"),
    RelationKind("hosted_by", "hosted by", "hosts", impact="source"),
    RelationKind("connected_to", "connected to", "connected to", impact="none"),
    RelationKind("depends_on", "depends on", "needed by", impact="source"),
    RelationKind("installed_on", "installed on", "has installed", impact="source"),
    RelationKind("backs_up", "backs up", "backed up by", impact="none"),
    RelationKind("powered_by", "powered by", "powers", impact="source"),
    RelationKind("managed_by", "managed by", "manages", impact="none"),
    RelationKind("documented_by", "documented by", "documents", impact="none"),
)


def link(kind_key: str, source, target, note: str = "", user=None):
    """Create ``source <kind> target`` unless it exists, writing the history
    of both ends. Returns the relationship."""
    from ..registry import current as registry
    from . import records
    from .fields import Invalid
    from .models import Relationship
    kind = registry().kinds.get(kind_key)
    if kind is None:
        raise Invalid("Choose what kind of link it is.")
    if source.id == target.id:
        raise Invalid("A record can't be linked to itself.")
    existing = Relationship.query.filter_by(kind=kind.key, source_id=source.id, target_id=target.id).first()
    if existing:
        return existing
    rel = Relationship(kind=kind.key, source_id=source.id, target_id=target.id,
                       note=(note or "").strip()[:300], created_by_id=records._user_id(user))
    db.session.add(rel)
    records.audit(source, "linked", [{"field": "relationship", "label": kind.label.capitalize(),
                                      "old": "", "new": target.name}], user)
    records.audit(target, "linked", [{"field": "relationship", "label": kind.reverse.capitalize(),
                                      "old": "", "new": source.name}], user)
    return rel
