"""The tables every module shares.

Every documented thing, whatever module it belongs to, has one row in
``entities``: its name, slug, status, location, tags, notes and who changed
it when. What is particular to its type lives in the module's own detail
table, one row per entity (``EntityDetail``). Relationships, custom fields,
attachments and history all hang off ``entities.id``, which is why anything
can link to anything.

New tables are created by ``db.create_all()``; new columns on these tables
need a step in ``_migrate()`` (docs/ARCHITECTURE.md, "Schema changes").
"""
import json

from sqlalchemy.orm import declared_attr

from ..models import User, db, utcnow

entity_tags = db.Table(
    "entity_tags",
    db.Column("entity_id", db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class Tag(db.Model):
    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60, collation="NOCASE"), unique=True, nullable=False)


class Entity(db.Model):
    __tablename__ = "entities"
    __table_args__ = (
        db.Index("ix_entities_live", "type", "deleted_at", "archived"),
        db.Index("ix_entities_updated", "updated_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    module = db.Column(db.String(40), nullable=False, index=True)
    type = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="active")
    # A location is itself an entity (a site, a room, a rack). For a location,
    # this is its parent, so one chain of breadcrumbs serves everything.
    location_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="SET NULL"), index=True)
    notes = db.Column(db.Text, nullable=False, default="")
    archived = db.Column(db.Boolean, nullable=False, default=False)
    # Deleting only stamps this, so Undo brings back the same id with its
    # links, files and history; the worker purges it later.
    deleted_at = db.Column(db.DateTime)
    # Lower-cased name, slug, notes, tags, detail and custom field values:
    # what the palette and ?q= match against. Rebuilt on every save.
    search_text = db.Column(db.Text, nullable=False, default="")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    location = db.relationship("Entity", remote_side=[id], foreign_keys=[location_id])
    tags = db.relationship(Tag, secondary=entity_tags, order_by=Tag.name, lazy="selectin")
    created_by = db.relationship(User, foreign_keys=[created_by_id])
    updated_by = db.relationship(User, foreign_keys=[updated_by_id])

    @classmethod
    def live(cls):
        return cls.query.filter(cls.deleted_at.is_(None))

    @property
    def tag_names(self) -> list[str]:
        return [t.name for t in self.tags]

    def __repr__(self) -> str:
        return f"<Entity {self.id} {self.type} {self.slug}>"


class Reminder(db.Model):
    """A date coming up or just past on a record (a field marked
    ``expires``), kept current by the worker and by every save
    (core/reminders.py). The dashboard and the sidebar badge read these."""
    __tablename__ = "reminders"
    __table_args__ = (db.UniqueConstraint("entity_id", "field"),)

    id = db.Column(db.Integer, primary_key=True)
    entity_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    field = db.Column(db.String(40), nullable=False)
    due = db.Column(db.Date, nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    entity = db.relationship("Entity")


class EntityDetail:
    """Base for a module's detail table: its primary key is the entity's id,
    and the row goes when the entity is purged.

        class RackDetail(EntityDetail, db.Model):
            __tablename__ = "rack_details"
            height_u = db.Column(db.Integer)
    """

    @declared_attr
    def entity_id(cls):
        return db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)


class CustomField(db.Model):
    """A field an admin added to an entity type, without code."""
    __tablename__ = "custom_fields"
    __table_args__ = (db.UniqueConstraint("entity_type", "key"),)

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(40), nullable=False, index=True)
    key = db.Column(db.String(40), nullable=False)
    label = db.Column(db.String(80), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default="text")
    options_json = db.Column(db.Text, nullable=False, default="[]")
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    @property
    def options(self) -> list[str]:
        try:
            return list(json.loads(self.options_json or "[]"))
        except ValueError:
            return []


class CustomValue(db.Model):
    """Stored as normalized text (ISO dates, plain numbers), so every value
    is searchable the same way."""
    __tablename__ = "custom_values"

    entity_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey("custom_fields.id", ondelete="CASCADE"), primary_key=True, index=True)
    value = db.Column(db.Text, nullable=False, default="")


class Relationship(db.Model):
    """A typed, directed link: source <kind> target ("vm1 runs on pve1")."""
    __tablename__ = "relationships"
    __table_args__ = (
        db.UniqueConstraint("kind", "source_id", "target_id"),
        db.CheckConstraint("source_id != target_id", name="ck_relationship_not_self"),
    )

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(40), nullable=False)
    source_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    target_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    note = db.Column(db.String(300), nullable=False, default="")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    source = db.relationship(Entity, foreign_keys=[source_id])
    target = db.relationship(Entity, foreign_keys=[target_id])


class Attachment(db.Model):
    """A file under DATA_DIR/attachments. ``stored_as`` is generated; the
    name the user gave it is only ever a label and a download name."""
    __tablename__ = "attachments"

    id = db.Column(db.Integer, primary_key=True)
    entity_id = db.Column(db.Integer, db.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    stored_as = db.Column(db.String(80), nullable=False, unique=True)
    content_type = db.Column(db.String(120), nullable=False, default="application/octet-stream")
    size = db.Column(db.Integer, nullable=False, default=0)
    sha256 = db.Column(db.String(64), nullable=False, default="")
    deleted_at = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    created_by = db.relationship(User, foreign_keys=[created_by_id])

    @property
    def is_image(self) -> bool:
        return self.content_type in ("image/png", "image/jpeg", "image/gif", "image/webp")


class AuditLog(db.Model):
    """One row per change. Names are copied in, not joined, so the history
    still reads right after the user or the entity is gone."""
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    user_name = db.Column(db.String(120), nullable=False, default="")
    entity_id = db.Column(db.Integer, index=True)
    entity_label = db.Column(db.String(200), nullable=False, default="")
    entity_type = db.Column(db.String(40), nullable=False, default="")
    action = db.Column(db.String(30), nullable=False)
    changes_json = db.Column(db.Text, nullable=False, default="[]")

    @property
    def changes(self) -> list[dict]:
        try:
            return json.loads(self.changes_json or "[]")
        except ValueError:
            return []
