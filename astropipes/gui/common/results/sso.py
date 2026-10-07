from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem
from PyQt6.QtGui import QFont, QColor, QBrush
from PyQt6.QtCore import pyqtSignal
from astropy.coordinates import Angle
import astropy.units as u

class SSOResultWindow(QDialog):
    sso_row_selected = pyqtSignal(int)
    def __init__(self, sso_objects, pixel_coords_dict, parent=None):
        super().__init__(parent)
        self.sso_objects = sso_objects  # Store for later use
        self.setWindowTitle("Solar System Objects in Field")
        self.setGeometry(250, 250, 875, 350)
        self.setModal(False)  # Make the dialog non-modal
        layout = QVBoxLayout(self)
        table = QTableWidget(self)
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels([
            "Name", "Type", "Magnitude", "Distance (AU)", "Velocity (arcsec/h)", "RA (deg)", "Dec (deg)", "Pixel (x, y)"
        ])
        table.setRowCount(len(sso_objects))
        table.setFont(QFont("Courier New", 10))
        table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
        table.setSelectionMode(table.SelectionMode.SingleSelection)
        def get_row_color(type_str):
            if not type_str:
                return None
            t = type_str.strip()
            if t == "Vulcanoid" or t.startswith("NEA"):
                return QColor(220, 0, 0)  # red
            if t == "Hungaria" or t.startswith("Mars-Crosser"):
                return QColor(255, 140, 0)  # orange
            if t.startswith("MB"):
                return QColor(0, 180, 0)  # green
            if t == "Trojan" or t == "Centaur":
                return QColor(0, 100, 255)  # blue
            if t == "IOC" or t.startswith("KBO"):
                return QColor(160, 32, 240)  # purple
            return None
        for i, obj in enumerate(sso_objects):
            type_str = str(getattr(obj, 'object_type', ''))
            color = get_row_color(type_str)
            ra_val = getattr(obj, 'ra', 0)
            dec_val = getattr(obj, 'dec', 0)
            try:
                ra_str = Angle(ra_val, unit=u.deg).to_string(unit=u.hourangle, sep=':', precision=1, pad=True)
            except Exception:
                ra_str = str(ra_val)
            try:
                dec_str = Angle(dec_val, unit=u.deg).to_string(unit=u.deg, sep=':', precision=1, alwayssign=True, pad=True)
            except Exception:
                dec_str = str(dec_val)
            # Flip y for display
            pixel_str = "-"
            if obj in pixel_coords_dict:
                x, y = pixel_coords_dict[obj]
                img_h = parent.image_data.shape[0] if parent and hasattr(parent, 'image_data') and parent.image_data is not None else None
                if img_h is not None:
                    y_flipped = img_h - y - 1
                    pixel_str = f"({x:.1f}, {y_flipped:.1f})"
                else:
                    pixel_str = f"({x:.1f}, {y:.1f})"
            items = [
                QTableWidgetItem(str(getattr(obj, 'name', ''))),
                QTableWidgetItem(type_str),
                QTableWidgetItem(f"{getattr(obj, 'magnitude', 0):.2f}" if getattr(obj, 'magnitude', None) is not None else ""),
                QTableWidgetItem(f"{getattr(obj, 'distance', 0):.2f}" if getattr(obj, 'distance', None) is not None else ""),
                QTableWidgetItem(f"{getattr(obj, 'velocity', 0):.2f}" if getattr(obj, 'velocity', None) is not None else ""),
                QTableWidgetItem(ra_str),
                QTableWidgetItem(dec_str),
                QTableWidgetItem(pixel_str)
            ]
            for col, item in enumerate(items):
                if color:
                    item.setForeground(QBrush(color))
                table.setItem(i, col, item)
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)
        table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
        # Connect selection change to emit signal
        table.selectionModel().selectionChanged.connect(lambda selected, deselected: self._on_row_selected(table))
        layout.addWidget(table)
        self.setLayout(layout)
        self.table = table
    def _on_row_selected(self, table):
        selected_rows = table.selectionModel().selectedRows()
        if selected_rows:
            visual_row = selected_rows[0].row()
            # For QTableWidget, we need to get the item and find its original position
            # Get the first column item to identify the object
            item = table.item(visual_row, 0)  # Name column
            if item is not None:
                # Find the original row by searching through the original data
                # We'll use the object name as a unique identifier
                object_name = item.text()
                # Find the original index by matching the object name
                for i, obj in enumerate(self.sso_objects):
                    if str(getattr(obj, 'name', '')) == object_name:
                        self.sso_row_selected.emit(i)
                        break 