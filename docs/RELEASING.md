# Releasing

How versions are numbered, when releases happen, and the exact steps. The
policy comes from Hylki, where it was settled after a week of twenty stable
releases left users tired of update prompts and a beta channel that only ever
mirrored stable after the fact.

## Versions: strict SemVer

Every release follows [Semantic Versioning 2.0.0](https://semver.org/). For an
app, the "public API" is whatever an existing install and its users depend on:
the data volume, the configuration, the URLs, and the features.

| Bump | When | Examples |
| --- | --- | --- |
| **MAJOR** `2.0.0` | Anything an existing install can't take without help | A migration an older version can't read back; a removed feature or setting; a renamed or removed environment variable; a changed URL other things link to; a changed volume path or port |
| **MINOR** `1.5.0` | New, backward-compatible functionality, or a deprecation | A new feature, setting, page or command; a new optional environment variable |
| **PATCH** `1.4.1` | Backward-compatible fixes only | A bug fix, a performance fix, a security fix with no behavior change |

`tools/next-version.sh` reads the Conventional Commit types since the last
stable and says which bump they call for: `!` or a `BREAKING CHANGE:` footer is
major, `feat` is minor, `fix`, `perf` and `revert` are patch.
`tools/prepare-release.sh` refuses a version that disagrees unless told
`FORCE_VERSION=1`. The tool cannot see everything, so read the commits too:
a `fix` that changes the schema irreversibly is still MAJOR.

**Before any release, say plainly if the requested version does not fit** what
the commits since the last tag contain, and what SemVer calls for instead. The
maintainer decides; a mismatch has to be a decision, not an accident. A week
with no features is a patch, not a minor.

A version never counts backwards, and a released version is never reused. The
version lives in one place, `__version__` in the package's `__init__.py`, and
the newest `CHANGELOG.md` section must match it (`tools/check-docs.py`).

## Channels and cadence

| | Branch | Version | Docker tags | GitHub release |
| --- | --- | --- | --- | --- |
| Development | `main` | the last stable, plus `## Unreleased` in the changelog | none | none |
| Beta | `beta` | `X.Y.0-beta.K` | `:X.Y.0-beta.K`, `:beta` | prerelease |
| Stable | `main` | `X.Y.Z` | `:X.Y.Z`, `:X.Y`, `:latest` | release |
| Urgent patch | `stable-X.Y` | `X.Y.Z+1` | as stable | release |

1. **Work lands on `main`.** Commits stay local until the maintainer says to
   push or ship. Every user-visible change adds a line under `## Unreleased`.
2. **Beta is the gate, not a copy.** "Ship it to beta" merges `main` into
   `beta` and publishes `X.(N+1).0-beta.K`, where N is the current stable
   minor and K counts up. Nightly-style: whatever is on main, whenever the
   maintainer asks. A beta never moves `:latest`.
3. **Stable is roughly weekly, and only on request.** "Ship it to stable"
   promotes what the latest beta carried. If `main` has commits since that
   beta, ask whether to include them untested or cut another beta first.
4. **Patches are for urgent fixes only:** a crash, data loss, a security
   hole, an instance that can't start or can't sign anyone in. Everything else
   waits for the next stable. See [Urgent patches](#urgent-patches).
5. **No catch-up beta after a stable.** The next beta after `1.N.0` is
   `1.(N+1).0-beta.1`, cut from main when asked.
6. **A bare "ship" or "ship it" is ambiguous.** Ask: beta or stable?

If the app gains translations, add a string freeze: no new user-facing strings
between the beta that becomes the stable and the stable itself.

## Before any release

- `python3 tools/check-docs.py` passes. A release does not go out while it fails.
- The test suite passes (`prepare-release.sh` runs both).
- The changelog entries are written in the project's prose style
  ([CONTRIBUTING.md](CONTRIBUTING.md#prose-style)): what changed, from the
  user's side, factual, no marketing and no emoji.
- Every contributor in the release is in `data/CONTRIBUTORS` **before** the
  notes are generated, or `tools/release-notes.sh` strips their @.
- No commit since the last release carries AI attribution:
  `git log origin/main..main --format=%B | grep -i co-authored-by` shows only
  people. The `pre-push` hook refuses the rest.

## Ship it to beta

```sh
tools/prepare-release.sh beta          # version from next-version.sh
```

That checks out `beta` (creating it the first time), merges `main` with
`-X theirs`, rewrites the changelog so one `## [X.Y.0-beta.K]` section holds
everything main has unreleased, sets `__version__`, runs the checks, commits
`chore(release): X.Y.0-beta.K`, tags it, and stops. Then publish:

```sh
git push origin main beta vX.Y.0-beta.K
tools/release-notes.sh X.Y.0-beta.K > /tmp/notes.md
gh release create vX.Y.0-beta.K --prerelease --title "vX.Y.0-beta.K" --notes-file /tmp/notes.md
tools/publish-image.sh X.Y.0-beta.K
git checkout main
```

`--prerelease` always, so `releases/latest` keeps pointing at stable.

Issues fixed in the beta get a reply naming the beta version and saying it
reaches stable with the next weekly release. They stay open until that stable
ships. See [Issue replies](CONTRIBUTING.md#issue-replies).

## Ship it to stable

On `main`, with the changelog's `## Unreleased` section written:

```sh
tools/prepare-release.sh stable        # version from next-version.sh
```

That turns `## Unreleased` into `## [X.Y.Z] — date`, sets `__version__`, runs
the checks, commits `chore(release): X.Y.Z`, tags it, and stops. Then publish:

```sh
git push origin main vX.Y.Z
tools/release-notes.sh X.Y.Z > /tmp/notes.md
gh release create vX.Y.Z --title "vX.Y.Z" --notes-file /tmp/notes.md
tools/publish-image.sh X.Y.Z
docker compose pull && docker compose up -d     # the maintainer's own instance
```

The release title is the version and nothing else: no name, no tagline. The
body is that version's changelog section plus the generated list of commits.

Then reply to and close every issue the release fixes, and delete the
superseded releases (below).

## Urgent patches

Only for a crash, data loss, a security hole, or an instance that can't start
or can't sign anyone in.

1. Fix it on `main` first, in its own commit, so it cherry-picks cleanly.
2. Cut the branch lazily, from the last release tag, never from main:
   `git branch stable-X.Y vX.Y.Z` (skip if it exists).
3. `git checkout stable-X.Y && git cherry-pick <sha>`, add the changelog line
   under `## Unreleased`, then `tools/prepare-release.sh stable X.Y.Z+1`.
4. Publish as for a stable, pushing `stable-X.Y` instead of `main`.
5. Merge `stable-X.Y` back into `main`, so the changelog entry survives.
6. Ship a beta from main alongside the patch, so the beta is never missing a
   fix that stable has.
7. Never delete a `stable-X.Y` branch: patch commits may exist only there.

## The Releases page

Keep it short: the newest release of each `X.Y` line, plus the current beta.
When a new patch supersedes `X.Y.Z`, or a new beta supersedes the previous one,
delete the superseded release and its tag, but only after the new one is
published, `releases/latest` points at it, and its notes were generated (the
notes diff against the previous tag of the same kind). Docker image tags are
never deleted: someone may have pinned one. Confirm with the maintainer the
first time this comes up in a project.

## Docker images

`tools/publish-image.sh` builds from the tag with `git archive`, not from the
working tree, so the image is exactly what was released. It pushes
`linux/amd64` only; set `PLATFORMS=linux/amd64,linux/arm64` once the host's
buildx has an arm64 builder. Users pick a channel with `IMAGE_TAG` in their
`.env`: `latest` (default), `beta`, or a version to pin.
