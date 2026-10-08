#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-$(cd "$(dirname "$0")/../external" && pwd)/chaos-persona}"
REPO="https://github.com/ELXaber/chaos-persona.git"
COMMIT="cabe1d0b77c5080f86f49cc2a7c230785e0ceb8e"

if [[ ! -e "$TARGET" ]]; then
  git clone "$REPO" "$TARGET"
elif [[ ! -d "$TARGET/.git" ]]; then
  echo "Target exists but is not a Git checkout: $TARGET" >&2
  exit 1
fi

git -C "$TARGET" fetch --tags --prune origin
git -C "$TARGET" checkout --detach "$COMMIT"

test -f "$TARGET/Project_Andrew/CAIOS.txt"
test -f "$TARGET/LICENSE.txt"

echo "CAIOS checkout pinned to $COMMIT"
echo "Set CAIOS_SOURCE_PATH=$TARGET/Project_Andrew"
echo "Required attribution: Built on CAIOS v1.0 by inventor Jonathan M. Schack – Patent Pending US 19/433,771 & 19/390,493 – www.cai-os.com"
