import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from PyQt6.QtWidgets import (
    QToolButton, QMenu, QWidget, QGridLayout, 
    QLabel, QSizePolicy, QSpacerItem, QToolBar
)
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import Qt, QTimer


def make_toolbar_separator(parent):
    """Create a visual separator for the toolbar."""
    from PyQt6.QtWidgets import QFrame
    sep = QFrame(parent)
    sep.setFixedWidth(8)  # Give it a little width for margin
    sep.setFixedHeight(32)  # Match your toolbar height
    sep.setStyleSheet("QFrame { margin-left: 5px; border-left: 1px solid #777777; background: transparent; }")
    return sep


class ToolbarController:
    """
    Handles all toolbar button creation and management for the FITS viewer.
    """
    
    def __init__(self, parent_viewer):
        self.parent = parent_viewer
        self.toolbar = None
        self.nav_widget = None
        
        # Initialize all button references
        self.prev_action = None
        self.next_action = None
        self.prev_button = None
        self.next_button = None
        self.play_pause_button = None
        self.image_count_label = None
        self.load_action = None
        self.close_action = None
        self.reset_zoom_action = None
        self.zoom_to_fit_action = None
        self.zoom_region_action = None
        self.simbad_button = None
        self.sso_button = None
        self.calibrate_button = None
        self.platesolve_button = None
        self.header_button = None
        self.integration_button = None
        self.filelist_action = None
        
        # Navigation state
        self.playing = False
        self.blink_timer = None
        self.play_icon = None
        self.pause_icon = None
        
        # Create the toolbar
        self._create_toolbar()
        self._create_navigation_controls()
        self._create_file_controls()
        self._create_zoom_controls()
        self._create_histogram_controls()
        self._create_processing_controls()
        self._create_integration_controls()
        self._create_search_controls()
        self._create_filelist_control()
    
    def _create_toolbar(self):
        """Create and configure the main toolbar."""
        self.toolbar = QToolBar("Main Toolbar")
        # Ignore context menu events
        self.toolbar.contextMenuEvent = lambda event: event.ignore()
        self.toolbar.setMovable(False)  # Disable moving the toolbar
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        
        # Disable context menu on the main window
        self.parent.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        
        # Set toolbar styling
        self.toolbar.setStyleSheet("""
            QToolBar { background: #222222; }
            QToolButton { 
                border: none; 
                background: transparent; 
                padding: 4px;
            }
            QToolButton:hover { 
                border: 1px solid #555555; 
                background: #333333; 
                border-radius: 4px;
            }
            QToolButton:pressed { 
                border: 1px solid #777777; 
                background: #444444; 
                border-radius: 4px;
            }
            QToolButton:checked {
                border: 1px solid #777777;
                background: #444444;
                border-radius: 4px;
            }
            QToolButton:disabled {
                color: #333333;
            }
        """)
        
        self.parent.addToolBar(self.toolbar)
    
    def _create_navigation_controls(self):
        """Create navigation controls (previous, next, play/pause, image count)."""
        # Previous/Next actions
        left_icon = QIcon.fromTheme("go-previous")
        if left_icon.isNull():
            left_icon = QIcon.fromTheme("arrow-left")
        self.prev_action = QAction(left_icon, "Previous", self.parent)
        self.prev_action.setToolTip("Show previous FITS file")
        self.prev_action.triggered.connect(self.parent.show_previous_file)
        
        right_icon = QIcon.fromTheme("go-next")
        if right_icon.isNull():
            right_icon = QIcon.fromTheme("arrow-right")
        self.next_action = QAction(right_icon, "Next", self.parent)
        self.next_action.setToolTip("Show next FITS file")
        self.next_action.triggered.connect(self.parent.show_next_file)
        
        # Image count label
        self.image_count_label = QLabel("- / -", self.parent)
        self.image_count_label.setMinimumWidth(50)
        
        # Create navigation widget
        self.nav_widget = QWidget(self.parent)
        nav_layout = QGridLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setHorizontalSpacing(4)
        
        # Previous button
        self.prev_button = QToolButton(self.parent)
        self.prev_button.setDefaultAction(self.prev_action)
        self.prev_button.setFixedSize(32, 32)
        nav_layout.addWidget(self.prev_button, 0, 0)
        
        # Image count label
        self.image_count_label.setFixedWidth(60)
        nav_layout.addWidget(self.image_count_label, 0, 1, 
                           alignment=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
        
        # Play/Pause button
        self.playing = False
        self.blink_timer = QTimer(self.parent)
        # Import config locally to avoid dependency issues
        try:
            import config
            self.blink_timer.setInterval(config.BLINK_PERIOD_MS)
        except ImportError:
            # Default to 1000ms if config is not available
            self.blink_timer.setInterval(1000)
        self.blink_timer.timeout.connect(self.parent._blink_next_image)
        
        self.play_pause_button = QToolButton(self.parent)
        self.play_icon = QIcon.fromTheme("media-playback-start")
        self.pause_icon = QIcon.fromTheme("media-playback-pause")
        if self.play_icon.isNull():
            self.play_icon = QIcon.fromTheme("play")
        if self.pause_icon.isNull():
            self.pause_icon = QIcon.fromTheme("pause")
        
        self.play_pause_button.setIcon(self.play_icon)
        self.play_pause_button.setToolTip("Play slideshow")
        self.play_pause_button.setFixedSize(32, 32)
        self.play_pause_button.clicked.connect(self.parent.toggle_play_pause)
        nav_layout.addWidget(self.play_pause_button, 0, 2)
        
        # Next button
        self.next_button = QToolButton(self.parent)
        self.next_button.setDefaultAction(self.next_action)
        self.next_button.setFixedSize(32, 32)
        nav_layout.addWidget(self.next_button, 0, 3)
        
        self.nav_widget.setLayout(nav_layout)
        self.nav_widget.setStyleSheet("""
            QToolButton { 
                border: none; 
                background: transparent; 
                padding: 4px;
            }
            QToolButton:hover { 
                border: 1px solid #555555; 
                background: #333333; 
                border-radius: 4px;
            }
            QToolButton:pressed { 
                border: 1px solid #777777; 
                background: #444444; 
                border-radius: 4px;
            }
        """)
    
    def _create_file_controls(self):
        """Create file operation controls (open, close)."""
        # Open button
        open_icon = QIcon.fromTheme("document-open")
        if open_icon.isNull():
            open_icon = QIcon.fromTheme("folder-open")
        self.load_action = QAction(open_icon, "Open FITS", self.parent)
        self.load_action.setToolTip("Open FITS file")
        self.load_action.triggered.connect(self.parent.open_file_dialog)
        self.toolbar.addAction(self.load_action)
        self.toolbar.widgetForAction(self.load_action).setFixedSize(32, 32)

        # Close button
        close_icon = QIcon.fromTheme("dialog-close")
        if close_icon.isNull():
            close_icon = QIcon.fromTheme("window-close")
        self.close_action = QAction(close_icon, "Close FITS", self.parent)
        self.close_action.setToolTip("Close current FITS file")
        self.close_action.setEnabled(False)  # Initially disabled until a file is loaded
        self.close_action.triggered.connect(self.parent.close_current_file)
        self.toolbar.addAction(self.close_action)
        self.toolbar.widgetForAction(self.close_action).setFixedSize(32, 32)

        # Delete button
        delete_icon = QIcon.fromTheme("edit-delete-remove")
        if delete_icon.isNull():
            delete_icon = QIcon.fromTheme("edit-delete")
        if delete_icon.isNull():
            delete_icon = QIcon.fromTheme("delete")
        self.delete_action = QAction(delete_icon, "Delete FITS", self.parent)
        self.delete_action.setToolTip("Delete current FITS file from disk")
        self.delete_action.setEnabled(False)  # Initially disabled until a file is loaded
        self.delete_action.triggered.connect(self.parent.delete_current_file)
        self.toolbar.addAction(self.delete_action)
        self.toolbar.widgetForAction(self.delete_action).setFixedSize(32, 32)

        # Header button - moved from processing controls
        self.header_button = QAction(QIcon.fromTheme("view-financial-list"), "", self.parent)
        self.header_button.setToolTip("Show FITS header")
        self.header_button.setEnabled(False)
        self.header_button.triggered.connect(self.parent.show_header_dialog)
        self.toolbar.addAction(self.header_button)
        self.toolbar.widgetForAction(self.header_button).setFixedSize(32, 32)

        self.toolbar.addWidget(make_toolbar_separator(self.parent))
    
    def _create_zoom_controls(self):
        """Create zoom-related controls."""
        # Reset zoom
        self.reset_zoom_action = QAction(QIcon.fromTheme("zoom-original"), "", self.parent)
        self.reset_zoom_action.setToolTip("Reset zoom to 1:1")
        self.reset_zoom_action.triggered.connect(self.parent.reset_zoom)
        self.toolbar.addAction(self.reset_zoom_action)
        self.toolbar.widgetForAction(self.reset_zoom_action).setFixedSize(32, 32)
        
        # Zoom to fit
        self.zoom_to_fit_action = QAction(QIcon.fromTheme("zoom-fit-width"), "", self.parent)
        self.zoom_to_fit_action.setToolTip("Zoom to fit image in viewport")
        self.zoom_to_fit_action.triggered.connect(self.parent.zoom_to_fit)
        self.toolbar.addAction(self.zoom_to_fit_action)
        self.toolbar.widgetForAction(self.zoom_to_fit_action).setFixedSize(32, 32)

        # Zoom to region
        self.zoom_region_action = QAction(QIcon.fromTheme("page-zoom"), "", self.parent)
        self.zoom_region_action.setCheckable(True)
        self.zoom_region_action.setChecked(False)
        self.zoom_region_action.setToolTip("Zoom to selected region (draw rectangle)")
        self.zoom_region_action.toggled.connect(self.parent.on_zoom_region_toggled)
        self.toolbar.addAction(self.zoom_region_action)
        self.toolbar.widgetForAction(self.zoom_region_action).setFixedSize(32, 32)
    
    def _create_histogram_controls(self):
        """Create histogram-related controls."""
        # Add separator before histogram controls
        self.toolbar.addWidget(make_toolbar_separator(self.parent))
        
        # Linear stretch action
        self.linear_action = QAction(QIcon.fromTheme("view-object-histogram-linear-symbolic"), "", self.parent)
        self.linear_action.setToolTip("Linear histogram stretch")
        self.toolbar.addAction(self.linear_action)
        self.toolbar.widgetForAction(self.linear_action).setFixedSize(32, 32)
        
        # Log stretch action
        self.log_action = QAction(QIcon.fromTheme("view-object-histogram-logarithmic"), "", self.parent)
        self.log_action.setToolTip("Logarithmic histogram stretch")
        self.toolbar.addAction(self.log_action)
        self.toolbar.widgetForAction(self.log_action).setFixedSize(32, 32)

        # Brightness slider
        from PyQt6.QtWidgets import QSlider
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal, self.parent)
        self.brightness_slider.setMinimum(0)
        self.brightness_slider.setMaximum(100)
        self.brightness_slider.setValue(50)  # Default to middle position
        self.brightness_slider.setFixedWidth(120)
        self.brightness_slider.setToolTip("Adjust image brightness")
        self.brightness_slider.setStyleSheet("""
            QSlider:disabled {
                color: #333333;
            }
        """)
        self.toolbar.addWidget(self.brightness_slider)

        # Clipping button
        self.clipping_action = QAction(QIcon.fromTheme("upindicator"), "", self.parent)
        self.clipping_action.setCheckable(True)
        self.clipping_action.setChecked(False)  # Default to off
        self.clipping_action.setToolTip(f"Toggle sigma clipping for display stretch (sigma={3.0})")
        self.toolbar.addAction(self.clipping_action)
        self.toolbar.widgetForAction(self.clipping_action).setFixedSize(32, 32)
        
        # Add separator after histogram controls
        self.toolbar.addWidget(make_toolbar_separator(self.parent))
    
    def connect_histogram_signals(self):
        """Connect histogram control signals to the histogram controller."""
        if hasattr(self.parent, 'histogram_controller'):
            self.linear_action.triggered.connect(self.parent.histogram_controller.set_linear_stretch)
            self.log_action.triggered.connect(self.parent.histogram_controller.set_log_stretch)
            self.brightness_slider.valueChanged.connect(self.parent.histogram_controller.on_brightness_slider_changed)
            self.clipping_action.triggered.connect(self.parent.histogram_controller.toggle_clipping)
    
    def _create_search_controls(self):
        """Create search and overlay controls."""
        # SIMBAD search button with dropdown
        simbad_icon = QIcon.fromTheme("file-search-symbolic")
        if simbad_icon.isNull():
            simbad_icon = QIcon.fromTheme("search")
        
        self.simbad_button = QToolButton(self.parent)
        self.simbad_button.setIcon(simbad_icon)
        self.simbad_button.setToolTip("Search for an object in SIMBAD and overlay on image")
        self.simbad_button.setEnabled(True)
        self.simbad_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.simbad_button.setFixedSize(32, 32)
        
        # Create SIMBAD dropdown menu
        simbad_menu = QMenu(self.simbad_button)
        search_simbad_action = QAction("Search on SIMBAD", self.parent)
        search_simbad_action.triggered.connect(self.parent.open_simbad_search_dialog)
        simbad_menu.addAction(search_simbad_action)
        
        simbad_menu.addSeparator()
        
        find_simbad_field_action = QAction("Find deep-sky objects in field", self.parent)
        find_simbad_field_action.triggered.connect(self.parent.open_simbad_field_search_dialog)
        simbad_menu.addAction(find_simbad_field_action)
        
        simbad_menu.addSeparator()
        
        self.simbad_button.setMenu(simbad_menu)
        self.simbad_button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.toolbar.addWidget(self.simbad_button)
        
        # Sources detection button with dropdown
        sources_icon = QIcon.fromTheme("kstars_stars")
        if sources_icon.isNull():
            sources_icon = QIcon.fromTheme("starred")
        self.sources_button = QToolButton(self.parent)
        self.sources_button.setIcon(sources_icon)
        self.sources_button.setToolTip("Detect sources in image")
        self.sources_button.setEnabled(True)
        self.sources_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.sources_button.setFixedSize(32, 32)
        
        # Create sources dropdown menu
        sources_menu = QMenu(self.sources_button)
        load_gaia_catalog_action = QAction("Load Gaia catalog", self.parent)
        load_gaia_catalog_action.triggered.connect(self.parent.open_gaia_search_dialog)
        sources_menu.addAction(load_gaia_catalog_action)
        
        sources_menu.addSeparator()
        
        detect_sources_action = QAction("Detect sources", self.parent)
        detect_sources_action.triggered.connect(self.parent.detect_sources_action)
        sources_menu.addAction(detect_sources_action)
        
        detect_gaia_stars_action = QAction("Detect Gaia stars in image", self.parent)
        detect_gaia_stars_action.triggered.connect(self.parent.detect_gaia_stars_in_image)
        sources_menu.addAction(detect_gaia_stars_action)
        
        self.sources_button.setMenu(sources_menu)
        self.sources_button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.toolbar.addWidget(self.sources_button)
        
        # Solar System Objects button
        sso_icon = QIcon.fromTheme("kstars_planets")
        if sso_icon.isNull():
            sso_icon = QIcon.fromTheme("applications-science")
        
        self.sso_button = QToolButton(self.parent)
        self.sso_button.setIcon(sso_icon)
        self.sso_button.setToolTip("Solar System Objects")
        self.sso_button.setEnabled(True)
        self.sso_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.sso_button.setFixedSize(32, 32)
        
        # Create SSO dropdown menu
        sso_menu = QMenu(self.sso_button)
        find_sso_action = QAction("Find SSO in field", self.parent)
        find_sso_action.triggered.connect(self.parent.open_sso_search_dialog)
        sso_menu.addAction(find_sso_action)
        
        sso_menu.addSeparator()
        
        compute_orbit_action = QAction("Get orbital elements", self.parent)
        compute_orbit_action.triggered.connect(self.parent.open_orbit_computation_dialog)
        sso_menu.addAction(compute_orbit_action)
        
        self.sso_button.setMenu(sso_menu)
        self.sso_button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.toolbar.addWidget(self.sso_button)
    
    def _create_processing_controls(self):
        """Create image processing controls (calibrate, platesolve, header)."""        
        # Calibrate button with dropdown
        calibrate_icon = QIcon.fromTheme("blur")
        if calibrate_icon.isNull():
            calibrate_icon = QIcon.fromTheme("edit-blur")
        
        self.calibrate_button = QToolButton(self.parent)
        self.calibrate_button.setIcon(calibrate_icon)
        self.calibrate_button.setToolTip("Calibrate images")
        self.calibrate_button.setEnabled(True)
        self.calibrate_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.calibrate_button.setFixedSize(32, 32)
        
        # Create calibrate dropdown menu
        calibrate_menu = QMenu(self.calibrate_button)
        
        calibrate_current_action = QAction("Calibrate this image", self.parent)
        calibrate_current_action.triggered.connect(self.parent.calibrate_current_image)
        calibrate_menu.addAction(calibrate_current_action)
        
        calibrate_menu.addSeparator()
        
        calibrate_all_action = QAction("Calibrate all images", self.parent)
        calibrate_all_action.triggered.connect(self.parent.calibrate_all_images)
        calibrate_menu.addAction(calibrate_all_action)
        
        self.calibrate_button.setMenu(calibrate_menu)
        self.calibrate_button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.toolbar.addWidget(self.calibrate_button)

        # Platesolve button with dropdown
        self.platesolve_button = QToolButton(self.parent)
        self.platesolve_button.setIcon(QIcon.fromTheme("map-globe"))
        self.platesolve_button.setToolTip("Platesolve images")
        self.platesolve_button.setEnabled(False)
        self.platesolve_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.platesolve_button.setFixedSize(32, 32)
        
        # Create platesolve dropdown menu
        platesolve_menu = QMenu(self.platesolve_button)
        
        platesolve_current_action = QAction("Platesolve this image", self.parent)
        platesolve_current_action.triggered.connect(self.parent.platesolve_current_image)
        platesolve_menu.addAction(platesolve_current_action)
        
        platesolve_menu.addSeparator()
        
        platesolve_all_action = QAction("Platesolve all images", self.parent)
        platesolve_all_action.triggered.connect(self.parent.platesolve_all_images)
        platesolve_menu.addAction(platesolve_all_action)
        
        self.platesolve_button.setMenu(platesolve_menu)
        self.platesolve_button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.toolbar.addWidget(self.platesolve_button)

        self.toolbar.addWidget(make_toolbar_separator(self.parent))

    
    def _create_integration_controls(self):
        """Create integration controls."""

        # Align button with dropdown
        align_icon = QIcon.fromTheme("transform-shear-left")
        if align_icon.isNull():
            align_icon = QIcon.fromTheme("transform-shear")
        
        self.align_button = QToolButton(self.parent)
        self.align_button.setIcon(align_icon)
        self.align_button.setToolTip("Align images")
        self.align_button.setEnabled(False)  # Initially disabled
        self.align_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.align_button.setFixedSize(32, 32)
        
        # Create align dropdown menu
        align_menu = QMenu(self.align_button)
        
        # Fast alignment option
        align_fast_action = QAction("Align images (Astroalign)", self.parent)
        align_fast_action.triggered.connect(self.parent.align_images_fast)
        align_menu.addAction(align_fast_action)
        
        # WCS alignment option
        align_wcs_action = QAction("Align images (WCS reprojection)", self.parent)
        align_wcs_action.triggered.connect(self.parent.align_images_wcs)
        align_menu.addAction(align_wcs_action)
        
        self.align_button.setMenu(align_menu)
        self.align_button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.toolbar.addWidget(self.align_button)

        # Integration button with dropdown
        integration_icon = QIcon.fromTheme("black_sum")
        if integration_icon.isNull():
            integration_icon = QIcon.fromTheme("applications-science")
        
        self.integration_button = QToolButton(self.parent)
        self.integration_button.setIcon(integration_icon)
        self.integration_button.setToolTip("Integration")
        self.integration_button.setEnabled(False)  # Initially disabled
        self.integration_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.integration_button.setFixedSize(32, 32)
        
        # Create integration dropdown menu
        integration_menu = QMenu(self.integration_button)
        
        stack_wcs_action = QAction("Stack aligned images", self.parent)
        stack_wcs_action.triggered.connect(self.parent.stack_align_wcs)
        integration_menu.addAction(stack_wcs_action)
        
        stack_ephemeris_action = QAction("Stack on ephemeris", self.parent)
        stack_ephemeris_action.triggered.connect(self.parent.stack_align_ephemeris)
        integration_menu.addAction(stack_ephemeris_action)
        
        self.integration_button.setMenu(integration_menu)
        self.integration_button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.toolbar.addWidget(self.integration_button)

        self.toolbar.addWidget(make_toolbar_separator(self.parent))
    
    def _create_filelist_control(self):
        """Create file list control and add navigation widget."""
        # Add spacer to push navigation elements to the right
        spacer = QWidget(self.parent)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)

        # Add navigation widget
        self.toolbar.addWidget(self.nav_widget)

        # File List toggle button
        self.filelist_action = QAction(QIcon.fromTheme("view-list-details"), "", self.parent)
        self.filelist_action.setToolTip("Show list of loaded FITS files")
        self.filelist_action.setVisible(False)
        self.filelist_action.setCheckable(True)
        self.filelist_action.setChecked(False)
        self.filelist_action.triggered.connect(self.parent.toggle_filelist_window)
        self.toolbar.addAction(self.filelist_action)
        self.toolbar.widgetForAction(self.filelist_action).setFixedSize(32, 32)
    
    def update_navigation_buttons(self):
        """Update navigation button visibility based on number of loaded files."""
        n = len(self.parent.loaded_files)
        # Hide navigation elements if only one or no files loaded
        visible = n > 1
        self.prev_action.setVisible(visible)
        self.next_action.setVisible(visible)
        self.prev_button.setVisible(visible)
        self.next_button.setVisible(visible)
        self.play_pause_button.setVisible(visible)
        self.image_count_label.setVisible(visible)
        self.update_image_count_label()
    
    def update_image_count_label(self):
        """Update the image count label text."""
        n = len(self.parent.loaded_files)
        if n == 0:
            self.image_count_label.setText("- / -")
        else:
            # Displayed as 1-based index
            self.image_count_label.setText(f"{self.parent.current_file_index + 1} / {n}")
    
    def update_button_states_for_no_image(self):
        """Disable all buttons that require an image to be loaded."""
        # Disable image-dependent buttons
        self.reset_zoom_action.setEnabled(False)
        self.zoom_to_fit_action.setEnabled(False)
        self.zoom_region_action.setEnabled(False)
        
        # Disable histogram controls
        self.linear_action.setEnabled(False)
        self.log_action.setEnabled(False)
        self.brightness_slider.setEnabled(False)
        self.clipping_action.setEnabled(False)
        
        # Disable search buttons
        self.simbad_button.setEnabled(False)
        self.sso_button.setEnabled(False)
        self.sources_button.setEnabled(False) # Disable sources button
        

        
        # Disable calibration and platesolve buttons
        self.calibrate_button.setEnabled(False)
        self.platesolve_button.setEnabled(False)
        
        # Disable integration buttons
        self.integration_button.setEnabled(False)
        if hasattr(self, 'align_button'):
            self.align_button.setEnabled(False)
    
    def update_button_states_for_image_loaded(self):
        """Enable all buttons that require an image to be loaded."""
        # Enable image-dependent buttons
        self.reset_zoom_action.setEnabled(True)
        self.zoom_to_fit_action.setEnabled(True)
        self.zoom_region_action.setEnabled(True)
        
        # Enable histogram controls
        self.linear_action.setEnabled(True)
        self.log_action.setEnabled(True)
        self.brightness_slider.setEnabled(True)
        self.clipping_action.setEnabled(True)
        
        # Enable search buttons
        self.simbad_button.setEnabled(True)
        self.sso_button.setEnabled(True)
        self.sources_button.setEnabled(True) # Enable sources button
        

        
        # Enable calibration and platesolve buttons
        self.calibrate_button.setEnabled(True)
        self.platesolve_button.setEnabled(True)
        
        # Integration buttons are managed separately based on number of files
        # self.integration_button.setEnabled(True)
        # self.align_button.setEnabled(True)
    
    def update_align_button_visibility(self):
        """Update integration button visibility based on number of loaded files."""
        visible = len(self.parent.loaded_files) > 1
        self.filelist_action.setVisible(visible)
        # For QToolButton, always keep visible, but enable/disable
        if hasattr(self, 'integration_button'):
            self.integration_button.setEnabled(visible)
        if hasattr(self, 'align_button'):
            self.align_button.setEnabled(visible)
        self.toolbar.update()
        self.toolbar.repaint()
    
    def update_platesolve_button_visibility(self):
        """Enable platesolve button if at least one file is loaded."""
        self.platesolve_button.setEnabled(len(self.parent.loaded_files) > 0)
    
    def update_close_button_visibility(self):
        """Update the close button enabled state based on whether files are loaded."""
        self.close_action.setEnabled(len(self.parent.loaded_files) > 0)
    
    def update_delete_button_visibility(self):
        """Update the delete button enabled state based on whether files are loaded."""
        self.delete_action.setEnabled(len(self.parent.loaded_files) > 0)
    
 