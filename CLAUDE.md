# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Astropipes is a PyQt6 desktop app and CLI for managing and processing astronomical FITS images, focused on asteroid follow-up. It has three entry points: the **Library** (`astropipes -G`, a SQLite-backed browser of light frames and calibration masters), the **FITS viewer** (`astropipes-viewer`), and the **CLI** (`astropipes`). `README.md` is the user manual and describes every feature, setting and work folder in detail.

## Commands

The project runs from a Python 3.14 venv in `.venv`, with astropipes installed in editable mode (`./install.sh` sets it all up). Code changes take effect without reinstalling; re-run `.venv/bin/pip install --no-deps -e .` only when `pyproject.toml` changes. Dependencies are pinned in `requirements.txt`, which `pyproject.toml` reads as its dependency list.

```bash
.venv/bin/astropipes --help                    # CLI (same as .venv/bin/python -m astropipes)
.venv/bin/astropipes -G                        # Library GUI
.venv/bin/astropipes-viewer file.fits ...      # FITS viewer (also python -m astropipes.gui.viewer)
.venv/bin/python -m astropipes.gui.library     # Library GUI directly
.venv/bin/astropipes --config                  # print settings file location and main paths
```

There is no test suite, linter or formatter config. To check a change without touching the real library, point the app at a scratch settings file (with its own `DATABASE_PATH` and data paths), and turn on debug logging:

```bash
ASTROPIPES_CONFIG=/path/to/scratch.toml ASTROPIPES_DEBUG=1 .venv/bin/astropipes --scan-all
```

Plate solving needs a local Astrometry.net `solve-field`; SIMBAD, Gaia, SkyBoT, Find_Orb, NEOfixer and the MPC lookup need network access.

## Architecture

The package lives in `astropipes/`, and its layers only import from the layers below them:

```
cli, gui  →  workflows  →  processing, astrometry, regions  →  fits, db  →  core, config
```

Two same-level exceptions: `db/scan.py` reads headers through `fits/`, and in `processing/` calibration looks up masters in `db/` and master generation registers new ones there.

- **Nothing outside `gui/` imports Qt.** Keep processing, astrometry and workflow code GUI-free so the CLI can call it.
- **Long-running jobs** are plain functions taking `log(text)` and `should_cancel()` callables and returning a result dict (`{'success': ..., ...}`). The GUI runs them through `gui/common/jobs.py:JobThread`, which emits `output`/`finished` signals and can redirect stdout (`capture_stdout=True`) for lower layers that `print` progress. The CLI calls the same functions directly.
- **`workflows/`** owns every operation that changes library files and their database records together (archive, rename, session stacks, region views, substacks). `db/repository.py` (`DatabaseManager`, shared instance via `get_db_manager()`) only does database queries and updates, never filesystem changes.
- **Settings**: `from astropipes.config import settings`, then read `settings.X` at call time rather than caching it at import, because `settings.reload()` (after the Settings dialog saves) must take effect everywhere. Defaults are the uppercase names in `config/defaults.py`; the user TOML file (`~/.config/astropipes/config.toml` or `$ASTROPIPES_CONFIG`) only stores values that differ from the defaults, plus the `PATH_KEYS`, which are always written. Adding a setting means adding it to `defaults.py`, since unknown keys in the TOML file are ignored with a warning. A legacy root `config.py` is imported once if no TOML file exists.
- **Database schema changes**: there is no migration framework. `db/engine.py:migrate_database()` inspects the existing SQLite schema and adds missing tables and columns with `ALTER TABLE`, so a new model column needs a matching step there for existing databases.
- **FITS viewer**: `gui/viewer/app.py:FITSViewer` is a `QMainWindow` assembled from mixins in `gui/viewer/mixins/` (files, navigation, display, catalogs, sources, integration, regions, monitor…) plus `overlays.py`. The toolbars live in `gui/viewer/toolbars/` and the orbit and MPC windows in `gui/viewer/orbit/`. Feature code usually belongs in the matching mixin. The Library opens the viewer as a separate process (`gui/common/launcher.py`).
- **Library GUI**: `gui/library/app.py` is the main window, with `widgets/`, `dialogs/`, background `threads.py` and a folder `watcher.py`.
- **Data layout conventions**: light frames sit in `<DATA_PATH>/<Target>/<Filter>/*.fits`, and the target name comes from the `OBJECT` header. Generated files go under `PROCESSED_PATH` subfolders, while session stacks and region views go under `STACKS_PATH/<Target>/`. See the README's tables before changing where outputs are written.

`.claude/worktrees/` holds old checkouts from before the move to the `astropipes/` package layout (with root-level `astropipes.py`, `config.py`, `lib/`). Ignore them when searching the code.
