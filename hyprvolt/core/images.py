"""A record's pictures: its featured image and its gallery.

The featured image has a place of its own at the top of the Overview and on
the record's card. It is stored like an attachment (the same folder, the
same backups and purge) and named by ``entities.image_id``, but it is not
listed with the attachments. The gallery is the record's other attached
images (PNG, JPEG, GIF, WebP).

Cards and galleries show thumbnails, not the originals a phone takes (often
several MB each). Pillow makes them the first time they are asked for, turned
the right way up, as WebP without the original's metadata (a photo's location
included), and keeps them under ``DATA_DIR/thumbs``. They can always be made
again, so a backup leaves them out.
"""
import logging
import threading
from pathlib import Path

from flask import current_app

from .attachments import STORED_RE, path_for
from .models import IMAGE_TYPES, Attachment, Entity

log = logging.getLogger(__name__)
#: The longest side of each size: a card or gallery tile, and the large view.
SIZES = {"sm": 480, "lg": 1600}
#: Larger than any camera makes; past it, a file is more likely a trap.
MAX_PIXELS = 120_000_000
# A page of cards asks for many thumbnails at once; make a few at a time.
_making = threading.Semaphore(2)


def thumbs_root() -> Path:
    return Path(current_app.config.get("THUMBS_DIR") or Path(current_app.config["DATA_DIR"]) / "thumbs")


def thumb_path(att: Attachment, size: str) -> Path | None:
    name = att.stored_as or ""
    if size not in SIZES or not STORED_RE.match(name):
        return None
    return thumbs_root() / size / name[:2] / f"{name}.webp"


def thumbnail(att: Attachment, size: str) -> Path | None:
    """The thumbnail's file, made now if it isn't there yet. None for a size
    that doesn't exist or a file Pillow can't read."""
    target = thumb_path(att, size)
    if target is None or not att.is_image:
        return None
    if target.exists():
        return target
    with _making:
        if target.exists():          # made by another request while this one waited
            return target
        try:
            _make(path_for(att), target, SIZES[size])
        except Exception:
            log.warning("could not make a thumbnail of %s (attachment %s)", att.filename, att.id, exc_info=True)
            return None
    return target


def _make(source: Path, target: Path, longest: int) -> None:
    from PIL import Image, ImageOps
    with Image.open(source) as im:
        if im.width * im.height > MAX_PIXELS:
            raise ValueError(f"{im.width}x{im.height} is too large to open")
        im.draft("RGB", (longest, longest))      # JPEGs decode at a fraction of their size
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P", "PA") else "RGB")
        im.thumbnail((longest, longest), Image.Resampling.LANCZOS)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".part")
        try:
            im.save(tmp, "WEBP", quality=82, method=4)
            tmp.rename(target)
        finally:
            if tmp.exists():
                tmp.unlink()


def forget(att: Attachment) -> None:
    """Delete an attachment's thumbnails, with the file."""
    for size in SIZES:
        path = thumb_path(att, size)
        if path is not None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def featured_of(entities) -> dict[int, Attachment]:
    """entity id -> its featured image, for a page of cards, in one query."""
    wanted = {e.image_id: e.id for e in entities if e.image_id}
    if not wanted:
        return {}
    rows = Attachment.query.filter(Attachment.id.in_(wanted), Attachment.deleted_at.is_(None),
                                   Attachment.content_type.in_(IMAGE_TYPES))
    return {wanted[a.id]: a for a in rows if a.entity_id == wanted[a.id]}


def featured(entity: Entity) -> Attachment | None:
    return featured_of([entity]).get(entity.id)


def gallery(entity: Entity) -> list[Attachment]:
    """The record's other pictures: its attached images, oldest first, the
    featured image left out."""
    return (Attachment.query.filter(Attachment.entity_id == entity.id, Attachment.deleted_at.is_(None),
                                    Attachment.content_type.in_(IMAGE_TYPES),
                                    Attachment.id != (entity.image_id or 0))
            .order_by(Attachment.created_at, Attachment.id).all())


def urls(att: Attachment) -> dict:
    from urllib.parse import quote
    base = f"/attachments/{att.id}"
    return {"url": f"{base}/{quote(att.filename)}", "thumb": f"{base}/thumb/sm", "large": f"{base}/thumb/lg"}

