"""Software: titles, their licenses, and where each is installed.

A title's installations are rows of this module's own (host, version,
license seat), shown in the title's Installations tab and in a Software tab
on every record with the ``host`` trait (a server, a VM, a container). A
license's seats in use are its installations plus the seats it says are
used elsewhere, such as user accounts.
"""
from hyprvolt.manifest import EntityType, Field, ListFilter, Module, Tab

from . import demo, views
from .models import Installation, SoftwareDetail

CATEGORIES = (("os", "Operating system"), ("application", "Application"), ("server", "Server software"),
              ("utility", "Utility"), ("other", "Other"))
MODELS = (("open_source", "Open source"), ("free", "Free"), ("subscription", "Subscription"),
          ("perpetual", "Bought outright"))
LICENSE_KINDS = (("subscription", "Subscription"), ("perpetual", "Perpetual"), ("oem", "OEM"),
                 ("volume", "Volume"), ("other", "Other"))
LICENSE_STATUSES = (("active", "In force"), ("planned", "Ordered"), ("retired", "Expired"))
TITLE_STATUSES = (("active", "In use"), ("planned", "Evaluating"), ("retired", "No longer used"))

ICON = ('<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M3.5 8.5h17M6 6.5h.1M8 6.5h.1"/>'
        '<path d="m9.5 12-2 2 2 2M14.5 12l2 2-2 2"/>')
TITLE = ICON
LICENSE = ('<path d="M4.5 6.5h15v11h-15z"/><circle cx="9" cy="11.2" r="1.8"/>'
           '<path d="M6.5 15c.5-1.2 1.4-1.8 2.5-1.8s2 .6 2.5 1.8M14 10h3M14 13h3"/>')

module = Module(
    id="software",
    name="Software",
    icon=ICON,
    description="Software titles and versions, where each is installed, and licenses with their seats.",
    group="Operations",
    order=60,
    models=(SoftwareDetail, Installation),
    blueprint=views.bp,
    types=(
        EntityType("software", "Software", "Software", detail=SoftwareDetail, located_in=(), icon=TITLE,
                   statuses=TITLE_STATUSES, traits=("supplied",),
                   fields=(Field("category", "Category", "select", options=CATEGORIES, list=True),
                           Field("current_version", "Current version", card=True, list=True,
                                 help="The one to be on. Installations at another version are flagged."),
                           Field("license_model", "Licensing", "select", options=MODELS, card=True),
                           Field("website", "Website", "url")),
                   tabs=(Tab("installations", "Installations", views.software_tab, count=views.software_count),)),
        EntityType("license", "License", "Licenses", detail=SoftwareDetail, located_in=(), icon=LICENSE,
                   statuses=LICENSE_STATUSES, traits=("supplied",),
                   fields=(Field("software", "For", "ref", types=("software",), required=True, card=True, list=True),
                           Field("kind", "Kind", "select", options=LICENSE_KINDS, list=True),
                           Field("seats", "Seats owned", "integer", min=0, max=1_000_000, card=True),
                           Field("extra_seats", "Seats used elsewhere", "integer", min=0, max=1_000_000,
                                 help="Users or accounts that aren't installations recorded here."),
                           Field("purchased", "Bought", "date", group="Term"),
                           Field("renews", "Renews", "date", card=True, list=True, group="Term"),
                           Field("cost", "Cost", "number", min=0, group="Term")),
                   tabs=(Tab("seats", "Seats", views.license_tab, count=views.license_count),)),
    ),
    filters=(ListFilter("outdated", "Behind the current version", views.outdated),
             ListFilter("over", "Licenses over their seats", views.over_seats),
             ListFilter("renewal", "License renewal soon", views.renewal_soon)),
    sheet_tabs=(Tab("software", "Software", views.host_tab, when=views.has_software_tab, count=views.host_count),),
    seed=demo.seed,
)
