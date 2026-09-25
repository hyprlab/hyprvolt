"""The smallest module: one entity type with one field of its own.

Everything else comes from the core: the list and card views, the form, the
detail sheet with its Relationships, Documents, Attachments and History tabs,
search, custom fields, archive, delete with Undo, and a place in the sidebar.
docs/MODULES.md walks through it.

Below the gadget are the extras the core's tests need: a place that can form
a loop, a field kept as a link, and a form section on another type.
"""
from flask import render_template_string

from hyprvolt.core.fields import Invalid
from hyprvolt.core.models import EntityDetail
from hyprvolt.manifest import EntityType, Field, FormSection, Module
from hyprvolt.models import db


class GadgetDetail(EntityDetail, db.Model):
    __tablename__ = "example_gadgets"
    color = db.Column(db.String(40))


class Sticker(db.Model):
    """What the sticker form section keeps, in the module's own table."""
    __tablename__ = "example_stickers"
    entity_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)
    text = db.Column(db.String(40), nullable=False)


def sticker_form(etype, entity):
    row = db.session.get(Sticker, entity.id) if entity else None
    return render_template_string('<label class="field"><span class="field-label">Sticker</span>'
                                  '<input name="s.sticker.text" value="{{ text }}"></label>',
                                  text=row.text if row else "")


def sticker_save(entity, values, user):
    text = " ".join(str(values.get("text") or "").split())
    if len(text) > 40:
        raise Invalid("A sticker holds 40 characters at most.")
    row = db.session.get(Sticker, entity.id)
    old = row.text if row else ""
    if text == old:
        return []
    if row is None:
        db.session.add(Sticker(entity_id=entity.id, text=text))
    elif text:
        row.text = text
    else:
        db.session.delete(row)
    return [{"field": "sticker", "label": "Sticker", "old": old, "new": text}]


module = Module(
    id="example",
    name="Gadgets",
    types=(
        EntityType("gadget", "Gadget", "Gadgets", detail=GadgetDetail, traits=("sticky",),
                   fields=(Field("color", "Color", list=True),
                           Field("battery", "Battery", "ref", types=("battery",), relation="powered_by",
                                 list=True))),
        # A place that can sit in any place, itself included, so the tests
        # can try to build a loop.
        EntityType("crate", "Crate", "Crates", location=True),
        EntityType("battery", "Battery", "Batteries"),
    ),
    models=(GadgetDetail, Sticker),
    form_sections=(FormSection("sticker", "Sticker", sticker_form, sticker_save,
                               when=lambda etype: "sticky" in etype.traits),),
)
