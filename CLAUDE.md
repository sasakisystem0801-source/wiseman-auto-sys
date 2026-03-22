# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Install dependencies
uv sync

# Run all tests
pytest

# Run a single test
pytest tests/unit/test_config.py::test_load_config_from_file

# Lint
ruff check src/
flake8 .          # pre-push hook uses this (config in .flake8)

# Type check
mypy src/

# Run the app
python -m wiseman_hub
```

Note: `pythonpath = ["src"]` is configured in pyproject.toml for pytest.

## Architecture

### What This System Does

Automates the care software "Wiseman System SP" via Python RPA (pywinauto) and syncs extracted data to GCP. The pipeline: **launch Wiseman → login → navigate to report → export CSV → upload to GCS**.

### Key Architectural Fact

Wiseman is marketed as "ASP" (Application Service Provider) but the client is a **.NET Framework 3.5 native Windows app** (WinForms, MDI), not a browser app. Installed at `C:\Users\{User}\AppData\Local\Programs\WISEMAN\WISEMANVSYSTEM\`. Authentication via USB dongle or License ID.

### Data Flow

```
WisemanHub (app.py)  orchestrates:
  → RPAEngine (rpa/base.py)     GUI automation via pywinauto
    → Wiseman .NET app           MDI windows, WinForms controls
  → storage.py (cloud/)          uploads CSV to GCS
  → config.py                    loads TOML config (dataclass-based)
```

### Module Boundaries

- `rpa/` — **Windows-only**. Uses `sys.platform == "win32"` guard. Must provide mock implementations for macOS testing. All RPA implementations extend `RPAEngine` (abstract base class in `rpa/base.py`).
- `cloud/` — Cross-platform. GCP SDK clients.
- `config.py` — TOML loader with `tomllib` (3.11+) / `tomli` (3.9+) fallback. Config structure is nested dataclasses (`AppConfig` → `WisemanConfig`, `GcpConfig`, `ReportTarget`, etc.).
- `updater/`, `scheduler/`, `ui/` — Planned modules (empty stubs).

### Credentials

Wiseman password stored via `keyring` (Windows DPAPI), never in config files. GCP uses service account key file referenced by path in TOML config.

## Cross-Platform Development

Development happens on macOS; Wiseman runs only on Windows.

- `rpa/` code cannot run on macOS — use mock implementations for unit tests
- Real E2E testing requires TeamViewer → Windows 11 client PC with USB dongle
- Use `Inspect.exe` or `Spy++` on Windows to discover pywinauto selectors
- Always use `pathlib.Path` — never hardcode `\\` path separators

## Design Decisions

ADRs in `docs/adr/` (001–006). Wiseman technical spec in `docs/wiseman-system-spec.md`. PRD in `docs/prd.md`.

Key decisions: pywinauto over Playwright (ADR-001), PyInstaller for packaging (ADR-002), GCP tokyo region for APPI compliance (ADR-003), GCS manifest polling for auto-update (ADR-004), TOML config format (ADR-005).

## Wiseman UI Structure (confirmed from real environment)

MDI parent window titled `通所・訪問リハビリ管理システム SP(ケア記録) [施設名]` with child windows. Standard WinForms controls: Button, ComboBox, CheckBox, RadioButton, DataGrid (with colored cells for abnormal values). See `docs/wiseman-system-spec.md` for full control tree and selector details.
