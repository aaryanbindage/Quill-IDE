# Build Quill IDE for development on Windows. Needs Git, Node 24 (see vscode\.nvmrc), pnpm,
# Python 3 and the Visual Studio C++ build tools.
param([string]$VsDir = (Join-Path (Split-Path $PSScriptRoot -Parent) "vscode"))
$ErrorActionPreference = "Stop"
$bash = (Get-Command bash -ErrorAction SilentlyContinue)
if (-not $bash) { throw "Git for Windows (Git Bash) is required: https://git-scm.com/download/win" }
& bash (Join-Path $PSScriptRoot "prepare.sh") ($VsDir -replace '\\','/')
Push-Location $VsDir
try {
  pnpm install --frozen-lockfile
  pnpm run compile-client
  pnpm run electron
  node build/lib/preLaunch.ts
} finally { Pop-Location }
Write-Host "Done. Launch with: $VsDir\scripts\code.bat <folder>"
