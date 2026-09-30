# Changelog

All notable changes to Hyprvolt are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## Unreleased

### Added
- An internet connection records the modem, router or firewall it comes in at, from either record or from the setup guide's Network gear step. The device lists the line it brings in, the line depends on the device, and the network diagram draws the line above it. The Network gear step's help explains that a modem in bridge mode has no address on your network
- An internet connection has a Dynamic or Static choice for its IP address, side by side with the chosen one raised. Static shows the line's static IP, subnet mask, gateway and DNS servers, in its record and in the setup guide; Dynamic hides them. A connection that already had public addresses is marked Static
- In the site setup guide, Buildings and rooms is a tree of the site: add a building or room right where it goes, saved as you type each name, and drag one onto another (or use the arrow keys on its handle) to move it a level. Deleting a building there takes the rooms in it too, after asking, and Undo brings them all back
- The setup wizard and the site setup guide have a light and dark button, and new installs and new accounts start in the dark theme
- Each step of the site setup guide has a What goes here button that explains what belongs in it, what belongs in another step, and why, such as a Usenet provider being a vendor with a contract while SABnzbd is a service
- The site setup guide's last page offers to start the site's runbook: a draft knowledge base document, attached to the site, that links to everything the guide recorded and has headings to fill in for who to call, what to check first and how to recover
- A guide that documents a site step by step, from the site out to the endpoints: its rooms, racks, vendors, internet connection, VLANs, subnets, network gear, servers, hypervisors, virtual machines, services, endpoints and the cables between them. Each step lists what is recorded as rows that are changed in place and deleted with a ×, each change saved as it is made, and a blank row at the end adds the next one when a name is typed and Enter is pressed, or when moving on with something typed in it, so all the endpoints or all the services go in one after another. A new install goes into it straight after creating the admin account, starting with a page that says what it covers. It has the screen to itself, with no sidebar, search or New menu, until it is done or Exit setup is chosen; later it opens from New > Set up a site, step by step, and from the empty dashboard
- A device can be cabled to another without recording its ports: in its Cabling tab (Ports before), Connect a cable offers other devices as a whole, and the ports of devices that have them recorded. Record each port, a switch at the top of the Cabling tab, turns on ports to name and cable one by one, as before. A device that already has ports keeps them recorded
- An admin can change the order of the sidebar in Settings > Modules: drag its groups, and the modules within each group, by their handles, or move them with the arrow keys. Put the default order back undoes it
- A setting in Settings > Appearance to show a record one section at a time, as before, instead of all its sections on one page
- A beta channel: `IMAGE_TAG=beta` runs previews of the next release, numbered like `1.4.0-beta.1`, while `latest` stays on stable
- The dependency view in a record's Relationships tab can be shown as a diagram: what it needs above the record, what breaks if it goes down below it, a row for each step away. It opens as the diagram; List and Diagram switch between the two, and the choice is remembered in the browser
- Diagrams open with all of them showing and can be zoomed, with −, Fit and + or with Ctrl or ⌘ and the scroll wheel (a trackpad's pinch), and dragged around when zoomed in: the dependency diagram, the Neighborhood tab and the network diagram

### Changed
- In the dark theme, messages such as Deleted with Undo are a dark pill with light text, and errors a dark red one, instead of a light pill the yellow Undo was hard to read on
- Once a subnet's range is typed, its gateway is filled in with the first address and its DHCP range with the upper half of the subnet, unless they were typed by hand
- A subnet's range is typed as its network address with the subnet mask chosen beside it (/24 · 255.255.255.0 · 254 hosts), and its DHCP range as a first and a last address in two boxes, in its record and in the setup guide
- The chosen option of a segmented control (Dynamic or Static, a theme, a user's role, List or Diagram) is shown in the yellow accent
- An internet connection's Bandwidth is now a Download and an Upload speed, each a number with Mb/s or Gb/s chosen beside it. Bandwidth already typed is read into them, and text that can't be read is kept at the end of the connection's notes
- Phone numbers are kept as typed and no longer checked, so a vanity number such as 1-833-VERIZON or a note saves. One that can be dialed is still a link, its letters dialed as their keypad digits
- A new app icon: the server unit now shades from light to dark, and the bolt from yellow to orange. It is the mark on every page, the browser tab's icon and the icon a phone's home screen shows
- A record shows all of its sections (Overview, Relationships, History and the rest) one after another instead of one tab at a time. A list of them down its left side marks the one being read as it scrolls, and choosing one scrolls there smoothly. Back, Forward and the record's actions sit above the list, and the close button on its own at the top right. The record is wider by as much as the list, so its content has the same room as before. On a screen 900 pixels wide or less the list is a row under the header that stays in view while the record scrolls, and ↑ and ↓ move through the list where ← and → moved along the tabs
- The New button offers every kind of record from every enabled module, on every page, in the sidebar's order. It used to offer only the kinds of the module being viewed
- An internet connection's ISP is a vendor, chosen in the Supplier section of the network's form with the contract for the line, so the ISP's support number and account number are a click away and the vendor's Supplies tab lists the connection. The Provider text field is gone: what was typed in it is kept at the end of the network's notes. Internet connections have a Circuit ID field instead, and the Network sidebar lists them
- A tower server has no Rack position section in its form or Overview
- Deleting a record asks first, in a dialog, and then offers Undo as before
- Removing a link between two records asks first, in a dialog, and so do detaching a document and taking a record off a maintenance window or change. Undo still follows

## [1.3.0] — 2026-09-28

### Added
- A location, a piece of hardware, or a VM or LXC container can be changed into another kind after it is saved, under Type in its Overview: a room into a building, a server into a NAS, a VM into an LXC container. It keeps its links, files and history
- Pictures on records: a featured image in a place of its own at the top of a record's Overview, added, replaced or removed there, and shown on the record's card in card view. The record's attached images show below it as a strip, and any picture opens a viewer that moves through them with the arrow keys or a swipe

### Changed
- In the light theme, the chosen row in the sidebar, settings and search is a darker grey instead of yellow, keeping its yellow edge
- The dark theme is lighter: charcoal backgrounds instead of near-black, with brighter borders and secondary text, so it is easier to read
- A record is edited where it is shown, instead of in a form: in its Overview, an editor changes a field in place, and it is saved on leaving the field, on Enter, or on closing the record. A change that can't be saved says why under the field and keeps the record open until it is fixed or closed again. Notes and other long text show formatted until their Edit button. New records are still made in the form
- The dependency view in the Relationships tab marks each record with what it is: a virtual machine, a server, a service and so on. The API's dependency tree gives it as `type_label`
- Deleting a record opened from another record goes back to that record, with Undo in the toast

### Fixed
- The Deleted toast, with its Undo, shows after deleting a record; it closed along with the record

## [1.2.0] — 2026-09-28

### Added
- Headings in documents get anchors, and a page with three or more headings opens with a contents list linking to them
- A fenced code block that names its language (bash, PowerShell, Python and the rest) is colored for it, with the language named above the block
- Task lists: `- [ ]` and `- [x]` items show as checkboxes
- An admin can set when a record was created, through the API, to keep the date a document was first written elsewhere; a record's header shows it
- A document can be a page of another, in an order: the parent lists its pages, and each page shows its path and links to the pages before and after it. A sidebar filter shows the top-level pages only
- A document's Linked from tab lists the documents that link to it
- Search finds a record by the words in its attached text files and PDFs, and by their names
- A document can be restricted to editors and admins, or to admins and the people with access to secrets; everyone else never sees it, in lists, search, links, exports or the API
- The API finds a record by its slug (`GET /api/entities/by-slug/<slug>`, or `?slug=` on the list) and creates or updates one by slug (`POST /api/entities/by-slug/<slug>`), so an import can run again without making copies

### Changed
- Back and Forward work in a record: following a link to another record, a page's Next, or j and k adds a step that the browser's Back and Forward, and the ‹ › buttons in the record's bar, walk through. Back from the first record closes it, and closing it leaves the browser's history as it was
- A record's notes come first in its Overview, above its fields
- A record's close button is on the right of its bar, with Back, Forward and its actions on the left
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
