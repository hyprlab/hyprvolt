# Architecture

One Flask process, SQLite in one volume, server-rendered HTML, and one
JavaScript file with no build step. This page is how the pieces fit and why.

## Layout

```
hyprprem/
  __init__.py      the app factory: database, sessions, CSRF, setup gate,
                   headers, error pages, template globals, migrations, worker
  config.py        every environment variable, each with a working default
  models.py        the models, and the runtime settings helpers
  auth.py          sign in, sign up, sign out, Turnstile, the sign-in throttle
  setup.py         the first-run wizard
  main.py          the shell route and the JSON API, admin routes last
  cli.py           flask commands: create-user, reset-password, backup
  worker.py        periodic background work
  about_docs.py    parses CHANGELOG.md for the About section
  sanitize.py      allowlist HTML sanitizer, stdlib only
  static/          css, js, fonts, images
  templates/       base, the app shell, auth, setup, error, partials
tools/             release and repository tooling
tests/             pytest
```

`run.py` is the development server. Production runs gunicorn against
`hyprprem:create_app()`.

## Decisions

**One gunicorn worker, eight threads.** The background thread must start
exactly once, and SQLite is happiest with one writing process. Threads carry
the concurrency. If the app outgrows that, the answer is moving the background
work to its own container, not adding web workers against one SQLite file.

**SQLite in WAL mode.** Readers don't wait for the writer, and
`busy_timeout` makes a writer wait for the lock instead of failing. Foreign
keys are switched on, which SQLite leaves off by default.

**No migration framework.** Schema changes are steps in `_migrate()`: an
`ALTER TABLE` guarded by a column check, run at every boot, safe to run twice.
New steps go at the end and old ones are never edited. It is enough for a
database that lives on one machine, and a deployment stays
`docker compose up -d` with nothing to remember.

**Server-rendered HTML, one JavaScript file.** Jinja renders pages; `app.js`
handles what would be worse as a page load. Paging asks the server for the
same list template (`?partial=1`) and splices it in, so there is one renderer
for the list, not two that drift apart. Nothing is compiled, so what is in the
repository is what runs.

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

**The first account is the admin.** No seeded account, no default password.
While the instance has no users every request goes to `/setup`.

**The changelog is the single record.** The About section renders `CHANGELOG.md`,
so one file is updated per release and the app shows exactly what the
repository says.

## A request

1. `ProxyFix` rewrites the client address and scheme, if `TRUST_PROXY` is set.
2. `steer_to_setup` sends everything to `/setup` while there are no users.
   Static files and `/healthz` are exempt.
3. `check_csrf` rejects a mutating request without the session token.
4. The route runs; `@login_required` covers everything but the auth pages,
   the wizard and `/healthz`. A signed-out API call gets a JSON 401.
5. `headers` adds `no-store` to HTML (the back button must never show records
   that have since changed) and the security headers.

## Where state lives

| | |
| --- | --- |
| `DATA_DIR` (`/data` in Docker, `./var` locally) | The SQLite database and the generated `.secret_key` |
| `users` | Accounts and per-user preferences |
| `settings` | Instance settings an admin changes at runtime |
| The session cookie | The signed-in user and the CSRF token |

Backing up the app is backing up `DATA_DIR` (see
[DOCUMENTATION.md](DOCUMENTATION.md#backups)).
