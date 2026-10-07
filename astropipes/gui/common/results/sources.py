from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QMenu
from PyQt6.QtGui import QFont
from PyQt6.QtCore import pyqtSignal, Qt

class SourcesResultWindow(QDialog):
    source_row_selected = pyqtSignal(int)
    
    def __init__(self, sources, parent=None):
        super().__init__(parent)
        self.sources = sources  # List of DetectedSource
        self.setWindowTitle("Detected Sources in Image")
        self.setGeometry(250, 250, 1100, 400)
        self.setModal(False)
        
        layout = QVBoxLayout(self)
        table = QTableWidget(self)
        table.setColumnCount(18)
        table.setHorizontalHeaderLabels([
            "ID", "RA (deg)", "Dec (deg)", "X (px)", "Y (px)", "Flux", "SNR", "Area (px^2)",
            "Eccentricity", "Major (px)", "Minor (px)", "Orientation (deg)", "Peak", "Background", 
            "HFR (px)", "FWHM (px)", "HFR (arcsec)", "FWHM (arcsec)"
        ])
        table.setRowCount(len(sources))
        table.setFont(QFont("Courier New", 10))
        table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
        table.setSelectionMode(table.SelectionMode.SingleSelection)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_context_menu)
        
        for i, src in enumerate(sources):
            ra_str = f"{src.ra:.6f}" if src.ra is not None else ""
            dec_str = f"{src.dec:.6f}" if src.dec is not None else ""
            items = [
                QTableWidgetItem(str(src.id)),
                QTableWidgetItem(ra_str),
                QTableWidgetItem(dec_str),
                QTableWidgetItem(f"{src.x:.2f}"),
                QTableWidgetItem(f"{src.y:.2f}"),
                QTableWidgetItem(f"{src.flux:.2f}"),
                QTableWidgetItem(f"{src.snr:.2f}"),
                QTableWidgetItem(f"{src.area:.2f}"),
                QTableWidgetItem(f"{src.eccentricity:.3f}"),
                QTableWidgetItem(f"{src.semimajor_axis:.2f}"),
                QTableWidgetItem(f"{src.semiminor_axis:.2f}"),
                QTableWidgetItem(f"{src.orientation:.2f}"),
                QTableWidgetItem(f"{src.peak_value:.2f}"),
                QTableWidgetItem(f"{src.background:.2f}"),
                QTableWidgetItem(f"{src.hfr:.2f}" if src.hfr > 0 else ""),
                QTableWidgetItem(f"{src.fwhm:.2f}" if src.fwhm > 0 else ""),
                QTableWidgetItem(f"{src.hfr_arcsec:.2f}" if src.hfr_arcsec > 0 else ""),
                QTableWidgetItem(f"{src.fwhm_arcsec:.2f}" if src.fwhm_arcsec > 0 else "")
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
        item = self.table.itemAt(position)
        if item is None:
            return
        row = item.row()
        context_menu = QMenu(self)
        view_details_action = context_menu.addAction("View source details")
        view_details_action.triggered.connect(lambda: self._view_source_details(row))
        context_menu.exec(self.table.mapToGlobal(position))
    
    def _view_source_details(self, row):
        # Placeholder for future details dialog or info popup
        if row < len(self.sources):
            src = self.sources[row]
            print(f"Source details: {src}")
    
    def _on_row_selected(self, table):
        selected_rows = table.selectionModel().selectedRows()
        if selected_rows:
            visual_row = selected_rows[0].row()
            self.source_row_selected.emit(visual_row) 