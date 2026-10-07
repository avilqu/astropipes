from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QMenu
from PyQt6.QtGui import QFont
from PyQt6.QtCore import pyqtSignal, Qt
import webbrowser

class GaiaDetectionResultWindow(QDialog):
    gaia_detection_row_selected = pyqtSignal(int)
    
    def __init__(self, gaia_detection_results, parent=None):
        super().__init__(parent)
        self.gaia_detection_results = gaia_detection_results  # List of (GaiaObject, DetectedSource, distance_arcsec) tuples
        self.setWindowTitle("Gaia Stars Corresponding to Detected Sources")
        self.setGeometry(250, 250, 1200, 500)
        self.setModal(False)
        
        layout = QVBoxLayout(self)
        table = QTableWidget(self)
        table.setColumnCount(15)
        table.setHorizontalHeaderLabels([
            "Gaia Source ID", "Gaia Mag (G)", "Gaia RA (deg)", "Gaia Dec (deg)", 
            "Detected Source ID", "Detected RA (deg)", "Detected Dec (deg)", 
            "Detected X (px)", "Detected Y (px)", "Detected Flux", "Detected SNR",
            "Distance (arcsec)", "Parallax (mas)", "PM RA (mas/yr)", "PM Dec (mas/yr)"
        ])
        table.setRowCount(len(gaia_detection_results))
        table.setFont(QFont("Courier New", 10))
        table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
        table.setSelectionMode(table.SelectionMode.SingleSelection)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_context_menu)
        
        for i, (gaia_obj, detected_source, distance_arcsec) in enumerate(gaia_detection_results):
            # Gaia object data
            gaia_ra_str = f"{gaia_obj.ra:.6f}" if gaia_obj.ra is not None else ""
            gaia_dec_str = f"{gaia_obj.dec:.6f}" if gaia_obj.dec is not None else ""
            gaia_mag_str = f"{gaia_obj.magnitude:.2f}" if gaia_obj.magnitude is not None else ""
            parallax_str = f"{gaia_obj.parallax:.2f}" if gaia_obj.parallax is not None else ""
            pm_ra_str = f"{gaia_obj.pm_ra:.2f}" if gaia_obj.pm_ra is not None else ""
            pm_dec_str = f"{gaia_obj.pm_dec:.2f}" if gaia_obj.pm_dec is not None else ""
            
            # Detected source data
            detected_ra_str = f"{detected_source.ra:.6f}" if detected_source.ra is not None else ""
            detected_dec_str = f"{detected_source.dec:.6f}" if detected_source.dec is not None else ""
            
            items = [
                QTableWidgetItem(str(gaia_obj.source_id)),
                QTableWidgetItem(gaia_mag_str),
                QTableWidgetItem(gaia_ra_str),
                QTableWidgetItem(gaia_dec_str),
                QTableWidgetItem(str(detected_source.id)),
                QTableWidgetItem(detected_ra_str),
                QTableWidgetItem(detected_dec_str),
                QTableWidgetItem(f"{detected_source.x:.2f}"),
                QTableWidgetItem(f"{detected_source.y:.2f}"),
                QTableWidgetItem(f"{detected_source.flux:.2f}"),
                QTableWidgetItem(f"{detected_source.snr:.2f}"),
                QTableWidgetItem(f"{distance_arcsec:.2f}"),
                QTableWidgetItem(parallax_str),
                QTableWidgetItem(pm_ra_str),
                QTableWidgetItem(pm_dec_str)
            ]
            
            for col, item in enumerate(items):
                table.setItem(i, col, item)
        
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)
        table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
        table.selectionModel().selectionChanged.connect(lambda selected, deselected: self._on_row_selected(table))
        layout.addWidget(table)
        self.setLayout(layout)
        self.table = table
    
    def _show_context_menu(self, position):
        """Show context menu for the table."""
        item = self.table.itemAt(position)
        if item is None:
            return
        
        row = item.row()
        context_menu = QMenu(self)
        
        # Add "View Gaia object details" action
        view_gaia_details_action = context_menu.addAction("View Gaia object details")
        view_gaia_details_action.triggered.connect(lambda: self._view_gaia_object_details(row))
        
        # Add "View detected source details" action
        view_source_details_action = context_menu.addAction("View detected source details")
        view_source_details_action.triggered.connect(lambda: self._view_source_details(row))
        
        context_menu.exec(self.table.mapToGlobal(position))
    
    def _view_gaia_object_details(self, row):
        """Open the Gaia object details page in the default browser."""
        if row < len(self.gaia_detection_results):
            gaia_obj, _, _ = self.gaia_detection_results[row]
            source_id = getattr(gaia_obj, 'source_id', '')
            if source_id:
                # Construct Gaia archive URL
                gaia_url = f"https://gea.esac.esa.int/archive/#!/result?queryId=21&dataId=all&table=gaiadr3.gaia_source&where=source_id={source_id}"
                try:
                    webbrowser.open(gaia_url)
                except Exception as e:
                    print(f"Failed to open browser: {e}")
    
    def _view_source_details(self, row):
        """Show details about the detected source."""
        if row < len(self.gaia_detection_results):
            _, detected_source, distance_arcsec = self.gaia_detection_results[row]
            print(f"Detected source details: {detected_source}")
            print(f"Distance from Gaia star: {distance_arcsec:.2f} arcseconds")
    
    def _on_row_selected(self, table):
        selected_rows = table.selectionModel().selectedRows()
        if selected_rows:
            visual_row = selected_rows[0].row()
            self.gaia_detection_row_selected.emit(visual_row)