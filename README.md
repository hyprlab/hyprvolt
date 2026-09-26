<p align="center">
  <img src="hyprvolt/static/img/logo.svg" width="72" alt="Hyprvolt logo">
</p>

<h1 align="center">Hyprvolt</h1>

<p align="center"><strong>IT documentation for on-premise infrastructure.</strong></p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
</p>

Hyprvolt documents what an on-premise business, organization or homelab
runs: where each box is, what sits in which rack unit, when its warranty
ends, which IP is free on which VLAN, how things depend on each other, and
the runbooks that explain them.
It is a self-hosted web app that runs in one Docker container with its data
in a single SQLite volume.

## Features

- Sites, buildings, rooms, racks and shelves, with breadcrumbs on everything
- Servers, network gear, UPSes, storage and desks, with serials, asset tags, warranties, specs and a lifecycle
- Hypervisors, VMs, LXC and Docker containers and compose stacks, and what each runs on
- VLANs, subnets with a map of used and free addresses, ports and cables traced end to end, and DNS records
- Services and what they run on, software installations and license seats, vendors, people and contracts
- Rack elevations, front and rear, that flag overlaps and anything that no longer fits
- A Markdown knowledge base whose documents attach to records and link to them with `[[slug]]`
- Typed links between any two records, and a view of what breaks if one goes down
- Attachments, tags, custom fields and a full history on every record
- A secrets vault: passwords and keys on any record, encrypted with a key kept out of the database, each reveal recorded
- Delete with Undo, archive, and search across everything with Ctrl K
- CSV export of any list, CSV import with column matching and a check first, and a JSON export of everything
- Viewer, editor and admin roles; the documentation belongs to the instance
- A JSON API for scripts, with per-user tokens that can be limited to reading
- A module system, so new kinds of records arrive without changes to the core
- A demo homelab to try it on, and backups made, scheduled, downloaded and restored from Settings

## Install with Docker Compose

```sh
curl -O https://raw.githubusercontent.com/hyprlab/hyprvolt/main/docker-compose.yml
docker compose up -d
```

Then open http://localhost:8101. The first visit opens the setup wizard.
Configuration is covered in [docs/DOCUMENTATION.md](docs/DOCUMENTATION.md).

## Documentation

| | |
| --- | --- |
| [Documentation](docs/DOCUMENTATION.md) | Configuration, deployment, backups |
| [Architecture](docs/ARCHITECTURE.md) | How the pieces fit, and why |
| [Modules](docs/MODULES.md) | Writing a module |
| [Contributing](docs/CONTRIBUTING.md) | Commits, prose style, tests |
| [Releasing](docs/RELEASING.md) | Versions, the beta and stable channels |
| [Changelog](CHANGELOG.md) | What changed in each release |

## AI notice

Hyprvolt is built by a human maintainer who uses generative AI as a development
tool. The maintainer decides what gets built, reviews the results, tests every
release and signs off on everything that ships. Commits are made under the
maintainer's name; the tool is declared here once, for the whole repository,
instead of in a trailer on every commit. The app itself contains no AI and
makes no requests to AI services.

## License

Hyprvolt is free software, released under the [MIT License](LICENSE).

© 2026 Hyprlab
