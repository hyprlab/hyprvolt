# Modules

Everything Hyprvolt documents comes from a module: Locations, the knowledge
base, and later Hardware, Virtual, Network and the rest. A module is a Python
package in `hyprvolt/modules/` whose `__init__.py` exports one `Module(...)`,
its manifest. The core reads the manifests at startup and builds the
interface, the search, the API and the migrations from them.

Adding a module needs no edit to any core file: the registry finds every
subpackage of `hyprvolt/modules/` by itself. This page is how to write one;
[ARCHITECTURE.md](ARCHITECTURE.md#modules) is why it works this way.

## The smallest module

This is `tests/example_modules/example/`, which the test suite loads next to
the real modules:

```python
from hyprvolt.core.models import EntityDetail
from hyprvolt.manifest import EntityType, Field, Module
from hyprvolt.models import db


class GadgetDetail(EntityDetail, db.Model):
    __tablename__ = "example_gadgets"
    color = db.Column(db.String(40))


module = Module(
    id="example",
    name="Gadgets",
    types=(
        EntityType("gadget", "Gadget", "Gadgets", detail=GadgetDetail,
                   fields=(Field("color", "Color", list=True),)),
    ),
)
```

With nothing more, gadgets get:

- a page at `/example` with cards and a list, sorting, paging, and a place in
  the sidebar with a live count
- the New menu and one form, built from the fields
- the detail sheet with Overview, Relationships, Documents, Attachments and
  History, a `?open=<id>` link and keyboard navigation
- a name, slug, status, location, tags and Markdown notes, which every record
  has
- custom fields an admin adds in Settings, search in the palette and `?q=`,
  archive, delete with Undo, and a history of every change
- the JSON API: `GET/POST /api/entities`, `/api/entities/<id>` and the rest
- a switch in Settings > Modules to turn it off, keeping its records

## The manifest

`Module` is a dataclass in `hyprvolt/manifest.py`. Only `id` and `name` are
required.

| Field | What it is |
| --- | --- |
| `id` | 2 to 31 lower-case letters, digits and underscores, starting with a letter; the URL (`/<id>`) and the name of its settings. Can't be a word the core uses (`all`, `api`, `admin`, `search`, …) |
| `name`, `description`, `icon` | What the sidebar, dashboard and Settings > Modules show. `icon` is the inside of a 24×24 stroked `<svg>`, like every icon in the app |
| `group`, `order` | Where it sits in the sidebar: under the `group` heading, sorted by `order`. That is the default; an admin can reorder the groups and the modules within them in Settings > Modules, and a module the saved order doesn't name follows the ones it does |
| `requires` | Ids of modules it builds on. They migrate and seed first; a module whose requirement is missing is left out, and one whose requirement is turned off is off too. A module that only takes part through traits (Services pointing at hosts) needs no requirement |
| `core` | Built in; it can't be turned off. The knowledge base and Secrets are |
| `models` | Its SQLAlchemy models, for the record; importing the package is what registers them |
| `migrations` | Its `Step`s, in order. See [Migrations](#migrations) |
| `blueprint` | A Flask blueprint named like the module, mounted at `/<id>`. Optional |
| `types` | Its `EntityType`s. See [Entity types and fields](#entity-types-and-fields) |
| `search` | `search(query, limit)` returning `SearchResult`s for the palette, for things that aren't records (an IP address, a DNS name). Records are searched without it |
| `filters` | `ListFilter(key, label, apply)`s: sidebar entries with live counts under the module. `apply(query)` narrows a query of the module's live records. The count is red, as something to see to; `alert=False` for a filter that is only a view, such as Network's internet connections |
| `widgets` | `Widget(key, label, render, wide=False)`s on the dashboard; `wide` spans the row |
| `pages` | `Page(key, label, render, sidebar=True, from_list=False)`s: pages of their own in the shell, at `/p/<module>/<key>`. `render()` returns the HTML and reads `request.args`. `sidebar` lists the page under the module (a module of pages alone is one sidebar link, to its first); `from_list` offers it in every list's export menu with the list's filters, and `records_listed(name, limit)` in main.py turns those into records. Diagram and Asset labels are the examples |
| `jobs` | `Job`s the worker runs, each at most every `minutes`. Dates that come due need no job: mark the field `expires` |
| `settings_pane` | A `Pane(key, label, render, icon="", admin=True)` in the settings window; `admin=False` shows it to everyone |
| `relation_kinds` | `RelationKind(key, label, reverse, impact)`s it adds to the core's: `label` reads from source to target ("runs on"), `reverse` the other way ("runs"), and `impact` is `source` (the source stops when the target goes down), `target`, or `none` (only a link); the dependency view follows only those with an impact |
| `sheet_tabs` | `Tab(key, label, render, when=None, count=None)`s on records of any module, shown where `when(entity)` says; `count(entity)` puts a number beside the label |
| `form_sections` | `FormSection`s in the record form of any module's types. See [Adding to other modules' forms](#adding-to-other-modules-forms) |
| `setup` | `SetupStep`s of the site setup guide. See [Steps of the site setup guide](#steps-of-the-site-setup-guide) |
| `setup_finish` | `SetupFinish`es: what the guide's last page offers to do with the site set up, such as the knowledge base's runbook |
| `before_retype` | `before_retype(entity, old, new)`, called when any record's type changes (`EntityType.becomes`), with both types. Raise `Invalid` to refuse while the record holds something of this module's that the new type couldn't: a rack mount (Locations), installed software (Software), ports (Network) |
| `seed` | `seed(demo)`, its part of `flask seed-demo`. Seeds run in sidebar order, each after the modules it requires, built-in modules last, so a module later in the sidebar finds the records it links to |

A manifest that fails validation is left out, logged, and listed in
Settings > Modules with the reason. With `MODULES_STRICT=1` (the tests set it)
it stops the app instead. The checks are in `registry.validate()`.

## Entity types and fields

```python
EntityType("rack", "Rack", "Racks", detail=LocationDetail,
           location=True, located_in=("room",),
           statuses=(("active", "In use"), ("planned", "Planned"), ("retired", "Out of use")),
           fields=(Field("height_u", "Height", "integer", required=True, default=42,
                         min=1, max=60, unit="U", card=True, list=True),),
           tabs=(Tab("elevation", "Elevation", views.elevation_tab),))
```

- `key` is unique across all modules; the database stores it on the record.
- `detail` is the module's table for the type's fields, one row per record,
  keyed by the record's id. Subclass `EntityDetail`, which supplies the key
  and makes the row go when the record is purged. Several types may share one
  table (Locations does), each using the columns it needs.
- `statuses` are (value, label) pairs; the first is the default.
- `location=True` makes records of this type choosable as a location. The
  location of a location is its parent, which is all the Locations hierarchy
  is.
- `located_in` limits where a record can be: `None` (the default) is any
  location type, `()` is none at all, or a tuple of type keys.
- `tabs` are sheet sections for this type only. They follow Overview. The
  sheet shows every section at once, so each `render` runs whenever the
  record opens: keep it quick, and give a long list a limit.
- `icon` overrides the module's icon for this type.
- `proper=True` keeps the label's capital inside a sentence ("New Docker
  host"). Without it, "New virtual machine"; a label that starts with an
  acronym keeps its case anyway ("New NAS"). `etype.text()` and
  `etype.text(plural=True)` give that form.
- `traits` are words other modules look for, so a type can take part in
  what another module adds without either naming the other: Hardware marks a
  server `("rackmount",)`, and Locations adds a rack position to the form of
  every type with that trait. The ones in use: `rackmount` (Locations),
  `addressable` and `cabled` (Network), `host` (Software and Services: where
  software is installed and services run), `supplied` (Contacts: has a
  supplier and a contract), `domain` (Services: a service's domain), `tls`
  (Certificates: services and hosts that serve a certificate).
- `inactive` are the statuses of records that need no reminders, `("retired",)`
  by default; Hardware's are retired and disposed.
- `name_from="address"` makes the record's name the shown value of one of
  its fields, and leaves the Name box out of the form: an IP address is
  named by its address.
- `check(entity, detail)` runs on every save after the fields are set, for
  rules that span fields or records: a gateway inside its subnet, a VLAN ID
  used once per network. It raises `Invalid` to refuse the save, and may
  tidy values (Network lower-cases a domain's name).
- `becomes` lists the types a record of this one can be changed into, from
  the Type choice in its form or `type` in the API: a room can become a
  building, a server a NAS, a VM an LXC container. Each must be in the same
  module with the same detail table (and the same `name_from`), so the
  record's values carry over. The core refuses the change while the
  record's location, anything located in it, or a ref field pointing at it
  (a service's Runs on) doesn't suit the new type. A module that attaches
  data by trait refuses it for its own data with `Module.before_retype`.
- `restrictable=True` gives the form a "Visible to" choice (everyone, editors,
  private) and hides the record from readers below it everywhere
  (`core/access.py`). Documents use it. Read records with `Entity.live()` or
  `records.live(id)`, which apply the rule; a query of your own over
  `Entity` goes through `access.visible(query)`.
- `overview(entity)` returns two pieces of HTML (render a template), shown
  above the Overview's fields and below its Markdown: a document's page
  path, and its pages with the ones either side.

A `Field` has a `key` that must be a column of the detail table, a `label`,
and a `kind`:

| Kind | Stored as | Shown as |
| --- | --- | --- |
| `text`, `email`, `url` | a string, 500 characters at most | text; a `url` starting with http links out, an `email` is a mailto: link |
| `phone` | a phone number as written, not checked: an extension, a vanity number (1-833-VERIZON) or a note | a tel: link when it can be dialed, letters on their keypad digits |
| `longtext` | text | text, line breaks kept |
| `markdown` | text | rendered Markdown with `[[slug]]` links, under the fields |
| `integer`, `number` | int, float, with `min` and `max` | the value and its `unit` |
| `date` | a date | `2026-09-25` |
| `datetime` | a date and time, stored in UTC; typed and shown in the instance's time zone (`core/clock.py`) | `2026-10-03 22:00` |
| `select` | one of `options`, as (value, label) pairs | its label |
| `boolean` | true or false | Yes or No |
| `ref` | the id of a record of one of `types` or of any type with `trait`, or a relationship (below) | a link to it |
| `ip` | an IPv4 or IPv6 address, in its short form | the address |
| `cidr` | a subnet, host bits dropped: `10.0.20.7/24` is `10.0.20.0/24` | the subnet |

A `ref` with `relation="runs_on"` is kept as a relationship of that kind from
this record to the chosen one, instead of in a column. A VM's host is one:
choosing it in the form links the VM to the hypervisor, so the Relationships
tab shows it and the dependency view follows it, and unlinking it there
empties the field. The detail table needs no column for it, and a type whose
fields are all kept as links needs no detail table.

A `date` field with `expires=True` is a date something ends or falls due: a
warranty, a renewal, a contract's end. The core reminds of it: within the
admin's reminder window either side of today, the record is on the
dashboard's Coming up card and counts toward the sidebar badge, unless it is
archived or in an `inactive` status. `reminders.ending_within(query, detail,
column)` is the sidebar filter for the window ahead; with `past=True` it also
takes in the window behind (a renewal missed).

`remind=` narrows the window ahead for one record: `remind(detail)` returns a
number of days, or None for the admin's window, and the smaller of the two
applies. Certificates uses it so one that renews by itself is only reminded
of when it is 21 days from its end, which means the renewal failed.

A `ref` with `trait="addressable"` instead of `types` points at a record of
any type with that trait, from whichever modules are installed; the form
names each choice's type.

`required`, `default`, `unit` and `group` (a heading in the form and the
Overview) do what they say. `help` says what the field is for, in a sentence
or two: the form shows it in a popover from an info button beside the label.
Give every field one; a person new to the app should not have to guess. `list=True` puts the value in the list row,
`card=True` on the card. `search=False` keeps it out of the search text.
A `select` can hide another module's form sections while it has certain
values: Hardware's form factor has `hides=("rack",)` and
`hides_when=("tower",)`, so a tower server's form and Overview have no Rack
position section. What a hidden section holds is left as it is.
Admins can add fields without code (Settings > Custom fields), of the kinds
`text`, `number`, `date`, `select`, `url` and `boolean`.

## Writing records

Everything that creates or changes a record goes through
`hyprvolt.core.records`: `create(type, data)`, `update(entity, data)`,
`set_archived`, `delete`, `restore`. They check the values, write the detail
and custom field rows, rebuild the search text, and write the history, which
nothing else does. Never set attributes on an `Entity` and commit.

`data` is what the API takes: `name`, `slug`, `status`, `location_id`, `tags`
(a list or a comma-separated string), `notes`, `fields` (or `f.<key>`) and
`custom` (or `c.<key>`). A bad value raises `records.Invalid` with a sentence
for a person; roll back and show it.

Links are `relations.link(kind, source, target)` and `relations.unlink(rel)`.
`records.audit(entity, action, changes)` adds a line to a record's history for
anything else a module does to it (Locations logs rack mounts this way).

## Steps of the site setup guide

The site setup guide (New > Set up a site, step by step) walks a site from
the site itself out to its endpoints, one short step at a time. Its steps
are the turned-on modules' `setup`, sorted by `order`: Locations has the
site (10), rooms (20) and racks (30), Contacts vendors (35), Network the
internet connection (40), VLANs (45) and subnets (50), Hardware network
gear (60), servers (70) and endpoints (100), Virtual hypervisors (80) and
guests (85), Services services (90), and Network cables (110). A step of a
new module takes a place between them. `group` is the part of the guide a
step is in, a heading over its steps: Place, Network, Equipment, What runs
or Endpoints. `plan` is how the guide's first page lists what the step
covers, in lower case, commas between several: `"buildings, rooms"`; the
group's steps read as one list, "Site, buildings, rooms, and racks".

```python
SetupStep("gear", "Network gear", "What connects everything, from where the internet comes in.", 60,
          kinds=(SetupKind("Router", "network_device", {"f.kind": "router"}),
                 SetupKind("Firewall", "firewall")),
          fields=(SetupField("name", placeholder="sw-core"), SetupField("location_id"),
                  SetupField("f.model"), SetupField("s.addresses.list", "IP address")))
```

- Each row of a step is a record, made through `records.create` with the
  row's values under the record form's names. `kinds` are what a row can
  be, each a type of the module's own and the values it starts with; with
  more than one, each row chooses.
- `fields` are the row's columns, by their form names. `f.<field>` takes its
  label and control from the type's `Field`; `location_id` offers the site
  being set up and everything in it, the site chosen; `s.<section>.<name>`
  needs a `label` and is left out where the section doesn't apply, and
  `types=("vendor",)` makes it a choice of those records.
- `scope=True` marks the step whose record the steps after it are about
  (the site). Only Locations has one.
- `tree=True` shows the step's records as a tree under the site instead of
  rows, each inside the place it is in (by the kinds' `located_in`), added,
  dragged to another level and deleted in place, each change saved at once
  through the records API. Locations' Buildings and rooms is one.
- A step that makes something other than records (Network's cables) has
  `save(values, scope, user)` instead of `kinds`, `existing(scope)` listing
  what is there, and `SetupField(..., choices=fn)` for its choices.
- A `SetupFinish(key, label, text, make, made=None, open_label="")` is
  offered on the guide's last page. `make(site, found, user)` gets what the
  steps recorded in the site, `[{"group", "title", "records"}]`, and returns
  the record to open; `made(site)` finds one made before, which is opened
  instead. The knowledge base's runbook (`modules/documents/runbook.py`) is
  the worked example.
- A step is saved whole or not at all: an `Invalid` from any row undoes the
  step and is shown with the row's name. Rows with no name are skipped.

## Adding to other modules' forms

A `FormSection` puts fields of one module into the form of another module's
records, with the values kept in the first module's tables. Locations uses
one for the rack position of anything with the `rackmount` trait:

```python
FormSection("rack", "Rack position", render=rack_form, save=rack_save,
            when=lambda etype: "rackmount" in etype.traits)
```

- `render(etype, entity)` returns the fields' HTML, from a template. Each
  input is named `s.<key>.<name>`: `s.rack.position_u`. `entity` is None in
  a new record's form.
- `save(entity, values, user)` runs inside `records.create` and
  `records.update`, after the record's own fields, whenever the data names the
  section. `values` is `{"position_u": "12", ...}`. It checks them, raising
  `Invalid` to refuse the whole save, stores them, and returns the changes
  for the history in the shape `records` uses:
  `[{"field", "label", "old", "new"}]`. To move the record, it calls
  `records.move(entity, place)` and returns that change too; the history
  shows one line per field.
- The API takes the same values as `s.rack.position_u` or nested as
  `"sections": {"rack": {"position_u": 12}}`. A save that doesn't name the
  section leaves its values alone.
- The same HTML appears in an editor's Overview, where the record is edited
  in place. There a change to any of the section's fields saves all of them
  together, so `save` always gets the whole section. Nothing in the template
  needs to know which of the two it is in.

## Pages, tabs and routes

A module's templates go in `templates/<id>/` inside its package; the app
finds them. Tabs, widgets and panes are functions that return
`render_template(...)` of a fragment that extends no page. The macros in
`templates/partials/macros.html` (`entity_link`, `crumbs`, `tag_chips`,
`type_icon`, `dep_tree`) and the components in [DESIGN.md](DESIGN.md) are
there to be used. Modules ship no CSS or JavaScript of their own; a visual
that no component covers becomes a new shared component in `app.css`, listed
in DESIGN.md.

Instead of scripts, a template asks `app.js` for behavior with attributes:

| Attribute | What happens |
| --- | --- |
| `form[data-api="/url"]` | Submitting posts its fields as JSON (as multipart with `enctype="multipart/form-data"`) |
| `[data-api-post="/url"]`, `data-body='{…}'` | A click posts the body |
| `data-confirm="Question?"`, `data-confirm-text`, `data-confirm-go` | Asks first in the confirmation dialog: the question, a line saying what happens, and the action button's label (Remove if not given). Every button that removes a link between records carries it |
| `data-then="sheet"`, `"reload"` or `"remove"` | Afterwards: re-render the open sheet, reload the page, or remove the closest `[data-row]` |
| `data-then="replace"`, `data-replace="id"` | Afterwards: the answer's `html` goes into that element (the next step of a flow, a check's result) |
| `data-done="Message"` | The toast; with Undo when the response has `undo`. An answer's own `message` takes its place |
| `[data-pick]`, `data-pick-types`, `data-pick-into` | Opens the palette to choose a record; its id goes into the form field named by `data-pick-into` (`other_id` by default) and its name into `[data-pick-label]`. `data-pick-exclude="id"` leaves a record out; `data-pick-submit` submits the form once one is chosen |
| `[data-fill='{"field": value}']`, `data-fill-form="id"` | Fills fields of a form and shows it; the field marked `data-fill-focus` gets the focus |
| `[data-new-type="rack"]`, `data-new-location`, `data-new-attach`, `data-new-link="affects:12"`, `data-new-name`, `data-new-fields='{"host": 12}'` | Opens the form for a new record, placed somewhere, attached as a document, linked to a record once saved (new record, kind, that record), with a name, or with fields filled in |
| `[data-open="dialog-id"]`, `[data-close]` | Opens a dialog; closes the one it is in |
| `form.dropzone` | Files dropped on it go in through its file input and the form is submitted |
| `[data-zoom]` (`zoom_frame()` in partials/macros.html, around an `svg.diagram`) | The drawing opens fitted so all of it shows (never larger than drawn); its −, Fit and + buttons, or Ctrl/⌘ and the wheel (a trackpad's pinch), zoom it about the pointer, and zoomed in a mouse drags it around. Every diagram in the app uses it |
| `[data-views="key"]` (radios, a `.seg`), `[data-view="name"]` | Choosing a radio shows the tab's `[data-view]` panel of that value and hides the others; the choice is remembered in the browser under the key and applied whenever the tab is drawn. The dependency view's List and Diagram use it |
| `[data-gallery]`, `a[data-gallery-item]`, `data-large`, `data-caption` | A click on an item opens the gallery's pictures in the viewer, at that one: `data-large` is what it shows, the link's `href` the original |
| `a[data-entity="id"]` | Opens that record's sheet in place (`entity_link` makes these) |
| `input[data-autosubmit]` | Submits its form when it changes |
| `[data-repeat]` | Rows of a form, as many as wanted: `[data-repeat-add]` copies its `<template data-repeat-template>`, numbering `__n__` in the names on; `[data-repeat-remove]` takes a row out |
| `[data-print]` | Prints the page; print styles hide the shell |
| `[data-reveal="/url"]`, `data-reveal-into="id"` | Posts to the URL and shows the answer's `value` in that element, until a second click or 30 seconds (the vault's Show); the element's `data-mask` is what it shows otherwise |
| `[data-copy="text"]`, `[data-copy-url="/url"]` | Copies the text, or posts to the URL and copies the answer's `value` |
| `[data-autosave="/url"]` with `[data-save]` controls, `[data-save-group]`, `[data-prose]`, `data-live="key"` | Editing in place (the core's Overview uses it): a `[data-save]` control posts `{name: value}` to the container's URL when it changes, a `[data-save-group]` posts all of its fields together, and the parts marked `data-live` are redrawn from the server after a save. `[data-prose]` holds long text shown formatted until its `[data-prose-edit]` button |

Routes live on the module's blueprint, which must be named like the module
and is mounted at `/<id>`. Every view declares who may call it with
`@role("viewer")`, `@role("editor")` or `@role("admin")` from
`hyprvolt.permissions`; a manifest whose blueprint has a view without one is
refused. JSON errors are `{"error": "..."}` written for a person. Anything
that can be taken back answers with `"undo": {"url": ..., "body": ...}`, which
the interface offers as Undo. When the module is turned off its routes answer
404.

## Migrations

A module's tables are created by `db.create_all()` the first time the app
starts with the module in place, so a new module needs no migration at all.
After it has shipped, a change to one of its tables is a step appended to
`migrations`:

```python
from hyprvolt.manifest import Step

migrations = (
    Step("0001-rack-power", lambda m: m.add_column("location_details", "power_w", "INTEGER")),
    Step("0002-index-mounts", lambda m: m.add_index("ix_mount_face", "rack_mounts", ["rack_id", "face"])),
)
```

`m` is a `Migrator` (`hyprvolt/migrate.py`): `add_column`, `add_index`,
`once(key, fn)` for data, `has_table`, `has_column`, `execute`. Each checks
before it acts, so every step is safe to run on every boot. Steps are
appended and never edited. The core's steps run first, then each module's in
a fixed order: after the modules it requires, ties by id. The full rule is in
[ARCHITECTURE.md](ARCHITECTURE.md#schema-changes).

## Tests

`tests/conftest.py` loads `tests.example_modules` next to the real modules,
in strict mode. Its fixtures give an admin client (`client`, `h` for the CSRF
header), `editor` and `viewer` clients, and `make(client, h, type, **data)`
creates a record through the API. Test each route's role: a viewer gets 403
on every write.

## Checklist

1. A package in `hyprvolt/modules/<id>/` exporting `module`, with
   `requires` naming the modules it can't work without.
2. Detail tables subclass `EntityDetail`; field keys match their columns.
3. Every route has `@role(...)`; writes go through `records`.
4. Templates in `templates/<id>/`, built from existing components.
5. A `seed(demo)` if the demo should show it.
6. Tests for its routes and their roles.
7. A line in `CHANGELOG.md`; a new component in DESIGN.md.

## Planned modules and the hooks they would use

This is not built yet, and fits the manifest as it is. Certificates, Backup
jobs, Maintenance and changes, Diagram and Asset labels were on this list
and are built; their packages show the hooks in use (a `job` that reads from
the network and commits record by record, a table of runs kept apart from
the history, `remind`, `datetime` fields, a sheet tab on every record,
`data-new-link`, `pages`, SVG drawn on the server).

| Module | Hooks |
| --- | --- |
| **Discovery and sync** (Proxmox, Portainer, pfSense) | A `settings_pane` for the API address and token (the token kept in the secrets vault); a `job` that pulls on a schedule and writes through `records.create` and `records.update`, so every change it makes is in the history; a table of its own mapping outside ids to record ids; a blueprint route for "Sync now"; a `widget` with the last run; the core's `runs_on` and `hosted_by` links |
