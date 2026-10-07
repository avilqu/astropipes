""" QApplication setup shared by the library and viewer GUIs. """

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication


# share/icons/ in the repository (the package is installed in editable mode)
ICON_PATH = Path(__file__).resolve().parents[3] / 'share' / 'icons' / 'astropipes.png'


def create_application(desktop_file_name: str) -> QApplication:
    """Create the QApplication with the astropipes icon.

    desktop_file_name matches the installed .desktop file (without extension) so
    the window manager associates windows with the launcher entry and its icon.
    """
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setDesktopFileName(desktop_file_name)
    return app
