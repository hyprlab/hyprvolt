"""What a module declares, and the core reads at startup.

A module is a subpackage of ``hyprvolt.modules`` whose ``__init__`` exports
``module = Module(...)``. Everything in it is data the core already knows how
to use: the entity types and their field schemas drive the list rows, cards,
forms and the detail sheet; the rest are hooks the shell calls when it
renders the sidebar, the palette, the dashboard, the settings window and the
worker. docs/MODULES.md is the guide; tests/example_modules/ is the smallest
working module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

#: Field kinds a module may use. The core parses, validates, renders and
#: indexes each one (core/fields.py).
FIELD_KINDS = ("text", "longtext", "markdown", "integer", "number", "date", "select",
               "url", "email", "boolean", "ref")
#: The subset an admin can add as a custom field, without code.
CUSTOM_KINDS = ("text", "number", "date", "select", "url", "boolean")

DEFAULT_STATUSES = (("active", "Active"), ("planned", "Planned"), ("retired", "Retired"))

#: How a relationship affects the dependency view: "source" means the source
#: stops working when the target goes down (a VM that runs on a host);
#: "target" the other way round; "none" is only a link.
IMPACTS = ("source", "target", "none")


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "text"
    required: bool = False
    default: Any = None
    options: tuple = ()              # select: ((value, label), ...)
    types: tuple = ()                # ref: entity types it may point at
    help: str = ""
    unit: str = ""                   # shown after the value: "U", "W", "GB"
    min: float | None = None
    max: float | None = None
    list: bool = False               # a column in the list row
    card: bool = False               # a line on the card
    search: bool = True              # part of the search text
    group: str = ""                  # a heading in the form and the Overview


@dataclass(frozen=True)
class Tab:
    """A tab in the detail sheet. ``render(entity)`` returns HTML (render a
    template; never build HTML from user text by hand). ``when(entity)``
    decides per entity; leave it out to always show the tab."""
    key: str
    label: str
    render: Callable
    when: Callable | None = None
    count: Callable | None = None    # a number beside the label, or None


@dataclass(frozen=True)
class EntityType:
    key: str                         # unique across all modules: "rack"
    label: str                       # "Rack"
    plural: str                      # "Racks"
    detail: Any = None               # the module's one-to-one model, or None
    fields: tuple = ()
    statuses: tuple = DEFAULT_STATUSES
    location: bool = False           # can be chosen as another entity's location
    located_in: tuple | None = None  # allowed location types; None: any, (): none
    tabs: tuple = ()
    icon: str = ""                   # SVG paths; the module's icon if empty
    module: str = ""                 # filled in by the registry


@dataclass(frozen=True)
class ListFilter:
    """A sidebar filter with a live count. ``apply(query)`` narrows a query
    over live entities of the module; the core counts and pages it."""
    key: str
    label: str
    apply: Callable


@dataclass(frozen=True)
class Widget:
    """A dashboard card. ``render()`` returns HTML."""
    key: str
    label: str
    render: Callable
    wide: bool = False


@dataclass(frozen=True)
class Job:
    """Periodic work, run by the worker thread every ``minutes`` at most.
    ``run()`` returns the number of rows it touched, for the log."""
    key: str
    run: Callable
    minutes: int = 60


@dataclass(frozen=True)
class Pane:
    """A section in the settings window. ``render()`` returns HTML; saving
    goes through the module's own blueprint routes."""
    key: str
    label: str
    render: Callable
    icon: str = ""
    admin: bool = True


@dataclass(frozen=True)
class RelationKind:
    key: str
    label: str                       # read source -> target: "runs on"
    reverse: str                     # read target -> source: "runs"
    impact: str = "none"


@dataclass(frozen=True)
class Step:
    """One migration step. ``run(m)`` gets a ``Migrator`` whose helpers are
    each guarded, so the step is safe on every boot. Steps are appended to a
    module's list and never edited once released (docs/ARCHITECTURE.md)."""
    id: str
    run: Callable


@dataclass(frozen=True)
class SearchResult:
    title: str
    meta: str = ""
    entity_id: int | None = None     # opens the detail sheet
    url: str = ""                    # or goes here


@dataclass
class Module:
    id: str
    name: str
    icon: str = ""                   # inline SVG paths, 24x24, stroked
    description: str = ""
    group: str = "Modules"           # the sidebar group it sits in
    order: int = 100                 # its place in the group
    requires: tuple = ()             # module ids it builds on
    core: bool = False               # built in; can't be disabled
    models: tuple = ()
    migrations: tuple = ()
    blueprint: Any = None            # mounted at /<id>/...
    types: tuple = ()
    search: Callable | None = None   # search(query, limit) -> [SearchResult]
    filters: tuple = ()
    widgets: tuple = ()
    jobs: tuple = ()
    settings_pane: Pane | None = None
    relation_kinds: tuple = ()
    sheet_tabs: tuple = ()           # tabs on any module's entities; use Tab.when
    seed: Callable | None = None     # seed(demo) for flask seed-demo
    package: str = field(default="", compare=False)  # filled in by the registry
