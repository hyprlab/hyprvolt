"""The smallest module: one entity type with one field of its own.

Everything else comes from the core: the list and card views, the form, the
detail sheet with its Relationships, Documents, Attachments and History tabs,
search, custom fields, archive, delete with Undo, and a place in the sidebar.
docs/MODULES.md walks through it.
"""
from hyprprem.core.models import EntityDetail
from hyprprem.manifest import EntityType, Field, Module
from hyprprem.models import db


class GadgetDetail(EntityDetail, db.Model):
    __tablename__ = "example_gadgets"
    color = db.Column(db.String(40))


module = Module(
    id="example",
    name="Gadgets",
    types=(
        EntityType("gadget", "Gadget", "Gadgets", detail=GadgetDetail,
                   fields=(Field("color", "Color", list=True),)),
        # A place that can sit in any place, itself included, so the tests
        # can try to build a loop.
        EntityType("crate", "Crate", "Crates", location=True),
    ),
)
