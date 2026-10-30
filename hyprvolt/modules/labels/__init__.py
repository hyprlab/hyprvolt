"""Asset labels: printable labels with QR codes, for the records of any
list, and 4 × 1 in asset tags branded with the organization's name and logo.

A page offered from every list's export menu (``Page(from_list=True)``),
so it prints what the list shows, filters and search included, and from a
record's bar (``SheetLink``) for the one tag. Each QR code opens the record
at ``/e/<id>``. Label sizes and print layout are shared components in
app.css; the codes come from segno; the PDF from core/pdf.py. The name and
logo are set in Settings > Asset labels (brand.py).
"""
from hyprvolt.manifest import Module, Page, Pane, SheetLink

from . import brand, views

ICON = ('<path d="M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7l8.3 8.3a1 1 0 0 1 0 1.4l-7.1 7.1a1 1 0 0 1-1.4 0Z"/>'
        '<circle cx="8" cy="8" r="1.5"/>')

module = Module(
    id="labels",
    name="Asset labels",
    icon=ICON,
    description="Printable labels with a QR code that opens the record, for any list, and branded asset tags.",
    group="Operations",
    order=90,
    models=(brand.LabelLogo,),
    blueprint=views.bp,      # /labels/print.pdf, /labels/logo, /labels/brand
    pages=(Page("print", "Print labels", views.print_page, sidebar=False, from_list=True),),
    sheet_links=(SheetLink("tag", "Print asset tag", ICON, views.taggable),),
    settings_pane=Pane("labels", "Asset labels", views.pane, icon=ICON),
)
