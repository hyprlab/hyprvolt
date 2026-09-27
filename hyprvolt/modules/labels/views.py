"""Printable asset labels: one per record of a list, each with a QR code
that opens the record (``/e/<id>``), its name, kind, asset tag or serial,
and where it is.

The page is offered in every list's export menu, with the list's filters,
so the labels are for exactly what the list shows. Sizes are laid out in
real units by app.css (``.labels``), one sheet per printed page.
"""
import segno
from flask import render_template, request, url_for
from markupsafe import Markup

from hyprvolt.core import present

LIMIT = 300
SIZES = (("5160", "Letter, 30 to a sheet (Avery 5160)"), ("l7160", "A4, 21 to a sheet (Avery L7160)"),
         ("62x29", "Label printer, 62 × 29 mm"))
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


def _with(**changes) -> str:
    args = {k: v for k, v in request.args.items() if k not in changes}
    args.update({k: v for k, v in changes.items() if v is not None})
    return url_for("main.module_page", module_id="labels", key="print", **args)


def print_page() -> str:
    from hyprvolt.main import records_listed
    name = request.args.get("list") or "all"
    module, a, rows = records_listed(name, LIMIT + 1)
    more = len(rows) > LIMIT
    rows = rows[:LIMIT]
    size = request.args.get("size") if request.args.get("size") in dict(SIZES) else SIZES[0][0]
    details = present.details_for(rows)
    base = request.host_url.rstrip("/")
    labels = []
    for v in present.views(rows):
        code_label, code = _code(details.get(v.id))
        # The innermost two places (a rack in a room) say where to find it.
        where = " › ".join(v.path.split(" › ")[-2:]) if v.path else ""
        labels.append({"view": v, "code_label": code_label, "code": code, "where": where,
                       "qr": qr(f"{base}/e/{v.id}")})
    back_args = {k: val for k, val in request.args.items() if k not in ("list", "size")}
    back = (url_for("main.module_list", module_id=module.id, **back_args) if module
            else url_for("main.all_records", **back_args))
    return render_template("labels/print.html", labels=labels, more=more, limit=LIMIT, size=size, sizes=SIZES,
                           sizes_url={key: _with(size=key) for key, _ in SIZES}, back=back,
                           what=(a["etype"].plural if a["etype"] else module.name if module else "All records"))
