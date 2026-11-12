#!/usr/bin/env bash
# Clone VS Code (Code-OSS) and apply the Quill overlay. Works on macOS, Linux and Windows (Git Bash).
# Usage: scripts/prepare.sh [vscode-dir]
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
VS="${1:-$HERE/vscode}"
if [ ! -d "$VS/.git" ]; then
  rm -rf "$VS"
  git clone -c core.autocrlf=false --depth 1 https://github.com/microsoft/vscode.git "$VS" ||
  git clone -c core.autocrlf=false --depth 1 git@github.com:microsoft/vscode.git "$VS"
  # a shallow checkout can stumble on git-lfs; fall back to skipping the filter
  git -C "$VS" -c filter.lfs.process= -c filter.lfs.smudge= -c filter.lfs.required=false \
      restore --source=HEAD --staged --worktree :/ || true
fi
rm -rf "$VS/extensions/quill"
cp -R "$HERE/extensions/quill" "$VS/extensions/quill"
for PATCH in "$HERE"/patches/*.patch; do
if git -C "$VS" apply --check "$PATCH" 2>/dev/null; then
  git -C "$VS" apply "$PATCH"
else
  echo "$(basename "$PATCH") already applied (or upstream changed)"
fi
done
echo "Prepared $VS"
