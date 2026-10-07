from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit
from PyQt6.QtGui import QFont

class HeaderViewer(QDialog):
    def __init__(self, header_dict, file_path=None, parent=None):
        super().__init__(parent)
        self.setModal(False)  # Make the dialog non-modal
        title = "FITS Header"
        if file_path:
            title += f" - {file_path}"
        self.setWindowTitle(title)
        self.setGeometry(200, 200, 700, 600)
        layout = QVBoxLayout(self)
        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setFont(QFont("Courier New", 10))
        self.text_area.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.text_area)
        self.setLayout(layout)
        self.display_header(header_dict)

    def display_header(self, header_dict):
        header_html = """
        <table style=\"font-family: 'Courier New', monospace; font-size: 10pt; border-collapse: collapse; width: 100%;\">
        <tr style=\"background-color: #333333;\">
            <th style=\"color: #0066CC; text-align: left; padding: 2px 5px; border-bottom: 1px solid #555555;\">Keyword</th>
            <th style=\"color: #FFFFFF; text-align: left; padding: 2px 5px; border-bottom: 1px solid #555555;\">Value</th>
            <th style=\"color: #AAAAAA; text-align: left; padding: 2px 5px; border-bottom: 1px solid #555555;\">Comment</th>
        </tr>
        """
        for i, (key, value) in enumerate(header_dict.items()):
            comment = ""
            if (isinstance(value, tuple) or isinstance(value, list)) and len(value) == 2:
                value, comment = value
            value_str = str(value) if value is not None else ""
            comment_str = comment if comment else ""
            row_color = "#222222" if i % 2 == 0 else "#2A2A2A"
            header_html += f"""
            <tr style=\"background-color: {row_color};\">
                <td style=\"color: #0066CC; font-weight: bold; padding: 2px 5px; border-right: 1px solid #555555; word-break: break-all;\">{key}</td>
                <td style=\"color: #FFFFFF; padding: 2px 5px; border-right: 1px solid #555555; word-break: break-all;\">{value_str}</td>
                <td style=\"color: #AAAAAA; padding: 2px 5px; word-break: break-all;\">{comment_str}</td>
            </tr>
            """
        header_html += "</table>"
        self.text_area.setHtml(header_html) 