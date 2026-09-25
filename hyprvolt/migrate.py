"""Schema migrations without a framework.

``db.create_all()`` runs first on every boot and creates any table that is
missing, with every column and index its model has. It never touches a table
that already exists. So:

* a **new table** needs only its model;
* a **new column** on an existing table needs the model column *and* a step
  (``m.add_column``), or older installs never get it;
* a **new index** on an existing table needs a step (``m.add_index``);
* a **data change** needs a step guarded by ``m.once``.

Each helper checks before it acts, so every step is safe to run on every boot,
and on a fresh install (where ``create_all`` already made the column) it does
nothing. Steps are appended and never edited: an install that has run a step
will not run its new version. docs/ARCHITECTURE.md has the full rule.
"""
import logging

from sqlalchemy import inspect, text

from .models import db, get_setting, set_setting

log = logging.getLogger("hyprvolt.migrate")


class Migrator:
    def __init__(self, owner: str = "core"):
        self.owner = owner

    def _inspector(self):
        # Fresh each time: an inspector caches the schema it first saw.
        return inspect(db.engine)

    def has_table(self, table: str) -> bool:
        return self._inspector().has_table(table)

    def has_column(self, table: str, column: str) -> bool:
        return column in {c["name"] for c in self._inspector().get_columns(table)}

    def add_column(self, table: str, column: str, ddl: str) -> None:
        """``ddl`` is the column's SQL type and constraints, as SQLite takes
        them in ALTER TABLE: a NOT NULL column needs a DEFAULT, and a foreign
        key column must default to NULL."""
        if not self.has_table(table) or self.has_column(table, column):
            return
        db.session.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
        db.session.commit()
        log.info("migrated (%s): added %s.%s", self.owner, table, column)

    def add_index(self, name: str, table: str, columns: list[str], unique: bool = False) -> None:
        cols = ", ".join(f'"{c}"' for c in columns)
        db.session.execute(text(
            f'CREATE {"UNIQUE " if unique else ""}INDEX IF NOT EXISTS "{name}" ON "{table}" ({cols})'
        ))
        db.session.commit()

    def once(self, key: str, fn) -> None:
        """Run ``fn()`` once per install, for changes to data rather than to
        the schema. The marker is a row in ``settings``."""
        marker = f"migration:{self.owner}:{key}"
        if get_setting(marker):
            return
        fn()
        db.session.commit()
        set_setting(marker, "done")
        log.info("migrated (%s): %s", self.owner, key)

    def execute(self, sql: str, **params) -> None:
        db.session.execute(text(sql), params)
        db.session.commit()
