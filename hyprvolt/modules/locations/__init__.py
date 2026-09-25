"""Locations: where everything is. Sites hold buildings, buildings hold
rooms, rooms hold racks and shelves, and anything can be put in a rack at a
unit position, on the front, the rear or through the full depth.

The hierarchy is the core's own ``location`` field: a room's location is its
building. So every record anywhere gets breadcrumbs, and the Contents tab
lists what is directly inside a place.
"""
from hyprvolt.manifest import EntityType, Field, ListFilter, Module, Tab, Widget

from . import demo, views
from .models import LocationDetail, RackMount

STATUSES = (("active", "In use"), ("planned", "Planned"), ("retired", "Out of use"))
CODE = Field("code", "Code", help="A short name, as on a label: HQ, B2, SRV1.", card=True, list=True)

ICON = '<path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11Z"/><circle cx="12" cy="10" r="2.3"/>'
SITE = ICON
BUILDING = '<path d="M5 20.5V5a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v15.5M15 9.5h3a1 1 0 0 1 1 1v10M3.5 20.5h17M8.5 8h3M8.5 11.5h3M8.5 15h3"/>'
ROOM = '<path d="M4.5 20V4.5a.5.5 0 0 1 .5-.5h14a.5.5 0 0 1 .5.5V20M3 20h18M14.5 12.5v.1"/><path d="M9 20V8h6v12"/>'
RACK = '<rect x="6" y="3.5" width="12" height="17" rx="1"/><path d="M6 8h12M6 12.5h12M6 17h12M9 5.8h.1M9 10.3h.1M9 14.8h.1"/>'
SHELF = '<path d="M4 8.5h16M4 15.5h16M5.5 4v16M18.5 4v16"/>'

in_a_rack = Tab("position", "Rack position", views.position_tab, when=views.has_mount)

module = Module(
    id="locations",
    name="Locations",
    icon=ICON,
    description="Sites, buildings, rooms, racks and shelves, and what sits in which rack unit.",
    group="Infrastructure",
    order=10,
    models=(LocationDetail, RackMount),
    blueprint=views.bp,
    types=(
        EntityType("site", "Site", "Sites", detail=LocationDetail, location=True, located_in=(),
                   statuses=STATUSES, icon=SITE,
                   fields=(CODE, Field("address", "Address", "longtext", list=True)),
                   tabs=(Tab("contents", "Contents", views.contents_tab, count=views.contents_count),)),
        EntityType("building", "Building", "Buildings", detail=LocationDetail, location=True,
                   located_in=("site",), statuses=STATUSES, icon=BUILDING, fields=(CODE,),
                   tabs=(Tab("contents", "Contents", views.contents_tab, count=views.contents_count),)),
        EntityType("room", "Room", "Rooms", detail=LocationDetail, location=True,
                   located_in=("building", "site"), statuses=STATUSES, icon=ROOM,
                   fields=(CODE, Field("floor", "Floor", list=True)),
                   tabs=(Tab("contents", "Contents", views.contents_tab, count=views.contents_count),)),
        EntityType("rack", "Rack", "Racks", detail=LocationDetail, location=True, located_in=("room",),
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
                   located_in=("room", "rack"), statuses=STATUSES, icon=SHELF,
                   fields=(Field("height_u", "Height in a rack", "integer", min=1, max=60, unit="U",
                                 help="How many units it takes when it is mounted in a rack."),),
                   tabs=(Tab("contents", "Contents", views.contents_tab, count=views.contents_count),)),
    ),
    filters=(ListFilter("conflicts", "Racks with conflicts", views.conflicts_filter),),
    widgets=(Widget("rack-space", "Rack space", views.rack_space_widget),),
    sheet_tabs=(in_a_rack,),
    seed=demo.seed,
)
