"""Printable asset labels: one per record of a list, each with a QR code
that opens the record (``/e/<id>``), its name, kind, asset tag or serial,
and where it is. A 4 × 1 in asset tag adds the organization and its logo
(brand.py), the asset tag in large type, the make and model, the serial and
the management IP (its hypervisor's, or its own IP addresses), in type
large enough for a thermal printer, so without the place.

The page is offered in every list's export menu, with the list's filters,
so the labels are for exactly what the list shows; ``?id=`` makes the one
tag a record's Print asset tag button asks for. Sizes are laid out in real
units by app.css (``.labels``), one sheet per printed page. Download PDF has
the server make the same page a PDF (core/pdf.py), at the label's own size,
for a label printer to print as it is.
"""
import segno
from flask import Blueprint, abort, jsonify, render_template, request, send_file, url_for
from markupsafe import Markup

from hyprvolt.core import pdf, present
from hyprvolt.core.fields import Invalid
from hyprvolt.models import db
from hyprvolt.permissions import role

from . import brand

bp = Blueprint("labels", __name__)

LIMIT = 300
TAG = "4x1"
SIZES = (("5160", "Letter, 30 to a sheet (Avery 5160)"), ("l7160", "A4, 21 to a sheet (Avery L7160)"),
         ("62x29", "Label printer, 62 × 29 mm"), (TAG, "Label printer, 4 × 1 in asset tag"))
#: Sizes a label printer prints, one label a page.
ROLLS = ("62x29", TAG)
#: Detail fields shown as the label's code, the first a record has.
CODES = (("asset_tag", "Asset tag"), ("serial", "Serial"))


def qr(url: str) -> Markup:
    """A QR code as inline SVG. A small quiet zone: the label's own white
    margin makes up the rest."""
    return Markup(segno.make(url, error="m", micro=False)
                  .svg_inline(border=2, omitsize=True, dark="#000", svgclass="label-qr"))


def _code(detail) -> tuple[str, str]:
    for key, label in CODES:
        value = getattr(detail, key, None) if detail is not None else None
        if value:
            return label, str(value)
    return "", ""


def _value(detail, key) -> str:
    value = getattr(detail, key, None) if detail is not None else None
    return str(value).strip() if value not in (None, "") else ""


def _make(detail) -> str:
    """"Dell PowerEdge R740": the manufacturer, unless the model names it."""
    maker, model = _value(detail, "manufacturer"), _value(detail, "model")
    if maker and model.lower().startswith(maker.lower()):
        return model
    return " ".join(p for p in (maker, model) if p)


#: Where a form section other modules add holds the management IP, first
#: found first: the Management IP of the hypervisor a server runs (Virtual),
#: then the record's own IP addresses (Network), which are a device's
#: management address, or a server's iDRAC or iLO.
MANAGEMENT = (("hypervisor", "address"), ("addresses", "list"))


def _management_ip(entity) -> str:
    from hyprvolt.registry import current as registry
    reg = registry()
    etype = reg.type(entity.type)
    sections = {s.key: s for s in reg.form_sections(etype) if s.values is not None} if etype else {}
    for key, value in MANAGEMENT:
        if key in sections and (found := (sections[key].values(entity) or {}).get(value)):
            return str(found)
    return ""


def taggable(entity) -> str:
    """The record's Print asset tag page, for a kind of record with an asset
    tag (hardware); "" for any other."""
    from hyprvolt.registry import current as registry
    etype = registry().type(entity.type)
    if etype is None or not any(f.key == "asset_tag" for f in etype.fields):
        return ""
    return url_for("main.module_page", module_id="labels", key="print", id=entity.id, size=TAG)


def _with(endpoint="main.module_page", **changes) -> str:
    args = {k: v for k, v in request.args.items() if k not in changes}
    args.update({k: v for k, v in changes.items() if v is not None})
    if endpoint == "main.module_page":
        return url_for(endpoint, module_id="labels", key="print", **args)
    return url_for(endpoint, **args)


def _records() -> tuple[list, bool, str, str, str]:
    """(records, more than the limit, what they are, back, back's label):
    the one record ``?id=`` names, or what ``?list=`` shows."""
    raw = request.args.get("id", "")
    if raw:
        from hyprvolt.core.api import entity_or_404
        if not raw.isdigit():
            abort(404)
        entity = entity_or_404(int(raw))
        return [entity], False, entity.name, f"/e/{entity.id}", "Back to the record"
    from hyprvolt.main import records_listed
    module, a, rows = records_listed(request.args.get("list") or "all", LIMIT + 1)
    back_args = {k: val for k, val in request.args.items() if k not in ("list", "size")}
    back = (url_for("main.module_list", module_id=module.id, **back_args) if module
            else url_for("main.all_records", **back_args))
    what = (a["etype"].plural if a["etype"] else module.name if module else "All records")
    return rows[:LIMIT], len(rows) > LIMIT, what.lower() if what != "All records" else "all records", back, \
        "Back to the list"


def _context() -> dict:
    rows, more, what, back, back_label = _records()
    default = TAG if request.args.get("id") else SIZES[0][0]
    size = request.args.get("size") if request.args.get("size") in dict(SIZES) else default
    details = present.details_for(rows)
    entities = {e.id: e for e in rows}
    base = request.host_url.rstrip("/")
    labels = []
    for v in present.views(rows):
        detail = details.get(v.id)
        code_label, code = _code(detail)
        # The innermost two places (a rack in a room) say where to find it.
        where = " › ".join(v.path.split(" › ")[-2:]) if v.path else ""
        labels.append({"view": v, "code_label": code_label, "code": code, "where": where,
                       "asset_tag": _value(detail, "asset_tag"), "serial": _value(detail, "serial"),
                       "make": _make(detail), "qr": qr(f"{base}/e/{v.id}"),
                       "ip": _management_ip(entities[v.id]) if size == TAG else ""})
    return dict(labels=labels, more=more, limit=LIMIT, size=size, sizes=SIZES, roll=size in ROLLS, what=what,
                sizes_url={key: _with(size=key) for key, _ in SIZES}, back=back, back_label=back_label,
                pdf_url=_with("labels.pdf_copy", size=size),
                owner=brand.owner() if size == TAG else "", logo=brand.logo_url() if size == TAG else "")


def print_page() -> str:
    return render_template("labels/print.html", **_context())


@bp.route("/print.pdf")
@role("viewer")
def pdf_copy():
    """The labels as a PDF: one page a label at a label printer's size, or
    sheets of them."""
    context = _context()
    if not context["labels"]:
        abort(404, description="There is nothing to label.")
    found = brand.logo() if context["logo"] else None
    files = {"/labels/logo": (found.data, found.content_type)} if found else None
    html = render_template("labels/pdf.html", **context)
    kind = "Asset tags" if context["size"] == TAG else "Labels"
    return pdf.download(pdf.render(html, files), f"{kind} for {context['what']}")


# ———— The organization and its logo ————

@bp.route("/logo")
@role("viewer")
def logo():
    found = brand.logo()
    if found is None:
        abort(404, description="There is no logo.")
    from io import BytesIO
    resp = send_file(BytesIO(found.data), mimetype=found.content_type, max_age=0,
                     etag=str(int(found.updated_at.timestamp())), conditional=True)
    # An SVG opened on its own runs no script.
    resp.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp


@bp.route("/brand", methods=["POST"])
@role("admin")
def brand_save():
    """The organization's name, as JSON ``{"owner": "Acme Corp"}``."""
    try:
        brand.set_owner(str((request.get_json(silent=True) or {}).get("owner") or ""))
    except Invalid as err:
        return jsonify(error=str(err)), 400
    return jsonify(ok=True)


@bp.route("/logo", methods=["POST"])
@role("admin")
def logo_save():
    """A new logo, as multipart ``file``."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify(error="Choose a logo."), 400
    try:
        brand.save_logo(upload)
    except Invalid as err:
        db.session.rollback()
        return jsonify(error=str(err)), 400
    return jsonify(ok=True)


@bp.route("/logo/remove", methods=["POST"])
@role("admin")
def logo_remove():
    brand.remove_logo()
    return jsonify(ok=True)


def pane() -> str:
    return render_template("labels/pane.html", owner=brand.owner(), owner_max=brand.OWNER_MAX,
                           logo=brand.logo_url(), types=brand.TYPES)
