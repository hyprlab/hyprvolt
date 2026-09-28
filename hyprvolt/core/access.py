"""Who may read a record.

Most records are for everyone signed in. A type marked ``restrictable``
(documents) can be narrowed to editors and admins, or to admins and the
people given access to secrets. A record a reader may not see is left out
of everything: lists, search, counts, tags, links, exports and the API
answer 404 for it, as if it were not there. ``Entity.live()`` applies the
rule, so most reads get it without asking; lookups by id go through
``can_see``.

Outside a request (the worker, the command line) everything is visible.
An API token reads what its account may.
"""
from flask import has_request_context
from flask_login import current_user

LEVELS = (("", "Everyone"), ("editors", "Editors and admins"),
          ("private", "Admins and people with access to secrets"))
LABELS = dict(LEVELS)
SHORT = {"editors": "Editors only", "private": "Private"}


def allows(user, level: str) -> bool:
    """Whether ``user`` may read a record at ``level``."""
    if not level:
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    if level == "editors":
        return bool(user.can_edit)
    if level == "private":
        return bool(user.sees_secrets)
    return False


def hidden() -> list[str]:
    """The levels the current reader may not see."""
    if not has_request_context():
        return []
    return [level for level, _ in LEVELS if level and not allows(current_user, level)]


def can_see(entity) -> bool:
    return (entity.access or "") not in hidden()


def visible(query):
    """``query`` without what the current reader may not see."""
    from .models import Entity
    levels = hidden()
    return query.filter(Entity.access.notin_(levels)) if levels else query


def choices(user) -> list[tuple[str, str]]:
    """The levels ``user`` may give a record: none that would hide it from
    themselves."""
    return [(level, label) for level, label in LEVELS if allows(user, level)]
