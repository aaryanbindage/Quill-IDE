# Quill IDE

An IDE for the [Quill language](https://github.com/aaryanbindage/Quill), built as a fork of
VS Code (Code-OSS) with a JetBrains-style look.

This repository holds only what Quill IDE changes. `scripts/setup.sh` clones VS Code,
applies these changes, and builds it.

| Path | What it is |
|---|---|
| `extensions/quill` | Built-in extension: `.ql` syntax, snippets, Darcula and light themes, Run/Build commands, bundled compiler |
| `patches/product.json.patch` | Branding (name, data folder, bundle id) and JetBrains-style default settings |
| `scripts/setup.sh` | Clone, patch, install, compile |

## Build

Requires Node 24 (see VS Code's `.nvmrc`), pnpm 12, Python 3 and clang.

    scripts/setup.sh
    vscode/scripts/code.sh path/to/project

## Status

Runs from source in development mode; not packaged as an installer. No language server yet
(see `server/` once added).
