#!/usr/bin/env python3
"""
Observation log table widget for displaying FITS files grouped by runs.
"""

import sys
import os
import subprocess
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QMenu, QMessageBox, QFrame, QDialog, QTextEdit, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QItemSelectionModel, QThread, pyqtSignal as Signal
from PyQt6.QtGui import QFont, QPalette, QColor, QAction
from .context_dropdown import build_single_file_menu, build_multi_file_menu, build_empty_menu, calibrate_and_compare_file, delete_files_with_confirmation
from .mpc_log_dialog import MPCLogDialog
import json
from astropy.io import fits
from lib.gui.common.header_window import HeaderViewer
from lib.fits.header import get_fits_header_as_json
import sys
import io
import threading
from contextlib import redirect_stdout, redirect_stderr
from lib.sci.platesolving import solve_single_image, PlatesolvingResult
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QMessageBox
from lib.gui.common.console_window import ConsoleOutputWindow, RealTimeStringIO
import signal
from .platesolving_thread import PlatesolvingThread
from config import to_display_time
from astropipes import VIEWER_PATH


class RunCommentDialog(QDialog):
    """Dialog for editing run comments."""
    
    def __init__(self, parent=None, initial_comment=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Run Comment")
        self.setModal(True)
        self.setFixedSize(500, 200)
        
        layout = QVBoxLayout(self)
        
        # Label
        label = QLabel("Comment:")
        layout.addWidget(label)
        
        # Text edit for comment
        self.comment_edit = QTextEdit()
        self.comment_edit.setPlaceholderText("Enter a comment for this run...")
        if initial_comment:
            self.comment_edit.setPlainText(initial_comment)
        layout.addWidget(self.comment_edit)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.accept)
        button_layout.addWidget(self.save_button)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        # Set focus to text edit
        self.comment_edit.setFocus()
    
    def get_comment(self):
        """Get the comment text."""
        text = self.comment_edit.toPlainText().strip()
        return text if text else None


def launch_viewer(fits_paths):
    """
    Launch the FITS viewer with the correct Python executable and working directory.
    
    Args:
        fits_paths: Single path string or list of path strings
    """
    # Get the project root directory
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    
    # Path to the virtual environment python
    venv_python = os.path.join(project_root, '.venv', 'bin', 'python')
    
    # Check if virtual environment exists, otherwise use system python
    if os.path.exists(venv_python):
        python_executable = venv_python
    else:
        python_executable = sys.executable
    
    # Convert single path to list if needed
    if isinstance(fits_paths, str):
        fits_paths = [fits_paths]
    
    # Launch the viewer
    try:
        subprocess.Popen([
            python_executable,
            '-m', 'lib.gui.viewer.index',
            *fits_paths
        ], cwd=project_root)
    except Exception as e:
        QMessageBox.warning(None, "Error", f"Failed to launch FITS viewer: {e}")


class RunSummaryWidget(QWidget):
    """Custom widget for displaying run summary information."""
    
    def __init__(self, run_data, parent=None):
        super().__init__(parent)
        self.run_data = run_data
        self.is_expanded = False
        self.init_ui()
    
    def init_ui(self):
        """Initialize the run summary display."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        # Create expand/collapse indicator
        self.indicator_label = QLabel("▶")  # Triangle pointing right (collapsed)
        self.indicator_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.indicator_label.setStyleSheet("color: #2c3e50; margin-right: 8px;")
        layout.addWidget(self.indicator_label)
        
        # Create summary text (without comment)
        summary_text = self._build_summary_text()
        
        # Create label with custom styling (bold)
        self.summary_label = QLabel(summary_text)
        self.summary_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(self.summary_label)
        
        # Create comment label if comment exists (darker, not bold)
        comment = self.run_data.get('comment')
        if comment:
            self.comment_label = QLabel(f" | {comment}")
            self.comment_label.setFont(QFont("Arial", 10, QFont.Weight.Normal))
            # Use a lighter gray color
            self.comment_label.setStyleSheet("color: #aaa;")
            layout.addWidget(self.comment_label)
        
        # Create badges
        badges = self.run_data.get('badges', [])
        if badges:
            for badge in badges:
                badge_label = QLabel(f" [{badge.upper()}]")
                badge_label.setFont(QFont("Arial", 9, QFont.Weight.Bold))
                if badge.lower() == 'mpc':
                    badge_label.setStyleSheet("color: #dc3545;")  # Red
                else:
                    badge_label.setStyleSheet("color: #6c757d;")  # Gray for other badges
                layout.addWidget(badge_label)
        
        layout.addStretch()
    
    def set_expanded(self, expanded):
        """Update the visual indicator based on expansion state."""
        self.is_expanded = expanded
        if expanded:
            self.indicator_label.setText("▼")  # Triangle pointing down (expanded)
        else:
            self.indicator_label.setText("▶")  # Triangle pointing right (collapsed)
    
    def _build_summary_text(self):
        """Build the summary text for the run."""
        date_time_str = self.run_data.get('date_time_str', self.run_data.get('date_str', '-'))
        target = self.run_data['target']
        count = self.run_data['count']
        filters = self.run_data['filters']
        exposures = self.run_data['exposures']
        total_minutes = self.run_data['total_minutes']
        binning = self.run_data['binning']
        comment = self.run_data.get('comment')
        
        # Format filters
        filter_str = ", ".join(sorted(set(filters))) if filters else "-"
        
        # Format exposures
        exposure_str = ", ".join([f"{exp:.1f}s" for exp in sorted(set(exposures))]) if exposures else "-"
        
        # Build base summary (without comment - comment is displayed separately)
        summary = f"{date_time_str} / {target} / {count} files / {binning} / {filter_str} / {exposure_str} / Total: {total_minutes}mn"
        
        return summary


class FitsTableWidget(QTableWidget):
    """Table widget for displaying FITS files grouped by runs."""
    
    # Custom signals
    selection_changed = pyqtSignal(list)  # Emits list of selected fits_file_ids
    platesolving_completed = pyqtSignal()
    database_refresh_requested = pyqtSignal()  # New signal for database refresh
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fits_files = []
        self.run_groups = []
        self.expanded_runs = set()  # Track which runs are expanded
        self.init_table()
    
    def init_table(self):
        """Initialize the table structure."""
        self.setColumnCount(15)
        self.setHorizontalHeaderLabels([
            "Filename", "Date obs", "Target", "Filter", "Exposure", "Bin", "Gain", "Offset", "CCD temp", "Focus", "Size", "Image Scale", "RA Center", "DEC Center", "WCS Type"
        ])
        
        # Hide row numbers (vertical header)
        self.verticalHeader().setVisible(False)
        
        # Set selection mode to select individual cells
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # Enable custom context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        
        # Disable sorting - order is fixed by date_obs
        self.setSortingEnabled(False)
        
        # Set table styling
        self.setShowGrid(True)
        self.setGridStyle(Qt.PenStyle.SolidLine)
        
        # Set column widths - all columns are manually resizable
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # Filename
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)  # Date obs (new column)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)  # Target
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)  # Filter
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)  # Exposure
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)  # Bin
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)  # Gain
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Interactive)  # Offset
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Interactive)  # CCD temp
        header.setSectionResizeMode(9, QHeaderView.ResizeMode.Interactive)  # Focus
        header.setSectionResizeMode(10, QHeaderView.ResizeMode.Interactive)  # Size
        header.setSectionResizeMode(11, QHeaderView.ResizeMode.Interactive)  # Image Scale
        header.setSectionResizeMode(12, QHeaderView.ResizeMode.Interactive)  # RA Center
        header.setSectionResizeMode(13, QHeaderView.ResizeMode.Interactive)  # DEC Center
        header.setSectionResizeMode(14, QHeaderView.ResizeMode.Interactive)  # WCS Type
        
        # Set default column widths
        self.setColumnWidth(0, 200)   # Filename
        self.setColumnWidth(1, 125)   # Date obs (new column)
        self.setColumnWidth(2, 100)   # Target
        self.setColumnWidth(3, 50)    # Filter
        self.setColumnWidth(4, 80)    # Exposure
        self.setColumnWidth(5, 60)    # Bin
        self.setColumnWidth(6, 60)    # Gain
        self.setColumnWidth(7, 60)    # Offset
        self.setColumnWidth(8, 80)    # CCD temp
        self.setColumnWidth(9, 60)    # Focus
        self.setColumnWidth(10, 80)   # Size
        self.setColumnWidth(11, 80)   # Image Scale
        self.setColumnWidth(12, 100)  # RA Center
        self.setColumnWidth(13, 100)  # DEC Center
        self.setColumnWidth(14, 80)   # WCS Type
        
        # Connect selection change and cell click
        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.cellClicked.connect(self._on_cell_clicked)
    
    RUN_TIME_WINDOW_MINUTES = 30

    def _group_files_by_runs(self, fits_files):
        """Group FITS files by runs based on stored run_id or target and time proximity."""
        if not fits_files:
            return []
        
        from lib.db import get_db_manager
        db_manager = get_db_manager()
        window = timedelta(minutes=self.RUN_TIME_WINDOW_MINUTES)
        
        # Sort files by date_obs (most recent first)
        sorted_files = sorted(fits_files, key=lambda x: x.date_obs or datetime.min, reverse=True)
        
        # First, group files that already belong to runs
        runs_by_id = {}
        unassigned_files = []
        
        for file in sorted_files:
            run_id = getattr(file, 'run_id', None)
            if run_id:
                if run_id not in runs_by_id:
                    runs_by_id[run_id] = []
                runs_by_id[run_id].append(file)
            else:
                unassigned_files.append(file)
        
        # Get run objects for existing runs and extract needed attributes
        run_objects = {}
        run_start_times = {}
        run_comments = {}
        run_badges = {}
        if runs_by_id:
            from lib.db.models import Run
            session = db_manager.get_session()
            try:
                for run_id in runs_by_id.keys():
                    run_obj = session.query(Run).filter(Run.id == run_id).first()
                    if run_obj:
                        run_objects[run_id] = run_obj
                        run_start_times[run_id] = run_obj.start_time
                        run_comments[run_id] = run_obj.comment
                        run_badges[run_id] = run_obj.badges
            finally:
                session.close()
        
        # Match unassigned files to existing runs (same target, within time window).
        # New files from the watcher then pile onto the current run instead of creating new ones.
        added_to_run = {}  # run_id -> [files]
        still_unassigned = []
        for file in unassigned_files:
            if not file.date_obs or not file.target:
                still_unassigned.append(file)
                continue
            best_run_id = None
            best_end = None
            for run_id, run_files in runs_by_id.items():
                run_obj = run_objects.get(run_id)
                if not run_obj or run_obj.target != file.target:
                    continue
                dates = [f.date_obs for f in run_files if f.date_obs]
                if not dates:
                    continue
                lo = min(dates) - window
                hi = max(dates) + window
                if not (lo <= file.date_obs <= hi):
                    continue
                end = max(dates)
                if best_end is None or end > best_end:
                    best_end = end
                    best_run_id = run_id
            if best_run_id is not None:
                if best_run_id not in added_to_run:
                    added_to_run[best_run_id] = []
                added_to_run[best_run_id].append(file)
                runs_by_id[best_run_id].append(file)
                file.run_id = best_run_id
            else:
                still_unassigned.append(file)
        
        for run_id, files_to_add in added_to_run.items():
            if files_to_add:
                ids = [f.id for f in files_to_add if hasattr(f, 'id') and f.id is not None]
                if ids:
                    db_manager.assign_files_to_run(run_id, ids)
        
        # Group remaining unassigned files by target and time proximity
        runs = []
        current_run = []
        
        for file in still_unassigned:
            if not current_run:
                current_run = [file]
            else:
                last_file = current_run[-1]
                same_target = file.target == last_file.target
                time_diff = abs((file.date_obs - last_file.date_obs).total_seconds() / 60) if file.date_obs and last_file.date_obs else float('inf')
                within_time_window = time_diff <= self.RUN_TIME_WINDOW_MINUTES
                if same_target and within_time_window:
                    current_run.append(file)
                else:
                    if current_run:
                        runs.append((None, current_run))
                    current_run = [file]
        if current_run:
            runs.append((None, current_run))
        
        final_runs = []
        for run_id, run_files in runs_by_id.items():
            run_obj = run_objects.get(run_id)
            if run_obj:
                run_obj._extracted_comment = run_comments.get(run_id)
                run_obj._extracted_badges = run_badges.get(run_id)
                # Sort by date_obs descending (most recent first)
                run_files_sorted = sorted(run_files, key=lambda f: f.date_obs or datetime.min, reverse=True)
                final_runs.append((run_obj, run_files_sorted))
        
        for run_id, run_files in runs:
            if run_files:
                target = run_files[0].target if run_files else "Unknown"
                dates = [f.date_obs for f in run_files if f.date_obs]
                if dates:
                    start_time = min(dates)
                    end_time = max(dates)
                    file_ids = [f.id for f in run_files if hasattr(f, 'id') and f.id is not None]
                    if file_ids:
                        run_obj = db_manager.create_or_get_run(target, start_time, end_time, file_ids)
                        if run_obj:
                            try:
                                run_obj._extracted_comment = run_obj.comment
                                run_obj._extracted_badges = run_obj.badges
                            except Exception:
                                run_obj._extracted_comment = None
                                run_obj._extracted_badges = None
                        final_runs.append((run_obj, run_files))
        
        def get_start_time(run_tuple):
            run_obj, files = run_tuple
            dates = [f.date_obs for f in files if f.date_obs]
            if dates:
                return min(dates)
            if run_obj and run_obj.id in run_start_times:
                return run_start_times[run_obj.id]
            return datetime.min
        
        final_runs.sort(key=get_start_time, reverse=True)
        return [(run_obj, files) for run_obj, files in final_runs]
    
    def _create_run_summary_data(self, run_obj, run_files):
        """Create summary data for a run."""
        count = len(run_files)
        target = run_files[0].target if run_files else "Unknown"
        filters = [f.filter_name for f in run_files if f.filter_name]
        exposures = [f.exptime for f in run_files if f.exptime]
        total_seconds = sum(exposures) if exposures else 0
        total_minutes = round(total_seconds / 60)
        binning = run_files[0].binning if run_files and hasattr(run_files[0], 'binning') else "-"
        # Use the oldest image (last in run_files) for date and time
        if run_files and hasattr(run_files[-1], 'date_obs') and run_files[-1].date_obs:
            dt = run_files[-1].date_obs
            if isinstance(dt, str):
                date_time_str = dt
                date_str = dt.split()[0]
            else:
                dt_disp = to_display_time(dt)
                date_time_str = dt_disp.strftime("%Y-%m-%d %H:%M:%S") if dt_disp else "-"
                date_str = dt_disp.strftime("%Y-%m-%d") if dt_disp else "-"
        else:
            date_time_str = "-"
            date_str = "-"
        
        # Get badges from run object (use extracted attribute if available)
        badges = []
        if run_obj:
            try:
                badges_str = getattr(run_obj, '_extracted_badges', None)
                if badges_str is None:
                    badges_str = run_obj.badges
                if badges_str:
                    badges = [b.strip() for b in badges_str.split(",") if b.strip()]
            except:
                pass
        
        return {
            'count': count,
            'target': target,
            'filters': filters,
            'exposures': exposures,
            'total_minutes': total_minutes,
            'binning': binning,
            'date_str': date_str,
            'date_time_str': date_time_str,
            'files': run_files,
            'run_obj': run_obj,  # Store the Run object
            'comment': getattr(run_obj, '_extracted_comment', None) if run_obj else None,
            'badges': badges
        }
    
    def populate_table(self, fits_files):
        """Populate the table with FITS files grouped by runs."""
        self.fits_files = fits_files
        self.expanded_runs.clear()
        
        # Group files by runs
        self.run_groups = self._group_files_by_runs(fits_files)
        
        # Calculate total rows needed (one row per run, plus expanded files)
        total_rows = len(self.run_groups)
        self.setRowCount(total_rows)
        
        # Set row height for run summary rows
        self.verticalHeader().setDefaultSectionSize(60)  # Double height
        
        # Populate each run as a summary row
        for row, (run_obj, run_files) in enumerate(self.run_groups):
            self._add_run_summary_row(row, run_obj, run_files)
        self._apply_striping()
        
        # Collapse all runs by default, expand only the most recent (first) run
        if self.run_groups:
            self._expand_run(0)

    def _add_run_summary_row(self, row, run_obj, run_files):
        """Add a run summary row to the table."""
        # Set double row height for run summary rows
        self.verticalHeader().setSectionResizeMode(row, QHeaderView.ResizeMode.Fixed)
        self.setRowHeight(row, 60)  # Double height
        
        # Create run summary data
        run_data = self._create_run_summary_data(run_obj, run_files)
        
        # Create custom widget for the summary
        summary_widget = RunSummaryWidget(run_data)
        
        # Set the widget to span all columns
        self.setCellWidget(row, 0, summary_widget)
        self.setSpan(row, 0, 1, self.columnCount())  # Span across all columns
        
        # Set the entire row background color and remove cell separations
        self._set_run_row_style(row)
        
        # Store the run data for selection handling
        if run_files:
            # Create a hidden item to store the run data
            hidden_item = QTableWidgetItem()
            hidden_item.setData(Qt.ItemDataRole.UserRole, {
                'run_files': run_files,
                'run_data': run_data,
                'run_obj': run_obj,
                'is_run_summary': True,
                'run_index': row
            })
            self.setItem(row, 0, hidden_item)
    
    def _set_run_row_style(self, row):
        """Set the visual style for a run summary row."""
        # Set background color for the entire row and make cells non-editable and non-selectable
        for col in range(self.columnCount()):
            item = QTableWidgetItem()
            item.setBackground(QColor(236, 240, 241))  # Light gray background
            # Make it non-editable and non-selectable
            item.setFlags(Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
            # Remove borders by setting transparent border
            item.setData(Qt.ItemDataRole.UserRole, {'is_run_cell': True})
            self.setItem(row, col, item)
    
    def _add_file_rows(self, run_index, run_files):
        """Add individual file rows for an expanded run, with striping."""
        insert_row = run_index + 1
        for i, file in enumerate(run_files):
            self.insertRow(insert_row + i)
            self._add_file_row(insert_row + i, file, run_index)
        self._apply_striping()
        # Update run indices for subsequent runs
        for row in range(insert_row + len(run_files), self.rowCount()):
            item = self.item(row, 0)
            if item:
                run_data = item.data(Qt.ItemDataRole.UserRole)
                if run_data and 'is_run_summary' in run_data:
                    run_data['run_index'] = row

    def _apply_striping(self):
        """Apply a striped effect to file rows, skipping run summary rows, with dark mode support."""
        palette = self.palette()
        base_color = palette.color(self.backgroundRole())
        is_dark = base_color.value() < 128 if hasattr(base_color, 'value') else False
        # Use dark-friendly colors if in dark mode
        color1 = QColor(40, 40, 40) if is_dark else QColor(255, 255, 255)
        color2 = QColor(55, 55, 55) if is_dark else QColor(245, 245, 245)
        file_row_index = 0
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and 'is_file' in data:
                    color = color2 if file_row_index % 2 == 1 else color1
                    for col in range(self.columnCount()):
                        cell = self.item(row, col)
                        if cell:
                            cell.setBackground(color)
                            # Only set foreground if not already colored (i.e., default brush), and skip filter column (2)
                            if is_dark and (col != 3 or cell.foreground().color() == QColor()):
                                cell.setForeground(QColor(230, 230, 230))
                    file_row_index += 1
    
    def _add_file_row(self, row, fits_file, parent_run_index):
        """Add a single file row."""
        # Set normal row height for file rows
        self.verticalHeader().setSectionResizeMode(row, QHeaderView.ResizeMode.Fixed)
        self.setRowHeight(row, 30)  # Normal height
        
        # Filename (extract from path)
        filename = os.path.basename(fits_file.path)
        filename_item = QTableWidgetItem(filename)
        filename_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        filename_item.setToolTip(fits_file.path)
        # Store file data in the filename item
        filename_item.setData(Qt.ItemDataRole.UserRole, {
            'fits_file': fits_file,
            'is_file': True,
            'parent_run_index': parent_run_index
        })
        self.setItem(row, 0, filename_item)
        
        # Date obs (new column)
        if hasattr(fits_file, 'date_obs') and fits_file.date_obs:
            if isinstance(fits_file.date_obs, str):
                date_obs_str = fits_file.date_obs
            else:
                dt_disp = to_display_time(fits_file.date_obs)
                date_obs_str = dt_disp.strftime("%Y-%m-%d %H:%M:%S") if dt_disp else "-"
        else:
            date_obs_str = "-"
        date_obs_item = QTableWidgetItem(date_obs_str)
        date_obs_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 1, date_obs_item)
        
        # Target
        target = fits_file.target or "-"
        target_item = QTableWidgetItem(target)
        target_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 2, target_item)
        
        # Filter
        filter_name = fits_file.filter_name or "-"
        filter_item = QTableWidgetItem(filter_name)
        filter_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        # Set foreground color for the filter cell only
        filter_name_upper = (fits_file.filter_name or "").upper()
        if filter_name_upper == 'R':
            filter_item.setForeground(QColor(220, 30, 30))  # Red
        elif filter_name_upper == 'G':
            filter_item.setForeground(QColor(30, 180, 30))  # Green
        elif filter_name_upper == 'B':
            filter_item.setForeground(QColor(30, 80, 220))  # Blue
        # L or others: leave as default (white/system)
        self.setItem(row, 3, filter_item)
        
        # Exposure time
        if fits_file.exptime:
            exposure_str = f"{fits_file.exptime:.1f}s"
        else:
            exposure_str = "-"
        exposure_item = QTableWidgetItem(exposure_str)
        exposure_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 4, exposure_item)
        
        # Bin
        binning = fits_file.binning or "-"
        binning_item = QTableWidgetItem(binning)
        binning_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 5, binning_item)
        
        # Gain
        if fits_file.gain:
            gain_str = f"{fits_file.gain:.1f}"
        else:
            gain_str = "-"
        gain_item = QTableWidgetItem(gain_str)
        gain_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 6, gain_item)
        
        # Offset
        if fits_file.offset:
            offset_str = f"{fits_file.offset:.1f}"
        else:
            offset_str = "-"
        offset_item = QTableWidgetItem(offset_str)
        offset_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 7, offset_item)
        
        # CCD temperature
        temp_item = QTableWidgetItem(f"{fits_file.ccd_temp:.1f}°C" if fits_file.ccd_temp is not None else "-")
        temp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 8, temp_item)
        
        # Focus
        focus_item = QTableWidgetItem(str(int(fits_file.focus_position)) if fits_file.focus_position is not None else "-")
        focus_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 9, focus_item)
        
        # Image size (X x Y)
        if fits_file.size_x and fits_file.size_y:
            size_str = f"{fits_file.size_x} × {fits_file.size_y}"
        else:
            size_str = "-"
        size_item = QTableWidgetItem(size_str)
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 10, size_item)
        
        # Image scale
        if fits_file.image_scale:
            scale_str = f"{fits_file.image_scale:.2f}\""
        else:
            scale_str = "-"
        scale_item = QTableWidgetItem(scale_str)
        scale_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 11, scale_item)
        
        # RA Center
        if fits_file.ra_center:
            # Convert decimal degrees to hours:minutes:seconds
            ra_hours = fits_file.ra_center / 15.0  # Convert degrees to hours
            ra_h = int(ra_hours)
            ra_m = int((ra_hours - ra_h) * 60)
            ra_s = ((ra_hours - ra_h - ra_m/60) * 3600)
            ra_str = f"{ra_h:02d}:{ra_m:02d}:{ra_s:05.2f}"
        else:
            ra_str = "-"
        ra_item = QTableWidgetItem(ra_str)
        ra_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 12, ra_item)
        
        # DEC Center
        if fits_file.dec_center:
            # Convert decimal degrees to degrees:minutes:seconds
            dec_deg = fits_file.dec_center
            dec_sign = "+" if dec_deg >= 0 else "-"
            dec_deg_abs = abs(dec_deg)
            dec_d = int(dec_deg_abs)
            dec_m = int((dec_deg_abs - dec_d) * 60)
            dec_s = ((dec_deg_abs - dec_d - dec_m/60) * 3600)
            dec_str = f"{dec_sign}{dec_d:02d}:{dec_m:02d}:{dec_s:04.1f}"
        else:
            dec_str = "-"
        dec_item = QTableWidgetItem(dec_str)
        dec_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 13, dec_item)
        
        # WCS Type
        wcs_type = fits_file.wcs_type or "-"
        wcs_item = QTableWidgetItem(wcs_type)
        wcs_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 14, wcs_item)
    
    def _on_cell_clicked(self, row, column):
        """Handle cell clicks for expanding/collapsing runs."""
        item = self.item(row, 0)
        if item:
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and 'is_run_summary' in data:
                # Use the actual row argument, not data['run_index']
                if row in self.expanded_runs:
                    self._collapse_run(row)
                else:
                    self._expand_run(row)
    
    def _reindex_run_summaries(self):
        """Update run_index for all run summary rows to match their current row number."""
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item:
                run_data = item.data(Qt.ItemDataRole.UserRole)
                if run_data and 'is_run_summary' in run_data:
                    run_data['run_index'] = row

    def _expand_run(self, run_index):
        """Expand a run to show individual files."""
        if run_index in self.expanded_runs:
            return
        
        # Find the run data
        item = self.item(run_index, 0)
        if not item:
            return
        
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or 'run_files' not in data:
            return
        
        run_files = data['run_files']
        
        # Update the visual indicator
        widget = self.cellWidget(run_index, 0)
        if widget and hasattr(widget, 'set_expanded'):
            widget.set_expanded(True)
        
        # Add file rows
        self._add_file_rows(run_index, run_files)
        
        # Mark as expanded
        self.expanded_runs.add(run_index)
        self._reindex_run_summaries()

    def _collapse_run(self, run_index):
        """Collapse a run to hide individual files."""
        if run_index not in self.expanded_runs:
            return
        
        # Find the run data
        item = self.item(run_index, 0)
        if not item:
            return
        
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or 'run_files' not in data:
            return
        
        run_files = data['run_files']
        
        # Update the visual indicator
        widget = self.cellWidget(run_index, 0)
        if widget and hasattr(widget, 'set_expanded'):
            widget.set_expanded(False)
        
        # Remove file rows
        start_row = run_index + 1
        end_row = start_row + len(run_files)
        
        for _ in range(len(run_files)):
            self.removeRow(start_row)
        
        # Update run_index for all run summary rows below
        for row in range(run_index + 1, self.rowCount()):
            item = self.item(row, 0)
            if item:
                run_data = item.data(Qt.ItemDataRole.UserRole)
                if run_data and 'is_run_summary' in run_data:
                    run_data['run_index'] = row
        
        # Mark as collapsed
        self.expanded_runs.discard(run_index)
        self._apply_striping()
        self._reindex_run_summaries()
    
    def _on_selection_changed(self):
        """Handle table selection changes and prevent run summary rows from being selected or highlighted."""
        selected_indexes = self.selectedIndexes()
        valid_rows = set()
        selected_file_ids = []
        
        for index in selected_indexes:
            item = self.item(index.row(), 0)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and 'is_file' in data and 'fits_file' in data:
                    valid_rows.add(index.row())
                    selected_file_ids.append(data['fits_file'].id)
        
        # Block signals to avoid recursion
        self.blockSignals(True)
        self.clearSelection()
        for row in valid_rows:
            for col in range(self.columnCount()):
                self.item(row, col).setSelected(True)
        self.blockSignals(False)
        
        # Emit only valid file selections
        self.selection_changed.emit(selected_file_ids)
    
    def get_selected_fits_file_ids(self):
        """Get the IDs of all selected FITS files."""
        selected_rows = self.selectionModel().selectedRows()
        selected_file_ids = []
        
        for row in selected_rows:
            item = self.item(row.row(), 0)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data:
                    if 'is_run_summary' in data and 'run_files' in data:
                        selected_file_ids.extend([f.id for f in data['run_files']])
                    elif 'is_file' in data and 'fits_file' in data:
                        selected_file_ids.append(data['fits_file'].id)
        
        return selected_file_ids
    
    def get_selected_fits_files(self):
        """Get all selected FITS file objects."""
        selected_file_ids = self.get_selected_fits_file_ids()
        return [f for f in self.fits_files if f.id in selected_file_ids]
    
    def clear_selection(self):
        """Clear the current selection."""
        self.clearSelection()
    
    def refresh_table(self):
        """Refresh the table display."""
        if self.fits_files:
            self.populate_table(self.fits_files) 

    def get_visible_file_count(self):
        """Return the number of file rows currently visible (not run summary rows)."""
        count = 0
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and 'is_file' in data:
                    count += 1
        return count

    def _format_platesolving_result(self, result):
        """Format platesolving result into a user-friendly message."""
        if result.success:
            success_msg = "Image successfully solved!\n\n"
            if result.ra_center is not None and result.dec_center is not None:
                success_msg += f"Center: RA={result.ra_center:.4f}°, Dec={result.dec_center:.4f}°\n"
            else:
                success_msg += "Center: Unknown\n"
            if result.pixel_scale is not None:
                success_msg += f"Pixel scale: {result.pixel_scale:.3f} arcsec/pixel\n"
            else:
                success_msg += "Pixel scale: Unknown\n"
            return success_msg
        else:
            return f"Could not solve image: {result.message}"

    def _on_platesolving_finished(self, result):
        """Handle platesolving completion."""
        if result.success:
            QMessageBox.information(self, "Platesolving Success", self._format_platesolving_result(result))
            # Emit signal to reload database
            self.platesolving_completed.emit()
        else:
            QMessageBox.warning(self, "Platesolving Failed", self._format_platesolving_result(result))

    def _show_context_menu(self, pos):
        """Show a context menu depending on the selection."""
        # Check if right-clicking on a run summary row
        item = self.itemAt(pos)
        if item:
            row = item.row()
            row_item = self.item(row, 0)
            if row_item:
                data = row_item.data(Qt.ItemDataRole.UserRole)
                if data and 'is_run_summary' in data and 'run_obj' in data:
                    # Right-clicked on a run summary row
                    run_obj = data.get('run_obj')
                    if run_obj:
                        def edit_comment():
                            # Get comment from extracted attribute or try to access it
                            initial_comment = getattr(run_obj, '_extracted_comment', None)
                            if initial_comment is None:
                                try:
                                    initial_comment = run_obj.comment
                                except:
                                    initial_comment = None
                            
                            dialog = RunCommentDialog(self, initial_comment=initial_comment)
                            if dialog.exec() == QDialog.DialogCode.Accepted:
                                new_comment = dialog.get_comment()
                                from lib.db import get_db_manager
                                db_manager = get_db_manager()
                                # Get run_id - use id attribute or try to access it
                                run_id = getattr(run_obj, 'id', None)
                                if run_id is None:
                                    try:
                                        run_id = run_obj.id
                                    except:
                                        # Can't get run_id, skip
                                        return
                                
                                if db_manager.update_run_comment(run_id, new_comment):
                                    # Refresh the table to show updated comment
                                    self.refresh_table()
                                    # Emit signal to refresh database
                                    self.database_refresh_requested.emit()
                        
                        def add_to_mpc_log():
                            """Add the run to MPC log."""
                            run_data = data.get('run_data', {})
                            run_files = data.get('run_files', [])
                            
                            if not run_files:
                                QMessageBox.warning(self, "No Files", "This run has no files.")
                                return
                            
                            # Get target name from run data
                            target_name = run_data.get('target', 'Unknown')
                            
                            # Get current comment from run
                            initial_comment = getattr(run_obj, '_extracted_comment', None)
                            if initial_comment is None:
                                try:
                                    initial_comment = run_obj.comment
                                except:
                                    initial_comment = None
                            
                            # Open MPC log dialog
                            dialog = MPCLogDialog(self, target_name=target_name, initial_comment=initial_comment)
                            if dialog.exec() == QDialog.DialogCode.Accepted:
                                # Validate input (validate before processing)
                                valid, error_msg = dialog.validate()
                                if not valid:
                                    QMessageBox.warning(self, "Invalid Input", error_msg)
                                    return
                                
                                # Get values from dialog
                                motion = dialog.get_motion()
                                magnitude = dialog.get_magnitude()
                                status = dialog.get_status()
                                comment = dialog.get_comment()
                                
                                # Get db_manager
                                from lib.db import get_db_manager
                                db_manager = get_db_manager()
                                
                                # Update run comment if provided
                                run_id = getattr(run_obj, 'id', None)
                                if run_id is None:
                                    try:
                                        run_id = run_obj.id
                                    except:
                                        pass
                                if run_id:
                                    db_manager.update_run_comment(run_id, comment)
                                
                                # Get run data
                                # Observation date is start of observation (oldest file)
                                dates = [f.date_obs for f in run_files if f.date_obs]
                                if not dates:
                                    QMessageBox.warning(self, "Error", "Could not determine observation date.")
                                    return
                                observation_date = min(dates)
                                
                                # Get coordinates from first image (oldest)
                                first_file = min(run_files, key=lambda f: f.date_obs if f.date_obs else datetime.max)
                                ra_center = first_file.ra_center
                                dec_center = first_file.dec_center
                                
                                # Get number of images
                                num_images = len(run_files)
                                
                                # Get single exposure (use first file's exposure)
                                single_exposure = first_file.exptime if first_file.exptime else None
                                
                                # Calculate total exposure
                                exposures = [f.exptime for f in run_files if f.exptime]
                                total_exposure = sum(exposures) if exposures else None
                                
                                # Get comment from run (now updated with dialog value)
                                # Re-fetch the run to get the updated comment
                                if run_id:
                                    updated_run = db_manager.get_run_by_id(run_id)
                                    if updated_run:
                                        comment = updated_run.comment
                                    else:
                                        comment = None
                                else:
                                    comment = None
                                
                                # Prepare MPC log data
                                
                                mpc_data = {
                                    'observation_date': observation_date,
                                    'target_name': target_name,
                                    'ra_center': ra_center,
                                    'dec_center': dec_center,
                                    'num_images': num_images,
                                    'single_exposure': single_exposure,
                                    'total_exposure': total_exposure,
                                    'magnitude': magnitude,
                                    'motion': motion,
                                    'status': status,
                                    'comment': comment
                                }
                                
                                try:
                                    db_manager.add_mpc_log_entry(mpc_data)
                                    # Add MPC badge to the run
                                    if run_id:
                                        db_manager.add_run_badge(run_id, "mpc")
                                    QMessageBox.information(self, "Success", "Observation added to MPC log successfully.")
                                    # Refresh the table to show the badge
                                    self.refresh_table()
                                    self.database_refresh_requested.emit()
                                except Exception as e:
                                    QMessageBox.critical(self, "Error", f"Failed to add observation to MPC log:\n{str(e)}")
                        
                        def clear_badges():
                            """Clear all badges from the run."""
                            run_id = getattr(run_obj, 'id', None)
                            if run_id is None:
                                try:
                                    run_id = run_obj.id
                                except:
                                    QMessageBox.warning(self, "Error", "Could not get run ID.")
                                    return
                            
                            from lib.db import get_db_manager
                            db_manager = get_db_manager()
                            if db_manager.clear_run_badges(run_id):
                                QMessageBox.information(self, "Success", "Badges cleared successfully.")
                                # Refresh the table
                                self.refresh_table()
                                self.database_refresh_requested.emit()
                            else:
                                QMessageBox.warning(self, "Error", "Failed to clear badges.")
                        
                        menu = QMenu(self)
                        edit_comment_action = QAction("Edit comment", menu)
                        edit_comment_action.triggered.connect(edit_comment)
                        menu.addAction(edit_comment_action)
                        
                        menu.addSeparator()
                        
                        add_mpc_action = QAction("Add to MPC log", menu)
                        add_mpc_action.triggered.connect(add_to_mpc_log)
                        menu.addAction(add_mpc_action)
                        
                        menu.addSeparator()
                        
                        clear_badges_action = QAction("Clear Badges", menu)
                        clear_badges_action.triggered.connect(clear_badges)
                        menu.addAction(clear_badges_action)
                        
                        menu.exec(self.viewport().mapToGlobal(pos))
                        return
        
        selected_files = self.get_selected_fits_files()
        if len(selected_files) == 1:
            def show_header():
                fits_file = selected_files[0]
                # Load header using the shared utility
                try:
                    header = get_fits_header_as_json(fits_file.path)
                except Exception as e:
                    header = {"Error": str(e)}
                dlg = HeaderViewer(header, fits_file.path, self)
                dlg.exec()
            def show_image():
                fits_file = selected_files[0]
                launch_viewer([fits_file.path])
            def solve_image():
                fits_file = selected_files[0]
                fits_path = fits_file.path
                
                # Create console output window
                self.console_window = ConsoleOutputWindow("Platesolving Console", self)
                self.console_window.show_and_raise()
                
                # Create and start the platesolving thread
                self.platesolving_thread = PlatesolvingThread(fits_path)
                self.platesolving_thread.output.connect(self.console_window.append_text)
                self.platesolving_thread.finished.connect(self._on_platesolving_finished)
                # Connect cancel button
                self.console_window.cancel_requested.connect(self.platesolving_thread.stop)
                
                self.platesolving_thread.start()
            
            def calibrate_and_compare():
                fits_file = selected_files[0]
                
                def show_file_in_viewer(file_path):
                    launch_viewer([file_path])
                
                def show_both_files_in_viewer(original_path, calibrated_path):
                    launch_viewer([original_path, calibrated_path])
                
                calibrate_and_compare_file(self, fits_file, show_image_callback=show_file_in_viewer, show_both_callback=show_both_files_in_viewer)
            
            def delete_file():
                delete_files_with_confirmation(self, selected_files, on_deletion_complete=self.database_refresh_requested.emit)
            
            menu = build_single_file_menu(self, show_header_callback=show_header, show_image_callback=show_image, solve_image_callback=solve_image, calibrate_and_compare_callback=calibrate_and_compare, delete_file_callback=delete_file)
        elif len(selected_files) > 1:
            from .context_dropdown import platesolve_multiple_files
            def load_in_viewer():
                # Sort selected_files by date_obs (oldest to newest)
                sorted_files = sorted(selected_files, key=lambda f: f.date_obs or '')
                fits_paths = [f.path for f in sorted_files]
                launch_viewer(fits_paths)
            def platesolve_all():
                platesolve_multiple_files(self, selected_files, on_all_finished=lambda results: self.platesolving_completed.emit())
            def delete_files():
                delete_files_with_confirmation(self, selected_files, on_deletion_complete=self.database_refresh_requested.emit)
            menu = build_multi_file_menu(self, load_in_viewer_callback=load_in_viewer, platesolve_all_callback=platesolve_all, delete_files_callback=delete_files)
        else:
            menu = build_empty_menu(self)
        menu.exec(self.viewport().mapToGlobal(pos)) 

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.pos())
        if item:
            data = self.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
            if data and 'is_file' in data and 'fits_file' in data:
                fits_file = data['fits_file']
                fits_path = fits_file.path
                launch_viewer([fits_path])
        super().mouseDoubleClickEvent(event) 