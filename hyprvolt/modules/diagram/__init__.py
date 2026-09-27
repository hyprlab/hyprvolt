"""Diagram: the network drawn from its cables, and each record's
neighborhood.

The Network diagram page draws every cabled device and the cables between
them, traced through patch panels, in tiers from the internet side
(graph.py). Every record with links or cables gets a Neighborhood tab
drawing what it is linked to, in both directions. Both are SVG made on the
server: no script, and the shared ``.diagram`` component styles them.
"""
from hyprvolt.manifest import Module, Page, Tab

from . import views

ICON = ('<rect x="9" y="3.5" width="6" height="4.5" rx="1"/><rect x="3" y="16" width="6" height="4.5" rx="1"/>'
        '<rect x="15" y="16" width="6" height="4.5" rx="1"/><path d="M12 8v4M6 16v-4h12v4"/>')

module = Module(
    id="diagram",
    name="Diagram",
    icon=ICON,
    description="The network drawn from its cables, and a Neighborhood tab on every linked record.",
    group="Infrastructure",
    order=45,
    requires=("network",),
    pages=(Page("network", "Network diagram", views.network_page),),
    sheet_tabs=(Tab("neighborhood", "Neighborhood", views.neighborhood_tab, when=views.has_neighbors),),
)
