"""Maintenance and changes: planned maintenance windows, and a log of the
changes people make.

A window has a start and end in the instance's time zone, an expected
impact, and a plan. What it or a change affects is kept as "affects" links,
added in its Impact or Affects tab or from the Changes tab that every other
record has. A window's Impact tab walks the core's relations from what it
affects to list everything else that goes down with it. The core's history
already logs every edit of a record; this module is for changes people make
to the systems and describe themselves.
"""
from hyprvolt.manifest import EntityType, Field, ListFilter, Module, RelationKind, Tab, Widget

from . import demo, views
from .models import MaintenanceDetail

ICON = ('<path d="M14.7 6.3a4 4 0 0 0-5.4 5.1l-5.1 5.1a1.6 1.6 0 0 0 2.3 2.3l5.1-5.1a4 4 0 0 0 5.1-5.4l-2.4 2.4-2.1-.4-.4-2.1'
        ' 2.9-1.9Z"/>')
WINDOW = '<rect x="3.5" y="5" width="17" height="15" rx="1.5"/><path d="M3.5 9.5h17M8 3v4M16 3v4M8.5 14.5l2 2 4-4"/>'
CHANGE = '<path d="M4 7h11M4 7l3-3M4 7l3 3M20 17H9m11 0-3-3m3 3-3 3"/>'

module = Module(
    id="maintenance",
    name="Maintenance",
    icon=ICON,
    description="Maintenance windows with what they take down, and a log of the changes made to everything.",
    group="Operations",
    order=56,
    models=(MaintenanceDetail,),
    relation_kinds=(RelationKind("affects", "affects", "affected by", impact="none"),),
    types=(
        EntityType("maintenance", "Maintenance window", "Maintenance windows", detail=MaintenanceDetail,
                   located_in=(), icon=WINDOW, statuses=views.WINDOW_STATUSES, inactive=("done", "canceled"),
                   check=views.check_window,
                   fields=(Field("starts", "Starts", "datetime", required=True, card=True, list=True),
                           Field("ends", "Ends", "datetime", required=True, card=True),
                           Field("impact", "Impact", "select", options=views.IMPACTS, default="outage", list=True,
                                 card=True, help="What people will notice while it runs."),
                           Field("owner", "Who does it"),
                           Field("announced", "Users told", "boolean"),
                           Field("plan", "Plan", "markdown",
                                 help="The steps, how to tell it worked, and how to roll it back.")),
                   tabs=(Tab("impact", "Impact", views.impact_tab),)),
        EntityType("change", "Change", "Changes", detail=MaintenanceDetail, located_in=(), icon=CHANGE,
                   statuses=views.CHANGE_STATUSES, check=views.check_change,
                   fields=(Field("at", "When", "datetime", card=True, list=True, help="Leave it empty for now."),
                           Field("kind", "Kind", "select", options=views.KINDS, list=True),
                           Field("done_by", "Done by", card=True),
                           Field("window", "During", "ref", types=("maintenance",),
                                 help="The maintenance window it was part of, if any."),
                           Field("details", "What and why", "markdown",
                                 help="What changed, why, and anything to know to undo it.")),
                   tabs=(Tab("affects", "Affects", views.impact_tab),)),
    ),
    filters=(ListFilter("upcoming", "Coming up", views.upcoming),
             ListFilter("now", "Under way", views.under_way),
             ListFilter("recent", "Recent changes", views.recent_changes),
             ListFilter("trouble", "Failed changes", views.trouble)),
    widgets=(Widget("maintenance", "Maintenance", views.widget),),
    sheet_tabs=(Tab("changes", "Changes", views.record_tab, when=views.on_record, count=views.record_count),),
    seed=demo.seed,
)
