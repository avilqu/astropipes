"""
Automatic processing of observing runs (astropipes --watch).

The watcher polls DATA_PATH, imports new light frames and follows the current run of each target
(see sessions.split_into_runs). A run is finished when a frame of another target arrives, or when
no frame of its target has been written for AUTOPROCESS_RUN_IDLE_MINUTES. Finished runs of
follow-up targets are processed one at a time in a worker thread while polling goes on: one stack
per flagged filter (registered and plate-solved), the region views, and the REF / NEW pair of
each region in PROCESSED_PATH/regions/<YYYY-MM-DD>/.

Processed runs are recorded in PROCESSED_PATH/autoprocess_state.json, keyed by their first frame,
so that a restarted watcher processes the runs it missed exactly once.
"""

import json
import os
import queue
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: no single-instance lock
    fcntl = None

from astropipes.config import settings
from astropipes.core import paths
from astropipes.core.log import log_banner
from astropipes.db import get_db_manager
from astropipes.db.scan import FitsFileScanner
from astropipes.workflows.regions import update_region_views_for_new_stacks
from astropipes.workflows.sessions import (
    RUN_TIME_WINDOW_MINUTES,
    group_files_by_session,
    norm_path,
    resolve_alignment_reference_raw,
    split_into_runs,
)
from astropipes.workflows.stacking import files_matching_filter, stack_register_solve

STATE_FILENAME = "autoprocess_state.json"
LOCK_FILENAME = "autoprocess.lock"


def _by_date(files):
    return sorted([f for f in files if f.date_obs], key=lambda f: f.date_obs)


def _light_frames(files):
    return [f for f in files if not paths.is_session_stack_fits_file(f)]


def run_key(run_files) -> str:
    """Identifies a run in the state file: the path of its first frame."""
    return norm_path(_by_date(run_files)[0].path)


def _night_start(first_date, files):
    """Start of the observing night (12 h session) of files that contains first_date."""
    for session in group_files_by_session(files):
        if session[0].date_obs <= first_date <= session[-1].date_obs:
            return session[0].date_obs
    return first_date


def run_stack_filename(target, filter_name, run_files, filter_files, taken_paths) -> str:
    """
    stack_<target>_<filter>_<YYYYMMDD>.fits, then _2, _3… for later runs of the same night.
    The date is the start of the night, as for the Library's session stacks.
    """
    night = _night_start(_by_date(run_files)[0].date_obs, filter_files)
    base = f"stack_{target}_{filter_name}_{night:%Y%m%d}"
    out_dir = paths.stacks_path_for_target(target)
    taken = {norm_path(p) for p in taken_paths}
    n = 1
    while True:
        name = f"{base}.fits" if n == 1 else f"{base}_{n}.fits"
        candidate = out_dir / name
        if not candidate.exists() and norm_path(str(candidate)) not in taken:
            return name
        n += 1


def process_run(target, run_files, log, should_cancel) -> dict:
    """
    Stack one finished run of a follow-up target: one stack per flagged filter in the run,
    registered and plate-solved, then the target's region views and the REF / NEW export.
    """
    db = get_db_manager()
    filter_names = db.follow_up_get_filters(target)
    if not filter_names:
        return {"success": False, "error": f"{target} is not flagged for follow-up."}

    files_all = db.get_files_by_target(target)
    raw_files = _light_frames(files_all)
    existing_stack_paths = {
        f.path for f in files_all if f.path and paths.is_session_stack_fits_file(f)
    }
    align_ref = resolve_alignment_reference_raw(raw_files, existing_stack_paths=existing_stack_paths)
    night = _night_start(_by_date(run_files)[0].date_obs, raw_files)

    results = {"success": True, "target": target, "stack_paths": [], "errors": []}
    for fn in filter_names:
        if should_cancel():
            break
        subset = files_matching_filter(run_files, fn)
        if not subset:
            continue
        name = run_stack_filename(
            target, fn, subset, files_matching_filter(raw_files, fn), existing_stack_paths
        )
        res = stack_register_solve(
            target, subset, fn, log, should_cancel,
            existing_stack_paths=existing_stack_paths,
            alignment_reference_raw_path=align_ref,
            stack_filename=name,
        )
        results["errors"].extend(res.get("errors", []))
        results["stack_paths"].extend(res.get("stack_paths", []))
        align_ref = res.get("alignment_reference_raw_path") or align_ref

    if should_cancel():
        return {**results, "success": False, "cancelled": True}
    if not results["stack_paths"]:
        flagged = ", ".join(filter_names)
        return {**results, "success": False, "error": f"No stack generated (flagged filters: {flagged})."}

    dest_dir = Path(paths.work_dir("regions", f"{night:%Y-%m-%d}"))
    log_banner(log, f"Region views: {target}")
    regions = update_region_views_for_new_stacks(
        target, results["stack_paths"], dest_dir, log, should_cancel
    )
    results["errors"].extend(regions["errors"])
    results["views_generated"] = regions["generated"]
    results["views_exported"] = regions["exported"]
    results["regions_dir"] = str(dest_dir)
    return results


# --- State file ---

class _State:
    """Processed runs, persisted in PROCESSED_PATH/autoprocess_state.json.

    'since': runs whose first frame is not later than this date_obs were in the library when
    the watcher first started, and count as processed.
    """

    def __init__(self):
        self.path = Path(paths.work_dir(STATE_FILENAME))
        self.lock = threading.Lock()
        self.since = None
        self.runs = {}
        if self.path.is_file():
            data = json.loads(self.path.read_text())
            since = data.get("since")
            self.since = datetime.fromisoformat(since) if since else None
            self.runs = data.get("runs", {})

    def initialize(self, light_frames) -> bool:
        """On first use (no state file), count the library's light frames (sorted by date_obs)
        as processed. Returns True if the state file was created."""
        if self.path.is_file():
            return False
        self.since = light_frames[-1].date_obs if light_frames else None
        self.save()
        return True

    def is_processed(self, run_files):
        first = _by_date(run_files)[0]
        if self.since and first.date_obs <= self.since:
            return True
        with self.lock:
            return run_key(run_files) in self.runs

    def record(self, run_files, target, result):
        info = {
            "target": target,
            "frames": len(run_files),
            "processed_at": datetime.now().isoformat(timespec="seconds"),
            "success": bool(result.get("success")),
            "stacks": [os.path.basename(p) for p in result.get("stack_paths", [])],
        }
        if result.get("error"):
            info["error"] = str(result["error"])
        with self.lock:
            self.runs[run_key(run_files)] = info
            self._prune()
            self.save()

    def _prune(self):
        """Forget runs processed long before the recovery window."""
        cutoff = time.time() - 2 * settings.AUTOPROCESS_RECOVERY_HOURS * 3600
        self.runs = {
            k: v for k, v in self.runs.items()
            if datetime.fromisoformat(v["processed_at"]).timestamp() >= cutoff
        }

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"since": self.since.isoformat() if self.since else None, "runs": self.runs}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(self.path)


def _acquire_lock():
    """Lock file held while a watcher runs. Returns its handle, or None if another watcher holds it."""
    lock_path = Path(paths.work_dir(LOCK_FILENAME))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "w")
    if fcntl:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return None
    return handle


# --- Watcher ---

def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


class RunTracker:
    """The open run of each target, fed with new frames in date_obs order.

    Each frame comes with the time it was written (file mtime), used for the idle timeout.
    """

    def __init__(self, window_minutes=RUN_TIME_WINDOW_MINUTES):
        self.window_minutes = window_minutes
        self.open = {}  # target -> {'files': [...], 'last_seen': timestamp}

    def add(self, files, seen_at) -> list:
        """Add frames (seen_at: path -> timestamp). Returns the runs closed, as (target, files)."""
        closed = []
        for f in _by_date(files):
            for target in list(self.open):
                if target != f.target:
                    closed.append((target, self.open.pop(target)["files"]))
            run = self.open.get(f.target)
            if run and len(split_into_runs([run["files"][-1], f], self.window_minutes)) > 1:
                closed.append((f.target, self.open.pop(f.target)["files"]))
                run = None
            if run is None:
                run = self.open[f.target] = {"files": [], "last_seen": 0.0}
            run["files"].append(f)
            run["last_seen"] = max(run["last_seen"], seen_at.get(f.path, time.time()))
        return closed

    def close_idle(self, now, idle_seconds) -> list:
        closed = []
        for target in list(self.open):
            if now - self.open[target]["last_seen"] >= idle_seconds:
                closed.append((target, self.open.pop(target)["files"]))
        return closed


def _stamp(text):
    return f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}"


def watch(log, should_cancel) -> dict:
    """
    Poll DATA_PATH until should_cancel() returns True, importing new light frames and processing
    each finished run of a follow-up target (see the module docstring).
    """
    lock = _acquire_lock()
    if lock is None:
        return {"success": False, "error": "Another watcher is already running."}

    db = get_db_manager()
    state = _State()
    all_files = db.get_all_fits_files()
    light_frames = _by_date(_light_frames(all_files))
    if state.initialize(light_frames):
        log(_stamp(f"First start, state file created: {state.path}\n"))

    known_paths = {f.path for f in all_files if f.path}
    jobs = queue.Queue()
    tracker = RunTracker()
    summary = {"success": True, "runs_processed": 0, "runs_failed": 0}

    def enqueue(target, run_files, quiet=False):
        if state.is_processed(run_files):
            return
        ages = [time.time() - _mtime(f.path) for f in run_files]
        if min(ages) > settings.AUTOPROCESS_RECOVERY_HOURS * 3600:
            return
        frames = f"{len(run_files)} frame(s)"
        if not db.follow_up_is_flagged(target):
            if not quiet:
                    log(_stamp(f"Run finished: {target}, {frames} (not flagged for follow-up)\n"))
            return
        log(_stamp(f"Run finished: {target}, {frames}, queued for processing\n"))
        jobs.put((target, run_files))

    def worker():
        while True:
            item = jobs.get()
            if item is None:
                return
            if should_cancel():
                continue
            target, run_files = item
            log_banner(log, _stamp(f"Processing run: {target} ({len(run_files)} frames)"))
            try:
                result = process_run(target, run_files, log, should_cancel)
            except Exception as e:
                log(traceback.format_exc())
                result = {"success": False, "error": str(e)}
            if result.get("cancelled"):
                continue
            state.record(run_files, target, result)
            if result.get("success"):
                summary["runs_processed"] += 1
                stacks = ", ".join(os.path.basename(p) for p in result["stack_paths"])
                log(_stamp(
                    f"✓ {target}: {stacks}; {result.get('views_exported', 0)} region PNG(s) in "
                    f"{result.get('regions_dir')}\n"
                ))
            else:
                summary["runs_failed"] += 1
                log(_stamp(f"✗ {target}: {result.get('error', 'failed')}\n"))
            for err in result.get("errors", []):
                log(f"    {err}\n")

    worker_thread = threading.Thread(target=worker, name="autoprocess-worker", daemon=True)
    worker_thread.start()

    # Runs missed while the watcher was stopped. The last one may still be going on, so it goes
    # to the tracker, which closes it once idle.
    if state.since is not None:
        missed = [f for f in light_frames if f.date_obs > state.since]
    else:
        missed = light_frames
    runs = split_into_runs(missed)
    for i, run_files in enumerate(runs):
        if i == len(runs) - 1:
            tracker.add(run_files, {f.path: _mtime(f.path) for f in run_files})
        else:
            enqueue(run_files[0].target, run_files, quiet=True)

    log(_stamp(f"Watching {settings.DATA_PATH} (every {settings.AUTOPROCESS_POLL_SECONDS} s)\n"))
    scanner = FitsFileScanner()
    failed_paths = set()
    while not should_cancel():
        now = time.time()
        new_frames = []
        seen_at = {}
        for fits_path in sorted(Path(settings.DATA_PATH).glob("*/*/*.fits")):
            path = str(fits_path)
            if path in known_paths:
                continue
            mtime = _mtime(path)
            if now - mtime < settings.AUTOPROCESS_FILE_SETTLE_SECONDS:
                continue
            try:
                if scanner.import_file(fits_path):
                    log(_stamp(f"Imported {fits_path.parent.parent.name}/{fits_path.parent.name}/{fits_path.name}\n"))
                record = db.get_fits_file_by_path(path)
            except Exception as e:
                if path not in failed_paths:
                    failed_paths.add(path)
                    log(_stamp(f"✗ Could not import {path}: {e} (will retry)\n"))
                continue
            known_paths.add(path)
            failed_paths.discard(path)
            if record and record.date_obs and not paths.is_session_stack_fits_file(record):
                new_frames.append(record)
                seen_at[path] = mtime

        idle_seconds = settings.AUTOPROCESS_RUN_IDLE_MINUTES * 60
        for target, run_files in tracker.add(new_frames, seen_at) + tracker.close_idle(now, idle_seconds):
            enqueue(target, run_files)

        deadline = time.time() + settings.AUTOPROCESS_POLL_SECONDS
        while time.time() < deadline and not should_cancel():
            time.sleep(0.5)

    log(_stamp("Stopping: waiting for the current job to finish or cancel…\n"))
    jobs.put(None)
    worker_thread.join()
    lock.close()
    return summary


def process_latest_run(target, log, should_cancel) -> dict:
    """Process the most recent run of a target now, and record it as processed."""
    db = get_db_manager()
    raw_files = _by_date(_light_frames(db.get_files_by_target(target)))
    if not raw_files:
        return {"success": False, "error": f"No light frames for target {target!r}."}
    run_files = split_into_runs(raw_files)[-1]
    first, last = run_files[0].date_obs, run_files[-1].date_obs
    log(f"Latest run of {target}: {len(run_files)} frame(s), {first} – {last}\n")
    result = process_run(target, run_files, log, should_cancel)
    if not result.get("cancelled"):
        state = _State()
        state.initialize(_by_date(_light_frames(db.get_all_fits_files())))
        state.record(run_files, target, result)
    return result
