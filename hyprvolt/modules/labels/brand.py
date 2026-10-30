"""What brands an asset tag: the organization that owns the equipment,
printed "Property of …", and its logo. An admin sets both in Settings >
Asset labels.

The name is a setting; the logo is kept in a table of its own (one row),
so a backup carries it with the database. A PNG, JPEG or WebP logo is
made a PNG no larger than it needs to be to print sharp; an SVG is kept as
it is, once it is known to be one, and is only ever shown as a picture.
"""
import io
import xml.etree.ElementTree as ET

from hyprvolt.core.fields import Invalid
from hyprvolt.models import db, get_setting, set_setting, utcnow

OWNER = "labels:owner"
OWNER_MAX = 80
#: The largest logo taken, before it is made smaller.
MAX_BYTES = 2 * 1024 * 1024
#: A raster logo is scaled down to fit this, in pixels: over 600 dpi on a tag.
FIT = (1200, 600)
TYPES = "image/png,image/jpeg,image/webp,image/svg+xml,.svg"


class LabelLogo(db.Model):
    __tablename__ = "label_logo"
    id = db.Column(db.Integer, primary_key=True)
    content_type = db.Column(db.String(40), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow)


def owner() -> str:
    return get_setting(OWNER) or ""


def set_owner(name: str) -> None:
    name = " ".join((name or "").split())
    if len(name) > OWNER_MAX:
        raise Invalid(f"The organization's name can be at most {OWNER_MAX} characters.")
    set_setting(OWNER, name)


def logo() -> LabelLogo | None:
    return db.session.get(LabelLogo, 1)


def logo_url() -> str:
    """Where the tag finds the logo, changed with each new one so a browser
    doesn't print the old; "" with none."""
    found = logo()
    return f"/labels/logo?v={int(found.updated_at.timestamp())}" if found else ""


def _svg(data: bytes) -> bytes:
    # No DOCTYPE, so no entities: nothing to expand and nothing to fetch.
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise Invalid("The SVG can't have a DOCTYPE. Save it again as plain SVG.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise Invalid("That SVG can't be read.") from None
    if root.tag not in ("svg", "{http://www.w3.org/2000/svg}svg"):
        raise Invalid("That file is not an SVG image.")
    return data


def _raster(data: bytes) -> bytes:
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP"):
                raise Invalid("The logo must be a PNG, JPEG, WebP or SVG image.")
            im.load()
            picture = im.convert("RGBA") if im.mode not in ("RGB", "RGBA", "L", "LA") else im.copy()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise Invalid("That picture can't be read.") from None
    picture.thumbnail(FIT)
    out = io.BytesIO()
    picture.save(out, "PNG", optimize=True)
    return out.getvalue()


def save_logo(upload) -> None:
    """Keep an uploaded logo, in place of any before it. Invalid if it isn't
    a picture the tag can print."""
    data = upload.read(MAX_BYTES + 1)
    if not data:
        raise Invalid("Choose a logo.")
    if len(data) > MAX_BYTES:
        raise Invalid("The logo can be at most 2 MB.")
    is_svg = (upload.mimetype == "image/svg+xml" or (upload.filename or "").lower().endswith(".svg")
              or data.lstrip()[:5] in (b"<?xml", b"<svg "))
    content_type = "image/svg+xml" if is_svg else "image/png"
    data = _svg(data) if is_svg else _raster(data)
    found = logo() or LabelLogo(id=1)
    found.content_type, found.data, found.updated_at = content_type, data, utcnow()
    db.session.add(found)
    db.session.commit()


def remove_logo() -> None:
    found = logo()
    if found is not None:
        db.session.delete(found)
        db.session.commit()
