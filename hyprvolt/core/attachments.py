"""Files attached to entities.

Stored under ``DATA_DIR/attachments/<2 hex>/<32 hex>``: the name on disk is
generated, never taken from the upload, so no filename can reach outside the
directory or collide with another. The name the user gave is kept as a label
and as the download name. ``flask backup`` copies the directory with the
database.

Text files and PDFs are read for search (``extract``): their words join the
record's search text, so a record is found by what its files say. That
happens when a file is uploaded, and for older files in the worker's
``index_pending`` pass.
"""
import hashlib
import logging
import os
import re
import secrets
from pathlib import Path

from flask import current_app

from ..models import db, int_setting
from .fields import Invalid
from .models import Attachment

log = logging.getLogger(__name__)
CHUNK = 1 << 16
#: How much of one file search keeps, and how much it reads to get there.
TEXT_LIMIT = 200_000
READ_LIMIT = 4 * 1024 * 1024
MAX_PDF_PAGES = 300
INDEX_PER_PASS = 25
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/x-yaml", "application/yaml",
              "application/x-sh", "application/javascript", "application/toml", "application/sql")
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml", ".toml",
                   ".ini", ".conf", ".cfg", ".log", ".sh", ".bash", ".ps1", ".psm1", ".bat", ".cmd", ".py",
                   ".sql", ".js", ".html", ".htm", ".rst", ".env", ".properties", ".nginx", ".service"}
#: Shown in the browser rather than downloaded. Everything else downloads.
INLINE = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain"}


def root() -> Path:
    return Path(current_app.config.get("ATTACHMENTS_DIR") or Path(current_app.config["DATA_DIR"]) / "attachments")


STORED_RE = re.compile(r"^[0-9a-f]{32}$")


def path_for(att: Attachment) -> Path:
    """Where the file is. ``stored_as`` is always a name the app made (32 hex
    digits); anything else (a restored database someone edited) points
    nowhere, rather than at another file on the server."""
    name = att.stored_as or ""
    if not STORED_RE.match(name):
        return root() / "missing" / "missing"
    return root() / name[:2] / name


def max_bytes() -> int:
    return int_setting("max_upload_mb", 25) * 1024 * 1024


def save(entity, upload, user=None) -> Attachment:
    """Stream an upload to disk, hashing as it goes. Refuses it past the size
    limit without keeping a partial file."""
    filename = os.path.basename((upload.filename or "").replace("\\", "/")).strip()[:255]
    if not filename:
        raise Invalid("Choose a file to attach.")
    limit = max_bytes()
    stored = secrets.token_hex(16)
    target = root() / stored[:2] / stored
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    tmp = target.with_suffix(".part")
    try:
        with open(tmp, "wb") as out:
            while True:
                chunk = upload.stream.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise Invalid(f"Files are limited to {limit // (1024 * 1024)} MB.")
                digest.update(chunk)
                out.write(chunk)
        tmp.rename(target)
    finally:
        if tmp.exists():
            tmp.unlink()
    content_type = (upload.mimetype or "application/octet-stream")[:120]
    att = Attachment(entity_id=entity.id, filename=filename, stored_as=stored,
                     content_type=content_type, size=size, sha256=digest.hexdigest(),
                     created_by_id=user.id if user else None)
    att.text = extract(att)
    db.session.add(att)
    return att


def _kind(att: Attachment) -> str:
    """"text", "pdf" or "" for a file search can't read."""
    suffix = Path(att.filename or "").suffix.lower()
    if att.content_type == "application/pdf" or suffix == ".pdf":
        return "pdf"
    if att.content_type.startswith(TEXT_TYPES) or suffix in TEXT_EXTENSIONS:
        return "text"
    return ""


def extract(att: Attachment) -> str:
    """The words in a file, for search: text files as they are, PDFs page
    by page. "" for anything else, or a file that can't be read."""
    kind, path = _kind(att), path_for(att)
    if not kind or not path.exists():
        return ""
    try:
        if kind == "text":
            with open(path, "rb") as f:
                text = f.read(READ_LIMIT).decode("utf-8", errors="replace")
        else:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            chunks, total = [], 0
            for page in reader.pages[:MAX_PDF_PAGES]:
                chunk = page.extract_text() or ""
                chunks.append(chunk)
                total += len(chunk)
                if total > TEXT_LIMIT:
                    break
            text = "\n".join(chunks)
    except Exception:          # a damaged or encrypted file is still attached, just not searchable
        log.warning("could not read %s (attachment %s) for search", att.filename, att.id, exc_info=True)
        return ""
    return " ".join(text.split())[:TEXT_LIMIT]


def index_pending() -> int:
    """The worker's pass: read the files attached before search read them,
    a few at a time, and refresh their records' search text."""
    from . import records
    from .models import Entity
    rows = (Attachment.query.filter(Attachment.text.is_(None))
            .order_by(Attachment.id).limit(INDEX_PER_PASS).all())
    touched = set()
    for att in rows:
        att.text = extract(att)
        touched.add(att.entity_id)
    for entity_id in touched:
        entity = db.session.get(Entity, entity_id)
        if entity is not None:
            records.reindex(entity)
    return len(rows)


def remove_files(entity_ids=None, attachments=None) -> None:
    """Delete the files behind these entities' attachments (or these
    attachments), before their rows go. Their thumbnails go too."""
    from .images import forget
    rows = list(attachments or [])
    if entity_ids:
        rows += Attachment.query.filter(Attachment.entity_id.in_(entity_ids)).all()
    for att in rows:
        forget(att)
        try:
            path_for(att).unlink()
        except FileNotFoundError:
            pass


def human_size(size: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size} {unit}" if unit == "bytes" else f"{size:.1f} {unit}".replace(".0 ", " ")
        size /= 1024
    return f"{size} GB"
