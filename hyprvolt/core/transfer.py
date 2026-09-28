"""Getting documentation in and out: a CSV of any list as it is filtered,
a CSV import for one kind of record (upload, match the columns, check, then
import), and a JSON export of the whole instance.

Imports go through ``records`` like every other write, so they have history,
search text and reminders. A check runs the whole import and rolls it back;
the import itself skips the rows that fail and keeps the rest.
"""
import csv
import io
import json
import re
import secrets as _secrets
import time
from datetime import date, datetime
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request
from sqlalchemy import func

from .. import __version__
from ..models import db, utcnow
from ..permissions import role
from ..registry import current as registry
from . import fields as F
from . import present, records
from .fields import Invalid
from .models import Entity

bp = Blueprint("transfer", __name__)

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
PREVIEW_ROWS = 60
#: An import's upload is kept this long between its steps.
KEEP_SECONDS = 24 * 3600
#: Never in the JSON export: they unlock things, and a backup has them if needed.
LEFT_OUT = {("users", "password_hash"), ("vault_secrets", "ciphertext"), ("api_tokens", "token_hash"),
            ("attachments", "text"), ("entities", "search_text")}
LEFT_OUT_SETTINGS = ("turnstile_secret_key",)


# ———— CSV export ————

def _cell(value) -> str:
    """Text a spreadsheet won't run: a leading =, +, -, @ makes a cell a
    formula, so text starting with one gets an apostrophe."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not re.fullmatch(r"-?\d+(\.\d+)?", text):
        return "'" + text
    return text


def _plain(f, value) -> str:
    """A value as a spreadsheet wants it: labels for choices, names for
    records, numbers without their unit."""
    if value in (None, ""):
        return ""
    if f.kind == "boolean":
        return "yes" if value else "no"
    if f.kind in ("select", "ref", "datetime"):
        return F.display(f, value, records.live)
    if isinstance(value, date):
        return value.isoformat()
    if f.kind == "number" and isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def csv_rows(entities, etypes) -> tuple[list[str], list[list[str]]]:
    """The header and rows for ``entities``, with the fields of ``etypes``.
    Every value is read in a few queries per kind of record, not per row."""
    from .models import CustomValue
    reg = registry()
    fields_of = {t.key: records.custom_fields(t.key) for t in etypes}
    columns, seen = [], set()
    for t in etypes:
        for f in t.fields:
            if f.key not in seen:
                seen.add(f.key)
                columns.append(("f", f))
        for cf in fields_of[t.key]:
            if ("c", cf.key) not in seen:
                seen.add(("c", cf.key))
                columns.append(("c", F.custom_field(cf)))
    header = ["id", "type", "name", "slug", "status", "location", "tags"] + [f.label for _, f in columns] + \
        ["notes", "created", "updated", "link"]
    ids = [e.id for e in entities]
    details = present.details_for(entities)
    linked: dict[int, dict] = {}
    for t in etypes:
        linked.update(records.linked_values([e.id for e in entities if e.type == t.key], t))
    stored: dict[int, dict[int, str]] = {}
    for v in CustomValue.query.filter(CustomValue.entity_id.in_(ids)) if ids else ():
        stored.setdefault(v.entity_id, {})[v.field_id] = v.value
    rows = []
    base = request.host_url.rstrip("/")
    for e in entities:
        etype = reg.type(e.type)
        own_keys = {f.key for f in etype.fields} if etype else set()
        own = records.own_values(e, details.get(e.id), linked.get(e.id, {})) if etype else {}
        custom = {cf.key: F.from_text(F.custom_field(cf), stored.get(e.id, {}).get(cf.id, ""))
                  for cf in (fields_of[e.type] if e.type in fields_of else records.custom_fields(e.type))}
        loc = present.path_label(e.location_id, " > ") if e.location_id else ""
        row = [str(e.id), etype.label if etype else e.type, e.name, e.slug, records.status_label(e), loc,
               ", ".join(e.tag_names)]
        for kind, f in columns:
            has = (kind == "f" and f.key in own_keys) or (kind == "c" and f.key in custom)
            row.append(_plain(f, own.get(f.key) if kind == "f" else custom.get(f.key)) if has else "")
        row += [e.notes or "", e.created_at.isoformat(timespec="seconds") + "Z",
                e.updated_at.isoformat(timespec="seconds") + "Z", f"{base}/e/{e.id}"]
        rows.append([_cell(v) for v in row])
    return header, rows


@bp.route("/export/<name>.csv")
@role("viewer")
def export_csv(name):
    """The list at ``/<module>`` (or ``/all``) with the same filters, every
    page of it, as CSV."""
    from ..main import records_listed
    reg = registry()
    module, a, rows = records_listed(name, 50_000)
    etypes = [a["etype"]] if a["etype"] else ([t for t in module.types] if module else reg.enabled_types())
    etypes = [t for t in etypes if any(e.type == t.key for e in rows)] or etypes[:1]
    header, body = csv_rows(rows, etypes)
    out = io.StringIO()
    out.write("﻿")          # so a spreadsheet reads it as UTF-8
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(body)
    label = (a["etype"].key if a["etype"] else name).replace("_", "-")
    return Response(out.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": f'attachment; filename="hyprvolt-{label}-{date.today().isoformat()}.csv"',
        "Cache-Control": "no-store"})


# ———— CSV import ————

def _folder() -> Path:
    path = Path(current_app.config["DATA_DIR"]) / "imports"
    path.mkdir(exist_ok=True)
    return path


def cleanup() -> int:
    """Uploads left behind by imports that were never finished."""
    folder = Path(current_app.config["DATA_DIR"]) / "imports"
    gone = 0
    for p in folder.glob("*.csv") if folder.is_dir() else ():
        if time.time() - p.stat().st_mtime > KEEP_SECONDS:
            p.unlink(missing_ok=True)
            gone += 1
    return gone


def _read(token: str) -> tuple[list[str], list[list[str]]]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token or ""):
        raise Invalid("That upload is gone. Choose the file again.")
    path = _folder() / f"{token}.csv"
    if not path.exists():
        raise Invalid("That upload is gone. Choose the file again.")
    return _parse(path.read_bytes())


def _parse(raw: bytes) -> tuple[list[str], list[list[str]]]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        raise Invalid("The file has no rows.")
    header = [h.strip() for h in rows[0]]
    body = rows[1:]
    if not body:
        raise Invalid("The file has a header but no rows under it.")
    if len(body) > MAX_ROWS:
        raise Invalid(f"An import takes at most {MAX_ROWS:,} rows at a time; this file has {len(body):,}.")
    return header, body


def targets(etype) -> list[tuple[str, str]]:
    """What a column can go into: (target, label)."""
    out = []
    if not etype.name_from:
        out.append(("name", "Name"))
    out += [("slug", "Slug"), ("status", "Status")]
    if etype.located_in != ():
        out.append(("location", "Location"))
    out += [("tags", "Tags"), ("notes", "Notes")]
    out += [("f." + f.key, f.label) for f in etype.fields]
    out += [("c." + cf.key, cf.label) for cf in records.custom_fields(etype.key)]
    return out


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def suggest(header, etype) -> list[str]:
    """A target for each column whose heading names one, by label or key."""
    options = targets(etype)
    by = {}
    for target, label in options:
        for word in (label, target.split(".")[-1]):
            by.setdefault(_norm(word), target)
    taken, out = set(), []
    for h in header:
        t = by.get(_norm(h), "")
        if t in taken:
            t = ""
        taken.add(t)
        out.append(t)
    return out


def _etype_or_invalid(key):
    reg = registry()
    etype = reg.type(key or "")
    if etype is None or not reg.is_enabled(etype.module):
        raise Invalid("Choose the kind of record to import.")
    return etype


@bp.route("/import/upload", methods=["POST"])
@role("editor")
def import_upload():
    """Step 1: the file and the kind of record. Answers with the column
    matching step, as HTML for the dialog."""
    try:
        etype = _etype_or_invalid(request.form.get("type"))
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            raise Invalid("Choose a CSV file.")
        raw = upload.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise Invalid(f"A CSV to import is limited to {MAX_BYTES // (1024 * 1024)} MB.")
        header, body = _parse(raw)
    except Invalid as err:
        return jsonify(error=str(err)), 400
    token = _secrets.token_urlsafe(24)
    (_folder() / f"{token}.csv").write_bytes(raw)
    samples = [[row[i] if i < len(row) else "" for row in body[:3]] for i in range(len(header))]
    return jsonify(ok=True, html=render_template(
        "partials/import_map.html", etype=etype, token=token, header=header, samples=samples,
        options=targets(etype), chosen=suggest(header, etype), rows=len(body), filename=upload.filename))


def _mapping(data, header, etype) -> dict[int, str]:
    allowed = {t for t, _ in targets(etype)}
    out, seen = {}, set()
    for i in range(len(header)):
        target = data.get(f"col{i}") or ""
        if not target:
            continue
        if target not in allowed:
            raise Invalid(f"“{header[i]}” goes into a field that {etype.text(True)} don't have. Choose again.")
        if target in seen:
            raise Invalid(f"Two columns go into the same field. Choose one for “{header[i]}”.")
        seen.add(target)
        out[i] = target
    return out


class _Resolver:
    """Turns what a spreadsheet says (a name, a path, a label) into what
    ``records`` takes (an id, a value)."""

    def __init__(self, etype):
        self.etype = etype
        self.reg = registry()
        self.cache: dict[tuple, dict] = {}

    def _index(self, keys) -> dict[str, list[Entity]]:
        key = tuple(sorted(keys))
        if key not in self.cache:
            idx: dict[str, list[Entity]] = {}
            for e in Entity.live().filter(Entity.type.in_(key)):
                for word in {e.name.lower(), e.slug.lower()}:
                    idx.setdefault(word, []).append(e)
                if self.reg.type(e.type) and self.reg.type(e.type).location:
                    path = present.path_label(e.location_id, " > ")
                    full = f"{path} > {e.name}" if path else e.name
                    idx.setdefault(_path_key(full), []).append(e)
            self.cache[key] = idx
        return self.cache[key]

    def find(self, text, keys, what) -> int:
        idx = self._index(keys)
        hits = idx.get(text.lower()) or idx.get(_path_key(text)) or []
        hits = list({e.id: e for e in hits}.values())
        if not hits:
            raise Invalid(f"No {what} is called “{text}”.")
        if len(hits) > 1:
            raise Invalid(f"More than one {what} is called “{text}”; use its slug or full path.")
        return hits[0].id

    def location(self, text):
        allowed = self.etype.located_in or [t.key for t in self.reg.location_types()]
        return self.find(text, allowed, "place")

    def value(self, f, text):
        if f.kind == "select":
            for value, label in f.options:
                if text.lower() in (value.lower(), label.lower()):
                    return value
            raise Invalid(f"{f.label} must be one of: {', '.join(label for _, label in f.options)}.")
        if f.kind == "ref":
            return self.find(text, self.reg.ref_types(f), f.label.lower())
        return text

    def status(self, text):
        for value, label in self.etype.statuses:
            if text.lower() in (value.lower(), label.lower()):
                return value
        raise Invalid("Status must be one of: " + ", ".join(label for _, label in self.etype.statuses) + ".")


def _path_key(text: str) -> str:
    return " > ".join(p.strip().lower() for p in re.split(r"\s*(?:>|›|/)\s*", text) if p.strip())


def _row_data(row, mapping, resolver, updating) -> dict:
    etype, data = resolver.etype, {"fields": {}, "custom": {}}
    fields = {f.key: f for f in etype.fields}
    custom = {cf.key: F.custom_field(cf) for cf in records.custom_fields(etype.key)}
    for i, target in mapping.items():
        text = (row[i] if i < len(row) else "").strip()
        if text.startswith("'") and text[1:2] in ("=", "+", "-", "@"):
            text = text[1:]         # our own export's guard against formulas
        if text == "":
            continue                # an empty cell leaves the field as it is
        if target == "location":
            data["location_id"] = resolver.location(text)
        elif target == "status":
            data["status"] = resolver.status(text)
        elif target in ("name", "slug", "tags", "notes"):
            data[target] = text.lower() if target == "slug" else text
        elif target.startswith("f."):
            f = fields[target[2:]]
            data["fields"][f.key] = resolver.value(f, text)
        elif target.startswith("c."):
            f = custom[target[2:]]
            data["custom"][f.key] = resolver.value(f, text)
    if not updating and not etype.name_from and not data.get("name"):
        raise Invalid("The name is empty.")
    return data


def run_import(etype, header, body, mapping, match) -> list[dict]:
    """Every row: {"row", "name", "action", "error"}. Callers commit or roll
    back; a failing row is already rolled back to before it."""
    resolver = _Resolver(etype)
    results = []
    name_col = next((i for i, t in mapping.items() if t == "name"), None)
    slug_col = next((i for i, t in mapping.items() if t == "slug"), None)
    for n, row in enumerate(body, start=2):         # row 1 is the header
        label = (row[name_col] if name_col is not None and name_col < len(row) else "") or f"Row {n}"
        existing = None
        if match in ("name", "slug"):
            col = name_col if match == "name" else slug_col
            key = (row[col].strip() if col is not None and col < len(row) else "")
            if key:
                q = Entity.live().filter(Entity.type == etype.key)
                q = q.filter(func.lower(Entity.name) == key.lower()) if match == "name" else \
                    q.filter(Entity.slug == key.lower())
                found = q.all()
                if len(found) > 1:
                    results.append({"row": n, "name": label, "action": "skip",
                                    "error": f"More than one {etype.text()} is called “{key}”."})
                    continue
                existing = found[0] if found else None
        try:
            with db.session.begin_nested():
                data = _row_data(row, mapping, resolver, updating=existing is not None)
                if existing is not None:
                    changes = records.update(existing, data)
                    action = "update" if changes else "same"
                    entity = existing
                else:
                    entity = records.create(etype.key, data)
                    action = "create"
            results.append({"row": n, "name": entity.name, "action": action, "error": ""})
        except Invalid as err:
            results.append({"row": n, "name": label, "action": "skip", "error": str(err)})
    return results


def _import_args():
    data = request.get_json(silent=True) or {}
    etype = _etype_or_invalid(data.get("type"))
    header, body = _read(data.get("token"))
    mapping = _mapping(data, header, etype)
    if not mapping:
        raise Invalid("Choose where at least one column goes.")
    if not etype.name_from and "name" not in mapping.values() and data.get("match") != "slug":
        raise Invalid("Choose the column that holds the name.")
    if etype.name_from and f"f.{etype.name_from}" not in mapping.values():
        raise Invalid(f"Choose the column that holds the {etype.name_from.replace('_', ' ')}.")
    match = data.get("match") if data.get("match") in ("none", "name", "slug") else "none"
    if match == "slug" and "slug" not in mapping.values():
        raise Invalid("To match on the slug, choose the column that holds it.")
    return data, etype, header, body, mapping, match


def _summary(results):
    return {k: sum(1 for r in results if r["action"] == k) for k in ("create", "update", "same", "skip")}


@bp.route("/import/check", methods=["POST"])
@role("editor")
def import_check():
    """Step 2: the whole import, rolled back. Answers with what it would do."""
    try:
        data, etype, header, body, mapping, match = _import_args()
        results = run_import(etype, header, body, mapping, match)
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    db.session.rollback()
    problems = [r for r in results if r["error"]]
    shown = (problems + [r for r in results if not r["error"]])[:PREVIEW_ROWS]
    body_json = {k: v for k, v in data.items()}
    return jsonify(ok=True, html=render_template(
        "partials/import_check.html", etype=etype, results=shown, total=len(results), counts=_summary(results),
        body=body_json))


@bp.route("/import/run", methods=["POST"])
@role("editor")
def import_run():
    """Step 3: the import. Rows with a problem are skipped; the rest are saved."""
    try:
        data, etype, header, body, mapping, match = _import_args()
        results = run_import(etype, header, body, mapping, match)
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    db.session.commit()
    (_folder() / f"{data['token']}.csv").unlink(missing_ok=True)
    counts = _summary(results)
    said = [f"{counts['create']} made" if counts["create"] else "", f"{counts['update']} updated" if counts["update"] else "",
            f"{counts['skip']} left out" if counts["skip"] else ""]
    return jsonify(ok=True, created=counts["create"], updated=counts["update"], skipped=counts["skip"],
                   message="Imported: " + (", ".join(s for s in said if s) or "nothing changed"))


# ———— The whole instance as JSON ————

def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return None
    return value


def export_all() -> dict:
    """Every table, every row, except what unlocks something: password
    hashes, secret values, API token hashes and the Turnstile secret. Files
    are listed, not included; ``flask backup`` has those."""
    tables = {}
    for table in db.metadata.sorted_tables:
        cols = [c.name for c in table.columns if (table.name, c.name) not in LEFT_OUT]
        rows = []
        for r in db.session.execute(table.select()).mappings():
            if table.name == "settings" and r["key"] in LEFT_OUT_SETTINGS:
                continue
            rows.append({c: _json_value(r[c]) for c in cols})
        tables[table.name] = rows
    reg = registry()
    return {
        "format": "hyprvolt-export",
        "version": 1,
        "app_version": __version__,
        "exported_at": utcnow().isoformat(timespec="seconds") + "Z",
        "left_out": ["users.password_hash", "vault_secrets.ciphertext", "api_tokens.token_hash",
                     "settings.turnstile_secret_key", "attachment files and the text read from them",
                     "entities.search_text"],
        "modules": [{"id": m.id, "name": m.name, "enabled": reg.is_enabled(m.id),
                     "types": [t.key for t in m.types]} for m in reg.modules.values()],
        "tables": tables,
    }


@bp.route("/admin/export.json")
@role("admin")
def export_json():
    body = json.dumps(export_all(), ensure_ascii=False, indent=1)
    return Response(body, mimetype="application/json", headers={
        "Content-Disposition": f'attachment; filename="hyprvolt-export-{date.today().isoformat()}.json"',
        "Cache-Control": "no-store"})
