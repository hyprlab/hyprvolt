"""Relationship kinds, and the dependency walk over them.

A kind reads from source to target ("vm1 runs on pve1") and back again with
its reverse label ("pve1 runs vm1"). Its ``impact`` says which end stops
working when the other goes down; the walk follows only those, which is what
answers "what breaks if this goes down?".
"""
from ..manifest import RelationKind

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
