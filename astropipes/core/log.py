''' Console output helpers for long-running jobs: file-like objects that forward printed output
    to a callback (e.g. a Qt signal's emit), and section banners.

    Jobs log through a `log(text)` callable; text should end with a newline.
'''

import io
import logging
import os
import shutil
import threading
import warnings

from colorama import Fore, Style


class CallbackStream(io.StringIO):
    """StringIO that also forwards written text to output_callback.

    line_buffered=False: forward every write immediately.
    line_buffered=True: forward complete non-empty lines, and long partial lines (> 200 chars),
                        so each callback receives whole lines; flush() forwards the remainder.
    """
    def __init__(self, output_callback, line_buffered=False):
        super().__init__()
        self.output_callback = output_callback
        self.line_buffered = line_buffered
        self._pending = ""
        self.lock = threading.Lock()

    def write(self, text):
        with self.lock:
            super().write(text)
            if not text:
                return len(text)
            if not self.line_buffered:
                self.output_callback(text)
                return len(text)
            self._pending += text
            while '\n' in self._pending:
                line, self._pending = self._pending.split('\n', 1)
                if line:
                    self.output_callback(line + '\n')
            if len(self._pending) > 200:
                self.output_callback(self._pending)
                self._pending = ""
            return len(text)

    def flush(self):
        with self.lock:
            super().flush()
            if self._pending:
                self.output_callback(self._pending)
                self._pending = ""

    def isatty(self):
        return False


def _terminal_columns():
    """Approximate console width for rule lines (embedded GUI consoles often report 80)."""
    try:
        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    except Exception:
        cols = 80
    return max(40, min(int(cols), 120))


def log_banner(log, title: str):
    """
    Section header using '=' rules sized to the terminal width.
    Each line ends with a newline so QTextEdit-style consoles don't join lines sideways.
    """
    # Keep a small margin so banners do not hit the console edge.
    w = max(20, _terminal_columns() - 8)
    sep = "=" * w
    cy = Style.BRIGHT + Fore.CYAN
    rs = Style.RESET_ALL
    log(f"\n{cy}{sep}{rs}\n")
    log(f"{cy}{title}{rs}\n")
    log(f"{cy}{sep}{rs}\n")


def configure_logging():
    """
    Process-wide logging and warnings setup; each entry point (CLI, Library, viewer) calls it once.

    Logging stays disabled, as the app has always run, unless the ASTROPIPES_DEBUG environment
    variable is set: then astropipes' debug messages are written to stderr.
    """
    # Astropy emits many harmless UserWarnings (FITS fixes, WCS convergence) while loading images
    warnings.filterwarnings('ignore', category=UserWarning)
    logging.basicConfig(level=logging.INFO)
    if os.environ.get('ASTROPIPES_DEBUG'):
        logging.disable(logging.NOTSET)
        logging.getLogger('astropipes').setLevel(logging.DEBUG)
    else:
        logging.disable(logging.CRITICAL)
