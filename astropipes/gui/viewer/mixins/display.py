import numpy as np
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import Qt, QTimer

def create_image_object(image_data: np.ndarray, display_min=None, display_max=None, clipping=False, sigma_clip=3):
    """Convert numpy array to QPixmap for display - optimized version. NaNs are replaced with the minimum finite value. If clipping is True, use sigma_clip-sigma clipping for display range."""
    # Replace NaNs with the minimum finite value
    if np.isnan(image_data).any():
        finite_vals = image_data[np.isfinite(image_data)]
        fill_value = np.min(finite_vals) if finite_vals.size > 0 else 0
        image_data = np.nan_to_num(image_data, nan=fill_value)
    # Use provided display range or calculate from histogram or sigma clipping
    if display_min is None or display_max is None:
        if clipping:
            finite_vals = image_data[np.isfinite(image_data)]
            if finite_vals.size > 0:
                mean = np.mean(finite_vals)
                std = np.std(finite_vals)
                display_min = mean - sigma_clip * std
                display_max = mean + sigma_clip * std
            else:
                display_min = np.min(image_data)
                display_max = np.max(image_data)
        else:
            histo = np.histogram(image_data, 60, None, True)
            display_min = histo[1][0]
            display_max = histo[1][-1]
    # Apply histogram stretching
    if display_max > display_min:
        clipped_data = np.clip(image_data, display_min, display_max)
        normalized_data = (clipped_data - display_min) / (display_max - display_min)
    else:
        normalized_data = image_data - image_data.min()
        if normalized_data.max() > 0:
            normalized_data = normalized_data / normalized_data.max()
    # Convert to 8-bit for display
    display_data = (normalized_data * 255).astype(np.uint8)
    # Create QImage from numpy array
    height, width = display_data.shape
    display_data = np.ascontiguousarray(display_data)
    q_image = QImage(display_data.data, width, height, width, QImage.Format.Format_Grayscale8)
    q_image = q_image.copy()
    # Convert to pixmap
    return QPixmap.fromImage(q_image)


class DisplayMixin:
    """Mixin class providing image display functionality for the FITS viewer."""
    
    def update_image_display(self, keep_zoom=False):
        """Update the image display with current data and zoom level."""
        if self.image_data is None:
            return
        # Save current zoom and viewport center
        if keep_zoom:
            current_zoom = self._zoom if hasattr(self, '_zoom') else 1.0
            # Save current viewport center for restoration
            saved_center = self._get_viewport_center()
        else:
            current_zoom = getattr(self, '_zoom', 1.0)
        viewport_w = self.scroll_area.viewport().width()
        viewport_h = self.scroll_area.viewport().height()
        
        # Get display parameters from histogram controller
        params = self.histogram_controller.get_display_parameters()
        if params['stretch_mode'] == 'linear':
            orig_pixmap = create_image_object(self.image_data, display_min=params['display_min'], display_max=params['display_max'], clipping=params['clipping'], sigma_clip=params['sigma_clip'])
        else:
            data = self.image_data.astype(float)
            # Avoid divide-by-zero warning by only computing log10 for positive values
            mask = data > 0
            log_data = np.zeros_like(data)
            log_data[mask] = np.log10(data[mask])
            orig_pixmap = create_image_object(log_data, display_min=params['display_min'], display_max=params['display_max'], clipping=params['clipping'], sigma_clip=params['sigma_clip'])
        self._orig_pixmap = orig_pixmap  # Always set to the unscaled pixmap
        # Set the display pixmap according to current zoom
        new_width = int(orig_pixmap.width() * self._zoom)
        new_height = int(orig_pixmap.height() * self._zoom)
        display_pixmap = orig_pixmap.scaled(new_width, new_height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(display_pixmap)
        
        # Add padding around the image to allow panning beyond boundaries
        # The padding should be large enough to allow significant panning
        padding = max(1000, max(new_width, new_height) * 2)  # At least 1000px or 2x image size
        padded_width = new_width + padding
        padded_height = new_height + padding
        self.image_label.setFixedSize(padded_width, padded_height)
        self.pixmap = orig_pixmap
        # Set scale_factor for coordinate conversion
        self.scale_factor = self._zoom if hasattr(self, '_zoom') else 1.0
        
        # If this is a new image (not restoring view), center it in the viewport
        if not keep_zoom:
            self._center_image_in_viewport()
        else:
            # Restore the viewport center with a delay to ensure image is fully loaded and displayed
            if saved_center:
                def restore_center():
                    # Double-check that the image is ready before restoring viewport
                    if (self.image_label.pixmap() is not None and 
                        self.image_label.width() > 0 and 
                        self.image_label.height() > 0):
                        self._set_viewport_center(saved_center[0], saved_center[1])
                    else:
                        # If still not ready, try again with a longer delay
                        QTimer.singleShot(50, restore_center)
                # Use a longer initial delay to ensure image is fully processed
                QTimer.singleShot(50, restore_center)
        # If zoom mode is set to fit, update zoom
        if getattr(self, '_pending_zoom_to_fit', False):
            self._pending_zoom_to_fit = False
            self.zoom_to_fit()