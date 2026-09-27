"""Asset labels: printable labels with QR codes, for the records of any
list.

A page offered from every list's export menu (``Page(from_list=True)``),
so it prints what the list shows, filters and search included. Each QR code
opens the record at ``/e/<id>``. Label sizes and print layout are shared
components in app.css; the codes come from segno.
"""
from hyprvolt.manifest import Module, Page

from . import views

ICON = ('<path d="M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7l8.3 8.3a1 1 0 0 1 0 1.4l-7.1 7.1a1 1 0 0 1-1.4 0Z"/>'
        '<circle cx="8" cy="8" r="1.5"/>')

module = Module(
    id="labels",
    name="Asset labels",
    icon=ICON,
    description="Printable labels with a QR code that opens the record, for any list.",
    group="Operations",
    order=90,
    pages=(Page("print", "Print labels", views.print_page, sidebar=False, from_list=True),),
)
