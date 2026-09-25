#!/usr/bin/env bash
# Prepare a release commit and tag, locally. Pushes nothing.
#
#   tools/prepare-release.sh beta [VERSION]     # on main: merges main into beta
#   tools/prepare-release.sh stable [VERSION]   # on main, or on stable-X.Y for a patch
#
# VERSION defaults to what tools/next-version.sh says SemVer calls for. If one
# is given and it disagrees, the script stops and says why: the version is the
# maintainer's call, but a mismatch has to be a decision, not an accident.
# Set FORCE_VERSION=1 to go ahead with a version that disagrees.
#
# Afterwards: review, then the publish steps in docs/RELEASING.md.
set -euo pipefail
cd "$(dirname "$0")/.."

CHANNEL="${1:?usage: tools/prepare-release.sh beta|stable [VERSION]}"
WANT="${2:-}"
INIT=$(ls */__init__.py | grep -vE '^(tests|tools)/' | head -1)

[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "The working tree has uncommitted changes." >&2; exit 1; }
[ "$(git config core.hooksPath)" = "tools/git-hooks" ] || { echo "Run: git config core.hooksPath tools/git-hooks" >&2; exit 1; }

branch=$(git symbolic-ref --short HEAD)
case "$CHANNEL" in
    beta)   [ "$branch" = main ] || { echo "Prepare a beta from main (you are on $branch)." >&2; exit 1; }
            SUGGESTED=$(tools/next-version.sh beta) ;;
    stable) [[ "$branch" = main || "$branch" == stable-* ]] || { echo "A stable ships from main or stable-X.Y." >&2; exit 1; }
            SUGGESTED=$(tools/next-version.sh stable) ;;
    *) echo "beta or stable" >&2; exit 1 ;;
esac

VERSION="${WANT:-$SUGGESTED}"
if [ "${VERSION%-beta.*}" != "${SUGGESTED%-beta.*}" ] && [ "${FORCE_VERSION:-0}" != 1 ]; then
    echo "SemVer calls for $SUGGESTED, not $VERSION. The commits that decide it:" >&2
    tools/next-version.sh "$CHANNEL" --why >/dev/null || true
    echo "Rerun with FORCE_VERSION=1 if $VERSION is deliberate." >&2
    exit 1
fi
if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null; then
    echo "v$VERSION already exists." >&2
    exit 1
fi

echo "==> tests and docs"
python3 tools/check-docs.py
if [ -x .venv/bin/python ]; then .venv/bin/python -m pytest -q; else python3 -m pytest -q; fi

if [ "$CHANNEL" = beta ]; then
    # main stays on "## Unreleased" and the last stable version; the beta
    # branch is main plus one release commit. The version line and the
    # changelog conflict on every merge, so neither is trusted to it: the
    # changelog is rebuilt from main's copy, with main's Unreleased entries
    # moved under the beta's heading. Earlier beta sections disappear,
    # superseded by this one, which carries everything the coming stable will.
    if git rev-parse -q --verify refs/heads/beta >/dev/null; then
        git checkout -q beta
        git merge -q --no-edit -X theirs main
    else
        git checkout -q -b beta
    fi
    git show main:CHANGELOG.md > CHANGELOG.md
    python3 - "$VERSION" "$(date +%F)" <<'PY'
import re, sys, pathlib
version, today = sys.argv[1:]
p = pathlib.Path("CHANGELOG.md")
t = p.read_text(encoding="utf-8")
m = re.search(r"^## Unreleased[ \t]*\n(.*?)(?=^## |\Z)", t, re.M | re.S)
if not m or not m.group(1).strip():
    sys.exit("main's Unreleased section is empty: nothing to preview.")
section = f"## Unreleased\n\n## [{version}] — {today}\n\n{m.group(1).strip()}\n\n"
p.write_text(t[:m.start()] + section + t[m.end():], encoding="utf-8")
PY
    sed -i "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" "$INIT"
    python3 tools/check-docs.py
else
    tools/bump-version.sh "$VERSION"
fi

git add CHANGELOG.md "$INIT"
git commit -q -m "chore(release): $VERSION"
git tag -a "v$VERSION" -m "$VERSION"
echo
echo "==> v$VERSION committed and tagged on $(git symbolic-ref --short HEAD). Nothing is pushed."
echo "    Review: git show --stat HEAD && tools/release-notes.sh $VERSION"
echo "    Then follow docs/RELEASING.md from \"Ship it to beta\" or \"Ship it to stable\"."
