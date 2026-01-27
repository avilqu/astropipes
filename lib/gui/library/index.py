#!/usr/bin/env python3
"""
Astronomical Image Library GUI
A PyQt6-based interface for managing a library of FITS files.
"""

import sys
import urllib.request
import math
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, 
    QMenuBar, QMessageBox, QProgressBar, QStatusBar, QSplitter, QStackedWidget, QDialog, QPushButton, QRadioButton, QHBoxLayout, QSpinBox, QGroupBox, QFileDialog, QLineEdit, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal, QFileSystemWatcher
from PyQt6.QtGui import QAction

# Import our modular components
from .db_access import DatabaseLoaderThread, DatabaseScannerThread, DatabaseManager
from .data_folder_watcher import DataFolderWatcher
from .obslog import FitsTableWidget
from .main_table import MainFitsTableWidget
from .sidebar import LeftPanel
from .calibration_tables import MasterDarksTableWidget, MasterBiasTableWidget, MasterFlatsTableWidget
from .mpc_log_table import MPCLogTableWidget
from lib.db import get_db_manager
from lib.db.models import CalibrationMaster
from lib.gui.library.menu_bar import create_menu_bar
from lib.gui.common.console_window import ConsoleOutputWindow
import config
import importlib


def query_mpc_observatory_code(obs_code):
    """
    Query the MPC observatory codes file to get coordinates for a given observatory code.
    
    Args:
        obs_code (str): The observatory code to look up
        
    Returns:
        tuple: (longitude, latitude) in degrees, or (None, None) if not found
    """
    try:
        # Fetch the MPC observatory codes file
        url = "https://www.minorplanetcenter.net/iau/lists/ObsCodes.html"
        with urllib.request.urlopen(url) as response:
            content = response.read().decode('utf-8')
        
        # Parse the content line by line
        lines = content.split('\n')
        for line in lines:
            # Skip header lines and empty lines
            if not line.strip() or line.startswith('Code') or line.startswith('----'):
                continue
            
            # Split the line into fields
            parts = line.split()
            if len(parts) >= 2:
                code = parts[0]
                if code == obs_code:
                    # The format can be: CODE LONGITUDE COS SIN NAME
                    # But sometimes values are concatenated like: R56 170.483890.720473-0.691324Scott
                    # We need to parse the second field more carefully
                    
                    # Try to extract longitude, cos, and sin from the second field
                    second_field = parts[1]
                    
                    # Check if the second field contains a sign (+ or -) to determine if it's concatenated
                    import re
                    has_sign = re.search(r'[+-]', second_field) is not None
                    
                    if has_sign:
                        # Try to parse concatenated format like: 170.483890.720473-0.691324
                        # Find the sign (+ or -) to separate cos and sin
                        
                        # Look for a sign followed by a decimal number
                        sign_match = re.search(r'([+-])(\d+\.\d+)', second_field)
                        if sign_match:
                            sign_pos = sign_match.start()
                            sign = sign_match.group(1)
                            sin_str = sign_match.group(2)
                            
                            # Extract the part before the sign
                            before_sign = second_field[:sign_pos]
                            
                            # Find the second decimal point in the before_sign part
                            decimal_points = [i for i, char in enumerate(before_sign) if char == '.']
                            if len(decimal_points) >= 2:
                                # First decimal point is for longitude
                                first_decimal = decimal_points[0]
                                
                                # Find the start of the cos component (first "0." after longitude)
                                cos_start = before_sign.find('0.', first_decimal + 4)
                                if cos_start != -1:
                                    # Extract longitude up to the start of cos
                                    longitude_str = before_sign[:cos_start]
                                    
                                    # For better precision, let's extract the full cos value
                                    # Find where the cos value ends (before the sign)
                                    cos_end = before_sign.find('+', cos_start)
                                    if cos_end == -1:
                                        cos_end = before_sign.find('-', cos_start)
                                    if cos_end != -1:
                                        cos_str = before_sign[cos_start:cos_end]
                                    else:
                                        # Fallback: use the rest of the string before the sign
                                        cos_str = before_sign[cos_start:]
                                else:
                                    # Fallback to old method if no "0." found
                                    longitude_str = before_sign[:first_decimal + 4]  # Include 3 decimal places
                                    # Find the second decimal point for cos
                                    second_decimal = decimal_points[1]
                                    cos_str = before_sign[first_decimal + 4:second_decimal + 6]  # Include 5 decimal places
                                
                                try:
                                    longitude = float(longitude_str)
                                    cos_val = float(cos_str)
                                    sin_val = float(sign + sin_str)
                                except ValueError:
                                    continue
                            else:
                                continue
                        else:
                            continue
                    elif len(parts) >= 4:
                        # Try the simple approach with separate fields
                        try:
                            longitude = float(parts[1])
                            cos_val = float(parts[2])
                            sin_val = float(parts[3])
                        except (ValueError, IndexError):
                            continue
                    else:
                        continue
                    
                    # Calculate latitude from cos and sin
                    # The cos and sin values represent cos(latitude) and sin(latitude)
                    # We can use either to calculate latitude
                    if abs(cos_val) <= 1.0:
                        # Use arccos if cos value is valid
                        latitude = math.degrees(math.acos(cos_val))
                        # Determine sign from sin value
                        if sin_val < 0:
                            latitude = -latitude
                    else:
                        # Fallback to arcsin
                        latitude = math.degrees(math.asin(sin_val))
                    
                    return longitude, latitude
        
        return None, None
        
    except Exception as e:
        print(f"Error querying MPC observatory codes: {e}")
        return None, None


class SettingsDialog(QDialog):
    settings_changed = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(320, 320)
        layout = QVBoxLayout(self)

        # Data path selection
        data_path_layout = QHBoxLayout()
        data_path_label = QLabel("Data Path:")
        self.data_path_edit = QLineEdit()
        self.data_path_edit.setReadOnly(True)
        data_path_browse = QPushButton("Browse")
        data_path_browse.clicked.connect(self.browse_data_path)
        data_path_layout.addWidget(data_path_label)
        data_path_layout.addWidget(self.data_path_edit)
        data_path_layout.addWidget(data_path_browse)
        layout.addLayout(data_path_layout)

        # Calibration path selection
        calib_path_layout = QHBoxLayout()
        calib_path_label = QLabel("Calibration Path:")
        self.calib_path_edit = QLineEdit()
        self.calib_path_edit.setReadOnly(True)
        calib_path_browse = QPushButton("Browse")
        calib_path_browse.clicked.connect(self.browse_calib_path)
        calib_path_layout.addWidget(calib_path_label)
        calib_path_layout.addWidget(self.calib_path_edit)
        calib_path_layout.addWidget(calib_path_browse)
        layout.addLayout(calib_path_layout)

        # Time mode radio buttons
        time_row = QHBoxLayout()
        time_label = QLabel("Time Display Mode:")
        self.utc_radio = QRadioButton("UTC time")
        self.local_radio = QRadioButton("Local time")
        time_row.addWidget(time_label)
        time_row.addWidget(self.utc_radio)
        time_row.addWidget(self.local_radio)
        time_row.addStretch()
        layout.addLayout(time_row)

        # Blink period input
        blink_layout = QHBoxLayout()
        blink_label = QLabel("Blink period (ms):")
        self.blink_spin = QSpinBox()
        self.blink_spin.setRange(10, 10000)
        self.blink_spin.setSingleStep(10)
        self.blink_spin.setValue(500)
        blink_layout.addWidget(blink_label)
        blink_layout.addWidget(self.blink_spin)
        layout.addLayout(blink_layout)

        # Observatory code input
        obs_layout = QHBoxLayout()
        obs_label = QLabel("Observatory Code:")
        self.obs_code_edit = QLineEdit()
        self.obs_code_edit.setPlaceholderText("e.g., R56")
        self.obs_code_ok_btn = QPushButton("OK")
        self.obs_code_ok_btn.clicked.connect(self.lookup_observatory_code)
        obs_layout.addWidget(obs_label)
        obs_layout.addWidget(self.obs_code_edit)
        obs_layout.addWidget(self.obs_code_ok_btn)
        layout.addLayout(obs_layout)

        # Observatory coordinates display
        self.obs_coords_label = QLabel("Coordinates: Not set")
        self.obs_coords_label.setStyleSheet("color: #888888; margin: 0px; padding: 0px;")
        layout.addWidget(self.obs_coords_label)

        # Save button
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)

        self.load_settings()

    def browse_data_path(self):
        path = QFileDialog.getExistingDirectory(self, "Select Data Path", self.data_path_edit.text() or "~")
        if path:
            self.data_path_edit.setText(path)

    def browse_calib_path(self):
        path = QFileDialog.getExistingDirectory(self, "Select Calibration Path", self.calib_path_edit.text() or "~")
        if path:
            self.calib_path_edit.setText(path)

    def lookup_observatory_code(self):
        """Look up observatory coordinates from MPC database."""
        obs_code = self.obs_code_edit.text().strip()
        if not obs_code:
            QMessageBox.warning(self, "Invalid Input", "Please enter an observatory code.")
            return
        
        try:
            longitude, latitude = query_mpc_observatory_code(obs_code)
            
            if longitude is not None and latitude is not None:
                self.obs_coords_label.setText(f"Coordinates: {longitude:.8f}° E, {latitude:.8f}° N")
                self.obs_coords_label.setStyleSheet("color: #888888; margin: 0px; padding: 0px;")
                
                # Update config file with the found coordinates
                current_mode = 'UTC' if self.utc_radio.isChecked() else 'Local'
                current_blink = self.blink_spin.value()
                current_data_path = self.data_path_edit.text()
                current_calib_path = self.calib_path_edit.text()
                self.update_config_file(current_mode, current_blink, current_data_path, current_calib_path, obs_code, longitude, latitude)
                
                QMessageBox.information(self, "Success", 
                    f"Found observatory {obs_code}:\n"
                    f"Longitude: {longitude:.8f}° E\n"
                    f"Latitude: {latitude:.8f}° N\n\n"
                    f"Coordinates have been saved to config.")
            else:
                self.obs_coords_label.setText("Coordinates: Not found")
                self.obs_coords_label.setStyleSheet("color: #888888; margin: 0px; padding: 0px;")
                QMessageBox.warning(self, "Not Found", 
                    f"Observatory code '{obs_code}' not found in MPC database.")
                
        except Exception as e:
            self.obs_coords_label.setText("Coordinates: Error")
            self.obs_coords_label.setStyleSheet("color: #888888; margin: 0px; padding: 0px;")
            QMessageBox.critical(self, "Error", f"Error looking up observatory code: {str(e)}")

    def load_settings(self):
        # Force reload config to get latest values
        importlib.reload(config)
        # Set data and calibration paths
        self.data_path_edit.setText(getattr(config, 'DATA_PATH', ''))
        self.calib_path_edit.setText(getattr(config, 'CALIBRATION_PATH', ''))
        # Set radio buttons
        if getattr(config, 'TIME_DISPLAY_MODE', 'UTC') == 'UTC':
            self.utc_radio.setChecked(True)
        else:
            self.local_radio.setChecked(True)
        # Set blink period
        self.blink_spin.setValue(getattr(config, 'BLINK_PERIOD_MS', 750))
        # Set observatory code
        obs_code = getattr(config, 'OBS_CODE', '')
        self.obs_code_edit.setText(obs_code)
        # Update coordinates display if we have coordinates
        obs_lon = getattr(config, 'OBS_LON', None)
        obs_lat = getattr(config, 'OBS_LAT', None)
        if obs_lon is not None and obs_lat is not None:
            self.obs_coords_label.setText(f"Coordinates: {obs_lon:.8f}° E, {obs_lat:.8f}° N")
            self.obs_coords_label.setStyleSheet("color: #888888; margin: 0px; padding: 0px;")
        else:
            self.obs_coords_label.setText("Coordinates: Not set")
            self.obs_coords_label.setStyleSheet("color: #888888; margin: 0px; padding: 0px;")

    def save_settings(self):
        # Update config.py file with new values
        mode = 'UTC' if self.utc_radio.isChecked() else 'Local'
        blink = self.blink_spin.value()
        data_path = self.data_path_edit.text()
        calib_path = self.calib_path_edit.text()
        obs_code = self.obs_code_edit.text().strip()
        
        # Get current coordinates from config if observatory code matches
        obs_lon = None
        obs_lat = None
        if obs_code:
            current_obs_code = getattr(config, 'OBS_CODE', '')
            if obs_code == current_obs_code:
                obs_lon = getattr(config, 'OBS_LON', None)
                obs_lat = getattr(config, 'OBS_LAT', None)
        
        self.update_config_file(mode, blink, data_path, calib_path, obs_code, obs_lon, obs_lat)
        self.settings_changed.emit()
        self.accept()

    def update_config_file(self, mode, blink, data_path, calib_path, obs_code, obs_lon, obs_lat):
        import re
        import os
        config_path = os.path.join(os.path.dirname(__file__), '../../../config.py')
        with open(config_path, 'r') as f:
            lines = f.readlines()
        def replace_or_append(lines, key, value):
            pat = re.compile(rf'^{key}\s*=')
            for i, line in enumerate(lines):
                if pat.match(line):
                    lines[i] = f"{key} = {repr(value)}\n"
                    return lines
            lines.append(f"{key} = {repr(value)}\n")
            return lines
        lines = replace_or_append(lines, 'TIME_DISPLAY_MODE', mode)
        lines = replace_or_append(lines, 'BLINK_PERIOD_MS', blink)
        lines = replace_or_append(lines, 'DATA_PATH', data_path)
        lines = replace_or_append(lines, 'CALIBRATION_PATH', calib_path)
        lines = replace_or_append(lines, 'OBS_CODE', obs_code)
        if obs_lon is not None:
            lines = replace_or_append(lines, 'OBS_LON', obs_lon)
        if obs_lat is not None:
            lines = replace_or_append(lines, 'OBS_LAT', obs_lat)
        with open(config_path, 'w') as f:
            f.writelines(lines)


class AstroLibraryGUI(QMainWindow):
    """Main window for Astropipes Library."""
    
    def __init__(self):
        super().__init__()
        self.db_manager = DatabaseManager()
        self.fits_files = []
        self.last_menu_category = None
        self.last_menu_value = None
        self.console_window = None  # For scan output
        self.init_ui()
        self.connect_signals()
        self.setup_database_watcher()
        self.setup_data_folder_watcher()
        self.load_database()
    
    def init_ui(self):
        """Initialize the user interface."""
        # Set window properties
        self.setWindowTitle("Astropipes FITS Library")
        self.setGeometry(100, 100, 1200, 800)
        
        # Create menu bar using the new function
        from . import db_access
        create_menu_bar(
            self,
            self.close,
            self.scan_for_files,
            self.open_settings_dialog,
            self.refresh_database,
            self.cleanup_temp_directories
        )
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        main_layout.setSpacing(0)  # Remove spacing between widgets
        
        # Create splitter for resizable panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # Left panel (menu)
        self.left_panel = LeftPanel()
        splitter.addWidget(self.left_panel)
        
        # Right panel (stacked widget for future extensibility)
        self.right_stack = QStackedWidget()
        self.table_widget = FitsTableWidget()
        self.main_table_widget = MainFitsTableWidget()
        self.master_darks_table = MasterDarksTableWidget()
        self.master_bias_table = MasterBiasTableWidget()
        self.master_flats_table = MasterFlatsTableWidget()
        self.mpc_log_table = MPCLogTableWidget()
        self.right_stack.addWidget(self.table_widget)  # index 0: Runs (obs log)
        self.right_stack.addWidget(self.main_table_widget)  # index 1: Main table (targets/dates)
        self.right_stack.addWidget(self.master_darks_table)  # index 2: Master darks
        self.right_stack.addWidget(self.master_bias_table)   # index 3: Master bias
        self.right_stack.addWidget(self.master_flats_table)  # index 4: Master flats
        self.right_stack.addWidget(self.mpc_log_table)  # index 5: MPC Log
        splitter.addWidget(self.right_stack)
        splitter.setStretchFactor(1, 1)  # Make right panel expand more
        splitter.setSizes([self.left_panel.minimumWidth(), 1000])  # Left panel at min width
        
        # Create status bar
        self.create_status_bar()
    
    def create_status_bar(self):
        """Create the status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        # Add spacing to the left of the status label
        self.status_label = QLabel()
        self.status_label.setText("   Ready")  # Add left padding with spaces
        self.status_bar.addWidget(self.status_label)

        # Add a visual separator and a label for time display mode
        self.status_separator = QFrame()
        self.status_separator.setFrameShape(QFrame.Shape.VLine)
        self.status_separator.setFrameShadow(QFrame.Shadow.Sunken)
        self.status_bar.addWidget(self.status_separator)

        self.time_mode_label = QLabel()
        self.status_bar.addWidget(self.time_mode_label)

        # Progress bar for operations
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)
    
    def connect_signals(self):
        """Connect all the signals and slots."""
        # Table connections
        self.table_widget.selection_changed.connect(self.on_table_selection_changed)
        self.table_widget.platesolving_completed.connect(self.load_database)
        self.table_widget.database_refresh_requested.connect(self.load_database)
        self.main_table_widget.platesolving_completed.connect(self.load_database)
        self.main_table_widget.database_refresh_requested.connect(self.load_database)
        # Refresh MPC log table when database is refreshed
        self.table_widget.database_refresh_requested.connect(self.refresh_mpc_log_table)
        self.main_table_widget.database_refresh_requested.connect(self.refresh_mpc_log_table)
        self.mpc_log_table.database_refresh_requested.connect(self.refresh_mpc_log_table)
        # Menu selection
        self.left_panel.menu_selection_changed.connect(self.on_menu_selection_changed)
        self.left_panel.target_renamed.connect(lambda old, new: self.load_database())
    
    def setup_database_watcher(self):
        """Set up a file system watcher to monitor the database file for changes."""
        import os
        import config
        
        # Create file system watcher
        self.db_watcher = QFileSystemWatcher(self)
        
        # Add the database file and related SQLite files to watch
        db_path = config.DATABASE_PATH
        db_dir = os.path.dirname(db_path) if os.path.dirname(db_path) else '.'
        db_basename = os.path.basename(db_path)
        
        # Watch the database directory for changes (catches all SQLite files)
        if os.path.exists(db_dir):
            self.db_watcher.addPath(db_dir)
            self.db_watcher.directoryChanged.connect(self.on_database_directory_changed)
        
        # Also watch the main database file if it exists
        if os.path.exists(db_path):
            self.db_watcher.addPath(db_path)
            self.db_watcher.fileChanged.connect(self.on_database_file_changed)
        
        # Watch SQLite journal and WAL files (SQLite may write to these)
        journal_path = db_path + '-journal'
        wal_path = db_path + '-wal'
        shm_path = db_path + '-shm'
        
        for sqlite_file in [journal_path, wal_path, shm_path]:
            if os.path.exists(sqlite_file):
                self.db_watcher.addPath(sqlite_file)
                self.db_watcher.fileChanged.connect(self.on_database_file_changed)
    
    def on_database_file_changed(self, path):
        """Handle database file change event."""
        # Debounce: use a timer to avoid multiple rapid refreshes
        if not hasattr(self, '_refresh_timer'):
            from PyQt6.QtCore import QTimer
            self._refresh_timer = QTimer(self)
            self._refresh_timer.setSingleShot(True)
            self._refresh_timer.timeout.connect(self._perform_database_refresh)
        
        # Restart the timer (debounce for 500ms)
        self._refresh_timer.stop()
        self._refresh_timer.start(500)
    
    def on_database_directory_changed(self, path):
        """Handle database directory change event (e.g., database file created or SQLite journal files changed)."""
        import os
        import config
        db_path = config.DATABASE_PATH
        db_basename = os.path.basename(db_path)
        
        # Check if the main database file exists and add it to watcher if not already watching
        if os.path.exists(db_path) and db_path not in self.db_watcher.files():
            self.db_watcher.addPath(db_path)
            if not self.db_watcher.receivers(self.db_watcher.fileChanged):
                self.db_watcher.fileChanged.connect(self.on_database_file_changed)
        
        # Check for SQLite journal/WAL files and add them if they exist
        for suffix in ['-journal', '-wal', '-shm']:
            sqlite_file = db_path + suffix
            if os.path.exists(sqlite_file) and sqlite_file not in self.db_watcher.files():
                self.db_watcher.addPath(sqlite_file)
                if not self.db_watcher.receivers(self.db_watcher.fileChanged):
                    self.db_watcher.fileChanged.connect(self.on_database_file_changed)
        
        # Trigger refresh when directory changes (SQLite may have written journal/WAL files)
        self.on_database_file_changed(db_path)

    def setup_data_folder_watcher(self):
        """Watch DATA_PATH and CALIBRATION_PATH recursively; trigger background scan on changes."""
        if not getattr(config, 'DATA_FOLDER_WATCH_ENABLED', True):
            self.data_folder_watcher = None
            return
        debounce = getattr(config, 'DATA_FOLDER_WATCH_DEBOUNCE_MS', 1500)
        self.data_folder_watcher = DataFolderWatcher(self, debounce_ms=debounce)
        self.data_folder_watcher.set_paths([config.DATA_PATH, config.CALIBRATION_PATH])
        self.data_folder_watcher.scan_requested.connect(self.run_watch_triggered_scan)
        self.data_folder_watcher.start()

    def run_watch_triggered_scan(self):
        """Run a quiet background scan when the data folder watcher detects changes."""
        if getattr(self, 'scanner_thread', None) and self.scanner_thread.isRunning():
            return
        self.status_label.setText("   Scanning for new files…")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.scanner_thread = DatabaseScannerThread(quiet=True)
        self.scanner_thread.scan_completed.connect(self.on_watch_scan_completed)
        self.scanner_thread.error_occurred.connect(self.on_watch_scan_error)
        self.scanner_thread.start()

    def on_watch_scan_completed(self, results):
        """Handle background scan completion (no console, no dialog)."""
        self.progress_bar.setVisible(False)
        n = results.get('files_imported', 0) + results.get('calib_imported', 0)
        if n > 0:
            self.status_label.setText(f"   Added {n} new file(s)")
        self.left_panel.repopulate_targets_and_dates()
        self.load_database()
        self.update_status_bar()

    def on_watch_scan_error(self, error_message):
        """Handle background scan error (log only, no dialog)."""
        self.progress_bar.setVisible(False)
        self.status_label.setText("   Background scan failed")
        self.update_status_bar()

    def _perform_database_refresh(self):
        """Perform the actual database refresh after debounce."""
        # Refresh the database connection
        from . import db_access
        try:
            db_access.refresh_database()
        except Exception as e:
            print(f"Error refreshing database connection: {e}")
        
        # Reload the database (on_data_loaded will refresh the sidebar)
        self.load_database()
    
    def load_database(self):
        """Load FITS files from the database."""
        self.status_label.setText("Loading database...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        
        # Use thread to avoid blocking GUI
        import config
        self.loader_thread = DatabaseLoaderThread(config.DATABASE_PATH)
        self.loader_thread.data_loaded.connect(self.on_data_loaded)
        self.loader_thread.error_occurred.connect(self.on_database_error)
        self.loader_thread.start()
    
    def on_data_loaded(self, fits_files):
        """Handle loaded database data."""
        self.fits_files = fits_files
        self.table_widget.populate_table(fits_files)
        # Refresh the sidebar to reflect new counts
        self.left_panel.repopulate_targets_and_dates()
        # If main_table_widget is visible, repopulate it with the correct filter
        if self.right_stack.currentIndex() == 1:
            if self.last_menu_category == "target":
                filtered = [f for f in self.fits_files if f.target == self.last_menu_value]
                self.main_table_widget.populate_table(filtered)
            elif self.last_menu_category == "date":
                from config import TIME_DISPLAY_MODE, to_display_time
                if TIME_DISPLAY_MODE == 'Local':
                    filtered = [
                        f for f in self.fits_files
                        if f.date_obs and to_display_time(f.date_obs).strftime('%Y-%m-%d') == self.last_menu_value
                    ]
                else:
                    filtered = [
                        f for f in self.fits_files
                        if f.date_obs and f.date_obs.strftime('%Y-%m-%d') == self.last_menu_value
                    ]
                self.main_table_widget.populate_table(filtered)
        self.update_status_bar()
        self.progress_bar.setVisible(False)
    
    def on_database_error(self, error_message):
        """Handle database loading errors."""
        self.status_label.setText("Database error")
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "Database Error", f"Failed to load database: {error_message}")
    
    def on_table_selection_changed(self, fits_file_ids):
        """Handle table selection changes."""
        # Currently no actions needed on selection change
        # The selection now returns a list of file IDs from the selected run(s)
        pass
    
    def on_menu_selection_changed(self, category, value):
        """Switch right panel content based on menu selection."""
        self.last_menu_category = category
        self.last_menu_value = value
        if category == "runs":
            self.right_stack.setCurrentIndex(0)
        elif category == "mpc_log":
            # Load MPC log entries from database
            db = get_db_manager()
            session = db.get_session()
            try:
                from lib.db.models import MPCLog
                entries = session.query(MPCLog).order_by(MPCLog.observation_date.desc()).all()
                self.mpc_log_table.populate(entries)
            finally:
                session.close()
            self.right_stack.setCurrentIndex(5)
        elif category == "target":
            filtered = [f for f in self.fits_files if f.target == value]
            self.main_table_widget.populate_table(filtered)
            self.right_stack.setCurrentIndex(1)
        elif category == "date":
            from config import TIME_DISPLAY_MODE, to_display_time
            if TIME_DISPLAY_MODE == 'Local':
                filtered = [
                    f for f in self.fits_files
                    if f.date_obs and to_display_time(f.date_obs).strftime('%Y-%m-%d') == value
                ]
            else:
                filtered = [
                    f for f in self.fits_files
                    if f.date_obs and f.date_obs.strftime('%Y-%m-%d') == value
                ]
            self.main_table_widget.populate_table(filtered)
            self.right_stack.setCurrentIndex(1)
        elif category == "darks":
            db = get_db_manager()
            session = db.get_session()
            darks = session.query(CalibrationMaster).filter_by(frame="Dark").all()
            session.close()
            self.master_darks_table.populate(darks)
            self.right_stack.setCurrentIndex(2)
        elif category == "bias":
            db = get_db_manager()
            session = db.get_session()
            biases = session.query(CalibrationMaster).filter_by(frame="Bias").all()
            session.close()
            self.master_bias_table.populate(biases)
            self.right_stack.setCurrentIndex(3)
        elif category == "flats":
            db = get_db_manager()
            session = db.get_session()
            flats = session.query(CalibrationMaster).filter_by(frame="Flat").all()
            session.close()
            self.master_flats_table.populate(flats)
            self.right_stack.setCurrentIndex(4)
        # Do nothing for 'targets', 'dates', or other parent nodes
        self.update_status_bar()
    
    def scan_for_files(self):
        """Scan for new FITS files."""
        # Show console window for scan output
        if self.console_window is not None:
            self.console_window.close()
        self.console_window = ConsoleOutputWindow(title="Database Scan Output", parent=self)
        self.console_window.clear_output()
        self.console_window.show_and_raise()
        # Optionally, connect cancel button to stop scan (not implemented yet)
        # self.console_window.cancel_requested.connect(self.cancel_scan)
        # Start scan in thread
        self.status_label.setText("Scanning for new files...")
        # Hide progress bar
        self.progress_bar.setVisible(False)
        self.scanner_thread = DatabaseScannerThread()
        self.scanner_thread.output_received.connect(self.console_window.append_text)
        self.scanner_thread.scan_completed.connect(self.on_scan_completed)
        self.scanner_thread.error_occurred.connect(self.on_scan_error)
        self.scanner_thread.start()
    
    def on_scan_completed(self, results):
        """Handle scan completion."""
        self.status_label.setText("Scan completed")
        if self.console_window:
            self.console_window.append_text("\nScan completed successfully!\n")
            self.console_window.close_button.setEnabled(True)
        # Compose a single summary message
        msg = (
            "Scan completed successfully!\n\n"
            f"Files imported: {results.get('files_imported', 0)}\n"
            f"Files skipped: {results.get('files_skipped', 0)}\n"
            f"Total files found: {results.get('total_files_found', 0)}\n\n"
            f"Calibration masters imported: {results.get('calib_imported', 0)}\n"
            f"Calibration masters skipped: {results.get('calib_skipped', 0)}\n"
            f"Total calibration masters found: {results.get('calib_total_found', 0)}"
        )
        errors = results.get('errors', [])
        if errors:
            msg += f"\n\nErrors: {len(errors)}"
            if len(errors) > 0:
                msg += f"\nFirst error: {errors[0]}"
        QMessageBox.information(self, "Scan Complete", msg)
        self.left_panel.repopulate_targets_and_dates()
        self.load_database()  # Refresh the table
    
    def on_scan_error(self, error_message):
        """Handle scan errors."""
        self.status_label.setText("Scan failed")
        if self.console_window:
            self.console_window.append_text(f"\nScan failed: {error_message}\n")
            self.console_window.close_button.setEnabled(True)
        QMessageBox.critical(self, "Scan Error", f"Error during scan: {error_message}")

    def open_settings_dialog(self):
        dlg = SettingsDialog(self)
        dlg.settings_changed.connect(self.on_settings_changed)
        dlg.exec()

    def on_settings_changed(self):
        import importlib
        importlib.reload(config)
        if self.data_folder_watcher is not None and getattr(config, 'DATA_FOLDER_WATCH_ENABLED', True):
            self.data_folder_watcher.set_paths([config.DATA_PATH, config.CALIBRATION_PATH])
        self.left_panel.repopulate_targets_and_dates()
        self.load_database()

    def update_status_bar(self):
        """Update the status bar to show 'Showing x / y files' for the current view and the time display mode."""
        import config
        total = len(self.fits_files)
        current_index = self.right_stack.currentIndex()
        if current_index == 0:
            # Runs (obs log)
            shown = self.table_widget.get_visible_file_count()
        elif current_index == 1:
            shown = self.main_table_widget.get_visible_file_count()
        elif current_index == 2:
            shown = self.master_darks_table.get_visible_file_count()
        elif current_index == 3:
            shown = self.master_bias_table.get_visible_file_count()
        elif current_index == 4:
            shown = self.master_flats_table.get_visible_file_count()
        elif current_index == 5:
            # MPC Log
            shown = self.mpc_log_table.get_visible_file_count()
        else:
            shown = 0
        self.status_label.setText(f"   Showing {shown} / {total} files")  # Add left padding
        # Update the time display mode label
        mode = getattr(config, 'TIME_DISPLAY_MODE', 'UTC')
        self.time_mode_label.setText(f"Time display mode: {mode}")

    def refresh_database(self):
        """Refresh the database from disk (for external modifications)."""
        from . import db_access
        try:
            db_access.refresh_database()
            self.load_database()
            # Refresh the sidebar to reflect new counts
            self.left_panel.repopulate_targets_and_dates()
            QMessageBox.information(self, "Database Refreshed", "Database has been refreshed from disk.")
        except Exception as e:
            QMessageBox.critical(self, "Refresh Failed", f"Failed to refresh database: {e}")

    def cleanup_temp_directories(self):
        """Delete all files in PROCESSED_PATH subdirectories (solved, calibrated, stacked, aligned, substacks)."""
        from . import db_access
        try:
            db_access.cleanup_temp_directories()
            QMessageBox.information(self, "Cleanup Complete", "Processed directories have been cleaned up.")
        except Exception as e:
            QMessageBox.critical(self, "Cleanup Failed", f"Failed to clean up processed directories: {e}")
    
    def refresh_mpc_log_table(self):
        """Refresh the MPC log table if it's currently visible."""
        if self.right_stack.currentIndex() == 5:
            db = get_db_manager()
            session = db.get_session()
            try:
                from lib.db.models import MPCLog
                entries = session.query(MPCLog).order_by(MPCLog.observation_date.desc()).all()
                self.mpc_log_table.populate(entries)
            finally:
                session.close()


def main():
    """Main function to launch the GUI application."""
    app = QApplication(sys.argv)
    
    # Create and show the main window
    window = AstroLibraryGUI()
    window.show()
    
    # Start the event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main() 