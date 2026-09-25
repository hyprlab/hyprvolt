# Contributing

The conventions anyone editing this repository follows, human or AI. Bug
reports, ideas and pull requests are all welcome, and a clear bug report is
often as useful as a patch.

## Setting up

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
git config core.hooksPath tools/git-hooks     # once per clone or worktree
.venv/bin/python -m pytest
.venv/bin/python run.py                       # http://localhost:8000
```

The hooks enforce the commit rules below and run the documentation check.
Without `core.hooksPath` they silently do nothing, so set it in every clone
and every worktree.

To try a change the way it will run in production, rebuild the container:
`tools/redeploy.sh`.

## Commits

**The history is the maintainer's.** Commits carry no AI tool attribution: no
`Co-Authored-By:` line for an AI assistant, no "Generated with"
footer, no session line, in a commit, a tag message, a pull request body or a
release body. The [AI notice](../README.md#ai-notice) declares how the project
is built, once, for the whole repository. One stray trailer puts the tool on
GitHub's Contributors panel, and removing it again means rewriting history.

A `Co-Authored-By:` trailer is still how a **person** is credited, with the
GitHub noreply address that resolves to their profile (see
[Credit](#credit)).

Subjects follow [Conventional Commits](https://www.conventionalcommits.org):
`type(area): summary`, lower case after the colon, imperative, no full stop,
72 characters at most and ideally nearer 50.

- Types: `feat`, `fix`, `perf`, `refactor`, `docs`, `build`, `ci`, `test`,
  `style`, `chore`, `revert`. A `!` after the type (`feat(api)!:`) marks a
  breaking change. The type is not decoration: `tools/next-version.sh` reads
  it to decide the next version ([RELEASING.md](RELEASING.md)).
- The area is where the change lives: `auth`, `setup`, `admin`, `settings`,
  `sidebar`, `sheet`, `search`, `worker`, `db`, `ui`, `docker`, `release`,
  plus the app's own: `core`, `api`, `cli`, and each module's id
  (`locations`, `documents`). Leave it out only when there is no single place.
- An issue number goes at the end: `fix(auth): keep the next page after sign-in (#12)`.
- Releases: `chore(release): 1.4.0`, `chore(release): 1.5.0-beta.1`.

The body is optional and short: why the change exists, never what the diff
already says. Past 100 words the detail belongs in `docs/` or `CHANGELOG.md`,
or the commit wants splitting. **Each body paragraph is one line, not
wrapped:** GitHub keeps every line break in a body, so text wrapped at 72
breaks a second time on a phone. Write it with `git commit -F -` and a heredoc.

No em dashes in commit messages: a colon, a comma or a full stop replaces
them.

`tools/git-hooks/commit-msg` refuses the attribution lines, em dashes, a
subject without a type, and an overlong subject or body. `pre-push` refuses to
publish any commit or tag carrying attribution. Patterns of a clone's own, one
regular expression per line, go in `.git/info/attribution`; both hooks read
them, and the file is never committed.

## Local files

Files a maintainer keeps for their own tools stay out of the repository:
list them in `.git/info/exclude`, not `.gitignore`, and never `git add -f`
them. The `pre-commit` hook refuses to commit anything listed there by name.
A new worktree does not get them: copy or link what it needs.

## Prose style

Documentation, the changelog, release notes, UI text and issue replies:

- Factual, plain language. Say what the app does, not what it enables you to
  do. No marketing, no superlatives, no "finally", no emoji.
- American spelling in anything the app shows: color, behavior, canceled.
- Changelog lines describe the change from the user's side. How it was built
  belongs in the commit.
- Comments in code explain *why*, not *what*.

## Documentation

The README is the front door and has a 200-line ceiling. Before writing a word
of documentation, decide where it goes: the table in
[docs/README.md](README.md) says. After touching any `.md`, run:

```sh
python3 tools/check-docs.py
```

It checks every relative link and anchor, that every `docs/*.md` is indexed,
that `docs/` holds Markdown only, the README's length, and the changelog's
shape and version.

Every release, patches included, gets a `CHANGELOG.md` section. The About section
renders the changelog, so a skipped section is a gap users see.

## Code

- Match what is there: the app factory, blueprints, the `{"error": "..."}`
  shape for JSON failures, `api()` in `app.js` for every mutating call.
- Schema changes go in `_migrate()` (the core's) or a module's `migrations`
  as guarded steps; a new table needs none. Never edit an old step. A step an
  older version can't read back is a MAJOR release. The rule is in
  [ARCHITECTURE.md](ARCHITECTURE.md#schema-changes).
- Every route carries `@role(...)`, and every change to a record goes through
  `core/records.py`. A new kind of record is a module ([MODULES.md](MODULES.md)).
- Anything the user typed is rendered with Jinja's escaping or `textContent`,
  never `|safe` or `innerHTML`. Foreign HTML goes through
  `sanitize.sanitize_html()` first.
- User-facing failures say what happened and what to do, in a sentence.
- Tests before committing (`pytest`), and rebuild and run the app
  (`tools/redeploy.sh`) before saying something works.

## Credit

Outside pull requests land as commits on `main` made by the maintainer,
crediting the author with a trailer that uses their GitHub noreply address:

```
Co-Authored-By: Jane Doe <12345678+janedoe@users.noreply.github.com>
```

Get the id with `gh api users/<login> --jq .id`. An address taken from their
own commit may not be linked to their account, and then they never appear as a
contributor; that can't be fixed after a tagged release without rewriting
history.

Add them to `data/CONTRIBUTORS` (their name and `@login`) and describe the
work in [CREDITS.md](CREDITS.md). Close the pull request with a comment saying
what was taken, what changed and what was left out.

In release notes an `@` is for people whose code, art or translation is in the
release. Reporters and requesters are named without the `@`: an @ notifies
someone and reads as authorship. `tools/release-notes.sh` strips the @ from any
handle not in `data/CONTRIBUTORS`.

## Issue replies

Every reply to an issue or pull request written by an agent begins with
`*Agentic reply:*` in italics, then a blank line, then the reply.

- A reply saying something is done is one or two sentences: what changed from
  the user's side, and which version carries it. How it was built is in the
  commit and the changelog.
- No thanks, no pleasantries, no em dashes. Plain, brief, human.
- Anything the user has to do (send a log, try something, check a setting) is
  a numbered list, one request per item.
- Fixed in a beta: name the beta version and say it reaches stable with the
  next weekly release. The issue closes when that stable ships.
- Fixed in a stable: name the version and how to update. Reply once the image
  is pushed, not before.

```
*Agentic reply:*

Fixed in 1.4.0: the sign-in page now returns you to the page you asked for.

Update with `docker compose pull && docker compose up -d`.
```

Only a reply that asks for something or explains a decline runs longer.
