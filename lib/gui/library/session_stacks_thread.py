"""Background batch: generate session stacks for all follow-up targets."""

import os
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

import config
from lib.db import get_db_manager
from lib.db.scan import FitsFileScanner
from lib.gui.library.daily_stacks_thread import generate_daily_stacks_impl
from lib.sci.platesolving import solve_single_image


def _filter_work_slug(filter_name: str) -> str:
    """Safe folder segment for PROCESSED_PATH session stack work dirs."""
    return str(filter_name).replace(" ", "_").replace(os.sep, "_")


def _files_matching_filter(raw_files, filter_name: str):
    if filter_name == "Unknown":
        return [f for f in raw_files if not f.filter_name or f.filter_name == "Unknown"]
    return [f for f in raw_files if f.filter_name == filter_name]


class SessionStacksBatchThread(QThread):
    output = pyqtSignal(str)
    finished = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._cancel = False

    def stop(self):
        self._cancel = True

    def run(self):
        results = {"success": True, "errors": []}
        db = get_db_manager()
        targets = db.follow_up_get_targets()
        if not targets:
            self.finished.emit({"success": False, "error": "No targets flagged for follow-up."})
            return

        scanner = FitsFileScanner()
        for target in targets:
            if self._cancel:
                break
            filter_names = db.follow_up_get_filters(target)
            files_all = db.get_files_by_target(target)
            raw_files = [f for f in files_all if not config.is_session_stack_fits_file(f)]
            existing_stack_paths = {
                f.path for f in files_all if config.is_session_stack_fits_file(f) and f.path
            }
            for fn in filter_names:
                if self._cancel:
                    break
                subset = _files_matching_filter(raw_files, fn)
                if not subset:
                    self.output.emit(
                        f"\nNo light frames for target {target!r} with filter {fn!r} — skipping.\n"
                    )
                    continue
                folder = config.data_path_target_folder_name(target)
                out_dir = config.stacks_path_for_target(target)
                out_dir.mkdir(parents=True, exist_ok=True)
                aligned_dir = (
                    Path(config.PROCESSED_PATH)
                    / "session_stacks_work"
                    / folder
                    / _filter_work_slug(fn)
                    / "aligned"
                )
                aligned_dir.mkdir(parents=True, exist_ok=True)
                self.output.emit(f"\n{'='*60}\nSession stacks: {target} / {fn}\n{'='*60}\n")
                res = generate_daily_stacks_impl(
                    target,
                    subset,
                    fn,
                    lambda m: self.output.emit(m),
                    lambda: self._cancel,
                    output_stacks_dir=str(out_dir),
                    allow_single_session=True,
                    aligned_output_dir=str(aligned_dir),
                    skip_existing_stack_paths=existing_stack_paths,
                    stack_filename_include_session_index=False,
                )
                if not res.get("success"):
                    err = res.get("error", "unknown error")
                    results["errors"].append((target, fn, err))
                    self.output.emit(f"✗ Stack generation failed: {err}\n")
                    continue
                skipped_existing = res.get("stacks_skipped_existing", 0)
                if skipped_existing:
                    self.output.emit(
                        f"  ↷ Skipped {skipped_existing} stack(s) already present in database\n"
                    )
                for p in res.get("stack_paths", []):
                    if self._cancel:
                        break
                    path = Path(p)
                    imported = scanner.import_fits_with_layout_target(
                        path, target, filter_fallback=fn
                    )
                    if imported:
                        self.output.emit(f"  Registered in database: {path.name}\n")
                    else:
                        self.output.emit(
                            f"  (Skipped DB import — already registered: {path.name})\n"
                        )

                    def out_cb(msg):
                        self.output.emit(msg)

                    sol = solve_single_image(str(path), output_callback=out_cb)
                    if not sol.success:
                        msg = getattr(sol, "message", "platesolve failed")
                        results["errors"].append((target, fn, str(path), msg))
                        self.output.emit(f"  ✗ Platesolve failed: {msg}\n")
                    else:
                        self.output.emit(f"  ✓ Platesolved: {path.name}\n")

        if self._cancel:
            results["success"] = False
            results["cancelled"] = True
        self.finished.emit(results)
