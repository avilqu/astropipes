#!/usr/bin/env python3
"""
Masters Generation Thread
Handles masters generation (calibration, alignment, integration) in a background thread for the GUI.
"""

import sys
import os
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
from config import DEFAULT_ALIGNMENT_METHOD, ALIGNMENT_MEMORY_LIMIT, ALIGNMENT_CHUNK_SIZE, INTEGRATION_MEMORY_LIMIT


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


class MastersGenerationThread(QThread):
    """Thread for performing masters generation (calibrate, align, integrate) for a target."""
    
    output = pyqtSignal(str)  # Emit process output
    finished = pyqtSignal(dict)  # Emit final result
    
    def __init__(self, target_name: str, files: list):
        super().__init__()
        self.target_name = target_name
        self.files = files  # List of FitsFile objects
        self._running = True
    
    def run(self):
        """Run the masters generation process."""
        old_stdout = sys.stdout
        try:
            # Initialize colorama for colored output
            init()
            
            # Use real-time stdout that emits immediately
            realtime_stdout = RealtimeStdout(self.output)
            sys.stdout = realtime_stdout
            
            # Force unbuffered mode for immediate output
            if hasattr(sys.stdout, 'reconfigure'):
                try:
                    sys.stdout.reconfigure(line_buffering=True)
                except:
                    pass
            
            result = self._generate_masters()
            
            # Flush any remaining output
            realtime_stdout.flush()
            
            # Restore stdout
            sys.stdout = old_stdout
            
            # Emit result
            self.finished.emit(result)
            
        except Exception as e:
            # Restore stdout in case of error
            sys.stdout = old_stdout
            error_msg = f"{Style.BRIGHT + Fore.RED}Error during masters generation: {e}{Style.RESET_ALL}\n"
            self.output.emit(error_msg)
            self.finished.emit({'error': str(e), 'success': False})
    
    def _log(self, message):
        """Log a message - emits immediately."""
        print(message)
        # Force flush to ensure immediate emission
        if hasattr(sys.stdout, 'flush'):
            sys.stdout.flush()
    
    def _generate_masters(self):
        """Generate masters for all filters of the target."""
        if not self.files:
            return {'error': 'No files found for target', 'success': False}
        
        self._log(f"{Style.BRIGHT + Fore.BLUE}Starting masters generation for target: {self.target_name}{Style.RESET_ALL}")
        self._log(f"Total files: {len(self.files)}\n")
        
        # Group files by filter for later integration
        files_by_filter = defaultdict(list)
        for file in self.files:
            filter_name = file.filter_name or "Unknown"
            files_by_filter[filter_name].append(file)
        
        self._log(f"Found {len(files_by_filter)} filter(s): {', '.join(files_by_filter.keys())}\n")
        
        calibration_manager = CalibrationManager()
        
        # Step 1: Calibrate all images (regardless of filter)
        self._log(f"\n{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}Step 1: Calibrating all {len(self.files)} images{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
        
        # Sort files by date_obs to ensure consistent ordering
        sorted_files = sorted(self.files, key=lambda f: f.date_obs or '')
        calibrated_paths = []
        file_to_calibrated = {}  # Map original file to calibrated path
        
        for i, file in enumerate(sorted_files):
            if not self._running:
                return {'error': 'Cancelled by user', 'success': False}
            
            self._log(f"  [{i+1}/{len(sorted_files)}] Calibrating: {os.path.basename(file.path)}")
            try:
                result = calibration_manager.calibrate_file(file.path)
                if result.get('success') and 'calibrated_path' in result:
                    calibrated_path = result['calibrated_path']
                    calibrated_paths.append(calibrated_path)
                    file_to_calibrated[file] = calibrated_path
                    self._log(f"    {Fore.GREEN}✓ Calibrated{Style.RESET_ALL}")
                else:
                    error = result.get('error', 'Unknown error')
                    self._log(f"    {Fore.RED}✗ Failed: {error}{Style.RESET_ALL}")
            except Exception as e:
                self._log(f"    {Fore.RED}✗ Error: {e}{Style.RESET_ALL}")
        
        if not calibrated_paths:
            return {'error': 'No images were successfully calibrated', 'success': False}
        
        self._log(f"\n{Fore.GREEN}✓ Calibrated {len(calibrated_paths)}/{len(sorted_files)} images{Style.RESET_ALL}\n")
        
        # Step 2: Align all calibrated images together (regardless of filter)
        self._log(f"\n{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}Step 2: Aligning all {len(calibrated_paths)} calibrated images{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
        
        # Load images and headers for alignment
        image_datas = []
        headers = []
        path_to_aligned = {}  # Map calibrated path to aligned path
        
        for i, path in enumerate(calibrated_paths):
            if not self._running:
                return {'error': 'Cancelled by user', 'success': False}
            
            self._log(f"  [{i+1}/{len(calibrated_paths)}] Loading: {os.path.basename(path)}")
            try:
                with fits.open(path) as hdul:
                    img = hdul[0].data
                    hdr = hdul[0].header.copy()
                    image_datas.append(img)
                    headers.append(hdr)
            except Exception as e:
                self._log(f"    {Fore.RED}✗ Error loading: {e}{Style.RESET_ALL}")
                return {'error': f'Error loading image {path}: {e}', 'success': False}
        
        if len(image_datas) < 2:
            self._log(f"{Fore.YELLOW}Warning: Only {len(image_datas)} image(s), skipping alignment{Style.RESET_ALL}\n")
            # No alignment needed, use calibrated paths as aligned paths
            for path in calibrated_paths:
                path_to_aligned[path] = path
        else:
            # Determine alignment method
            alignment_method = DEFAULT_ALIGNMENT_METHOD
            if alignment_method == "astroalign" and not check_astroalign_available():
                self._log(f"{Fore.YELLOW}astroalign not available, using WCS reprojection{Style.RESET_ALL}\n")
                alignment_method = "wcs_reprojection"
            
            self._log(f"  Using alignment method: {alignment_method}\n")
            
            # Align images (first one as reference)
            try:
                def log_callback(msg):
                    self._log(f"  {msg}")
                
                aligned_datas, reference_header = align_images_chunked(
                    image_datas,
                    headers,
                    method=alignment_method,
                    reference_index=0,
                    chunk_size=ALIGNMENT_CHUNK_SIZE,
                    memory_limit=ALIGNMENT_MEMORY_LIMIT,
                    log_callback=log_callback
                )
                
                # Save aligned images
                aligned_dir = os.path.join(config.PROCESSED_PATH, "aligned", self.target_name)
                os.makedirs(aligned_dir, exist_ok=True)
                
                self._log(f"\n  Saving aligned images...\n")
                for i, (aligned_data, original_path, original_header) in enumerate(zip(aligned_datas, calibrated_paths, headers)):
                    if not self._running:
                        return {'error': 'Cancelled by user', 'success': False}
                    
                    base_name = os.path.basename(original_path)
                    aligned_path = os.path.join(aligned_dir, f"aligned_{base_name}")
                    
                    # Create new header starting with original header to preserve metadata
                    new_header = original_header.copy()
                    
                    # Update dimensions
                    new_header['NAXIS1'] = aligned_data.shape[1]
                    new_header['NAXIS2'] = aligned_data.shape[0]
                    
                    # Copy WCS from reference header
                    from lib.fits.wcs import copy_wcs_from_reference
                    new_header = copy_wcs_from_reference(reference_header, new_header)
                    
                    # Add alignment metadata
                    new_header['ALIGNED'] = (True, 'Image has been aligned')
                    new_header['ALIGNREF'] = (os.path.basename(calibrated_paths[0]), 'Reference image for alignment')
                    
                    # Write aligned image
                    hdu = fits.PrimaryHDU(data=aligned_data, header=new_header)
                    hdu.writeto(aligned_path, overwrite=True)
                    path_to_aligned[original_path] = aligned_path
                    self._log(f"    [{i+1}/{len(aligned_datas)}] Saved: {os.path.basename(aligned_path)}")
                
                self._log(f"\n{Fore.GREEN}✓ Aligned {len(path_to_aligned)} images{Style.RESET_ALL}\n")
                
            except Exception as e:
                error_msg = f"Alignment failed: {e}"
                self._log(f"{Fore.RED}✗ {error_msg}{Style.RESET_ALL}\n")
                return {'error': error_msg, 'success': False}
        
        # Step 3: Integrate images per filter
        self._log(f"\n{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}Step 3: Integrating images per filter{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
        
        results = {}
        
        for filter_name, filter_files in files_by_filter.items():
            self._log(f"\n{Style.BRIGHT}Processing filter: {filter_name} ({len(filter_files)} files){Style.RESET_ALL}\n")
            
            try:
                # Get aligned paths for files in this filter
                aligned_paths_for_filter = []
                for file in filter_files:
                    if file in file_to_calibrated:
                        calibrated_path = file_to_calibrated[file]
                        if calibrated_path in path_to_aligned:
                            aligned_paths_for_filter.append(path_to_aligned[calibrated_path])
                
                if not aligned_paths_for_filter:
                    error_msg = f"No aligned images found for filter {filter_name}"
                    self._log(f"{Fore.RED}✗ {error_msg}{Style.RESET_ALL}\n")
                    results[filter_name] = {'error': error_msg, 'success': False}
                    continue
                
                # Integrate images for this filter
                filter_result = self._integrate_filter(filter_name, aligned_paths_for_filter)
                results[filter_name] = filter_result
                
            except Exception as e:
                error_msg = f"Error processing filter {filter_name}: {e}"
                self._log(f"{Style.BRIGHT + Fore.RED}{error_msg}{Style.RESET_ALL}\n")
                results[filter_name] = {'error': error_msg, 'success': False}
        
        # Summary
        self._log(f"\n{Style.BRIGHT + Fore.BLUE}{'='*60}{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.BLUE}Masters Generation Summary{Style.RESET_ALL}")
        self._log(f"{Style.BRIGHT + Fore.BLUE}{'='*60}{Style.RESET_ALL}\n")
        
        successful = sum(1 for r in results.values() if r.get('success', False))
        failed = len(results) - successful
        
        self._log(f"Filters processed: {len(results)}")
        self._log(f"Successful: {successful}")
        self._log(f"Failed: {failed}\n")
        
        return {
            'success': successful > 0,
            'results': results,
            'total_filters': len(results),
            'successful_filters': successful,
            'failed_filters': failed
        }
    
    def _integrate_filter(self, filter_name: str, aligned_paths: list):
        """Integrate aligned images for a single filter."""
        if not aligned_paths:
            return {'error': 'No aligned images for filter', 'success': False}
        
        try:
            # Create output directory
            output_dir = os.path.join(config.PROCESSED_PATH, "integrated", self.target_name)
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate output filename
            safe_filter = filter_name.replace(' ', '_').replace('/', '_')
            output_filename = f"{self.target_name}_{safe_filter}_integrated.fits"
            output_path = os.path.join(output_dir, output_filename)
            
            self._log(f"  Integrating {len(aligned_paths)} images...")
            
            def progress_callback(progress):
                if progress < 1.0:
                    self._log(f"    Progress: {progress*100:.1f}%")
            
            # Integrate images
            integrated_result = integrate_standard(
                files=aligned_paths,
                method='average',
                sigma_clip=False,
                output_path=output_path,
                progress_callback=progress_callback,
                memory_limit=INTEGRATION_MEMORY_LIMIT
            )
            
            self._log(f"  {Fore.GREEN}✓ Integration complete{Style.RESET_ALL}")
            self._log(f"    Output: {output_path}\n")
            
            return {
                'success': True,
                'aligned_count': len(aligned_paths),
                'integrated_path': output_path,
                'filter': filter_name
            }
            
        except Exception as e:
            error_msg = f"Integration failed: {e}"
            self._log(f"  {Fore.RED}✗ {error_msg}{Style.RESET_ALL}\n")
            return {'error': error_msg, 'success': False}
    
    def stop(self):
        """Stop the thread."""
        self._running = False
