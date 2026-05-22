"""Batch generation of region-of-interest PNG views for all stacks."""

from PyQt6.QtCore import QThread, pyqtSignal

import config
from lib.db import get_db_manager
from lib.fits.region_views import generate_views_for_region


class RegionViewsBatchThread(QThread):
    output = pyqtSignal(str)
    finished = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._cancel = False

    def stop(self):
        self._cancel = True

    def run(self):
        results = {"success": True, "regions": 0, "generated": 0, "skipped": 0, "errors": []}
        db = get_db_manager()
        regions = db.get_all_regions()
        if not regions:
            self.finished.emit({"success": False, "error": "No regions of interest defined."})
            return

        all_files = db.get_all_fits_files()
        stacks = [f for f in all_files if config.is_session_stack_fits_file(f)]

        if not stacks:
            self.finished.emit({
                "success": False,
                "error": "No session stacks in the database.",
            })
            return

        self.output.emit(f"Found {len(regions)} region(s), {len(stacks)} stack(s).\n\n")

        for region in regions:
            if self._cancel:
                results["cancelled"] = True
                break
            self.output.emit(f"Region: {region.name} (target {region.target})\n")
            sub = generate_views_for_region(
                region,
                stacks,
                log=lambda m: self.output.emit(m),
                should_cancel=lambda: self._cancel,
            )
            results["regions"] += 1
            results["generated"] += sub.get("generated", 0)
            results["skipped"] += sub.get("skipped", 0)
            for err in sub.get("errors", []):
                results["errors"].append((region.name, err))

        self.finished.emit(results)
