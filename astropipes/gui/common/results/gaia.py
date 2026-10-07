from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QMenu
from PyQt6.QtGui import QFont
from PyQt6.QtCore import pyqtSignal, Qt
from astropy.coordinates import Angle
import astropy.units as u
import webbrowser

class GaiaResultWindow(QDialog):
    gaia_row_selected = pyqtSignal(int)
    
    def __init__(self, gaia_objects, pixel_coords_dict, parent=None):
        super().__init__(parent)
        self.gaia_objects = gaia_objects  # Store for later use
        self.pixel_coords_dict = pixel_coords_dict
        self.setWindowTitle("Gaia Stars in Field")
        self.setGeometry(250, 250, 900, 400)
        self.setModal(False)  # Make the dialog non-modal
        
        layout = QVBoxLayout(self)
        table = QTableWidget(self)
        table.setColumnCount(9)
        table.setHorizontalHeaderLabels([
            "Source ID", "Magnitude (G)", "Parallax (mas)", "PM RA (mas/yr)", "PM Dec (mas/yr)", 
            "RA (deg)", "Dec (deg)", "Pixel (x, y)", "Distance (pc)"
        ])
        table.setRowCount(len(gaia_objects))
        table.setFont(QFont("Courier New", 10))
        table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
        table.setSelectionMode(table.SelectionMode.SingleSelection)
        
        # Enable context menu for the table
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_context_menu)
        
        for i, obj in enumerate(gaia_objects):
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
            
            # Calculate distance from parallax if available
            distance_pc = None
            if getattr(obj, 'parallax', None) is not None and obj.parallax > 0:
                distance_pc = 1000.0 / obj.parallax  # Convert mas to pc
            
            # Get pixel coordinates
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
                QTableWidgetItem(str(getattr(obj, 'source_id', ''))),
                QTableWidgetItem(f"{getattr(obj, 'magnitude', 0):.2f}" if getattr(obj, 'magnitude', None) is not None else ""),
                QTableWidgetItem(f"{getattr(obj, 'parallax', 0):.2f}" if getattr(obj, 'parallax', None) is not None else ""),
                QTableWidgetItem(f"{getattr(obj, 'pm_ra', 0):.2f}" if getattr(obj, 'pm_ra', None) is not None else ""),
                QTableWidgetItem(f"{getattr(obj, 'pm_dec', 0):.2f}" if getattr(obj, 'pm_dec', None) is not None else ""),
                QTableWidgetItem(ra_str),
                QTableWidgetItem(dec_str),
                QTableWidgetItem(pixel_str),
                QTableWidgetItem(f"{distance_pc:.1f}" if distance_pc is not None else "")
            ]
            
            for col, item in enumerate(items):
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
        """Open the Gaia object details page in the default browser."""
        if row < len(self.gaia_objects):
            obj = self.gaia_objects[row]
            source_id = getattr(obj, 'source_id', '')
            if source_id:
                # Construct Gaia archive URL
                gaia_url = f"https://gea.esac.esa.int/archive/#!/result?queryId=21&dataId=all&table=gaiadr3.gaia_source&where=source_id={source_id}"
                try:
                    webbrowser.open(gaia_url)
                except Exception as e:
                    # If webbrowser fails, we could show a message box here
                    print(f"Failed to open browser: {e}")
    
    def _on_row_selected(self, table):
        selected_rows = table.selectionModel().selectedRows()
        if selected_rows:
            visual_row = selected_rows[0].row()
            # Get the first column item to identify the object
            item = table.item(visual_row, 0)  # Source ID column
            if item is not None:
                # Find the original index by matching the source ID
                source_id = item.text()
                for i, obj in enumerate(self.gaia_objects):
                    if str(getattr(obj, 'source_id', '')) == source_id:
                        self.gaia_row_selected.emit(i)
                        break 