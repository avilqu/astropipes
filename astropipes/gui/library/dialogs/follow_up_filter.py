"""Multi-select dialog for follow-up session stack filters."""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QDialogButtonBox,
)
from PyQt6.QtCore import Qt


class FollowUpFilterDialog(QDialog):
    def __init__(self, parent, target_name: str, filter_names: list):
        super().__init__(parent)
        self.setWindowTitle(f"Follow-up filters — {target_name}")
        self._selected = []
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Select one or more filters for session stack generation "
                "(Actions → Generate session stacks):"
            )
        )
        self.list_widget = QListWidget()
        for fn in filter_names:
            item = QListWidgetItem(fn)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_filters(self) -> list:
        out = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.text())
        return out
