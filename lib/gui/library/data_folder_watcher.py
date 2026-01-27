"""
Recursive file system watcher for DATA_PATH and CALIBRATION_PATH.
Emits scan_requested when new files or directories appear, so the Library
can run a background scan and refresh automatically.
"""

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, QFileSystemWatcher, QTimer


class DataFolderWatcher(QObject):
    """Watches data and calibration paths recursively; emits scan_requested on changes."""

    scan_requested = pyqtSignal()

    def __init__(self, parent=None, debounce_ms=1500):
        super().__init__(parent)
        self._watcher = QFileSystemWatcher(self)
        self._watched_dirs = set()
        self._root_paths = []
        self._debounce_ms = debounce_ms
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._emit_scan_requested)

        self._watcher.directoryChanged.connect(self._on_directory_changed)
        self._watcher.fileChanged.connect(self._on_file_changed)

    def set_paths(self, paths):
        """Set root paths to watch (e.g. [DATA_PATH, CALIBRATION_PATH]). Replaces any existing."""
        self.stop()
        self._root_paths = [Path(p).resolve() for p in paths if p]
        self._update_watched_tree()

    def _update_watched_tree(self):
        """Add each root and all its subdirectories to the watcher."""
        for root in self._root_paths:
            if not root.exists() or not root.is_dir():
                continue
            self._add_tree(root)

    def _add_tree(self, dir_path):
        """Add dir_path and all subdirectories to the watcher."""
        dir_path = Path(dir_path).resolve()
        try:
            s = str(dir_path)
            if s not in self._watched_dirs:
                self._watcher.addPath(s)
                self._watched_dirs.add(s)
        except Exception:
            pass
        try:
            for entry in dir_path.iterdir():
                if entry.is_dir() and not entry.is_symlink():
                    self._add_tree(entry)
        except (PermissionError, OSError):
            pass

    def _on_directory_changed(self, path):
        """New files/dirs or new subdirs; add new subdirs and debounce scan."""
        path = Path(path)
        if not path.exists() or not path.is_dir():
            return
        self._add_tree(path)
        self._debounce_scan()

    def _on_file_changed(self, _path):
        """A file was modified; debounce and request scan."""
        self._debounce_scan()

    def _debounce_scan(self):
        """Restart debounce timer; emit scan_requested after quiet period."""
        self._timer.stop()
        self._timer.start(self._debounce_ms)

    def _emit_scan_requested(self):
        self.scan_requested.emit()

    def start(self):
        """Start watching. Call set_paths first."""
        self._update_watched_tree()

    def stop(self):
        """Stop watching and clear watched paths."""
        self._timer.stop()
        watched = list(self._watched_dirs)
        if watched:
            self._watcher.removePaths(watched)
        self._watched_dirs.clear()
