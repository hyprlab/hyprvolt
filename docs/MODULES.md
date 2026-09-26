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
| `id` | Lower-case letters, digits and underscores; the URL (`/<id>`) and the name of its settings. Can't be a word the core uses (`all`, `api`, `admin`, `search`, …) |
| `name`, `description`, `icon` | What the sidebar, dashboard and Settings > Modules show. `icon` is the inside of a 24×24 stroked `<svg>`, like every icon in the app |
| `group`, `order` | Where it sits in the sidebar: under the `group` heading, sorted by `order` |
| `requires` | Ids of modules it builds on. They migrate and seed first; a module whose requirement is missing is left out, and one whose requirement is turned off is off too. A module that only takes part through traits (Services pointing at hosts) needs no requirement |
| `core` | Built in; it can't be turned off. Only the knowledge base is |
| `models` | Its SQLAlchemy models, for the record; importing the package is what registers them |
| `migrations` | Its `Step`s, in order. See [Migrations](#migrations) |
| `blueprint` | A Flask blueprint named like the module, mounted at `/<id>`. Optional |
| `types` | Its `EntityType`s. See [Entity types and fields](#entity-types-and-fields) |
| `search` | `search(query, limit)` returning `SearchResult`s for the palette, for things that aren't records (an IP address, a DNS name). Records are searched without it |
| `filters` | `ListFilter`s: sidebar entries with live counts under the module |
| `widgets` | `Widget`s on the dashboard |
| `jobs` | `Job`s the worker runs, each at most every `minutes` |
| `settings_pane` | A `Pane` in the settings window, admin-only by default |
| `relation_kinds` | `RelationKind`s it adds to the core's |
| `sheet_tabs` | `Tab`s on records of any module, shown where `when(entity)` says |
| `form_sections` | `FormSection`s in the record form of any module's types. See [Adding to other modules' forms](#adding-to-other-modules-forms) |
| `seed` | `seed(demo)`, its part of `flask seed-demo`. Seeds run in sidebar order, each after the modules it requires, the knowledge base last, so a module later in the sidebar finds the records it links to |

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
- `tabs` are sheet tabs for this type only. They follow Overview.
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
  supplier and a contract), `domain` (Services: a service's domain).
- `name_from="address"` makes the record's name the shown value of one of
  its fields, and leaves the Name box out of the form: an IP address is
  named by its address.
- `check(entity, detail)` runs on every save after the fields are set, for
  rules that span fields or records: a gateway inside its subnet, a VLAN ID
  used once per network. It raises `Invalid` to refuse the save, and may
  tidy values (Network lower-cases a domain's name).

A `Field` has a `key` that must be a column of the detail table, a `label`,
and a `kind`:

| Kind | Stored as | Shown as |
| --- | --- | --- |
| `text`, `email`, `url` | a string, 500 characters at most | text; a `url` starting with http links out, an `email` is a mailto: link |
| `phone` | a phone number as written, with an extension if any | a tel: link |
| `longtext` | text | text, line breaks kept |
| `markdown` | text | rendered Markdown with `[[slug]]` links, under the fields |
| `integer`, `number` | int, float, with `min` and `max` | the value and its `unit` |
| `date` | a date | `2026-09-25` |
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

A `ref` with `trait="addressable"` instead of `types` points at a record of
any type with that trait, from whichever modules are installed; the form
names each choice's type.

`required`, `default`, `help`, `unit` and `group` (a heading in the form and
the Overview) do what they say. `list=True` puts the value in the list row,
`card=True` on the card. `search=False` keeps it out of the search text.
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
| `data-then="sheet"`, `"reload"` or `"remove"` | Afterwards: re-render the open sheet, reload the page, or remove the closest `[data-row]` |
| `data-done="Message"` | The toast; with Undo when the response has `undo` |
| `[data-pick]`, `data-pick-types`, `data-pick-into` | Opens the palette to choose a record; its id goes into the form field named by `data-pick-into` (`other_id` by default) and its name into `[data-pick-label]` |
| `[data-fill='{"field": value}']`, `data-fill-form="id"` | Fills fields of a form and shows it |
| `[data-new-type="rack"]`, `data-new-location`, `data-new-attach`, `data-new-fields='{"host": 12}'` | Opens the form for a new record, placed somewhere, attached as a document, or with fields filled in |
| `a[data-entity="id"]` | Opens that record's sheet in place (`entity_link` makes these) |
| `input[data-autosubmit]` | Submits its form when it changes |
| `[data-reveal="/url"]`, `data-reveal-into="id"` | Posts to the URL and shows the answer's `value` in that element, until a second click or 30 seconds (the vault's Show) |
| `[data-copy="text"]`, `[data-copy-url="/url"]` | Copies the text, or posts to the URL and copies the answer's `value` |

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

These are not built. Each fits the manifest as it is:

| Module | Hooks |
| --- | --- |
| **Discovery and sync** (Proxmox, Portainer, pfSense) | A `settings_pane` for the API address and token (the token in the secrets vault, Phase 5); a `job` that pulls on a schedule and writes through `records.create` and `records.update`, so every change it makes is in the history; a table of its own mapping outside ids to record ids; a blueprint route for "Sync now"; a `widget` with the last run; the core's `runs_on` and `hosted_by` links |
| **Certificates** | A `certificate` type with issuer, names and an expiry `date`; a `job` that checks expiry (and can fetch certificates from hosts); a `ListFilter` "Expiring soon" with a count; a `widget`; a `search` provider for host names; a `RelationKind` "secures" |
| **Backup jobs** | A `backup_job` type with its schedule, retention and last success; the core's `backs_up` link to what it backs up; a `job` that marks stale ones; a `ListFilter` "Failing or stale"; a `widget` |
| **Maintenance windows and change log** | `maintenance` and `change` types with start and end dates and a Markdown description; a `RelationKind` "affects"; a `sheet_tab` on any record listing its windows and changes; `relations.walk()` to list what a window takes down; a `widget` of what is coming up. The core's history already logs every edit; this module is for changes people describe |
| **Network diagram** | A blueprint page that draws an SVG on the server from `relations` and Network's cables (`network_cables`, port to port), and a `sheet_tab` showing the neighborhood of one record. `requires=("network",)`. No script needed |
| **Asset labels** | A blueprint page of printable labels, each with a QR code linking to `/e/<id>` (which opens `?open=<id>` in the right module), reached from a `ListFilter` or a `sheet_tab`. It needs a QR encoder: a small dependency or a hand-written one, to be decided then, and print styles added to `app.css` as a shared component |
