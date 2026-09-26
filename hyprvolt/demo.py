"""The demo homelab: ``flask seed-demo``, or Load a demo homelab on the
dashboard of an empty instance.

Each module adds its part through its manifest's ``seed(demo)``, called in
sidebar order but always after the modules it requires, built-in modules
last (``seed_order``). So Services finds the VMs it runs on, and a module that
requires another finds that one's records already there
(``demo.get("rack-1")``). Everything
goes through the normal write path, so the demo has history, search text and
links like real data.
"""
from flask_login import current_user

from .core import records, relations
from .core.fields import Invalid
from .core.models import Entity
from .models import User, db
from .registry import current as registry


class DemoError(Exception):
    pass


class Demo:
    def __init__(self, user=None, force: bool = False):
        self.user = user
        self.force = force
        self.made: dict[str, Entity] = {}

    def add(self, type_key: str, name: str, key: str | None = None, location=None, tags=(), notes: str = "",
            status: str | None = None, sections: dict | None = None, **fields) -> Entity | None:
        """Create a record; ``key`` (default: its name as a slug) finds it again.
        ``location``, and the value of a ref field, is a key or an entity.
        ``sections`` are values for other
        modules' form sections: ``{"rack": {"rack_id": ..., ...}}``, where an
        entity or a key stands for its id. Returns None if the type's module
        is turned off, so seeds need not check."""
        if registry().type(type_key) is None or not registry().is_enabled(registry().type(type_key).module):
            return None
        for f in registry().type(type_key).fields:
            if f.kind == "ref" and f.key in fields:
                fields[f.key] = self._id(fields[f.key])
        data = {"name": name, "tags": list(tags), "notes": notes, "fields": fields,
                "sections": {k: {n: self._id(v) for n, v in values.items()} for k, values in (sections or {}).items()}}
        if status:
            data["status"] = status
        loc = self.get(location) if isinstance(location, str) else location
        if loc is not None:
            data["location_id"] = loc.id
        if self.force:
            # Added to an instance that has records: what it can't take (an
            # address already recorded) is left out, first the other modules'
            # sections, then the record, rather than stopping the demo.
            entity = None
            for attempt in ((data, {**data, "sections": {}}) if data["sections"] else (data,)):
                try:
                    with db.session.begin_nested():
                        entity = records.create(type_key, attempt, self.user)
                    break
                except Invalid:
                    continue
            if entity is None:
                return None
        else:
            entity = records.create(type_key, data, self.user)
        self.made[key or records.slugify(name)] = entity
        return entity

    def get(self, key: str) -> Entity | None:
        return self.made.get(key)

    def _id(self, value):
        if isinstance(value, Entity):
            return value.id
        if isinstance(value, str) and value in self.made:
            return self.made[value].id
        return value

    def link(self, kind: str, source, target, note: str = "") -> None:
        source = self.get(source) if isinstance(source, str) else source
        target = self.get(target) if isinstance(target, str) else target
        if source is not None and target is not None:
            relations.link(kind, source, target, note, self.user)


def seed_order() -> list:
    """The modules in sidebar order, each moved after the ones it requires,
    built-in modules last: the knowledge base documents everything else."""
    reg = registry()
    waiting = sorted(reg.sidebar_order(), key=lambda m: m.core)
    done, order = set(), []
    while waiting:
        m = next((m for m in waiting if all(r in done for r in m.requires)), waiting[0])
        waiting.remove(m)
        done.add(m.id)
        order.append(m)
    return order


def is_empty() -> bool:
    return Entity.query.first() is None


def seed(user=None, force: bool = False) -> int:
    """Fill the instance with the demo. Refuses one that has records unless
    ``force``. Returns how many records it made."""
    if not force and not is_empty():
        raise DemoError("The demo only goes into an empty instance.")
    if user is None:
        user = User.query.filter_by(role="admin").order_by(User.id).first()
    demo = Demo(user, force=force)
    try:
        for module in seed_order():
            if module.seed is not None and registry().is_enabled(module.id):
                module.seed(demo)
                db.session.flush()
    except Invalid as err:
        db.session.rollback()
        raise DemoError(f"The demo could not be loaded: {err}") from err
    db.session.commit()
    return len(demo.made)


def seed_for_request() -> int:
    return seed(current_user._get_current_object())
