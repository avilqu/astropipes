#!/usr/bin/env python3
"""
Source Detection Parameters Dialog
A dialog for customizing source detection parameters before execution.
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, 
                              QSpinBox, QDoubleSpinBox, QCheckBox, QLabel, QGroupBox, QDialogButtonBox)


class SourceDetectionDialog(QDialog):
    """Dialog for configuring source detection parameters."""
    
    def __init__(self, parent=None, default_params=None):
        super().__init__(parent)
        self.setWindowTitle("Source Detection Parameters")
        self.setModal(True)
        self.setMinimumWidth(400)
        
        # Default parameters if none provided
        if default_params is None:
            default_params = {
                'threshold_sigma': 2.5,
                'npixels': 8,
                'min_area': 15,
                'min_snr': 4.0,
                'max_area': 1000,
                'min_eccentricity': 0.0,
                'max_eccentricity': 0.9,
                'deblend': False,
                'connectivity': 8,
                'background_box_size': 100,
                'background_filter_size': 5
            }
        
        self.params = default_params.copy()
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        
        # Add description
        desc_label = QLabel(
            "Configure source detection parameters. Higher values for thresholds "
            "and minimums will result in fewer but higher-quality detections."
        )
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        # Detection thresholds group
        threshold_group = QGroupBox("Detection Thresholds")
        threshold_layout = QFormLayout(threshold_group)
        
        self.threshold_sigma = QDoubleSpinBox()
        self.threshold_sigma.setRange(0.5, 10.0)
        self.threshold_sigma.setSingleStep(0.1)
        self.threshold_sigma.setValue(self.params['threshold_sigma'])
        self.threshold_sigma.setToolTip("Number of sigma above background for detection threshold")
        threshold_layout.addRow("Threshold Sigma:", self.threshold_sigma)
        
        self.npixels = QSpinBox()
        self.npixels.setRange(1, 50)
        self.npixels.setValue(self.params['npixels'])
        self.npixels.setToolTip("Minimum number of connected pixels for a source")
        threshold_layout.addRow("Min Connected Pixels:", self.npixels)
        
        layout.addWidget(threshold_group)
        
        # Source filtering group
        filter_group = QGroupBox("Source Filtering")
        filter_layout = QFormLayout(filter_group)
        
        self.min_area = QSpinBox()
        self.min_area.setRange(1, 1000)
        self.min_area.setValue(self.params['min_area'])
        self.min_area.setToolTip("Minimum area in pixels for a source")
        filter_layout.addRow("Min Area (pixels):", self.min_area)
        
        self.max_area = QSpinBox()
        self.max_area.setRange(10, 10000)
        self.max_area.setValue(self.params['max_area'])
        self.max_area.setToolTip("Maximum area in pixels for a source (filters out extended objects)")
        filter_layout.addRow("Max Area (pixels):", self.max_area)
        
        self.min_snr = QDoubleSpinBox()
        self.min_snr.setRange(0.1, 20.0)
        self.min_snr.setSingleStep(0.1)
        self.min_snr.setValue(self.params['min_snr'])
        self.min_snr.setToolTip("Minimum signal-to-noise ratio for a source")
        filter_layout.addRow("Min SNR:", self.min_snr)
        
        self.min_eccentricity = QDoubleSpinBox()
        self.min_eccentricity.setRange(0.0, 1.0)
        self.min_eccentricity.setSingleStep(0.1)
        self.min_eccentricity.setValue(self.params['min_eccentricity'])
        self.min_eccentricity.setToolTip("Minimum eccentricity for a source")
        filter_layout.addRow("Min Eccentricity:", self.min_eccentricity)
        
        self.max_eccentricity = QDoubleSpinBox()
        self.max_eccentricity.setRange(0.0, 1.0)
        self.max_eccentricity.setSingleStep(0.1)
        self.max_eccentricity.setValue(self.params['max_eccentricity'])
        self.max_eccentricity.setToolTip("Maximum eccentricity for a source (filters out very elongated objects)")
        filter_layout.addRow("Max Eccentricity:", self.max_eccentricity)
        
        layout.addWidget(filter_group)
        
        # Processing options group
        options_group = QGroupBox("Processing Options")
        options_layout = QFormLayout(options_group)
        
        self.deblend = QCheckBox()
        self.deblend.setChecked(self.params['deblend'])
        self.deblend.setToolTip("Deblend overlapping sources (can be slow for many sources)")
        options_layout.addRow("Deblend Sources:", self.deblend)
        
        self.connectivity = QSpinBox()
        self.connectivity.setRange(4, 8)
        self.connectivity.setValue(self.params['connectivity'])
        self.connectivity.setToolTip("Connectivity for source detection (4 or 8)")
        options_layout.addRow("Connectivity:", self.connectivity)
        
        layout.addWidget(options_group)
        
        # Background estimation group
        background_group = QGroupBox("Background Estimation")
        background_layout = QFormLayout(background_group)
        
        self.background_box_size = QSpinBox()
        self.background_box_size.setRange(10, 500)
        self.background_box_size.setValue(self.params['background_box_size'])
        self.background_box_size.setToolTip("Box size for background estimation")
        background_layout.addRow("Background Box Size:", self.background_box_size)
        
        self.background_filter_size = QSpinBox()
        self.background_filter_size.setRange(3, 21)
        self.background_filter_size.setSingleStep(2)  # Keep odd numbers
        self.background_filter_size.setValue(self.params['background_filter_size'])
        self.background_filter_size.setToolTip("Filter size for background estimation (must be odd)")
        background_layout.addRow("Background Filter Size:", self.background_filter_size)
        
        layout.addWidget(background_group)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | 
                                     QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def get_parameters(self):
        """Get the current parameter values."""
        return {
            'threshold_sigma': self.threshold_sigma.value(),
            'npixels': self.npixels.value(),
            'min_area': self.min_area.value(),
            'min_snr': self.min_snr.value(),
            'max_area': self.max_area.value(),
            'min_eccentricity': self.min_eccentricity.value(),
            'max_eccentricity': self.max_eccentricity.value(),
            'deblend': self.deblend.isChecked(),
            'connectivity': self.connectivity.value(),
            'background_box_size': self.background_box_size.value(),
            'background_filter_size': self.background_filter_size.value()
        }
    
    def accept(self):
        """Validate and accept the dialog."""
        # Ensure background filter size is odd
        if self.background_filter_size.value() % 2 == 0:
            self.background_filter_size.setValue(self.background_filter_size.value() + 1)
        
        # Ensure max area is greater than min area
        if self.max_area.value() <= self.min_area.value():
            self.max_area.setValue(self.min_area.value() + 10)
        
        # Ensure max eccentricity is greater than min eccentricity
        if self.max_eccentricity.value() <= self.min_eccentricity.value():
            self.max_eccentricity.setValue(self.min_eccentricity.value() + 0.1)
        
        super().accept() 