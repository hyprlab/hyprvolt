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
creates the admin account. There is no default account or password. On an
empty instance the dashboard offers to load a demo homelab to look around in;
`flask seed-demo` does the same from the server.

From a clone of the repository, `docker compose up -d --build` builds the
image from source instead: `docker-compose.override.yml` is picked up
automatically.

## Configuration

Everything is optional. Put values in a `.env` file next to
`docker-compose.yml` (`.env.example` lists them all), then
`docker compose up -d` to apply.

| Variable | Default | What it does |
| --- | --- | --- |
| `IMAGE_TAG` | `latest` | The image to run: `latest` for stable, `beta`, or a version to pin |
| `APP_NAME` | `Hyprvolt` | What the app calls itself |
| `APP_TAGLINE` | `IT documentation for on-premise infrastructure.` | The line under the name on the sign-in page and in About |
| `SECRET_KEY` | generated | Signs sessions. If unset, one is generated and kept in the volume |
| `SESSION_COOKIE_SECURE` | `0` | Set to `1` when the app is served over HTTPS |
| `TRUST_PROXY` | `0` | How many reverse proxies are in front; see below |
| `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` | empty | Cloudflare Turnstile keys; see [Turnstile](#turnstile). Usually set in the app instead |
| `ALLOW_REGISTRATION` | `0` | Whether anyone can create an account. New accounts get the default role (viewer unless an admin changes it) |
| `WORKER_MINUTES` | `15` | How often background work runs; `0` turns it off |
| `ITEMS_PER_PAGE` | `40` | Records per page |
| `DATA_DIR` | `/data` | Where the database and attachments live inside the container |
| `MODULES_STRICT` | `0` | Stop at startup when a module's manifest is broken, instead of leaving the module out |

`ALLOW_REGISTRATION`, `WORKER_MINUTES`, `ITEMS_PER_PAGE` and the Turnstile
keys are only defaults for a fresh install. Once they are changed in Settings
(under Admin or Security), what is saved there wins.

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

## Modules and custom fields

What Hyprvolt documents comes in modules: Locations and the knowledge base
so far. Settings > Modules turns a module off; it then disappears from the
sidebar, search and the dashboard, and its records stay in the database until
it is turned back on. The knowledge base is built in.

Settings > Custom fields adds fields of your own to any kind of record: text,
a number, a date, a choice list, a web address, or yes or no. They appear in
the record's form and Overview, and search finds their values. Removing one
removes its values too, with Undo.

## Records

Deleting a record, a link or a file can be undone from the message that
follows. A deleted record then waits under Recently deleted, where it can
still be restored, and is purged for good after the number of days set in
Settings > Admin (30 by default). Archiving a record instead keeps it out of
lists and search with its history and links, until it is unarchived.

Attachments are limited in size per file in Settings > Admin (25 MB by
default). Images, PDFs and plain text open in the browser; everything else
downloads.

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

`IMAGE_TAG=beta` follows the beta channel: previews of the next minor
release, published whenever the maintainer asks. Betas can break things;
back up first. `IMAGE_TAG=1.4.0` pins a version. Switching back from beta to
`latest` works as long as the beta did not run a migration the stable can't
read, which the changelog says.

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

Everything is in the volume: the SQLite database, the attachments and the
generated secret key. For a consistent copy while the app runs:

```sh
docker exec hyprvolt flask backup /data/backup-$(date +%F).tar.gz
docker cp hyprvolt:/data/backup-$(date +%F).tar.gz .
```

A name ending in `.tar.gz` (or `.tgz`, `.tar`) gets an archive of the
database (`hyprvolt.db`) and every attachment (`attachments/`). A name ending
in `.db` gets the database alone, without the files. `flask backup` uses
SQLite's online backup API; copying the `.db` file by hand while the app
writes can produce a torn copy.

To restore, stop the container, unpack the archive into the volume so that
`hyprvolt.db` and `attachments/` replace what is there (remove any `-wal` and
`-shm` files beside the database), and start it again.

## Commands

Run inside the container:

| Command | What it does |
| --- | --- |
| `flask create-user EMAIL [--role viewer\|editor\|admin] [--admin] [--name NAME]` | Create an account; asks for the password. `--admin` is `--role admin` |
| `flask reset-password EMAIL` | Set a new password; the way back in for a locked-out admin |
| `flask backup PATH` | Write a consistent copy: `.tar.gz` for the database and attachments, `.db` for the database alone |
| `flask seed-demo [--force]` | Fill an empty instance with a small demo homelab |
| `flask turnstile status`, `flask turnstile off` | Show whether Turnstile is on; turn it off when nobody can sign in |

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
| `n` | a page | New record (the menu of kinds, where there is more than one) |
| `j`, `k` | a record | Next, previous in the list |
| `1` to `9`, ← → | a record | Its tabs |
| `e`, `a`, `c` | a record | Edit, archive or unarchive, copy its link |
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
