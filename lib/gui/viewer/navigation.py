from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication

class NavigationMixin:
    def __init__(self):
        self._zoom = 1.0
        self._zoom_step = 1.15
        self._min_zoom = 0.05
        self._max_zoom = 20.0
        self._orig_pixmap = None
        self._panning = False
        self._last_pan_pos = None
        self._pan_speed = 1.5  # Coefficient to make panning match cursor
        super().__init__()

    def _get_viewport_center(self):
        """Get the current viewport center in image coordinates"""
        if self.image_label.pixmap() is None or self.image_data is None:
            return None
            
        hbar = self.scroll_area.horizontalScrollBar()
        vbar = self.scroll_area.verticalScrollBar()
        viewport_w = self.scroll_area.viewport().width()
        viewport_h = self.scroll_area.viewport().height()
        label_w = self.image_label.width()
        label_h = self.image_label.height()
        
        if label_w > 0 and label_h > 0:
            # Get the original image dimensions
            img_h, img_w = self.image_data.shape
            
            # Calculate the image dimensions in the current zoom
            pixmap_w = self.image_label.pixmap().width()
            pixmap_h = self.image_label.pixmap().height()
            
            # Calculate the scale factor (same as in overlay coordinate conversion)
            scale_x = pixmap_w / img_w
            scale_y = pixmap_h / img_h
            scale = scale_x  # or scale_y, they should be equal
            
            # Calculate the offset to center the image within the padded label
            x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
            y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
            
            # Get the center of the viewport in label coordinates
            # Use floating-point division for better precision
            center_x = hbar.value() + viewport_w / 2.0
            center_y = vbar.value() + viewport_h / 2.0
            
            # Convert from label coordinates to image coordinates (reverse of overlay conversion)
            pixmap_x = center_x - x_offset
            pixmap_y = center_y - y_offset
            
            if (0 <= pixmap_x < pixmap_w and 0 <= pixmap_y < pixmap_h):
                # Use precise floating-point division to avoid rounding errors
                img_cx = pixmap_x / scale
                img_cy = pixmap_y / scale
                return (img_cx, img_cy)
        return None

    def _set_viewport_center(self, img_cx, img_cy):
        """Centers the viewport on (img_cx, img_cy) in image coordinates"""
        if self.image_label.pixmap() is None:
            return
            
        viewport_w = self.scroll_area.viewport().width()
        viewport_h = self.scroll_area.viewport().height()
        label_w = self.image_label.width()
        label_h = self.image_label.height()
        
        if label_w > 0 and label_h > 0:
            # Get the original image dimensions
            img_h, img_w = self.image_data.shape
            
            # Calculate the image dimensions in the current zoom
            pixmap_w = self.image_label.pixmap().width()
            pixmap_h = self.image_label.pixmap().height()
            
            # Calculate the scale factor (same as in overlay coordinate conversion)
            scale_x = pixmap_w / img_w
            scale_y = pixmap_h / img_h
            scale = scale_x  # or scale_y, they should be equal
            
            # Calculate the offset to center the image within the padded label
            x_offset = (label_w - pixmap_w) / 2.0  # Use float division to avoid integer truncation
            y_offset = (label_h - pixmap_h) / 2.0  # Use float division to avoid integer truncation
            
            # Convert image coordinates to label coordinates (same as overlay conversion)
            # Use precise floating-point arithmetic to maintain consistency with _get_viewport_center
            center_x = img_cx * scale + x_offset
            center_y = img_cy * scale + y_offset
            
            hbar = self.scroll_area.horizontalScrollBar()
            vbar = self.scroll_area.verticalScrollBar()
            # Allow centering beyond image boundaries by not constraining to minimum values
            # Use round() instead of int() to minimize rounding errors
            hbar.setValue(round(center_x - viewport_w / 2.0))
            vbar.setValue(round(center_y - viewport_h / 2.0))

    def _center_image_in_viewport(self):
        """Center the image in the viewport, accounting for padding"""
        if self.image_label.pixmap() is None:
            return
        
        viewport_w = self.scroll_area.viewport().width()
        viewport_h = self.scroll_area.viewport().height()
        label_w = self.image_label.width()
        label_h = self.image_label.height()
        
        # Calculate the center of the image within the padded label
        # The image is centered in the label, so its center is at label_w/2, label_h/2
        # Use floating-point division for better precision
        image_center_x = label_w / 2.0
        image_center_y = label_h / 2.0
        
        # Calculate scroll position to center the image in the viewport
        hbar = self.scroll_area.horizontalScrollBar()
        vbar = self.scroll_area.verticalScrollBar()
        
        scroll_x = image_center_x - viewport_w / 2.0
        scroll_y = image_center_y - viewport_h / 2.0
        
        # Use round() to minimize rounding errors
        hbar.setValue(round(scroll_x))
        vbar.setValue(round(scroll_y))

    def reset_zoom(self):
        """Reset zoom to 1.0"""
        self._zoom = 1.0
        self.update_image_display(keep_zoom=False)

    def zoom_in_at_center(self):
        """Zoom in at the current viewport center"""
        if self._orig_pixmap is None:
            return
        self._zoom = min(self._zoom * 1.15, 20.0)
        self.update_image_display(keep_zoom=True)

    def zoom_out_at_center(self):
        """Zoom out at the current viewport center"""
        if self._orig_pixmap is None:
            return
        self._zoom = max(self._zoom / 1.15, 0.05)
        self.update_image_display(keep_zoom=True)

    def zoom_to_fit(self):
        """Zoom to fit the image in the viewport"""
        if self.image_label.pixmap() is None:
            return
        viewport = self.scroll_area.viewport()
        pixmap = self._orig_pixmap
        if pixmap is None:
            return
        # Compute scale to fit
        scale_x = viewport.width() / pixmap.width()
        scale_y = viewport.height() / pixmap.height()
        self._zoom = min(scale_x, scale_y)
        # Use the proper display update mechanism
        self.update_image_display(keep_zoom=False)
        # Center the image in the viewport
        self._center_image_in_viewport()
        # Force a repaint to ensure the viewport is updated
        self.image_label.update()
        self.scroll_area.viewport().update()
        # Force the viewport to center on the image
        label_w = self.image_label.width()
        label_h = self.image_label.height()
        viewport_w = self.scroll_area.viewport().width()
        viewport_h = self.scroll_area.viewport().height()
        # Use floating-point division for better precision
        center_x = (label_w - viewport_w) / 2.0
        center_y = (label_h - viewport_h) / 2.0
        hbar = self.scroll_area.horizontalScrollBar()
        vbar = self.scroll_area.verticalScrollBar()
        # Use round() to minimize rounding errors
        hbar.setValue(round(center_x))
        vbar.setValue(round(center_y))

    def zoom_to_region(self, img_x0, img_y0, img_x1, img_y1):
        """Zoom to a specific region defined by image coordinates"""
        # img_x0, img_y0, img_x1, img_y1 are in image coordinates (float)
        # Compute the rectangle in image coordinates
        x0, x1 = sorted([img_x0, img_x1])
        y0, y1 = sorted([img_y0, img_y1])
        width = x1 - x0
        height = y1 - y0
        if width < 5 or height < 5:
            return  # Ignore too small regions
        # Compute the zoom factor needed to fit this region in the viewport
        viewport = self.scroll_area.viewport()
        if width == 0 or height == 0:
            return
        scale_x = viewport.width() / width
        scale_y = viewport.height() / height
        self._zoom = min(scale_x, scale_y)
        # Center the viewport on the center of the selected region
        center_x = (x0 + x1) / 2
        center_y = (y0 + y1) / 2
        # Update display with new zoom level
        self.update_image_display(keep_zoom=False)  # Use keep_zoom=False to apply new zoom
        # Set viewport center after display is updated
        self._set_viewport_center(center_x, center_y)
        # Optionally, turn off region mode after zoom
        if hasattr(self, 'zoom_region_action'):
            self.zoom_region_action.setChecked(False)

    def wheelEvent(self, event):
        if not hasattr(self, 'image_label'):
            return super().wheelEvent(event)
        label = self.image_label
        # Do not set self._orig_pixmap here; it should be set by the viewer to the original image
        if self._orig_pixmap is None:
            return
        angle = event.angleDelta().y()
        if angle == 0:
            return
        
        # Get the current mouse position relative to the image label
        cursor_pos = event.position().toPoint()
        
        # Get current scroll position
        hbar = self.scroll_area.horizontalScrollBar()
        vbar = self.scroll_area.verticalScrollBar()
        
        # Calculate the point under the cursor in image coordinates before zoom
        # This is the point we want to keep centered during zoom
        cursor_x_in_label = cursor_pos.x() + hbar.value()
        cursor_y_in_label = cursor_pos.y() + vbar.value()
        
        # Get current image dimensions and padding
        current_width = int(self._orig_pixmap.width() * self._zoom)
        current_height = int(self._orig_pixmap.height() * self._zoom)
        padding = max(1000, max(current_width, current_height) * 2)
        current_padded_width = current_width + padding
        current_padded_height = current_height + padding
        
        # Calculate the offset to center the image within the padded label
        # Use floating-point division for better precision
        current_x_offset = (current_padded_width - current_width) / 2.0
        current_y_offset = (current_padded_height - current_height) / 2.0
        
        # Convert cursor position from label coordinates to image coordinates
        cursor_x_in_image = (cursor_x_in_label - current_x_offset) / self._zoom
        cursor_y_in_image = (cursor_y_in_label - current_y_offset) / self._zoom
        
        # Apply zoom change
        if angle > 0:
            self._zoom = min(self._zoom * self._zoom_step, self._max_zoom)
        else:
            self._zoom = max(self._zoom / self._zoom_step, self._min_zoom)
        
        # Calculate new image dimensions and padding
        new_width = int(self._orig_pixmap.width() * self._zoom)
        new_height = int(self._orig_pixmap.height() * self._zoom)
        
        # Add padding around the image to allow panning beyond boundaries
        padding = max(1000, max(new_width, new_height) * 2)  # At least 1000px or 2x image size
        padded_width = new_width + padding
        padded_height = new_height + padding
        label.setFixedSize(padded_width, padded_height)
        label.setPixmap(self._orig_pixmap.scaled(new_width, new_height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        
        # Calculate the new offset to center the image within the padded label
        # Use floating-point division for better precision
        new_x_offset = (padded_width - new_width) / 2.0
        new_y_offset = (padded_height - new_height) / 2.0
        
        # Calculate where the cursor point should be in the new zoomed image
        new_cursor_x_in_image = cursor_x_in_image * self._zoom
        new_cursor_y_in_image = cursor_y_in_image * self._zoom
        
        # Calculate the new scroll position to keep the cursor point centered
        new_scroll_x = int(new_cursor_x_in_image + new_x_offset - cursor_pos.x())
        new_scroll_y = int(new_cursor_y_in_image + new_y_offset - cursor_pos.y())
        
        # Set the new scroll position
        hbar.setValue(new_scroll_x)
        vbar.setValue(new_scroll_y)
        
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and hasattr(self, 'scroll_area'):
            self._panning = True
            self._last_pan_pos = event.position().toPoint()
            self.image_label.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and hasattr(self, 'scroll_area'):
            current_pos = event.position().toPoint()
            if self._last_pan_pos is None:
                self._last_pan_pos = current_pos
                event.accept()
                return
            delta = current_pos - self._last_pan_pos
            if delta.manhattanLength() == 0:
                event.accept()
                return
            hbar = self.scroll_area.horizontalScrollBar()
            vbar = self.scroll_area.verticalScrollBar()
            # Apply pan speed coefficient and allow panning beyond image boundaries
            new_h = hbar.value() - int(delta.x() * self._pan_speed)
            new_v = vbar.value() - int(delta.y() * self._pan_speed)
            # Set values without constraining to maximum/minimum to allow panning beyond boundaries
            hbar.setValue(new_h)
            vbar.setValue(new_v)
            self._last_pan_pos = current_pos
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._panning = False
            self._last_pan_pos = None
            # self.image_label.setCursor(Qt.CursorShape.ArrowCursor)  # Remove this line to allow custom cursor
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    # Image navigation functions
    def update_navigation_buttons(self):
        """Update the state of navigation buttons based on current file index."""
        self.toolbar_controller.update_navigation_buttons()

    def update_image_count_label(self):
        """Update the image count label in the toolbar."""
        self.toolbar_controller.update_image_count_label()

    def toggle_play_pause(self):
        """Toggle between play and pause states for slideshow mode."""
        if not self.toolbar_controller.playing:
            if len(self.loaded_files) > 1:
                self.toolbar_controller.playing = True
                self.play_pause_button.setIcon(self.pause_icon)
                self.play_pause_button.setToolTip("Pause slideshow")
                self.blink_timer.start()
        else:
            self.toolbar_controller.playing = False
            self.play_pause_button.setIcon(self.play_icon)
            self.play_pause_button.setToolTip("Play slideshow")
            self.blink_timer.stop()

    def _blink_next_image(self):
        """Show the next image in slideshow mode."""
        if len(self.loaded_files) > 1:
            self.show_next_file()

    def update_align_button_visibility(self):
        """Update alignment button visibility based on number of loaded files."""
        self.toolbar_controller.update_align_button_visibility()

    def update_platesolve_button_visibility(self):
        """Update platesolve button visibility based on whether files are loaded."""
        self.toolbar_controller.update_platesolve_button_visibility()

    def update_close_button_visibility(self):
        """Update the close button enabled state based on whether files are loaded."""
        self.toolbar_controller.update_close_button_visibility()
    
    def update_delete_button_visibility(self):
        """Update the delete button enabled state based on whether files are loaded."""
        self.toolbar_controller.update_delete_button_visibility()

    def update_button_states_for_no_image(self):
        """Disable all buttons that require an image to be loaded."""
        # Disable toolbar buttons (includes histogram controls)
        self.toolbar_controller.update_button_states_for_no_image()

    def update_button_states_for_image_loaded(self):
        """Enable all buttons that require an image to be loaded."""
        # Enable toolbar buttons (includes histogram controls)
        self.toolbar_controller.update_button_states_for_image_loaded()

    def on_zoom_region_toggled(self, checked):
        """Handle zoom region mode toggle."""
        if checked and getattr(self, "define_roi_action", None):
            self.define_roi_action.blockSignals(True)
            self.define_roi_action.setChecked(False)
            self.define_roi_action.blockSignals(False)
            if hasattr(self, "on_define_roi_toggled"):
                self.on_define_roi_toggled(False)
        self._zoom_region_mode = checked
        self.image_label.set_zoom_region_mode(checked)
        if not checked:
            self._pending_zoom_rect = None
            self.image_label.clear_zoom_region_rect() 