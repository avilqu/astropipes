#!/usr/bin/env python3
"""
Table widget for displaying Minor Planet Center (MPC) observation log entries.
"""

from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QMessageBox
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QAction
from lib.db import get_db_manager
from lib.db.models import MPCLog
from config import to_display_time


class MPCLogTableWidget(QTableWidget):
    """Table widget for displaying MPC log entries."""
    
    # Signal emitted when database should be refreshed
    database_refresh_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mpc_entries = []
        self.init_table()
    
    def init_table(self):
        """Initialize the table structure."""
        self.setColumnCount(11)
        self.setHorizontalHeaderLabels([
            "Date", "Target", "RA", "DEC", "Images", "Total Exp (s)", 
            "Single Exp (s)", "Motion (\"/mn)", "Magnitude", "Status", "Comment"
        ])
        
        # Hide row numbers (vertical header)
        self.verticalHeader().setVisible(False)
        
        # Set selection mode
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # Enable sorting
        self.setSortingEnabled(True)
        
        # Set table styling
        self.setShowGrid(True)
        self.setGridStyle(Qt.PenStyle.SolidLine)
        
        # Set column widths - all columns are manually resizable
        header = self.horizontalHeader()
        for col in range(self.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        
        # Set default column widths
        self.setColumnWidth(0, 150)   # Date
        self.setColumnWidth(1, 150)   # Target
        self.setColumnWidth(2, 100)   # RA
        self.setColumnWidth(3, 100)   # DEC
        self.setColumnWidth(4, 70)    # Images
        self.setColumnWidth(5, 100)   # Total Exp
        self.setColumnWidth(6, 100)   # Single Exp
        self.setColumnWidth(7, 100)   # Motion
        self.setColumnWidth(8, 80)    # Magnitude
        self.setColumnWidth(9, 80)    # Status
        self.setColumnWidth(10, 200)  # Comment
        
        # Enable custom context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
    
    def populate(self, mpc_entries):
        """Populate the table with MPC log entries.
        
        Args:
            mpc_entries: List of MPCLog objects
        """
        self.mpc_entries = mpc_entries
        self.setRowCount(len(mpc_entries))
        
        for row, entry in enumerate(mpc_entries):
            # Date
            if entry.observation_date:
                dt_disp = to_display_time(entry.observation_date)
                date_str = dt_disp.strftime("%Y-%m-%d %H:%M:%S") if dt_disp else "-"
            else:
                date_str = "-"
            date_item = QTableWidgetItem(date_str)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 0, date_item)
            
            # Target
            target = entry.target_name or "-"
            target_item = QTableWidgetItem(target)
            target_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 1, target_item)
            
            # RA (format as hours:minutes:seconds)
            if entry.ra_center is not None:
                ra_hours = entry.ra_center / 15.0  # Convert degrees to hours
                ra_h = int(ra_hours)
                ra_m = int((ra_hours - ra_h) * 60)
                ra_s = ((ra_hours - ra_h - ra_m/60) * 3600)
                ra_str = f"{ra_h:02d}:{ra_m:02d}:{ra_s:05.2f}"
            else:
                ra_str = "-"
            ra_item = QTableWidgetItem(ra_str)
            ra_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 2, ra_item)
            
            # DEC (format as degrees:minutes:seconds)
            if entry.dec_center is not None:
                dec_deg = entry.dec_center
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
            self.setItem(row, 3, dec_item)
            
            # Number of images
            num_images = entry.num_images if entry.num_images is not None else 0
            num_images_item = QTableWidgetItem(str(num_images))
            num_images_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 4, num_images_item)
            
            # Total exposure (column 5)
            if entry.total_exposure is not None:
                total_exp_str = f"{entry.total_exposure:.1f}"
            else:
                total_exp_str = "-"
            total_exp_item = QTableWidgetItem(total_exp_str)
            total_exp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 5, total_exp_item)
            
            # Single exposure (column 6)
            if entry.single_exposure is not None:
                single_exp_str = f"{entry.single_exposure:.1f}"
            else:
                single_exp_str = "-"
            single_exp_item = QTableWidgetItem(single_exp_str)
            single_exp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 6, single_exp_item)
            
            # Motion (column 7)
            if entry.motion is not None:
                motion_str = f"{entry.motion:.2f}"
            else:
                motion_str = "-"
            motion_item = QTableWidgetItem(motion_str)
            motion_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 7, motion_item)
            
            # Magnitude (column 8)
            if entry.magnitude is not None:
                mag_str = f"{entry.magnitude:.2f}"
            else:
                mag_str = "-"
            mag_item = QTableWidgetItem(mag_str)
            mag_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 8, mag_item)
            
            # Status (column 9)
            status = entry.status or "-"
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # Color code status
            if status == "Found":
                status_item.setForeground(QColor(30, 180, 30))  # Green
            elif status == "Not Found":
                status_item.setForeground(QColor(220, 30, 30))  # Red
            self.setItem(row, 9, status_item)
            
            # Comment (column 10)
            comment = entry.comment or "-"
            comment_item = QTableWidgetItem(comment)
            self.setItem(row, 10, comment_item)
            
            # Store the entry ID in the first item for context menu access
            date_item.setData(Qt.ItemDataRole.UserRole, entry.id)
        
        # Apply striping
        self._apply_striping()
    
    def _apply_striping(self):
        """Apply a striped effect to rows with dark mode support."""
        palette = self.palette()
        base_color = palette.color(self.backgroundRole())
        is_dark = base_color.value() < 128 if hasattr(base_color, 'value') else False
        # Use dark-friendly colors if in dark mode
        color1 = QColor(40, 40, 40) if is_dark else QColor(255, 255, 255)
        color2 = QColor(55, 55, 55) if is_dark else QColor(245, 245, 245)
        
        for row in range(self.rowCount()):
            color = color2 if row % 2 == 1 else color1
            for col in range(self.columnCount()):
                cell = self.item(row, col)
                if cell:
                    cell.setBackground(color)
                    if is_dark:
                        cell.setForeground(QColor(230, 230, 230))
    
    def get_visible_file_count(self):
        """Return the number of visible rows (for status bar)."""
        return self.rowCount()
    
    def _show_context_menu(self, pos):
        """Show a context menu for the selected row."""
        item = self.itemAt(pos)
        if not item:
            return
        
        row = item.row()
        if row < 0 or row >= len(self.mpc_entries):
            return
        
        # Get the entry ID from the first item in the row
        first_item = self.item(row, 0)
        if not first_item:
            return
        
        entry_id = first_item.data(Qt.ItemDataRole.UserRole)
        if not entry_id:
            return
        
        # Get the entry for display
        entry = self.mpc_entries[row]
        
        def delete_entry():
            """Delete the selected MPC log entry."""
            # Confirm deletion
            reply = QMessageBox.question(
                self,
                "Delete MPC Log Entry",
                f"Are you sure you want to delete this MPC log entry?\n\n"
                f"Date: {to_display_time(entry.observation_date).strftime('%Y-%m-%d %H:%M:%S') if entry.observation_date else 'Unknown'}\n"
                f"Target: {entry.target_name or 'Unknown'}\n"
                f"Status: {entry.status or 'Unknown'}\n\n"
                f"This action cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                db = get_db_manager()
                if db.delete_mpc_log_entry(entry_id):
                    QMessageBox.information(self, "Success", "MPC log entry deleted successfully.")
                    # Refresh the table
                    self.refresh_table()
                    # Emit signal to refresh database
                    self.database_refresh_requested.emit()
                else:
                    QMessageBox.warning(self, "Error", "Failed to delete MPC log entry.")
        
        menu = QMenu(self)
        delete_action = QAction("Delete entry", menu)
        delete_action.triggered.connect(delete_entry)
        menu.addAction(delete_action)
        
        menu.exec(self.viewport().mapToGlobal(pos))
    
    def refresh_table(self):
        """Refresh the table from the database."""
        db = get_db_manager()
        session = db.get_session()
        try:
            entries = session.query(MPCLog).order_by(MPCLog.observation_date.desc()).all()
            self.populate(entries)
        finally:
            session.close()
