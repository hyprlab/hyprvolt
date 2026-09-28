# Architecture

One Flask process, SQLite in one volume, server-rendered HTML, and one
JavaScript file with no build step. On top of that, a small core that every
documented thing shares, and modules that declare what they add. This page is
how the pieces fit and why.

## Layout

```
hyprvolt/
  __init__.py      the app factory: modules, database, sessions, CSRF, setup
                   gate, headers, error pages, template globals, migrations,
                   worker
  config.py        every environment variable, each with a working default
  models.py        users, API tokens and runtime settings
  tokens.py        API tokens: Bearer authentication for scripts
  permissions.py   roles, and the @role decorator every route carries
  manifest.py      what a module declares: Module, EntityType, Field, Tab, …
  registry.py      finds the modules, checks them, orders them, mounts them
  migrate.py       the guarded helpers migration steps use
  auth.py          sign in, sign up, sign out, Turnstile, the sign-in throttle
  setup.py         the first-run wizard
  main.py          the dashboard, the lists, palette search, account and admin
  cli.py           flask commands: create-user, reset-password, backup,
                   restore, export, seed-demo, secrets, turnstile
  demo.py          the demo homelab, gathered from the modules' seeds
  worker.py        the background jobs: the core's and the modules'
  core/
    models.py      entities, tags, custom fields, relationships, attachments,
                   the audit log
    records.py     the one write path: create, edit, archive, delete, restore,
                   purge, history
    fields.py      field kinds: parsing, checking, display, search text
    relations.py   relationship kinds and the dependency walk
    depmap.py      the dependency walk drawn as SVG, in the Relationships tab
    markdown.py    Markdown with [[slug]] links, through the sanitizer
    attachments.py files on disk
    images.py      a record's featured image and gallery, and their thumbnails
    api.py         the JSON API
    views.py       the detail sheet and the form, as HTML fragments
    shell.py       the sidebar and what surrounds every page
    present.py     how a record shows in a card or a row
    reminders.py   dates coming up, for the dashboard and the badge
    clock.py       the instance's time zone, and times in it
    transfer.py    CSV export and import, the JSON export
    backups.py     backups and restores, made and scheduled in Settings
  modules/
    documents/     the knowledge base (built in)
    vault/         secrets, encrypted (built in)
    locations/     sites, buildings, rooms, racks and shelves
    hardware/      servers, network gear, UPSes and the rest
    virtual/       clusters, hypervisors, VMs, containers, stacks
    network/       networks, VLANs, subnets, IP addresses, ports, DNS
    services/      what people use, and what it runs on
    certificates/  TLS certificates, read from the servers that serve them
    backup_jobs/   backup jobs and their runs
    maintenance/   maintenance windows and the change log
    diagram/       the network diagram and each record's neighborhood
    labels/        printable asset labels with QR codes
    software/      titles, installations and licenses
    contacts/      vendors, people and contracts
  about_docs.py    parses CHANGELOG.md for the About section
  sanitize.py      allowlist HTML sanitizer, stdlib only
  static/          css, js, fonts, images
  templates/       base, the shell, the sheet, auth, setup, error, partials
tools/             release and repository tooling
tests/             pytest, with an example module of its own
```

`run.py` is the development server. Production runs gunicorn against
`hyprvolt:create_app()`.

## Modules

**A module is a manifest.** Each package in `hyprvolt/modules/` exports a
`Module` that says what it adds: its entity types and their fields, its
routes, sidebar filters, dashboard widgets, jobs, settings pane, relationship
kinds, sheet tabs and form sections on other modules' records, migration
steps and demo data. The core builds everything
else from that: lists, cards, forms, the sheet, search, the API. How to write
one is [MODULES.md](MODULES.md).

**Discovery, not registration.** The registry imports every subpackage of
the packages in `MODULE_PACKAGES`, so a new module is a new directory and no
core file changes. It runs before the blueprints are registered (the
`/<module>` URL converter needs the module ids) and before `create_all` (so
every module's tables exist).

**Checked at startup.** A manifest with a bad id, an unknown field kind, a
field without a column, a duplicate type or relationship kind, a missing
requirement, a circle of requirements, or a route without a role is left out
and shown in Settings > Modules, or stops the app with `MODULES_STRICT=1`.
A broken module can't take the instance down, and a mistake shows up in the
test suite rather than in production.

**Off is hidden, not gone.** An admin turns a module off in Settings; the
choice is a row in `settings` (`module:<id>:enabled`). A module that is off
disappears from the sidebar, search, the dashboard, the API and other
records' tabs, and its routes answer 404, but its models are still imported,
its migrations still run and its rows stay. Turning it back on is instant.

**No module CSS or JavaScript.** Modules render on the server, SVG included,
from the shared components in [DESIGN.md](DESIGN.md), and ask `app.js` for
behavior with `data-*` attributes (posting a form, choosing a record,
refreshing the sheet). One stylesheet and one script stay the whole client.

## The shared core

**Every documented thing is a row in `entities`.** Its name, slug, status,
location, tags, notes, archived flag and who changed it when. What is
particular to a type lives in its module's detail table, one row per entity,
keyed by the entity's id. Because everything has an id in one table,
relationships, custom fields, attachments, documents and history work for
every type, including ones written later.

**Not everything is a record.** What comes by the dozen and only matters
as part of something else lives in its module's own tables: rack mounts,
the ports on a device, the cables between them, a domain's DNS records.
They are shown and changed in a tab of the record they belong to, and each
change is written to that record's history. An IP address is a record,
because it is searched for, linked to and given notes on its own; which
addresses of a subnet are free is worked out, not stored.

**A location is an entity.** `entities.location_id` points at a record of a
location type (a site, a room, a rack), and a location's own location is its
parent. One column gives every record its breadcrumbs, and the Locations
hierarchy needs nothing more.

**One write path.** Every change goes through `core/records.py`, which checks
the values, writes the detail and custom field rows, rebuilds the search text
and writes the history. Imports, sync jobs and the demo use it too, so the
history is complete and search is never stale.

**Search is a column.** `entities.search_text` holds the lower-cased name,
slug, notes, tags and every searchable field value, custom fields included,
rebuilt on each save. A LIKE over it is fast enough for thousands of records.
If it ever isn't, an FTS5 table can take its place without touching a module.

**Relationships are typed and directed.** A kind has a label for each
direction ("runs on", "runs") and an impact: which end breaks when the other
goes down. The dependency view walks only kinds with an impact, marks a loop
instead of following it, and shows a record reached twice once in full. A
field that names another record in a way that matters when it fails (a VM's
host) is kept as a relationship, not a column, so the form and the
dependency view can never disagree.

**Secrets are a built-in module with a permission of their own.** The vault
(`modules/vault`) keeps its values encrypted with a key outside the
database, shows its tab only to admins and accounts given `can_see_secrets`
(`User.sees_secrets`), and writes
every reveal to the record's history. The core hides those history lines
from everyone else; nothing else in the core knows about secrets.

**Reminders are data, not code.** A module marks a date field `expires`; the
core keeps a `reminders` table of what falls within the window, updated by
every save and by the worker's hourly pass, and the dashboard and sidebar
badge read it. No module writes a reminder job of its own.

**A restore is a copy, not a file swap.** Settings > Backups restores by
copying the backup's database into the live one with SQLite's backup API,
under SQLite's own locking, then swapping the attachments folder and running
the migrations for an older backup. It changes the session epoch, which is
part of every sign-in id (`User.get_id`), so every session and remember-me
cookie from before stops matching: nobody stays signed in as whoever had
their user id in the restored database.

**A token is a user for one request.** `tokens.authenticate` runs before the
CSRF check: a valid `Authorization: Bearer` token sets Flask-Login's user for
that request only, without a session, so there is no cookie to forge and no
CSRF token to check. The role decorator then treats it like anyone else.

**SQLAlchemy begins every SQLite transaction.** The sqlite3 driver's own
transaction handling breaks savepoints (releasing one commits it), so it is
turned off on connect and SQLAlchemy emits `BEGIN` itself. An import's check
relies on this: it runs every row in a savepoint and rolls the whole
transaction back.

**Delete marks, the worker purges.** Deleting stamps `deleted_at`. Undo
clears it, so the record comes back with the same id, its links, files,
history and every `/e/<id>` link intact, which re-creating a record could not
do. The worker purges what was deleted more than `purge_days` ago (30 by
default), files first. Attachments are removed the same way.

**History outlives what it describes.** `audit_log` copies the user's and the
record's names in rather than joining, and has no foreign key to `entities`,
so the history of a purged record or a deleted account still reads right.

## Decisions

**One gunicorn worker, eight threads.** The background thread must start
exactly once, and SQLite is happiest with one writing process. Threads carry
the concurrency. If the app outgrows that, the answer is moving the background
work to its own container, not adding web workers against one SQLite file.

**SQLite in WAL mode.** Readers don't wait for the writer, and
`busy_timeout` makes a writer wait for the lock instead of failing. Foreign
keys are switched on, which SQLite leaves off by default; the detail tables,
tags, links and files rely on `ON DELETE CASCADE`.

**Roles, not owners.** The documentation belongs to the instance. An account
is a viewer (reads everything), an editor (also writes) or an admin (also
users, modules, custom fields and settings). The first account is the admin,
and the last admin can't be removed. Every route carries `@role(...)` or
`@public`, and the app refuses to start if one doesn't, so no route reaches
production without a decision about who may call it.

**Server-rendered HTML, one JavaScript file.** Jinja renders pages and
fragments; `app.js` handles what would be worse as a page load. Paging asks
the server for the same list template (`?partial=1`), and the detail sheet
and the form are fetched as HTML (`/e/<id>/sheet?tab=`, `/e/form?type=`), so
there is one renderer for each view of a record, escaped by Jinja, not a
second one in JavaScript that could drift. Nothing is compiled, so what is in
the repository is what runs.

**Session CSRF, not an extension.** A token in the session goes back as a
hidden `_csrf` field from forms and an `X-CSRF` header from `fetch`, compared
with `secrets.compare_digest`. One `before_request` covers every mutating
method.

**JSON errors for the API, pages for people.** A request that sent `X-CSRF`,
a JSON body, or prefers JSON gets `{"error": "..."}`; anything else gets the
error page. The client shows `error` as written, so it is written for a person.

**Two kinds of setting.** Environment variables are fresh-install defaults.
Anything an admin changes while the app runs is a row in `settings`, and the
stored value wins. A compose file can move between machines without carrying
one machine's choices with it.

**Preferences on the account.** Theme, default view and infinite scroll are
columns on `User`, so they follow the person to another browser. The theme is
applied by an inline script in `<head>` before first paint, or the page flashes
the wrong one.

**The changelog is the single record.** The About section renders `CHANGELOG.md`,
so one file is updated per release and the app shows exactly what the
repository says.

## Schema changes

There is no migration framework. At every boot `db.create_all()` runs first,
then `_migrate()`: the core's steps, then each module's, in the registry's
migration order (each module after the ones it `requires`, ties by id; it
never depends on anything an admin can change). `create_all` creates any
table that is missing, with all its columns and indexes, and never alters one
that exists. That decides what a change needs:

| Change | What to do |
| --- | --- |
| A new table (a new model, a new module) | The model only. `create_all` makes it on new and old installs alike |
| A new column on an existing table | The model column **and** an appended step, `m.add_column(table, column, ddl)`. On a fresh install `create_all` already made the column and the step does nothing; on an old one only the step adds it. SQLite needs a `DEFAULT` for a `NOT NULL` column, and a foreign key column must default to NULL |
| A new index on an existing table | A step, `m.add_index(...)`: `create_all` only makes indexes with new tables |
| A change to data (a backfill, a rename of values) | A step using `m.once(key, fn)`, which records that it ran in `settings` (`migration:<owner>:<key>`) |
| A renamed or dropped column, a changed type | A table rebuild, and a MAJOR release ([RELEASING.md](RELEASING.md)) |

Steps are appended and never edited: an install that ran a step won't run
its new version. Each helper checks before it acts, so every step is safe on
every boot and safe twice. The core's steps are in `_migrate()` in
`__init__.py`; a module's are its manifest's `migrations`. A step that makes
the database unreadable to the previous version is a MAJOR release.

## A request

1. `ProxyFix` rewrites the client address and scheme, if `TRUST_PROXY` is set.
2. A request to a turned-off module's blueprint answers 404.
3. `steer_to_setup` sends everything to `/setup` while there are no users.
   Static files and `/healthz` are exempt.
4. `check_csrf` rejects a mutating request without the session token.
5. The route runs behind `@role(...)`: signed out, a page redirects to sign-in
   and an API call gets a JSON 401; without the role, a 403 that says which
   role it needs.
6. `headers` adds `no-store` to HTML (the back button must never show records
   that have since changed) and the security headers. Attachments are served
   with `Content-Security-Policy: sandbox`, except PDFs, and anything but
   images, PDFs and plain text downloads rather than opening.

## Where state lives

| | |
| --- | --- |
| `DATA_DIR` (`/data` in Docker, `./var` locally) | The SQLite database, the generated `.secret_key`, the secrets vault's `secrets.key` (unless `SECRETS_KEY` is set), `attachments/`, `thumbs/` (smaller copies of attached images, made again when missing, so not backed up), `backups/` (unless `BACKUP_DIR` is set) and `imports/`, uploads between an import's steps, cleared after a day |
| `users` | Accounts, their roles and preferences |
| `settings` | Instance settings, which modules are off, migration markers, when each job last ran |
| `entities` and the core tables | Every record, its tags, custom values, links, files and history |
| Each module's tables | What is particular to its types |
| The session cookie | The signed-in user and the CSRF token |

Backing up the app is backing up `DATA_DIR`; `flask backup` makes a
consistent archive of the database and the attachments (see
[DOCUMENTATION.md](DOCUMENTATION.md#backups)).
