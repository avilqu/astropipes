"""
Launch the FITS viewer as a separate process.
"""

import subprocess
import sys

from PyQt6.QtWidgets import QMessageBox


def launch_viewer(fits_paths):
    """
    Launch the FITS viewer with the current Python interpreter.

    Args:
        fits_paths: Single path string or list of path strings
    """
    if isinstance(fits_paths, str):
        fits_paths = [fits_paths]

    try:
        subprocess.Popen([sys.executable, '-m', 'astropipes.gui.viewer', *fits_paths])
    except Exception as e:
        QMessageBox.warning(None, "Error", f"Failed to launch FITS viewer: {e}")
