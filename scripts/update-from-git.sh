#!/usr/bin/env bash
set -euo pipefail

repo="${EVERYWHERE_GIT_REPO:-https://github.com/jas0n1ee/.everywhere.git}"
ref="${1:-${EVERYWHERE_GIT_REF:-main}}"

if [[ "${repo}" == git+* ]]; then
  package="${repo}@${ref}"
else
  package="git+${repo}@${ref}"
fi

echo "Updating jas0n1ee-everywhere from ${package}"

uv tool install --force --refresh "${package}"

if ! command -v everywhere >/dev/null 2>&1; then
  echo "everywhere is not on PATH after install; run: uv tool update-shell" >&2
  exit 1
fi

everywhere install
everywhere feishu status

echo "Update complete."
