"""
Library settings dialog: edits the user-facing settings (saved to the settings TOML file).
"""

from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from astropipes.astrometry.mpc import query_mpc_observatory_code
from astropipes.config import settings

ALIGNMENT_METHODS = ['astroalign', 'wcs_reprojection']
INTEGRATION_METHODS = ['average', 'median', 'sum']


@dataclass
class Setting:
    """One editable setting.

    kind: 'dir', 'file', 'text', 'secret', 'int', 'float', 'bool', 'choice' or 'gb'
          ('gb' is a byte count shown and edited in gigabytes).
    restart: the value is captured when the app starts, so edits apply after a restart.
    """
    key: str
    label: str
    kind: str
    tooltip: str = ''
    restart: bool = False
    minimum: float = 0
    maximum: float = 1_000_000
    step: float = 1
    decimals: int = 2
    suffix: str = ''
    special_text: str = ''
    choices: list = field(default_factory=list)


# Tab title → settings shown on that tab, in order.
SETTINGS_TABS = {
    'General': [
        Setting('TIME_DISPLAY_MODE', 'Time display', 'choice', choices=['UTC', 'Local'],
                tooltip='Show observation times in UTC or in this computer\'s local timezone.'),
        Setting('BLINK_PERIOD_MS', 'Blink period', 'int', minimum=10, maximum=10000, step=10,
                suffix=' ms', tooltip='Interval between frames when blinking images in the viewer.'),
        Setting('DATA_FOLDER_WATCH_ENABLED', 'Watch data folders', 'bool', restart=True,
                tooltip='Watch the data and calibration folders and scan new files automatically. '
                        'Disable for very large folder trees.'),
        Setting('DATA_FOLDER_WATCH_DEBOUNCE_MS', 'Watch debounce', 'int', restart=True,
                minimum=100, maximum=60000, step=100, suffix=' ms',
                tooltip='Wait this long after the last file change before scanning.'),
    ],
    'Paths': [
        Setting('DATA_PATH', 'Data', 'dir', tooltip='Root folder of raw light frames.'),
        Setting('CALIBRATION_PATH', 'Calibration', 'dir',
                tooltip='Calibration masters are written to (and expected to stay in) this folder.'),
        Setting('STACKS_PATH', 'Stacks', 'dir',
                tooltip='Session stacks and region views are written under <stacks>/<target>/.'),
        Setting('ARCHIVE_PATH', 'Archive', 'dir', restart=True,
                tooltip='Destination for targets moved to the archive.'),
        Setting('PROCESSED_PATH', 'Processing workspace', 'dir', restart=True,
                tooltip='Scratch folder for calibrated and aligned intermediate files.'),
        Setting('DATABASE_PATH', 'Library database', 'file', restart=True,
                tooltip='SQLite database file for the library.'),
    ],
    'Observatory': [
        Setting('OBS_CODE', 'MPC observatory code', 'text',
                tooltip='Used for MPC reports and ephemerides. Use "Look up" to fill in the coordinates.'),
        Setting('OBS_LON', 'Longitude', 'float', minimum=-180, maximum=360, step=0.001,
                decimals=6, suffix=' ° E'),
        Setting('OBS_LAT', 'Latitude', 'float', minimum=-90, maximum=90, step=0.001,
                decimals=6, suffix=' ° N'),
    ],
    'Plate solving': [
        Setting('SOLVER_DOWNSAMPLE', 'Downsample factor', 'int', minimum=1, maximum=16),
        Setting('SOLVER_SEARCH_RADIUS', 'Search radius', 'float', minimum=0.1, maximum=180,
                step=1, decimals=1, suffix=' °'),
    ],
    'Alignment': [
        Setting('DEFAULT_ALIGNMENT_METHOD', 'Default method', 'choice', restart=True,
                choices=ALIGNMENT_METHODS,
                tooltip='astroalign is fast (asterism matching); wcs_reprojection is slow but uses '
                        'the plate solution.'),
        Setting('FALLBACK_ALIGNMENT_METHOD', 'Fallback method', 'choice', restart=True,
                choices=ALIGNMENT_METHODS, tooltip='Used when the default method fails.'),
        Setting('SHOW_ALIGNMENT_METHOD_DIALOG', 'Ask for method each time', 'bool', restart=True),
        Setting('MAX_ALIGNMENT_IMAGES', 'Max images per alignment', 'int', restart=True,
                minimum=1, maximum=10000),
        Setting('ALIGNMENT_MEMORY_LIMIT', 'Memory limit', 'gb', restart=True),
        Setting('ALIGNMENT_ENABLE_CHUNKED', 'Chunked processing', 'bool', restart=True),
        Setting('ALIGNMENT_CHUNK_SIZE', 'Chunk size', 'int', restart=True, minimum=1,
                maximum=1000, suffix=' images'),
        Setting('ALIGNMENT_SAVE_PROGRESSIVE', 'Save progressively', 'bool', restart=True,
                tooltip='Write aligned images as they are produced instead of all at the end.'),
    ],
    'Integration': [
        Setting('SIGMA_LOW', 'Sigma clip low', 'float', restart=True, minimum=0.1, maximum=20,
                step=0.5, decimals=1, suffix=' σ',
                tooltip='Pixel rejection threshold for light frames and calibration masters.'),
        Setting('SIGMA_HIGH', 'Sigma clip high', 'float', restart=True, minimum=0.1, maximum=20,
                step=0.5, decimals=1, suffix=' σ'),
        Setting('INTEGRATION_MEMORY_LIMIT', 'Memory limit', 'gb', restart=True),
        Setting('INTEGRATION_ENABLE_CHUNKED', 'Chunked processing', 'bool', restart=True),
        Setting('INTEGRATION_CHUNK_SIZE', 'Chunk size', 'int', restart=True, minimum=1,
                maximum=1000, suffix=' images'),
        Setting('MAX_INTEGRATION_IMAGES', 'Max images per stack', 'int', minimum=1,
                maximum=10000, tooltip='Warning threshold in the astropipes command line tool.'),
        Setting('MOTION_TRACKING_METHOD', 'Motion tracking method', 'choice', restart=True,
                choices=INTEGRATION_METHODS),
        Setting('MOTION_TRACKING_SIGMA_CLIP', 'Motion tracking sigma clip', 'bool', restart=True,
                tooltip='Off by default: clipping can create artefacts at the stack borders.'),
        Setting('MOTION_TRACKING_CREATE_BOTH_STACKS', 'Create median and average stacks', 'bool',
                restart=True),
    ],
    'Calibration': [
        Setting('MAX_BIAS_AGE', 'Max bias age', 'int', maximum=3650, suffix=' days',
                special_text='No limit',
                tooltip='Oldest master allowed relative to the light frame. 0 = no limit.'),
        Setting('MAX_DARK_AGE', 'Max dark age', 'int', maximum=3650, suffix=' days',
                special_text='No limit'),
        Setting('MAX_FLAT_AGE', 'Max flat age', 'int', maximum=3650, suffix=' days',
                special_text='No limit'),
    ],
}


class SettingsDialog(QDialog):
    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(560, 420)
        self.settings = {s.key: s for tab in SETTINGS_TABS.values() for s in tab}
        self.widgets = {}
        self.loaded_values = {}

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        for title, settings in SETTINGS_TABS.items():
            tabs.addTab(self._build_tab(settings), title)
        layout.addWidget(tabs)

        note = QLabel("* Takes effect after restarting Astropipes.")
        note.setStyleSheet("color: #888888;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save_settings)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.load_settings()

    # --- Widgets ---

    def _build_tab(self, settings):
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for s in settings:
            editor, row = self._make_editor(s)
            if s.tooltip:
                editor.setToolTip(s.tooltip)
            self.widgets[s.key] = editor
            label = QLabel(s.label + (" *" if s.restart else ""))
            if s.tooltip:
                label.setToolTip(s.tooltip)
            form.addRow(label, row)
        return page

    def _make_editor(self, s: Setting):
        """Return (value widget, widget placed in the form row)."""
        if s.kind in ('dir', 'file'):
            edit = QLineEdit()
            browse = QPushButton("Browse")
            browse.clicked.connect(lambda _=False, s=s, e=edit: self._browse(s, e))
            return edit, self._row(edit, browse)
        if s.kind == 'secret':
            edit = QLineEdit()
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            show = QPushButton("Show")
            show.setCheckable(True)
            show.toggled.connect(lambda on, e=edit: e.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
            return edit, self._row(edit, show)
        if s.kind == 'text':
            edit = QLineEdit()
            if s.key == 'OBS_CODE':
                edit.setPlaceholderText("e.g., R56")
                lookup = QPushButton("Look up")
                lookup.setToolTip("Fill in the coordinates from the MPC observatory list.")
                lookup.clicked.connect(self.lookup_observatory_code)
                return edit, self._row(edit, lookup)
            return edit, edit
        if s.kind == 'int':
            spin = QSpinBox()
            spin.setRange(int(s.minimum), int(s.maximum))
            spin.setSingleStep(int(s.step))
            spin.setSuffix(s.suffix)
            spin.setSpecialValueText(s.special_text)
            return spin, spin
        if s.kind in ('float', 'gb'):
            spin = QDoubleSpinBox()
            if s.kind == 'gb':
                spin.setRange(0.5, 512)
                spin.setSingleStep(0.5)
                spin.setDecimals(1)
                spin.setSuffix(' GB')
            else:
                spin.setRange(s.minimum, s.maximum)
                spin.setSingleStep(s.step)
                spin.setDecimals(s.decimals)
                spin.setSuffix(s.suffix)
            return spin, spin
        if s.kind == 'bool':
            check = QCheckBox()
            return check, check
        if s.kind == 'choice':
            combo = QComboBox()
            combo.addItems(s.choices)
            return combo, combo
        raise ValueError(f"Unknown setting kind {s.kind!r} for {s.key}")

    @staticmethod
    def _row(*widgets):
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            box.addWidget(w)
        return row

    def _browse(self, s: Setting, edit: QLineEdit):
        start = edit.text() or str(Path.home())
        if s.kind == 'dir':
            path = QFileDialog.getExistingDirectory(self, f"Select {s.label} folder", start)
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, f"Select {s.label}", start, "SQLite database (*.db);;All files (*)",
                options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            edit.setText(path)

    # --- Values ---

    def _get_widget_value(self, s: Setting):
        w = self.widgets[s.key]
        if s.kind in ('dir', 'file', 'text', 'secret'):
            return w.text().strip()
        if s.kind == 'int':
            return w.value()
        if s.kind == 'float':
            return round(w.value(), s.decimals)
        if s.kind == 'gb':
            return round(w.value(), 1)
        if s.kind == 'bool':
            return w.isChecked()
        return w.currentText()

    def _set_widget_value(self, s: Setting, value):
        w = self.widgets[s.key]
        if s.kind in ('dir', 'file', 'text', 'secret'):
            w.setText('' if value is None else str(value))
        elif s.kind == 'int':
            w.setValue(int(value or 0))
        elif s.kind == 'float':
            w.setValue(float(value or 0))
        elif s.kind == 'gb':
            w.setValue(float(value or 0) / 1e9)
        elif s.kind == 'bool':
            w.setChecked(bool(value))
        elif s.kind == 'choice':
            if value not in s.choices:
                w.addItem(str(value))
            w.setCurrentText(str(value))

    def load_settings(self):
        # Re-read the settings file so values edited outside the app are shown.
        settings.reload()
        for key, s in self.settings.items():
            if hasattr(settings, key):
                self._set_widget_value(s, getattr(settings, key))
            # Compare against what the widget shows, so rounding alone isn't a change.
            self.loaded_values[key] = self._get_widget_value(s)

    def lookup_observatory_code(self):
        """Fill the observatory coordinates from the MPC observatory list."""
        obs_code = self.widgets['OBS_CODE'].text().strip()
        if not obs_code:
            QMessageBox.warning(self, "Invalid Input", "Please enter an observatory code.")
            return

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            longitude, latitude = query_mpc_observatory_code(obs_code)
        finally:
            QGuiApplication.restoreOverrideCursor()

        if longitude is None or latitude is None:
            QMessageBox.warning(self, "Not Found",
                f"Observatory code '{obs_code}' not found in MPC database.")
            return
        self.widgets['OBS_LON'].setValue(longitude)
        self.widgets['OBS_LAT'].setValue(latitude)
        QMessageBox.information(self, "Observatory Found",
            f"Found observatory {obs_code}:\n"
            f"Longitude: {longitude:.6f}° E\n"
            f"Latitude: {latitude:.6f}° N\n\n"
            f"Click Save to keep these coordinates.")

    def save_settings(self):
        changed = {}
        for key, s in self.settings.items():
            value = self._get_widget_value(s)
            if value != self.loaded_values.get(key):
                changed[key] = value
        if not changed:
            self.accept()
            return

        try:
            settings.save({k: v * 1e9 if self.settings[k].kind == 'gb' else v
                           for k, v in changed.items()})
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Settings Not Saved", f"Could not update {settings.path}:\n{e}")
            return

        self.settings_changed.emit()
        restart_labels = [self.settings[k].label for k in changed if self.settings[k].restart]
        if restart_labels:
            QMessageBox.information(self, "Restart Required",
                "These changes take effect after restarting Astropipes:\n\n• "
                + "\n• ".join(restart_labels))
        self.accept()
