from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QTextEdit, QPushButton, QLabel, QLineEdit, 
                             QFormLayout, QDialog, QMessageBox, QComboBox, QCheckBox)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt
from datetime import datetime
from astropipes.astrometry.mpc import generate_mpc_submission


class MPCReportWindow(QMainWindow):
    """Window for displaying measurements in MPC submission format."""
    
    def __init__(self, measurements, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MPC Report")
        
        # Center the window on screen
        screen = self.screen()
        if screen:
            screen_geometry = screen.geometry()
            x = (screen_geometry.width() - 800) // 2
            y = (screen_geometry.height() - 600) // 2
            self.setGeometry(x, y, 800, 600)
        else:
            self.setGeometry(400, 300, 800, 600)
        
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        
        self.measurements = measurements
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()
        central_widget.setLayout(layout)
        
        # Add configuration section
        self._create_config_section(layout)
        
        # Add MPC format text area
        self._create_mpc_text_area(layout)
        
        # Add buttons
        self._create_buttons(layout)
        
        # Generate initial MPC report if we have measurements
        if self.measurements and len(self.measurements) >= 3:
            self._generate_mpc_report()
    
    def _create_config_section(self, layout):
        """Create configuration section for MPC report."""
        config_widget = QWidget()
        config_layout = QFormLayout()
        config_widget.setLayout(config_layout)
        
        # Object designation
        self.object_designation = QLineEdit()
        self.object_designation.setPlaceholderText("e.g., C34UMY1 or 2023 ABC123")
        self.object_designation.textChanged.connect(self._generate_mpc_report)
        config_layout.addRow("Object Designation:", self.object_designation)
        
        # Discovery asterisk
        self.discovery_asterisk = QCheckBox()
        self.discovery_asterisk.stateChanged.connect(self._generate_mpc_report)
        config_layout.addRow("New Discovery:", self.discovery_asterisk)
        
        # Note 1 (program code)
        self.note1 = QLineEdit()
        self.note1.setPlaceholderText("Program code (optional)")
        self.note1.textChanged.connect(self._generate_mpc_report)
        config_layout.addRow("Note 1 (Program Code):", self.note1)
        
        # Note 2 (observation method)
        self.note2 = QComboBox()
        self.note2.addItems(["C", "B", "P", "e", "T", "M", "V", "R", "S", "E", "O", "H", "N", "n"])
        self.note2.setCurrentText("C")  # Default to CCD
        self.note2.currentTextChanged.connect(self._generate_mpc_report)
        config_layout.addRow("Note 2 (Method):", self.note2)
        
        # Observatory code
        self.observatory_code = QLineEdit()
        self.observatory_code.setPlaceholderText("e.g., R56")
        self.observatory_code.textChanged.connect(self._generate_mpc_report)
        config_layout.addRow("Observatory Code:", self.observatory_code)
        
        layout.addWidget(config_widget)
    
    def _create_mpc_text_area(self, layout):
        """Create the MPC format text area."""
        # Label
        label = QLabel("MPC Submission Format:")
        label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(label)
        
        # Text area
        self.mpc_text = QTextEdit()
        self.mpc_text.setFont(QFont("Courier New", 10))
        self.mpc_text.setReadOnly(True)
        layout.addWidget(self.mpc_text)
    
    def _create_buttons(self, layout):
        """Create action buttons."""
        button_layout = QHBoxLayout()
        
        # Copy to clipboard button
        self.copy_button = QPushButton("Copy to Clipboard")
        self.copy_button.clicked.connect(self._copy_to_clipboard)
        button_layout.addWidget(self.copy_button)
        
        # Save to file button
        self.save_button = QPushButton("Save to File")
        self.save_button.clicked.connect(self._save_to_file)
        button_layout.addWidget(self.save_button)
        
        # Close button
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)
        
        layout.addLayout(button_layout)
    
    def _generate_mpc_report(self):
        """Generate the MPC format report."""
        if not self.measurements or len(self.measurements) < 3:
            self.mpc_text.setPlainText("Error: Need at least 3 measurements for MPC report.")
            return
        
        # Get configuration values
        designation = self.object_designation.text().strip()
        is_discovery = self.discovery_asterisk.isChecked()
        note1 = self.note1.text().strip()
        note2 = self.note2.currentText()
        observatory_code = self.observatory_code.text().strip()
        
        if not designation:
            self.mpc_text.setPlainText("Error: Object designation is required.")
            return
        
        if not observatory_code:
            self.mpc_text.setPlainText("Error: Observatory code is required.")
            return
        
        try:
            # Use the new MPC generation function
            mpc_text = generate_mpc_submission(
                observations=self.measurements[:3],  # Only use first 3 measurements
                object_designation=designation,
                observatory_code=observatory_code,
                is_discovery=is_discovery,
                note1=note1,
                note2=note2,
                magnitude=None,  # No magnitude for now
                magnitude_band="V"
            )
            
            # Display only the MPC submission lines
            self.mpc_text.setPlainText(mpc_text)
            
        except Exception as e:
            self.mpc_text.setPlainText(f"Error generating MPC report: {str(e)}")
    

    
    def _copy_to_clipboard(self):
        """Copy the MPC report to clipboard."""
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        
        # Copy the MPC text directly (it's already just the MPC lines)
        text = self.mpc_text.toPlainText()
        clipboard.setText(text)
        QMessageBox.information(self, "Copied", "MPC format lines copied to clipboard.")
    
    def _save_to_file(self):
        """Save the MPC report to a file."""
        from PyQt6.QtWidgets import QFileDialog
        
        # Get the MPC text directly (it's already just the MPC lines)
        text = self.mpc_text.toPlainText()
        
        if not text.strip():
            QMessageBox.warning(self, "Error", "No MPC format lines found to save.")
            return
        
        # Get filename from user
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save MPC Report", 
            f"mpc_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(text)
                QMessageBox.information(self, "Saved", f"MPC report saved to {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save file: {str(e)}")


class MPCReportDialog(QDialog):
    """Dialog for configuring and generating MPC report."""
    
    def __init__(self, measurements, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MPC Report Configuration")
        self.setModal(True)
        self.setFixedSize(500, 400)
        
        self.measurements = measurements
        
        layout = QVBoxLayout(self)
        
        # Instructions
        instruction_label = QLabel("Configure MPC report settings:")
        instruction_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(instruction_label)
        
        # Configuration form
        form_layout = QFormLayout()
        
        # Object designation
        self.object_designation = QLineEdit()
        self.object_designation.setPlaceholderText("e.g., C34UMY1 or 2023 ABC123")
        form_layout.addRow("Object Designation:", self.object_designation)
        
        # Discovery asterisk
        self.discovery_asterisk = QComboBox()
        self.discovery_asterisk.addItems(["No", "Yes"])
        form_layout.addRow("Discovery Observation:", self.discovery_asterisk)
        
        # Note 1 (program code)
        self.note1 = QLineEdit()
        self.note1.setPlaceholderText("Program code (optional)")
        form_layout.addRow("Note 1 (Program Code):", self.note1)
        
        # Note 2 (observation method)
        self.note2 = QComboBox()
        self.note2.addItems(["C", "B", "P", "e", "T", "M", "V", "R", "S", "E", "O", "H", "N", "n"])
        self.note2.setCurrentText("C")  # Default to CCD
        form_layout.addRow("Note 2 (Method):", self.note2)
        
        # Magnitude and band
        self.magnitude = QLineEdit()
        self.magnitude.setPlaceholderText("e.g., 18.5")
        form_layout.addRow("Magnitude:", self.magnitude)
        
        self.magnitude_band = QComboBox()
        self.magnitude_band.addItems(["V", "R", "B", "I", "J", "W", "U", "C", "L", "H", "K", "Y", "G", "g", "r", "i", "w", "y", "z", "o", "c", "v", "u"])
        self.magnitude_band.setCurrentText("V")  # Default to V band
        form_layout.addRow("Magnitude Band:", self.magnitude_band)
        
        # Observatory code
        self.observatory_code = QLineEdit()
        self.observatory_code.setPlaceholderText("e.g., 568")
        form_layout.addRow("Observatory Code:", self.observatory_code)
        
        layout.addLayout(form_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.generate_button = QPushButton("Generate Report")
        self.generate_button.clicked.connect(self._generate_report)
        button_layout.addWidget(self.generate_button)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
    
    def _generate_report(self):
        """Generate and show the MPC report window."""
        # Validate required fields
        if not self.object_designation.text().strip():
            QMessageBox.warning(self, "Error", "Object designation is required.")
            return
        
        if not self.observatory_code.text().strip():
            QMessageBox.warning(self, "Error", "Observatory code is required.")
            return
        
        # Store configuration for the caller to use
        self.config = {
            'object_designation': self.object_designation.text().strip(),
            'discovery_asterisk': self.discovery_asterisk.currentText(),
            'note1': self.note1.text().strip(),
            'note2': self.note2.currentText(),
            'magnitude': self.magnitude.text().strip(),
            'magnitude_band': self.magnitude_band.currentText(),
            'observatory_code': self.observatory_code.text().strip()
        }
        
        # Close the dialog
        self.accept() 