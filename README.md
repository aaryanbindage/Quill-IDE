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

