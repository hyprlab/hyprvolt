#!/usr/bin/env bash
# Build the Docker image for a tagged version and push it to Docker Hub.
#
#   tools/publish-image.sh 1.3.0          # pushes :1.3.0, :1.3 and :latest
#   tools/publish-image.sh 1.4.0-beta.1   # pushes :1.4.0-beta.1 and :beta
#
# A beta never moves :latest, so anyone on the default compose file stays on
# stable. Builds from the tag, not the working tree, so what is pushed is
# exactly what was released. linux/amd64 only by default: the host's buildx has
# no arm64 builder. Set PLATFORMS=linux/amd64,linux/arm64 once it does.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:?usage: tools/publish-image.sh X.Y.Z[-beta.N]}"
TAG="v$VERSION"
PKG=$(ls */__init__.py | grep -vE '^(tests|tools)/' | head -1 | cut -d/ -f1)
IMAGE="${IMAGE:-hyprlab/$PKG}"
PLATFORMS="${PLATFORMS:-linux/amd64}"

git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || { echo "no tag $TAG" >&2; exit 1; }
tagged=$(git show "$TAG:$PKG/__init__.py" | sed -n 's/^__version__ = "\(.*\)"/\1/p')
[ "$tagged" = "$VERSION" ] || { echo "$TAG carries __version__ $tagged, not $VERSION" >&2; exit 1; }

if [[ "$VERSION" == *-* ]]; then
    tags=(-t "$IMAGE:$VERSION" -t "$IMAGE:beta")
else
    minor="${VERSION%.*}"
    tags=(-t "$IMAGE:$VERSION" -t "$IMAGE:$minor" -t "$IMAGE:latest")
fi

src=$(mktemp -d)
trap 'rm -rf "$src"' EXIT
git archive "$TAG" | tar -x -C "$src"

echo "Building $IMAGE for $VERSION ($PLATFORMS) from $TAG"
docker buildx build --platform "$PLATFORMS" \
    --label "org.opencontainers.image.version=$VERSION" \
    --label "org.opencontainers.image.revision=$(git rev-parse "$TAG^{commit}")" \
    --label "org.opencontainers.image.source=https://github.com/$IMAGE" \
    "${tags[@]}" --push "$src"

echo "Pushed: ${tags[*]//-t /}"
