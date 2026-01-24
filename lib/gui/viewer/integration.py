import os
import time
import sys
import traceback
from PyQt6.QtCore import QThread, QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QDialog
from lib.gui.viewer.orbital_elements import OrbitComputationDialog, OrbitComputationWorker, OrbitDataWindow
from lib.gui.common.console_window import ConsoleOutputWindow
from config import MOTION_TRACKING_SIGMA_CLIP, MOTION_TRACKING_METHOD, MOTION_TRACKING_CREATE_BOTH_STACKS, PROCESSED_PATH


class MotionTrackingStackWorker(QObject):
    """Worker thread for motion tracking integration."""
    console_output = pyqtSignal(str)  # console output text
    finished = pyqtSignal(bool, str, list)  # success, message, output_files
    
    def __init__(self, files, object_name, output_path, console_window=None, ephemerides_data=None):
        super().__init__()
        self.files = files
        self.object_name = object_name
        self.output_path = output_path
        self.console_window = console_window
        self.ephemerides_data = ephemerides_data
    
    def run(self):
        """Run the motion tracking integration."""
        try:
            from lib.gui.common.console_window import RealTimeStringIO
            from lib.fits.integration import integrate_with_motion_tracking, MotionTrackingIntegrationError
            
            # Redirect stdout/stderr to console output
            rtio = RealTimeStringIO(self.console_output.emit)
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = rtio
            
            try:
                self.console_output.emit(f"\033[1;34mStarting motion tracking integration for {self.object_name}\033[0m\n")
                self.console_output.emit(f"\033[1;34mProcessing {len(self.files)} files\033[0m\n")
                
                if MOTION_TRACKING_CREATE_BOTH_STACKS:
                    self.console_output.emit(f"\033[1;34mConfiguration: Creating both median and average stacks\033[0m\n")
                else:
                    self.console_output.emit(f"\033[1;34mConfiguration: Creating single {MOTION_TRACKING_METHOD} stack\033[0m\n")
                
                output_files = []
                
                # Generate output filenames
                output_dir = os.path.dirname(self.output_path)
                base_name = os.path.splitext(os.path.basename(self.output_path))[0]
                
                if MOTION_TRACKING_CREATE_BOTH_STACKS:
                    self.console_output.emit(f"\033[1;34mWill create both median and average stacks\033[0m\n\n")
                    
                    # Create median stack
                    median_output_path = os.path.join(output_dir, f"{base_name}_median.fits")
                    self.console_output.emit(f"\033[1;33mCreating median stack...\033[0m\n")
                    
                    median_result = integrate_with_motion_tracking(
                        files=self.files,
                        object_name=self.object_name,
                        method='median',
                        sigma_clip=MOTION_TRACKING_SIGMA_CLIP,
                        output_path=median_output_path,
                        ephemerides_data=self.ephemerides_data
                    )
                    output_files.append(median_output_path)
                    
                    self.console_output.emit(f"\033[1;32m✓ Median stack completed\033[0m\n")
                    
                    # Create average stack
                    average_output_path = os.path.join(output_dir, f"{base_name}_average.fits")
                    self.console_output.emit(f"\033[1;33mCreating average stack...\033[0m\n")
                    
                    average_result = integrate_with_motion_tracking(
                        files=self.files,
                        object_name=self.object_name,
                        method='average',
                        sigma_clip=MOTION_TRACKING_SIGMA_CLIP,
                        output_path=average_output_path,
                        ephemerides_data=self.ephemerides_data
                    )
                    output_files.append(average_output_path)
                    
                    self.console_output.emit(f"\033[1;32m✓ Average stack completed\033[0m\n")
                    
                    # Success message for both stacks
                    message = f"Successfully created motion tracked stacks:\n"
                    message += f"Object: {self.object_name}\n"
                    message += f"Files processed: {len(self.files)}\n"
                    message += f"Median stack: {median_output_path}\n"
                    message += f"Average stack: {average_output_path}\n"
                    message += f"Median image shape: {median_result.data.shape}\n"
                    message += f"Average image shape: {average_result.data.shape}\n"
                    message += f"Median data range: {median_result.data.min():.2f} to {median_result.data.max():.2f}\n"
                    message += f"Average data range: {average_result.data.min():.2f} to {average_result.data.max():.2f}"
                else:
                    self.console_output.emit(f"\033[1;34mWill create {MOTION_TRACKING_METHOD} stack\033[0m\n\n")
                    
                    # Create single stack with configured method
                    result = integrate_with_motion_tracking(
                        files=self.files,
                        object_name=self.object_name,
                        method=MOTION_TRACKING_METHOD,
                        ephemerides_data=self.ephemerides_data,
                        sigma_clip=MOTION_TRACKING_SIGMA_CLIP,
                        output_path=self.output_path
                    )
                    output_files.append(self.output_path)
                    
                    # Success message for single stack
                    message = f"Successfully created motion tracked stack:\n"
                    message += f"Object: {self.object_name}\n"
                    message += f"Files processed: {len(self.files)}\n"
                    message += f"Method: {MOTION_TRACKING_METHOD}\n"
                    message += f"Output: {self.output_path}\n"
                    message += f"Image shape: {result.data.shape}\n"
                    message += f"Data range: {result.data.min():.2f} to {result.data.max():.2f}"
                
                self.finished.emit(True, message, output_files)
                
            finally:
                # Restore stdout/stderr
                sys.stdout = old_stdout
                sys.stderr = old_stderr
            
        except MotionTrackingIntegrationError as e:
            self.finished.emit(False, f"Motion tracking integration error: {e}", [])
        except Exception as e:
            import traceback
            error_msg = f"Unexpected error during motion tracking integration:\n{str(e)}\n\n{traceback.format_exc()}"
            self.finished.emit(False, error_msg, [])


class IntegrationMixin:
    """Mixin class providing integration and stacking functionality for the FITS viewer."""
    
    def open_orbit_computation_dialog(self):
        """Open dialog to compute orbit data for a specific object."""
        if not self.loaded_files:
            QMessageBox.warning(self, "No Files", "No FITS files loaded. Please load some files first.")
            return
        
        # Extract target name from current FITS file
        target_name = None
        if self.current_file_index >= 0 and self.current_file_index < len(self.loaded_files):
            current_file_path = self.loaded_files[self.current_file_index]
            
            # Try to get target name from preloaded FITS data first
            if current_file_path in self._preloaded_fits:
                _, header, _ = self._preloaded_fits[current_file_path]
                if header:
                    target_name = header.get('OBJECT', '').strip()
            
            # If not found in preloaded data, try to read from file directly
            if not target_name:
                try:
                    from astropy.io import fits
                    with fits.open(current_file_path) as hdul:
                        header = hdul[0].header
                        target_name = header.get('OBJECT', '').strip()
                except Exception:
                    pass
        
        dialog = OrbitComputationDialog(self, target_name)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            object_name = dialog.get_object_name()
            if not object_name:
                QMessageBox.warning(self, "No Object", "Please enter an object designation.")
                return
            
            # Console output window for orbit computation
            console_window = ConsoleOutputWindow(f"Orbit Computation: {object_name}", self)
            console_window.show_and_raise()
            
            # Start worker thread
            self._orbit_thread = QThread()
            self._orbit_worker = OrbitComputationWorker(object_name, self.loaded_files, console_window)
            self._orbit_worker.moveToThread(self._orbit_thread)
            self._orbit_worker.console_output.connect(console_window.append_text)
            self._orbit_thread.started.connect(self._orbit_worker.run)
            
            def on_finished(predicted_positions, pseudo_mpec_text):
                console_window.append_text("\nComputation finished.\n")
                self._orbit_thread.quit()
                self._orbit_thread.wait()
                
                # Show orbit data window
                dlg = OrbitDataWindow(object_name, predicted_positions, pseudo_mpec_text, self)
                dlg.row_selected.connect(self.on_ephemeris_row_selected)
                self._ephemeris_predicted_positions = predicted_positions
                self._ephemeris_object_name = object_name
                dlg.show()
                # Store reference to prevent garbage collection
                self._orbit_window = dlg
                # Optionally, select the current file's row by default
                if self.current_file_index >= 0 and self.current_file_index < len(predicted_positions):
                    dlg.positions_table.selectRow(self.current_file_index)
                    self.on_ephemeris_row_selected(self.current_file_index, predicted_positions[self.current_file_index])
            
            def on_error(msg):
                console_window.append_text(f"\nError: {msg}\n")
                self._orbit_thread.quit()
                self._orbit_thread.wait()
                QMessageBox.critical(self, "Orbit Computation Error", f"Error computing orbit data: {msg}")
            
            self._orbit_worker.finished.connect(on_finished)
            self._orbit_worker.error.connect(on_error)
            self._orbit_thread.start()

    def stack_align_wcs(self):
        """Stack alignment using WCS coordinates (placeholder for future implementation)."""
        # TODO: Implement stack alignment on WCS
        pass

    def stack_align_ephemeris(self):
        """Perform motion tracking integration using ephemeris data."""
        if not hasattr(self, '_ephemeris_predicted_positions') or not self._ephemeris_predicted_positions:
            QMessageBox.warning(self, "No Ephemeris Data", 
                              "No ephemeris data available. Please compute orbit data first using the Solar System Objects menu.")
            return
        
        if not self.loaded_files:
            QMessageBox.warning(self, "No Files", "No FITS files are currently loaded in the viewer.")
            return
        
        if len(self.loaded_files) < 2:
            QMessageBox.warning(self, "Insufficient Files", "At least 2 FITS files are required for stacking.")
            return
        
        # Create output directory if it doesn't exist
        output_dir = os.path.join(PROCESSED_PATH, "stacked")
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate output filename
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_object_name = self._ephemeris_object_name.replace(' ', '_').replace('/', '_').replace('\\', '_')
        output_file = os.path.join(output_dir, f"motion_tracked_{safe_object_name}_{timestamp}.fits")
        
        # Create console window for output
        console_window = ConsoleOutputWindow("Motion Tracking Integration", self)
        console_window.show_and_raise()
        
        # Start stacking in background thread
        self._stack_thread = QThread()
        self._stack_worker = MotionTrackingStackWorker(
            self.loaded_files, 
            self._ephemeris_object_name, 
            output_file,
            console_window,
            self._ephemeris_predicted_positions
        )
        self._stack_worker.moveToThread(self._stack_thread)
        self._stack_thread.started.connect(self._stack_worker.run)
        
        def on_console_output(text):
            console_window.append_text(text)
        
        def on_finished(success, message, output_files):
            if success:
                console_window.append_text(f"\n\033[1;32mMotion tracking integration completed successfully!\033[0m\n\n{message}\n")
                # Add the results to the loaded files in the viewer
                self.loaded_files.extend(output_files)
                # Load the files in the viewer
                for file_path in output_files:
                    self.open_and_add_file(file_path)
                # Update navigation buttons and file count
                self.update_navigation_buttons()
                self.update_image_count_label()
            else:
                console_window.append_text(f"\n\033[1;31mMotion tracking integration failed:\033[0m\n\n{message}\n")
            
            self._stack_thread.quit()
            self._stack_thread.wait()
        
        def on_cancel():
            console_window.append_text("\n\033[1;31mCancelling motion tracking integration...\033[0m\n")
            self._stack_thread.quit()
            self._stack_thread.wait()
            console_window.close()
        
        self._stack_worker.console_output.connect(on_console_output)
        self._stack_worker.finished.connect(on_finished)
        console_window.cancel_requested.connect(on_cancel)
        self._stack_thread.start() 