import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from PyQt6.QtWidgets import QApplication, QMainWindow, QScrollArea, QToolBar, QDialog
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import QStatusBar, QSizePolicy, QLabel

from lib.gui.viewer.overlay import ImageLabel
from lib.gui.viewer.navigation import NavigationMixin
from lib.gui.viewer.catalogs import CatalogSearchMixin
from lib.gui.viewer.image_operations import ImageOperationsMixin
from lib.gui.viewer.files import FileOperationsMixin
from lib.gui.viewer.overlay import OverlayMixin
from lib.gui.viewer.integration import IntegrationMixin
from lib.gui.viewer.display import DisplayMixin
from lib.gui.viewer.histogram import HistogramController
from lib.gui.viewer.toolbar import ToolbarController
from lib.gui.viewer.overlay_toolbar import OverlayToolbarController
from lib.gui.viewer.sources import SourceDetectionMixin
from lib.gui.viewer.monitor import MonitorMixin
from lib.gui.viewer.region_of_interest import RegionOfInterestMixin
from lib.sci.catalogs import AstrometryCatalog

import logging
import threading
import io
import sys



class FITSViewer(
    NavigationMixin,
    CatalogSearchMixin,
    ImageOperationsMixin,
    FileOperationsMixin,
    OverlayMixin,
    IntegrationMixin,
    DisplayMixin,
    SourceDetectionMixin,
    MonitorMixin,
    RegionOfInterestMixin,
    QMainWindow,
):
    def __init__(self, fits_path=None):
        super().__init__()
        self.setWindowTitle("Astropipes FITS Viewer")
        self.setGeometry(100, 100, 1000, 800)
        
        # Set global stylesheet for better disabled state visibility
        self.setStyleSheet("""
            QAction:disabled {
                color: #333333;
            }
            QPushButton:disabled {
                color: #333333;
            }
            QLabel:disabled {
                color: #333333;
            }
        """)

        # --- Multi-file support ---
        self.loaded_files = []  # List of file paths
        self.current_file_index = -1  # Index of currently displayed file
        self._preloaded_fits = {}  # path -> (image_data, header, wcs)

        self.astrometry_catalog = AstrometryCatalog()
        self.pixmap = None  # For ImageLabel compatibility
        self.wcs = None    # For ImageLabel compatibility
        self.image_data = None  # Store current image data
        
        # Initialize toolbar controller first (creates the toolbar)
        self.toolbar_controller = ToolbarController(self)
        
        # Initialize overlay toolbar controller
        self.overlay_toolbar_controller = OverlayToolbarController(self)
        
        # Initialize histogram controller (needs access to toolbar)
        self.histogram_controller = HistogramController(self)
        
        # Connect histogram control signals
        self.toolbar_controller.connect_histogram_signals()
        
        # Get references to toolbar and navigation elements
        self.toolbar = self.toolbar_controller.toolbar
        self.prev_action = self.toolbar_controller.prev_action
        self.next_action = self.toolbar_controller.next_action
        self.prev_button = self.toolbar_controller.prev_button
        self.next_button = self.toolbar_controller.next_button
        self.play_pause_button = self.toolbar_controller.play_pause_button
        self.image_count_label = self.toolbar_controller.image_count_label
        self.load_action = self.toolbar_controller.load_action
        self.close_action = self.toolbar_controller.close_action
        self.delete_action = self.toolbar_controller.delete_action
        self.reset_zoom_action = self.toolbar_controller.reset_zoom_action
        self.zoom_to_fit_action = self.toolbar_controller.zoom_to_fit_action
        self.zoom_region_action = self.toolbar_controller.zoom_region_action
        self.define_roi_action = self.toolbar_controller.define_roi_action
        self.simbad_button = self.toolbar_controller.simbad_button
        self.sso_button = self.toolbar_controller.sso_button
        self.calibrate_button = self.toolbar_controller.calibrate_button
        self.platesolve_button = self.toolbar_controller.platesolve_button
        self.monitor_button = self.toolbar_controller.monitor_button
        self.header_button = self.toolbar_controller.header_button
        self.integration_button = self.toolbar_controller.integration_button
        self.filelist_action = self.toolbar_controller.filelist_action
        
        # Navigation state
        self.playing = self.toolbar_controller.playing
        self.blink_timer = self.toolbar_controller.blink_timer
        self.play_icon = self.toolbar_controller.play_icon
        self.pause_icon = self.toolbar_controller.pause_icon
        # Remove sidebar and use only scroll_area as central widget
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)
        # Ignore wheel events so they are not used for scrolling
        self.scroll_area.wheelEvent = lambda event: event.ignore()
        self.setCentralWidget(self.scroll_area)
        self.image_label = ImageLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("QLabel { background-color: black; }")
        self.image_label.setText("No image loaded")
        self.scroll_area.setWidget(self.image_label)
        # Add default attributes for compatibility with ImageLabel
        self.bit_depth = None
        self.pixel_value_label = QLabel("--", self)
        self.pixel_value_label.setVisible(False)
        self.coord_label = QLabel("", self)
        self.coord_label.setVisible(False)
        self._overlay_visible = True
        self._zoom = 1.0  # Track current zoom level
        self._last_center = None  # Track last center (in image coordinates)
        self._sso_highlight_index = None
        self._source_highlight_index = None  # Track highlighted source
        self._source_overlay = None  # Store source overlay data
        self._zoom_region_mode = False  # Track if zoom-to-region is active
        self._define_roi_mode = False
        self._roi_field_overlay = None
        self._roi_field_overlay_active = False
        self._pending_zoom_rect = None  # Store the last selected rectangle
        self._computed_positions_overlay = None  # Store computed positions overlay data
        if fits_path:
            self.open_and_add_file(fits_path)
        self.overlay_toolbar_controller.update_overlay_button_visibility()
        self.update_navigation_buttons()
        self.update_align_button_visibility()
        self.update_platesolve_button_visibility()
        self.update_close_button_visibility()
        self.update_delete_button_visibility()
        
        # Set initial button states (disabled if no image loaded)
        if not fits_path:
            self.update_button_states_for_no_image()
        # Status bar: coordinates (left), pixel value (right)
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_coord_label = QLabel("No WCS", self)
        self.status_coord_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        self.status_bar.addWidget(self.status_coord_label)
        self.status_pixel_label = QLabel("--", self)
        self.status_pixel_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        self.status_bar.addPermanentWidget(self.status_pixel_label)



def main():
    fits_paths = sys.argv[1:] if len(sys.argv) > 1 else []
    app = QApplication(sys.argv)
    viewer = FITSViewer()
    if fits_paths:
        for i, path in enumerate(fits_paths):
            viewer.open_and_add_file(path)
        # The first file is already loaded by open_and_add_file
        viewer.update_navigation_buttons()
    viewer.show()
    # Ensure zoom to fit is called after the window is visible
    QTimer.singleShot(0, viewer.zoom_to_fit)
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 