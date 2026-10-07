#!/usr/bin/env python3
"""
Console Output Window
A reusable widget for displaying real-time console output in a dedicated window.
"""

import re
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor


class ConsoleOutputWindow(QWidget):
    cancel_requested = pyqtSignal()
    """A window for displaying real-time console output."""
    
    def __init__(self, title="Console Output", parent=None):
        super().__init__(parent)
        self.title = title
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle(self.title)
        self.setGeometry(100, 100, 640, 480)
        self.setWindowFlags(Qt.WindowType.Window)  # Make it a proper window with title bar
        
        # Create layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Create text area for console output
        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setFont(QFont("Monospace", 8))
        self.text_area.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.text_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self.text_area)
        
        # Create button layout
        button_layout = QHBoxLayout()
        
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.on_cancel)
        button_layout.addWidget(self.cancel_button)
        
        # Close button
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close_window)
        button_layout.addWidget(self.close_button)
        
        button_layout.addStretch()  # Push buttons to the left
        layout.addLayout(button_layout)
    
    def ansi_to_html(self, text):
        """Convert ANSI escape codes in text to HTML for QTextEdit."""
        ansi_escape = re.compile(r'\x1b\[(?P<code>[0-9;]+)m')
        # Mapping of ANSI color codes to HTML color names
        ansi_colors = {
            '30': 'black', '31': 'red', '32': 'green', '33': 'yellow',
            '34': '#7faaff', '35': 'magenta', '36': 'cyan', '37': 'white',
            '90': 'gray', '91': 'lightcoral', '92': 'lightgreen', '93': 'lightyellow',
            '94': 'lightblue', '95': 'violet', '96': 'lightcyan', '97': 'white',
        }
        # Stack for nested styles
        style_stack = []
        html = ''
        last_end = 0
        for match in ansi_escape.finditer(text):
            start, end = match.span()
            code = match.group('code')
            # Append text before this escape
            html += self.escape_html(text[last_end:start])
            codes = code.split(';')
            # Reset
            if '0' in codes:
                while style_stack:
                    html += '</span>'
                    style_stack.pop()
                codes = [c for c in codes if c != '0']
            style = ''
            for c in codes:
                if c == '1':
                    style += 'font-weight: bold;'
                elif c in ansi_colors:
                    style += f'color: {ansi_colors[c]};'
            if style:
                html += f'<span style="{style}">'  # Open new style
                style_stack.append('</span>')
            last_end = end
        html += self.escape_html(text[last_end:])
        while style_stack:
            html += style_stack.pop()
        # Replace newlines with <br> for HTML display
        html = html.replace('\n', '<br>')
        return html

    def escape_html(self, text):
        """Escape HTML special characters."""
        return (
            text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;')
        )

    def append_text(self, text):
        """Append text to the console output, parsing ANSI codes to HTML."""
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_area.setTextCursor(cursor)
        html = self.ansi_to_html(text)
        self.text_area.insertHtml(html)
        # Auto-scroll to bottom
        self.text_area.ensureCursorVisible()
    
    def clear_output(self):
        """Clear all console output."""
        self.text_area.clear()
    
    def show_and_raise(self):
        """Show the window and bring it to front."""
        self.show()
        self.raise_()
        self.activateWindow()
    
    def close_window(self):
        """Close the window properly."""
        self.close()
    
    def closeEvent(self, event):
        """Handle window close event."""
        # Allow normal closing behavior
        event.accept() 

    def on_cancel(self):
        self.cancel_requested.emit() 