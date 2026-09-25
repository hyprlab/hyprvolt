"""Files attached to entities.

Stored under ``DATA_DIR/attachments/<2 hex>/<32 hex>``: the name on disk is
generated, never taken from the upload, so no filename can reach outside the
directory or collide with another. The name the user gave is kept as a label
and as the download name. ``flask backup`` copies the directory with the
database.
"""
import hashlib
import os
import secrets
from pathlib import Path

from flask import current_app

from ..config import DATA_DIR
from ..models import db, int_setting
from .fields import Invalid
from .models import Attachment

CHUNK = 1 << 16
#: Shown in the browser rather than downloaded. Everything else downloads.
INLINE = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain"}


def root() -> Path:
    return Path(current_app.config.get("ATTACHMENTS_DIR") or DATA_DIR / "attachments")


def path_for(att: Attachment) -> Path:
    return root() / att.stored_as[:2] / att.stored_as


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
    db.session.add(att)
    return att


def remove_files(entity_ids=None, attachments=None) -> None:
    """Delete the files behind these entities' attachments (or these
    attachments), before their rows go."""
    rows = list(attachments or [])
    if entity_ids:
        rows += Attachment.query.filter(Attachment.entity_id.in_(entity_ids)).all()
    for att in rows:
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
