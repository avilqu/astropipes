#!/usr/bin/env python3
"""
Table widget for displaying FITS files in a flat, sortable table (no run grouping).
"""

import os
import sys
import subprocess
from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSignal as Signal
from PyQt6.QtGui import QColor
from .context_dropdown import build_single_file_menu, build_multi_file_menu, build_empty_menu, calibrate_and_compare_file, delete_files_with_confirmation
from lib.gui.common.header_window import HeaderViewer
from lib.gui.common.console_window import ConsoleOutputWindow
from lib.fits.header import get_fits_header_as_json
import sys
import io
import threading
from contextlib import redirect_stdout, redirect_stderr
from lib.sci.platesolving import solve_single_image, PlatesolvingResult
import signal
from .platesolving_thread import PlatesolvingThread
from config import to_display_time
from astropipes import VIEWER_PATH

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

class MainFitsTableWidget(QTableWidget):
    """Table widget for displaying FITS files in a flat, sortable table."""
    selection_changed = pyqtSignal(list)  # Emits list of selected fits_file_ids
    platesolving_completed = pyqtSignal()
    database_refresh_requested = pyqtSignal()  # New signal for database refresh

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fits_files = []
        self.init_table()

    def init_table(self):
        self.setColumnCount(15)
        self.setHorizontalHeaderLabels([
            "Filename", "Date obs", "Target", "Filter", "Exposure", "Bin", "Gain", "Offset", "CCD temp", "Focus", "Size", "Image Scale", "RA Center", "DEC Center", "WCS Type"
        ])
        # self.verticalHeader().setVisible(False)  # Remove this line to show the vertical header
        self.verticalHeader().setVisible(True)     # Show the vertical header
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setSortingEnabled(True)
        self.setShowGrid(True)
        self.setGridStyle(Qt.PenStyle.SolidLine)
        header = self.horizontalHeader()
        for i in range(self.columnCount()):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        self.setColumnWidth(0, 200)   # Filename
        self.setColumnWidth(1, 140)   # Date obs
        self.setColumnWidth(2, 100)   # Target
        self.setColumnWidth(3, 50)    # Filter
        self.setColumnWidth(4, 80)    # Exposure
        self.setColumnWidth(5, 60)    # Bin
        self.setColumnWidth(6, 60)    # Gain
        self.setColumnWidth(7, 60)    # Offset
        self.setColumnWidth(8, 80)    # CCD temp
        self.setColumnWidth(9, 60)   # Focus
        self.setColumnWidth(10, 80)   # Size
        self.setColumnWidth(11, 80)   # Image Scale
        self.setColumnWidth(12, 100)  # RA Center
        self.setColumnWidth(13, 100)  # DEC Center
        self.setColumnWidth(14, 80)   # WCS Type
        self.itemSelectionChanged.connect(self._on_selection_changed)

    def populate_table(self, fits_files):
        self.fits_files = fits_files
        self.blockSignals(True)  # Prevent selection events during repopulation
        self.clearSelection()
        self.setRowCount(0)  # Clear all rows
        # Sort by date_obs descending by default
        sorted_files = sorted(fits_files, key=lambda f: f.date_obs or '', reverse=True)
        self.setRowCount(len(sorted_files))
        self.verticalHeader().setDefaultSectionSize(30)
        for row, fits_file in enumerate(sorted_files):
            self._add_file_row(row, fits_file)
        # Set vertical header labels to row numbers (1-based)
        self.setVerticalHeaderLabels([str(i+1) for i in range(len(sorted_files))])
        self._apply_striping()
        self.sortItems(1, Qt.SortOrder.DescendingOrder)
        self.blockSignals(False)

    def _add_file_row(self, row, fits_file):
        filename = os.path.basename(fits_file.path)
        filename_item = QTableWidgetItem(filename)
        filename_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        filename_item.setToolTip(fits_file.path)
        filename_item.setData(Qt.ItemDataRole.UserRole, {'fits_file': fits_file, 'is_file': True})
        self.setItem(row, 0, filename_item)
        # Date obs
        if fits_file.date_obs:
            dt_disp = to_display_time(fits_file.date_obs)
            date_str = dt_disp.strftime('%Y-%m-%d %H:%M:%S') if dt_disp else "-"
        else:
            date_str = "-"
        date_item = QTableWidgetItem(date_str)
        date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 1, date_item)
        # Target
        target = fits_file.target or "-"
        target_item = QTableWidgetItem(target)
        target_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 2, target_item)
        filter_name = fits_file.filter_name or "-"
        filter_item = QTableWidgetItem(filter_name)
        filter_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        # Set color based on filter
        if filter_name.upper() == 'R':
            filter_item.setForeground(QColor(220, 30, 30))  # Red
        elif filter_name.upper() == 'G':
            filter_item.setForeground(QColor(30, 180, 30))  # Green
        elif filter_name.upper() == 'B':
            filter_item.setForeground(QColor(30, 80, 220))  # Blue
        # L or others: leave as default (white/system)
        self.setItem(row, 3, filter_item)
        if fits_file.exptime:
            exposure_str = f"{fits_file.exptime:.1f}s"
        else:
            exposure_str = "-"
        exposure_item = QTableWidgetItem(exposure_str)
        exposure_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 4, exposure_item)
        binning = fits_file.binning or "-"
        binning_item = QTableWidgetItem(binning)
        binning_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 5, binning_item)
        if fits_file.gain:
            gain_str = f"{fits_file.gain:.1f}"
        else:
            gain_str = "-"
        gain_item = QTableWidgetItem(gain_str)
        gain_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 6, gain_item)
        if fits_file.offset:
            offset_str = f"{fits_file.offset:.1f}"
        else:
            offset_str = "-"
        offset_item = QTableWidgetItem(offset_str)
        offset_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 7, offset_item)
        if fits_file.ccd_temp:
            temp_str = f"{fits_file.ccd_temp:.1f}°C"
        else:
            temp_str = "-"
        temp_item = QTableWidgetItem(temp_str)
        temp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 8, temp_item)
        focus_item = QTableWidgetItem(str(int(fits_file.focus_position)) if fits_file.focus_position is not None else "-")
        focus_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 9, focus_item)
        if fits_file.size_x and fits_file.size_y:
            size_str = f"{fits_file.size_x} × {fits_file.size_y}"
        else:
            size_str = "-"
        size_item = QTableWidgetItem(size_str)
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 10, size_item)
        if fits_file.image_scale:
            scale_str = f"{fits_file.image_scale:.2f}\""
        else:
            scale_str = "-"
        scale_item = QTableWidgetItem(scale_str)
        scale_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 11, scale_item)
        if fits_file.ra_center:
            ra_hours = fits_file.ra_center / 15.0
            ra_h = int(ra_hours)
            ra_m = int((ra_hours - ra_h) * 60)
            ra_s = ((ra_hours - ra_h - ra_m/60) * 3600)
            ra_str = f"{ra_h:02d}:{ra_m:02d}:{ra_s:05.2f}"
        else:
            ra_str = "-"
        ra_item = QTableWidgetItem(ra_str)
        ra_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 12, ra_item)
        if fits_file.dec_center:
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
        wcs_type = fits_file.wcs_type or "-"
        wcs_item = QTableWidgetItem(wcs_type)
        wcs_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 14, wcs_item)

        # Set foreground color for the filter cell only
        filter_name_upper = (fits_file.filter_name or "").upper()
        if filter_name_upper == 'R':
            filter_item.setForeground(QColor(220, 30, 30))  # Red
        elif filter_name_upper == 'G':
            filter_item.setForeground(QColor(30, 180, 30))  # Green
        elif filter_name_upper == 'B':
            filter_item.setForeground(QColor(30, 80, 220))  # Blue
        # L or others: leave as default (white/system)

    def _apply_striping(self):
        palette = self.palette()
        base_color = palette.color(self.backgroundRole())
        is_dark = base_color.value() < 128 if hasattr(base_color, 'value') else False
        color1 = QColor(40, 40, 40) if is_dark else QColor(255, 255, 255)
        color2 = QColor(55, 55, 55) if is_dark else QColor(245, 245, 245)
        for row in range(self.rowCount()):
            color = color2 if row % 2 == 1 else color1
            for col in range(self.columnCount()):
                cell = self.item(row, col)
                if cell:
                    cell.setBackground(color)
                    # Only set foreground if not already colored (i.e., default brush)
                    if is_dark and cell.foreground().color() == QColor():
                        cell.setForeground(QColor(230, 230, 230))

    def _on_selection_changed(self):
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
        self.blockSignals(True)
        self.clearSelection()
        for row in valid_rows:
            for col in range(self.columnCount()):
                self.item(row, col).setSelected(True)
        self.blockSignals(False)
        self.selection_changed.emit(selected_file_ids)

    def get_selected_fits_file_ids(self):
        selected_rows = self.selectionModel().selectedRows()
        selected_file_ids = []
        for row in selected_rows:
            item = self.item(row.row(), 0)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and 'is_file' in data and 'fits_file' in data:
                    selected_file_ids.append(data['fits_file'].id)
        return selected_file_ids

    def get_selected_fits_files(self):
        selected_file_ids = self.get_selected_fits_file_ids()
        return [f for f in self.fits_files if f.id in selected_file_ids]

    def clear_selection(self):
        self.clearSelection()

    def refresh_table(self):
        if self.fits_files:
            self.populate_table(self.fits_files)

    def get_visible_file_count(self):
        """Return the number of file rows currently visible."""
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
        selected_files = self.get_selected_fits_files()
        if len(selected_files) == 1:
            def show_header():
                fits_file = selected_files[0]
                try:
                    header = get_fits_header_as_json(fits_file.path)
                except Exception as e:
                    header = {"Error": str(e)}
                dlg = HeaderViewer(header, fits_file.path, self)
                dlg.exec()
            def show_image():
                fits_file = selected_files[0]
                fits_path = fits_file.path
                launch_viewer([fits_path])
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