#!/usr/bin/env bash
# Prepare a release commit and tag, locally. Pushes nothing.
#
#   tools/prepare-release.sh stable [VERSION]   # on main, or on stable-X.Y for a patch
#
# Hyprvolt has no beta channel: a release goes from main straight to stable.
#
# VERSION defaults to what tools/next-version.sh says SemVer calls for. If one
# is given and it disagrees, the script stops and says why: the version is the
# maintainer's call, but a mismatch has to be a decision, not an accident.
# Set FORCE_VERSION=1 to go ahead with a version that disagrees.
#
# Afterwards: review, then the publish steps in docs/RELEASING.md.
set -euo pipefail
cd "$(dirname "$0")/.."

CHANNEL="${1:?usage: tools/prepare-release.sh stable [VERSION]}"
WANT="${2:-}"
INIT=$(ls */__init__.py | grep -vE '^(tests|tools)/' | head -1)

[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "The working tree has uncommitted changes." >&2; exit 1; }
[ "$(git config core.hooksPath)" = "tools/git-hooks" ] || { echo "Run: git config core.hooksPath tools/git-hooks" >&2; exit 1; }

branch=$(git symbolic-ref --short HEAD)
case "$CHANNEL" in
    stable) [[ "$branch" = main || "$branch" == stable-* ]] || { echo "A stable ships from main or stable-X.Y." >&2; exit 1; }
            SUGGESTED=$(tools/next-version.sh) ;;
    beta)   echo "This project has no beta channel: ship to stable (docs/RELEASING.md)." >&2; exit 1 ;;
    *) echo "usage: tools/prepare-release.sh stable [VERSION]" >&2; exit 1 ;;
esac

VERSION="${WANT:-$SUGGESTED}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "A version is X.Y.Z; $VERSION is not one." >&2; exit 1; }
if [ "$VERSION" != "$SUGGESTED" ] && [ "${FORCE_VERSION:-0}" != 1 ]; then
    echo "SemVer calls for $SUGGESTED, not $VERSION. The commits that decide it:" >&2
    tools/next-version.sh --why >/dev/null || true
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

tools/bump-version.sh "$VERSION"

git add CHANGELOG.md "$INIT"
git commit -q -m "chore(release): $VERSION"
git tag -a "v$VERSION" -m "$VERSION"
echo
echo "==> v$VERSION committed and tagged on $(git symbolic-ref --short HEAD). Nothing is pushed."
echo "    Review: git show --stat HEAD && tools/release-notes.sh $VERSION"
echo "    Then follow docs/RELEASING.md from \"Publish\"."
