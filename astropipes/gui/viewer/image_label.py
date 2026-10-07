"""The viewer's image widget: pan/zoom mouse handling, coordinates readout, overlay painting,
right-click menu (object position measurement)."""

from PyQt6.QtWidgets import QLabel, QMessageBox, QMenu, QApplication
from PyQt6.QtCore import Qt, QPoint, QTimer, QRect
from PyQt6.QtGui import QPixmap, QPainter, QMouseEvent, QKeyEvent, QPen, QColor, QCursor, QAction
import logging

from astropipes.gui.viewer.overlays import RegionFieldOverlay

logger = logging.getLogger(__name__)


class ImageLabel(QLabel):
    """Custom QLabel that handles mouse events for panning and zooming, and supports overlays"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_viewer = parent
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.coord_timer = QTimer()
        self.coord_timer.setSingleShot(True)
        self.coord_timer.timeout.connect(self._update_coordinates)
        self.last_mouse_pos = QPoint()
        self.panning = False
        self.pan_start_pos = QPoint()
        self.pan_start_scroll = QPoint()
        self.original_cursor = None
        self.pan_timer = QTimer()
        self.pan_timer.timeout.connect(self._update_pan)
        self.pan_timer.setInterval(16)
        self.target_scroll_pos = QPoint()
        self._custom_cross_cursor = self._create_cross_cursor()
        # --- Rectangle drag (zoom or define ROI) ---
        self._zoom_region_mode = False
        self._define_roi_mode = False
        self._zoom_region_start = None  # QPoint
        self._zoom_region_end = None    # QPoint
        self._zoom_region_active = False

    def _create_cross_cursor(self):
        # Create a 24x24 pixmap with a 1px thick white cross
        size = 24
        thickness = 1
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        pen = QPen(QColor(255, 255, 255), thickness)
        painter.setPen(pen)
        # Draw vertical line
        painter.drawLine(size // 2, 0, size // 2, size - 1)
        # Draw horizontal line
        painter.drawLine(0, size // 2, size - 1, size // 2)
        painter.end()
        # Hotspot at center
        return QCursor(pm, size // 2, size // 2)

    def enterEvent(self, event):
        if not self.panning:
            self.setCursor(self._custom_cross_cursor)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.panning:
            self.unsetCursor()
        super().leaveEvent(event)

    def set_zoom_region_mode(self, enabled):
        self._zoom_region_mode = enabled
        if enabled:
            self._define_roi_mode = False
        if not enabled:
            self._clear_rect_drag()
        self.update()

    def set_define_roi_mode(self, enabled):
        self._define_roi_mode = enabled
        if enabled:
            self._zoom_region_mode = False
        if not enabled:
            self._clear_rect_drag()
        self.update()

    def clear_zoom_region_rect(self):
        self._clear_rect_drag()

    def clear_define_roi_rect(self):
        self._clear_rect_drag()

    def _clear_rect_drag(self):
        self._zoom_region_start = None
        self._zoom_region_end = None
        self._zoom_region_active = False
        self.update()

    def _rect_drag_active(self):
        return self._zoom_region_mode or self._define_roi_mode

    def mousePressEvent(self, event: QMouseEvent):
        if self._rect_drag_active() and event.button() == Qt.MouseButton.LeftButton:
            self._zoom_region_start = event.pos()
            self._zoom_region_end = event.pos()
            self._zoom_region_active = True
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.update()
            return
        
        # Handle right-click events properly
        if event.button() == Qt.MouseButton.RightButton:
            # Let the context menu event handle this
            super().mousePressEvent(event)
            return
            
        if event.button() == Qt.MouseButton.LeftButton and self.parent_viewer:
            self.panning = True
            self.pan_start_pos = event.pos()
            scroll_area = self.parent_viewer.scroll_area
            self.pan_start_scroll = QPoint(
                scroll_area.horizontalScrollBar().value(),
                scroll_area.verticalScrollBar().value()
            )
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.setCursor(Qt.CursorShape.BlankCursor)
            self.pan_timer.start()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._rect_drag_active() and self._zoom_region_active:
            self._zoom_region_end = event.pos()
            self.update()
            return
        if self.parent_viewer and self.parent_viewer.pixmap is not None:
            if self.panning:
                delta = event.pos() - self.pan_start_pos
                self.target_scroll_pos = QPoint(
                    self.pan_start_scroll.x() - delta.x(),
                    self.pan_start_scroll.y() - delta.y()
                )
            else:
                self.last_mouse_pos = event.pos()
                if not self.coord_timer.isActive():
                    self.coord_timer.start(50)
        super().mouseMoveEvent(event)

    def _update_pan(self):
        if not self.panning or not self.parent_viewer:
            return
        scroll_area = self.parent_viewer.scroll_area
        h_scroll = scroll_area.horizontalScrollBar()
        v_scroll = scroll_area.verticalScrollBar()
        
        # Allow panning beyond image boundaries by not constraining to maximum values
        # This enables viewing "empty space" around the image when zoomed out
        target_h = self.target_scroll_pos.x()
        target_v = self.target_scroll_pos.y()
        
        current_h = h_scroll.value()
        current_v = v_scroll.value()
        interpolation_factor = 0.7
        new_h = int(current_h + (target_h - current_h) * interpolation_factor)
        new_v = int(current_v + (target_v - current_v) * interpolation_factor)
        
        # Set the scroll values without constraining to maximum
        # This allows negative values and values beyond the image size
        h_scroll.setValue(new_h)
        v_scroll.setValue(new_v)

    def _update_coordinates(self):
        if not self.parent_viewer or not self.parent_viewer.wcs or self.panning:
            return
        mouse_pos = self.last_mouse_pos
        pixmap = self.pixmap()
        if not pixmap or self.parent_viewer.image_data is None:
            return
        img_h, img_w = self.parent_viewer.image_data.shape
        pixmap_w = pixmap.width()
        pixmap_h = pixmap.height()
        label_w = self.width()
        label_h = self.height()
        # Compute centering offset and scale (aspect ratio preserved)
        scale_x = pixmap_w / img_w
        scale_y = pixmap_h / img_h
        scale = scale_x  # or scale_y, they should be equal
        x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
        y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
        # Map mouse position to image coordinates
        pixmap_x = mouse_pos.x() - x_offset
        pixmap_y = mouse_pos.y() - y_offset
        if (0 <= pixmap_x < pixmap_w and 0 <= pixmap_y < pixmap_h):
            orig_x = pixmap_x / scale
            orig_y = pixmap_y / scale
            # Use direct y (no flip)
            pixel_value = None
            try:
                if (0 <= orig_x < img_w and 0 <= orig_y < img_h):
                    pixel_value = self.parent_viewer.image_data[int(orig_y), int(orig_x)]
            except Exception:
                pixel_value = None
            # Format sky coordinates
            coord_text = ""
            if pixel_value is not None:
                pixel_str = f"({orig_x:.1f}, {orig_y:.1f})"
            else:
                pixel_str = "(--)"
            try:
                sky_coords = self.parent_viewer.wcs.pixel_to_world(orig_x, orig_y)
                if hasattr(sky_coords, 'ra') and hasattr(sky_coords, 'dec'):
                    ra = sky_coords.ra.to_string(unit='hourangle', precision=1, pad=True)
                    dec = sky_coords.dec.to_string(unit='deg', precision=1, alwayssign=True, pad=True)
                else:
                    ra = sky_coords[0].to_string(unit='hourangle', precision=1, pad=True)
                    dec = sky_coords[1].to_string(unit='deg', precision=1, alwayssign=True, pad=True)
                coord_text = f"{ra} {dec}  {pixel_str}"
            except Exception:
                coord_text = f"WCS error  {pixel_str}"
            # Update status bar labels
            if hasattr(self.parent_viewer, 'status_coord_label'):
                self.parent_viewer.status_coord_label.setText(coord_text)
            if hasattr(self.parent_viewer, 'status_pixel_label'):
                if pixel_value is not None:
                    self.parent_viewer.status_pixel_label.setText(str(pixel_value))
                else:
                    self.parent_viewer.status_pixel_label.setText("--")
        else:
            if hasattr(self.parent_viewer, 'status_coord_label'):
                self.parent_viewer.status_coord_label.setText("No WCS - coordinates unavailable")
            if hasattr(self.parent_viewer, 'status_pixel_label'):
                self.parent_viewer.status_pixel_label.setText("--")

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._rect_drag_active() and self._zoom_region_active and event.button() == Qt.MouseButton.LeftButton:
            self._zoom_region_end = event.pos()
            self._zoom_region_active = False
            self.setCursor(self._custom_cross_cursor)
            rect = self._get_zoom_region_rect()
            if rect is not None and self.parent_viewer is not None:
                (img_x0, img_y0), (img_x1, img_y1) = rect
                if self._define_roi_mode and hasattr(self.parent_viewer, "on_roi_region_selected"):
                    self.parent_viewer.on_roi_region_selected(img_x0, img_y0, img_x1, img_y1)
                else:
                    self.parent_viewer.zoom_to_region(img_x0, img_y0, img_x1, img_y1)
            self._zoom_region_start = None
            self._zoom_region_end = None
            self.update()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.parent_viewer:
            self.panning = False
            self.pan_timer.stop()
            # Always restore the custom cross cursor after panning
            self.setCursor(self._custom_cross_cursor)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if self.parent_viewer:
            if event.key() == Qt.Key.Key_Plus or event.key() == Qt.Key.Key_Equal:
                self.parent_viewer.zoom_in_at_center()
            elif event.key() == Qt.Key.Key_Minus:
                self.parent_viewer.zoom_out_at_center()
            elif event.key() == Qt.Key.Key_0:
                self.parent_viewer.reset_zoom()
            elif event.key() == Qt.Key.Key_O:
                self.parent_viewer.open_file()
        super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        # Draw SIMBAD overlay if enabled
        if (
            self.parent_viewer and
            hasattr(self.parent_viewer, '_simbad_overlay') and
            self.parent_viewer._simbad_overlay and
            getattr(self.parent_viewer, '_overlay_visible', True) and
            hasattr(self.parent_viewer, 'overlay_toolbar_controller') and
            self.parent_viewer.overlay_toolbar_controller.is_simbad_visible()
        ):
            try:
                from astropipes.gui.viewer.overlays import SIMBADOverlay
                simbad_object, pixel_coords = self.parent_viewer._simbad_overlay
                pixmap = self.pixmap()
                if pixmap is None or self.parent_viewer.image_data is None:
                    return
                img_h, img_w = self.parent_viewer.image_data.shape
                pixmap_w = pixmap.width()
                pixmap_h = pixmap.height()
                label_w = self.width()
                label_h = self.height()
                scale_x = pixmap_w / img_w
                scale_y = pixmap_h / img_h
                scale = scale_x
                x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
                y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
                x_img, y_img = pixel_coords
                # Use direct y (no flip)
                x_disp = x_img * scale + x_offset
                y_disp = y_img * scale + y_offset
                overlay = SIMBADOverlay(simbad_object.name, (x_disp, y_disp))
                painter = QPainter(self)
                overlay.draw(painter)
                painter.end()
            except Exception as e:
                pass
        # Draw SIMBAD field overlay if enabled
        if (
            self.parent_viewer and
            hasattr(self.parent_viewer, '_simbad_field_overlay') and
            self.parent_viewer._simbad_field_overlay and
            getattr(self.parent_viewer, '_overlay_visible', True) and
            hasattr(self.parent_viewer, 'overlay_toolbar_controller') and
            self.parent_viewer.overlay_toolbar_controller.is_simbad_visible()
        ):
            try:
                from astropipes.gui.viewer.overlays import SIMBADFieldOverlay
                simbad_objects, pixel_coords_list = self.parent_viewer._simbad_field_overlay
                pixmap = self.pixmap()
                if pixmap is None or self.parent_viewer.image_data is None:
                    return
                img_h, img_w = self.parent_viewer.image_data.shape
                pixmap_w = pixmap.width()
                pixmap_h = pixmap.height()
                label_w = self.width()
                label_h = self.height()
                scale_x = pixmap_w / img_w
                scale_y = pixmap_h / img_h
                scale = scale_x
                x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
                y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
                pixel_coords_disp = [
                    (x * scale + x_offset, y * scale + y_offset)
                    for (x, y) in pixel_coords_list
                ]
                highlight_index = getattr(self.parent_viewer, '_simbad_field_highlight_index', None)
                overlay = SIMBADFieldOverlay(simbad_objects, pixel_coords_disp, highlight_index=highlight_index)
                painter = QPainter(self)
                overlay.draw(painter)
                painter.end()
            except Exception as e:
                pass
        # Draw SSO overlay if enabled
        if (
            self.parent_viewer and
            hasattr(self.parent_viewer, '_sso_overlay') and
            self.parent_viewer._sso_overlay and
            getattr(self.parent_viewer, '_overlay_visible', True) and
            hasattr(self.parent_viewer, 'overlay_toolbar_controller') and
            self.parent_viewer.overlay_toolbar_controller.is_sso_visible()
        ):
            try:
                from astropipes.gui.viewer.overlays import SSOOverlay
                sso_objects, pixel_coords_list = self.parent_viewer._sso_overlay
                pixmap = self.pixmap()
                if pixmap is None or self.parent_viewer.image_data is None:
                    return
                img_h, img_w = self.parent_viewer.image_data.shape
                pixmap_w = pixmap.width()
                pixmap_h = pixmap.height()
                label_w = self.width()
                label_h = self.height()
                scale_x = pixmap_w / img_w
                scale_y = pixmap_h / img_h
                scale = scale_x
                x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
                y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
                pixel_coords_disp = [
                    (x * scale + x_offset, y * scale + y_offset)
                    for (x, y) in pixel_coords_list
                ]
                highlight_index = getattr(self.parent_viewer, '_sso_highlight_index', None)
                overlay = SSOOverlay(sso_objects, pixel_coords_disp, highlight_index=highlight_index)
                painter = QPainter(self)
                overlay.draw(painter)
                painter.end()
            except Exception as e:
                pass
        # Draw source overlay if enabled
        if (
            self.parent_viewer and
            hasattr(self.parent_viewer, '_source_overlay') and
            self.parent_viewer._source_overlay and
            getattr(self.parent_viewer, '_overlay_visible', True) and
            hasattr(self.parent_viewer, 'overlay_toolbar_controller') and
            self.parent_viewer.overlay_toolbar_controller.is_source_visible()
        ):
            try:
                from astropipes.gui.viewer.overlays import SourceOverlay
                sources, pixel_coords_list = self.parent_viewer._source_overlay
                pixmap = self.pixmap()
                if pixmap is None or self.parent_viewer.image_data is None:
                    return
                img_h, img_w = self.parent_viewer.image_data.shape
                pixmap_w = pixmap.width()
                pixmap_h = pixmap.height()
                label_w = self.width()
                label_h = self.height()
                scale_x = pixmap_w / img_w
                scale_y = pixmap_h / img_h
                scale = scale_x
                x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
                y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
                pixel_coords_disp = [
                    (x * scale + x_offset, y * scale + y_offset)
                    for (x, y) in pixel_coords_list
                ]
                highlight_index = getattr(self.parent_viewer, '_source_highlight_index', None)
                overlay = SourceOverlay(sources, pixel_coords_disp, highlight_index=highlight_index)
                painter = QPainter(self)
                overlay.draw(painter)
                painter.end()
            except Exception as e:
                pass
        # Draw Gaia overlay if enabled
        if (
            self.parent_viewer and
            hasattr(self.parent_viewer, '_gaia_overlay') and
            self.parent_viewer._gaia_overlay and
            getattr(self.parent_viewer, '_overlay_visible', True) and
            hasattr(self.parent_viewer, 'overlay_toolbar_controller') and
            self.parent_viewer.overlay_toolbar_controller.is_gaia_visible()
        ):
            try:
                from astropipes.gui.viewer.overlays import GaiaOverlay
                gaia_objects, pixel_coords_list = self.parent_viewer._gaia_overlay
                pixmap = self.pixmap()
                if pixmap is None or self.parent_viewer.image_data is None:
                    return
                img_h, img_w = self.parent_viewer.image_data.shape
                pixmap_w = pixmap.width()
                pixmap_h = pixmap.height()
                label_w = self.width()
                label_h = self.height()
                scale_x = pixmap_w / img_w
                scale_y = pixmap_h / img_h
                scale = scale_x
                x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
                y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
                pixel_coords_disp = [
                    (x * scale + x_offset, y * scale + y_offset)
                    for (x, y) in pixel_coords_list
                ]
                highlight_index = getattr(self.parent_viewer, '_gaia_highlight_index', None)
                overlay = GaiaOverlay(gaia_objects, pixel_coords_disp, highlight_index=highlight_index)
                painter = QPainter(self)
                overlay.draw(painter)
                painter.end()
            except Exception as e:
                pass
        # Draw ephemeris marker overlay if present
        if (
            self.parent_viewer and
            hasattr(self.parent_viewer, '_ephemeris_overlay') and
            self.parent_viewer._ephemeris_overlay is not None and
            getattr(self.parent_viewer, '_overlay_visible', True) and
            hasattr(self.parent_viewer, 'overlay_toolbar_controller') and
            self.parent_viewer.overlay_toolbar_controller.is_ephemeris_visible()
        ):
            try:
                pixmap = self.pixmap()
                if pixmap is None or self.parent_viewer.image_data is None:
                    return
                img_h, img_w = self.parent_viewer.image_data.shape
                pixmap_w = pixmap.width()
                pixmap_h = pixmap.height()
                label_w = self.width()
                label_h = self.height()
                scale_x = pixmap_w / img_w
                scale_y = pixmap_h / img_h
                scale = scale_x
                x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
                y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
                _, (x_img, y_img) = self.parent_viewer._ephemeris_overlay
                x_disp = x_img * scale + x_offset
                y_disp = y_img * scale + y_offset
                painter = QPainter(self)
                pen = QPen(QColor(255, 0, 0))
                pen.setWidth(1)  # Thinner lines
                painter.setPen(pen)
                radius = 24  # Twice as long as before
                gap = 6      # Length of the gap at the center
                # Draw a red cross with missing center (4 segments)
                # Horizontal segments
                painter.drawLine(int(x_disp - radius), int(y_disp), int(x_disp - gap), int(y_disp))
                painter.drawLine(int(x_disp + gap), int(y_disp), int(x_disp + radius), int(y_disp))
                # Vertical segments
                painter.drawLine(int(x_disp), int(y_disp - radius), int(x_disp), int(y_disp - gap))
                painter.drawLine(int(x_disp), int(y_disp + gap), int(x_disp), int(y_disp + radius))
                painter.end()
            except Exception as e:
                pass
        
        # Draw computed positions marker overlay if present
        if (
            self.parent_viewer and
            hasattr(self.parent_viewer, '_computed_positions_overlay') and
            self.parent_viewer._computed_positions_overlay is not None and
            getattr(self.parent_viewer, '_overlay_visible', True) and
            hasattr(self.parent_viewer, 'overlay_toolbar_controller') and
            self.parent_viewer.overlay_toolbar_controller.is_ephemeris_visible()  # Use same button as ephemeris
        ):
            try:
                pixmap = self.pixmap()
                if pixmap is None or self.parent_viewer.image_data is None:
                    return
                img_h, img_w = self.parent_viewer.image_data.shape
                pixmap_w = pixmap.width()
                pixmap_h = pixmap.height()
                label_w = self.width()
                label_h = self.height()
                scale_x = pixmap_w / img_w
                scale_y = pixmap_h / img_h
                scale = scale_x
                x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
                y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
                _, (x_img, y_img) = self.parent_viewer._computed_positions_overlay
                x_disp = x_img * scale + x_offset
                y_disp = y_img * scale + y_offset
                painter = QPainter(self)
                pen = QPen(QColor(0, 255, 0))  # Green color
                pen.setWidth(1)  # Thinner lines
                painter.setPen(pen)
                radius = 24  # Same size as ephemeris marker
                gap = 6      # Length of the gap at the center
                # Draw a green cross with missing center (4 segments)
                # Horizontal segments
                painter.drawLine(int(x_disp - radius), int(y_disp), int(x_disp - gap), int(y_disp))
                painter.drawLine(int(x_disp + gap), int(y_disp), int(x_disp + radius), int(y_disp))
                # Vertical segments
                painter.drawLine(int(x_disp), int(y_disp - radius), int(x_disp), int(y_disp - gap))
                painter.drawLine(int(x_disp), int(y_disp + gap), int(x_disp), int(y_disp + radius))
                painter.end()
            except Exception as e:
                pass
        
        # Draw measurement marker (yellow) if present
        if (
            self.parent_viewer and
            hasattr(self.parent_viewer, '_measurement_overlay') and
            self.parent_viewer._measurement_overlay is not None and
            getattr(self.parent_viewer, '_overlay_visible', True) and
            hasattr(self.parent_viewer, 'overlay_toolbar_controller') and
            self.parent_viewer.overlay_toolbar_controller.is_ephemeris_visible()  # same toggle
        ):
            try:
                pixmap = self.pixmap()
                if pixmap is None or self.parent_viewer.image_data is None:
                    return
                img_h, img_w = self.parent_viewer.image_data.shape
                pixmap_w, pixmap_h = pixmap.width(), pixmap.height()
                label_w,  label_h  = self.width(), self.height()
                scale_x = pixmap_w / img_w
                x_off   = (label_w  - pixmap_w) / 2.0  # Use float division to avoid integer truncation
                y_off   = (label_h  - pixmap_h) / 2.0  # Use float division to avoid integer truncation
                _, (x_img, y_img) = self.parent_viewer._measurement_overlay
                x_disp = x_img * scale_x + x_off
                y_disp = y_img * scale_x + y_off
                painter = QPainter(self)
                pen     = QPen(QColor(255, 255, 0))      # yellow
                pen.setWidth(1)
                painter.setPen(pen)
                radius = 24
                gap    = 6
                painter.drawLine(int(x_disp - radius), int(y_disp), int(x_disp - gap), int(y_disp))
                painter.drawLine(int(x_disp + gap), int(y_disp), int(x_disp + radius), int(y_disp))
                painter.drawLine(int(x_disp), int(y_disp - radius), int(x_disp), int(y_disp - gap))
                painter.drawLine(int(x_disp), int(y_disp + gap), int(x_disp), int(y_disp + radius))
                painter.end()
            except Exception:
                pass
        # Draw Gaia detection overlay if enabled
        if (
            self.parent_viewer and
            hasattr(self.parent_viewer, '_gaia_detection_overlay') and
            self.parent_viewer._gaia_detection_overlay and
            getattr(self.parent_viewer, '_overlay_visible', True) and
            hasattr(self.parent_viewer, 'overlay_toolbar_controller') and
            self.parent_viewer.overlay_toolbar_controller.is_gaia_detection_visible()
        ):
            try:
                from astropipes.gui.viewer.overlays import GaiaDetectionOverlay
                gaia_detection_results = self.parent_viewer._gaia_detection_overlay
                pixmap = self.pixmap()
                if pixmap is None or self.parent_viewer.image_data is None:
                    return
                img_h, img_w = self.parent_viewer.image_data.shape
                pixmap_w = pixmap.width()
                pixmap_h = pixmap.height()
                label_w = self.width()
                label_h = self.height()
                scale_x = pixmap_w / img_w
                scale_y = pixmap_h / img_h
                scale = scale_x
                x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
                y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
                
                # Extract pixel coordinates from detected sources and scale them properly
                pixel_coords_list = [(result[1].x, result[1].y) for result in gaia_detection_results]
                pixel_coords_disp = [
                    (x * scale + x_offset, y * scale + y_offset)
                    for (x, y) in pixel_coords_list
                ]
                
                highlight_index = getattr(self.parent_viewer, '_gaia_detection_highlight_index', None)
                overlay = GaiaDetectionOverlay(gaia_detection_results, pixel_coords_disp, highlight_index=highlight_index)
                painter = QPainter(self)
                overlay.draw(painter)
                painter.end()
            except Exception as e:
                pass
        # Draw regions of interest in field
        if (
            self.parent_viewer
            and hasattr(self.parent_viewer, "_roi_field_overlay")
            and self.parent_viewer._roi_field_overlay
            and getattr(self.parent_viewer, "_overlay_visible", True)
            and hasattr(self.parent_viewer, "overlay_toolbar_controller")
            and self.parent_viewer.overlay_toolbar_controller.is_roi_field_visible()
        ):
            try:
                pixmap = self.pixmap()
                if pixmap is None or self.parent_viewer.image_data is None:
                    return
                img_h, img_w = self.parent_viewer.image_data.shape
                pixmap_w = pixmap.width()
                pixmap_h = pixmap.height()
                label_w = self.width()
                label_h = self.height()
                scale = pixmap_w / img_w
                x_offset = (label_w - pixmap_w) / 2.0
                y_offset = (label_h - pixmap_h) / 2.0
                names = []
                rects_disp = []
                for name, (x0, y0, x1, y1) in self.parent_viewer._roi_field_overlay:
                    names.append(name)
                    rects_disp.append(
                        (
                            x0 * scale + x_offset,
                            y0 * scale + y_offset,
                            x1 * scale + x_offset,
                            y1 * scale + y_offset,
                        )
                    )
                overlay = RegionFieldOverlay(names, rects_disp)
                painter = QPainter(self)
                overlay.draw(painter)
                painter.end()
            except Exception:
                pass
        # Draw rectangle selection (zoom or ROI)
        if self._rect_drag_active() and (self._zoom_region_active or (self._zoom_region_start and self._zoom_region_end)):
            painter = QPainter(self)
            color = QColor(80, 220, 120) if self._define_roi_mode else QColor(0, 180, 255)
            pen = QPen(color, 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            start = self._zoom_region_start
            end = self._zoom_region_end
            if start and end:
                rect = QRect(start, end)
                painter.drawRect(rect.normalized())
            painter.end()
        # Remove info insert drawing; now handled by status bar 

    def _get_zoom_region_rect(self):
        # Returns ((img_x0, img_y0), (img_x1, img_y1)) in image coordinates, or None
        if self._zoom_region_start is None or self._zoom_region_end is None:
            return None
        pixmap = self.pixmap()
        if pixmap is None or self.parent_viewer is None or self.parent_viewer.image_data is None:
            return None
        img_h, img_w = self.parent_viewer.image_data.shape
        pixmap_w = pixmap.width()
        pixmap_h = pixmap.height()
        label_w = self.width()
        label_h = self.height()
        scale_x = pixmap_w / img_w
        scale_y = pixmap_h / img_h
        scale = scale_x
        x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
        y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
        def to_img_coords(qpoint):
            px = qpoint.x() - x_offset
            py = qpoint.y() - y_offset
            img_x = px / scale
            img_y = py / scale
            return (img_x, img_y)
        return to_img_coords(self._zoom_region_start), to_img_coords(self._zoom_region_end)

    def _get_coordinates_at_point(self, pos):
        """Get sky coordinates at a specific point in the format 'hh:mm:ss.s dd:mm:ss.s'"""
        if not self.parent_viewer or not self.parent_viewer.wcs:
            return None
        
        pixmap = self.pixmap()
        if not pixmap or self.parent_viewer.image_data is None:
            return None
        
        img_h, img_w = self.parent_viewer.image_data.shape
        pixmap_w = pixmap.width()
        pixmap_h = pixmap.height()
        label_w = self.width()
        label_h = self.height()
        
        # Compute centering offset and scale (aspect ratio preserved)
        scale_x = pixmap_w / img_w
        scale_y = pixmap_h / img_h
        scale = scale_x  # or scale_y, they should be equal
        x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
        y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
        
        # Map mouse position to image coordinates
        pixmap_x = pos.x() - x_offset
        pixmap_y = pos.y() - y_offset
        
        if (0 <= pixmap_x < pixmap_w and 0 <= pixmap_y < pixmap_h):
            orig_x = pixmap_x / scale
            orig_y = pixmap_y / scale
            
            try:
                sky_coords = self.parent_viewer.wcs.pixel_to_world(orig_x, orig_y)
                if hasattr(sky_coords, 'ra') and hasattr(sky_coords, 'dec'):
                    ra = sky_coords.ra.to_string(unit='hourangle', precision=1, pad=True)
                    dec = sky_coords.dec.to_string(unit='deg', precision=1, alwayssign=True, pad=True)
                else:
                    ra = sky_coords[0].to_string(unit='hourangle', precision=1, pad=True)
                    dec = sky_coords[1].to_string(unit='deg', precision=1, alwayssign=True, pad=True)
                return f"{ra} {dec}"
            except Exception:
                return None
        return None

    def contextMenuEvent(self, event):
        """Handle right-click context menu"""
        if not self.parent_viewer:
            return
        
        # Create context menu
        menu = QMenu(self)
        
        # Get coordinates at the right-click position
        coords = None
        if self.parent_viewer.wcs:
            coords = self._get_coordinates_at_point(event.pos())
        
        # Add "Copy coordinates" action only if coordinates are available
        if coords:
            copy_action = QAction("Copy coordinates", self)
            copy_action.triggered.connect(lambda: self._copy_coordinates_to_clipboard(coords))
            menu.addAction(copy_action)
        
        # Check if this is a motion tracked stacked image
        is_motion_tracked = self._is_motion_tracked_stacked_image()
        
        if is_motion_tracked:
            # Add separator if we have coordinates action
            if coords:
                menu.addSeparator()
            
            # Store the right-click position for use in compute_object_positions
            self._right_click_pos = event.pos()
            
            # Create "Compute object positions" action
            compute_positions_action = QAction("Compute object positions", self)
            compute_positions_action.triggered.connect(self._compute_object_positions)
            menu.addAction(compute_positions_action)
        
        # Show the menu at the cursor position (only if we have actions)
        if menu.actions():
            menu.exec(event.globalPos())

    def _is_motion_tracked_stacked_image(self):
        """Check if the current image is a motion tracked stacked image."""
        if not self.parent_viewer:
            return False
        
        if not hasattr(self.parent_viewer, '_current_header'):
            return False
        
        header = self.parent_viewer._current_header
        if not header:
            return False
        
        # Check for MOTION_TRACKED header field
        # Header values are stored as (value, comment) tuples
        motion_tracked_tuple = header.get('MOTION_TRACKED', (False, ''))
        tracked_object_tuple = header.get('TRACKED_OBJECT', (None, ''))
        combined_tuple = header.get('COMBINED', (False, ''))
        
        # Extract the actual values from the tuples
        motion_tracked = motion_tracked_tuple[0] if isinstance(motion_tracked_tuple, tuple) else motion_tracked_tuple
        tracked_object = tracked_object_tuple[0] if isinstance(tracked_object_tuple, tuple) else tracked_object_tuple
        combined = combined_tuple[0] if isinstance(combined_tuple, tuple) else combined_tuple
        
        # Handle the case where boolean values might be stored as strings
        if isinstance(motion_tracked, str):
            motion_tracked = motion_tracked.lower() in ('true', '1', 'yes')
        if isinstance(combined, str):
            combined = combined.lower() in ('true', '1', 'yes')
        
        return motion_tracked and tracked_object and combined

    def _compute_object_positions(self):
        """Compute object positions from motion tracked coordinates."""
        if not self.parent_viewer:
            return
        
        # Ensure a star catalog is loaded (check for Gaia catalog from SIMBAD search first, then legacy detection)
        has_gaia_catalog = False
        
        # Check for Gaia catalog loaded via SIMBAD search menu (preferred method)
        if (hasattr(self.parent_viewer, '_gaia_overlay') and 
            self.parent_viewer._gaia_overlay):
            has_gaia_catalog = True
            logger.debug("Found Gaia catalog from SIMBAD search")
        
        # Check for legacy Gaia detection results (source detection + matching)
        elif (hasattr(self.parent_viewer, '_gaia_detection_overlay') and 
              self.parent_viewer._gaia_detection_overlay):
            has_gaia_catalog = True
            logger.debug("Found legacy Gaia detection results")
        
        if not has_gaia_catalog:
            QMessageBox.warning(self.parent_viewer, "No Star Catalog",
                                 "Load a star catalog first before computing object positions.\n\n"
                                 "Recommended workflow:\n"
                                 "1. Go to SIMBAD search menu → 'Search Gaia catalog'\n"
                                 "2. Enter magnitude limit (e.g., 16.0)\n"
                                 "3. Then right-click on motion-tracked image → 'Compute object positions'\n\n"
                                 "Alternative: Use 'Detect Gaia Stars in Image' (less precise)")
            return

        # Get the current image path
        current_file_path = None
        if (self.parent_viewer.current_file_index >= 0 and 
            self.parent_viewer.current_file_index < len(self.parent_viewer.loaded_files)):
            current_file_path = self.parent_viewer.loaded_files[self.parent_viewer.current_file_index]
        
        if not current_file_path:
            QMessageBox.warning(self.parent_viewer, "No Image", "No image is currently loaded.")
            return
        
        # Get the stored right-click position in image coordinates
        if not hasattr(self, '_right_click_pos'):
            QMessageBox.warning(self.parent_viewer, "No Position", "No right-click position available.")
            return
        
        cursor_pos = self._right_click_pos
        
        # Convert cursor position to image coordinates
        pixmap = self.pixmap()
        if not pixmap or self.parent_viewer.image_data is None:
            QMessageBox.warning(self.parent_viewer, "No Image Data", "No image data available.")
            return
        
        img_h, img_w = self.parent_viewer.image_data.shape
        pixmap_w = pixmap.width()
        pixmap_h = pixmap.height()
        label_w = self.width()
        label_h = self.height()
        
        # Compute centering offset and scale
        scale_x = pixmap_w / img_w
        scale_y = pixmap_h / img_h
        scale = scale_x
        x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
        y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
        
        # Map cursor position to image coordinates
        pixmap_x = cursor_pos.x() - x_offset
        pixmap_y = cursor_pos.y() - y_offset
        
        if not (0 <= pixmap_x < pixmap_w and 0 <= pixmap_y < pixmap_h):
            QMessageBox.warning(self.parent_viewer, "Invalid Position", 
                              "Cursor position is outside the image area.")
            return
        
        orig_x = pixmap_x / scale
        orig_y = pixmap_y / scale
        
        # Show coordinate refinement dialog
        from astropipes.gui.common.dialogs.coordinate_refinement import CoordinateRefinementDialog
        
        refinement_dialog = CoordinateRefinementDialog(
            self.parent_viewer.image_data, 
            (orig_x, orig_y), 
            self.parent_viewer
        )
        
        # Connect the signal to handle refined coordinates
        refinement_dialog.coordinates_confirmed.connect(self._on_coordinates_refined)
        
        # Store the current file path for use in the callback
        self._pending_compute_file_path = current_file_path
        
        # Show the dialog
        refinement_dialog.exec()
        
        # Clean up the stored position
        if hasattr(self, '_right_click_pos'):
            delattr(self, '_right_click_pos')
    
    def _on_coordinates_refined(self, refined_x, refined_y):
        """Handle refined coordinates from the coordinate refinement dialog."""
        current_file_path = getattr(self, '_pending_compute_file_path', None)
        if not current_file_path:
            return
        
        # Format cursor coordinates for display
        cursor_coords = f"({refined_x:.1f}, {refined_y:.1f})"
        
        # Compute object positions using the refined coordinates
        try:
            from astropipes.processing.motion_tracking import compute_object_positions_from_motion_tracked
            
            positions = compute_object_positions_from_motion_tracked(
                current_file_path, 
                (refined_x, refined_y),
                loaded_files=self.parent_viewer.loaded_files
            )
            
            if not positions:
                QMessageBox.warning(self.parent_viewer, "No Positions", 
                                  "Could not compute positions for the original images.")
                return
            
            # Get the tracked object name from the header
            tracked_object = None
            if hasattr(self.parent_viewer, '_current_header') and self.parent_viewer._current_header:
                tracked_object_tuple = self.parent_viewer._current_header.get('TRACKED_OBJECT', (None, ''))
                tracked_object = tracked_object_tuple[0] if isinstance(tracked_object_tuple, tuple) else tracked_object_tuple
            
            if not tracked_object:
                tracked_object = "Unknown Object"
            
            # Show the positions in a new tab in the orbital elements window
            self._show_object_positions_tab(positions, tracked_object, cursor_coords)
            
        except Exception as e:
            QMessageBox.critical(self.parent_viewer, "Error", 
                               f"Error computing object positions: {str(e)}")
        finally:
            # Clean up the stored file path
            if hasattr(self, '_pending_compute_file_path'):
                delattr(self, '_pending_compute_file_path')
    
    def _show_object_positions_tab(self, positions, object_name, cursor_coords):
        """Show object positions in a new tab in the orbital elements window."""
        # Check if we have an existing orbital elements window
        orbit_window = None
        if hasattr(self.parent_viewer, '_orbit_window'):
            orbit_window = self.parent_viewer._orbit_window
        
        if not orbit_window:
            # Create a new orbital elements window
            from astropipes.gui.viewer.orbit.windows import OrbitDataWindow
            orbit_window = OrbitDataWindow(object_name, [], "", self.parent_viewer)
            self.parent_viewer._orbit_window = orbit_window
        
        # Add the positions tab
        orbit_window.add_positions_tab(positions, cursor_coords)
        
        # Show the window
        orbit_window.show()
        orbit_window.raise_()
        orbit_window.activateWindow()

    def _copy_coordinates_to_clipboard(self, coords):
        """Copy coordinates to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(coords)
