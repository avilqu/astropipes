import os
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem, QDialog, QTableWidget, QVBoxLayout
from astropy.io import fits
from lib.gui.common.header_window import HeaderViewer
from lib.fits.header import get_fits_header_as_json


class FileOperationsMixin:
    """Mixin class providing file operations and FITS header functionality."""
    
    def open_file_dialog(self):
        """Open a file dialog to select and load FITS files."""
        file_paths, _ = QFileDialog.getOpenFileNames(self, "Open FITS files", "", "FITS files (*.fits *.fit *.fts);;All files (*)")
        if file_paths:
            for file_path in file_paths:
                self.open_and_add_file(file_path)

    def open_file(self):
        """Alias for open_file_dialog for keyboard shortcuts."""
        self.open_file_dialog()

    def close_current_file(self):
        """Close the currently displayed FITS file and remove it from the image list."""
        if not self.loaded_files or self.current_file_index < 0:
            return
        
        # Remove the current file from the list
        removed_file = self.loaded_files.pop(self.current_file_index)
        
        # Remove from preloaded data
        if removed_file in self._preloaded_fits:
            del self._preloaded_fits[removed_file]
        
        # Update current file index
        if not self.loaded_files:
            # No files left - completely reset the viewer state
            self.current_file_index = -1
            self.image_data = None
            self.wcs = None
            self._current_header = None
            self.pixmap = None
            self._orig_pixmap = None
            
            # Clear the image label and set proper styling for text display
            self.image_label.clear()
            self.image_label.setText("No image loaded")
            self.image_label.setStyleSheet("QLabel { background-color: #f0f0f0; color: #333333; font-size: 14px; }")
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Reset the label size to allow proper text display
            self.image_label.setFixedSize(400, 300)
            
            # Center the label in the scroll area
            self.scroll_area.setWidgetResizable(True)
            self.scroll_area.ensureWidgetVisible(self.image_label)
            
            self.setWindowTitle("Astropipes FITS Viewer")
            self.header_button.setEnabled(False)
            self.close_action.setEnabled(False)
            self.delete_action.setEnabled(False)
            
            # Disable all image-dependent buttons
            self.update_button_states_for_no_image()
            
            # Clear any overlays
            self._simbad_overlay = None
            self._simbad_field_overlay = None
            self._sso_overlay = None
            self._ephemeris_overlay = None
            self._measurement_overlay = None
            self._overlay_visible = False
            if hasattr(self, 'overlay_toolbar_controller'):
                self.overlay_toolbar_controller.update_overlay_button_visibility()
        else:
            # Adjust current index if necessary
            if self.current_file_index >= len(self.loaded_files):
                self.current_file_index = len(self.loaded_files) - 1
            
            # Load the new current file
            self.load_fits(self.loaded_files[self.current_file_index], restore_view=False)
        
        # Update UI elements
        self.update_navigation_buttons()
        self.update_image_count_label()
        self.update_align_button_visibility()
        self.update_platesolve_button_visibility()
        self.update_close_button_visibility()
        self.update_delete_button_visibility()
        
        # Update file list window if open
        if hasattr(self, '_filelist_window') and self._filelist_window is not None:
            self._filelist_window.table.setRowCount(len(self.loaded_files))
            for i, path in enumerate(self.loaded_files):
                item = QTableWidgetItem(os.path.basename(path))
                item.setToolTip(path)
                self._filelist_window.table.setItem(i, 0, item)
            self._filelist_window.file_paths = list(self.loaded_files)
            if self.current_file_index >= 0:
                self._filelist_window.select_row(self.current_file_index)

    def delete_current_file(self):
        """Delete the currently displayed FITS file from disk and remove it from the image list."""
        if not self.loaded_files or self.current_file_index < 0:
            return
        
        # Get the file to delete
        file_to_delete = self.loaded_files[self.current_file_index]
        file_name = os.path.basename(file_to_delete)
        
        # Show confirmation dialog
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "Delete File",
            f"Are you sure you want to delete '{file_name}'?\n\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Check if file exists in database and delete it
        db_deleted = False
        try:
            from lib.db.manager import get_db_manager
            db_manager = get_db_manager()
            db_entry = db_manager.get_fits_file_by_path(file_to_delete)
            if db_entry:
                # File exists in database, delete it
                if db_manager.delete_fits_file(db_entry.id):
                    db_deleted = True
                else:
                    QMessageBox.warning(
                        self,
                        "Database Delete Failed",
                        f"File '{file_name}' was found in the database but could not be deleted from it."
                    )
        except Exception as e:
            # Log error but continue with file deletion
            print(f"Error checking/deleting from database: {e}")
        
        # Try to delete the file from disk
        try:
            if os.path.exists(file_to_delete):
                os.remove(file_to_delete)
            else:
                if not db_deleted:
                    QMessageBox.warning(
                        self,
                        "File Not Found",
                        f"File '{file_name}' was not found on disk. It will be removed from the viewer only."
                    )
                else:
                    # File was deleted from database but not found on disk - that's okay
                    pass
        except Exception as e:
            QMessageBox.critical(
                self,
                "Delete Failed",
                f"Failed to delete file '{file_name}':\n{str(e)}"
            )
            return
        
        # Remove the current file from the list (same logic as close_current_file)
        removed_file = self.loaded_files.pop(self.current_file_index)
        
        # Remove from preloaded data
        if removed_file in self._preloaded_fits:
            del self._preloaded_fits[removed_file]
        
        # Update current file index
        if not self.loaded_files:
            # No files left - completely reset the viewer state
            self.current_file_index = -1
            self.image_data = None
            self.wcs = None
            self._current_header = None
            self.pixmap = None
            self._orig_pixmap = None
            
            # Clear the image label and set proper styling for text display
            self.image_label.clear()
            self.image_label.setText("No image loaded")
            self.image_label.setStyleSheet("QLabel { background-color: #f0f0f0; color: #333333; font-size: 14px; }")
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Reset the label size to allow proper text display
            self.image_label.setFixedSize(400, 300)
            
            # Center the label in the scroll area
            self.scroll_area.setWidgetResizable(True)
            self.scroll_area.ensureWidgetVisible(self.image_label)
            
            self.setWindowTitle("Astropipes FITS Viewer")
            self.header_button.setEnabled(False)
            self.close_action.setEnabled(False)
            self.delete_action.setEnabled(False)
            
            # Disable all image-dependent buttons
            self.update_button_states_for_no_image()
            
            # Clear any overlays
            self._simbad_overlay = None
            self._simbad_field_overlay = None
            self._sso_overlay = None
            self._ephemeris_overlay = None
            self._measurement_overlay = None
            self._overlay_visible = False
            if hasattr(self, 'overlay_toolbar_controller'):
                self.overlay_toolbar_controller.update_overlay_button_visibility()
        else:
            # Adjust current index if necessary
            if self.current_file_index >= len(self.loaded_files):
                self.current_file_index = len(self.loaded_files) - 1
            
            # Load the new current file
            self.load_fits(self.loaded_files[self.current_file_index], restore_view=False)
        
        # Update UI elements
        self.update_navigation_buttons()
        self.update_image_count_label()
        self.update_align_button_visibility()
        self.update_platesolve_button_visibility()
        self.update_close_button_visibility()
        self.update_delete_button_visibility()
        
        # Update file list window if open
        if hasattr(self, '_filelist_window') and self._filelist_window is not None:
            self._filelist_window.table.setRowCount(len(self.loaded_files))
            for i, path in enumerate(self.loaded_files):
                item = QTableWidgetItem(os.path.basename(path))
                item.setToolTip(path)
                self._filelist_window.table.setItem(i, 0, item)
            self._filelist_window.file_paths = list(self.loaded_files)
            if self.current_file_index >= 0:
                self._filelist_window.select_row(self.current_file_index)
        
        # Note: Library windows will automatically refresh via file watcher when database changes

    def open_and_add_file(self, fits_path):
        """Open and add a FITS file to the loaded files list."""
        # Clean up temporary aligned files if loading a new file that's not part of current set
        if self.loaded_files and fits_path not in self.loaded_files:
            # Check if current files are temporary aligned files
            import config
            aligned_path = os.path.join(config.PROCESSED_PATH, "aligned")
            current_files_are_temp = all(
                os.path.basename(path).startswith('aligned_') and 
                aligned_path in path 
                for path in self.loaded_files
            )
            if current_files_are_temp:
                # Clean up temporary files when loading new files
                self.cleanup_temp_files()
        
        # Save zoom, center, and brightness before switching
        if self.image_data is not None:
            self._last_zoom = self._zoom
            self._last_center = self._get_viewport_center()
            self.histogram_controller.save_state_before_switch()
        else:
            self._last_zoom = 1.0
            self._last_center = None
            self._last_brightness = 50
        
        # If already loaded, just switch to it
        if fits_path in self.loaded_files:
            self.current_file_index = self.loaded_files.index(fits_path)
            self.load_fits(fits_path, restore_view=True)
        else:
            self.loaded_files.append(fits_path)
            self.current_file_index = len(self.loaded_files) - 1
            self._preload_fits_file(fits_path)
            self.load_fits(fits_path, restore_view=False)  # New files should be centered, not restore view
            # Auto-zoom to fit for the first file loaded
            if len(self.loaded_files) == 1:
                # Process events and then apply zoom to fit
                def delayed_zoom():
                    self.zoom_to_fit()
                QTimer.singleShot(100, delayed_zoom)
        
        self.update_navigation_buttons()
        self.update_image_count_label()
        self.update_align_button_visibility()
        self.update_platesolve_button_visibility()
        self.update_close_button_visibility()
        self.update_delete_button_visibility()
        
        # Update file list window if open
        if hasattr(self, '_filelist_window') and self._filelist_window is not None:
            self._filelist_window.table.setRowCount(len(self.loaded_files))
            for i, path in enumerate(self.loaded_files):
                item = QTableWidgetItem(os.path.basename(path))
                item.setToolTip(path)
                self._filelist_window.table.setItem(i, 0, item)
            self._filelist_window.file_paths = list(self.loaded_files)
            self._filelist_window.select_row(self.current_file_index)

    def _preload_fits_file(self, fits_path):
        """Preload FITS file data for faster switching."""
        if fits_path in self._preloaded_fits:
            return
        try:
            from astropy.wcs import WCS
            with fits.open(fits_path) as hdul:
                image_data = hdul[0].data
                header = hdul[0].header
                try:
                    wcs = WCS(header)
                except Exception:
                    wcs = None
                self._preloaded_fits[fits_path] = (image_data, header, wcs)
        except Exception:
            self._preloaded_fits[fits_path] = (None, None, None)

    def show_previous_file(self):
        """Show the previous file in the loaded files list."""
        # Save zoom, center, and brightness before switching
        if self.image_data is not None:
            self._last_zoom = self._zoom
            self._last_center = self._get_viewport_center()
            self.histogram_controller.save_state_before_switch()
        else:
            self._last_zoom = 1.0
            self._last_center = None
            self._last_brightness = 50
        
        n = len(self.loaded_files)
        if n == 0:
            return
        
        # Loop around to the last file if at the first
        if self.current_file_index > 0:
            self.current_file_index -= 1
        else:
            self.current_file_index = n - 1
        
        self.load_fits(self.loaded_files[self.current_file_index], restore_view=True)
        self.update_navigation_buttons()
        self.update_image_count_label()
        self.update_align_button_visibility()
        self.update_platesolve_button_visibility()
        self.update_close_button_visibility()
        self.update_delete_button_visibility()
        
        # Update highlight in file list window
        if hasattr(self, '_filelist_window') and self._filelist_window is not None:
            self._filelist_window.select_row(self.current_file_index)

    def show_next_file(self):
        """Show the next file in the loaded files list."""
        # Save zoom, center, and brightness before switching
        if self.image_data is not None:
            self._last_zoom = self._zoom
            self._last_center = self._get_viewport_center()
            self.histogram_controller.save_state_before_switch()
        else:
            self._last_zoom = 1.0
            self._last_center = None
            self._last_brightness = 50
        
        n = len(self.loaded_files)
        if n == 0:
            return
        
        # Loop around to the first file if at the last
        if self.current_file_index < n - 1:
            self.current_file_index += 1
        else:
            self.current_file_index = 0
        
        self.load_fits(self.loaded_files[self.current_file_index], restore_view=True)
        self.update_navigation_buttons()
        self.update_image_count_label()
        self.update_align_button_visibility()
        self.update_platesolve_button_visibility()
        self.update_close_button_visibility()
        self.update_delete_button_visibility()
        
        # Update highlight in file list window
        if hasattr(self, '_filelist_window') and self._filelist_window is not None:
            self._filelist_window.select_row(self.current_file_index)

    def load_fits(self, fits_path, restore_view=False):
        """Load a FITS file and display it."""
        try:
            # Use preloaded data if available
            if fits_path in self._preloaded_fits:
                image_data, header, wcs = self._preloaded_fits[fits_path]
            else:
                from astropy.wcs import WCS
                with fits.open(fits_path) as hdul:
                    image_data = hdul[0].data
                    header = hdul[0].header
                    try:
                        wcs = WCS(header)
                    except Exception:
                        wcs = None
                    self._preloaded_fits[fits_path] = (image_data, header, wcs)
            
            self._current_header = get_fits_header_as_json(fits_path)
            self.wcs = wcs
            
            if image_data is not None:
                if image_data.ndim == 2:
                    self.image_data = image_data
                    
                    # Restore proper image display styling
                    self.image_label.setStyleSheet("QLabel { background-color: black; }")
                    self.scroll_area.setWidgetResizable(False)
                    
                    # Restore zoom and center if requested
                    if restore_view and hasattr(self, '_last_zoom') and self._last_zoom:
                        self._zoom = self._last_zoom
                    else:
                        self._zoom = 1.0
                    self._pending_zoom_to_fit = False
                    self.update_image_display(keep_zoom=restore_view)
                    self.image_label.setText("")
                    self.setWindowTitle(f"Astropipes FITS Viewer - {fits_path}")
                    self.header_button.setEnabled(True)
                    
                    # Enable all image-dependent buttons
                    self.update_button_states_for_image_loaded()
                    # Initialize histogram parameters for the new image
                    self.histogram_controller.initialize_for_new_image(restore_view)
                else:
                    self.image_label.setText("FITS file is not a 2D image.")
                    self.image_data = None
                    self.header_button.setEnabled(False)
            else:
                self.image_label.setText("No image data in FITS file.")
                self.image_data = None
                self.header_button.setEnabled(False)
            
            # self._simbad_overlay = None  # Do NOT clear SIMBAD overlay when switching images
        except Exception as e:
            self.image_label.setText(f"Error loading FITS: {e}")
            self.image_data = None
            self.header_button.setEnabled(False)
            # self._simbad_overlay = None  # Do NOT clear SIMBAD overlay on error
        
        self.update_navigation_buttons()
        self.update_image_count_label()
        self.update_close_button_visibility()
        self.update_delete_button_visibility()
        
        # After loading, update ephemeris marker if present
        self.update_ephemeris_marker()
        
        # After loading, update computed positions marker if present
        self.update_computed_positions_marker()
        
        # After loading, update measurement marker if present
        self.update_measurement_marker()

    def _get_header_value(self, key, default=None):
        """Helper method to extract header values from (value, comment) tuples."""
        if not hasattr(self, '_current_header') or not self._current_header:
            return default
        
        value = self._current_header.get(key, default)
        if isinstance(value, tuple):
            return value[0]
        return value

    def update_ephemeris_marker(self):
        """Update the ephemeris marker for the current file."""
        # Check if this is a substack - if so, don't show ephemeris marker
        # Substacks have filenames starting with "substack"
        current_file = self.loaded_files[self.current_file_index] if self.loaded_files and 0 <= self.current_file_index < len(self.loaded_files) else ""
        is_substack = os.path.basename(current_file).startswith("substack")
        if is_substack:
            # This is a substack, don't show ephemeris marker
            self._ephemeris_overlay = None
            self._show_ephemeris_marker(None)
            return
            
        if hasattr(self, '_ephemeris_predicted_positions') and self._ephemeris_predicted_positions:
            # Check if this is a motion-tracked stack
            is_motion_tracked = False
            reference_position = None
            
            # Extract motion tracking flag from header
            is_motion_tracked = self._get_header_value('MOTION_TRACKED', False)
            
            if is_motion_tracked:
                import json
                reference_position_json = self._get_header_value('REFERENCE_POSITION')
                if reference_position_json:
                    try:
                        reference_position = json.loads(reference_position_json)
                    except (json.JSONDecodeError, TypeError):
                        reference_position = None
            
            if is_motion_tracked and reference_position is not None:
                # For motion-tracked stacks, we need to get the ephemeris position in pixel coordinates
                # The ephemeris positions are calculated for the original images, but we need the position
                # in the stacked image coordinate system
                
                # Get the ephemeris data for the first original image (index 0)
                idx = 0  # Use first ephemeris position for motion-tracked stacks
                if 0 <= idx < len(self._ephemeris_predicted_positions):
                    ephemeris = self._ephemeris_predicted_positions[idx]
                    ra = ephemeris.get("RA", 0.0)
                    dec = ephemeris.get("Dec", 0.0)
                    
                    # For motion-tracked stacks, the ephemeris position should be at the reference position
                    # because that's where the object was tracked to during stacking
                    # The reference position is the ephemeris-derived position in the stacked image
                    x, y = reference_position[0], reference_position[1]
                    
                    self._ephemeris_overlay = ((ra, dec), (x, y))
                    self._show_ephemeris_marker((x, y))
                else:
                    # Fallback to using reference position if no ephemeris data available
                    x, y = reference_position[0], reference_position[1]
                    # Use the first ephemeris entry for RA/Dec
                    idx = 0
                    if idx < len(self._ephemeris_predicted_positions):
                        ephemeris = self._ephemeris_predicted_positions[idx]
                        ra = ephemeris.get("RA", 0.0)
                        dec = ephemeris.get("Dec", 0.0)
                    else:
                        ra, dec = 0.0, 0.0
                    
                    self._ephemeris_overlay = ((ra, dec), (x, y))
                    self._show_ephemeris_marker((x, y))
            else:
                # For regular images, use the ephemeris data for the current file index
                idx = self.current_file_index
                if 0 <= idx < len(self._ephemeris_predicted_positions):
                    ephemeris = self._ephemeris_predicted_positions[idx]
                    ra = ephemeris.get("RA", 0.0)
                    dec = ephemeris.get("Dec", 0.0)
                    if self.wcs is not None:
                        from astropy.wcs.utils import skycoord_to_pixel
                        from astropy.coordinates import SkyCoord
                        import astropy.units as u
                        skycoord = SkyCoord(ra*u.deg, dec*u.deg, frame='icrs')
                        x, y = skycoord_to_pixel(skycoord, self.wcs)
                        self._ephemeris_overlay = ((ra, dec), (x, y))
                        self._show_ephemeris_marker((x, y))
                    else:
                        self._ephemeris_overlay = None
                        self._show_ephemeris_marker(None)

    def update_computed_positions_marker(self):
        """Update the computed positions marker for the current file."""
        
        # Check if this is a substack - if so, don't show computed positions marker
        # Substacks have filenames starting with "substack"
        current_file = self.loaded_files[self.current_file_index] if self.loaded_files and 0 <= self.current_file_index < len(self.loaded_files) else ""
        is_substack = os.path.basename(current_file).startswith("substack")
        if is_substack:
            # This is a substack, don't show computed positions marker
            self._computed_positions_overlay = None
            self._show_computed_positions_marker(None)
            return
        
        # Check if we have computed positions data available
        if hasattr(self, '_orbit_window') and self._orbit_window and hasattr(self._orbit_window, 'computed_positions_data'):
            computed_positions_data = self._orbit_window.computed_positions_data
            print(f"DEBUG: Found orbit window with {len(computed_positions_data)} computed positions")
        else:
            print(f"DEBUG: No orbit window or computed positions data available")
            # No orbit window or computed positions data
            self._computed_positions_overlay = None
            self._show_computed_positions_marker(None)
            return
        
        # Find the position data for the current file
        current_file_path = None
        if self.current_file_index >= 0 and self.current_file_index < len(self.loaded_files):
            current_file_path = self.loaded_files[self.current_file_index]
        
        if current_file_path and computed_positions_data:
            # Check if this is a motion-tracked stack
            is_motion_tracked = self._get_header_value('MOTION_TRACKED', False)
            
            if is_motion_tracked:
                # For motion-tracked stacks, find the position data for this stacked image
                # The computed positions data contains the user's clicked position in the stacked image
                position_data = None
                print(f"DEBUG: Looking for position data for current file: {current_file_path}")
                for pos in computed_positions_data:
                    # For motion-tracked stacks, we're looking for the stacked image position
                    # The file_path should match the current motion-tracked stack
                    pos_file_path = pos.get('file_path')
                    print(f"DEBUG: Checking position data file: {pos_file_path}")
                    if pos_file_path == current_file_path:
                        position_data = pos
                        print(f"DEBUG: Found matching position data")
                        break
                
                if position_data:
                    # Use the stacked coordinates (where the user clicked in the stacked image)
                    stacked_x = position_data.get('stacked_x', 0.0)
                    stacked_y = position_data.get('stacked_y', 0.0)
                    print(f"DEBUG: Found position data for motion-tracked stack: stacked_x={stacked_x}, stacked_y={stacked_y}")
                    
                    # Store the position data and coordinates for the overlay
                    self._computed_positions_overlay = (position_data, (stacked_x, stacked_y))
                    self._show_computed_positions_marker((stacked_x, stacked_y))
                    print(f"DEBUG: Set computed positions marker at ({stacked_x}, {stacked_y})")
                else:
                    # No position data for this specific motion-tracked stack
                    # Check if we have computed positions data for any motion-tracked stack
                    # If so, use the reference position from the header (which should be the same for all stacks)
                    print(f"DEBUG: No specific position data found, checking for reference position")
                    reference_position_json = self._get_header_value('REFERENCE_POSITION')
                    if reference_position_json:
                        try:
                            import json
                            reference_position = json.loads(reference_position_json)
                            ref_x, ref_y = reference_position[0], reference_position[1]
                            print(f"DEBUG: Using reference position for computed positions marker: ({ref_x}, {ref_y})")
                            
                            # Create a position data entry for the reference position
                            ref_position_data = {
                                'file_path': current_file_path,
                                'original_x': ref_x,
                                'original_y': ref_y,
                                'stacked_x': ref_x,
                                'stacked_y': ref_y,
                                'shift_x': 0.0,
                                'shift_y': 0.0,
                                'ra': None,
                                'dec': None
                            }
                            
                            self._computed_positions_overlay = (ref_position_data, (ref_x, ref_y))
                            self._show_computed_positions_marker((ref_x, ref_y))
                        except (json.JSONDecodeError, TypeError, IndexError) as e:
                            print(f"DEBUG: Error parsing reference position: {e}")
                            self._computed_positions_overlay = None
                            self._show_computed_positions_marker(None)
                    else:
                        # No reference position available, clear the marker
                        print(f"DEBUG: No reference position available")
                        self._computed_positions_overlay = None
                        self._show_computed_positions_marker(None)
            else:
                # For regular images, find the position data for the current file
                position_data = None
                for pos in computed_positions_data:
                    if pos.get('file_path') == current_file_path:
                        position_data = pos
                        break
                
                if position_data:
                    # Set marker overlay for computed position
                    original_x = position_data.get('original_x', 0.0)
                    original_y = position_data.get('original_y', 0.0)
                    
                    # Store the position data and coordinates for the overlay
                    self._computed_positions_overlay = (position_data, (original_x, original_y))
                    self._show_computed_positions_marker((original_x, original_y))
                else:
                    # No position data for this file, clear the marker
                    self._computed_positions_overlay = None
                    self._show_computed_positions_marker(None)
        else:
            # No computed positions data available
            self._computed_positions_overlay = None
            self._show_computed_positions_marker(None)

    def _show_computed_positions_marker(self, pixel_coords):
        """Store the marker position for overlay drawing."""
        self._computed_positions_marker_coords = pixel_coords
        self._overlay_visible = True
        if hasattr(self, 'overlay_toolbar_controller'):
            self.overlay_toolbar_controller.update_overlay_button_visibility()
        self.image_label.update()

    def update_measurement_marker(self):
        """
        Read MEAS_POS from the FITS header (if present) and prepare the yellow
        measurement overlay.
        """
        meas_json = self._get_header_value('MEAS_POS', None)
        if meas_json:
            import json
            try:
                x, y = json.loads(meas_json)
                self._measurement_overlay = (None, (x, y))
                self._show_measurement_marker((x, y))
                return
            except Exception:
                pass
        self._measurement_overlay = None
        self._show_measurement_marker(None)

    def _show_measurement_marker(self, pixel_coords):
        self._measurement_marker_coords = pixel_coords
        self._overlay_visible = True
        if hasattr(self, 'overlay_toolbar_controller'):
            self.overlay_toolbar_controller.update_overlay_button_visibility()
        self.image_label.update()

    def show_header_dialog(self):
        """Show the FITS header dialog for the current file."""
        if hasattr(self, '_current_header') and self._current_header:
            file_path = None
            if self.loaded_files and 0 <= self.current_file_index < len(self.loaded_files):
                file_path = self.loaded_files[self.current_file_index]
            dlg = HeaderViewer(self._current_header, file_path, self)
            dlg.show()

    # File list functions
    def toggle_filelist_window(self):
        """Toggle the file list window visibility."""
        if not hasattr(self, '_filelist_window') or self._filelist_window is None:
            def on_row_selected(row):
                # Save current brightness before switching
                self.histogram_controller.save_state_before_switch()
                # Save current viewport state before switching
                if hasattr(self, '_zoom'):
                    self._last_zoom = self._zoom
                self._last_center = self._get_viewport_center()
                self.current_file_index = row
                self.load_fits(self.loaded_files[row], restore_view=True)
                self.update_navigation_buttons()
                self.update_image_count_label()
                self.update_align_button_visibility()
                self.update_platesolve_button_visibility()
                self.update_close_button_visibility()
                self.update_delete_button_visibility()
                # Update highlight in file list window
                if hasattr(self, '_filelist_window') and self._filelist_window is not None:
                    self._filelist_window.select_row(row)
            self._filelist_window = FileListWindow(self.loaded_files, self.current_file_index, on_row_selected, self)
            self._filelist_window.finished.connect(self._on_filelist_closed)
            self.filelist_action.setChecked(True)
            self._filelist_window.show()
        else:
            self._filelist_window.close()

    def _on_filelist_closed(self):
        """Handle file list window closure."""
        self.filelist_action.setChecked(False)
        self._filelist_window = None


class FileListWindow(QDialog):
    """Dialog window for displaying and selecting from loaded FITS files."""
    
    def __init__(self, file_paths, current_index, on_row_selected, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Loaded FITS Files")
        self.resize(400, 400)
        self.table = QTableWidget(self)
        self.table.setColumnCount(1)
        self.table.setHorizontalHeaderLabels(["Filename"])
        self.table.setRowCount(len(file_paths))
        self.file_paths = file_paths
        self.on_row_selected = on_row_selected
        for i, path in enumerate(file_paths):
            item = QTableWidgetItem(os.path.basename(path))
            item.setToolTip(path)
            self.table.setItem(i, 0, item)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.select_row(current_index)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        self.setLayout(layout)
        # Connect selection change instead of clicks to enable keyboard navigation
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

    def _row_activated(self, row, col):
        """Handle row activation (double-click or Enter key)."""
        if 0 <= row < len(self.file_paths):
            self.on_row_selected(row)
            # Do not close the window here

    def _on_selection_changed(self, selected, deselected):
        """Handle selection changes to enable keyboard navigation."""
        selected_rows = self.table.selectionModel().selectedRows()
        if selected_rows:
            row = selected_rows[0].row()
            if 0 <= row < len(self.file_paths):
                self.on_row_selected(row)

    def select_row(self, row):
        """Select a specific row in the table."""
        if 0 <= row < self.table.rowCount():
            self.table.selectRow(row) 