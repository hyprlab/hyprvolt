"""Database models.

Schema changes go through ``_migrate()`` in ``__init__.py``: ``ALTER TABLE``
guarded by a column check, no migration framework. SQLite in one volume is the
whole storage story (see docs/ARCHITECTURE.md).
"""
import hashlib
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
    # viewer | editor | admin (permissions.py). The data belongs to the
    # instance; the role decides what an account may do with it.
    role = db.Column(db.String(10), default="viewer", nullable=False)
    # Preferences live on the account, not in localStorage, so they follow the
    # user to another browser.
    theme = db.Column(db.String(10), default="system", nullable=False)     # system|light|dark
    view_mode = db.Column(db.String(10), default="cards", nullable=False)  # cards|list
    infinite_scroll = db.Column(db.Boolean, default=True, nullable=False)
    # A record's sections all on one page, followed as it scrolls; off, one
    # section at a time.
    record_scroll = db.Column(db.Boolean, default=True, nullable=False)
    # Secrets are their own permission for viewers and editors, granted per
    # account by an admin. Admins have it always: they can do everything.
    can_see_secrets = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    def get_id(self) -> str:
        """What the session and the remember-me cookie hold: the id, the
        session epoch and a stamp of the password. A restore changes the
        epoch, so a sign-in from before it can't land on whoever has that id
        in the restored database; a new password changes the stamp, so every
        other session and remember-me cookie of the account ends."""
        return f"{self.id}.{get_setting('session_epoch') or ''}.{self.password_stamp}"

    @property
    def password_stamp(self) -> str:
        return hashlib.sha256(self.password_hash.encode()).hexdigest()[:12]

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def sees_secrets(self) -> bool:
        return self.is_admin or bool(self.can_see_secrets)

    @property
    def can_edit(self) -> bool:
        return self.role in ("editor", "admin")

    @property
    def display_name(self) -> str:
        return self.name or self.username

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class ApiToken(db.Model):
    """A token a script sends instead of signing in. Only its SHA-256 is
    kept; the token itself is shown once, when it is made (tokens.py)."""
    __tablename__ = "api_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    prefix = db.Column(db.String(12), nullable=False)          # "hv_Ab12Cd": enough to tell them apart
    read_only = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_used_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)

    user = db.relationship(User, backref=db.backref("tokens", cascade="all, delete-orphan", passive_deletes=True))


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
