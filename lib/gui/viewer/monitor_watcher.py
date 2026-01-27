"""
Recursive watcher for DATA_PATH used by the FITS Viewer "Monitor" mode.
Emits changes_detected when new files or directories appear under the data folder.
"""

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, QFileSystemWatcher, QTimer


class ViewerDataWatcher(QObject):
    """Watches a root path recursively; emits changes_detected on filesystem changes."""

    changes_detected = pyqtSignal()

    def __init__(self, parent=None, debounce_ms=1500):
        super().__init__(parent)
        self._watcher = QFileSystemWatcher(self)
        self._watched_dirs = set()
        self._root_path = None
        self._debounce_ms = debounce_ms
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._emit)

        self._watcher.directoryChanged.connect(self._on_directory_changed)
        self._watcher.fileChanged.connect(self._on_file_changed)

    def set_root(self, path):
        """Set the root path to watch. Replaces any existing."""
        self.stop()
        self._root_path = Path(path).resolve() if path else None
        self._update_watched_tree()

    def _update_watched_tree(self):
        if not self._root_path or not self._root_path.exists() or not self._root_path.is_dir():
            return
        self._add_tree(self._root_path)

    def _add_tree(self, dir_path):
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
        p = Path(path)
        if not p.exists() or not p.is_dir():
            return
        self._add_tree(p)
        self._debounce()

    def _on_file_changed(self, _path):
        self._debounce()

    def _debounce(self):
        self._timer.stop()
        self._timer.start(self._debounce_ms)

    def _emit(self):
        self.changes_detected.emit()

    def start(self):
        self._update_watched_tree()

    def stop(self):
        self._timer.stop()
        watched = list(self._watched_dirs)
        if watched:
            self._watcher.removePaths(watched)
        self._watched_dirs.clear()
