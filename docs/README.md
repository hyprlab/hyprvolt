# Documentation

The README is the front door. Everything else lives here, and every file in
this directory is listed below; `tools/check-docs.py` fails if one is not.

| File | What is in it |
| --- | --- |
| [DOCUMENTATION.md](DOCUMENTATION.md) | Installing, configuration, reverse proxies, backups, commands, troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the pieces fit together, and why they are the way they are |
| [DESIGN.md](DESIGN.md) | The design system: tokens, components, and the interface rules |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Commits, prose style, code, credit, issue replies |
| [RELEASING.md](RELEASING.md) | SemVer, the beta and stable channels, and the ship procedure |
| [SECURITY.md](SECURITY.md) | What the app defends against, and how to report a problem |
| [CREDITS.md](CREDITS.md) | Who contributed what |

## Where a new piece of documentation goes

| What you have | Where it goes |
| --- | --- |
| A feature worth pitching | The README's feature list, only if it displaces a bullet already there |
| How to set something up or run it | [DOCUMENTATION.md](DOCUMENTATION.md) |
| A design decision and its reasoning | [ARCHITECTURE.md](ARCHITECTURE.md) |
| A new component, token or interface rule | [DESIGN.md](DESIGN.md) |
| A convention for anyone editing the repository | [CONTRIBUTING.md](CONTRIBUTING.md) |
| A change to how releases are made | [RELEASING.md](RELEASING.md) |
| Credit for somebody's work | `data/CONTRIBUTORS` for the name, [CREDITS.md](CREDITS.md) for the work |
| What changed in a release | [CHANGELOG.md](../CHANGELOG.md) |
| Artwork for the README or the docs | `data/repo/`, never `docs/`, which holds Markdown only |

A new `docs/*.md` must be added to the first table and linked from somewhere
it will be found.
