"""Backups and restores, from Settings > Backups; no terminal needed.

A backup is one ``.tar.gz``: ``backup.json`` (what it holds, and which
version made it), the database (``hyprvolt.db``, copied with SQLite's online
backup API, so it is consistent while the app runs) and every attached file
(``attachments/``). The secrets key is never in it: a backup that goes astray
is no use without the key, which is downloaded and put back on its own.

Backups live in ``BACKUP_DIR`` (the data volume's ``backups/`` unless set).
The worker makes one every ``backup_hours`` and keeps the newest
``backup_keep`` automatic ones; the ones made by hand stay until deleted.

A restore checks the archive, saves the instance as it is first (so a
restore can itself be undone, by restoring that), copies the database into
the live one with the same backup API, swaps the attachments, brings the
database up to this version, and changes the session epoch: every sign-in
from before it ends, except the admin's who restored, if their account is an
admin in the backup too.
"""
import io
import json
import re
import secrets as _secrets
import shutil
import sqlite3
import tarfile
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, render_template, request, send_file, session
from flask_login import current_user, login_user

from .. import __version__
from ..models import ApiToken, User, db, int_setting, set_setting, utcnow
from ..permissions import role, session_only
from . import attachments as files
from .fields import Invalid

bp = Blueprint("backups", __name__)

FORMAT = "hyprvolt-backup"
KINDS = {"manual": "Made by hand", "auto": "Automatic", "before-restore": "Before a restore",
         "uploaded": "Uploaded"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.(tar\.gz|tgz|tar)$")
DB_NAME = "hyprvolt.db"
MANIFEST = "backup.json"


# ———— Where things are ————

def folder() -> Path:
    path = Path(current_app.config["BACKUP_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def _trash() -> Path:
    path = folder() / ".deleted"
    path.mkdir(exist_ok=True)
    return path


def db_path() -> Path:
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        raise Invalid("Backups here only know how to copy a SQLite database.")
    return Path(uri.removeprefix("sqlite:///"))


def path_of(name: str, trashed: bool = False) -> Path:
    if not SAFE_NAME.match(name or ""):
        abort(404, description="There is no such backup.")
    path = (_trash() if trashed else folder()) / name
    if not path.is_file():
        abort(404, description="There is no such backup.")
    return path


# ———— Making one ————

def copy_db(target: Path) -> None:
    src = sqlite3.connect(db_path())
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _counts(conn) -> dict:
    def one(sql):
        try:
            return conn.execute(sql).fetchone()[0]
        except sqlite3.Error:
            return 0
    return {"records": one("SELECT COUNT(*) FROM entities WHERE deleted_at IS NULL"),
            "users": one("SELECT COUNT(*) FROM users"),
            "attachments": one("SELECT COUNT(*) FROM attachments WHERE deleted_at IS NULL")}


def write_archive(dest: Path, kind: str = "manual", user=None, with_files: bool = True) -> dict:
    """The archive at ``dest`` (gzip unless it ends in .tar). Returns its
    manifest."""
    root = files.root()
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / DB_NAME
        copy_db(db_copy)
        conn = sqlite3.connect(db_copy)
        counts = _counts(conn)
        conn.close()
        manifest = {"format": FORMAT, "version": 1, "app_version": __version__,
                    "made_at": utcnow().isoformat(timespec="seconds") + "Z", "kind": kind,
                    "made_by": user.display_name if user is not None else "", **counts}
        mode = "w" if str(dest).endswith(".tar") else "w:gz"
        with tarfile.open(dest, mode) as tar:
            raw = json.dumps(manifest, indent=1).encode()
            info = tarfile.TarInfo(MANIFEST)
            info.size, info.mtime = len(raw), int(time.time())
            tar.addfile(info, io.BytesIO(raw))           # first, so a listing reads only this
            tar.add(db_copy, arcname=DB_NAME)
            if with_files and root.is_dir():
                tar.add(root, arcname="attachments")
    return manifest


def make(kind: str = "manual", user=None) -> Path:
    """A new backup in the backups folder; written under a temporary name
    and renamed, so a listing never shows half of one."""
    stamp = utcnow().strftime("%Y-%m-%d-%H%M%S")
    name, n = f"hyprvolt-{kind}-{stamp}.tar.gz", 2
    while (folder() / name).exists():
        name, n = f"hyprvolt-{kind}-{stamp}-{n}.tar.gz", n + 1
    part = folder() / f".{name}.part"
    try:
        write_archive(part, kind, user)
        part.rename(folder() / name)
    finally:
        part.unlink(missing_ok=True)
    return folder() / name


# ———— Reading them ————

def manifest_of(path: Path) -> dict | None:
    try:
        with tarfile.open(path) as tar:
            first = tar.next()
            if first is not None and first.name == MANIFEST and first.isfile():
                return json.loads(tar.extractfile(first).read())
    except (tarfile.TarError, OSError, ValueError):
        return None
    return None


def _kind(name: str, manifest) -> str:
    if manifest and manifest.get("kind") in KINDS:
        return manifest["kind"]
    m = re.match(r"hyprvolt-(manual|auto|before-restore|uploaded)-", name)
    return m.group(1) if m else "manual"


def listing() -> list[dict]:
    out = []
    for p in folder().iterdir():
        if not p.is_file() or not SAFE_NAME.match(p.name):
            continue
        manifest = manifest_of(p)
        made = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).replace(tzinfo=None)   # UTC, as stored
        if manifest and manifest.get("made_at"):
            try:
                made = datetime.fromisoformat(manifest["made_at"].rstrip("Z"))
            except ValueError:
                pass
        kind = _kind(p.name, manifest)
        out.append({"name": p.name, "size": p.stat().st_size, "size_label": files.human_size(p.stat().st_size),
                    "made_at": made, "kind": kind,
                    "kind_label": KINDS[kind], "manifest": manifest or {}})
    return sorted(out, key=lambda b: b["made_at"], reverse=True)


def _version(text) -> tuple:
    """A version in SemVer order: 1.4.0-beta.2 comes after 1.4.0-beta.1 and
    before 1.4.0, so a beta won't restore a backup its stable made."""
    core, _, pre = str(text or "0").partition("-")
    numbers = tuple(int(x) for x in re.findall(r"\d+", core)[:3])
    numbers += (0,) * (3 - len(numbers))
    if not pre:
        return numbers + (1,)
    return numbers + (0,) + tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))


def inspect(path: Path) -> dict:
    """What a backup holds, or ``Invalid`` saying why it can't be restored."""
    try:
        tar = tarfile.open(path)
    except (tarfile.TarError, OSError):
        raise Invalid("This isn't a backup Hyprvolt can read: it isn't a .tar.gz archive.") from None
    with tar, tempfile.TemporaryDirectory() as tmp:
        names = tar.getnames()
        for m in tar.getmembers():
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                raise Invalid("This archive has files outside its own folder, so it won't be restored.")
            if not (m.isfile() or m.isdir()):
                raise Invalid("This archive has links or devices in it, which a Hyprvolt backup never has.")
        if DB_NAME not in names:
            raise Invalid(f"This isn't a Hyprvolt backup: it has no {DB_NAME}.")
        manifest = manifest_of(path) or {}
        if manifest and _version(manifest.get("app_version")) > _version(__version__):
            raise Invalid(f"It was made by Hyprvolt {manifest['app_version']}, newer than this one "
                          f"({__version__}). Update this instance first.")
        tar.extract(DB_NAME, tmp, filter="data")
        conn = sqlite3.connect(Path(tmp) / DB_NAME)
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise Invalid("The database in this backup is damaged.")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"users", "entities"} <= tables:
                raise Invalid("This isn't a Hyprvolt backup: its database has no records or accounts.")
            admins = [r[0] for r in conn.execute("SELECT username FROM users WHERE role = 'admin'")]
            if not admins:
                raise Invalid("This backup has no admin account, so nobody could sign in to manage it.")
            counts = _counts(conn)
        except sqlite3.DatabaseError:
            raise Invalid("The database in this backup can't be read.") from None
        finally:
            conn.close()
        attached = sum(1 for m in tar.getmembers() if m.isfile() and m.name.startswith("attachments/"))
    made = manifest.get("made_at")
    return {"made_at": datetime.fromisoformat(made.rstrip("Z")) if made else None,
            "app_version": manifest.get("app_version") or "an earlier version",
            "kind": manifest.get("kind") or "", "made_by": manifest.get("made_by") or "",
            "admins": admins, "files": attached, **counts}


# ———— Restoring one ————

def restore(path: Path, user=None) -> dict:
    """Replace this instance with the backup at ``path``. Returns what was
    restored and the name of the backup of what was here before."""
    from .. import _migrate
    from .. import setup as setup_module
    from .reminders import refresh_all
    info = inspect(path)
    safety = make("before-restore", user)
    live_files = files.root()
    work = Path(tempfile.mkdtemp(dir=Path(current_app.config["DATA_DIR"]), prefix=".restore-"))
    try:
        with tarfile.open(path) as tar:
            members = [m for m in tar.getmembers()
                       if m.name == DB_NAME or m.name == "attachments" or m.name.startswith("attachments/")]
            tar.extractall(work, members=members, filter="data")
        # The database: copied into the live one page by page, under
        # SQLite's own locking, rather than swapping the file under the app.
        db.session.remove()
        db.engine.dispose()
        src = sqlite3.connect(work / DB_NAME)
        dst = sqlite3.connect(db_path(), timeout=60)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        # The files: the backup's in, the old ones out.
        old = work / "old-attachments"
        if live_files.exists():
            shutil.move(str(live_files), str(old))
        if (work / "attachments").is_dir():
            shutil.move(str(work / "attachments"), str(live_files))
        else:
            live_files.mkdir(parents=True, exist_ok=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # Up to this version, with its reminders, and nobody signed in as whoever
    # had their id before.
    _migrate(current_app._get_current_object())
    refresh_all()
    db.session.commit()
    set_setting("session_epoch", _secrets.token_hex(8))
    # The restored tokens are the backup's: one revoked since would be back.
    # A restore revokes them all; people make new ones.
    ApiToken.query.filter(ApiToken.revoked_at.is_(None)).update({"revoked_at": utcnow()})
    db.session.commit()
    setup_module._completed["done"] = False
    return {**info, "safety": safety.name}


# ———— The worker: automatic backups, and clearing up ————

def scheduled() -> int:
    """Make the automatic backup when one is due, keep the newest
    ``backup_keep``, and empty the deleted ones after ``purge_days``."""
    touched = 0
    hours = int_setting("backup_hours", 24)
    autos = [b for b in listing() if b["kind"] == "auto"]
    # A few minutes' slack, so a pass that runs just early doesn't skip a day.
    if hours > 0 and (not autos or utcnow() - autos[0]["made_at"] >= timedelta(hours=hours, minutes=-5)):
        make("auto")
        touched += 1
        autos = [b for b in listing() if b["kind"] == "auto"]
    for b in autos[max(int_setting("backup_keep", 7), 1):]:
        (folder() / b["name"]).unlink(missing_ok=True)
        touched += 1
    cutoff = time.time() - int_setting("purge_days", 30) * 86400
    for p in list(_trash().iterdir()) + list(folder().glob(".*.part")):
        if p.is_file() and p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)
            touched += 1
    return touched


# ———— Routes, admin only ————

def _json(b: dict) -> dict:
    m = b["manifest"]
    return {"name": b["name"], "size": b["size"], "made_at": b["made_at"].isoformat(), "kind": b["kind"],
            "app_version": m.get("app_version"), "records": m.get("records"), "users": m.get("users"),
            "attachments": m.get("attachments")}


@bp.route("/admin/backups")
@role("admin")
@session_only
def backup_list():
    return jsonify(backups=[_json(b) for b in listing()], folder=str(folder()))


@bp.route("/admin/backups", methods=["POST"])
@role("admin")
@session_only
def backup_make():
    try:
        path = make("manual", current_user)
    except Invalid as err:
        return jsonify(error=str(err)), 400
    return jsonify(ok=True, backup=next(_json(b) for b in listing() if b["name"] == path.name))


@bp.route("/admin/backups/<name>")
@role("admin")
@session_only
def backup_download(name):
    return send_file(path_of(name), mimetype="application/gzip", as_attachment=True, download_name=name,
                     max_age=0)


@bp.route("/admin/backups/<name>/check", methods=["POST"])
@role("admin")
@session_only
def backup_check(name):
    """What restoring this backup would do, as HTML for Settings > Backups."""
    try:
        info = inspect(path_of(name))
    except Invalid as err:
        return jsonify(error=str(err)), 400
    return jsonify(ok=True, html=render_template("partials/backup_check.html", name=name, info=info,
                                                 kinds=KINDS))


@bp.route("/admin/backups/upload", methods=["POST"])
@role("admin")
@session_only
def backup_upload():
    """A backup downloaded earlier, or from another instance: kept in the
    backups folder once it checks out, and answered with its check."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify(error="Choose a backup file, a .tar.gz."), 400
    stamp = utcnow().strftime("%Y-%m-%d-%H%M%S")
    name = f"hyprvolt-uploaded-{stamp}.tar.gz"
    part = folder() / f".{name}.part"
    try:
        upload.save(part)
        info = inspect(part)
        part.rename(folder() / name)
    except Invalid as err:
        return jsonify(error=str(err)), 400
    finally:
        part.unlink(missing_ok=True)
    return jsonify(ok=True, name=name, html=render_template("partials/backup_check.html", name=name, info=info,
                                                            kinds=KINDS))


@bp.route("/admin/backups/<name>/restore", methods=["POST"])
@role("admin")
@session_only
def backup_restore(name):
    path = path_of(name)
    username = current_user.username
    try:
        done = restore(path, current_user._get_current_object())
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    # Still here if the backup has this account as an admin; signed out if not.
    me = User.query.filter_by(username=username).first()
    stays = me is not None and me.is_admin
    csrf = session.get("_csrf")
    session.clear()
    if stays:
        login_user(me)
        if csrf:
            session["_csrf"] = csrf
    made = done["made_at"].strftime("%b %-d, %Y %H:%M") if done["made_at"] else "the backup"
    return jsonify(ok=True, signed_out=not stays, before=done["safety"],
                   message=f"Restored the backup of {made}. What was here before is kept as a backup too.")


@bp.route("/admin/backups/<name>/delete", methods=["POST"])
@role("admin")
@session_only
def backup_delete(name):
    path = path_of(name)
    path.rename(_trash() / name)
    return jsonify(ok=True, undo={"url": f"/admin/backups/{name}/undelete", "body": {}})


@bp.route("/admin/backups/<name>/undelete", methods=["POST"])
@role("admin")
@session_only
def backup_undelete(name):
    path = path_of(name, trashed=True)
    path.rename(folder() / name)
    return jsonify(ok=True)
