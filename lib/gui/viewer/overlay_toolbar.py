import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from PyQt6.QtWidgets import QToolBar, QToolButton, QWidget, QVBoxLayout, QSizePolicy
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import Qt


class OverlayToolbarController:
    """
    Handles the vertical overlay toolbar with individual toggle buttons for each overlay type.
    """
    
    def __init__(self, parent_viewer):
        self.parent = parent_viewer
        self.toolbar = None
        
        # Initialize overlay toggle actions
        self.ephemeris_toggle_action = None
        self.sso_toggle_action = None
        self.source_toggle_action = None
        self.simbad_toggle_action = None
        self.gaia_toggle_action = None
        self.gaia_detection_toggle_action = None
        self.roi_field_toggle_action = None
        
        # Overlay visibility states (separate from global overlay visibility)
        self._ephemeris_visible = True
        self._sso_visible = True
        self._source_visible = True
        self._simbad_visible = True
        self._gaia_visible = True
        self._gaia_detection_visible = True
        self._roi_field_visible = True
        
        # Create the toolbar
        self._create_toolbar()
        self._create_overlay_controls()
    
    def _create_toolbar(self):
        """Create and configure the vertical overlay toolbar."""
        self.toolbar = QToolBar("Overlay Toolbar")
        self.toolbar.setOrientation(Qt.Orientation.Vertical)
        self.toolbar.setMovable(False)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        
        # Set toolbar styling
        self.toolbar.setStyleSheet("""
            QToolBar { 
                background: #222222; 
                border-right: 1px solid #555555;
                spacing: 2px;
            }
            QToolButton { 
                border: none; 
                background: transparent; 
                padding: 4px;
                margin: 2px;
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
        
        # Add the toolbar to the left side of the main window
        self.parent.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self.toolbar)
    
    def _create_overlay_controls(self):
        """Create individual overlay toggle buttons."""
        
        # Ephemeris overlay toggle
        ephemeris_icon = QIcon.fromTheme("kstars_planets")
        if ephemeris_icon.isNull():
            ephemeris_icon = QIcon.fromTheme("applications-science")
        self.ephemeris_toggle_action = QAction(ephemeris_icon, "Toggle Ephemeris", self.parent)
        self.ephemeris_toggle_action.setCheckable(True)
        self.ephemeris_toggle_action.setChecked(True)
        self.ephemeris_toggle_action.setToolTip("Show/hide ephemeris markers")
        self.ephemeris_toggle_action.triggered.connect(self._toggle_ephemeris_overlay)
        self.toolbar.addAction(self.ephemeris_toggle_action)
        self.toolbar.widgetForAction(self.ephemeris_toggle_action).setFixedSize(32, 32)
        
        # SSO overlay toggle
        sso_icon = QIcon.fromTheme("kstars_planets")
        if sso_icon.isNull():
            sso_icon = QIcon.fromTheme("applications-science")
        self.sso_toggle_action = QAction(sso_icon, "Toggle SSO", self.parent)
        self.sso_toggle_action.setCheckable(True)
        self.sso_toggle_action.setChecked(True)
        self.sso_toggle_action.setToolTip("Show/hide Solar System Objects")
        self.sso_toggle_action.triggered.connect(self._toggle_sso_overlay)
        self.toolbar.addAction(self.sso_toggle_action)
        self.toolbar.widgetForAction(self.sso_toggle_action).setFixedSize(32, 32)
        
        # Source overlay toggle
        source_icon = QIcon.fromTheme("kstars_stars")
        if source_icon.isNull():
            source_icon = QIcon.fromTheme("starred")
        self.source_toggle_action = QAction(source_icon, "Toggle Sources", self.parent)
        self.source_toggle_action.setCheckable(True)
        self.source_toggle_action.setChecked(True)
        self.source_toggle_action.setToolTip("Show/hide detected sources")
        self.source_toggle_action.triggered.connect(self._toggle_source_overlay)
        self.toolbar.addAction(self.source_toggle_action)
        self.toolbar.widgetForAction(self.source_toggle_action).setFixedSize(32, 32)
        
        # SIMBAD overlay toggle
        simbad_icon = QIcon.fromTheme("file-search-symbolic")
        if simbad_icon.isNull():
            simbad_icon = QIcon.fromTheme("search")
        self.simbad_toggle_action = QAction(simbad_icon, "Toggle SIMBAD", self.parent)
        self.simbad_toggle_action.setCheckable(True)
        self.simbad_toggle_action.setChecked(True)
        self.simbad_toggle_action.setToolTip("Show/hide SIMBAD objects")
        self.simbad_toggle_action.triggered.connect(self._toggle_simbad_overlay)
        self.toolbar.addAction(self.simbad_toggle_action)
        self.toolbar.widgetForAction(self.simbad_toggle_action).setFixedSize(32, 32)
        
        # Gaia overlay toggle
        gaia_icon = QIcon.fromTheme("kstars_stars")
        if gaia_icon.isNull():
            gaia_icon = QIcon.fromTheme("starred")
        self.gaia_toggle_action = QAction(gaia_icon, "Toggle Gaia", self.parent)
        self.gaia_toggle_action.setCheckable(True)
        self.gaia_toggle_action.setChecked(True)
        self.gaia_toggle_action.setToolTip("Show/hide Gaia stars")
        self.gaia_toggle_action.triggered.connect(self._toggle_gaia_overlay)
        self.toolbar.addAction(self.gaia_toggle_action)
        self.toolbar.widgetForAction(self.gaia_toggle_action).setFixedSize(32, 32)
        
        # Gaia detection overlay toggle
        gaia_detection_icon = QIcon.fromTheme("kstars_stars")
        if gaia_detection_icon.isNull():
            gaia_detection_icon = QIcon.fromTheme("starred")
        self.gaia_detection_toggle_action = QAction(gaia_detection_icon, "Toggle Gaia Detection", self.parent)
        self.gaia_detection_toggle_action.setCheckable(True)
        self.gaia_detection_toggle_action.setChecked(True)
        self.gaia_detection_toggle_action.setToolTip("Show/hide matched Gaia stars")
        self.gaia_detection_toggle_action.triggered.connect(self._toggle_gaia_detection_overlay)
        self.toolbar.addAction(self.gaia_detection_toggle_action)
        self.toolbar.widgetForAction(self.gaia_detection_toggle_action).setFixedSize(32, 32)

        roi_icon = QIcon.fromTheme("draw-rectangle")
        if roi_icon.isNull():
            roi_icon = QIcon.fromTheme("select-rectangular")
        self.roi_field_toggle_action = QAction(roi_icon, "Toggle field regions", self.parent)
        self.roi_field_toggle_action.setCheckable(True)
        self.roi_field_toggle_action.setChecked(True)
        self.roi_field_toggle_action.setToolTip("Show/hide regions of interest in field")
        self.roi_field_toggle_action.triggered.connect(self._toggle_roi_field_overlay)
        self.toolbar.addAction(self.roi_field_toggle_action)
        self.toolbar.widgetForAction(self.roi_field_toggle_action).setFixedSize(32, 32)
    
    def _toggle_ephemeris_overlay(self):
        """Toggle ephemeris overlay visibility."""
        self._ephemeris_visible = not self._ephemeris_visible
        self.parent.image_label.update()
    
    def _toggle_sso_overlay(self):
        """Toggle SSO overlay visibility."""
        self._sso_visible = not self._sso_visible
        self.parent.image_label.update()
    
    def _toggle_source_overlay(self):
        """Toggle source overlay visibility."""
        self._source_visible = not self._source_visible
        self.parent.image_label.update()
    
    def _toggle_simbad_overlay(self):
        """Toggle SIMBAD overlay visibility."""
        self._simbad_visible = not self._simbad_visible
        self.parent.image_label.update()
    
    def _toggle_gaia_overlay(self):
        """Toggle Gaia overlay visibility."""
        self._gaia_visible = not self._gaia_visible
        self.parent.image_label.update()
    
    def _toggle_gaia_detection_overlay(self):
        """Toggle Gaia detection overlay visibility."""
        self._gaia_detection_visible = not self._gaia_detection_visible
        self.parent.image_label.update()

    def _toggle_roi_field_overlay(self):
        """Toggle field regions of interest overlay visibility."""
        self._roi_field_visible = not self._roi_field_visible
        self.parent.image_label.update()
    
    def update_overlay_button_visibility(self):
        """Update overlay button visibility based on overlay availability."""
        # Ephemeris button (controls ephemeris, measurement & computed markers)
        has_ephemeris = (
            (hasattr(self.parent, '_ephemeris_overlay') and self.parent._ephemeris_overlay is not None) or
            (hasattr(self.parent, '_computed_positions_overlay') and self.parent._computed_positions_overlay is not None) or
            (hasattr(self.parent, '_measurement_overlay') and self.parent._measurement_overlay is not None)
        )
        self.ephemeris_toggle_action.setVisible(has_ephemeris)
        if has_ephemeris:
            self.ephemeris_toggle_action.setChecked(self._ephemeris_visible)
        
        # SSO button
        has_sso = (hasattr(self.parent, '_sso_overlay') and 
                  self.parent._sso_overlay is not None)
        self.sso_toggle_action.setVisible(has_sso)
        if has_sso:
            self.sso_toggle_action.setChecked(self._sso_visible)
        
        # Source button
        has_source = (hasattr(self.parent, '_source_overlay') and 
                     self.parent._source_overlay is not None)
        self.source_toggle_action.setVisible(has_source)
        if has_source:
            self.source_toggle_action.setChecked(self._source_visible)
        
        # SIMBAD button (check both single object and field overlays)
        has_simbad = ((hasattr(self.parent, '_simbad_overlay') and 
                      self.parent._simbad_overlay is not None) or
                     (hasattr(self.parent, '_simbad_field_overlay') and 
                      self.parent._simbad_field_overlay is not None))
        self.simbad_toggle_action.setVisible(has_simbad)
        if has_simbad:
            self.simbad_toggle_action.setChecked(self._simbad_visible)
        
        # Gaia button
        has_gaia = (hasattr(self.parent, '_gaia_overlay') and 
                   self.parent._gaia_overlay is not None)
        self.gaia_toggle_action.setVisible(has_gaia)
        if has_gaia:
            self.gaia_toggle_action.setChecked(self._gaia_visible)
        
        # Gaia detection button
        has_gaia_detection = (hasattr(self.parent, '_gaia_detection_overlay') and 
                             self.parent._gaia_detection_overlay is not None)
        self.gaia_detection_toggle_action.setVisible(has_gaia_detection)
        if has_gaia_detection:
            self.gaia_detection_toggle_action.setChecked(self._gaia_detection_visible)

        has_roi_field = (
            hasattr(self.parent, "_roi_field_overlay")
            and self.parent._roi_field_overlay is not None
        )
        self.roi_field_toggle_action.setVisible(has_roi_field)
        if has_roi_field:
            self.roi_field_toggle_action.setChecked(self._roi_field_visible)
    
    def is_ephemeris_visible(self):
        """Check if ephemeris overlay should be visible."""
        return self._ephemeris_visible and getattr(self.parent, '_overlay_visible', True)
    
    def is_sso_visible(self):
        """Check if SSO overlay should be visible."""
        return self._sso_visible and getattr(self.parent, '_overlay_visible', True)
    
    def is_source_visible(self):
        """Check if source overlay should be visible."""
        return self._source_visible and getattr(self.parent, '_overlay_visible', True)
    
    def is_simbad_visible(self):
        """Check if SIMBAD overlay should be visible."""
        return self._simbad_visible and getattr(self.parent, '_overlay_visible', True)
    
    def is_gaia_visible(self):
        """Check if Gaia overlay should be visible."""
        return self._gaia_visible and getattr(self.parent, '_overlay_visible', True) 

    def is_gaia_detection_visible(self):
        """Check if Gaia detection overlay should be visible."""
        return self._gaia_detection_visible and getattr(self.parent, '_overlay_visible', True)

    def is_roi_field_visible(self):
        """Check if field regions of interest overlay should be visible."""
        return self._roi_field_visible and getattr(self.parent, "_overlay_visible", True)