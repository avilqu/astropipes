"""
Background threads used by the Library: database loading and scanning, single-file
calibration and plate solving.
"""

import sys
import io
import signal

from PyQt6.QtCore import QThread, pyqtSignal
from colorama import init, Fore, Style

from astropipes.db import get_db_manager
from astropipes.processing.calibration import CalibrationManager
from astropipes.workflows.library import solve_and_update_library


class DatabaseLoaderThread(QThread):
    """Thread for loading database data to avoid blocking the GUI."""
    data_loaded = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
    
    def run(self):
        try:
            db_manager = get_db_manager(self.db_path)
            fits_files = db_manager.get_all_fits_files()
            self.data_loaded.emit(fits_files)
        except Exception as e:
            self.error_occurred.emit(str(e))


class DatabaseScannerThread(QThread):
    """Thread for scanning FITS files and calibration masters to avoid blocking the GUI."""
    scan_completed = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    output_received = pyqtSignal(str)  # New signal for real-time output

    def __init__(self, quiet=False):
        super().__init__()
        self.quiet = quiet

    def run(self):
        import io
        from contextlib import redirect_stdout
        try:
            from astropipes.db import scan_fits_library, scan_calibration_masters
            verbose = not self.quiet

            if self.quiet:
                fits_results = scan_fits_library(verbose=False)
                calib_results = scan_calibration_masters(verbose=False)
            else:
                class SignalStringIO(io.StringIO):
                    def __init__(self, signal, buffer_size=100):
                        super().__init__()
                        self.signal = signal
                        self.buffer = []
                        self.buffer_size = buffer_size
                    def write(self, text):
                        lines = text.splitlines(keepends=True)
                        for line in lines:
                            self.buffer.append(line)
                            if len(self.buffer) >= self.buffer_size:
                                self._emit_buffer()
                    def flush(self):
                        self._emit_buffer()
                        super().flush()
                    def close(self):
                        self._emit_buffer()
                        super().close()
                    def _emit_buffer(self):
                        if self.buffer:
                            self.signal.emit(''.join(self.buffer))
                            self.buffer.clear()
                sio = SignalStringIO(self.output_received, buffer_size=100)
                with redirect_stdout(sio):
                    fits_results = scan_fits_library(verbose=verbose)
                    print("\n--- Calibration Masters Scan ---\n")
                    calib_results = scan_calibration_masters(verbose=verbose)
                sio.flush()

            summary = {
                'files_imported': fits_results.get('files_imported', 0),
                'files_skipped': fits_results.get('files_skipped', 0),
                'total_files_found': fits_results.get('total_files_found', 0),
                'calib_imported': calib_results.get('files_imported', 0),
                'calib_skipped': calib_results.get('files_skipped', 0),
                'calib_total_found': calib_results.get('total_files_found', 0),
                'errors': (fits_results.get('errors', []) or []) + (calib_results.get('errors', []) or [])
            }
            self.scan_completed.emit(summary)
        except Exception as e:
            self.error_occurred.emit(str(e))


class CalibrationThread(QThread):
    """Thread for performing calibration operations."""
    
    output = pyqtSignal(str)  # Emit calibration output
    finished = pyqtSignal(dict)  # Emit calibration result
    
    def __init__(self, fits_file_path: str):
        super().__init__()
        self.fits_file_path = fits_file_path
        self._running = True
    
    def run(self):
        """Run the calibration process."""
        try:
            # Initialize colorama for colored output
            init()
            
            # Capture stdout to emit to GUI
            old_stdout = sys.stdout
            string_io = io.StringIO()
            sys.stdout = string_io
            
            # Initialize calibration manager
            calib_manager = CalibrationManager()
            
            # Perform calibration
            result = calib_manager.calibrate_file_simple(self.fits_file_path)
            
            # Restore stdout
            sys.stdout = old_stdout
            
            # Emit captured output
            output_text = string_io.getvalue()
            if output_text:
                self.output.emit(output_text)
            
            # Emit result
            self.finished.emit(result)
            
        except Exception as e:
            # Restore stdout in case of error
            sys.stdout = old_stdout
            error_msg = f"{Style.BRIGHT + Fore.RED}Error during calibration: {e}{Style.RESET_ALL}\n"
            self.output.emit(error_msg)
            self.finished.emit({'error': str(e)})
    
    def stop(self):
        """Stop the thread."""
        self._running = False


class PlatesolvingThread(QThread):
    output = pyqtSignal(str)
    finished = pyqtSignal(object)  # Emits PlatesolvingResult

    def __init__(self, fits_file_path):
        super().__init__()
        self.fits_file_path = fits_file_path
        self._process = None
        self._should_stop = False

    def set_process(self, process):
        self._process = process

    def stop(self):
        self._should_stop = True
        if self._process is not None:
            try:
                self.output.emit("\nCancelling platesolving...\n")
                self._process.send_signal(signal.SIGINT)
            except Exception as e:
                self.output.emit(f"\nError sending cancel signal: {e}\n")

    def run(self):
        def output_callback(line):
            self.output.emit(line)
        def process_callback(process):
            self.set_process(process)
        result = solve_and_update_library(self.fits_file_path, output_callback=output_callback, process_callback=process_callback)
        self.finished.emit(result)
