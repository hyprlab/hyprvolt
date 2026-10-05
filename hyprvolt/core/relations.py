"""Relationship kinds, and the dependency walk over them.

A kind reads from source to target ("vm1 runs on pve1") and back again with
its reverse label ("pve1 runs vm1"). Its ``impact`` says which end stops
working when the other goes down; the walk follows only those, which is what
answers "what breaks if this goes down?". It follows as well the
dependencies modules work out from what they record (``impact_edges``):
Network's, from the cables.
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
    RelationKind("part_of", "part of", "includes", impact="none"),
)


def link(kind_key: str, source, target, note: str = "", user=None, audit_source: bool = True):
    """Create ``source <kind> target`` unless it exists, writing the history
    of both ends (only the target's when the source records the change
    itself, as a field kept as a link does). Returns the relationship."""
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
    if audit_source:
        records.audit(source, "linked", [{"field": "relationship", "label": kind.label.capitalize(),
                                          "old": "", "new": target.name, "ref": target.id}], user)
    records.audit(target, "linked", [{"field": "relationship", "label": kind.reverse.capitalize(),
                                      "old": "", "new": source.name, "ref": source.id}], user)
    return rel


def unlink(rel, user=None, audit_source: bool = True) -> dict:
    """Remove a relationship; returns what re-creates it (for Undo)."""
    from ..registry import current as registry
    from . import records
    kind = registry().kinds.get(rel.kind)
    label = kind.label if kind else rel.kind
    reverse = kind.reverse if kind else rel.kind
    snapshot = {"kind": rel.kind, "source_id": rel.source_id, "target_id": rel.target_id, "note": rel.note}
    if audit_source:
        records.audit(rel.source, "unlinked", [{"field": "relationship", "label": label.capitalize(),
                                                "old": rel.target.name, "new": "", "ref": rel.target_id}], user)
    records.audit(rel.target, "unlinked", [{"field": "relationship", "label": reverse.capitalize(),
                                            "old": rel.source.name, "new": "", "ref": rel.source_id}], user)
    db.session.delete(rel)
    return snapshot


# ———— Links ticked from a list: what a UPS powers, what an access point broadcasts ————

def _other(rel, side) -> int:
    return rel.target_id if side == "source" else rel.source_id


def _ends(kind_key: str, entity, side: str) -> list:
    from .models import Relationship
    end = Relationship.source_id if side == "source" else Relationship.target_id
    return Relationship.query.filter(Relationship.kind == kind_key, end == entity.id).order_by(Relationship.id).all()


def linked(kind_key: str, entity, side: str) -> list:
    """The live records at the other end of ``entity``'s links of a kind,
    ``entity`` being the links' ``side`` ("source" or "target"), by name."""
    from . import records
    found = {}
    for rel in _ends(kind_key, entity, side):
        other = records.live(_other(rel, side))
        if other is not None:
            found[other.id] = other
    return sorted(found.values(), key=lambda e: e.name.lower())


def chosen_ids(raw) -> list[int]:
    """Record ids ticked in a list, as a form sends them: "3,5", or a list."""
    from .fields import Invalid
    items = raw if isinstance(raw, (list, tuple)) else str(raw or "").split(",")
    out = []
    for item in (str(i).strip() for i in items):
        if item and not item.isdigit():
            raise Invalid("Choose from the list.")
        if item and int(item) not in out:
            out.append(int(item))
    return out


def set_linked(kind_key: str, entity, side: str, raw, offered, what: str, user=None) -> dict | None:
    """Make ``entity``'s links of a kind the ones ticked (``raw``, ids) from
    ``offered`` (records): one no longer ticked is removed, one newly ticked
    made. A link to a record out of sight (deleted) is left alone. None when
    nothing changed, else the names before and after, for the history."""
    from .fields import Invalid
    offered = {e.id: e for e in offered}
    wanted = []
    for i in chosen_ids(raw):
        if i not in offered:
            raise Invalid(f"Choose {what} that exists.")
        wanted.append(offered[i])
    current = linked(kind_key, entity, side)
    have, want = {e.id for e in current}, {e.id for e in wanted}
    if have == want:
        return None
    for rel in _ends(kind_key, entity, side):
        if _other(rel, side) in have - want:
            unlink(rel, user)
    for e in wanted:
        if e.id not in have:
            link(kind_key, entity if side == "source" else e, e if side == "source" else entity, user=user)

    def names(es):
        return ", ".join(e.name for e in sorted(es, key=lambda e: e.name.lower()))
    return {"old": names(current), "new": names(wanted)}


def visible_ids() -> set[int]:
    """Entities that can appear on the other end of a link: not deleted, and
    of a turned-on module."""
    from ..registry import current as registry
    from .models import Entity
    keys = registry().enabled_type_keys()
    from .access import visible
    return {i for (i,) in visible(db.session.query(Entity.id).filter(Entity.deleted_at.is_(None),
                                                                      Entity.type.in_(keys)))}


def for_entity(entity) -> list[dict]:
    """Both directions, read from ``entity``'s side: [{"rel", "kind",
    "label", "other", "outgoing"}], grouped by label."""
    from ..registry import current as registry
    from .models import Relationship
    kinds = registry().kinds
    visible = visible_ids()
    rows = Relationship.query.filter((Relationship.source_id == entity.id) | (Relationship.target_id == entity.id)).all()
    out = []
    for rel in rows:
        outgoing = rel.source_id == entity.id
        other = rel.target if outgoing else rel.source
        if other.id not in visible:
            continue
        kind = kinds.get(rel.kind)
        label = (kind.label if outgoing else kind.reverse) if kind else rel.kind
        out.append({"rel": rel, "kind": kind, "label": label, "other": other, "outgoing": outgoing})
    return sorted(out, key=lambda r: (r["label"], r["other"].name.lower()))


def derived(entity) -> list[dict]:
    """Links modules work out rather than record (the devices a device is
    cabled to), read-only: [{"other", "label", "sub", "note"}], each other
    end one the reader may see."""
    from ..registry import current as registry
    visible = visible_ids()
    out = []
    for module in registry().enabled_modules():
        if module.derived_links:
            out += [d for d in module.derived_links(entity) if d["other"].id in visible]
    return out


def _edges(direction: str) -> dict[int, list[tuple[int, str]]]:
    """Adjacency for the walk. "dependencies": X -> what X needs.
    "dependents": X -> what needs X."""
    from ..registry import current as registry
    from .models import Relationship
    kinds = registry().kinds
    visible = visible_ids()
    impactful = [k for k in kinds.values() if k.impact != "none"]
    rows = Relationship.query.filter(Relationship.kind.in_([k.key for k in impactful])).all()
    edges: dict[int, list[tuple[int, str]]] = {}
    pairs: set[tuple[int, int]] = set()

    def add(needs, needed, forward, backward):
        pairs.add((needs, needed))
        if direction == "dependencies":
            edges.setdefault(needs, []).append((needed, forward))
        else:
            edges.setdefault(needed, []).append((needs, backward))
    for rel in rows:
        if rel.source_id not in visible or rel.target_id not in visible:
            continue
        kind = kinds[rel.kind]
        # needs -> needed, and the words for each way of reading it
        if kind.impact == "source":
            needs, needed, forward, backward = rel.source_id, rel.target_id, kind.label, kind.reverse
        else:
            needs, needed, forward, backward = rel.target_id, rel.source_id, kind.reverse, kind.label
        add(needs, needed, forward, backward)
    # Dependencies modules work out rather than record (Network's cables),
    # unless a link says the same already.
    for module in registry().enabled_modules():
        for needs, needed, forward, backward in (module.impact_edges() if module.impact_edges else ()):
            if needs in visible and needed in visible and (needs, needed) not in pairs:
                add(needs, needed, forward, backward)
    return edges


def walk(entity, direction: str = "dependents", max_depth: int = 6) -> list[dict]:
    """The dependency tree from ``entity``. "dependents" answers "what breaks
    if this goes down"; "dependencies" answers "what does this need".

    Each node is {"entity", "label", "type_label", "children", "cycle",
    "repeat", "truncated"}; ``type_label`` is the kind of record it is. A
    loop back into the current path is marked ``cycle`` and not followed; a
    node already expanded elsewhere is marked ``repeat``, so a diamond is
    shown once in full and the walk stays linear.
    """
    from ..registry import current as registry
    from .models import Entity
    edges = _edges(direction)
    names = {}
    expanded = {entity.id}

    reg = registry()

    def kind_of(eid):
        etype = reg.type(name_of(eid).type)
        return etype.label if etype else name_of(eid).type

    def name_of(eid):
        if eid not in names:
            names[eid] = db.session.get(Entity, eid)
        return names[eid]

    def children(eid, depth, path):
        out = []
        for other, label in sorted(edges.get(eid, []), key=lambda e: (e[1], name_of(e[0]).name.lower())):
            node = {"entity": name_of(other), "label": label, "type_label": kind_of(other), "children": [],
                    "cycle": False, "repeat": False, "truncated": False}
            if other in path:
                node["cycle"] = True
            elif other in expanded:
                node["repeat"] = True
            elif depth >= max_depth:
                node["truncated"] = bool(edges.get(other))
            else:
                expanded.add(other)
                node["children"] = children(other, depth + 1, path | {other})
            out.append(node)
        return out

    return children(entity.id, 1, {entity.id})


def count(tree: list[dict]) -> int:
    """Distinct entities in a tree."""
    seen = set()

    def visit(nodes):
        for n in nodes:
            seen.add(n["entity"].id)
            visit(n["children"])
    visit(tree)
    return len(seen)


def tree_json(tree: list[dict]) -> list[dict]:
    return [{"id": n["entity"].id, "name": n["entity"].name, "type": n["entity"].type,
             "type_label": n["type_label"], "label": n["label"],
             "cycle": n["cycle"], "repeat": n["repeat"], "truncated": n["truncated"],
             "children": tree_json(n["children"])} for n in tree]
