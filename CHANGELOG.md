# Changelog

All notable changes to Hyprvolt are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## Unreleased

### Added
- Headings in documents get anchors, and a page with three or more headings opens with a contents list linking to them
- Code blocks are colored for their language (```bash, ```powershell, ```python and the rest), with the language named above the block
- Task lists: `- [ ]` and `- [x]` items show as checkboxes
- An admin can set when a record was created, through the API, to keep the date a document was first written elsewhere; a record's header shows it
- A document can be a page of another, in an order: the parent lists its pages, and each page shows its path and links to the pages before and after it. A sidebar filter shows the top-level pages only
- A document's Linked from tab lists the documents that link to it
- The API finds a record by its slug (`GET /api/entities/by-slug/<slug>`, or `?slug=` on the list) and creates or updates one by slug (`POST /api/entities/by-slug/<slug>`), so an import can run again without making copies

### Changed
- A document's headings keep their levels: # and ## are no longer shown the same size as ###
- Table cells keep their colspan and rowspan
- There is no beta channel: every release goes to `latest`, and `IMAGE_TAG` takes `latest` or a version to pin

## [1.1.0] — 2026-09-28

### Changed
- Windows such as the record form and Settings, and a record's sheet, no longer close on a click beside them; they close with their close button or Escape, so a form half filled in isn't lost
- A record's sheet slides back down when it closes, the way it came in
- Every field in the record form has an info button beside its label that says what the field is for, tags, slug and codes included, instead of hints under some of them
- A site's address is a field each: street, city, state or region, postal code and country. An address written before is kept in Street address

## [1.0.0] — 2026-09-28

### Added
- Records of every kind share one interface: cards or a list with filters and live counts in the sidebar, a detail sheet with Overview, Relationships, Documents, Attachments and History tabs, and one form
- Locations: sites, buildings, rooms, racks and shelves, with breadcrumbs on everything that has a place
- Rack elevations show what occupies each unit on the front and rear, and flag overlaps and anything that no longer fits; a sidebar filter lists the racks with conflicts
- The form of anything that goes in a rack has its rack position: the rack, the lowest unit, the height and the face
- Hardware: servers, network gear, firewalls, access points, UPSes, NAS, workstations, printers and peripherals, with make, model, serial, asset tag, purchase, warranty, specs and a lifecycle status from ordered to disposed
- Sidebar filters list hardware whose warranty ends soon or is over
- A module that needs another is off while that one is, and Settings > Modules says why
- Virtual: clusters, hypervisors, virtual machines, LXC containers, Docker hosts, compose stacks and containers, with resources, operating system, and what each runs on
- What something runs on, chosen in its form, is also a link, so the dependency view reaches from a server down to the containers on it
- A hypervisor's Guests tab, and a cluster's, weigh the vCPUs and memory given to running guests against the hardware; the dashboard shows each hypervisor's memory
- Buttons in a hypervisor's or Docker host's tabs open the form for a new VM, container or stack with its host filled in
- Network: networks, VLANs, subnets, IP addresses and domains
- A device's or a VM's IP addresses are typed into its own form, and each becomes an IP address record in its subnet
- A subnet's Addresses tab shows every address as used, reserved, held for DHCP or free, and a free one can be recorded from there
- Devices have ports, set with their speed, PoE and VLANs, cabled to other devices' ports; a cable path is traced through patch panels to the far end
- Domains hold DNS records written down by hand, linked to the devices their addresses belong to; the palette finds DNS names and MAC addresses
- Sidebar filters list IP addresses with no device and domains due for renewal, and a dashboard card shows how full each subnet is
- Services: what people use, with its address, ports, users, importance, what it runs on and its domain; the dependency view of a server or a domain lists the services that go with it
- A dashboard card lists the services marked high or critical and any that are degraded or down
- Software: titles and where each is installed, at which version; installations behind the current version are marked
- Licenses count the seats in use against the seats owned, and sidebar filters list licenses over their seats or due for renewal
- Contacts and vendors: vendors with support and account numbers, the people there, and contracts with their term, notice period and cost
- Hardware, software, services, networks and domains name their supplier and the contract that covers them in their form
- Phone numbers and email addresses are links
- Certificates: TLS certificates with the names they cover, issuer, dates, key and fingerprint, and the services they secure; the dependency view of a certificate lists what breaks when it expires
- A certificate's Check tab reads it from PEM text, or from the server that serves it; given an address, the app checks it once a day and takes in a renewed certificate by itself
- Certificates are reminded of before they expire; one that renews by itself only once its renewal is plainly late. Sidebar filters list certificates expiring soon and those whose check failed
- Backup jobs: what each backs up, where it saves to, its schedule, retention and restore tests, and a status that follows its runs, from Succeeding to Failing or Overdue
- Backup scripts report each run with an API token, and the Runs tab shows the command to use; runs can be recorded by hand too
- What a job backs up has a Backups tab, and a dashboard card lists the backup jobs failing or overdue
- Maintenance windows: start and end, expected impact, who does it, whether users were told, and a plan; the Impact tab lists what a window affects and everything that goes down with it
- A change log: changes with when, what kind, who, what and why, and the window they were part of. Every record has a Changes tab with its changes and maintenance, and buttons to record a change or plan maintenance for it
- A dashboard card lists the maintenance of the next 30 days, marking what is under way, and the changes of the past week; sidebar filters list maintenance coming up and under way, recent changes, and changes that failed or were rolled back
- A network diagram draws every cabled device and the cables between them, traced through patch panels, from the internet side down; hovering a link shows its ports and VLANs
- Every record with links or cables has a Neighborhood tab drawing what it is linked to and what is linked to it
- Print labels, in any list's export menu, prints a label for each record listed: a QR code that opens it, its name, kind, asset tag or serial, and where it is. Avery 5160 and L7160 sheets and 62 × 29 mm label printer labels
- Settings > Admin sets the instance's time zone, in which times are typed and shown; it starts as the `TZ` environment variable, or UTC
- A secrets vault: passwords, API keys, SSH keys and license keys in a Secrets tab on any record, encrypted with a key kept outside the database, shown or copied on request, each time written to the history
- Admins always see secrets; viewers and editors see them when an admin gives them access in Settings > Admin. Settings > Secrets says where the key is and who revealed what lately
- `flask secrets status` and `flask secrets new-key`; `flask create-user --secrets`
- The dashboard's Coming up card lists the soonest warranties, license renewals, contract ends, domain renewals and UPS battery dates near their date, with a link to all of them, and the sidebar counts them
- Settings > Admin sets how many days ahead and behind reminders reach, 90 by default; the sidebar filters for things ending soon follow it
- Any list exports as CSV, as it is filtered and searched
- Editors import records from a CSV file: match the columns to fields, check what the import will do without saving anything, then import; rows with a problem are left out and said why
- Settings > Admin and `flask export` export the whole instance as JSON, without password hashes, secret values or token hashes
- Settings > Backups: make a backup, have one made every day (the newest seven kept), download, delete with Undo, upload one, see what it holds, and restore it; what was there is saved first, so a restore can be undone
- Settings > Secrets downloads the secrets key to keep apart from the backups, and puts one back after moving to a new server
- `flask restore`, and `BACKUP_DIR` to keep backups on another disk
- Changing a password signs the account out everywhere else
- API tokens: each account makes its own in Settings > API tokens, to use the JSON API from scripts; a token can be limited to reading, never reveals a secret, and is revoked at once
- A knowledge base of Markdown documents that attach to any record and link to records with [[slug]]
- Typed links between records in both directions, and a view of what breaks if a record goes down
- Files attached to any record, included in every backup
- Tags shared by every module, custom fields an admin adds to any kind of record, and a history of every change
- `flask seed-demo`, or Load a demo homelab on an empty dashboard, fills a new instance with a small homelab to try the app on
- Settings has a Modules section to turn modules on and off (a module that is off keeps its records) and a Custom fields section
- Deleting a record can be undone, and deleted records stay under Recently deleted until they are purged
- The dashboard counts what is documented, shows what changed lately, and how full each rack is
- Accounts have a role: viewers read everything, editors also change the documentation, admins also manage users and the instance. Admins pick the role per user and the role new accounts start with

### Changed
- Hyprvolt is released under the MIT License
- Secondary text and the red of errors and alerts have more contrast, meeting WCAG AA in both themes, and links and small buttons are easier to tap on a touch screen
- The app icon is Hyprvolt's own, in the sidebar, on the sign-in page and as the browser tab's icon
- Documentation belongs to the instance rather than to the account that wrote it; deleting an account keeps it
- Sign-up is off on a fresh install

## [0.1.0] — 2026-09-25

### Added
- The first version, started from the Hyprlab Flask template
