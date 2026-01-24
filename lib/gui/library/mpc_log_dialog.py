#!/usr/bin/env python3
"""
Dialog for adding observations to the Minor Planet Center (MPC) log.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QComboBox, QPushButton, QFormLayout, QTextEdit
)
from PyQt6.QtCore import Qt


class MPCLogDialog(QDialog):
    """Dialog for entering MPC log observation data."""
    
    def __init__(self, parent=None, target_name=None, initial_comment=None):
        super().__init__(parent)
        self.setWindowTitle("Add to MPC Log")
        self.setModal(True)
        self.setFixedSize(400, 350)
        
        layout = QVBoxLayout(self)
        
        # Form layout for input fields
        form_layout = QFormLayout()
        
        # Target speed (motion in "/mn)
        self.motion_edit = QLineEdit()
        self.motion_edit.setPlaceholderText("e.g., 15.5")
        form_layout.addRow("Motion (\"/mn):", self.motion_edit)
        
        # Magnitude
        self.magnitude_edit = QLineEdit()
        self.magnitude_edit.setPlaceholderText("e.g., 18.5")
        form_layout.addRow("Magnitude:", self.magnitude_edit)
        
        # Status (Found/Not Found)
        self.status_combo = QComboBox()
        self.status_combo.addItems(["Found", "Not Found"])
        form_layout.addRow("Status:", self.status_combo)
        
        layout.addLayout(form_layout)
        
        # Comment field
        comment_label = QLabel("Comment:")
        layout.addWidget(comment_label)
        self.comment_edit = QTextEdit()
        self.comment_edit.setPlaceholderText("Enter a comment for this run (optional)...")
        self.comment_edit.setMaximumHeight(80)
        if initial_comment:
            self.comment_edit.setPlainText(initial_comment)
        layout.addWidget(self.comment_edit)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.accept)
        self.save_button.setDefault(True)
        button_layout.addWidget(self.save_button)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        # Set focus to motion field
        self.motion_edit.setFocus()
    
    def accept(self):
        """Override accept to validate before closing."""
        valid, error_msg = self.validate()
        if not valid:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Invalid Input", error_msg)
            return
        super().accept()
    
    def get_motion(self):
        """Get the motion value as float, or None if invalid."""
        try:
            text = self.motion_edit.text().strip()
            if not text:
                return None
            return float(text)
        except ValueError:
            return None
    
    def get_magnitude(self):
        """Get the magnitude value as float, or None if invalid."""
        try:
            text = self.magnitude_edit.text().strip()
            if not text:
                return None
            return float(text)
        except ValueError:
            return None
    
    def get_status(self):
        """Get the status string."""
        return self.status_combo.currentText()
    
    def get_comment(self):
        """Get the comment text."""
        text = self.comment_edit.toPlainText().strip()
        return text if text else None
    
    def validate(self):
        """Validate the input fields."""
        motion = self.get_motion()
        magnitude = self.get_magnitude()
        
        if motion is None:
            return False, "Motion is required and must be a valid number"
        if magnitude is None:
            return False, "Magnitude is required and must be a valid number"
        
        return True, None
