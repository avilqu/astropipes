#!/usr/bin/env python3
"""
Daily Stacks Generation Thread
Handles daily stacks generation (group by session, calibrate, align, integrate) in a background thread for the GUI.
"""

import sys
import os
from datetime import datetime, timedelta
from collections import defaultdict
from PyQt6.QtCore import QThread, pyqtSignal
from colorama import init, Fore, Style
from astropy.io import fits
import config

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from lib.fits.calibration import CalibrationManager
from lib.fits.align import align_images_chunked, check_astroalign_available
from lib.fits.integration import integrate_standard
from config import DEFAULT_ALIGNMENT_METHOD, ALIGNMENT_MEMORY_LIMIT, ALIGNMENT_CHUNK_SIZE, INTEGRATION_MEMORY_LIMIT, SIGMA_LOW, SIGMA_HIGH


class RealtimeStdout:
    """A stdout-like object that emits output immediately via a signal."""
    def __init__(self, output_signal):
        self.output_signal = output_signal
        self.buffer = ""
    
    def write(self, text):
        """Write text and emit immediately."""
        if text:
            self.buffer += text
            # Emit complete lines immediately
            while '\n' in self.buffer:
                line, self.buffer = self.buffer.split('\n', 1)
                if line:
                    self.output_signal.emit(line + '\n')
            # If buffer is getting large, emit it anyway (for long lines without newlines)
            if len(self.buffer) > 200:
                self.output_signal.emit(self.buffer)
                self.buffer = ""
    
    def flush(self):
        """Flush any remaining buffer."""
        if self.buffer:
            self.output_signal.emit(self.buffer)
            self.buffer = ""
    
    def isatty(self):
        """Return False to indicate this is not a TTY (helps with some buffering)."""
        return False


def group_files_by_session(files, session_threshold_hours=12):
    """
    Group files by session. Images taken during the same night - any image with more than 
    session_threshold_hours difference is from another session.
    
    Args:
        files: List of FitsFile objects with date_obs attribute
        session_threshold_hours: Time difference in hours to consider a new session (default: 12)
        
    Returns:
        List of lists, where each inner list contains files from the same session
    """
    if not files:
        return []
    
    # Sort files by date_obs
    sorted_files = sorted([f for f in files if f.date_obs], key=lambda f: f.date_obs)
    
    if not sorted_files:
        return []
    
    sessions = []
    current_session = [sorted_files[0]]
    
    for i in range(1, len(sorted_files)):
        time_diff = sorted_files[i].date_obs - sorted_files[i-1].date_obs
        if time_diff.total_seconds() / 3600 > session_threshold_hours:
            # New session
            sessions.append(current_session)
            current_session = [sorted_files[i]]
        else:
            # Same session
            current_session.append(sorted_files[i])
    
    # Add the last session
    if current_session:
        sessions.append(current_session)
    
    return sessions


class DailyStacksGenerationThread(QThread):
    """Thread for performing daily stacks generation (group by session, calibrate, align, integrate) for a target."""
    
    output = pyqtSignal(str)  # Emit process output
    finished = pyqtSignal(dict)  # Emit final result
    
    def __init__(self, target_name, files, filter_name=None):
        """
        Initialize the daily stacks generation thread.
        
        Args:
            target_name: Name of the target
            files: List of FitsFile objects for the target (already filtered by filter if provided)
            filter_name: Optional filter name for display purposes
        """
        super().__init__()
        self.target_name = target_name
        self.files = files
        self.filter_name = filter_name
        self._running = True
        
        # Initialize colorama
        init(autoreset=False)
    
    def stop(self):
        """Stop the thread execution."""
        self._running = False
    
    def _log(self, message):
        """Log a message via the output signal."""
        self.output.emit(message)
    
    def run(self):
        """Run the daily stacks generation process."""
        try:
            result = self._generate_daily_stacks()
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit({'error': str(e), 'success': False})
    
    def _generate_daily_stacks(self):
        """Generate daily stacks for all sessions of the target."""
        if not self.files:
            return {'error': 'No files found for target', 'success': False}
        
        filter_info = f" (filter: {self.filter_name})" if self.filter_name else ""
        self._log(f"{Style.BRIGHT + Fore.BLUE}Starting daily stacks generation for target: {self.target_name}{filter_info}{Style.RESET_ALL}")
        self._log(f"Total files: {len(self.files)}\n")
        
        # Step 1: Group files by session (12h threshold)
        self._log(f"\n{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}Step 1: Grouping files by session (12h threshold){Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
        
        sessions = group_files_by_session(self.files, session_threshold_hours=12)
        
        if not sessions:
            return {'error': 'No valid sessions found (files must have date_obs)', 'success': False}
        
        # Check if there's only one session
        if len(sessions) == 1:
            return {
                'error': 'Only one session found for this target. Daily stacks generation requires multiple sessions.',
                'success': False,
                'single_session': True
            }
        
        self._log(f"Found {len(sessions)} session(s):\n")
        for i, session in enumerate(sessions):
            if session:
                start_time = session[0].date_obs
                end_time = session[-1].date_obs
                self._log(f"  Session {i+1}: {len(session)} files, from {start_time} to {end_time}\n")
        
        calibration_manager = CalibrationManager()
        
        # Step 2: Calibrate all images (regardless of session)
        self._log(f"\n{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}Step 2: Calibrating all {len(self.files)} images{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
        
        # Sort files by date_obs to ensure consistent ordering
        sorted_files = sorted(self.files, key=lambda f: f.date_obs or '')
        calibrated_paths = []
        file_to_calibrated = {}  # Map original file to calibrated path
        calibrated_to_file = {}  # Map calibrated path to original file
        
        for i, file in enumerate(sorted_files):
            if not self._running:
                return {'error': 'Cancelled by user', 'success': False}
            
            self._log(f"  [{i+1}/{len(sorted_files)}] Calibrating: {os.path.basename(file.path)}\n")
            
            try:
                result = calibration_manager.calibrate_file(file.path)
                if result.get('success'):
                    calibrated_path = result['calibrated_path']
                    calibrated_paths.append(calibrated_path)
                    file_to_calibrated[file] = calibrated_path
                    calibrated_to_file[calibrated_path] = file
                    self._log(f"    ✓ Calibrated: {os.path.basename(calibrated_path)}\n")
                else:
                    error = result.get('error', 'Unknown error')
                    self._log(f"    ✗ Failed: {error}\n")
                    # Continue with other files even if one fails
            except Exception as e:
                self._log(f"    ✗ Error: {str(e)}\n")
                # Continue with other files
        
        if not calibrated_paths:
            return {'error': 'No files could be calibrated', 'success': False}
        
        self._log(f"\n{Fore.GREEN}✓ Calibrated {len(calibrated_paths)} images{Style.RESET_ALL}\n")
        
        # Step 3: Align all calibrated images together
        self._log(f"\n{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}Step 3: Aligning all {len(calibrated_paths)} images together{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
        
        # Load image data and headers (maintain order)
        image_datas = []
        headers = []
        calibrated_paths_ordered = []  # Keep track of which calibrated paths were successfully loaded
        
        for calibrated_path in calibrated_paths:
            if not self._running:
                return {'error': 'Cancelled by user', 'success': False}
            
            try:
                with fits.open(calibrated_path) as hdul:
                    image_data = hdul[0].data
                    header = hdul[0].header.copy()
                    image_datas.append(image_data)
                    headers.append(header)
                    calibrated_paths_ordered.append(calibrated_path)
            except Exception as e:
                self._log(f"  Warning: Could not load {calibrated_path}: {e}\n")
                continue
        
        if not image_datas:
            return {'error': 'No images could be loaded for alignment', 'success': False}
        
        # Determine alignment method
        alignment_method = DEFAULT_ALIGNMENT_METHOD
        if alignment_method == "astroalign" and not check_astroalign_available():
            self._log(f"{Fore.YELLOW}astroalign not available, using WCS reprojection{Style.RESET_ALL}\n")
            alignment_method = "wcs_reprojection"
        
        self._log(f"  Using alignment method: {alignment_method}\n")
        
        # Align images (first one as reference)
        try:
            def log_callback(msg):
                # Ensure message ends with newline if it doesn't already
                msg_str = str(msg)
                if not msg_str.endswith('\n'):
                    msg_str += '\n'
                self._log(f"  {msg_str}")
            
            aligned_datas, reference_header = align_images_chunked(
                image_datas,
                headers,
                method=alignment_method,
                reference_index=0,
                chunk_size=ALIGNMENT_CHUNK_SIZE,
                memory_limit=ALIGNMENT_MEMORY_LIMIT,
                log_callback=log_callback
            )
            
            self._log(f"\n{Fore.GREEN}✓ Aligned {len(aligned_datas)} images{Style.RESET_ALL}\n")
            
        except Exception as e:
            error_msg = f"Alignment failed: {e}"
            self._log(f"{Fore.RED}✗ {error_msg}{Style.RESET_ALL}\n")
            return {'error': error_msg, 'success': False}
        
        # Step 4: Save aligned images and generate stack for each session
        self._log(f"\n{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}Step 4: Saving aligned images and generating stacks{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
        
        # Create output directory
        stacks_dir = os.path.join(config.PROCESSED_PATH, "daily_stacks", self.target_name)
        os.makedirs(stacks_dir, exist_ok=True)
        
        # Save all aligned images first
        aligned_dir = os.path.join(stacks_dir, "aligned")
        os.makedirs(aligned_dir, exist_ok=True)
        
        # Map calibrated paths to aligned file paths (maintain order)
        calibrated_to_aligned = {}
        for i, calibrated_path in enumerate(calibrated_paths_ordered):
            if i < len(aligned_datas):
                aligned_data = aligned_datas[i]
                aligned_header = reference_header.copy()
                aligned_header['NAXIS1'] = aligned_data.shape[1]
                aligned_header['NAXIS2'] = aligned_data.shape[0]
                
                # Copy WCS from reference header
                from lib.fits.wcs import copy_wcs_from_reference
                aligned_header = copy_wcs_from_reference(reference_header, aligned_header)
                
                # Add alignment metadata
                aligned_header['ALIGNED'] = (True, 'Image has been aligned')
                if calibrated_paths_ordered:
                    aligned_header['ALIGNREF'] = (os.path.basename(calibrated_paths_ordered[0]), 'Reference image for alignment')
                
                # Save aligned image
                base_name = os.path.basename(calibrated_path)
                aligned_path = os.path.join(aligned_dir, f"aligned_{base_name}")
                
                hdu = fits.PrimaryHDU(data=aligned_data, header=aligned_header)
                hdu.writeto(aligned_path, overwrite=True)
                
                calibrated_to_aligned[calibrated_path] = aligned_path
        
        self._log(f"  Saved {len(calibrated_to_aligned)} aligned images\n")
        
        # Generate stack for each session
        stack_paths = []
        
        for session_idx, session in enumerate(sessions):
            if not self._running:
                return {'error': 'Cancelled by user', 'success': False}
            
            self._log(f"\n{Style.BRIGHT}Processing session {session_idx + 1}/{len(sessions)} ({len(session)} files){Style.RESET_ALL}\n")
            
            # Get aligned paths for files in this session
            session_aligned_paths = []
            
            for file in session:
                if file in file_to_calibrated:
                    calibrated_path = file_to_calibrated[file]
                    if calibrated_path in calibrated_to_aligned:
                        session_aligned_paths.append(calibrated_to_aligned[calibrated_path])
            
            if not session_aligned_paths:
                self._log(f"  Warning: No aligned images for session {session_idx + 1}, skipping\n")
                continue
            
            # Integrate session images
            try:
                # Generate output filename
                filter_suffix = f"_{self.filter_name}" if self.filter_name else ""
                if session:
                    session_start = session[0].date_obs
                    session_date_str = session_start.strftime('%Y%m%d')
                    output_filename = f"stack_{self.target_name}{filter_suffix}_{session_date_str}_session{session_idx+1}.fits"
                else:
                    output_filename = f"stack_{self.target_name}{filter_suffix}_session{session_idx+1}.fits"
                
                output_path = os.path.join(stacks_dir, output_filename)
                
                self._log(f"  Integrating {len(session_aligned_paths)} images...\n")
                
                def progress_callback(progress):
                    self._log(f"  Progress: {progress*100:.1f}%\n")
                
                # Use integrate_standard with sigma clipping
                stack = integrate_standard(
                    session_aligned_paths,
                    method='average',
                    sigma_clip=True,
                    output_path=output_path,
                    progress_callback=progress_callback,
                    memory_limit=INTEGRATION_MEMORY_LIMIT
                )
                
                stack_paths.append(output_path)
                self._log(f"  ✓ Stack saved: {output_filename}\n")
                
            except Exception as e:
                error_msg = f"Integration failed for session {session_idx + 1}: {e}"
                self._log(f"  ✗ {error_msg}\n")
                continue
        
        if not stack_paths:
            return {'error': 'No stacks could be generated', 'success': False}
        
        self._log(f"\n{Fore.GREEN}✓ Generated {len(stack_paths)} stack(s){Style.RESET_ALL}\n")
        
        return {
            'success': True,
            'target_name': self.target_name,
            'sessions_processed': len(sessions),
            'stacks_generated': len(stack_paths),
            'stack_paths': stack_paths
        }
