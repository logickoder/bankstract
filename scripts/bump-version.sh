#!/usr/bin/env bash
# Bump the project version.
#
#   scripts/bump-version.sh              # patch bump (0.2.0 -> 0.2.1)
#   scripts/bump-version.sh patch        # same
#   scripts/bump-version.sh minor        # 0.2.1 -> 0.3.0
#   scripts/bump-version.sh major        # 0.3.0 -> 1.0.0
#   scripts/bump-version.sh 0.3.0        # set to exact X.Y.Z
#
# Updates pyproject.toml and src/bankstract/__init__.py atomically and
# re-syncs the uv lockfile.

set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
pyproject="${repo_root}/pyproject.toml"
init_py="${repo_root}/src/bankstract/__init__.py"

current=$(sed -nE 's/^version = "([0-9]+\.[0-9]+\.[0-9]+)"$/\1/p' "$pyproject" | head -1)
if [[ -z "$current" ]]; then
  echo "bump-version: couldn't parse current version in $pyproject" >&2
  exit 1
fi

arg=${1:-patch}
IFS=. read -r major minor patch <<<"$current"

case "$arg" in
  patch) new="${major}.${minor}.$((patch + 1))" ;;
  minor) new="${major}.$((minor + 1)).0" ;;
  major) new="$((major + 1)).0.0" ;;
  *)     new="$arg" ;;
esac

if ! [[ "$new" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "bump-version: invalid semver '$new' (want X.Y.Z)" >&2
  exit 1
fi

if [[ "$new" == "$current" ]]; then
  echo "bump-version: already at $current — nothing to do" >&2
  exit 1
fi

sed -i.bak -E "s/^version = \"${current}\"$/version = \"${new}\"/" "$pyproject"
sed -i.bak -E "s/^__version__ = \"${current}\"$/__version__ = \"${new}\"/" "$init_py"
rm "${pyproject}.bak" "${init_py}.bak"

# README status table shows the current MAJOR.MINOR tag; keep it in sync.
# (PRD scope / roadmap intentionally retain historical labels — not touched.)
new_short="${new%.*}"
readme="${repo_root}/README.md"
if [[ -f "$readme" ]]; then
  sed -i.bak -E "s/v[0-9]+\.[0-9]+ — alpha/v${new_short} — alpha/g" "$readme"
  rm "${readme}.bak"
fi

uv sync --quiet

echo "${current} -> ${new}"
