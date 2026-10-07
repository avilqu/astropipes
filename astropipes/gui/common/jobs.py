"""
Run a workflow function in a background QThread and report its console output and result.
"""

import sys
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from astropipes.core.log import CallbackStream


class JobThread(QThread):
    """
    Runs job(log, should_cancel) off the GUI thread.

    output(str): text passed to log() (and, with capture_stdout, anything printed).
    finished(dict): the job's result dict; {'success': False, 'error': ...} if it raised.
    stop(): makes should_cancel() return True; the job decides when to stop.

    capture_stdout: redirect sys.stdout to output while the job runs. This is process-wide,
    so use it only for jobs whose lower layers print progress that the console should show.
    """
    output = pyqtSignal(str)
    finished = pyqtSignal(dict)

    def __init__(self, job, capture_stdout=False, parent=None):
        super().__init__(parent)
        self._job = job
        self._capture_stdout = capture_stdout
        self._cancel = False

    def stop(self):
        self._cancel = True

    def is_cancelled(self):
        return self._cancel

    def run(self):
        old_stdout = sys.stdout
        stream = CallbackStream(self.output.emit, line_buffered=True) if self._capture_stdout else None
        if stream:
            sys.stdout = stream
        try:
            result = self._job(self.output.emit, self.is_cancelled)
        except Exception as e:
            traceback.print_exc(file=sys.__stderr__)
            self.output.emit(f"\nError: {e}\n")
            result = {'success': False, 'error': str(e)}
        finally:
            if stream:
                stream.flush()
                sys.stdout = old_stdout
        self.finished.emit(result if isinstance(result, dict) else {'success': True, 'result': result})
