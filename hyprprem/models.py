"""Database models.

Schema changes go through ``_migrate()`` in ``__init__.py``: ``ALTER TABLE``
guarded by a column check, no migration framework. SQLite in one volume is the
whole storage story (see docs/ARCHITECTURE.md).
"""
from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def utcnow() -> datetime:
    """Naive UTC. SQLite has no timezone type, so everything stored is UTC and
    every comparison goes through this."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)  # an email address
    name = db.Column(db.String(120))
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    # Preferences live on the account, not in localStorage, so they follow the
    # user to another browser.
    theme = db.Column(db.String(10), default="system", nullable=False)     # system|light|dark
    view_mode = db.Column(db.String(10), default="cards", nullable=False)  # cards|list
    infinite_scroll = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    items = db.relationship(
        "Item", backref="owner", cascade="all, delete-orphan", lazy="dynamic"
    )

    @property
    def display_name(self) -> str:
        return self.name or self.username

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Setting(db.Model):
    """Instance-wide key/value settings an admin edits at runtime.

    A stored value always wins over the matching environment variable, which
    is only the fresh-install default.
    """
    __tablename__ = "settings"

    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(500), nullable=False)


def get_setting(key: str) -> str | None:
    row = db.session.get(Setting, key)
    return row.value if row else None


def int_setting(key: str, fallback: int) -> int:
    raw = get_setting(key)
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return fallback


def set_setting(key: str, value: str) -> None:
    row = db.session.get(Setting, key)
    if row:
        row.value = value
    else:
        db.session.add(Setting(key=key, value=value))
    db.session.commit()


class Item(db.Model):
    """The one domain model the template ships with.

    It exists so the shell, the list and grid views, the detail sheet, the
    search palette and the JSON API are wired to something real. Rename it to
    whatever the app is about, or replace it and keep the machinery around it
    (docs/TEMPLATE.md).
    """
    __tablename__ = "items"
    __table_args__ = (db.Index("ix_items_user_created", "user_id", "created_at"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    body = db.Column(db.Text, default="", nullable=False)
    pinned = db.Column(db.Boolean, default=False, nullable=False)
    done = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    @property
    def summary(self) -> str:
        """The body on one line, for the card dek and the list row."""
        return " ".join((self.body or "").split())[:220]
