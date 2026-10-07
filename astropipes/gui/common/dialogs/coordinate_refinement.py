from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QKeyEvent
import numpy as np

class CoordinateRefinementDialog(QDialog):
    """Dialog for refining coordinates by showing a zoomed-in view with a movable marker."""
    
    coordinates_confirmed = pyqtSignal(float, float)  # Signal with refined x, y coordinates
    
    def __init__(self, image_data, initial_coords, parent=None):
        super().__init__(parent)
        self.image_data = image_data
        self.initial_x, self.initial_y = initial_coords
        self.marker_x, self.marker_y = initial_coords
        
        # Window setup
        self.setWindowTitle("Refine Coordinates")
        self.setFixedSize(300, 350)  # 300x300 for image + 50 for button
        self.setModal(True)
        
        # Create layout
        layout = QVBoxLayout(self)
        
        # Create image label
        self.image_label = QLabel()
        self.image_label.setFixedSize(300, 300)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("QLabel { background-color: black; border: 1px solid gray; }")
        layout.addWidget(self.image_label)
        
        # Create button layout
        button_layout = QHBoxLayout()
        
        # Confirm button
        self.confirm_button = QPushButton("Confirm")
        self.confirm_button.clicked.connect(self._on_confirm)
        button_layout.addWidget(self.confirm_button)
        
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        # Set focus to the dialog for keyboard events
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # Generate the zoomed image
        self._generate_zoomed_image()
        
    def _generate_zoomed_image(self):
        """Generate a zoomed-in view of the 100x100 pixel area around the initial coordinates."""
        if self.image_data is None:
            return
            
        img_h, img_w = self.image_data.shape
        
        # Calculate the 50x50 pixel area around the initial coordinates
        half_size = 25
        x0 = max(0, int(self.initial_x - half_size))
        y0 = max(0, int(self.initial_y - half_size))
        x1 = min(img_w, int(self.initial_x + half_size))
        y1 = min(img_h, int(self.initial_y + half_size))
        
        # Extract the region
        region = self.image_data[y0:y1, x0:x1]
        
        if region.size == 0:
            return
            
        # Get histogram parameters from parent viewer if available
        display_min = None
        display_max = None
        clipping = False
        sigma_clip = 3.0
        stretch_mode = 'linear'
        
        if hasattr(self.parent(), 'histogram_controller'):
            params = self.parent().histogram_controller.get_display_parameters()
            display_min = params['display_min']
            display_max = params['display_max']
            clipping = params['clipping']
            sigma_clip = params['sigma_clip']
            stretch_mode = params['stretch_mode']
        
        # Apply the same histogram stretching as the main viewer
        if stretch_mode == 'log':
            # Apply log stretch to the region
            data = region.astype(float)
            mask = data > 0
            log_data = np.zeros_like(data)
            log_data[mask] = np.log10(data[mask])
            region = log_data
        
        # Use the same create_image_object logic as the main viewer
        from astropipes.gui.viewer.mixins.display import create_image_object
        pixmap = create_image_object(region, display_min=display_min, display_max=display_max, 
                                   clipping=clipping, sigma_clip=sigma_clip)
        
        # Scale to fill the whole 300x300 window (6x zoom for 50x50 region)
        scaled_pixmap = pixmap.scaled(300, 300, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        
        # Store the scaling information for coordinate conversion
        self.scale_x = scaled_pixmap.width() / region.shape[1]  # Should be 6.0 (300/50)
        self.scale_y = scaled_pixmap.height() / region.shape[0]  # Should be 6.0 (300/50)
        self.offset_x = 0  # No offset since we fill the whole window
        self.offset_y = 0  # No offset since we fill the whole window
        self.region_x0 = x0
        self.region_y0 = y0
        
        # Create a pixmap with the yellow marker
        self._draw_marker_on_pixmap(scaled_pixmap)
        
        self.image_label.setPixmap(scaled_pixmap)
        
    def _draw_marker_on_pixmap(self, pixmap):
        """Draw a yellow marker at the current marker position."""
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Calculate marker position in the scaled pixmap
        marker_rel_x = self.marker_x - self.region_x0
        marker_rel_y = self.marker_y - self.region_y0
        marker_pixmap_x = int(marker_rel_x * self.scale_x + self.offset_x)
        marker_pixmap_y = int(marker_rel_y * self.scale_y + self.offset_y)
        
        # Draw green cross marker (same style as ephemeris marker)
        pen = QPen(QColor(0, 255, 0))  # Green
        pen.setWidth(1)  # Thinner lines like ephemeris marker
        painter.setPen(pen)
        
        # Draw a cross with missing center (4 segments) - same as ephemeris marker but doubled scale
        radius = 24  # Doubled from 12 to match the request
        gap = 6      # Doubled from 3 to match the request
        
        # Horizontal segments
        painter.drawLine(marker_pixmap_x - radius, marker_pixmap_y, marker_pixmap_x - gap, marker_pixmap_y)
        painter.drawLine(marker_pixmap_x + gap, marker_pixmap_y, marker_pixmap_x + radius, marker_pixmap_y)
        
        # Vertical segments
        painter.drawLine(marker_pixmap_x, marker_pixmap_y - radius, marker_pixmap_x, marker_pixmap_y - gap)
        painter.drawLine(marker_pixmap_x, marker_pixmap_y + gap, marker_pixmap_x, marker_pixmap_y + radius)
        
        painter.end()
        
    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard events for moving the marker."""
        step = 0.5  # Small increment for precise movement
        
        if event.key() == Qt.Key.Key_Left:
            self.marker_x -= step
        elif event.key() == Qt.Key.Key_Right:
            self.marker_x += step
        elif event.key() == Qt.Key.Key_Up:
            self.marker_y -= step
        elif event.key() == Qt.Key.Key_Down:
            self.marker_y += step
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self._on_confirm()
            return
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        else:
            super().keyPressEvent(event)
            return
            
        # Clamp marker position to image bounds
        img_h, img_w = self.image_data.shape
        self.marker_x = max(0, min(img_w - 1, self.marker_x))
        self.marker_y = max(0, min(img_h - 1, self.marker_y))
        
        # Redraw the image with updated marker
        self._generate_zoomed_image()
        
    def _on_confirm(self):
        """Handle confirm button click."""
        self.coordinates_confirmed.emit(self.marker_x, self.marker_y)
        self.accept() 