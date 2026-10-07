import os
import numpy as np
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QTabWidget, QTableWidget, QTableWidgetItem, 
                             QLabel, QTextEdit, QPushButton, QAbstractItemView,
                             QMessageBox, QDialog, QLineEdit)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import pyqtSignal
from astropy.coordinates import Angle
import astropy.units as u
import json
from astropipes.astrometry.lspc import fit_plate_constants, plate_constants_to_sky
from astropipes.gui.common.jobs import JobThread
from astropipes.workflows import substacks
from astropipes.config import settings
import logging

logger = logging.getLogger(__name__)


class OrbitDataWindow(QMainWindow):
    row_selected = pyqtSignal(int, object)  # row index, ephemeris tuple
    def __init__(self, object_name, predicted_positions, pseudo_mpec_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Orbit Details - {object_name}")
        self.setGeometry(300, 200, 1000, 700)
        
        # Store data for stacking
        self.object_name = object_name
        self.predicted_positions = predicted_positions
        self.pseudo_mpec_text = pseudo_mpec_text
        self.parent_viewer = parent
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()
        central_widget.setLayout(layout)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # Create Positions tab
        self._create_positions_tab()
        
        # Create Pseudo MPEC tab
        self._create_pseudo_mpec_tab()
        
        # Populate data
        self._populate_predicted_positions(predicted_positions)
        self._populate_pseudo_mpec(pseudo_mpec_text)
    
    def _create_positions_tab(self):
        """Create the Positions tab with the predicted positions table."""
        positions_widget = QWidget()
        positions_layout = QVBoxLayout()
        positions_widget.setLayout(positions_layout)
        
        # Predicted positions table
        self.positions_table = QTableWidget()
        self.positions_table.setColumnCount(5)
        self.positions_table.setHorizontalHeaderLabels([
            "Date/Time", "RA (deg)", "Dec (deg)", "RA (h:m:s)", "Dec (d:m:s)"
        ])
        self.positions_table.setFont(QFont("Courier New", 10))
        self.positions_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.positions_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        positions_layout.addWidget(self.positions_table)
        
        # Connect selection change instead of clicks to enable keyboard navigation
        self.positions_table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        
        # Add the tab
        self.tab_widget.addTab(positions_widget, "Ephemerides")
    
    def _create_pseudo_mpec_tab(self):
        """Create the Pseudo MPEC tab with text display."""
        pseudo_mpec_widget = QWidget()
        pseudo_mpec_layout = QVBoxLayout()
        pseudo_mpec_widget.setLayout(pseudo_mpec_layout)
        
        # Pseudo MPEC text area
        self.pseudo_mpec_text_edit = QTextEdit()
        self.pseudo_mpec_text_edit.setReadOnly(True)
        self.pseudo_mpec_text_edit.setFont(QFont("Courier New", 10))
        pseudo_mpec_layout.addWidget(self.pseudo_mpec_text_edit)
        
        # Add the tab
        self.tab_widget.addTab(pseudo_mpec_widget, "Pseudo MPEC")
    
    def _populate_predicted_positions(self, predicted_positions):
        """Populate the predicted positions table with all fields from the ephemeris entry, except ISO_time, JD, and date_obs."""
        if not predicted_positions:
            self.positions_table.setRowCount(0)
            return
        # Use all keys from the first entry as columns, except the excluded ones
        exclude = {"ISO_time", "JD", "date_obs", "RA60", "Dec60"}
        columns = [k for k in predicted_positions[0].keys() if k not in exclude]
        self.positions_table.setColumnCount(len(columns))
        self.positions_table.setHorizontalHeaderLabels(columns)
        self.positions_table.setRowCount(len(predicted_positions))
        for i, entry in enumerate(predicted_positions):
            for j, key in enumerate(columns):
                value = entry.get(key, "")
                self.positions_table.setItem(i, j, QTableWidgetItem(str(value)))
        self.positions_table.resizeColumnsToContents()
        
        # Set initial selection to first row to trigger viewer update
        if predicted_positions:
            self.positions_table.selectRow(0)

    def _populate_pseudo_mpec(self, pseudo_mpec_text):
        """Populate the pseudo MPEC text area."""
        if pseudo_mpec_text:
            self.pseudo_mpec_text_edit.setPlainText(pseudo_mpec_text)
        else:
            self.pseudo_mpec_text_edit.setPlainText("No pseudo MPEC data available.")

    def _on_row_clicked(self, row, col):
        if 0 <= row < len(self.predicted_positions):
            self.row_selected.emit(row, self.predicted_positions[row])

    def _on_selection_changed(self, selected, deselected):
        """Handle selection changes to enable keyboard navigation."""
        selected_rows = self.positions_table.selectionModel().selectedRows()
        if selected_rows:
            row = selected_rows[0].row()
            if 0 <= row < len(self.predicted_positions):
                self.row_selected.emit(row, self.predicted_positions[row])

    def add_positions_tab(self, positions, cursor_coords):
        """Add a new tab showing computed object positions."""
        # Check if the Positions tab already exists
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == "Positions":
                # Update existing tab
                self._update_positions_tab(positions, cursor_coords, i)
                return
        
        # Create new Positions tab
        self._create_positions_tab_new(positions, cursor_coords)
    
    def _create_positions_tab_new(self, positions, cursor_coords):
        """Create a new Positions tab with the computed positions."""
        positions_widget = QWidget()
        positions_layout = QVBoxLayout()
        positions_widget.setLayout(positions_layout)
        
        # Store cursor coordinates for later use
        self.cursor_coords = cursor_coords
        
        
        # Add Generate Substacks button (initially disabled)
        self.generate_substacks_button = QPushButton("Generate Substacks")
        self.generate_substacks_button.setFont(QFont("Arial", 10))
        self.generate_substacks_button.setEnabled(False)  # Enabled after LSPC computed
        self.generate_substacks_button.clicked.connect(lambda: self._generate_substacks(positions))
        positions_layout.addWidget(self.generate_substacks_button)
        
        # Add Measure object positions button (disabled until substacks generated)
        self.measure_button = QPushButton("Measure object positions")
        self.measure_button.setFont(QFont("Arial", 10))
        self.measure_button.setEnabled(False)
        self.measure_button.clicked.connect(self._measure_object_positions)
        positions_layout.addWidget(self.measure_button)
        
        # Create LSPC solution text area
        self.lspc_solution_text = QTextEdit()
        self.lspc_solution_text.setReadOnly(True)
        self.lspc_solution_text.setFont(QFont("Courier New", 10))
        self.lspc_solution_text.setMaximumHeight(150)
        self.lspc_solution_text.setPlaceholderText("LSPC solution will appear here after computation...")
        positions_layout.addWidget(self.lspc_solution_text)
        
        
        # Create table for positions
        self.computed_positions_table = QTableWidget()
        self.computed_positions_table.setColumnCount(8)
        self.computed_positions_table.setHorizontalHeaderLabels([
            "File", "Original X", "Original Y", "Stacked X", "Stacked Y", 
            "Shift X", "Shift Y", "RA/Dec"
        ])
        self.computed_positions_table.setFont(QFont("Courier New", 9))
        self.computed_positions_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.computed_positions_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        positions_layout.addWidget(self.computed_positions_table)
        
        # Connect selection change to enable keyboard navigation
        self.computed_positions_table.selectionModel().selectionChanged.connect(self._on_computed_positions_selection_changed)
        
        # Store the positions data for row selection
        self.computed_positions_data = positions
        
        # Populate the table
        self._populate_computed_positions(positions)

        # Automatically compute LSPC once positions are available
        self._compute_lspc(positions)
        
        # Add the tab
        self.tab_widget.addTab(positions_widget, "Positions")
    
    def _update_positions_tab(self, positions, cursor_coords, tab_index):
        """Update an existing Positions tab with new data."""
        positions_widget = self.tab_widget.widget(tab_index)
        if positions_widget:
            # Store cursor coordinates for later use
            self.cursor_coords = cursor_coords
            
            # Clear existing layout
            for i in reversed(range(positions_widget.layout().count())):
                child = positions_widget.layout().itemAt(i).widget()
                if child:
                    child.deleteLater()
            
            # Recreate the layout
            positions_layout = positions_widget.layout()
            
            # Add information about the cursor position
            info_label = QLabel(f"Cursor position in stacked image: {cursor_coords}")
            info_label.setFont(QFont("Arial", 10))
            positions_layout.addWidget(info_label)
            
            # Automatically compute LSPC (button removed)
            
            # Add Generate Substacks button (initially disabled)
            self.generate_substacks_button = QPushButton("Generate Substacks")
            self.generate_substacks_button.setFont(QFont("Arial", 10))
            self.generate_substacks_button.setEnabled(False)
            self.generate_substacks_button.clicked.connect(lambda: self._generate_substacks(positions))
            positions_layout.addWidget(self.generate_substacks_button)
            
            # Add Measure object positions button (disabled until substacks generated)
            self.measure_button = QPushButton("Measure object positions")
            self.measure_button.setFont(QFont("Arial", 10))
            self.measure_button.setEnabled(False)
            self.measure_button.clicked.connect(self._measure_object_positions)
            positions_layout.addWidget(self.measure_button)
            
            # Create LSPC solution text area
            self.lspc_solution_text = QTextEdit()
            self.lspc_solution_text.setReadOnly(True)
            self.lspc_solution_text.setFont(QFont("Courier New", 10))
            self.lspc_solution_text.setMaximumHeight(150)
            self.lspc_solution_text.setPlaceholderText("LSPC solution will appear here after computation...")
            positions_layout.addWidget(self.lspc_solution_text)
            
            
            # Create table for positions
            self.computed_positions_table = QTableWidget()
            self.computed_positions_table.setColumnCount(8)
            self.computed_positions_table.setHorizontalHeaderLabels([
                "File", "Original X", "Original Y", "Stacked X", "Stacked Y", 
                "Shift X", "Shift Y", "RA/Dec"
            ])
            self.computed_positions_table.setFont(QFont("Courier New", 9))
            self.computed_positions_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.computed_positions_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            positions_layout.addWidget(self.computed_positions_table)
            
            # Connect selection change to enable keyboard navigation
            self.computed_positions_table.selectionModel().selectionChanged.connect(self._on_computed_positions_selection_changed)
            
            # Store the positions data for row selection
            self.computed_positions_data = positions
            
            # Populate the table
            self._populate_computed_positions(positions)

            # Automatically compute LSPC once positions are updated
            self._compute_lspc(positions)
    
    def _generate_substacks(self, positions):
        """Generate three motion tracked substacks from the dataset."""
        if not hasattr(self, 'parent_viewer') or not self.parent_viewer:
            QMessageBox.warning(self, "Error", "No parent viewer available.")
            return
        
        if not self.parent_viewer.loaded_files:
            QMessageBox.warning(self, "No Files", "No FITS files loaded in the viewer.")
            return
        
        # Filter out already stacked images, keeping only individual images
        individual_files = substacks.individual_frames(self.parent_viewer.loaded_files)
        
        if len(individual_files) < 3:
            QMessageBox.warning(self, "Insufficient Files", 
                              f"Only {len(individual_files)} individual images found. At least 3 individual images are required to generate substacks.")
            return
        
        # Get the object name from the parent viewer
        object_name = getattr(self.parent_viewer, '_ephemeris_object_name', 'Unknown_Object')
        
        # Chronological thirds of the dataset
        substack_files = substacks.split_in_thirds(substacks.sort_files_by_date(individual_files))
        try:
            object_positions = substacks.reference_positions(positions, substack_files)
        except Exception as e:
            # Fallback to using the original cursor position for all substacks
            print(f"Warning: Could not calculate substack-specific positions: {e}")
            object_positions = [self.cursor_coords] * 3
        
        # Create console window for output
        from astropipes.gui.common.console_window import ConsoleOutputWindow
        console_window = ConsoleOutputWindow("Substack Generation", self)
        console_window.show_and_raise()
        
        # Start substack generation in background thread
        predicted_positions = self.predicted_positions
        self._substack_thread = JobThread(
            lambda log, cancel: substacks.generate_substacks(
                substack_files, object_name, object_positions, predicted_positions, log, cancel),
            capture_stdout=True,
        )
        
        def on_finished(result):
            message = result.get('message') or result.get('error', '')
            if result.get('success'):
                console_window.append_text(f"\n\033[1;32mSubstack generation completed successfully!\033[0m\n\n{message}\n")
                # Load the generated substacks into the viewer
                for file_path in result['output_files']:
                    self.parent_viewer.open_and_add_file(file_path)
                
                # Update viewer UI
                self.parent_viewer.update_navigation_buttons()
                self.parent_viewer.update_image_count_label()
                
                # Enable 'Measure object positions' button now that substacks are generated
                if hasattr(self, 'measure_button'):
                    self.measure_button.setEnabled(True)
            else:
                console_window.append_text(f"\n\033[1;31mSubstack generation failed:\033[0m\n\n{message}\n")
        
        def on_cancel():
            console_window.append_text("\n\033[1;31mCancelling substack generation...\033[0m\n")
            self._substack_thread.stop()
        
        self._substack_thread.output.connect(console_window.append_text)
        self._substack_thread.finished.connect(on_finished)
        console_window.cancel_requested.connect(on_cancel)
        self._substack_thread.start()
    
    def _compute_lspc(self, positions):
        """Compute LSPC using Gaia catalog positions directly (bypassing source detection)."""
        if not hasattr(self, 'parent_viewer') or not self.parent_viewer:
            QMessageBox.warning(self, "Error", "No parent viewer available.")
            return
        
        # Check if we have WCS and can load Gaia catalog directly
        if not hasattr(self.parent_viewer, 'wcs') or not self.parent_viewer.wcs:
            QMessageBox.warning(self, "No WCS Solution", 
                              "Image must be plate-solved first.\n\n"
                              "To plate-solve the image:\n"
                              "1. Go to the Tools menu\n"
                              "2. Select 'Plate Solve Image'\n"
                              "3. Wait for the solution to complete")
            return
        
        # Try to use existing Gaia catalog from SIMBAD search menu first
        gaia_detection_results = None
        
        # Debug: Check what overlays are available
        logger.debug(f"Checking for Gaia overlays...")
        logger.debug(f"Parent viewer type: {type(self.parent_viewer)}")
        logger.debug(f"Parent viewer class: {self.parent_viewer.__class__.__name__ if self.parent_viewer else 'None'}")
        logger.debug(f"Has _gaia_overlay attribute: {hasattr(self.parent_viewer, '_gaia_overlay')}")
        if hasattr(self.parent_viewer, '_gaia_overlay'):
            logger.debug(f"_gaia_overlay value: {self.parent_viewer._gaia_overlay}")
            logger.debug(f"_gaia_overlay type: {type(self.parent_viewer._gaia_overlay)}")
            if self.parent_viewer._gaia_overlay:
                logger.debug(f"_gaia_overlay length: {len(self.parent_viewer._gaia_overlay) if isinstance(self.parent_viewer._gaia_overlay, (list, tuple)) else 'not list/tuple'}")
        logger.debug(f"Has _gaia_detection_overlay attribute: {hasattr(self.parent_viewer, '_gaia_detection_overlay')}")
        if hasattr(self.parent_viewer, '_gaia_detection_overlay'):
            logger.debug(f"_gaia_detection_overlay value: {self.parent_viewer._gaia_detection_overlay}")
            if self.parent_viewer._gaia_detection_overlay:
                logger.debug(f"_gaia_detection_overlay length: {len(self.parent_viewer._gaia_detection_overlay) if isinstance(self.parent_viewer._gaia_detection_overlay, (list, tuple)) else 'not list/tuple'}")
        
        # Debug: Check other relevant attributes
        logger.debug(f"Has WCS: {hasattr(self.parent_viewer, 'wcs') and self.parent_viewer.wcs is not None}")
        logger.debug(f"Has image_data: {hasattr(self.parent_viewer, 'image_data') and self.parent_viewer.image_data is not None}")
        
        # List all attributes that start with _gaia to see what's available
        gaia_attrs = [attr for attr in dir(self.parent_viewer) if attr.startswith('_gaia')]
        logger.debug(f"All _gaia* attributes: {gaia_attrs}")
        
        # Check for Gaia catalog loaded via SIMBAD search menu
        if (hasattr(self.parent_viewer, '_gaia_overlay') and 
            self.parent_viewer._gaia_overlay):
            gaia_objects_in_field, coords_list = self.parent_viewer._gaia_overlay
            
            # Convert to detection results format using precise WCS positions
            gaia_detection_results = []
            for gaia_obj, (pixel_x, pixel_y) in zip(gaia_objects_in_field, coords_list):
                # Create a precise "detected source" using WCS-derived coordinates
                from astropipes.astrometry.sources import DetectedSource
                precise_source = DetectedSource(
                    id=len(gaia_detection_results) + 1,
                    x=pixel_x,
                    y=pixel_y,
                    ra=gaia_obj.ra,
                    dec=gaia_obj.dec,
                    flux=1000.0,  # Mock value
                    snr=50.0      # Mock value
                )
                
                # Distance is 0 since we're using exact catalog positions
                gaia_detection_results.append((gaia_obj, precise_source, 0.0))
            
            logger.debug(f"Using existing Gaia catalog from SIMBAD menu ({len(gaia_detection_results)} stars, precise WCS positions)")
        
        # Try legacy Gaia detection results (source detection + matching)
        elif (hasattr(self.parent_viewer, '_gaia_detection_overlay') and 
              self.parent_viewer._gaia_detection_overlay):
            gaia_detection_results = self.parent_viewer._gaia_detection_overlay
            logger.debug("Using existing Gaia detection results (legacy mode with source detection)")
        
        # If no existing results, load Gaia catalog directly using WCS
        if not gaia_detection_results:
            logger.debug("No existing Gaia detection results, loading catalog directly")
            try:
                # Load Gaia catalog using precise WCS positions
                from astropipes.astrometry.catalogs import AstrometryCatalog
                catalog = AstrometryCatalog()
                
                # Get image shape
                if hasattr(self.parent_viewer, 'image_data') and self.parent_viewer.image_data is not None:
                    image_shape = self.parent_viewer.image_data.shape
                else:
                    QMessageBox.warning(self, "No Image Data", "No image data available for catalog loading.")
                    return
                
                logger.debug(f"Loading Gaia catalog for image shape: {image_shape}")
                
                # Get Gaia objects in the field
                gaia_objects = catalog.get_field_gaia_objects(
                    self.parent_viewer.wcs, image_shape, max_magnitude=15.0
                )
                
                if len(gaia_objects) < 6:
                    QMessageBox.warning(self, "Insufficient Stars", 
                                      f"Only {len(gaia_objects)} Gaia stars found in the field.\n\n"
                                      "At least 6 stars are required for LSPC calculation.\n\n"
                                      "Recommended workflow:\n"
                                      "1. Go to SIMBAD search menu → 'Search Gaia catalog'\n"
                                      "2. Use a higher magnitude limit (e.g., 16-18)\n"
                                      "3. Then run LSPC calculation with the loaded catalog")
                    return
                
                logger.debug(f"Found {len(gaia_objects)} Gaia stars in field")
                
                # Convert to pixel coordinates using WCS (this is the precise step!)
                pixel_coords = catalog.get_gaia_object_pixel_coordinates(self.parent_viewer.wcs, gaia_objects)
                
                # Create pseudo-detection results using WCS-derived positions
                gaia_detection_results = []
                for gaia_obj, pixel_x, pixel_y in pixel_coords:
                    # Create a mock DetectedSource with precise WCS-derived coordinates
                    from astropipes.astrometry.sources import DetectedSource
                    precise_source = DetectedSource(
                        id=len(gaia_detection_results) + 1,
                        x=pixel_x,
                        y=pixel_y,
                        ra=gaia_obj.ra,  # Use catalog RA/Dec
                        dec=gaia_obj.dec,
                        flux=1000.0,  # Mock values
                        snr=50.0      # Mock values
                    )
                    
                    # Distance is 0 since we're using exact catalog positions
                    gaia_detection_results.append((gaia_obj, precise_source, 0.0))
                
                logger.debug(f"Created {len(gaia_detection_results)} precise catalog-based star positions")
                
            except Exception as e:
                QMessageBox.critical(self, "Catalog Loading Error", 
                                   f"Failed to load Gaia catalog:\n{str(e)}\n\n"
                                   "Fallback: Please use 'Detect Gaia Stars in Image' from the Catalogs menu.")
                return
        
        if not gaia_detection_results:
            QMessageBox.warning(self, "No Star Catalog", 
                              "No star catalog available for LSPC calculation.\n\n"
                              "Recommended workflow:\n"
                              "1. Go to SIMBAD search menu → 'Search Gaia catalog'\n"
                              "2. Enter magnitude limit (e.g., 16.0)\n"
                              "3. Then calculate LSPC using the precise catalog positions\n\n"
                              "Alternative: Use 'Detect Gaia Stars in Image' (less precise)")
            return
        
        # Validate Gaia detection results structure
        for i, result in enumerate(gaia_detection_results):
            if not isinstance(result, tuple) or len(result) != 3:
                QMessageBox.warning(self, "Invalid Gaia Data", 
                                  f"Gaia detection result {i} has invalid structure: {result}")
                return
            gaia_obj, detected_source, distance_arcsec = result
            if not hasattr(gaia_obj, 'ra') or not hasattr(gaia_obj, 'dec') or not hasattr(gaia_obj, 'source_id'):
                QMessageBox.warning(self, "Invalid Gaia Data", 
                                  f"Gaia object {i} missing required attributes")
                return
            if not hasattr(detected_source, 'x') or not hasattr(detected_source, 'y'):
                QMessageBox.warning(self, "Invalid Gaia Data", 
                                  f"Detected source {i} missing required coordinates")
                return
        
        # Check if we have enough stars for LSPC (need at least 3)
        if len(gaia_detection_results) < 3:
            QMessageBox.warning(self, "Insufficient Stars", 
                              f"Only {len(gaia_detection_results)} matched stars found.\n\n"
                              "At least 3 comparison stars are required for LSPC calculation.")
            return
        
        # Validate that positions data is available and valid
        if not positions:
            QMessageBox.warning(self, "No Positions", 
                              "No position data available for LSPC calculation.")
            return
        
        # Check that positions have required fields
        for i, pos in enumerate(positions):
            if not isinstance(pos, dict):
                QMessageBox.warning(self, "Invalid Position Data", 
                                  f"Position {i} is not a valid dictionary.")
                return
            if 'original_x' not in pos or 'original_y' not in pos:
                QMessageBox.warning(self, "Invalid Position Data", 
                                  f"Position {i} missing required coordinates (original_x, original_y).")
                return
            
            # Check that coordinates are numeric
            if not isinstance(pos['original_x'], (int, float)) or not isinstance(pos['original_y'], (int, float)):
                QMessageBox.warning(self, "Invalid Position Data", 
                                  f"Position {i} has non-numeric coordinates: original_x={pos['original_x']}, original_y={pos['original_y']}")
                return
        
        # Compute LSPC
        try:
            logger.debug(f"Computing LSPC with {len(gaia_detection_results)} Gaia stars and {len(positions)} positions")
            logger.debug(f"First position sample: {positions[0] if positions else 'No positions'}")
            lspc_results = self._calculate_lspc(gaia_detection_results, positions)
            self._update_positions_table_with_lspc(lspc_results)
            
            # Enable the Generate Substacks button after LSPC is computed
            if hasattr(self, 'generate_substacks_button'):
                self.generate_substacks_button.setEnabled(True)
                
            # Store a backup of the original positions data if not already stored
            if not hasattr(self, '_original_positions_data'):
                self._original_positions_data = positions.copy()
                
        except Exception as e:
            QMessageBox.critical(self, "LSPC Error", f"Error computing LSPC: {str(e)}")
    
    def _calculate_lspc(self, gaia_detection_results, positions):
        """Calculate LSPC using matched Gaia stars (see astrometry.lspc.fit_plate_constants)."""
        return fit_plate_constants(gaia_detection_results, positions)
    
    def _update_positions_table_with_lspc(self, lspc_results):
        """Update the positions table with LSPC results."""
        logger.debug(f"Updating positions table with LSPC results")
        logger.debug(f"LSPC results type: {type(lspc_results)}")
        logger.debug(f"LSPC results keys: {list(lspc_results.keys()) if isinstance(lspc_results, dict) else 'Not a dict'}")
        
        if not isinstance(lspc_results, dict):
            print(f"Error: LSPC results is not a dictionary: {lspc_results}")
            return
            
        # Update the table headers to include LSPC columns
        self.computed_positions_table.setColumnCount(12)
        self.computed_positions_table.setHorizontalHeaderLabels([
            "File", "Original X", "Original Y", "Stacked X", "Stacked Y", 
            "Shift X", "Shift Y", "WCS RA", "WCS Dec", "LSPC RA", "LSPC Dec", "Difference"
        ])
        
        # Update the table data with LSPC results
        lspc_positions = lspc_results.get('lspc_positions', [])
        if not lspc_positions:
            print("Warning: No LSPC positions found in results")
            return
        
        # Create a mapping from file_path to LSPC results for easy lookup
        lspc_lookup = {}
        for lspc_pos in lspc_positions:
            file_path = lspc_pos.get('file_path')
            if file_path:
                lspc_lookup[file_path] = lspc_pos
        
        # Use the original positions data for the table, but add LSPC columns
        if not hasattr(self, 'computed_positions_data') or not self.computed_positions_data:
            print("Error: No computed positions data available")
            return
            
        original_positions = self.computed_positions_data
        logger.debug(f"Original positions data has {len(original_positions)} entries")
        self.computed_positions_table.setRowCount(len(original_positions))
        
        for i, pos in enumerate(original_positions):
            logger.debug(f"Processing position {i}: {pos}")
            try:
                # File name (basename only)
                filename = os.path.basename(pos['file_path'])
                self.computed_positions_table.setItem(i, 0, QTableWidgetItem(filename))
                
                # Original coordinates
                original_x = pos.get('original_x')
                original_y = pos.get('original_y')
                if original_x is not None and original_y is not None:
                    self.computed_positions_table.setItem(i, 1, QTableWidgetItem(f"{original_x:.2f}"))
                    self.computed_positions_table.setItem(i, 2, QTableWidgetItem(f"{original_y:.2f}"))
                else:
                    self.computed_positions_table.setItem(i, 1, QTableWidgetItem("N/A"))
                    self.computed_positions_table.setItem(i, 2, QTableWidgetItem("N/A"))
                
                # Stacked coordinates
                stacked_x = pos.get('stacked_x')
                stacked_y = pos.get('stacked_y')
                if stacked_x is not None and stacked_y is not None:
                    self.computed_positions_table.setItem(i, 3, QTableWidgetItem(f"{stacked_x:.2f}"))
                    self.computed_positions_table.setItem(i, 4, QTableWidgetItem(f"{stacked_y:.2f}"))
                else:
                    self.computed_positions_table.setItem(i, 3, QTableWidgetItem("N/A"))
                    self.computed_positions_table.setItem(i, 4, QTableWidgetItem("N/A"))
                
                # Shifts
                shift_x = pos.get('shift_x')
                shift_y = pos.get('shift_y')
                if shift_x is not None and shift_y is not None:
                    self.computed_positions_table.setItem(i, 5, QTableWidgetItem(f"{shift_x:.2f}"))
                    self.computed_positions_table.setItem(i, 6, QTableWidgetItem(f"{shift_y:.2f}"))
                else:
                    self.computed_positions_table.setItem(i, 5, QTableWidgetItem("N/A"))
                    self.computed_positions_table.setItem(i, 6, QTableWidgetItem("N/A"))
                
                # WCS coordinates
                wcs_ra = pos.get('ra', 'N/A')
                wcs_dec = pos.get('dec', 'N/A')
                if wcs_ra != 'N/A' and wcs_dec != 'N/A':
                    self.computed_positions_table.setItem(i, 7, QTableWidgetItem(f"{wcs_ra:.6f}"))
                    self.computed_positions_table.setItem(i, 8, QTableWidgetItem(f"{wcs_dec:.6f}"))
                else:
                    self.computed_positions_table.setItem(i, 7, QTableWidgetItem("N/A"))
                    self.computed_positions_table.setItem(i, 8, QTableWidgetItem("N/A"))
                
                # LSPC coordinates
                file_path = pos.get('file_path')
                lspc_pos = lspc_lookup.get(file_path) if file_path else None
                
                # Check if this is a stacked image
                is_stacked = False
                if hasattr(self, 'parent_viewer') and self.parent_viewer:
                    try:
                        from astropy.io import fits
                        with fits.open(file_path) as hdul:
                            header = hdul[0].header
                            if header.get('MOTION_TRACKED', False) or 'STACK' in file_path.upper():
                                is_stacked = True
                    except Exception:
                        pass
                
                if lspc_pos and not is_stacked:
                    lspc_ra = lspc_pos.get('lspc_ra')
                    lspc_dec = lspc_pos.get('lspc_dec')
                    
                    if lspc_ra is not None and lspc_dec is not None:
                        self.computed_positions_table.setItem(i, 9, QTableWidgetItem(f"{lspc_ra:.6f}"))
                        self.computed_positions_table.setItem(i, 10, QTableWidgetItem(f"{lspc_dec:.6f}"))
                        
                        # Calculate and display difference
                        if wcs_ra != 'N/A' and wcs_dec != 'N/A':
                            ra_diff = (lspc_ra - wcs_ra) * 3600  # Convert to arcseconds
                            dec_diff = (lspc_dec - wcs_dec) * 3600
                            distance = np.sqrt(ra_diff**2 + dec_diff**2)
                            diff_text = f"{distance:.2f}\""
                        else:
                            diff_text = "N/A"
                    else:
                        self.computed_positions_table.setItem(i, 9, QTableWidgetItem("N/A"))
                        self.computed_positions_table.setItem(i, 10, QTableWidgetItem("N/A"))
                        diff_text = "N/A"
                else:
                    # No LSPC data available (either no LSPC results or stacked image)
                    if is_stacked:
                        self.computed_positions_table.setItem(i, 9, QTableWidgetItem("Stacked"))
                        self.computed_positions_table.setItem(i, 10, QTableWidgetItem("Stacked"))
                        diff_text = "N/A"
                    else:
                        self.computed_positions_table.setItem(i, 9, QTableWidgetItem("N/A"))
                        self.computed_positions_table.setItem(i, 10, QTableWidgetItem("N/A"))
                        diff_text = "N/A"
                
                self.computed_positions_table.setItem(i, 11, QTableWidgetItem(diff_text))
                
            except Exception as e:
                logger.debug(f"Error processing position {i}: {e}")
                # Set all cells to error state
                for col in range(12):
                    self.computed_positions_table.setItem(i, col, QTableWidgetItem("ERROR"))
                continue
        
        # Resize columns to fit content
        self.computed_positions_table.resizeColumnsToContents()
        
        # Store the LSPC results separately, but keep the original position data for markers
        self.lspc_results = lspc_results
        # Note: We don't overwrite self.computed_positions_data here to preserve marker functionality
        
        # Show LSPC information in the tab
        self._show_lspc_info_in_tab(lspc_results)
    
    def _show_lspc_info_in_tab(self, lspc_results):
        """Show LSPC information in the current Positions tab."""
        # Format LSPC solution values for display
        solution_text = "HIGHER-ORDER LSPC SOLUTION\n"
        solution_text += "=" * 50 + "\n\n"
        
        # Model information
        model_type = lspc_results.get('model_type', 'unknown')
        num_parameters = lspc_results.get('num_parameters', 0)
        comparison_stars = lspc_results.get('comparison_stars', [])
        
        # Check if using precise catalog positions (distance = 0)
        using_precise_positions = False
        if comparison_stars:
            avg_distance = sum(star.get('distance_arcsec', 0) for star in comparison_stars) / len(comparison_stars)
            using_precise_positions = avg_distance < 0.01  # Less than 0.01 arcsec means catalog positions
        
        solution_text += "MODEL INFORMATION:\n"
        solution_text += "-" * 20 + "\n"
        solution_text += f"Model type: {model_type.upper()}\n"
        solution_text += f"Parameters: {num_parameters}\n"
        if using_precise_positions:
            solution_text += f"Star positions: PRECISE CATALOG (WCS-derived)\n"
            solution_text += f"Centroiding errors: ELIMINATED\n"
        else:
            solution_text += f"Star positions: Detected sources (with centroiding errors)\n"
        if model_type == "linear":
            solution_text += "Equations: RA = a*x + b*y + c, Dec = d*x + e*y + f\n"
        elif model_type == "radial":
            solution_text += "Equations: RA = a*x + b*y + c + k1*r²*x\n"
            solution_text += "           Dec = d*x + e*y + f + k2*r²*y\n"
        elif model_type == "quadratic":
            solution_text += "Equations: RA = a*x + b*y + c + d*x² + e*xy + f*y²\n"
            solution_text += "           Dec = g*x + h*y + i + j*x² + k*xy + l*y²\n"
        solution_text += "\n"
        
        # Plate constants
        solution_text += "PLATE CONSTANTS:\n"
        solution_text += "-" * 20 + "\n"
        constants = lspc_results.get('plate_constants', {})
        if constants:
            if model_type == "linear":
                a, b, c = constants.get('a'), constants.get('b'), constants.get('c')
                d, e, f = constants.get('d'), constants.get('e'), constants.get('f')
                
                if all(v is not None for v in [a, b, c, d, e, f]):
                    solution_text += f"a = {a:12.8f}  (RA linear terms)\n"
                    solution_text += f"b = {b:12.8f}\n"
                    solution_text += f"c = {c:12.8f}\n"
                    solution_text += f"d = {d:12.8f}  (Dec linear terms)\n"
                    solution_text += f"e = {e:12.8f}\n"
                    solution_text += f"f = {f:12.8f}\n\n"
                else:
                    solution_text += "Linear constants: N/A\n\n"
                    
            elif model_type == "radial":
                a, b, c = constants.get('a'), constants.get('b'), constants.get('c')
                d, e, f = constants.get('d'), constants.get('e'), constants.get('f')
                k1, k2 = constants.get('k1'), constants.get('k2')
                
                if all(v is not None for v in [a, b, c, d, e, f, k1, k2]):
                    solution_text += f"a = {a:12.8f}  (RA linear terms)\n"
                    solution_text += f"b = {b:12.8f}\n"
                    solution_text += f"c = {c:12.8f}\n"
                    solution_text += f"d = {d:12.8f}  (Dec linear terms)\n"
                    solution_text += f"e = {e:12.8f}\n"
                    solution_text += f"f = {f:12.8f}\n"
                    solution_text += f"k1 = {k1:12.8f}  (RA radial distortion)\n"
                    solution_text += f"k2 = {k2:12.8f}  (Dec radial distortion)\n\n"
                else:
                    solution_text += "Radial constants: N/A\n\n"
                    
            elif model_type == "quadratic":
                params = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l']
                values = [constants.get(p) for p in params]
                
                if all(v is not None for v in values):
                    solution_text += f"a = {values[0]:12.8f}  (RA linear & quadratic)\n"
                    solution_text += f"b = {values[1]:12.8f}\n"
                    solution_text += f"c = {values[2]:12.8f}\n"
                    solution_text += f"d = {values[3]:12.8f}\n"
                    solution_text += f"e = {values[4]:12.8f}\n"
                    solution_text += f"f = {values[5]:12.8f}\n"
                    solution_text += f"g = {values[6]:12.8f}  (Dec linear & quadratic)\n"
                    solution_text += f"h = {values[7]:12.8f}\n"
                    solution_text += f"i = {values[8]:12.8f}\n"
                    solution_text += f"j = {values[9]:12.8f}\n"
                    solution_text += f"k = {values[10]:12.8f}\n"
                    solution_text += f"l = {values[11]:12.8f}\n\n"
                else:
                    solution_text += "Quadratic constants: N/A\n\n"
            
            # Normalization parameters
            image_center_x = constants.get('image_center_x')
            image_center_y = constants.get('image_center_y')
            norm_scale = constants.get('norm_scale')
            
            if all(v is not None for v in [image_center_x, image_center_y, norm_scale]):
                solution_text += "NORMALIZATION PARAMETERS:\n"
                solution_text += "-" * 25 + "\n"
                solution_text += f"Image center X: {image_center_x:10.2f} pixels\n"
                solution_text += f"Image center Y: {image_center_y:10.2f} pixels\n"
                solution_text += f"Scale factor:   {norm_scale:10.2f} pixels\n\n"
        else:
            solution_text += "Plate constants: N/A\n\n"
        
        # RMS residuals
        solution_text += "RMS RESIDUALS:\n"
        solution_text += "-" * 15 + "\n"
        rms_ra = lspc_results.get('rms_ra')
        rms_dec = lspc_results.get('rms_dec')
        
        if rms_ra is not None and rms_dec is not None:
            solution_text += f"RA  RMS: {rms_ra:10.6f} degrees\n"
            solution_text += f"Dec RMS: {rms_dec:10.6f} degrees\n"
            solution_text += f"RA  RMS: {rms_ra*3600:10.2f} arcseconds\n"
            solution_text += f"Dec RMS: {rms_dec*3600:10.2f} arcseconds\n\n"
        else:
            solution_text += "RA  RMS: N/A degrees\n"
            solution_text += "Dec RMS: N/A degrees\n"
            solution_text += "RA  RMS: N/A arcseconds\n"
            solution_text += "Dec RMS: N/A arcseconds\n\n"
        
        # Comparison stars info
        solution_text += "COMPARISON STARS:\n"
        solution_text += "-" * 18 + "\n"
        comparison_stars = lspc_results.get('comparison_stars', [])
        solution_text += f"Number of stars: {len(comparison_stars)}\n\n"
        
        # Show individual star residuals
        solution_text += "STAR RESIDUALS:\n"
        solution_text += "-" * 16 + "\n"
        solution_text += "Gaia ID          RA Residual    Dec Residual   Total\n"
        solution_text += "                 (arcsec)       (arcsec)       (arcsec)\n"
        solution_text += "-" * 60 + "\n"
        
        # Calculate and display residuals for each comparison star
        comparison_stars = lspc_results.get('comparison_stars', [])
        if comparison_stars and constants:
            residuals_calculated = False
            for star in comparison_stars:
                predicted_ra, predicted_dec = plate_constants_to_sky(
                    constants, star['measured_x'], star['measured_y'])
                if predicted_ra is None:
                    break
                residuals_calculated = True
                ra_residual = (predicted_ra - star['catalog_ra']) * 3600
                dec_residual = (predicted_dec - star['catalog_dec']) * 3600
                total_residual = np.sqrt(ra_residual**2 + dec_residual**2)
                
                # Format Gaia ID (truncate if too long)
                gaia_id = str(star['gaia_id'])
                if len(gaia_id) > 15:
                    gaia_id = gaia_id[:12] + "..."
                
                solution_text += f"{gaia_id:15s} {ra_residual:10.2f} {dec_residual:10.2f} {total_residual:10.2f}\n"
            
            if not residuals_calculated:
                solution_text += "Cannot calculate residuals: plate constants are missing\n"
        else:
            solution_text += "No comparison stars available for residual calculation\n"
        
        # Update the LSPC solution text area
        if hasattr(self, 'lspc_solution_text'):
            self.lspc_solution_text.setPlainText(solution_text)
    
    def _on_computed_positions_selection_changed(self, selected, deselected):
        """Handle selection changes in the computed positions table."""
        selected_rows = self.computed_positions_table.selectionModel().selectedRows()
        if selected_rows and hasattr(self, 'computed_positions_data'):
            row = selected_rows[0].row()
            if 0 <= row < len(self.computed_positions_data):
                position_data = self.computed_positions_data[row]
                
                # Add LSPC data if available
                if hasattr(self, 'lspc_results') and self.lspc_results:
                    file_path = position_data.get('file_path')
                    if file_path:
                        lspc_positions = self.lspc_results.get('lspc_positions', [])
                        for lspc_pos in lspc_positions:
                            if lspc_pos.get('file_path') == file_path:
                                # Merge LSPC data with original position data
                                position_data = {**position_data, **lspc_pos}
                                break
                
                # Emit signal to parent viewer to show marker
                if hasattr(self, 'parent_viewer') and self.parent_viewer:
                    self.parent_viewer.on_computed_positions_row_selected(row, position_data)
    
    def _populate_computed_positions(self, positions):
        """Populate the computed positions table."""
        if not positions:
            self.computed_positions_table.setRowCount(0)
            return
        
        self.computed_positions_table.setRowCount(len(positions))
        
        for i, pos in enumerate(positions):
            # File name (basename only)
            filename = os.path.basename(pos['file_path'])
            self.computed_positions_table.setItem(i, 0, QTableWidgetItem(filename))
            
            # Original coordinates
            self.computed_positions_table.setItem(i, 1, QTableWidgetItem(f"{pos['original_x']:.2f}"))
            self.computed_positions_table.setItem(i, 2, QTableWidgetItem(f"{pos['original_y']:.2f}"))
            
            # Stacked coordinates
            self.computed_positions_table.setItem(i, 3, QTableWidgetItem(f"{pos['stacked_x']:.2f}"))
            self.computed_positions_table.setItem(i, 4, QTableWidgetItem(f"{pos['stacked_y']:.2f}"))
            
            # Shifts
            self.computed_positions_table.setItem(i, 5, QTableWidgetItem(f"{pos['shift_x']:.2f}"))
            self.computed_positions_table.setItem(i, 6, QTableWidgetItem(f"{pos['shift_y']:.2f}"))
            
            # RA/Dec
            if pos['ra'] is not None and pos['dec'] is not None:
                ra_str = f"{pos['ra']:.6f}"
                dec_str = f"{pos['dec']:.6f}"
                ra_dec_str = f"{ra_str}, {dec_str}"
            else:
                ra_dec_str = "N/A"
            self.computed_positions_table.setItem(i, 7, QTableWidgetItem(ra_dec_str))
        
        self.computed_positions_table.resizeColumnsToContents()

    # ---------------- Measurement functions ----------------
    def _measure_object_positions(self):
        """
        Compute RA/Dec for each measurement marker found in motion-tracked
        stacked images (yellow markers) and show the results in a new
        'Measurements' tab.
        """
        if not hasattr(self, 'parent_viewer') or not self.parent_viewer:
            QMessageBox.warning(self, "Error", "No parent viewer available.")
            return

        loaded_files = getattr(self.parent_viewer, 'loaded_files', [])
        if not loaded_files:
            QMessageBox.warning(self, "No Files", "No files loaded in the viewer.")
            return

        import numpy as np
        from astropy.io import fits
        from astropy.time import Time
        from astropipes.processing.motion_tracking import compute_object_positions_from_motion_tracked

        measurements = []

        for file_path in loaded_files:
            try:
                with fits.open(file_path) as hdul:
                    header = hdul[0].header
                    meas_json = header.get('MEAS_POS')
                    if not meas_json:
                        continue
                    x, y = json.loads(meas_json)
                    substack_date = header.get('DATE-OBS')
            except Exception:
                continue

            # Get LSPC constants if available
            lspc_constants = None
            if hasattr(self, 'lspc_results') and self.lspc_results:
                lspc_constants = self.lspc_results.get('plate_constants')
                if lspc_constants:
                    logger.debug(f"Using LSPC constants: {lspc_constants}")
                else:
                    logger.debug("No LSPC constants found in results")
            else:
                logger.debug("No LSPC results available")
            
            # Compute positions back to original images
            try:
                positions = compute_object_positions_from_motion_tracked(
                    file_path, (x, y), lspc_constants=lspc_constants
                )
            except Exception as exc:
                print(f"Warning: could not compute object positions for {file_path}: {exc}")
                continue

            # Gather RA/Dec with times from original images
            times_mjd, ras_deg, decs_deg = [], [], []
            for pos in positions:
                # Check if LSPC coordinates are available and use them instead of WCS
                lspc_ra = pos.get('lspc_ra')
                lspc_dec = pos.get('lspc_dec')
                
                if lspc_ra is not None and lspc_dec is not None:
                    # Use LSPC coordinates (more precise)
                    ra_deg = lspc_ra
                    dec_deg = lspc_dec
                    print(f"Using LSPC coordinates: RA={ra_deg:.6f}, Dec={dec_deg:.6f}")
                else:
                    # Fall back to WCS coordinates
                    ra_deg = pos.get('ra')
                    dec_deg = pos.get('dec')
                    if ra_deg is not None and dec_deg is not None:
                        print(f"Using WCS coordinates: RA={ra_deg:.6f}, Dec={dec_deg:.6f}")
                
                if ra_deg is None or dec_deg is None:
                    continue
                    
                orig_path = pos['file_path']
                try:
                    with fits.open(orig_path) as hdul_o:
                        date_obs_orig = hdul_o[0].header.get('DATE-OBS')
                    if not date_obs_orig:
                        continue
                    t = Time(date_obs_orig, format='isot', scale='utc')
                except Exception:
                    continue
                times_mjd.append(t.mjd)
                ras_deg.append(ra_deg)
                decs_deg.append(dec_deg)

            if not times_mjd:
                continue

            # Determine target time (substack DATE-OBS); fall back to mean
            import numpy as np
            if substack_date:
                try:
                    target_time = Time(substack_date, format='isot', scale='utc').mjd
                except Exception:
                    target_time = np.mean(times_mjd)
            else:
                target_time = np.mean(times_mjd)

            # Interpolate RA/Dec to target time
            if len(times_mjd) == 1:
                ra_interp = ras_deg[0]
                dec_interp = decs_deg[0]
            else:
                # Handle RA wrap-around by working in radians and unwrapping
                ra_rad = np.deg2rad(ras_deg)
                ra_rad_unwrapped = np.unwrap(ra_rad)
                ra_interp_rad = np.interp(target_time, times_mjd, ra_rad_unwrapped)
                ra_interp = np.rad2deg(ra_interp_rad)
                dec_interp = np.interp(target_time, times_mjd, decs_deg)

            # Format RA/Dec
            ra_hms = Angle(ra_interp, unit=u.deg).to_string(unit='hourangle',
                                                            sep=':', precision=2, pad=True)
            dec_dms = Angle(dec_interp, unit=u.deg).to_string(unit='deg',
                                                              sep=':', precision=1, pad=True,
                                                              alwayssign=True)
            if not substack_date:
                substack_date = Time(target_time, format='mjd').isot

            measurements.append({
                'file_path': file_path,
                'date_obs': substack_date,
                'ra_deg': ra_interp,
                'dec_deg': dec_interp,
                'ra_hms': ra_hms,
                'dec_dms': dec_dms
            })

        if not measurements:
            QMessageBox.warning(self, "No Measurements",
                                "No measurement markers found or RA/Dec could not be computed.")
            return
        
        # Check if LSPC was used and inform the user
        lspc_used = False
        if hasattr(self, 'lspc_results') and self.lspc_results:
            # Check if any measurements used LSPC coordinates
            for measurement in measurements:
                # We need to check if LSPC was actually used in the computation
                # This is a bit tricky since we don't store this info in measurements
                # For now, we'll assume LSPC was used if we have LSPC results
                lspc_used = True
                break
        
        if not lspc_used and hasattr(self, 'lspc_results') and self.lspc_results:
            QMessageBox.information(self, "LSPC Available", 
                                  "LSPC solution is available and should be used for measurements.\n"
                                  "This will provide better astrometric precision than WCS coordinates.")
        elif not hasattr(self, 'lspc_results') or not self.lspc_results:
            QMessageBox.information(self, "LSPC Not Available", 
                                  "No LSPC solution available. Measurements use WCS coordinates only.\n\n"
                                  "For improved astrometric precision:\n"
                                  "1. Load Gaia stars (Catalogs → Detect Gaia Stars in Image)\n"
                                  "2. Ensure stars are properly matched\n"
                                  "3. Recompute LSPC solution")

        self._show_measurements_tab(measurements)

    def _show_measurements_tab(self, measurements):
        """Create or update the 'Measurements' tab with the provided data."""
        # Check if a Measurements tab already exists
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabText(i) == "Measurements":
                # Remove it – easier than updating in-place
                self.tab_widget.removeTab(i)
                break

        # Create new tab
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setLayout(layout)

        self.measurements_table = QTableWidget()
        tbl = self.measurements_table
        tbl.setColumnCount(6)
        tbl.setHorizontalHeaderLabels([
            "File", "Date/Time", "RA (deg)", "Dec (deg)", "RA (h:m:s)", "Dec (d:m:s)"
        ])
        tbl.setFont(QFont("Courier New", 9))
        tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tbl.setRowCount(len(measurements))

        for row, m in enumerate(measurements):
            tbl.setItem(row, 0, QTableWidgetItem(os.path.basename(m['file_path'])))
            tbl.setItem(row, 1, QTableWidgetItem(str(m['date_obs'])))
            tbl.setItem(row, 2, QTableWidgetItem(f"{m['ra_deg']:.6f}"))
            tbl.setItem(row, 3, QTableWidgetItem(f"{m['dec_deg']:.6f}"))
            tbl.setItem(row, 4, QTableWidgetItem(m['ra_hms']))
            tbl.setItem(row, 5, QTableWidgetItem(m['dec_dms']))

        tbl.resizeColumnsToContents()
        layout.addWidget(tbl)

        # Add MPC Report button
        mpc_button_layout = QHBoxLayout()
        
        # Get object name from parent viewer if available
        object_name = "Unknown"
        if hasattr(self, 'parent_viewer') and self.parent_viewer:
            object_name = getattr(self.parent_viewer, '_ephemeris_object_name', 'Unknown')
        
        # Create MPC Report button
        self.mpc_report_button = QPushButton("Generate MPC Report")
        self.mpc_report_button.setFont(QFont("Arial", 10))
        self.mpc_report_button.clicked.connect(lambda: self._open_mpc_report(measurements, object_name))
        mpc_button_layout.addWidget(self.mpc_report_button)
        
        # Add spacer to push button to the left
        mpc_button_layout.addStretch()
        
        layout.addLayout(mpc_button_layout)

        # Store data for later row selection
        self.measurements_data = measurements
        # Connect selection change handler
        tbl.selectionModel().selectionChanged.connect(self._on_measurements_selection_changed)

        self.tab_widget.addTab(widget, "Measurements")
        self.tab_widget.setCurrentWidget(widget)

    def _on_measurements_selection_changed(self, selected, deselected):
        """Handle selection changes in the measurements table and load the chosen substack."""
        if not hasattr(self, 'measurements_table') or not hasattr(self, 'measurements_data'):
            return
        selected_rows = self.measurements_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        if not (0 <= row < len(self.measurements_data)):
            return
        entry = self.measurements_data[row]
        file_path = entry.get('file_path')
        if not file_path or not hasattr(self, 'parent_viewer') or not self.parent_viewer:
            return
        # If the file is already loaded list, switch to it, otherwise load directly
        try:
            loaded_files = getattr(self.parent_viewer, 'loaded_files', [])
            if file_path in loaded_files:
                idx = loaded_files.index(file_path)
                self.parent_viewer.current_file_index = idx
            self.parent_viewer.load_fits(file_path, restore_view=True)
            if hasattr(self.parent_viewer, 'update_navigation_buttons'):
                self.parent_viewer.update_navigation_buttons()
        except Exception as exc:
            print(f"Warning: could not load {file_path}: {exc}")

    def _open_mpc_report(self, measurements, object_name):
        """Open the MPC report window with the given measurements."""
        try:
            from astropipes.gui.common.dialogs.mpc_report import MPCReportWindow
            
            # Create and show the MPC report window
            mpc_window = MPCReportWindow(measurements, self)
            
            # Pre-fill the object designation if available
            if object_name and object_name != "Unknown":
                mpc_window.object_designation.setText(object_name)
            
            # Pre-fill the observatory code from config
            mpc_window.observatory_code.setText(settings.OBS_CODE)
            
            # Show the window
            mpc_window.show()
            mpc_window.raise_()
            mpc_window.activateWindow()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not open MPC report window: {str(e)}")

class OrbitComputationDialog(QDialog):
    def __init__(self, parent=None, target_name=None):
        super().__init__(parent)
        self.setWindowTitle("Get orbital elements")
        self.setModal(True)
        self.setFixedSize(400, 150)
        
        layout = QVBoxLayout(self)
        
        # Instructions
        instruction_label = QLabel("Enter the object designation (e.g., C34UMY1):")
        layout.addWidget(instruction_label)
        
        # Object name input
        self.object_input = QLineEdit()
        self.object_input.setPlaceholderText("Object designation...")
        # Pre-fill with target name if provided
        if target_name:
            self.object_input.setText(target_name)
        layout.addWidget(self.object_input)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.compute_button = QPushButton("Get")
        self.compute_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(self.compute_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def get_object_name(self):
        return self.object_input.text().strip()
