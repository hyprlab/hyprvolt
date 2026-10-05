# Documentation

Installing, configuring and running Hyprvolt.

## Installing

Hyprvolt runs as one Docker container with its data in one volume.

```sh
mkdir hyprvolt && cd hyprvolt
curl -O https://raw.githubusercontent.com/hyprlab/hyprvolt/main/docker-compose.yml
docker compose up -d
```

Open `http://<host>:8101`. The first visit opens the setup wizard, which
creates the admin account, then goes on into the guide that documents the
first site a step at a time ([Setting up a site](#setting-up-a-site)). There
is no default account or password. It is in the dark theme, as every new
account is; the sun button at the top switches to light, and the admin
account keeps the choice (Settings > Appearance changes it later). The guide's first page, and the dashboard
while the instance is empty, offer to load a demo homelab to look around in
instead; `flask seed-demo` does the same from the server.

From a clone of the repository, `docker compose up -d` runs the same
published image. `tools/redeploy.sh` builds the image from the working tree
instead, tagged `local`, and runs that.

## Configuration

Everything is optional. Put values in a `.env` file next to
`docker-compose.yml` (`.env.example` has the common ones), then
`docker compose up -d` to apply.

| Variable | Default | What it does |
| --- | --- | --- |
| `IMAGE_TAG` | `latest` | The image to run: `latest` for stable, `beta`, or a version to pin |
| `APP_NAME` | `Hyprvolt` | What the app calls itself |
| `APP_TAGLINE` | `IT documentation for on-premise infrastructure.` | The line under the name on the sign-in page and in About |
| `SECRET_KEY` | generated | Signs sessions. If unset, one is generated and kept in the volume |
| `SECRETS_KEY` | made in the volume | Encrypts the secrets vault; see [Secrets](#secrets) |
| `BACKUP_DIR` | `/data/backups` | Where Settings > Backups keeps backups; point it at another disk |
| `SESSION_COOKIE_SECURE` | `0` | Set to `1` when the app is served over HTTPS |
| `TRUST_PROXY` | `0` | How many reverse proxies are in front; see below |
| `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` | empty | Cloudflare Turnstile keys; see [Turnstile](#turnstile). Usually set in the app instead |
| `ALLOW_REGISTRATION` | `0` | Whether anyone can create an account. The setup wizard asks and saves the answer, which wins from then on |
| `WORKER_MINUTES` | `15` | How often background work runs. The setup wizard saves 15, which Settings > Admin changes; `0` here keeps the worker from starting at all |
| `ITEMS_PER_PAGE` | `40` | Records per page |
| `TZ` | `UTC` | The time zone the app starts with, such as `America/Chicago`. Settings > Admin changes it |
| `DATA_DIR` | `/data` | Where the database and attachments live inside the container |
| `MODULES_STRICT` | `0` | Stop at startup when a module's manifest is broken, instead of leaving the module out |
| `DATABASE_URL` | the SQLite file in `DATA_DIR` | Where the database is. Only SQLite is supported; backups copy it with SQLite's own API |
| `SOURCE_URL` | the GitHub repository | Where About links to the source code |

`ITEMS_PER_PAGE` and the Turnstile keys are only defaults for a fresh
install, and the setup wizard saves its own answers for sign-up and the
worker. Once a setting is saved in Settings (under Admin or Security), what
is saved there wins.

## Accounts and roles

Every account has a role:

| Role | Can |
| --- | --- |
| Viewer | Read everything, and download attachments |
| Editor | Also create, edit, link, archive and delete records, and attach files |
| Admin | Also manage users, modules, custom fields and the instance settings |

The account made in the setup wizard is an admin. Admins set each account's
role in Settings > Admin, and the role accounts from sign-up start with
(viewer unless changed). Sign-up is off on a fresh install. An admin can't
change their own role or delete themselves, so there is always one left.

Changing a password, in Settings > Account or by an admin's reset, signs the
account out everywhere else, remember-me cookies included; the session that
changed it stays signed in.

## Modules and custom fields

What Hyprvolt documents comes in modules: Locations, Hardware, Virtual,
Network, Diagram, Services, Certificates, Backup jobs, Maintenance, Software, Contacts and vendors,
Asset labels, and the knowledge base. Settings > Modules turns a module off; it then
disappears from the sidebar, search and the dashboard, and its records stay
in the database until it is turned back on. A module that needs another is
off while that one is: Hardware needs Locations, and Virtual and Network
need Hardware. The knowledge base and Secrets are built in, and stay on.

An admin also sets the sidebar's order there: drag a group, or a module
within its group, by its handle, or focus the handle and use ↑ and ↓. The
order is saved as it changes, for every account, and Put the default order
back undoes it. A record's sections from other modules follow the same
order.

A location, a piece of hardware, or a VM or LXC container can be made
another kind in its Overview, under Type: a room that is really a building, a
server recorded as a NAS, a VM that is really an LXC container. It keeps its
name, links, files and history, and then shows the fields of the kind
chosen; values the new kind has no field for are kept, and come back if it
changes back. The change waits until everything fits: a building goes in a
site and a rack only in a room, so a room with racks in it becomes a
building once they have moved. A rack is emptied first, and anything
mounted in one comes out before it becomes something that can't be. A
device with software installed, or that services or hypervisors run on,
stays a kind that can host them.

Hardware's status is where a device is in its life: deployed, ordered, in
stock, in repair, retired or disposed. Anything that goes in a rack has its
rack, units and face in its own form, and choosing a rack there makes the
rack its location. The sidebar lists hardware whose warranty ends within the
reminder window and hardware out of warranty (retired and disposed hardware
is left out of both), and the dashboard's Coming up card shows warranties
near their end. A UPS's Powers section ticks the equipment plugged into it,
also in the setup guide's UPSes step, which offers the site's equipment:
each is then powered by the UPS, and shows as going down with it. An IP
phone records who uses it and its extension, and is added with the other
endpoints in the setup guide's Endpoints step, as is an IP camera.

An operating system field (a VM's, a container's, a server's) offers known
operating systems as it is typed in: typing "ubu 24" lists Ubuntu Server and
Ubuntu Desktop 24.04 LTS, and a click or the arrow keys and Enter fills it
in. The last choice keeps what was typed, for a name not on the list.

In Virtual, what something runs on is a field in its form: a VM's host, a
hypervisor's hardware, a container's Docker host and stack. Each is also a
link in the Relationships tab, so the dependency view goes from a server
through its hypervisor and VMs down to the containers. A hypervisor's
Guests tab adds up the vCPUs and memory of its running guests against the
cores and memory recorded for its hardware, and a cluster's does the same
for all its hypervisors. The sidebar lists VMs, containers and the rest that
have no host yet. A bare-metal hypervisor is its server's operating system,
so the address it is managed at goes on the hypervisor, and the server keeps
only its iDRAC, iLO or IPMI address. Giving a hypervisor an address recorded
on the server it runs on moves the address to it, and says so; any other
address already assigned is refused. A server's or a NAS's Hypervisor section (also in
the setup guide's Servers and storage step) has Runs a hypervisor: ticked,
it adds a hypervisor of the same name running on the server, with its
platform and management IP, and the server's IP address becomes its BMC's;
unticked, it deletes that hypervisor after asking, unless something runs on
it.

In Network, a device's or a VM's IP addresses are typed into its own form,
separated by commas; each becomes an IP address record in the subnet that
holds it, and one taken off the list is deleted (it can be restored from
Recently deleted), or only unassigned if it has notes or tags. An address can
belong to one record at a time. A subnet's range is typed as its network
address with the subnet mask chosen beside it, and its DHCP range as its
first and last address; a range the DHCP addresses don't fit in is refused.
Once the range is typed, the gateway is filled in with its first address
and the DHCP range with its upper half (.128 to .254 in a /24), leaving the
lower half for fixed addresses; a gateway or range typed by hand is left
alone.
A subnet's Addresses tab draws an IPv4 subnet
up to a /22 as a grid: used, reserved, held for DHCP or free. Choosing a free
address records it. Anything with network ports has a Cabling tab. A cable
goes to the device as a whole, to another device or to one of its ports,
with no ports to set up first. A switch, router or firewall given a number
of Ports (in its form, or the guide's Network gear step) takes no more
cables than that: its Cabling tab counts them, a full one is no longer
offered as the other end, and Suggest cables stops at it; with Ports left
empty there is no limit. To be more exact about a device, turn on
Record each port, the switch at the top of its Cabling tab: then add its
ports in a run (Port 1 to 24, or a patch panel's Front and Rear pairs), set
a port's VLANs, and cable each port; a patch panel needs its ports recorded
for a path to go through it. Turning it off again keeps the ports, out of
sight. A cabled port's path can be traced to the far end through patch
panels. An internet connection
is a network of the kind Internet connection, with its download and upload
speeds (each a number with Mb/s or Gb/s chosen beside it), a Dynamic or
Static switch for its IP address, and circuit ID. Static shows the line's
fixed address, subnet mask (255.255.255.248 or /29), gateway and DNS
servers; a gateway outside the address's network is refused. Dynamic hides
them and keeps what was there. Its Comes in at names the modem, router or
firewall the line plugs into (also set from that device's Internet
connections section, and in the guide's Network gear step): the device then
brings in the line, the network diagram draws the line above it, and the
line depends on it. A router or firewall at a site with more than one ISP
(dual WAN, or a mobile backup) has each of its lines ticked there; a line
comes in at one device, so ticking it on another moves it. A modem in bridge mode has no address on your network
and can be left without one. The ISP is a vendor, chosen in its Supplier
section, with the contract for the line. The sidebar lists internet
connections. A network device of the kind Wireless bridge links two places
over the air: each end is its own record, with its own location and IP
address, and its Wireless link section names the bridge at the other end, a
link that reads the same from both; the diagram draws it as a dotted line.
A Wireless extender is network gear that repeats an access point's signal.
A MoCA adapter carries the network over the coaxial cable in the walls, and
two of them work like one cable: each is its own record, where it is (so
each can be powered by a UPS of its own), and its Coax link section names
the adapter at the other end of the coax. In the guide's Network gear step
a pair is one row: Where is one end, and Other end at the place of the
other, which adds that adapter there (named for the pair and the place,
with the same model) or moves it; deleting the row deletes both, and its Undo
brings both back. Each is cabled to what it plugs into, and a trace,
the Neighborhood and the network diagram go straight through the pair,
naming the two adapters on the link as they do a patch panel.
A wireless network is one Wi-Fi network name (SSID), with its security,
bands, whether it is hidden, and the VLAN and subnet it puts devices on;
its password belongs on its Secrets tab. The gear that broadcasts it (an
access point, or network gear of the kind Modem, Router, Wireless extender
or Wireless bridge) is ticked in its Broadcast by section, or the other way
round in that gear's Wireless networks section; the network depends on the
gear that broadcasts it. A switch, a router, a firewall or a modem that
is the gateway ticks the VLANs and subnets it carries in its Networks
section (and in the guide's Network gear step), or the other way round in
a VLAN's or subnet's Carried by section; a subnet on a VLAN comes with the
VLAN. A network depends on the gear that carries it, so the dependency view
of a switch lists the networks it takes down. A domain's DNS records
are written down by hand in its DNS records tab, and an A record or a CNAME
that leads to a recorded address links to the device holding it. The
palette finds DNS names and MAC addresses. The sidebar lists addresses with
no device and domains due for renewal within the reminder window, or
overdue by no more than it.

A service is what people use: its address, ports, who uses it, how much it
matters, what it runs on and the domain it is under. The last two are also
links, so the dependency view of a server or a domain lists the services
that go with it, and the dashboard shows the services marked high or
critical and any that are degraded or down. One that isn't on your
premises, such as Microsoft 365 or a hosted website, runs on Cloud service,
at the top of the Runs on list.

A certificate records the names it covers, its issuer, its dates, its key
and its fingerprint, and what uses it: a service or host chosen in its form, or
anything linked as "secures" in Relationships, so the dependency view of a
certificate lists what breaks when it expires. Its expiry is on the Coming
up card like a warranty; one marked "Renews by itself" only once it is 21
days from its end, since by then its renewal has failed. The Check tab reads
a certificate from its PEM text, and given a host and port in "Check at",
the app connects there once a day, reads the certificate the server
presents, and updates the record when it has changed, so renewals keep the
dates current by themselves. The check trusts nothing and sends nothing but
a TLS handshake; it goes out from the app's server, so the address must be
reachable from there. The sidebar lists certificates expiring soon and those
whose last check failed.

A backup job records its tool, what it backs up, where it saves to, its
schedule, how long it keeps copies, and how often it should succeed. What it
backs up gets a Backups tab showing the jobs and how each stands. Its status
follows its runs: Succeeding, Warnings or Failing after the latest run, and
Overdue once half an interval more than it should take passes without a
success (a nightly job after 36 hours). The backup script reports each run
with an API token; the job's Runs tab shows the command to add to it, and
runs can be recorded there by hand too. A paused or retired job keeps its
status. Only the changes of status go in the history, and each job keeps its
latest 200 runs. The dashboard's Backups card lists the jobs failing or
overdue, and the next restore test is on the Coming up card.

A maintenance window has a start and an end, the impact people will notice
(an outage, degraded service, or none), who does it, whether users were
told, and a plan in Markdown. Its Impact tab lists what it affects, added
from the palette, and, unless nothing is interrupted, everything that goes
down with those: what runs on them or depends on them, however far down.
A window's status is what was decided (planned, done or canceled); whether it
is coming or under way follows from its times. The dashboard's Maintenance
card lists the planned windows of the next 30 days, those under way marked,
and the changes of the past week.

A change is something someone did to a system: when, what kind, who did it,
what and why, and the window it was part of. Every other record has a
Changes tab: its change log and its maintenance, with buttons to record a
change or plan maintenance that start out linked to it. A change left
without a time is one made now. The sidebar lists maintenance coming up and
under way, the changes of the last 30 days, and the changes that failed or
were rolled back. The history of each record still logs every edit to it;
changes are what people did to the systems themselves.

Diagram draws the network from its cables: every device with a cable to
another, the cables traced through patch panels and over pairs of MoCA
adapters (which are named on the link rather than drawn), in tiers from the internet side: modems, then
routers and firewalls, then outward. A "connected to" link between two
devices with no cable recorded is drawn dashed. Hovering a link shows its
ports and VLANs; choosing a device opens it. Every record with links or
cables also has a Neighborhood tab, drawing what it is linked to on the
left (and cabled to) and what is linked to it on the right. Diagram needs
Network.

Asset labels prints a label for each record of a list: open any list,
filter or search it, and choose Print labels in its export menu. Each
label has a QR code that opens the record in the app, its name and kind,
its asset tag or serial number, and the two innermost places it is in (a
rack in a room). Sheets of 30 on Letter (Avery 5160) and 21 on A4 (Avery
L7160), and single 62 × 29 mm labels for a label printer, print at their
real size at 100% scale with the default margins. Up to 300 labels at a
time.

Times, such as a window's start, are typed and shown in the instance's time
zone, set in Settings > Admin (it starts as the `TZ` environment variable, or
UTC). They are stored in UTC, so changing the zone moves nothing; a time sent
to the API with an offset or a `Z` is taken as it says, and one without, in
the instance's zone. The API returns times in UTC with a `Z`.

Software titles are installed on hosts: record an installation in the
title's Installations tab or the host's Software tab, with its version and
the license seat it takes. An installation at another version than the
title's current one is marked as behind. A license's seats in use are its
installations plus the seats it says are used elsewhere; the sidebar lists
licenses over their seats and those due for renewal.

Vendors hold support numbers and account numbers, people work at them, and
contracts are with them. Hardware, software, services, networks and domains
have a Supplier section in their form: the vendor and the contract that
covers them. A vendor's Supplies tab and a contract's Covers tab list what
is linked; the sidebar lists contracts ending within the reminder window, or
ended by no more than it. Phone numbers
are kept as typed, not checked; one that can be dialed is a link, a vanity
number such as 1-833-VERIZON dialing its keypad digits. Email addresses are
links too.

Settings > Custom fields adds fields of your own to any kind of record: text,
a number, a date, a choice list, a web address, or yes or no. They appear in
the record's form and Overview, and search finds their values. Removing one
removes its values too, with Undo.

## The knowledge base

Documents are Markdown pages: runbooks, how-tos, manuals. A document can
stand alone, be attached to records (their Documents tab), and link to any
record by writing its slug in double brackets, `[[pve1]]` or `[[pve1|the
main host]]`. A link to a slug that matches nothing is struck through, so a
broken link shows.

- **Headings** keep their levels: `#` and `##` are sections, `###` and
  below subsections. Each heading gets an anchor, `h-` and its words (a
  heading "Setup" is `h-setup`), for links within the page, and a page with three or more headings opens with a
  contents list.
- **Code** in a fenced block names its language, ```` ```bash ````,
  ```` ```powershell ````, ```` ```python ````, and is colored for it.
- **Task lists**: `- [ ]` and `- [x]` items show as checkboxes.
- **Tables** keep `colspan` and `rowspan` when written as HTML.

A document can be a page of another: choose the parent in "Part of" and a
number in "Order". The parent lists its pages in order, with an Add a page
button; each page shows its path, such as IMS Exporter › Setup, and links
to the pages before and after it. The sidebar's Top-level pages filter
hides the pages, leaving the documents they belong to. Pages nest eight deep
at most, and a document can't be a page of itself or of one of its pages.

A document's Linked from tab lists the documents that link to it; another
record's Documents tab lists those that mention it.

Search reads attached files too: a text file (notes, configs, scripts, CSV,
JSON, logs) or a PDF is read when it is uploaded, and its words find the
record it is attached to, as does its file name. Up to 200,000 characters of
each file count. Files attached before this came in are read in the
background, a few every ten minutes. A scanned PDF with no text layer has
nothing to read.

A document's "Visible to" narrows who can read it: everyone signed in (the
default), editors and admins, or admins and the people given access to
secrets in Settings > Admin. Anyone below the level never sees the document:
not in lists, search, counts, tags, links, exports, labels or the API, where
it answers 404 like a record that isn't there. A `[[link]]` to it is struck
through for them, and a history line naming it is left out, or says "a
restricted record". Nobody can set a level that would hide the document from
themselves. An API token reads what its account may.

## The dashboard and reminders

The dashboard counts what each module documents, lists what changed
lately, and carries the cards modules add (rack space, hypervisors, subnets,
services, backups). Its Coming up card lists every warranty, license
renewal, contract end, domain renewal, certificate expiry, restore test and
UPS battery date that falls within the
reminder window, from that many days before the date until that many days
after; the Dashboard entry in the sidebar shows how many. The window is 90
days unless an admin changes it in Settings > Admin ("Remind of dates
within"). Records that are archived, retired or disposed are left out.

The background worker brings the list up to date every hour as the days go
by, and saving a record updates its own dates at once. The sidebar filters
for warranties, renewals and contracts ending soon use the same window.

## Import and export

Every list, as filtered and searched, exports as a CSV file from the
download button in the top bar: one row per record with its name, status,
location path, tags, every field and custom field, notes, dates and a link.
Choices come out as their labels, linked records as their names, and text
that a spreadsheet would read as a formula gets a leading apostrophe.

Editors import from the same button. A CSV file (comma, semicolon or tab,
with a header row, up to 5 MB and 5,000 rows) becomes records of one kind:

1. Choose the kind of record and the file.
2. Say which column goes into which field. Columns whose heading matches a
   field's name are matched already; leave out the rest. A location can be
   given by name, slug or full path (`Home lab > House > Basement`); a linked
   record by name or slug; a choice by its label.
3. Say what to do with records that are already there: always make new
   ones, or update the one with the same name (or slug). An empty cell
   leaves a field as it is when updating.
4. Check. The whole import runs and is rolled back, and the result says
   what would be made or updated, and why any row can't be.
5. Import. Rows with a problem are left out; the rest are saved, each with
   its line in the history. An exported file imports back unchanged.

Services can also be read from a [Homepage](https://gethomepage.dev)
dashboard: Import from Homepage, under Services in the sidebar and in the
setup guide's Services step. Choose its `services.yaml`, and its
`docker.yaml` if it has one (each up to 1 MB). Each service's name, group,
link and description are read, and what it runs on is worked out from what
the file says:

- its Docker server and container: the container record on the Docker host
  of that name, or at the address docker.yaml gives;
- its Proxmox node and ID: the VM or LXC container with that ID on that
  node;
- its addresses (the widget's, the site monitor's, the ping's, then the
  link's, which may be a reverse proxy's): the record an IP address is
  assigned to, a name in a DNS record written down in Network, or a host
  name like a record's own name.

The review lists every service with what it would run on and why: Matched
when one record is clearly best, Check when it is only likely, and Choose
when nothing points anywhere or two are as likely, those first. Each has its
Runs on, kind (guessed from the app: Sonarr is media, AdGuard Home DNS) and
whether to add it, update the service of the same name, or leave it out.
Import saves them, tagged with their Homepage group unless that is turned
off, the description as notes and an address's port as Ports. API keys and
passwords in the file are never read, and a value Homepage fills in itself
(`{{HOMEPAGE_VAR_...}}`) is left out.

Settings > Admin exports the whole instance as one JSON file: every table
and row, the modules' own included, with password hashes, secret values, API
token hashes and the Turnstile secret left out. Attached files are listed but
not included, nor the text search read from them. It is for reading elsewhere, not for restoring: a backup from
Settings > Backups is. `flask export PATH` writes the same file from the
server.

## The API

Everything the interface does goes through a JSON API, and scripts can use it
too. Make a token in Settings > API tokens, then send it as a header:

```sh
curl -H "Authorization: Bearer hv_…" "http://localhost:8101/api/entities?type=server"
curl -H "Authorization: Bearer hv_…" -H "Content-Type: application/json" \
     -d '{"type": "server", "name": "srv3", "fields": {"ram_gb": 64}}' \
     http://localhost:8101/api/entities
```

A token acts as the account that made it, with its role, and is shown once
when it is made; only a hash of it is kept. One made to "only read" is
refused anything but reading. No token can reveal a secret, download the
secrets key or a backup, restore one, or make or revoke tokens; those need
someone signed in. Revoking one takes effect at once, and a restore revokes
them all. Errors are
`{"error": "..."}`, with a sentence meant for a person. A change that did
more than was asked (an address moved from a server to its hypervisor) says
so in `notices`, a list of sentences, beside the record.

| Route | What it does |
| --- | --- |
| `GET /api/entities` | Records, newest change first; filter with `type`, `module`, `tag`, `location`, `slug` (one, or several separated by commas), `q`, and `archived=1` (or `all`) for archived ones; page with `limit` (100 unless given, up to 500) and `offset` |
| `GET /api/entities/<id>` | One record with its fields, custom fields, location path and featured `image` (`null` when it has none) |
| `POST /api/entities` | Make one: `type`, `name`, `status`, `location_id`, `tags`, `notes`, `fields`, `custom`, and `sections` for what other modules add (`{"rack": {...}}`, `{"addresses": {"list": "10.0.20.5"}}`). An admin can also send `created_at` (`2019-05-02T09:30Z`; without an offset, in the instance's time zone) to keep the date a record was first written elsewhere, here or on a change |
| `POST /api/entities/<id>` | Change one; only what the body names changes. A `type` other than its own changes its kind, where the type allows it (a room into a building) |
| `GET /api/entities/by-slug/<slug>` | One record by its slug |
| `POST /api/entities/by-slug/<slug>` | Create the record with that slug, or change it if it exists, so an import can run again without making copies. Creating needs `type` and `name`. The answer says `created` true or false; a slug held by a deleted record is refused until it is restored |
| `POST /api/entities/<id>/archive`, `/delete`, `/restore` | Archive (`{"archived": false}` to undo), delete, restore |
| `GET /api/entities/<id>/history`, `/relationships`, `/dependencies` | Its history, its links, what depends on it (`direction=dependencies` for the other way) |
| `GET /api/catalogs/<key>` | A list of known names a field offers as it is typed in, under group headings: `os`, operating systems |
| `POST /api/relationships`, `POST /api/relationships/<id>/delete` | Link two records (`kind`, `source_id`, `target_id`), unlink |
| `GET /api/tags`, `GET /api/custom-fields` | Tags in use, custom field definitions |
| `GET /api/entities/<id>/attachments`, `POST` the same | A record's files, the featured image aside; upload with multipart `file` parts. An image also has `thumb` and `large` |
| `POST /api/entities/<id>/image` | Its featured image: upload one as a multipart `file` part, or send `{"attachment_id": null}` to remove it. The answer's `undo` brings back the one replaced or removed |
| `POST /api/attachments/<id>/delete`, `/restore` | Remove a file (kept until the purge), bring it back |
| `GET /attachments/<id>` | The file itself |
| `GET /attachments/<id>/thumb/sm`, `/thumb/lg` | An image at most 480 or 1600 pixels on its longest side, as WebP |
| `GET /export/<module>.csv` | A module's records as CSV, with the list's filters |
| `GET /locations/racks/<id>/elevation` | A rack's units and what occupies them |
| `GET /network/subnets/<id>/addresses` | A subnet's recorded addresses and how many are free |
| `GET /network/devices/<id>/ports`, `GET /network/ports/<id>/trace` | A device's ports and cables (a port with no name is where a cable meets a device cabled as a whole); a cable path |
| `GET /network/domains/<id>/records` | A domain's DNS records |
| `GET /software/titles/<id>/installations`, `GET /software/hosts/<id>/installations` | Where a title is installed; what a host has |
| `GET /vault/entities/<id>/secrets` | A record's secrets, without their values, for an account with access |

## Setting up a site

A new install goes from the setup wizard straight into a guide that
documents a site a step at a time; Set up a site, step by step, at the foot
of the New record window (and the empty dashboard), opens it again later. Its first page says what it
covers, in five parts: the place (the site, its buildings and rooms,
racks, and the vendors it deals with), the network (the internet
connection, VLANs, subnets, wireless networks), the equipment (network gear, servers and storage),
what runs (hypervisors, virtual machines, services), and the endpoints, the
UPSes that power them and everything else, and the cables between them.
Steps of turned-off modules are left out. Each step has a What goes here
button beside its title that says what belongs in it, what belongs in
another step, and why: a Usenet provider or an indexer is a vendor, with its
subscription as a contract, while SABnzbd, which you run, is a service. The guide has the screen to
itself, the first time and every time after: no sidebar, search or New menu,
only the steps. The app comes back at the end, or with Exit setup at the top.

The last page counts what each step recorded and offers to start the site's
runbook: a draft document in the knowledge base, attached to the site, that
links to every room, device, subnet and service the guide recorded, with
headings to fill in for who to call, what to check when the internet is
down, what to do when something else breaks, and backups and recovery. Once
it exists, the same button opens it.

Buildings and rooms is a tree of the site: each place shows inside the one
it is in, and its + buttons add a building or a room right there, saved as
Enter is pressed, with the next name typed straight after. A room is in a
building or straight in the site. Dragging a place by its handle onto another puts it inside that one, and
onto the site brings it back to the top; with the handle focused, → puts it
inside the place above it and ← takes it out a level. The × beside a place
deletes it, and a building goes with the rooms in it: the dialog asks first
and says how many, and Undo brings them all back. A place's name is changed
where it is shown, saved on Enter or on leaving it (Escape puts it back),
and its kind beside it: a room that is really a building becomes one,
keeping its links and what is in it, and moves up to the site, where
buildings go. A building made a room keeps its place, and the rooms in it
move out beside it. A room with a rack in it stays a room, and says so,
since a rack can't be in a building.

Every other step is a list of rows, one record a row: what the site has
already, and a blank row at the end. Typing a name in the blank row and
pressing Enter or its Add button adds it (nothing is added until then), and
a new blank row appears for the next, so every endpoint or every service
goes in one after another. In Network gear, Servers and storage, and
Endpoints, the rows are grouped under a heading for each kind (modems,
routers, firewalls, switches and so on, in that order), and a row whose
kind is changed moves to its group. A row once added folds to one line, its name and
what it holds; choosing it opens it again, and moving into another row folds
it back. Any field of a row is changed in place and saved when it is left, a
row's kind too (a router into a firewall); a change that doesn't fit says
why under the row and saves nothing. The × on a row deletes it, asked first
and with Undo. Continue goes on; anything typed in the blank row is added
first, and if it can't be (it has no name), it says why and the step stays.
Back, the steps down the side and Exit setup do the same. On the first step,
the Site choice picks another site, or a new one; the guide can be run again
to add what was left out, or for another site.

Each cable in the Cables step can be moved: choose another From or To in
its row (a free port, or a device with a port to spare) and the cable keeps
its label, color and length. Once the site has a cable, the Cables step
draws the network diagram below its rows, drawn again as each cable is added or deleted. The Cables step's
Suggest cables works the cabling out from the steps before. Each modem goes to the gateway (a firewall, otherwise a router), the
gateway to the core switch (the switch nearest it, by rack, room and
building), and each other switch to the core. A pair of MoCA adapters, or
of wireless bridges, works like one cable: its end nearer the gateway plugs
into a switch, and its far end serves the place it is in, with no cable
between the two. Every other device goes to
a switch that carries its subnet (or the VLAN of it, or of a wireless
network it broadcasts) if any does, otherwise to the switch nearest it, or
to the far end serving its place, and a switch
with its ports recorded gives its free ports in order. Wireless extenders,
patch panels, peripherals and anything with a cable already are left out.
Each suggestion says why and is marked Likely, Check (the switch is
further away, or nothing records where the device is) or Choose a port
(the switch has none free); either end can be changed, and nothing is
added until Add the cables. The ones ticked are added, and any that can't
be are listed with the reason.

A cable added in the Cables step without a label is given one from its
network: the VLAN's number, or with no VLAN the subnet's third number
(192.168.50.0/24 is 50), then a running number, so 20-03 is the third cable
on VLAN 20. The network is the VLAN set on the switch port it plugs into,
if any, otherwise the subnet of the device's address (one the switch
carries, if it has several), with patch panels followed to the device at
the far end. A cable between two pieces of network gear is an uplink,
UP-01, from a modem to the gateway WAN-01, and one whose network isn't
known C-01. Suggest cables fills in each label the same way, to change
before adding, and Label the unlabeled cables, shown while any cable in the
site has none, labels those.

## Records

A record shows all of its sections, Overview first, one after another. The
list of them beside it (above it on a narrow screen) marks the one being
read, and choosing one scrolls there. Settings > Appearance can show one
section at a time instead, for each account: then choosing a section shows
that one alone.

A record's Relationships tab ends with its dependency view: what breaks if
it goes down, and what it needs, followed through the links that carry a
dependency (runs on, hosted by, depends on, installed on, powered by) and
through the cables. A device cabled to network gear (a switch, router,
firewall, modem or MoCA adapter) needs it, through any patch panels on the
way; between two pieces of gear, the one further from where the internet
comes in needs the nearer one (an edge switch the core, the core the
firewall), and at the same distance neither needs the other. The far end
of a MoCA or wireless bridge pair needs the near end. A UPS or a peripheral
cabled to the network is managed over it and goes on working without it,
so its cable makes it need nothing. None of this is stored: it follows the
cables as they are, and a link that says the same is shown once. The tab
lists the devices a device is cabled to under Cabled to, read-only, with the
ports, any patch panels and the cable labels; the cable is changed in the
Cabling tab. The form for a new link opens from Add link. It
opens as a drawing, and List and Diagram switch between that and two nested
lists. In the drawing, the record sits in the middle, what it needs above
it and what breaks below it, a row for each step further away. A dashed
line through the record divides the two, What it needs named just above it
and What breaks if this goes down just below; the names keep their size and
stay in sight however far the drawing is zoomed or scrolled, at the edge
the line went out by once it is out of view. A record
reached two ways is one box with two lines into it, and a loop is a dashed
line. Any box opens its record. A record with more hanging from it has a −
on the edge its branch leaves from (below it under the record, above it over
it): choosing it, or Enter on it, folds the branch away and draws the rest
again closer together, with a +N in its place saying how many records it
hides, and choosing that shows them again. Collapse all, beside the zoom
buttons, folds everything past the records next to this one, and Expand all
opens it all again. The folds last while the record is open, through edits
to it, and it opens unfolded next time. The choice is remembered in the browser.

Every diagram (this one, the Neighborhood tab and the network diagram)
opens with all of it showing. −, Fit and + above it zoom it, as does
Ctrl or ⌘ with the scroll wheel, or a trackpad's pinch; zoomed in, drag it
with the mouse to move around.

An editor edits a record where it is shown. In its Overview each field reads
as its value until it is pointed at or clicked, when it becomes a field to
type in or a list to choose from; the name is edited in the title. A change
is saved when the cursor leaves the field, on Enter, or when the record is
closed or another one opened, and the list behind it follows. A change that
can't be saved (a required field left empty, a number out of range) says why
under the field and keeps what was typed; closing the record then keeps it
open once, and closing it again discards the change. Notes and other long
text show formatted, with an Edit button that opens them as Markdown. `e`
puts the cursor in the first field.

New records are made in the New record window, from New at the top of the
page or the `n` key. It starts with what kind of record: type to search
(by name, plural or module, and by the kinds a type comes in, so "switch"
finds a network device with Switch chosen and "dns" a DNS service), or
choose from the list, grouped by module; the arrow keys and Enter pick
too. The form follows a step at a time down the rail: Basics (the name,
status, location and tags, and the type's own main fields), then each
group of fields, custom fields, each section other modules add (Rack
position, IP addresses) and Notes. Next and Enter go on, Back and the rail
go anywhere, and Create saves from any step; a required field left empty
brings its step back with the reason. A choice that rules a section out
(a tower has no rack position) takes its step away. Going back to the kind
and choosing another keeps what was typed. A New button on a record (a VLAN
on its network, a contract on its vendor) opens the window at Basics, the
kind and the link to that record already settled.

Deleting a record, a link or a file can be undone from the message that
follows. A deleted record then waits under Recently deleted, where it can
still be restored, and is purged for good after the number of days set in
Settings > Admin (30 by default). Archiving a record instead keeps it out of
lists and search with its history and links, until it is unarchived.

Attachments are limited in size per file in Settings > Admin (25 MB by
default). Images, PDFs and plain text open in the browser; everything else
downloads.

A record can have a featured image, with a place of its own at the top of
its Overview: an editor drops an image there, or chooses one, and replaces
or removes it with the buttons on it (both can be undone). It also heads the
record's card in card view. It is not one of the record's attachments. The
record's attached images (PNG, JPEG, GIF and WebP) show below it as a strip;
any picture opens the viewer, where the arrow keys, the side buttons or a
swipe move through them and a button opens the original. Cards and the
Overview show smaller copies, made the first time each is shown, turned the
way the camera was held and without the photo's metadata (its location
included). They are kept in `DATA_DIR/thumbs` and are not in backups, as
they can always be made again.

## Secrets

Passwords, API keys, SSH keys and license keys are kept in the Secrets tab
of the record they belong to. Admins see and change them always, as they can
do everything. Viewers and editors see them only when an admin gives them
access, with the key button beside each user in Settings > Admin. Seeing
needs only that access; adding, changing and removing also need the editor
role.

A secret's value is hidden until Show, which hides it again after 30
seconds, and Copy puts it on the clipboard without showing it. Each Show and
each Copy is a line in the record's History ("revealed a secret"), and
Settings > Secrets lists the latest. Those lines, like the tab, are hidden
from people without access. Values are never searched, exported or given to
an API token.

**The key.** Values are encrypted in the database with a key that is not in
it. It comes from `SECRETS_KEY`, or else from `secrets.key` in the volume,
made the first time a secret is saved. **Keep a copy of the key somewhere
other than this server and its backups. Without it nobody can read the
secrets, and there is no way to recover them: losing the key loses the
secrets.** Backups leave the key out on purpose, so a backup that goes astray
is no use without it. Settings > Secrets downloads the key to keep a copy,
and puts one back after a restore on a new server; each download is noted
there. To move to `SECRETS_KEY`, put the key in it; `flask secrets status`
says where the key in use is and whether it opens every secret.

## Turnstile

[Cloudflare Turnstile](https://www.cloudflare.com/products/turnstile/) puts a
challenge on the sign-in and sign-up pages, which stops most automated
password guessing and sign-up spam. It is off until an admin turns it on.

1. In the [Cloudflare dashboard](https://dash.cloudflare.com/?to=/:account/turnstile),
   add a widget and list the hostname the app is reached on (for example
   `app.example.com`, or the server's address on a LAN).
2. In the app, open Settings > Security, paste the site key and the secret key,
   and press **Verify and turn on**.
3. Complete the challenge that appears. The keys are saved only if Cloudflare
   accepts the answer, which proves they belong together and work on this
   hostname, so a wrong key can't lock anyone out.

To change keys, do the same again; leave the secret empty to keep the saved
one. **Turn off** removes the challenge at once and keeps the keys. The secret
is stored in the database and never sent to the browser.

If sign-in becomes impossible anyway (the widget's hostname list was changed,
or Cloudflare is unreachable), turn it off from the server:

```sh
docker exec hyprvolt flask turnstile off
```

The `TURNSTILE_*` variables still work, as a fresh-install default: with both
set and nothing saved in the app, Turnstile is on with those keys. Turning it
off in Settings overrides them.

For testing, Cloudflare publishes
[dummy keys](https://developers.cloudflare.com/turnstile/troubleshooting/testing/)
that always pass: site key `1x00000000000000000000AA`, secret
`1x0000000000000000000000000000000AA`.

## Channels

`latest`, the default, follows stable releases. `IMAGE_TAG=beta` follows the
betas: previews of the next release, such as `1.4.0-beta.2`, published while
it is refined. Betas can break things; back up first. `IMAGE_TAG=1.3.0` pins
one version, and `IMAGE_TAG=1.3` takes that line's patches only. Switching
back from `beta` to `latest` works as long as the beta did not run a
migration the stable can't read, which the changelog says.

## Behind a reverse proxy

Behind Cloudflare Tunnel, Caddy, Traefik or nginx, set `TRUST_PROXY` to the
number of proxies in front, usually `1`. The app then takes the client's
address and the scheme from the `X-Forwarded-*` headers, which the sign-in
throttle and redirects need. Setting it higher than the real number lets a
client forge its address. With HTTPS at the proxy, also set
`SESSION_COOKIE_SECURE=1`.

## Updating

```sh
docker compose pull && docker compose up -d
```

Migrations run by themselves at startup. A MAJOR version (`2.0.0`) means an
existing install needs something done by hand; the changelog says what.

## Backups

Everything is done in Settings > Backups, by an admin; no terminal needed.

- **Make a backup now** saves one archive with every record, account,
  setting and attached file. The database is copied with SQLite's online
  backup API, so it is consistent while people keep working.
- **Automatic backups** are made by the background worker every 24 hours,
  and the newest 7 are kept; both numbers are set there, and 0 hours turns
  them off. The ones made by hand stay until deleted. Deleting one can be
  undone.
- **Download** a backup to keep it somewhere else. Backups live in the data
  volume's `backups` folder unless `BACKUP_DIR` points at another disk, so
  on their own they don't survive losing the disk the data is on.
- **Restore…** shows what a backup holds (when it was made, by which
  version, how many records, accounts and files, which admins) and what
  restoring will do. **Restore this backup** then replaces everything with
  it. What was there before is saved as a backup first, so restoring that
  one undoes it. Everyone is signed out, except the admin who restored, if
  their account is an admin in the backup too.
- **Restore from a file** uploads a backup downloaded earlier, from this
  instance or another. It is checked first: an archive that isn't a Hyprvolt
  backup, is damaged, has no admin, or was made by a newer version is
  refused, and nothing is replaced.

**Moving to a new server:** install there, sign in with the account the
setup wizard makes, upload the backup in Settings > Backups and restore it,
then sign in with an admin account from the backup. If there are secrets,
put their key back in Settings > Secrets (below).

**The secrets key is never in a backup**, on purpose: a backup that goes
astray is no use without it. Download it once from Settings > Secrets and
keep it apart from the backups. After restoring on a new server, **Put a key
back** there; it is checked against the secrets before it is used.

From the server, `flask backup PATH` writes the same archive (`.db` for the
database alone) and `flask restore PATH` restores one, for scripts or for
when the app can't be reached.

## Commands

Run inside the container:

| Command | What it does |
| --- | --- |
| `flask create-user EMAIL [--role viewer\|editor\|admin] [--admin] [--secrets] [--name NAME]` | Create an account; asks for the password. `--admin` is `--role admin`; `--secrets` gives it access to secrets |
| `flask reset-password EMAIL` | Set a new password; the way back in for a locked-out admin |
| `flask backup PATH` | Write a consistent copy: `.tar.gz` for the database and attachments, `.db` for the database alone. Settings > Backups does this in the app |
| `flask restore PATH` | Replace the instance with a backup archive, saving what is there first. Settings > Backups does this in the app |
| `flask seed-demo [--force]` | Fill an empty instance with a small demo homelab |
| `flask turnstile status`, `flask turnstile off` | Show whether Turnstile is on; turn it off when nobody can sign in |
| `flask secrets status` | Say where the secrets key is and whether it opens every secret |
| `flask secrets new-key` | Print a new key for `SECRETS_KEY` |
| `flask export PATH` | Write the whole instance as JSON, as Settings > Admin does |

```sh
docker exec -it hyprvolt flask reset-password you@example.com
```

## Health

`GET /healthz` answers `{"ok": true, "version": "..."}` once the app can reach
its database, without signing in. The image's `HEALTHCHECK` uses it, so
`docker ps` shows the container as healthy or not.

## Keyboard

| Key | Where | What it does |
| --- | --- | --- |
| Ctrl K, ⌘K or `/` | anywhere | Search |
| `n` | a page | New record: the window that searches every kind of record, then walks through its form |
| `j`, `k` | a record | Next, previous in the list |
| Back, Forward (the browser's, or ‹ › in the record's bar) | a record | The records opened one from another: a link, a page's Next, `j` and `k`. Back from the first one closes it |
| `1` to `9`, ↑ ↓ (← → on a narrow screen) | a record | Scroll to its sections |
| `e`, `a`, `c` | a record | Edit (the cursor in its first field), archive or unarchive, copy its link |
| `?` | a page | Help: how records, links and cables connect, and what follows from them |
| Esc | a dialog | Close it |

## Troubleshooting

**"Your session expired. Reload the page and try again."** The CSRF token no
longer matches, usually because the secret key changed (a new `SECRET_KEY`, or
a lost volume) or the session cookie was cleared. Reload.

**Signed out on every restart.** `SECRET_KEY` is unset and the volume is not
persistent, so a new key is generated each time. Keep the volume, or set
`SECRET_KEY`.

**"Too many attempts."** Eight failed sign-ins for one account from one
address lock that pair out for fifteen minutes. Restarting the container
clears it. Behind a proxy without `TRUST_PROXY`, every client shares the
proxy's address.

**The challenge on the sign-in page fails for everyone.** The Turnstile
widget no longer lists the hostname the app is reached on. Run
`docker exec hyprvolt flask turnstile off`, fix the hostname list in the
Cloudflare dashboard, then turn it back on in Settings > Security.

**The container stays unhealthy.** `docker compose logs` shows why. The usual
cause is a volume the container user (uid 1000) can't write to.
