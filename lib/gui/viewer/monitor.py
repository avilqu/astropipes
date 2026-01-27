"""
Monitor mode for the FITS Viewer: watch the data folder and automatically
add new FITS files to the loaded files list.
"""

import os
from pathlib import Path

from PyQt6.QtCore import QTimer

from .monitor_watcher import ViewerDataWatcher


class MonitorMixin:
    """Mixin adding Monitor mode (auto-add new FITS from data folder) to the viewer."""

    def toggle_monitor_mode(self, on):
        """Enable or disable Monitor mode. Called when the Monitor toolbar button is toggled."""
        if on:
            self._monitor_start()
        else:
            self._monitor_stop()

    def _monitor_start(self):
        import config
        data_path = getattr(config, "DATA_PATH", None)
        if not data_path or not Path(data_path).exists():
            if hasattr(self, "monitor_button") and self.monitor_button:
                self.monitor_button.setChecked(False)
            return
        self._monitor_known_paths = set()
        root = Path(data_path).resolve()
        for p in root.rglob("*.fits"):
            if p.is_file():
                self._monitor_known_paths.add(str(p))
        for p in root.rglob("*.fit"):
            if p.is_file():
                self._monitor_known_paths.add(str(p))
        for p in root.rglob("*.fts"):
            if p.is_file():
                self._monitor_known_paths.add(str(p))
        for path in getattr(self, "loaded_files", []):
            if path and os.path.isabs(path) and path.startswith(str(root)):
                self._monitor_known_paths.add(path)
        debounce = getattr(config, "DATA_FOLDER_WATCH_DEBOUNCE_MS", 1500)
        self._monitor_watcher = ViewerDataWatcher(self, debounce_ms=debounce)
        self._monitor_watcher.set_root(data_path)
        self._monitor_watcher.changes_detected.connect(self._on_monitor_changes_detected)
        self._monitor_watcher.start()

    def _monitor_stop(self):
        w = getattr(self, "_monitor_watcher", None)
        if w:
            try:
                w.changes_detected.disconnect(self._on_monitor_changes_detected)
            except Exception:
                pass
            w.stop()
            self._monitor_watcher = None
        self._monitor_known_paths = getattr(self, "_monitor_known_paths", set())

    def _on_monitor_changes_detected(self):
        """Discover new FITS under data folder and add them to the loaded files list."""
        import config
        data_path = getattr(config, "DATA_PATH", None)
        if not data_path:
            return
        root = Path(data_path).resolve()
        known = getattr(self, "_monitor_known_paths", None)
        if known is None:
            return
        new_paths = []
        for ext in ("*.fits", "*.fit", "*.fts"):
            for p in root.rglob(ext):
                if not p.is_file():
                    continue
                s = str(p)
                if s not in known:
                    known.add(s)
                    new_paths.append(s)
        for path in sorted(new_paths):
            self.open_and_add_file(path, switch_to=False)
