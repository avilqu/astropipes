"""Dialog to edit the comment of an observing run."""

from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout,
)


class RunCommentDialog(QDialog):
    """Dialog for editing run comments."""
    
    def __init__(self, parent=None, initial_comment=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Run Comment")
        self.setModal(True)
        self.setFixedSize(500, 200)
        
        layout = QVBoxLayout(self)
        
        # Label
        label = QLabel("Comment:")
        layout.addWidget(label)
        
        # Text edit for comment
        self.comment_edit = QTextEdit()
        self.comment_edit.setPlaceholderText("Enter a comment for this run...")
        if initial_comment:
            self.comment_edit.setPlainText(initial_comment)
        layout.addWidget(self.comment_edit)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.accept)
        button_layout.addWidget(self.save_button)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        # Set focus to text edit
        self.comment_edit.setFocus()
    
    def get_comment(self):
        """Get the comment text."""
        text = self.comment_edit.toPlainText().strip()
        return text if text else None
