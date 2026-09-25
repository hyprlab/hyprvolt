# Changelog

All notable changes to Hyprvolt are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## Unreleased

### Added
- Records of every kind share one interface: cards or a list with filters and live counts in the sidebar, a detail sheet with Overview, Relationships, Documents, Attachments and History tabs, and one form
- Locations: sites, buildings, rooms, racks and shelves, with breadcrumbs on everything that has a place
- Rack elevations show what occupies each unit on the front and rear, and flag overlaps and anything that no longer fits; a sidebar filter lists the racks with conflicts
- A knowledge base of Markdown documents that attach to any record and link to records with [[slug]]
- Typed links between records in both directions, and a view of what breaks if a record goes down
- Files attached to any record, included in `flask backup` when the backup is named `.tar.gz`
- Tags shared by every module, custom fields an admin adds to any kind of record, and a history of every change
- `flask seed-demo`, or Load a demo homelab on an empty dashboard, fills a new instance with a small homelab to try the app on
- Settings has a Modules section to turn modules on and off (a module that is off keeps its records) and a Custom fields section
- Deleting a record can be undone, and deleted records stay under Recently deleted until they are purged
- The dashboard counts what is documented, shows what changed lately, and how full each rack is
- Accounts have a role: viewers read everything, editors also change the documentation, admins also manage users and the instance. Admins pick the role per user and the role new accounts start with

### Changed
- Documentation belongs to the instance rather than to the account that wrote it; deleting an account keeps it
- Sign-up is off on a fresh install

## [0.1.0] — 2026-09-25

### Added
- The first version, started from the Hyprlab Flask template
