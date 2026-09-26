#!/usr/bin/env python3
"""
Astronomical Image Library GUI
A PyQt6-based interface for managing a library of FITS files.
"""

import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel,
    QMenuBar, QMessageBox, QProgressBar, QStatusBar, QSplitter, QStackedWidget, QGroupBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal, QFileSystemWatcher, QTimer
from PyQt6.QtGui import QAction

# Import our modular components
from .db_access import DatabaseLoaderThread, DatabaseScannerThread, DatabaseManager
from .data_folder_watcher import DataFolderWatcher
from .obslog import FitsTableWidget
from .main_table import MainFitsTableWidget
from .sidebar import LeftPanel
from .calibration_tables import MasterDarksTableWidget, MasterBiasTableWidget, MasterFlatsTableWidget
from .mpc_log_table import MPCLogTableWidget
from .region_detail import RegionDetailWidget
from .settings_dialog import SettingsDialog
from lib.db import get_db_manager
from lib.db.models import CalibrationMaster
from lib.gui.library.menu_bar import create_menu_bar
from lib.gui.common.console_window import ConsoleOutputWindow
import config
from lib import paths
from lib.time_display import to_display_time


class AstroLibraryGUI(QMainWindow):
    """Main window for Astropipes Library."""
    
    def __init__(self):
        super().__init__()
        self.db_manager = DatabaseManager()
        self.fits_files = []
        self.last_menu_category = None
        self.last_menu_value = None
        self.console_window = None  # For scan output
        self._suppress_db_file_watcher = False
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
            self.cleanup_temp_directories,
            self.generate_session_stacks,
            self.generate_region_views,
            self.latest_regions_update,
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
        self.region_detail_widget = RegionDetailWidget()
        self.right_stack.addWidget(self.table_widget)  # index 0: Runs (obs log)
        self.right_stack.addWidget(self.main_table_widget)  # index 1: Main table (targets/dates)
        self.right_stack.addWidget(self.master_darks_table)  # index 2: Master darks
        self.right_stack.addWidget(self.master_bias_table)   # index 3: Master bias
        self.right_stack.addWidget(self.master_flats_table)  # index 4: Master flats
        self.right_stack.addWidget(self.mpc_log_table)  # index 5: MPC Log
        self.right_stack.addWidget(self.region_detail_widget)  # index 6: Region detail
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
        self.left_panel.region_deleted.connect(self._on_region_deleted)
        self.left_panel.region_renamed.connect(self._on_region_renamed)
    
    def setup_database_watcher(self):
        """Set up a file system watcher to monitor the database file for changes."""
        import os
        import config
        
        # Create file system watcher
        self.db_watcher = QFileSystemWatcher(self)
        
        # Add the database file and related SQLite files to watch
        db_path = config.DATABASE_PATH
        db_dir = os.path.dirname(db_path) if os.path.dirname(db_path) else '.'

        # Watch only the main DB file. Do NOT watch -wal / -shm / -journal: with WAL mode
        # those change on every read/write and would spam fileChanged → refresh → infinite load.
        if os.path.exists(db_path):
            self.db_watcher.addPath(db_path)
            self.db_watcher.fileChanged.connect(self.on_database_file_changed)
        # If DB file does not exist yet, we intentionally do not watch the directory:
        # directory-level events are too noisy with SQLite WAL sidecar updates.
    
    def on_database_file_changed(self, path):
        """Handle database file change event."""
        if getattr(self, "_suppress_db_file_watcher", False):
            return
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
        """Handle database directory change (e.g. main .db file created)."""
        # Directory watching is disabled to avoid refresh loops/reinit churn with SQLite WAL.
        return

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
        self.left_panel.repopulate_regions()
        self.load_database()
        self.update_status_bar()

    def on_watch_scan_error(self, error_message):
        """Handle background scan error (log only, no dialog)."""
        self.progress_bar.setVisible(False)
        self.status_label.setText("   Background scan failed")
        self.update_status_bar()

    def _perform_database_refresh(self):
        """Perform the actual database refresh after debounce."""
        if getattr(self, "_suppress_db_file_watcher", False):
            return
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
        self._suppress_db_file_watcher = True
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
        self.left_panel.repopulate_regions()
        # If main_table_widget is visible, repopulate it with the correct filter
        if self.right_stack.currentIndex() == 1:
            if self.last_menu_category == "target":
                filtered = [
                    f for f in self.fits_files
                    if f.target == self.last_menu_value
                    and not paths.is_session_stack_fits_file(f)
                ]
                self.main_table_widget.populate_table(filtered, show_stack_count_column=False)
            elif self.last_menu_category == "followup_target":
                filtered = [
                    f for f in self.fits_files
                    if f.target == self.last_menu_value
                    and paths.is_session_stack_fits_file(f)
                ]
                self.main_table_widget.populate_table(filtered, show_stack_count_column=True)
            elif self.last_menu_category == "date":
                if config.TIME_DISPLAY_MODE == 'Local':
                    filtered = [
                        f for f in self.fits_files
                        if f.date_obs and to_display_time(f.date_obs).strftime('%Y-%m-%d') == self.last_menu_value
                    ]
                else:
                    filtered = [
                        f for f in self.fits_files
                        if f.date_obs and f.date_obs.strftime('%Y-%m-%d') == self.last_menu_value
                    ]
                self.main_table_widget.populate_table(filtered, show_stack_count_column=False)
        elif self.right_stack.currentIndex() == 6 and self.last_menu_category == "region":
            region = get_db_manager().get_region_by_id(int(self.last_menu_value))
            if region:
                n = self.region_detail_widget.populate(region, self._session_stack_files())
                self.left_panel.set_region_stack_count(region.id, n, region.name)
        self.update_status_bar()
        self.progress_bar.setVisible(False)
        QTimer.singleShot(250, self._release_db_file_watcher)
    
    def on_database_error(self, error_message):
        """Handle database loading errors."""
        self.status_label.setText("Database error")
        self.progress_bar.setVisible(False)
        QTimer.singleShot(250, self._release_db_file_watcher)
        QMessageBox.critical(self, "Database Error", f"Failed to load database: {error_message}")

    def _release_db_file_watcher(self):
        """Re-enable QFileSystemWatcher for the DB after load finishes (avoids refresh loops with WAL)."""
        self._suppress_db_file_watcher = False

    def _session_stack_files(self):
        """All session stacks in the loaded library (for region detail / overlap checks)."""
        return [f for f in self.fits_files if paths.is_session_stack_fits_file(f)]

    def _on_region_deleted(self, region_id: int):
        """Clear region detail panel when the selected region was removed."""
        if (
            self.last_menu_category == "region"
            and self.last_menu_value == str(region_id)
        ):
            self.region_detail_widget.populate(None, [])
            self.last_menu_category = None
            self.last_menu_value = None

    def _on_region_renamed(self, region_id: int, _new_name: str):
        """Refresh region detail when the open region was renamed."""
        if (
            self.last_menu_category == "region"
            and self.last_menu_value == str(region_id)
        ):
            db = get_db_manager()
            region = db.get_region_by_id(region_id)
            if region:
                self.region_detail_widget.populate(region, self._session_stack_files())
            else:
                self.region_detail_widget.populate(None, [])
    
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
            filtered = [
                f for f in self.fits_files
                if f.target == value and not paths.is_session_stack_fits_file(f)
            ]
            self.main_table_widget.populate_table(filtered, show_stack_count_column=False)
            self.right_stack.setCurrentIndex(1)
        elif category == "followup_target":
            filtered = [
                f for f in self.fits_files
                if f.target == value and paths.is_session_stack_fits_file(f)
            ]
            self.main_table_widget.populate_table(filtered, show_stack_count_column=True)
            self.right_stack.setCurrentIndex(1)
        elif category == "date":
            if config.TIME_DISPLAY_MODE == 'Local':
                filtered = [
                    f for f in self.fits_files
                    if f.date_obs and to_display_time(f.date_obs).strftime('%Y-%m-%d') == value
                ]
            else:
                filtered = [
                    f for f in self.fits_files
                    if f.date_obs and f.date_obs.strftime('%Y-%m-%d') == value
                ]
            self.main_table_widget.populate_table(filtered, show_stack_count_column=False)
            self.right_stack.setCurrentIndex(1)
        elif category == "region":
            db = get_db_manager()
            region = db.get_region_by_id(int(value))
            if region:
                n = self.region_detail_widget.populate(region, self._session_stack_files())
                self.left_panel.set_region_stack_count(region.id, n, region.name)
            else:
                self.region_detail_widget.populate(None, [])
            self.right_stack.setCurrentIndex(6)
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
        self.left_panel.repopulate_regions()
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
        self.left_panel.repopulate_regions()
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

    def generate_session_stacks(self):
        """Generate session stacks for all follow-up targets, platesolve, and register FITS in the database."""
        from lib.gui.library.session_stacks_thread import SessionStacksBatchThread

        db = get_db_manager()
        if not db.follow_up_get_targets():
            QMessageBox.information(
                self,
                "No follow-up targets",
                "Flag one or more targets from the sidebar (right-click → Flag for follow-up) first.",
            )
            return
        if getattr(self, "_session_stacks_thread", None) and self._session_stacks_thread.isRunning():
            QMessageBox.warning(self, "Busy", "Session stack generation is already running.")
            return
        cw = ConsoleOutputWindow("Generate session stacks", self)
        cw.clear_output()
        cw.show_and_raise()
        self._session_stacks_thread = SessionStacksBatchThread()
        self._session_stacks_thread.output.connect(cw.append_text)

        def on_finished(res):
            cw.append_text("\n— Finished —\n")
            cw.close_button.setEnabled(True)
            # Defer reload so the worker thread releases SQLite before another thread queries.
            def _reload_after_batch():
                from . import db_access
                try:
                    db_access.refresh_database()
                except Exception as e:
                    print(f"refresh_database after session stacks: {e}")
                self.load_database()

            QTimer.singleShot(400, _reload_after_batch)
            errs = res.get("errors") or []
            if res.get("cancelled"):
                QMessageBox.information(self, "Cancelled", "Session stack generation was cancelled.")
            elif res.get("error"):
                QMessageBox.warning(self, "Session stacks", str(res.get("error")))
            elif errs:
                QMessageBox.warning(
                    self,
                    "Session stacks",
                    f"Completed with {len(errs)} issue(s). See the console for details.",
                )

        self._session_stacks_thread.finished.connect(on_finished)
        cw.cancel_requested.connect(self._session_stacks_thread.stop)
        self._session_stacks_thread.start()

    def generate_region_views(self):
        """Generate PNG crops for every ROI on every session stack in the field."""
        from lib.gui.library.region_views_thread import RegionViewsBatchThread

        db = get_db_manager()
        if not db.get_all_regions():
            QMessageBox.information(
                self,
                "No regions",
                "Define at least one region of interest in the FITS viewer first.",
            )
            return
        if getattr(self, "_region_views_thread", None) and self._region_views_thread.isRunning():
            QMessageBox.warning(self, "Busy", "Region view generation is already running.")
            return
        cw = ConsoleOutputWindow("Generate region views", self)
        cw.clear_output()
        cw.show_and_raise()
        self._region_views_thread = RegionViewsBatchThread()
        self._region_views_thread.output.connect(cw.append_text)

        def on_finished(res):
            cw.append_text("\n— Finished —\n")
            cw.close_button.setEnabled(True)
            self.left_panel.repopulate_regions()
            if self.last_menu_category == "region" and self.last_menu_value:
                region = get_db_manager().get_region_by_id(int(self.last_menu_value))
                if region:
                    n = self.region_detail_widget.populate(region, self._session_stack_files())
                    self.left_panel.set_region_stack_count(region.id, n, region.name)
            gen = res.get("generated", 0)
            skip = res.get("skipped", 0)
            errs = res.get("errors") or []
            if res.get("cancelled"):
                QMessageBox.information(self, "Cancelled", "Region view generation was cancelled.")
            elif res.get("error"):
                QMessageBox.warning(self, "Region views", str(res.get("error")))
            elif errs:
                QMessageBox.warning(
                    self,
                    "Region views",
                    f"Done: {gen} created, {skip} skipped, {len(errs)} error(s). See console.",
                )
            else:
                QMessageBox.information(
                    self,
                    "Region views",
                    f"Generated {gen} PNG(s), skipped {skip} existing.",
                )

        self._region_views_thread.finished.connect(on_finished)
        cw.cancel_requested.connect(self._region_views_thread.stop)
        self._region_views_thread.start()

    def latest_regions_update(self):
        """Copy oldest and newest region-view PNGs for the latest observing session."""
        from lib.gui.library.latest_regions_update_thread import LatestRegionsUpdateThread

        if getattr(self, "_latest_regions_thread", None) and self._latest_regions_thread.isRunning():
            QMessageBox.warning(self, "Busy", "Latest regions update is already running.")
            return
        cw = ConsoleOutputWindow("Latest regions update", self)
        cw.clear_output()
        cw.show_and_raise()
        self._latest_regions_thread = LatestRegionsUpdateThread()
        self._latest_regions_thread.output.connect(cw.append_text)

        def on_finished(res):
            cw.append_text("\n— Finished —\n")
            cw.close_button.setEnabled(True)
            if res.get("error"):
                QMessageBox.warning(self, "Latest regions update", str(res.get("error")))
            elif res.get("errors"):
                QMessageBox.warning(
                    self,
                    "Latest regions update",
                    f"Copied {res.get('copied', 0)} file(s) with {len(res['errors'])} error(s). See console.",
                )
            else:
                QMessageBox.information(
                    self,
                    "Latest regions update",
                    f"Copied {res.get('copied', 0)} PNG(s) to\n{res.get('dest_dir')}\n"
                    f"(session {res.get('session_date')}).",
                )

        self._latest_regions_thread.finished.connect(on_finished)
        self._latest_regions_thread.start()

    def cleanup_temp_directories(self):
        """Delete work files under PROCESSED_PATH (solved, calibrated, stacked, aligned, substacks, session_stacks_work)."""
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