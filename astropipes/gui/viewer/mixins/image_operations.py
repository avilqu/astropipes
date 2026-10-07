import os

from PyQt6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QCheckBox

# Import configuration
from astropipes.config import settings
from astropipes.core.paths import work_dir
from astropipes.gui.common.jobs import JobThread


class AlignmentMethodDialog(QDialog):
    """Dialog for selecting alignment method."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Alignment Method")
        self.setModal(True)
        self.setFixedSize(400, 200)
        
        # Get available methods
        from astropipes.processing.alignment import get_alignment_methods
        self.available_methods = get_alignment_methods()
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Description
        desc_label = QLabel("Choose the alignment method to use:")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        # Method selection
        method_layout = QHBoxLayout()
        method_layout.addWidget(QLabel("Method:"))
        
        self.method_combo = QComboBox()
        for method in self.available_methods:
            if method == "astroalign":
                self.method_combo.addItem("Astroalign (Fast - Asterism-based)", method)
            elif method == "wcs_reprojection":
                self.method_combo.addItem("WCS Reprojection (Slow - Precise)", method)
            else:
                self.method_combo.addItem(method, method)
        
        # Set default selection
        default_index = self.method_combo.findData(settings.DEFAULT_ALIGNMENT_METHOD)
        if default_index >= 0:
            self.method_combo.setCurrentIndex(default_index)
        else:
            # Set to first available method as fallback
            if self.method_combo.count() > 0:
                self.method_combo.setCurrentIndex(0)
        
        method_layout.addWidget(self.method_combo)
        layout.addLayout(method_layout)
        
        # Remember choice checkbox
        self.remember_checkbox = QCheckBox("Remember this choice")
        self.remember_checkbox.setChecked(False)
        layout.addWidget(self.remember_checkbox)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def get_selected_method(self):
        """Get the selected alignment method."""
        method = self.method_combo.currentData()
        
        # Safety check - if method is None or invalid, use default
        if method is None or method not in self.available_methods:
            method = settings.DEFAULT_ALIGNMENT_METHOD
        
        return method
    
    def should_remember_choice(self):
        """Check if the user wants to remember this choice."""
        return self.remember_checkbox.isChecked()


class ImageOperationsMixin:
    """Mixin class providing image calibration, platesolving, and alignment functionality."""
    
    def cleanup_temp_files(self):
        """Clean up temporary aligned files."""
        import shutil
        if hasattr(self, '_temp_aligned_dirs'):
            for temp_dir in self._temp_aligned_dirs:
                try:
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
                except Exception as e:
                    print(f"Warning: Could not remove temporary directory {temp_dir}: {e}")
            self._temp_aligned_dirs.clear()
    
    def check_system_memory(self):
        """Check system memory availability and provide recommendations."""
        try:
            import psutil
            memory = psutil.virtual_memory()
            available_gb = memory.available / (1024**3)
            total_gb = memory.total / (1024**3)
            used_percent = memory.percent
            
            print(f"System memory status:")
            print(f"  Total: {total_gb:.1f} GB")
            print(f"  Available: {available_gb:.1f} GB")
            print(f"  Used: {used_percent:.1f}%")
            
            if available_gb < 2.0:
                QMessageBox.warning(
                    self, "Low Memory Warning",
                    f"System has only {available_gb:.1f} GB of available memory.\n\n"
                    f"Recommendations:\n"
                    f"• Close other applications\n"
                    f"• Reduce the number of images to align\n"
                    f"• Use chunked processing (enabled: {settings.ALIGNMENT_ENABLE_CHUNKED})\n"
                    f"• Consider using a smaller chunk size (current: {settings.ALIGNMENT_CHUNK_SIZE})"
                )
                return False
            elif available_gb < 4.0:
                QMessageBox.information(
                    self, "Memory Notice",
                    f"System has {available_gb:.1f} GB of available memory.\n\n"
                    f"Chunked processing is recommended for large datasets."
                )
            
            return True
            
        except ImportError:
            print("psutil not available - cannot check system memory")
            return True
        except Exception as e:
            print(f"Error checking system memory: {e}")
            return True
    
    def closeEvent(self, event):
        """Override closeEvent to cleanup temporary files."""
        self.cleanup_temp_files()
        # Call parent closeEvent if it exists
        if hasattr(super(), 'closeEvent'):
            super().closeEvent(event)
        else:
            event.accept()
    
    def align_images(self, method=None):
        """Align all loaded images using the specified method or configuration default.
        
        Parameters:
        -----------
        method : str, optional
            Alignment method: "astroalign" (fast, asterism-based) or "wcs_reprojection" (slow, WCS-based)
            If None, uses the method from configuration or shows dialog if enabled.
        """
        from astropipes.processing.alignment import AlignmentError, align_image_set, choose_alignment_method
        from astropipes.core.memory import get_memory_usage
        
        # Remove overlays before aligning
        self._simbad_overlay = None
        self._simbad_field_overlay = None
        self._roi_field_overlay = None
        self._roi_field_overlay_active = False
        self._overlay_visible = True
        if hasattr(self, 'overlay_toolbar_controller'):
            self.overlay_toolbar_controller.update_overlay_button_visibility()
        
        # Gather image data and headers
        image_datas = []
        headers = []
        total_memory_estimate = 0
        
        for path in self.loaded_files:
            img, hdr, wcs = self._preloaded_fits.get(path, (None, None, None))
            if img is None or hdr is None:
                QMessageBox.critical(self, "Alignment Error", f"Could not load image or header for {path}")
                return
            image_datas.append(img)
            headers.append(hdr)
            # Estimate memory usage (rough calculation)
            total_memory_estimate += img.nbytes
        
        # Show memory information
        current_memory = get_memory_usage()
        estimated_alignment_memory = total_memory_estimate * 2  # Rough estimate for aligned images
        total_estimated_memory = current_memory + (estimated_alignment_memory / (1024 * 1024))
        
        print(f"Memory analysis for alignment:")
        print(f"  Current memory usage: {current_memory:.1f} MB")
        print(f"  Images to align: {len(image_datas)}")
        print(f"  Total image data size: {total_memory_estimate / (1024*1024):.1f} MB")
        print(f"  Estimated alignment memory: {estimated_alignment_memory / (1024*1024):.1f} MB")
        print(f"  Total estimated memory: {total_estimated_memory:.1f} MB")
        print(f"  Memory limit: {settings.ALIGNMENT_MEMORY_LIMIT / (1024*1024):.1f} MB")
        
        # Check if we're likely to exceed memory limits
        if total_estimated_memory > (settings.ALIGNMENT_MEMORY_LIMIT / (1024 * 1024)):
            reply = QMessageBox.question(
                self, "High Memory Usage", 
                f"Estimated memory usage ({total_estimated_memory:.1f} MB) exceeds the limit ({settings.ALIGNMENT_MEMORY_LIMIT / (1024*1024):.1f} MB).\n\n"
                f"This may cause the application to crash. Consider:\n"
                f"• Reducing the number of images\n"
                f"• Using chunked processing (enabled: {settings.ALIGNMENT_ENABLE_CHUNKED})\n"
                f"• Closing other applications\n\n"
                f"Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        # Check image count limit
        if len(image_datas) > settings.MAX_ALIGNMENT_IMAGES:
            reply = QMessageBox.question(
                self, "Many Images", 
                f"You are trying to align {len(image_datas)} images. This may take a long time and use significant memory. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        # Check system memory availability
        if not self.check_system_memory():
            return
        
        # Determine alignment method
        if method is None:
            if settings.SHOW_ALIGNMENT_METHOD_DIALOG:
                # Show method selection dialog
                dialog = AlignmentMethodDialog(self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    method = dialog.get_selected_method()
                    # TODO: If dialog.should_remember_choice(), save to user preferences
                else:
                    return  # User cancelled
            else:
                # Use configuration default
                method = settings.DEFAULT_ALIGNMENT_METHOD
        
        try:
            method, notice = choose_alignment_method(method, headers)
        except AlignmentError as e:
            QMessageBox.critical(self, "Alignment Error", f"{e} Alignment aborted.")
            return
        if notice:
            QMessageBox.warning(self, "Alignment Method Unavailable", notice)
        
        # Create console window for alignment output
        from astropipes.gui.common.console_window import ConsoleOutputWindow
        console_window = ConsoleOutputWindow("Image Alignment", self)
        console_window.show_and_raise()
        
        def align_job(log, should_cancel):
            log("=" * 60 + "\nSTARTING IMAGE ALIGNMENT\n" + "=" * 60 + "\n")
            aligned_datas, reference_header, updated_headers = align_image_set(image_datas, headers, method, log)
            new_nx = reference_header['NAXIS1'] if reference_header else aligned_datas[0].shape[1]
            new_ny = reference_header['NAXIS2'] if reference_header else aligned_datas[0].shape[0]
            log(f"Final image dimensions: {new_nx} x {new_ny}\n")
            log("=" * 60 + "\nALIGNMENT COMPLETED SUCCESSFULLY\n" + "=" * 60 + "\n")
            return {'success': True, 'aligned_datas': aligned_datas, 'new_nx': new_nx, 'new_ny': new_ny,
                    'headers': updated_headers}
        
        self._align_thread = JobThread(align_job)
        self._align_thread.output.connect(console_window.append_text)
        
        def on_finished(result):
            if not result.get('success'):
                msg = result.get('error', 'unknown error')
                console_window.append_text(f"\nERROR: {msg}\n")
                QMessageBox.critical(self, "Alignment Error", f"Error during alignment: {msg}")
                return
            aligned_datas = result['aligned_datas']
            new_nx, new_ny = result['new_nx'], result['new_ny']
            headers = result['headers']
            console_window.append_text("\nSaving aligned images...\n")
            
            # Create temporary directory for aligned files
            import tempfile
            import os
            from astropy.io import fits
            
            # Create the base aligned directory
            base_aligned_dir = work_dir("aligned")
            os.makedirs(base_aligned_dir, exist_ok=True)
            
            # Create a unique subdirectory for this alignment session
            temp_dir = tempfile.mkdtemp(dir=base_aligned_dir, prefix="")
            if not hasattr(self, '_temp_aligned_dirs'):
                self._temp_aligned_dirs = []
            self._temp_aligned_dirs.append(temp_dir)  # Track for cleanup
            new_file_paths = []
            
            try:
                for i, path in enumerate(self.loaded_files):
                    console_window.append_text(f"Saving aligned image {i+1}/{len(self.loaded_files)}: {os.path.basename(path)}\n")
                    
                    # Use the updated header for this specific image
                    new_header = headers[i].copy()
                    new_header['NAXIS1'] = new_nx
                    new_header['NAXIS2'] = new_ny
                    # Add alignment method info to header
                    new_header['ALIGN_MTH'] = method
                    if method == "astroalign":
                        new_header['COMMENT'] = 'Aligned using astroalign asterism matching'
                    else:
                        new_header['COMMENT'] = 'Aligned using WCS reprojection'
                    
                    # Create WCS object for this specific image
                    image_wcs = None
                    try:
                        from astropy.wcs import WCS
                        image_wcs = WCS(new_header)
                    except:
                        pass
                    
                    # Save aligned image to temporary file
                    original_filename = os.path.basename(path)
                    name, ext = os.path.splitext(original_filename)
                    aligned_filename = f"aligned_{name}{ext}"
                    aligned_path = os.path.join(temp_dir, aligned_filename)
                    
                    # Create FITS file with aligned data and updated header
                    hdu = fits.PrimaryHDU(aligned_datas[i], new_header)
                    hdu.writeto(aligned_path, overwrite=True)
                    
                    new_file_paths.append(aligned_path)
                    
                    # Update the preloaded fits cache
                    self._preloaded_fits[aligned_path] = (aligned_datas[i], new_header, image_wcs)
                    
                    # Force garbage collection every few images to prevent memory buildup
                    if settings.ALIGNMENT_SAVE_PROGRESSIVE and (i + 1) % 5 == 0:
                        import gc
                        gc.collect()
                        console_window.append_text("  Memory cleanup performed\n")
                
                # Update loaded_files list to point to the new aligned files
                self.loaded_files = new_file_paths
                
                self.current_file_index = 0
                self.load_fits(self.loaded_files[0], restore_view=False)
                self.update_navigation_buttons()
                self.update_image_count_label()
                self.update_align_button_visibility()
                
                console_window.append_text("\n" + "=" * 60 + "\n")
                console_window.append_text("ALIGNMENT AND SAVING COMPLETED SUCCESSFULLY\n")
                console_window.append_text("=" * 60 + "\n")
                console_window.append_text(f"Aligned {len(new_file_paths)} images\n")
                console_window.append_text(f"Files saved to: {temp_dir}\n")
                
            except Exception as e:
                console_window.append_text(f"\nERROR during saving: {str(e)}\n")
                QMessageBox.critical(self, "Alignment Error", f"Error during saving: {str(e)}")
            finally:
                # Final memory cleanup
                import gc
                gc.collect()
                console_window.append_text("Final memory cleanup completed\n")
            
        self._align_thread.finished.connect(on_finished)
        self._align_thread.start()

    def align_images_fast(self):
        """Align images using the fast astroalign method."""
        self.align_images(method="astroalign")

    def align_images_wcs(self):
        """Align images using the slow WCS reprojection method."""
        self.align_images(method="wcs_reprojection")

    def _format_platesolving_result(self, result):
        """Format platesolving results for display."""
        if hasattr(result, 'success') and result.success:
            success_msg = "Image successfully solved!\n\n"
            if getattr(result, 'ra_center', None) is not None and getattr(result, 'dec_center', None) is not None:
                success_msg += f"Center: RA={result.ra_center:.4f}°, Dec={result.dec_center:.4f}°\n"
            else:
                success_msg += "Center: Unknown\n"
            if getattr(result, 'pixel_scale', None) is not None:
                success_msg += f"Pixel scale: {result.pixel_scale:.3f} arcsec/pixel\n"
            else:
                success_msg += "Pixel scale: Unknown\n"
            return success_msg
        else:
            return f"Could not solve image: {getattr(result, 'message', str(result))}"

    def platesolve_all_images(self):
        """Platesolve all loaded images using astrometry.net."""
        from astropipes.gui.common.console_window import ConsoleOutputWindow
        from astropipes.gui.library.threads import PlatesolvingThread
        
        # Minimal wrapper for .path attribute
        class FilePathObj:
            def __init__(self, path):
                self.path = path
        
        files = [FilePathObj(p) for p in self.loaded_files]
        if not files:
            QMessageBox.warning(self, "No files", "No FITS files loaded to platesolve.")
            return
        
        console_window = ConsoleOutputWindow("Platesolving All Files", self)
        console_window.show_and_raise()
        queue = list(files)
        results = []
        cancelled = {"flag": False}
        
        if not hasattr(self, '_platesolving_threads'):
            self._platesolving_threads = []
        
        def next_in_queue():
            if cancelled["flag"]:
                console_window.append_text("\nPlatesolving cancelled by user.\n")
                return
            if not queue:
                console_window.append_text("\nAll files platesolved.\n")
                # Reload all loaded files after platesolving
                current_index = self.current_file_index
                loaded_files_copy = list(self.loaded_files)
                self._preloaded_fits.clear()
                for path in loaded_files_copy:
                    self._preload_fits_file(path)
                # Try to restore the current file index
                if loaded_files_copy:
                    self.current_file_index = min(current_index, len(loaded_files_copy) - 1)
                    self.load_fits(loaded_files_copy[self.current_file_index], restore_view=True)
                self.update_navigation_buttons()
                self.update_image_count_label()
                self.update_align_button_visibility()
                self.update_platesolve_button_visibility()
                return
            
            fits_file = queue.pop(0)
            fits_path = fits_file.path
            console_window.append_text(f"\nPlatesolving: {fits_path}\n")
            thread = PlatesolvingThread(fits_path)
            self._platesolving_threads.append(thread)
            thread.output.connect(console_window.append_text)
            
            def on_finished(result):
                results.append(result)
                msg = self._format_platesolving_result(result)
                console_window.append_text(f"\n{msg}\n")
                if thread in self._platesolving_threads:
                    self._platesolving_threads.remove(thread)
                next_in_queue()
            
            thread.finished.connect(on_finished)
            thread.start()
        
        console_window.cancel_requested.connect(lambda: cancelled.update({"flag": True}))
        next_in_queue()

    def calibrate_all_images(self):
        """Calibrate all loaded images using bias, dark, and flat frames."""
        from astropipes.gui.common.console_window import ConsoleOutputWindow
        from astropipes.gui.library.threads import CalibrationThread
        
        # Minimal wrapper for .path attribute
        class FilePathObj:
            def __init__(self, path):
                self.path = path
        
        files = [FilePathObj(p) for p in self.loaded_files]
        if not files:
            QMessageBox.warning(self, "No files", "No FITS files loaded to calibrate.")
            return
        
        console_window = ConsoleOutputWindow("Calibrating All Files", self)
        console_window.show_and_raise()
        queue = list(files)
        results = []
        cancelled = {"flag": False}
        
        if not hasattr(self, '_calibration_threads'):
            self._calibration_threads = []
        
        def next_in_queue():
            if cancelled["flag"]:
                console_window.append_text("\nCalibration cancelled by user.\n")
                return
            if not queue:
                # Check for errors
                errors = [r for r in results if not r.get('success')]
                if errors:
                    console_window.append_text("\nCalibration failed for one or more files. No files were replaced.\n")
                    QMessageBox.critical(self, "Calibration Error", "Calibration failed for one or more files. No files were replaced.")
                    return
                # All succeeded: replace loaded files with calibrated equivalents
                new_files = [r['calibrated_path'] for r in results]
                self.loaded_files = new_files
                self._preloaded_fits.clear()
                for path in new_files:
                    self._preload_fits_file(path)
                self.current_file_index = 0
                self.load_fits(self.loaded_files[0], restore_view=False)
                self.update_navigation_buttons()
                self.update_image_count_label()
                self.update_align_button_visibility()
                self.update_platesolve_button_visibility()
                console_window.append_text("\nAll files calibrated and loaded.\n")
                return
            
            fits_file = queue.pop(0)
            fits_path = fits_file.path
            console_window.append_text(f"\nCalibrating: {fits_path}\n")
            thread = CalibrationThread(fits_path)
            self._calibration_threads.append(thread)
            thread.output.connect(console_window.append_text)
            
            def on_finished(result):
                results.append(result)
                if thread in self._calibration_threads:
                    self._calibration_threads.remove(thread)
                next_in_queue()
            
            thread.finished.connect(on_finished)
            thread.start()
        
        console_window.cancel_requested.connect(lambda: cancelled.update({"flag": True}))
        next_in_queue() 

    def calibrate_current_image(self):
        """Calibrate the currently displayed image using bias, dark, and flat frames."""
        from astropipes.gui.common.console_window import ConsoleOutputWindow
        from astropipes.gui.library.threads import CalibrationThread
        
        if not self.loaded_files:
            QMessageBox.warning(self, "No files", "No FITS files loaded to calibrate.")
            return
        
        current_file = self.loaded_files[self.current_file_index]
        
        console_window = ConsoleOutputWindow("Calibrating Current File", self)
        console_window.show_and_raise()
        
        # Store thread as instance variable to prevent premature destruction
        self._calibrate_current_thread = CalibrationThread(current_file)
        self._calibrate_current_thread.output.connect(console_window.append_text)
        
        def on_finished(result):
            if result.get('success'):
                # Replace the current file with the calibrated version
                calibrated_path = result['calibrated_path']
                self.loaded_files[self.current_file_index] = calibrated_path
                # Reload all files to ensure cache is consistent
                self._preloaded_fits.clear()
                for path in self.loaded_files:
                    self._preload_fits_file(path)
                self.load_fits(calibrated_path, restore_view=True)
                self.update_navigation_buttons()
                self.update_image_count_label()
                self.update_align_button_visibility()
                self.update_platesolve_button_visibility()
                console_window.append_text("\nFile calibrated and loaded.\n")
            else:
                console_window.append_text("\nCalibration failed.\n")
                QMessageBox.critical(self, "Calibration Error", "Calibration failed for the current file.")
            
            # Clean up thread reference
            self._calibrate_current_thread = None
        
        self._calibrate_current_thread.finished.connect(on_finished)
        self._calibrate_current_thread.start()

    def platesolve_current_image(self):
        """Platesolve the currently displayed image using astrometry.net."""
        from astropipes.gui.common.console_window import ConsoleOutputWindow
        from astropipes.gui.library.threads import PlatesolvingThread
        
        if not self.loaded_files:
            QMessageBox.warning(self, "No files", "No FITS files loaded to platesolve.")
            return
        
        current_file = self.loaded_files[self.current_file_index]
        
        console_window = ConsoleOutputWindow("Platesolving Current File", self)
        console_window.show_and_raise()
        
        # Store thread as instance variable to prevent premature destruction
        self._platesolve_current_thread = PlatesolvingThread(current_file)
        self._platesolve_current_thread.output.connect(console_window.append_text)
        
        def on_finished(result):
            msg = self._format_platesolving_result(result)
            console_window.append_text(f"\n{msg}\n")
            
            if hasattr(result, 'success') and result.success:
                # Reload all files after platesolving to ensure cache is consistent
                self._preloaded_fits.clear()
                for path in self.loaded_files:
                    self._preload_fits_file(path)
                self.load_fits(current_file, restore_view=True)
                self.update_navigation_buttons()
                self.update_image_count_label()
                self.update_align_button_visibility()
                self.update_platesolve_button_visibility()
            
            # Clean up thread reference
            self._platesolve_current_thread = None
        
        self._platesolve_current_thread.finished.connect(on_finished)
        self._platesolve_current_thread.start() 