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

## Platforms

macOS (Apple Silicon) and Windows (x64). Releases are built by `.github/workflows/release.yml` on
macOS and Windows runners when a `v*` tag is pushed. Python 3 must be installed (the extension
detects `python3`, `python` or `py -3`; override with the `quill.python` setting).

## Install

- **Windows:** download `QuillIDE-Setup-<version>-x64.exe` from Releases and run it (per-user, no
  administrator needed). `QuillIDE-Setup-<version>-x64-system.exe` installs for all users.
  There is also a portable `QuillIDE-windows-x64.zip`. Installers are unsigned, so SmartScreen
  shows "Windows protected your PC": choose *More info*, then *Run anyway*.
- **macOS (Apple Silicon):** unzip `QuillIDE-macos-arm64.zip`. If macOS blocks it, right-click > Open.

Install [Python 3](https://www.python.org/downloads/) first (tick *Add python.exe to PATH* on Windows).
Building programs needs `clang`; on Windows it also needs `gcc` from a MinGW-w64 toolchain (such as w64devkit or winlibs) on `PATH`, which links the program.

## Build

Requires Node 24 (see VS Code's `.nvmrc`), pnpm 12, Python 3 and clang.

    scripts/setup.sh          # macOS / Linux / Git Bash
    scripts/setup.ps1         # Windows PowerShell (needs Git for Windows, VS C++ build tools)
    vscode/scripts/code.sh path/to/project      # Windows: vscode\scripts\code.bat

## Status

Runs from source in development mode; not packaged as an installer.

## Language server

`extensions/quill/server/quill_lsp.py` is a dependency-free LSP server that imports the bundled
Quill compiler, so its errors are the compiler's own. It provides diagnostics (syntax and type
errors as you type), completion (members through `self.`, variables, class names, generics such
as `List[int]`), hover, go to definition, signature help, document and workspace symbols.
`extensions/quill/client.js` is a small client that connects it to the editor.

Tests:

    python3 tests/test_lsp.py
    NODE_PATH=vscode/node_modules node tests/test_grammar.js

