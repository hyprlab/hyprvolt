"""Locations: where everything is. Sites hold buildings, buildings hold
rooms, rooms hold racks and shelves, and anything can be put in a rack at a
unit position, on the front, the rear or through the full depth. A type with
the ``rackmount`` trait gets its rack position in its own form.

The hierarchy is the core's own ``location`` field: a room's location is its
building. So every record anywhere gets breadcrumbs, and the Contents tab
lists what is directly inside a place.
"""
from hyprvolt.manifest import EntityType, Field, FormSection, ListFilter, Module, Step, Tab, Widget

from . import demo, views
from .models import LocationDetail, RackMount

STATUSES = (("active", "In use"), ("planned", "Planned"), ("retired", "Out of use"))
CODE = Field("code", "Code", card=True, list=True,
             help="A short name for when the full one won't fit, such as HQ, B2 or SRV1: shown on cards and "
                  "lists, and handy on labels, rack names and cable tags. Optional.")

#: A site's address, a field each. "address" holds the street lines: it was
#: the whole address before 1.1, so an older one is still all in it.
ADDRESS = (
    Field("address", "Street address", "longtext", group="Address",
          help="The street and number, with a second line for a suite, unit or floor if it needs one."),
    Field("city", "City", list=True, card=True, group="Address", help="The city or town."),
    Field("region", "State or region", group="Address",
          help="The state, province or county, written the way the post office writes it."),
    Field("postal_code", "Postal code", group="Address", help="The ZIP code or postcode."),
    Field("country", "Country", list=True, group="Address", help="The country, written out in full."),
)


def _address_parts(m):
    for column, ddl in (("city", "VARCHAR(120)"), ("region", "VARCHAR(120)"), ("postal_code", "VARCHAR(20)"),
                        ("country", "VARCHAR(120)")):
        m.add_column("location_details", column, ddl)

ICON = '<path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11Z"/><circle cx="12" cy="10" r="2.3"/>'
SITE = ICON
BUILDING = '<path d="M5 20.5V5a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v15.5M15 9.5h3a1 1 0 0 1 1 1v10M3.5 20.5h17M8.5 8h3M8.5 11.5h3M8.5 15h3"/>'
ROOM = '<path d="M4.5 20V4.5a.5.5 0 0 1 .5-.5h14a.5.5 0 0 1 .5.5V20M3 20h18M14.5 12.5v.1"/><path d="M9 20V8h6v12"/>'
RACK = '<rect x="6" y="3.5" width="12" height="17" rx="1"/><path d="M6 8h12M6 12.5h12M6 17h12M9 5.8h.1M9 10.3h.1M9 14.8h.1"/>'
SHELF = '<path d="M4 8.5h16M4 15.5h16M5.5 4v16M18.5 4v16"/>'

KINDS = ("site", "building", "room", "rack", "shelf")


def _becomes(key: str) -> tuple:
    """Any location can be made another kind: a room that is really a building."""
    return tuple(k for k in KINDS if k != key)


in_a_rack = Tab("position", "Rack position", views.position_tab, when=views.has_mount)

module = Module(
    id="locations",
    name="Locations",
    icon=ICON,
    description="Sites, buildings, rooms, racks and shelves, and what sits in which rack unit.",
    group="Infrastructure",
    order=10,
    models=(LocationDetail, RackMount),
    migrations=(Step("site-address-parts", _address_parts),),
    blueprint=views.bp,
    types=(
        EntityType("site", "Site", "Sites", detail=LocationDetail, location=True, located_in=(),
                   becomes=_becomes("site"),
                   statuses=STATUSES, icon=SITE,
                   fields=(CODE,) + ADDRESS,
                   tabs=(Tab("contents", "Contents", views.contents_tab, count=views.contents_count),)),
        EntityType("building", "Building", "Buildings", detail=LocationDetail, location=True,
                   becomes=_becomes("building"),
                   located_in=("site",), statuses=STATUSES, icon=BUILDING, fields=(CODE,),
                   tabs=(Tab("contents", "Contents", views.contents_tab, count=views.contents_count),)),
        EntityType("room", "Room", "Rooms", detail=LocationDetail, location=True,
                   becomes=_becomes("room"),
                   located_in=("building", "site"), statuses=STATUSES, icon=ROOM,
                   fields=(CODE, Field("floor", "Floor", list=True)),
                   tabs=(Tab("contents", "Contents", views.contents_tab, count=views.contents_count),)),
        EntityType("rack", "Rack", "Racks", detail=LocationDetail, location=True, located_in=("room",),
                   becomes=_becomes("rack"),
                   statuses=STATUSES, icon=RACK,
                   fields=(
                       Field("height_u", "Height", "integer", required=True, default=42, min=1, max=60,
                             unit="U", card=True, list=True),
                       Field("numbering", "Unit numbers", "select", required=True, default="bottom",
                             options=(("bottom", "U1 at the bottom"), ("top", "U1 at the top"))),
                       Field("depth_mm", "Depth", "integer", min=1, max=2000, unit="mm"),
                   ),
                   tabs=(Tab("elevation", "Elevation", views.elevation_tab, count=views.elevation_count),)),
        EntityType("shelf", "Shelf", "Shelves", detail=LocationDetail, location=True,
                   becomes=_becomes("shelf"),
                   located_in=("room", "rack"), statuses=STATUSES, icon=SHELF, traits=("rackmount",),
                   fields=(Field("height_u", "Height in a rack", "integer", min=1, max=60, unit="U",
                                 help="How many units it takes when it is mounted in a rack."),),
                   tabs=(Tab("contents", "Contents", views.contents_tab, count=views.contents_count),)),
    ),
    filters=(ListFilter("conflicts", "Racks with conflicts", views.conflicts_filter),),
    widgets=(Widget("rack-space", "Rack space", views.rack_space_widget),),
    sheet_tabs=(in_a_rack,),
    form_sections=(FormSection("rack", "Rack position", views.rack_form, views.rack_save,
                               when=views.is_rackmount),),
    before_retype=views.before_retype,
    seed=demo.seed,
)
