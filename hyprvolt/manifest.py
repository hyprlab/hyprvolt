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
FIELD_KINDS = ("text", "longtext", "markdown", "integer", "number", "date", "datetime", "select",
               "url", "email", "phone", "boolean", "ref", "ip", "cidr", "iprange", "speed")
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
    trait: str = ""                  # ref: or any type with this trait
    relation: str = ""               # ref: kept as a link of this kind, not a column
    help: str = ""
    unit: str = ""                   # shown after the value: "U", "W", "GB"
    min: float | None = None
    max: float | None = None
    list: bool = False               # a column in the list row
    card: bool = False               # a line on the card
    search: bool = True              # part of the search text
    group: str = ""                  # a heading in the form and the Overview
    expires: bool = False            # date: when something ends or is due; reminded of
    remind: Callable | None = None   # expires: remind(detail) -> days ahead, or None for the window
    suggest: str = ""                # text: a catalog (core/catalogs.py) offered as it is typed in, one
                                     # picked with a click, anything else kept: "os", operating systems
    switch: tuple = ()               # boolean: a switch reading (off, on): ("Dynamic", "Static")
    prefills: tuple = ()             # cidr: fields filled in from it while empty: an ip with its first
                                     # host (a gateway), an iprange with its upper half (DHCP)
    shown_when: tuple = ()           # (field key, value): shown only while that field has it:
                                     # ("static_ip", True), the static address of a static line
    hides: tuple = ()                # select: form sections (their keys) hidden while
    hides_when: tuple = ()           # its value is one of these: a tower has no rack position;
                                     # or (key, values) pairs, a section hidden for values of its own

    def hide_rules(self) -> tuple:
        """Each section it hides, with the values it is hidden for."""
        return tuple(h if isinstance(h, tuple) else (h, self.hides_when) for h in self.hides)


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
    traits: tuple = ()               # words other modules look for: ("rackmount",)
    proper: bool = False             # the label starts with a name: "Docker host"
    name_from: str = ""              # a field whose value is the name: an IP's address
    name_label: str = "Name"         # the name's label: "Name or hostname" for what has one
    inactive: tuple = ("retired",)   # statuses that need no reminders
    check: Callable | None = None    # check(entity, detail): rules across fields
    overview: Callable | None = None # overview(entity) -> (html above, html below) the Overview
    restrictable: bool = False       # can be hidden from viewers (core/access.py)
    becomes: tuple = ()              # types a record can be changed into: same module, same detail
    module: str = ""                 # filled in by the registry

    def text(self, plural: bool = False) -> str:
        """The label inside a sentence: "New virtual machine", but "New NAS"
        and "New Docker host". Lower case, unless it starts with an acronym
        or the type is ``proper``."""
        label = self.plural if plural else self.label
        first = label.split(" ", 1)[0]
        return label if self.proper or (len(first) > 1 and first[:2].isupper()) else label.lower()


@dataclass(frozen=True)
class FormSection:
    """Fields a module adds to the record form of types it doesn't own (or
    its own), kept in its own tables. ``when(etype)`` picks the types, often
    by a trait. ``render(etype, entity)`` returns the fields' HTML, each named
    ``s.<key>.<name>`` (``entity`` is None for a new record).
    ``save(entity, values, user)`` gets those values as a dict when the
    record is saved through ``records``, stores them or raises ``Invalid``,
    and returns the changes for the history: [{"field", "label", "old",
    "new"}]. ``values(entity)``, if given, returns what the section holds as
    those same names ({"list": "10.0.20.5"}), for the site setup guide's rows;
    ``choices(name)`` the options of one that is a choice (None for one
    that is typed)."""
    key: str
    label: str
    render: Callable
    save: Callable
    when: Callable | None = None
    values: Callable | None = None   # values(entity) -> {name: value}: what it holds now
    choices: Callable | None = None  # choices(name) -> [(value, label)]: a choice's options, for the guide


@dataclass(frozen=True)
class ListFilter:
    """A sidebar filter with a live count. ``apply(query)`` narrows a query
    over live entities of the module; the core counts and pages it. The
    count is red, as something to see to, unless ``alert`` is False."""
    key: str
    label: str
    apply: Callable
    alert: bool = True


def plural(label: str) -> str:
    """A kind's label made plural: "Switches", "Access points"; one ending
    in an acronym stays as it is: "NAS"."""
    if label.rsplit(" ", 1)[-1].isupper():
        return label
    return label + ("es" if label.endswith(("ch", "sh", "s", "x")) else "s")


@dataclass(frozen=True)
class SetupKind:
    """One thing a row of a setup step can be: a type of this module, and
    form values it starts with ({"f.kind": "switch"} for a switch)."""
    label: str
    type: str
    values: dict = field(default_factory=dict)
    plural: str = ""                 # its heading in a grouped step; made from the label if empty

    def heading(self) -> str:
        """The kind's rows' heading: "Switches", "Access points", "NAS"."""
        return self.plural or plural(self.label)


@dataclass(frozen=True)
class SetupField:
    """A column of a setup step's rows. ``name`` is the record form's own:
    "name", "location_id" (a place in the site being set up), "f.<field>"
    (its label and control come from the type's Field), or "s.<section>.<name>",
    which needs a ``label`` and is left out where the section doesn't apply.
    ``types`` makes it a choice of the records of those types; ``choices(scope)``
    gives the choices of a step with its own ``save``."""
    name: str
    label: str = ""
    kind: str = "text"               # text, number or select, where not from a Field; multi: a
                                     # section's choice of several, ticked (wireless networks);
                                     # place: a section's choice of the site's places
    placeholder: str = ""            # a multi's: what it says when there is nothing to tick
    types: tuple = ()
    choices: Callable | None = None
    newline: bool = False            # starts a new line of the row: download and upload, then the IP
    kinds: tuple = ()                # only in rows of these kinds (their labels): a modem's internet line
    shown_when: tuple = ()           # (column, value): shown only while that column of the row has it:
                                     # ("s.hypervisor.on", "1"), a server's hypervisor platform
    relabel: tuple = ()              # (column, value, label): another label while that column has it:
                                     # a server's IP address is its BMC's once it runs a hypervisor
    confirm_off: tuple = ()          # check: (question, text) asked before it is unticked, when that
                                     # deletes something; the section's values may give
                                     # "<name>_blocked", (title, text), said instead when it can't be


@dataclass(frozen=True)
class SetupStep:
    """A step of the site setup guide (core/guide.py), from the site out to
    the endpoints. Each row is a record of one of ``kinds``, edited and saved
    in place; or, with ``save``, ``save(values, scope, user)`` makes what the
    step is for (a cable), ``rows(scope)`` lists what is there as rows
    ({"id", "label", "values", "text", "locked"}, and to fold to something
    other than the label, "title", "badge" (a column shown before it) and
    "in_title" (columns left out of the summary): locked columns show the
    text instead of a control), ``update(id, values, user)`` changes one and
    ``delete(id)`` deletes one, returning its Undo ({"url", "body"}). ``scope``: the step
    chooses the site the steps after it are about. ``tree``: instead of rows,
    the step's records are a tree under the site, by where each is (the
    kinds' ``located_in``), added in place, dragged to another level, and
    saved as that happens. ``order`` places it among
    every module's steps; ``group`` names the stretch of the guide it is in
    (Place, Network, Equipment, What runs, Endpoints), a heading over its
    steps."""
    key: str
    title: str
    intro: str
    order: int
    group: str = ""
    plan: str = ""                   # what it covers on the first page, lower case: "buildings, rooms"
    help: tuple = ()                 # paragraphs behind the step's info button: what goes here, what goes
                                     # elsewhere, and why
    fields: tuple = ()
    kinds: tuple = ()
    scope: bool = False
    tree: bool = False               # records that hold each other (buildings, rooms) as a tree
    grouped: bool = False            # rows under a heading for each kind, in the kinds' order
    joined: Callable | None = None   # joined(entity) -> records shown in its row, not their own,
                                     # and deleted with it: a MoCA adapter's far end, in the pair's
    extra: Callable | None = None    # extra(scope) -> HTML above the rows: another way to fill the step
    after: Callable | None = None    # after(scope) -> HTML below the rows, once there are any, drawn
                                     # again with them: the cables' network diagram
                                     # (Services' Import from Homepage)
    save: Callable | None = None
    rows: Callable | None = None
    update: Callable | None = None
    delete: Callable | None = None


@dataclass(frozen=True)
class SetupFinish:
    """What the site setup guide's last page offers to do with the site just
    set up: the knowledge base starts its runbook. ``make(site, found, user)``
    does it and returns the record to open next, ``found`` being what the
    guide's steps recorded in the site: [{"group", "title", "records"}].
    ``made(site)`` returns the record made before, if any, so the page offers
    to open that instead."""
    key: str
    label: str                       # the button: "Start the site's runbook"
    text: str                        # a sentence beside it
    make: Callable
    made: Callable | None = None
    open_label: str = ""             # the button once made: "Open the site's runbook"


@dataclass(frozen=True)
class Widget:
    """A dashboard card. ``render()`` returns HTML."""
    key: str
    label: str
    render: Callable
    wide: bool = False


@dataclass(frozen=True)
class Page:
    """A page of its own in the shell, at ``/p/<module>/<key>``. ``render()``
    returns its HTML, reading what it needs from ``request.args``.
    ``sidebar`` lists it under the module in the sidebar; ``from_list``
    offers it in a list's export menu, the list's filters in its query
    string (``records_listed()`` in main.py turns them into records)."""
    key: str
    label: str
    render: Callable
    sidebar: bool = True
    from_list: bool = False


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
    pages: tuple = ()                # full pages in the shell
    widgets: tuple = ()
    jobs: tuple = ()
    settings_pane: Pane | None = None
    relation_kinds: tuple = ()
    impact_edges: Callable | None = None   # impact_edges() -> [(needs id, needed id, label, reverse)]: dependencies worked out, not recorded
    derived_links: Callable | None = None  # derived_links(entity) -> [{"other", "label", "sub", "note"}]: read-only, in Relationships
    sheet_tabs: tuple = ()           # tabs on any module's entities; use Tab.when
    form_sections: tuple = ()        # form sections on any module's types
    before_retype: Callable | None = None  # before_retype(entity, old, new) on any type change; raise Invalid to refuse
    setup: tuple = ()                # SetupSteps of the site setup guide
    setup_finish: tuple = ()         # SetupFinishes: what its last page offers to do
    seed: Callable | None = None     # seed(demo) for flask seed-demo
    package: str = field(default="", compare=False)  # filled in by the registry
