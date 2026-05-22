"""Background thread for Latest regions update action."""

from PyQt6.QtCore import QThread, pyqtSignal

from lib.fits.latest_regions_update import run_latest_regions_update


class LatestRegionsUpdateThread(QThread):
    output = pyqtSignal(str)
    finished = pyqtSignal(dict)

    def run(self):
        result = run_latest_regions_update(log=lambda m: self.output.emit(m))
        self.finished.emit(result)
