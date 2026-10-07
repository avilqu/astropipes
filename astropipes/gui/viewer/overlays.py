"""Overlay painters drawn on the viewer image (catalog objects, sources, regions) and the
viewer mixin that manages them."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QFont, QPen, QColor


class SIMBADOverlay:
    def __init__(self, name, pixel_coords, color=QColor(0, 255, 0), radius=12):
        self.name = name
        self.pixel_coords = pixel_coords  # (x, y)
        self.color = color
        self.radius = radius  # radius of the circle

    def draw(self, painter: QPainter):
        x, y = self.pixel_coords
        pen = QPen(self.color)
        pen.setWidth(3)
        painter.setPen(pen)
        # Draw circle
        painter.drawEllipse(int(x - self.radius), int(y - self.radius), 
                           int(2 * self.radius), int(2 * self.radius))
        # Draw name text to the right of the circle
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self.color)
        # Position text to the right of the circle with some spacing
        text_x = int(x + self.radius + 8)
        text_y = int(y + 4)  # Slightly below center for better alignment
        painter.drawText(text_x, text_y, self.name) 

class SourceOverlay:
    """Overlay for displaying detected sources in the image."""
    def __init__(self, sources, pixel_coords_list, color=QColor(160, 32, 240), radius=8, highlight_index=None):
        self.sources = sources  # List of DetectedSource
        self.pixel_coords_list = pixel_coords_list  # List of (x, y)
        self.color = color  # Purple color for sources
        self.radius = radius
        self.highlight_index = highlight_index

    def draw(self, painter: QPainter):
        font = QFont()
        font.setPointSize(8)
        font.setBold(False)
        painter.setFont(font)
        
        for idx, (source, (x, y)) in enumerate(zip(self.sources, self.pixel_coords_list)):
            if self.highlight_index is not None and idx == self.highlight_index:
                color = QColor(255, 0, 0)  # Red for highlight
                pen = QPen(color)
                pen.setWidth(3)
            else:
                color = self.color  # Purple for normal sources
                pen = QPen(color)
                pen.setWidth(2)
            
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(int(x - self.radius), int(y - self.radius), int(2 * self.radius), int(2 * self.radius))
            
            # Draw source ID to the right
            text_x = int(x + self.radius + 4)
            text_y = int(y + 4)
            painter.drawText(text_x, text_y, f"S{source.id}")


class SSOOverlay:
    def __init__(self, sso_objects, pixel_coords_list, color=QColor(255, 200, 0), radius=10, highlight_index=None):
        self.sso_objects = sso_objects  # List of SolarSystemObject
        self.pixel_coords_list = pixel_coords_list  # List of (x, y)
        self.color = color
        self.radius = radius
        self.highlight_index = highlight_index

    def _whiten_color(self, color, factor=0.5):
        # Blend color with white by the given factor (0.0 = original, 1.0 = white)
        r = int(color.red() + (255 - color.red()) * factor)
        g = int(color.green() + (255 - color.green()) * factor)
        b = int(color.blue() + (255 - color.blue()) * factor)
        return QColor(r, g, b)

    def draw(self, painter: QPainter):
        font = QFont()
        font.setPointSize(10)
        font.setBold(False)
        painter.setFont(font)
        for idx, (obj, (x, y)) in enumerate(zip(self.sso_objects, self.pixel_coords_list)):
            if self.highlight_index is not None and idx == self.highlight_index:
                color = QColor(255, 0, 0)  # Red for highlight
                pen = QPen(color)
                pen.setWidth(3)
            else:
                color = self.color
                pen = QPen(color)
                pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(int(x - self.radius), int(y - self.radius), int(2 * self.radius), int(2 * self.radius))
            # Draw name to the right
            text_x = int(x + self.radius + 4)
            text_y = int(y + 4)
            painter.drawText(text_x, text_y, obj.name)


class RegionFieldOverlay:
    """Overlay for saved regions of interest that overlap the current image field."""

    def __init__(self, regions, pixel_rects, color=QColor(80, 220, 120)):
        self.regions = regions  # list of region names
        self.pixel_rects = pixel_rects  # list of (x0, y0, x1, y1) display coordinates
        self.color = color

    def draw(self, painter: QPainter):
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        pen = QPen(self.color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for name, (x0, y0, x1, y1) in zip(self.regions, self.pixel_rects):
            rx = int(min(x0, x1))
            ry = int(min(y0, y1))
            rw = int(abs(x1 - x0))
            rh = int(abs(y1 - y0))
            painter.drawRect(rx, ry, rw, rh)
            painter.drawText(rx + 4, ry + 14, name)


class SIMBADFieldOverlay:
    """Overlay for displaying multiple SIMBAD objects found in the field."""
    def __init__(self, simbad_objects, pixel_coords_list, color=QColor(0, 255, 0), radius=8, highlight_index=None):
        self.simbad_objects = simbad_objects  # List of SIMBADObject
        self.pixel_coords_list = pixel_coords_list  # List of (x, y)
        self.color = color
        self.radius = radius
        self.highlight_index = highlight_index

    def draw(self, painter: QPainter):
        font = QFont()
        font.setPointSize(9)
        font.setBold(False)
        painter.setFont(font)
        
        for idx, (obj, (x, y)) in enumerate(zip(self.simbad_objects, self.pixel_coords_list)):
            if self.highlight_index is not None and idx == self.highlight_index:
                color = QColor(255, 0, 0)  # Red for highlight
                pen = QPen(color)
                pen.setWidth(3)
            else:
                color = self.color
                pen = QPen(color)
                pen.setWidth(2)
            
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(int(x - self.radius), int(y - self.radius), int(2 * self.radius), int(2 * self.radius))
            
            # Draw name to the right
            text_x = int(x + self.radius + 4)
            text_y = int(y + 4)
            painter.drawText(text_x, text_y, obj.name)


class GaiaOverlay:
    """Overlay for displaying Gaia stars in the image."""
    def __init__(self, gaia_objects, pixel_coords_list, color=QColor(0, 255, 255), radius=6, highlight_index=None):
        self.gaia_objects = gaia_objects  # List of GaiaObject
        self.pixel_coords_list = pixel_coords_list  # List of (x, y)
        self.color = color
        self.radius = radius
        self.highlight_index = highlight_index

    def draw(self, painter: QPainter):
        font = QFont()
        font.setPointSize(8)
        font.setBold(False)
        painter.setFont(font)
        
        for idx, (obj, (x, y)) in enumerate(zip(self.gaia_objects, self.pixel_coords_list)):
            if self.highlight_index is not None and idx == self.highlight_index:
                color = QColor(255, 0, 0)  # Red for highlight
                pen = QPen(color)
                pen.setWidth(3)
            else:
                color = self.color  # Use consistent color for all stars
                pen = QPen(color)
                pen.setWidth(2)
            
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(int(x - self.radius), int(y - self.radius), int(2 * self.radius), int(2 * self.radius))
            
            # Draw source ID to the right for highlighted objects
            if self.highlight_index is not None and idx == self.highlight_index:
                text_x = int(x + self.radius + 4)
                text_y = int(y + 4)
                painter.drawText(text_x, text_y, obj.source_id)


class GaiaDetectionOverlay:
    """Overlay for displaying matched Gaia stars with detected sources."""
    def __init__(self, gaia_detection_results, pixel_coords_list, color=QColor(160, 32, 240), radius=8, highlight_index=None):
        self.gaia_detection_results = gaia_detection_results  # List of (GaiaObject, DetectedSource, distance_arcsec)
        self.pixel_coords_list = pixel_coords_list  # List of (x, y) display coordinates
        self.color = color  # Purple color like sources
        self.radius = radius
        self.highlight_index = highlight_index

    def draw(self, painter: QPainter):
        font = QFont()
        font.setPointSize(8)
        font.setBold(False)
        painter.setFont(font)
        
        for idx, ((gaia_obj, detected_source, distance_arcsec), (x, y)) in enumerate(zip(self.gaia_detection_results, self.pixel_coords_list)):
            if self.highlight_index is not None and idx == self.highlight_index:
                color = QColor(255, 0, 0)  # Red for highlight
                pen = QPen(color)
                pen.setWidth(3)
            else:
                color = self.color  # Purple for normal matched sources
                pen = QPen(color)
                pen.setWidth(2)
            
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(int(x - self.radius), int(y - self.radius), int(2 * self.radius), int(2 * self.radius))
            
            # Only draw Gaia source ID and distance when highlighted
            if self.highlight_index is not None and idx == self.highlight_index:
                text_x = int(x + self.radius + 4)
                text_y = int(y + 4)
                painter.drawText(text_x, text_y, f"G{gaia_obj.source_id} ({distance_arcsec:.1f}\")")


class OverlayMixin:
    """Mixin class providing overlay functionality for the FITS viewer."""

    def on_sso_row_selected(self, row_index):
        """Handle selection of a Solar System Object row."""
        self._sso_highlight_index = row_index
        self.image_label.update()

    def on_simbad_field_row_selected(self, row_index):
        """Handle selection of a SIMBAD field object row."""
        self._simbad_field_highlight_index = row_index
        self.image_label.update()

    def on_gaia_row_selected(self, row_index):
        """Handle Gaia row selection for highlighting."""
        self._gaia_highlight_index = row_index
        self.image_label.update()

    def on_source_row_selected(self, row_index):
        """Handle source row selection for highlighting."""
        self._source_highlight_index = row_index
        self.image_label.update()

    def on_ephemeris_row_selected(self, row_index, ephemeris):
        """
        Handle selection of an ephemeris row and show marker at the predicted position.
        """
        # Save current brightness before switching
        self.histogram_controller.save_state_before_switch()
        # Save current viewport state before switching
        if hasattr(self, '_zoom'):
            self._last_zoom = self._zoom
        self._last_center = self._get_viewport_center()
        # Load the corresponding FITS file and add a marker at the ephemeris position
        if not (0 <= row_index < len(self.loaded_files)):
            return
        self.current_file_index = row_index
        self.load_fits(self.loaded_files[row_index], restore_view=True)
        self.update_close_button_visibility()
        self.update_delete_button_visibility()
        
        # The ephemeris marker will be updated by the load_fits method calling update_ephemeris_marker
        self.image_label.update()

    def _show_ephemeris_marker(self, pixel_coords):
        """Store the marker position for overlay drawing."""
        self._ephemeris_marker_coords = pixel_coords
        self._overlay_visible = True
        if hasattr(self, 'overlay_toolbar_controller'):
            self.overlay_toolbar_controller.update_overlay_button_visibility()
        self.image_label.update()

    def on_computed_positions_row_selected(self, row_index, position_data):
        """Handle selection of a computed positions row and show marker at the position."""
        # Save current brightness before switching
        self.histogram_controller.save_state_before_switch()
        # Save current viewport state before switching
        if hasattr(self, '_zoom'):
            self._last_zoom = self._zoom
        self._last_center = self._get_viewport_center()
        
        # Get the file path from the position data
        file_path = position_data.get('file_path')
        if not file_path:
            return
        
        # Find the file in the loaded files list
        try:
            file_index = self.loaded_files.index(file_path)
        except ValueError:
            # File not in loaded files, try to load it
            try:
                self.open_and_add_file(file_path)
                file_index = len(self.loaded_files) - 1
            except Exception as e:
                print(f"Error loading file {file_path}: {e}")
                return
        
        # Load the corresponding FITS file
        if 0 <= file_index < len(self.loaded_files):
            self.current_file_index = file_index
            self.load_fits(self.loaded_files[file_index], restore_view=True)
            self.update_close_button_visibility()
        self.update_delete_button_visibility()
        
        # The computed positions marker will be updated by the load_fits method calling update_computed_positions_marker
        self.image_label.update() 