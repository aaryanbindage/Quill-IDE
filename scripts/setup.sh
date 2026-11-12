#!/usr/bin/env bash
# Build Quill IDE: clone VS Code (Code-OSS), apply the Quill overlay, install, compile.
# Needs Node (version in vscode/.nvmrc) and pnpm. Usage: scripts/setup.sh [vscode-dir]
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
VS="${1:-$HERE/vscode}"
if [ ! -d "$VS" ]; then
  git clone --depth 1 https://github.com/microsoft/vscode.git "$VS" ||
  git clone --depth 1 git@github.com:microsoft/vscode.git "$VS"
  # a shallow checkout can stumble on git-lfs; fall back to skipping the filter
  git -C "$VS" -c filter.lfs.process= -c filter.lfs.smudge= -c filter.lfs.required=false \
      restore --source=HEAD --staged --worktree :/ || true
fi
rm -rf "$VS/extensions/quill"
cp -R "$HERE/extensions/quill" "$VS/extensions/quill"
git -C "$VS" apply --check "$HERE/patches/product.json.patch" 2>/dev/null &&
  git -C "$VS" apply "$HERE/patches/product.json.patch" || echo "product.json already patched (or upstream changed)"
cd "$VS"
pnpm install --frozen-lockfile
pnpm run compile-client
pnpm run electron
node build/lib/preLaunch.ts
echo "Done. Launch with: $VS/scripts/code.sh <folder>"
