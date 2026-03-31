# Wiseman Auto System - Windows Setup
# Run: irm https://raw.githubusercontent.com/sasakisystem0801-source/wiseman-auto-sys/main/scripts/setup-windows.ps1 | iex

Write-Host "=== Wiseman Auto System Setup ===" -ForegroundColor Green

# Git
Write-Host "Installing Git..." -ForegroundColor Yellow
winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
$env:Path += ";C:\Program Files\Git\cmd"

# Python 3.11
Write-Host "Installing Python 3.11..." -ForegroundColor Yellow
winget install --id Python.Python.3.11 -e --accept-source-agreements --accept-package-agreements
$env:Path += ";$env:LOCALAPPDATA\Programs\Python\Python311;$env:LOCALAPPDATA\Programs\Python\Python311\Scripts"

# uv
Write-Host "Installing uv..." -ForegroundColor Yellow
irm https://astral.sh/uv/install.ps1 | iex
$env:Path += ";$env:USERPROFILE\.local\bin"

# Clone
Write-Host "Cloning repository..." -ForegroundColor Yellow
cd $env:USERPROFILE\Desktop
git clone https://github.com/sasakisystem0801-source/wiseman-auto-sys.git
cd wiseman-auto-sys

# Dependencies
Write-Host "Installing dependencies..." -ForegroundColor Yellow
uv sync

Write-Host ""
Write-Host "=== Done! ===" -ForegroundColor Green
Write-Host "Next: Start Wiseman, then run:" -ForegroundColor Yellow
Write-Host "  uv run python scripts/dump_ui.py --text" -ForegroundColor Cyan
