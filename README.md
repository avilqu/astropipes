# Astropipes

Astropipes manages and processes astronomical images (FITS files), with a focus on asteroid follow-up. It has three parts:

- **The Library** (`astropipes -G`): a database of your light frames and calibration masters, browsable by target, date and observing run, with batch operations such as session stacks, region-of-interest views and archiving.
- **The FITS viewer** (`astropipes-viewer`): blink sequences, plate-solve, calibrate, align and stack them, overlay catalog objects, stack on a moving object's ephemeris and measure its positions for MPC reports.
- **The command line** (`astropipes`): scanning, plate solving, calibration, calibration masters, alignment and integration.

## Requirements

- Linux. The installer and the application launchers target a Linux desktop.
- Python 3.14. The versions pinned in `requirements.txt` have been tested with it.
- For plate solving: a local [Astrometry.net](https://astrometry.net/) engine (`solve-field`) with its index files, which can take over 50 GB. Without it, everything except plate solving works.
- An internet connection for the online services: SIMBAD, Gaia and SkyBoT searches, Find_Orb ephemerides, NEOfixer (NEOCP objects and observations) and the MPC observatory code lookup.

## Installation

```bash
./install.sh
```

The script checks for Python 3.14 and creates a virtual environment in `.venv`. It then installs the dependencies from `requirements.txt` and installs astropipes itself in editable mode. It links the `astropipes` and `astropipes-viewer` commands into `~/bin` (or `~/.local/bin` if `~/bin` doesn't exist), so they can be run from anywhere. Finally, it adds **Astropipes Library** and **Astropipes Viewer** entries to the application launcher, in `~/.local/share/applications`. It also installs the `astropipes-watch` systemd user service for [automatic processing](#automatic-processing), without enabling it.

To do the same by hand:

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install --no-deps -e .
ln -s "$PWD/.venv/bin/astropipes" ~/bin/astropipes                 # optional: run from anywhere
ln -s "$PWD/.venv/bin/astropipes-viewer" ~/bin/astropipes-viewer
```

The commands start the venv's Python by its full path, so the links work without activating the venv.

`pip install -e .` creates the `astropipes` and `astropipes-viewer` commands in `.venv/bin` and makes `import astropipes` point at this repository. Code changes take effect without reinstalling. Re-run it only when `pyproject.toml` changes.

## Configuration

Settings are stored in `~/.config/astropipes/config.toml`, or in the file named by the `ASTROPIPES_CONFIG` environment variable. The easiest way to edit them is the Library's **File → Settings** dialog. The file only lists the values that differ from the defaults in `astropipes/config/defaults.py`; the paths are always written. `astropipes --config` prints the settings file location and the main paths.

| Setting | Used for |
|---|---|
| `DATA_PATH` | Light frames, organised as `<DATA_PATH>/<Target>/<Filter>/*.fits` |
| `CALIBRATION_PATH` | Calibration masters (scanned recursively, and written here by `astropipes -M`) |
| `STACKS_PATH` | Session stacks and region-of-interest views, in `<STACKS_PATH>/<Target>/` |
| `ARCHIVE_PATH` | Where archived targets are moved |
| `PROCESSED_PATH` | Work folders for intermediate and output files (see below) |
| `DATABASE_PATH` | The library database (SQLite) |
| `OBS_CODE`, `OBS_LON`, `OBS_LAT` | MPC observatory code and site coordinates. The code is used for Find_Orb ephemerides, the NEOCP list and MPC reports. The Settings dialog can look up the coordinates from the code. |

The other tabs of the Settings dialog cover:
- **General:** time display in UTC or local time, blink period, automatic folder watching.
- **Alignment:** default and fallback method, memory limits and chunk sizes.
- **Integration:** sigma clipping and motion-tracking options.
- **Calibration:** the maximum age of masters, in days.

Settings marked with `*` take effect after a restart.

### Work folders

Everything written under `PROCESSED_PATH` is generated and can be recreated:

| Folder | Contents |
|---|---|
| `solved/` | Temporary plate-solving files |
| `calibrated/` | Calibrated frames (`b_`, `d_`, `f_` prefixes for the bias, dark and flat steps applied) |
| `aligned/` | Aligned frames |
| `integrated/` | CLI integrations and the Library's per-filter masters |
| `stacked/` | Motion-tracked stacks from the viewer |
| `substacks/` | Motion-tracked substacks |
| `daily_stacks/` | Daily stacks from the Library |
| `session_stacks_work/` | Aligned frames used for session stacks |
| `regions/` | Output of **Latest regions update**, and one `<YYYY-MM-DD>/` folder per night from automatic processing |

**Database → Cleanup temp directories** in the Library empties `solved`, `calibrated`, `stacked`, `aligned`, `substacks` and `session_stacks_work`.

## The Library

Open it with `astropipes -G` or the **Astropipes Library** launcher.

### Getting files in

- **Database → Scan for new files** imports new light frames from `DATA_PATH` and calibration masters from `CALIBRATION_PATH`.
  - Light frames must be in `<Target>/<Filter>/` folders.
  - The target name comes from the `OBJECT` header, with underscores shown as spaces.
  - Calibration masters are recognised from their `FRAME` or `IMAGETYP` header, or their file name.
- When folder watching is enabled in Settings, both folders are watched and new files are scanned automatically.
- **Database → Refresh database** reloads the view.

The command-line equivalents are `astropipes --scan`, `--scan-calibration` and `--scan-all`.

### Sidebar

| Entry | Shows |
|---|---|
| Obs log → Runs | All light frames, grouped into observing runs (frames of the same target less than 30 minutes apart). Runs can be expanded and carry a comment and badges. |
| Obs log → MPC Log | Observations recorded for MPC reporting |
| Targets | One entry per target, with its frame count |
| Dates | Frames per observing date |
| Stacks | Session stacks of the targets flagged for follow-up |
| Regions | Regions of interest, with the number of stacks that contain each one |
| Calibration | Master bias, dark and flat tables |

### Right-click actions

- **A file:** Show in FITS viewer, Calibrate and compare (opens the raw and calibrated frames together in the viewer, to blink between them), Platesolve image, Show header, Delete file.
- **Several selected files:** Load files in FITS viewer, Platesolve all images, Delete selected files.
- **A run in the observation log:** Edit comment, Add to MPC log (also adds an MPC badge to the run), Clear Badges.
- **A target in the sidebar:**
  - **Load all files in FITS Viewer.**
  - **Rename target:** renames the target's folders under `DATA_PATH` and `STACKS_PATH`, updates the database (files, regions, follow-up flags) and rewrites the `OBJECT` header of its files.
  - **Generate masters:** calibrates and aligns all of the target's frames, then integrates one image per filter into `PROCESSED_PATH/integrated/<Target>/`.
  - **Generate daily stacks:** after you pick a filter, stacks each observing night separately into `PROCESSED_PATH/daily_stacks/<Target>/` and opens the results in the viewer. It needs at least two nights.
  - **Flag for follow-up (session stacks)… / Remove follow-up flag:** chooses which filters get session stacks.
  - **Add to MPC log.**
  - **Move to archive:** moves the light frames to `ARCHIVE_PATH`, keeping their folders, and deletes the target's session stacks. It removes the target from the database and deletes its empty folders.
- **A date:** Load all files in FITS Viewer.
- **A region:** Rename region… (moves its PNG views too), Delete region….

### Actions menu

- **Generate session stacks:** for every target flagged for follow-up, stacks each observing night in each flagged filter into `STACKS_PATH/<Target>/stack_<Target>_<Filter>_<YYYYMMDD>.fits`.
  - All stacks of a target are aligned to the same reference frame, recorded in the `ALIGNREF` header, so they line up across nights and filters.
  - Existing stacks are skipped.
  - New stacks are added to the library and plate-solved.
- **Generate all Region of interest views:** crops every region of interest from every session stack that contains it. The PNGs go to `STACKS_PATH/<Target>/views/<Region>/` and show up in the region's detail view.
- **Latest regions update:** for the most recent observing session, copies the oldest (`-REF`) and newest (`-NEW`) view of each region into `PROCESSED_PATH/regions/`, for quick comparison.

## The FITS viewer

Open it with `astropipes-viewer [files...]`, the **Astropipes Viewer** launcher (which also opens FITS files from a file manager), or from the Library.

### Toolbar

- **Files:** previous/next file and a slideshow ("blink") button. Also open, close and delete the current file, the loaded-files list, and the FITS header.
- **Monitor mode:** watches `DATA_PATH` and adds new FITS files as they arrive.
- **Zoom:** zoom 1:1, zoom to fit, and zoom to a rectangle you draw.
- **Display:** linear or logarithmic stretch, a brightness slider, and sigma clipping of the display range.
- **SIMBAD:** search for an object, or find the deep-sky objects in the field.
- **Sources:** load the Gaia catalog for the field, detect sources, or detect and match Gaia stars in the image.
- **Solar System Objects:** find known objects in the field (SkyBoT), or **Get orbital elements** (Find_Orb ephemerides for the loaded frames).
- **Calibrate / Platesolve:** apply to this image or to all loaded images.
- **Align:** align all loaded images with astroalign or by WCS reprojection.
- **Integration:** **Stack on ephemeris** (motion-tracked stack).
- **Regions of interest:** define a new region by drawing a rectangle, or show the regions in the field.
- **Overlay toolbar:** shows or hides each overlay (ephemeris markers, solar system objects, sources, SIMBAD objects, Gaia stars, matched Gaia stars, regions).

Hovering over the image shows the RA/Dec (on plate-solved images) and the pixel value. Keyboard: `+`/`=` zoom in, `-` zoom out, `0` resets the zoom, `O` opens a file.

### Measuring an asteroid

1. Load the frames of the sequence and plate-solve them.
2. **Solar System Objects → Get orbital elements**, and enter the object's designation. Find_Orb returns the predicted position at each frame's mid-exposure time. They're shown in an orbit window (Ephemerides and Pseudo MPEC tabs) and as markers on the images.
3. **Integration → Stack on ephemeris** builds a motion-tracked stack in which the object stays still: a median and an average stack by default, `<name>_median.fits` and `<name>_average.fits`.
4. With the Gaia catalog loaded (**Sources → Load Gaia catalog**), right-click the object in the stack and choose **Compute object positions**.
   - After you refine the click position, the object's position in each frame is added to the orbit window.
   - It includes a least-squares plate constants (LSPC) solution fitted on the Gaia stars.
5. **Generate Substacks** splits the frames into three consecutive groups and stacks each on the object, marking its expected position.
6. **Measure object positions** measures the object on the substacks (Measurements tab), and **Generate MPC Report** formats the observations for submission.

## Command line

```bash
astropipes --help
```

| Command | What it does |
|---|---|
| `-G`, `--gui` | Open the Library |
| `--config` | Print the settings file location and the main paths |
| `--scan`, `--scan-calibration`, `--scan-all` | Import new light frames, calibration masters, or both into the library |
| `-S`, `--solve FILES` | Plate-solve with `solve-field` and write the WCS into the files. Library records are updated. |
| `-C`, `--calibrate FILES` | Calibrate with the best matching masters from the library, into `PROCESSED_PATH/calibrated/` |
| `-M`, `--masters {bias,dark,flat} FILES` | Build a calibration master from the given frames, into `CALIBRATION_PATH` |
| `-A`, `--align FILES` | Align to the first file with the default method, into `PROCESSED_PATH/aligned/` |
| `-I`, `--integrate FILES` | Stack aligned frames into `PROCESSED_PATH/integrated/`, named `integration_<Filter>.fits` when all frames share a filter. Options: `--integration-method {average,median,sum}`, `--sigma-clip`. |
| `--get-neocp-objects` | List the objects currently on the NEOCP (via NEOfixer) |
| `--watch` | Automatic processing of each finished run (see below) |
| `--process-latest-run TARGET` | Stack the latest run of a follow-up target now, with its region views, as `--watch` does |
| `--get-obs NEOCP_DESIGNATION` | Print the observations of a NEOCP object (via NEOfixer), in MPC 80-column format |

Examples:

```bash
astropipes -M dark darks/*.fits
astropipes -C L/*.fits
astropipes -A calibrated/*.fits
astropipes -I aligned/*.fits --integration-method median --sigma-clip
```

`python -m astropipes` is equivalent to `astropipes`.

## Automatic processing

`astropipes --watch` processes each observing run as soon as it ends, while the next run is being captured. It is meant to run all the time on the observatory computer.

- Every `AUTOPROCESS_POLL_SECONDS` (30 s), it imports the new light frames in `DATA_PATH`. Files modified in the last `AUTOPROCESS_FILE_SETTLE_SECONDS` (10 s) are left for the next poll, so frames still being written are not read.
- A run is a series of frames of the same target less than 30 minutes apart, as in the observation log. It ends when a frame of another target arrives, or when no frame of the target has been written for `AUTOPROCESS_RUN_IDLE_MINUTES` (30 min), which covers the last run of the night.
- Only runs of targets flagged for follow-up are processed, one at a time:
  - one stack per flagged filter in the run, aligned like the session stacks (`ALIGNREF`), into `STACKS_PATH/<Target>/stack_<Target>_<Filter>_<YYYYMMDD>.fits`. Later runs of the same night get `_2`, `_3`…;
  - the stacks are added to the library and plate-solved;
  - the target's region views are generated;
  - the oldest (`-REF`) and newest (`-NEW`) view of each region in the new stacks are copied into `PROCESSED_PATH/regions/<YYYY-MM-DD>/`, replacing the previous copies of that night.
- Processed runs are recorded in `PROCESSED_PATH/autoprocess_state.json`. At startup, the watcher processes the runs it missed, as long as they were written in the last `AUTOPROCESS_RECOVERY_HOURS` (36 h). The first time it starts, everything already in the library counts as processed.
- Only one watcher runs at a time (lock file `PROCESSED_PATH/autoprocess.lock`).

The Library can stay open meanwhile. Turn its folder watching off on that computer so only the watcher imports frames. Frames of several targets interleaved (A, B, A, B…) make one run per frame, so capture each target in one block.

`install.sh` installs it as the systemd user service `astropipes-watch`, but doesn't enable it. To run it on the observatory computer:

```bash
systemctl --user enable --now astropipes-watch   # start now and at login
loginctl enable-linger $USER                     # keep it running without a login session
journalctl --user -u astropipes-watch -f         # follow its log
```

To use a settings file other than the default, uncomment the `ASTROPIPES_CONFIG` line with `systemctl --user edit --full astropipes-watch`.

## Calibration

Calibration uses the masters in the library, so scan `CALIBRATION_PATH` after adding masters. For each light frame:

- **Bias and dark:** same binning, gain and offset, and a CCD temperature within ±2 °C. The dark's exposure must be at least the frame's, and it is scaled to the frame's exposure time.
- **Flat:** same binning and filter, taken on or before the frame's date.
- **Age limits:** `MAX_BIAS_AGE`, `MAX_DARK_AGE` and `MAX_FLAT_AGE` limit how old a master may be, in days; 0 means no limit.

Matching doesn't use any camera or telescope identifier, so keep one rig's masters per `CALIBRATION_PATH`.

## Known issues

- **Integration → Stack aligned images** in the viewer is not implemented and does nothing.
- `-G` accepts a FITS file argument (`[FITS_FILE]` in `--help`) but ignores it.
- The **Downsample factor** and **Search radius** settings are not used. Plate solving always uses a downsample of 2 and, when the image has coordinates, a 15° search radius, which happen to equal the defaults.
- Alignment with astroalign isn't reproducible: its random sampling isn't seeded, so repeated runs can give slightly different results.

## Development

Setting `ASTROPIPES_DEBUG=1` prints astropipes' debug log messages to stderr; logging is off otherwise. `ASTROPIPES_CONFIG=/path/to/config.toml` selects another settings file, which is useful for testing against a scratch library.

### Code layout

```
astropipes/
├── config/        settings: defaults.py + the user TOML file (`from astropipes.config import settings`)
├── core/          paths and work folders, naming, time display, memory, console/log helpers
├── fits/          FITS headers, metadata parsing (DATE-OBS, binning), sequence checks, WCS
├── db/            SQLAlchemy models, engine and migrations, repository (DatabaseManager), library scanner
├── processing/    calibration, calibration masters, alignment, integration, motion tracking, display stretch
├── astrometry/    plate solving, catalogs (SIMBAD/Gaia/SkyBoT), source detection, LSPC, orbits, MPC reports
├── regions/       region-of-interest geometry and PNG views
├── workflows/     multi-step jobs combining files and the database: stacking, sessions, archive/rename,
│                  region views, substacks, ephemerides, single-file library operations,
│                  automatic run processing (autoprocess.py, `astropipes --watch`)
├── cli/           the `astropipes` command
└── gui/
    ├── common/    app setup, JobThread, viewer launcher, console/header windows, shared dialogs and result tables
    ├── library/   the Library window (app.py): widgets/, dialogs/, background threads, folder watcher
    └── viewer/    the FITS viewer (app.py): image widget, overlays, mixins/, toolbars/, orbit/ windows

share/
├── applications/  .desktop launchers (paths filled in by install.sh)
├── systemd/       user service for `astropipes --watch` (installed by install.sh, not enabled)
└── icons/         application icon
```

Layers only import from the layers below them:

```
cli, gui  →  workflows  →  processing, astrometry, regions  →  fits, db  →  core, config
```

Two parts of the code use a module at the same level:
- `db/scan.py` (the library scanner) reads FITS headers through `fits/`.
- In `processing/`, calibration looks up calibration masters in `db/`, and master generation registers new ones there.

Nothing outside `gui/` imports Qt. Operations that move, rename or delete library files together with their database records live in `workflows/`. Long-running work is written as a function taking `log(text)` and `should_cancel()` callables. `gui.common.jobs.JobThread` runs these in the background, and the CLI can call them directly.
