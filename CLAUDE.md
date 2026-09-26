# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Astropipes is a personal astronomical image-reduction toolkit (calibration, platesolving, alignment, stacking, asteroid/NEO follow-up and MPC reporting) with a PyQt6 GUI built around a SQLite library of FITS files. Python 3.14, dependencies pinned in `requirements.txt`, venv in `.venv/`.

## Commands

```bash
./install.sh                      # create .venv, install requirements, install .desktop files
source .venv/bin/activate

python astropipes.py --help       # CLI entry point (./astropipes is a wrapper that picks the .venv python)
python astropipes.py -G           # Library GUI (lib/gui/library/index.py → AstroLibraryGUI)
python -m lib.gui.viewer.index some.fits   # standalone FITS viewer (run from repo root)
python astropipes.py --scan-all   # import DATA_PATH images + CALIBRATION_PATH masters into the DB
python astropipes.py -S/-C/-A/-I file.fits ...   # solve / calibrate / align / integrate
python astropipes.py -M dark files...            # build a calibration master
```

There is no test suite, linter, or build step. Verify changes by running the CLI or GUI against real data.

## Configuration

`config.py` is a plain module of constants imported everywhere as `import config`. It holds absolute, machine-specific paths (`DATA_PATH`, `CALIBRATION_PATH`, `STACKS_PATH`, `DATABASE_PATH`, …), observatory code/location, solver/alignment/integration tuning, and calibration-master matching constraints. It also defines path helpers (`stacks_path_for_target`, `views_path_for_target`, `is_session_stack_fits_file`, …) that decide where outputs go and how session stacks are recognized. Use these helpers rather than building paths by hand.

## Architecture

- `astropipes.py`: argparse CLI; each flag dispatches to a local function that calls into `lib/`.
- `lib/db/`: SQLAlchemy models (`models.py`: `FitsFile`, `Source`, `CalibrationMaster`, `Run`, `FollowUpFilter`, `MPCLog`, `RegionOfInterest`, `RegionView`) and `DatabaseManager` (`manager.py`, accessed via the `get_db_manager()` singleton). Schema changes need **both** a model change and a hand-written step in `DatabaseManager._migrate_database()` (inspect columns, `ALTER TABLE`), because existing DBs are migrated in place; `create_all` only creates missing tables. `scan.py` reads FITS headers into the DB and groups files into `Run`s (same target, close in time). The full header is stored as JSON in `FitsFile.header_json`.
- `lib/fits/`: image processing on files: calibration (`CalibrationManager` picks masters by `*_CONSTRAINTS` in config and scales darks by exposure), `masters.py`, `align.py` (astroalign with WCS-reprojection fallback, chunked for memory), `integration.py` (standard and motion-tracking/ephemeris stacking), `wcs.py`, display stretch, and region-of-interest views/exports.
- `lib/sci/`: science and external services: `platesolving.py` (wraps local Astrometry.Net `solve-field`, online fallback), `sources.py` (photutils detection and HFR), `catalogs.py` (SIMBAD, Gaia, Skybot), `orbit.py` (NEOfixer, NEOCP, Find_Orb ephemerides), `mpc.py` (MPC 80-column report formatting).
- `lib/gui/library/`: main Library window (`index.py`) with the file table, sidebar, obslog, calibration tables, and region views. Long operations each have their own `QThread` subclass in a `*_thread.py` file (platesolving, calibration, masters, daily/session stacks, region views), which reports back through `pyqtSignal`s. Follow that pattern for new background work. `data_folder_watcher.py` watches the data folders and triggers rescans.
- `lib/gui/viewer/`: FITS viewer. The Library opens it as a **separate process** (`python -m lib.gui.viewer.index <files>`), so the viewer must stay runnable on its own. Features are split into modules: overlay, sources, catalogs, orbital_elements, integration, region_of_interest, and so on.
- `lib/gui/common/`: dialogs and result windows shared by both GUIs.
- `lib/legacy/`: the old pre-refactor code (old GUI, `Calibrator`, `FITSSequence`, solver). Don't extend it.

## Gotchas

- Imports assume the repo root is on `sys.path` (`from lib.db import ...`, `import config`). Run from the repo root, or use `python -m`.
- `autopipe.py` still imports `lib.class_calibrator`, `lib.solver`, and `lib.helpers`, which have moved to `lib/legacy/`, so it is currently broken.
- `README.md` is partly outdated: it references `astro-pipelines.py`, `lib/gui_pyqt.py`, `TIMEOUT_FEATURES.md`, and `INTEGRATION_USAGE.md`, none of which exist.
- Platesolving needs Astrometry.Net `solve-field` and its index files installed locally. Catalog, orbit, and MPC features need network access.
