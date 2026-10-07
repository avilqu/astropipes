from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QMenu
from PyQt6.QtGui import QFont, QColor, QBrush
from PyQt6.QtCore import pyqtSignal, Qt
from astropy.coordinates import Angle
import astropy.units as u
import webbrowser

class SIMBADFieldResultWindow(QDialog):
    simbad_field_row_selected = pyqtSignal(int)
    
    def __init__(self, simbad_objects, pixel_coords_list, parent=None):
        super().__init__(parent)
        self.simbad_objects = simbad_objects  # Store for later use
        self.pixel_coords_list = pixel_coords_list
        self.setWindowTitle("Deep-Sky objects in field")
        self.setGeometry(250, 250, 750, 250)
        self.setModal(False)  # Make the dialog non-modal
        
        layout = QVBoxLayout(self)
        table = QTableWidget(self)
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels([
            "Name", "Type", "Mag (V)", "Distance", "Unit", "RA", "Dec", "Pixel (x, y)"
        ])
        table.setRowCount(len(simbad_objects))
        table.setFont(QFont("Courier New", 10))
        table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
        table.setSelectionMode(table.SelectionMode.SingleSelection)
        
        # Enable context menu for the table
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_context_menu)
        
        def get_row_color(type_str):
            if not type_str:
                return None
            t = type_str.strip()
            if t == "Star":
                return QColor(255, 255, 0)  # yellow
            elif t == "Galaxy":
                return QColor(0, 255, 255)  # cyan
            elif t == "Nebula":
                return QColor(255, 0, 255)  # magenta
            elif t == "Cluster":
                return QColor(0, 255, 0)  # green
            elif t == "Planet":
                return QColor(255, 165, 0)  # orange
            return None
        
        for i, obj in enumerate(simbad_objects):
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
            
            # Get pixel coordinates
            pixel_str = "-"
            if i < len(pixel_coords_list):
                x, y = pixel_coords_list[i]
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
                QTableWidgetItem(f"{getattr(obj, 'distance', 0):.1f}" if getattr(obj, 'distance', None) is not None else ""),
                QTableWidgetItem(str(getattr(obj, 'distance_unit', '')) if getattr(obj, 'distance_unit', None) is not None else ""),
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
    
    def _show_context_menu(self, position):
        """Show context menu for the table."""
        # Get the item at the clicked position
        item = self.table.itemAt(position)
        if item is None:
            return
        
        # Get the row index
        row = item.row()
        
        # Create context menu
        context_menu = QMenu(self)
        
        # Add "View object details" action
        view_details_action = context_menu.addAction("View object details")
        view_details_action.triggered.connect(lambda: self._view_object_details(row))
        
        # Show the context menu at the cursor position
        context_menu.exec(self.table.mapToGlobal(position))
    
    def _view_object_details(self, row):
        """Open the SIMBAD object details page in the default browser."""
        if row < len(self.simbad_objects):
            obj = self.simbad_objects[row]
            object_name = getattr(obj, 'name', '')
            if object_name:
                # Construct SIMBAD URL
                simbad_url = f"http://simbad.u-strasbg.fr/simbad/sim-id?Ident={object_name}"
                try:
                    webbrowser.open(simbad_url)
                except Exception as e:
                    # If webbrowser fails, we could show a message box here
                    print(f"Failed to open browser: {e}")
    
    def _on_row_selected(self, table):
        selected_rows = table.selectionModel().selectedRows()
        if selected_rows:
            visual_row = selected_rows[0].row()
            # Get the first column item to identify the object
            item = table.item(visual_row, 0)  # Name column
            if item is not None:
                # Find the original index by matching the object name
                object_name = item.text()
                for i, obj in enumerate(self.simbad_objects):
                    if str(getattr(obj, 'name', '')) == object_name:
                        self.simbad_field_row_selected.emit(i)
                        break 