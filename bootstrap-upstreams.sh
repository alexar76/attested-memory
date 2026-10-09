#!/usr/bin/env sh
# Fetch the exact AIMarket runtime used by this independent Hub.
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
upstream_dir="$project_dir/.upstreams"
mkdir -p "$upstream_dir"

# The canonical monorepo deploy copies the exact, tested Hub and protocol trees
# into .upstreams and records the source commit here. This path never needs a
# GitHub satellite and guarantees that production runs the same code committed
# to Gitea main. Keep the pinned checkout flow below as a standalone/offline
# fallback for operators who received only this project directory.
vendored_marker="$upstream_dir/.monorepo-vendored"
if [ -f "$vendored_marker" ]; then
  for required in \
    "$upstream_dir/aimarket-hub/pyproject.toml" \
    "$upstream_dir/aimarket-hub/aimarket_hub" \
    "$upstream_dir/aimarket-protocol/schemas"; do
    if [ ! -e "$required" ]; then
      echo "Vendored monorepo upstream is incomplete: $required is missing." >&2
      exit 1
    fi
  done
  echo "using monorepo-vendored upstreams ($(cat "$vendored_marker"))"
  exit 0
fi

apply_named_patches() {
  name=$1
  checkout=$2
  git_safe() {
    git -c "safe.directory=$checkout" -C "$checkout" "$@"
  }
  # production base first, then additive overlays (assay-schema-input, federation-verify, …).
  ordered=""
  prod="$project_dir/patches/$name-production.patch"
  [ -f "$prod" ] && ordered="$prod"
  for patch in "$project_dir/patches/$name"-*.patch; do
    [ -f "$patch" ] || continue
    [ "$patch" = "$prod" ] && continue
    ordered="$ordered $patch"
  done
  for patch in $ordered; do
    if git_safe apply --reverse --check "$patch" >/dev/null 2>&1; then
      continue
    fi
    git_safe apply --check "$patch"
    git_safe apply "$patch"
    echo "applied $(basename "$patch")"
  done
}

checkout_pinned() {
  name=$1
  url=$2
  commit=$3
  checkout="$upstream_dir/$name"
  # Deploys may run under a different uid than the persistent volume owner.
  # Trust only this pinned checkout for each invocation; never weaken Git's
  # ownership check globally on the host.
  git_safe() {
    git -c "safe.directory=$checkout" -C "$checkout" "$@"
  }
  if [ -e "$checkout" ] && [ ! -d "$checkout/.git" ]; then
    echo ".upstreams/$name exists but is not a verifiable Git checkout." >&2
    exit 1
  fi
  if [ ! -d "$checkout/.git" ]; then
    git clone --filter=blob:none --no-checkout "$url" "$checkout"
    git_safe checkout --detach "$commit"
  fi
  actual=$(git_safe rev-parse HEAD)
  if [ "$actual" != "$commit" ]; then
    echo "$name is at $actual, expected pinned commit $commit." >&2
    exit 1
  fi
  apply_named_patches "$name" "$checkout"
}

checkout_pinned \
  aimarket-hub \
  https://github.com/alexar76/aimarket-hub.git \
  cf556fe4409eb63ea9d44999a4329929a373164f

checkout_pinned \
  aimarket-protocol \
  https://github.com/alexar76/aimarket-protocol.git \
  b5200212ab8068286bfa4859d5954cb2974d4abf
