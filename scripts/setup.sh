#!/usr/bin/env bash
# Build Quill IDE for development: prepare, install, compile. Needs Node (see vscode/.nvmrc) and pnpm.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
VS="${1:-$HERE/vscode}"
"$HERE/scripts/prepare.sh" "$VS"
cd "$VS"
pnpm install --frozen-lockfile
pnpm run compile-client
pnpm run electron
node build/lib/preLaunch.ts
echo "Done. Launch with: $VS/scripts/code.sh <folder>   (Windows: scripts\\code.bat)"
