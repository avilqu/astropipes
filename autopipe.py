#!/home/tan/dev/astro-pipelines/.venv/bin/python

''' AutoPipe - Automated astronomical image processing pipeline
    Monitors obs/ folder for new FITS files and automatically platesolves them.
    Use --calibrate flag to also calibrate images before platesolving.
    @author: Adrien Vilquin Barrajon <avilqu@gmail.com>
'''

import os
import sys
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading
from queue import Queue, Empty
import signal

# Add the current directory to Python path to import local modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import astro-pipelines modules
from lib.legacy.class_calibrator import Calibrator
from lib.legacy.class_fits_sequence import FITSSequence
import lib.legacy.solver
import config
from colorama import Fore, Style
import warnings
from astropy import wcs
from astropy.utils.exceptions import AstropyUserWarning
import lib.legacy.helpers

# Suppress warnings
warnings.filterwarnings("ignore", category=wcs.FITSFixedWarning)
warnings.filterwarnings("ignore", category=AstropyUserWarning)
logging.disable(sys.maxsize)


class FITSFileHandler(FileSystemEventHandler):
    """Handles new FITS file events."""
    
    def __init__(self, processing_queue, autopipe_path):
        self.processing_queue = processing_queue
        self.autopipe_path = Path(autopipe_path)
        self.processed_files = set()  # Track processed files to avoid duplicates
        
    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.fits'):
            # Check if the file is in the autopipe directory (ignore to prevent loops)
            file_path = Path(event.src_path)
            if self.autopipe_path in file_path.parents:
                print(f"{Style.BRIGHT + Fore.YELLOW}Ignoring file in autopipe directory: {event.src_path}{Style.RESET_ALL}")
                return
                
            # Add to processing queue
            self.processing_queue.put(event.src_path)
            print(f"{Style.BRIGHT + Fore.GREEN}New FITS file detected: {event.src_path}{Style.RESET_ALL}")


class AutoPipeProcessor:
    """Main processor for AutoPipe pipeline."""
    
    def __init__(self, obs_path, autopipe_path, enable_calibration=False):
        self.obs_path = Path(obs_path)
        self.autopipe_path = Path(autopipe_path) if autopipe_path else None
        self.enable_calibration = enable_calibration
        self.calibrator = Calibrator() if enable_calibration else None
        self.processing_queue = Queue()
        self.running = True
        
        # Reset solver interruption flag
        lib.legacy.solver.set_solver_interrupted(False)
        
        # Create autopipe directory if calibration is enabled
        if self.enable_calibration and self.autopipe_path:
            self.autopipe_path.mkdir(parents=True, exist_ok=True)
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
    def signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        print(f"\n{Style.BRIGHT + Fore.YELLOW}Shutdown signal received. Stopping AutoPipe...{Style.RESET_ALL}")
        self.running = False
        # Also signal the solver to stop
        lib.legacy.solver.set_solver_interrupted(True)
        
    def get_relative_path(self, file_path):
        """Get the relative path from obs_path."""
        return Path(file_path).relative_to(self.obs_path)
        
    def create_output_path(self, input_file_path):
        """Create the output path maintaining the original folder structure."""
        relative_path = self.get_relative_path(input_file_path)
        output_dir = self.autopipe_path / relative_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / relative_path.name
        
    def calibrate_file(self, input_file_path):
        """Calibrate a single FITS file."""
        try:
            print(f"{Style.BRIGHT}Calibrating {input_file_path}...{Style.RESET_ALL}")
            
            # Load the FITS file
            seq = FITSSequence([str(input_file_path)])
            
            # Calibrate the image
            image = seq.files[0]
            calibrated_image, new_filename = self.calibrator.calibrate_image(image, write=False)
            
            if calibrated_image is False:
                print(f"{Style.BRIGHT + Fore.RED}Calibration failed for {input_file_path}{Style.RESET_ALL}")
                return None
                
            # Create output path
            output_path = self.create_output_path(input_file_path)
            
            # Write calibrated file
            print(f"{Style.BRIGHT}Writing calibrated file to {output_path}...{Style.RESET_ALL}")
            calibrated_image.write(str(output_path), overwrite=True)
            
            return str(output_path)
            
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error calibrating {input_file_path}: {e}{Style.RESET_ALL}")
            return None
            
    def platesolve_file(self, file_path):
        """Platesolve a FITS file."""
        try:
            print(f"{Style.BRIGHT}Platesolving {file_path}...{Style.RESET_ALL}")
            
            # Setup solver options
            solver_options = type('Options', (), {
                'blind': False,
                'radius': config.SOLVER_SEARCH_RADIUS,
                'downsample': config.SOLVER_DOWNSAMPLE,
                'files': [file_path],
                'ra': None,
                'dec': None
            })()
            
            # Try to get coordinates from file header
            try:
                seq = FITSSequence([file_path])
                header = seq.files[0]['header']
                
                # Use helper function to extract coordinates
                ra_center, dec_center, has_wcs, source = lib.legacy.helpers.extract_coordinates_from_header(header)
                
                if has_wcs:
                    solver_options.ra = ra_center
                    solver_options.dec = dec_center
                    print(f"{Style.BRIGHT + Fore.GREEN}Found coordinates in file header.{Style.RESET_ALL}")
                    print(f"  Source: {source}")
                else:
                    print(f"{Style.BRIGHT + Fore.YELLOW}No coordinates found, using blind solving.{Style.RESET_ALL}")
                    solver_options.blind = True
                    
            except Exception as e:
                print(f"{Style.BRIGHT + Fore.YELLOW}Could not read coordinates from header: {e}{Style.RESET_ALL}")
                solver_options.blind = True
            
            # Run platesolving
            lib.legacy.solver.solve_offline(solver_options)
            
            print(f"{Style.BRIGHT + Fore.GREEN}Platesolving completed for {file_path}{Style.RESET_ALL}")
            return True
            
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error platesolving {file_path}: {e}{Style.RESET_ALL}")
            return False
            
    def process_file(self, file_path):
        """Process a single file through the pipeline."""
        # Check if we should stop processing
        if not self.running:
            return False
            
        try:
            print(f"\n{Style.BRIGHT + Fore.CYAN}Processing {file_path}...{Style.RESET_ALL}")
            
            if self.enable_calibration:
                # Step 1: Calibrate the file
                if not self.running:
                    return False
                calibrated_path = self.calibrate_file(file_path)
                if calibrated_path is None:
                    print(f"{Style.BRIGHT + Fore.RED}Calibration failed, skipping platesolving.{Style.RESET_ALL}")
                    return False
                    
                # Step 2: Platesolve the calibrated file
                if not self.running:
                    return False
                solve_success = self.platesolve_file(calibrated_path)
                
                if solve_success:
                    print(f"{Style.BRIGHT + Fore.GREEN}Successfully processed {file_path}{Style.RESET_ALL}")
                    return True
                else:
                    print(f"{Style.BRIGHT + Fore.YELLOW}Platesolving failed for {file_path}, but calibration was successful.{Style.RESET_ALL}")
                    return True  # Still consider it a success since calibration worked
            else:
                # Platesolve the original file in place
                if not self.running:
                    return False
                solve_success = self.platesolve_file(file_path)
                
                if solve_success:
                    print(f"{Style.BRIGHT + Fore.GREEN}Successfully platesolved {file_path}{Style.RESET_ALL}")
                    return True
                else:
                    print(f"{Style.BRIGHT + Fore.RED}Platesolving failed for {file_path}{Style.RESET_ALL}")
                    return False
                
        except KeyboardInterrupt:
            print(f"{Style.BRIGHT + Fore.YELLOW}Processing interrupted by user.{Style.RESET_ALL}")
            self.running = False
            return False
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error processing {file_path}: {e}{Style.RESET_ALL}")
            return False
            
    def process_queue(self):
        """Process files from the queue."""
        while self.running:
            try:
                # Get file from queue with timeout
                file_path = self.processing_queue.get(timeout=1)
                
                # Check if file is still being written (wait a bit)
                time.sleep(2)
                
                # Check if file exists and is readable
                if os.path.exists(file_path) and os.access(file_path, os.R_OK):
                    # Process the file
                    self.process_file(file_path)
                else:
                    print(f"{Style.BRIGHT + Fore.YELLOW}File {file_path} is not accessible, skipping.{Style.RESET_ALL}")
                    
            except Empty:
                # This is expected when no files are in the queue - just continue
                continue
            except Exception as e:
                if self.running:  # Only log errors if we're still running
                    print(f"{Style.BRIGHT + Fore.RED}Error in queue processing: {e}{Style.RESET_ALL}")
                    
    def start_monitoring(self):
        """Start the file monitoring system."""
        print(f"{Style.BRIGHT + Fore.CYAN}AutoPipe starting...{Style.RESET_ALL}")
        print(f"Monitoring directory: {self.obs_path}")
        if self.enable_calibration:
            print(f"Output directory: {self.autopipe_path}")
            print(f"Mode: Calibration + Platesolving")
        else:
            print(f"Mode: Platesolving only (modifying files in place)")
        print(f"Press Ctrl+C to stop monitoring\n")
        
        # Start the processing thread
        processing_thread = threading.Thread(target=self.process_queue, daemon=True)
        processing_thread.start()
        
        # Setup file system observer
        event_handler = FITSFileHandler(self.processing_queue, self.autopipe_path or self.obs_path / "autopipe")
        observer = Observer()
        observer.schedule(event_handler, str(self.obs_path), recursive=True)
        observer.start()
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n{Style.BRIGHT + Fore.YELLOW}Keyboard interrupt received.{Style.RESET_ALL}")
        finally:
            observer.stop()
            observer.join()
            print(f"{Style.BRIGHT + Fore.GREEN}AutoPipe stopped.{Style.RESET_ALL}")


def main():
    parser = argparse.ArgumentParser(
        description="AutoPipe - Automated astronomical image processing pipeline"
    )
    parser.add_argument(
        "--obs-path",
        default=config.DATA_PATH,
        help=f"Path to the observation directory to monitor (default: {config.DATA_PATH})"
    )
    parser.add_argument(
        "--autopipe-path",
        default=None,
        help="Path for output files when calibration is enabled (default: DATA_PATH/autopipe)"
    )
    parser.add_argument(
        "--calibrate", "-C",
        action="store_true",
        help="Enable calibration before platesolving (creates new files in autopipe directory)"
    )
    parser.add_argument(
        "--process-existing",
        action="store_true",
        help="Process all existing FITS files in the obs directory before starting monitoring"
    )
    
    args = parser.parse_args()
    
    # Set autopipe path if calibration is enabled
    if args.calibrate:
        if args.autopipe_path is None:
            autopipe_path = Path(args.obs_path) / "autopipe"
        else:
            autopipe_path = Path(args.autopipe_path)
    else:
        # When not calibrating, we still need an autopipe path for the file handler
        # to avoid processing files in the autopipe directory
        if args.autopipe_path is None:
            autopipe_path = Path(args.obs_path) / "autopipe"
        else:
            autopipe_path = Path(args.autopipe_path)
    
    # Validate paths
    obs_path = Path(args.obs_path)
    if not obs_path.exists():
        print(f"{Style.BRIGHT + Fore.RED}Error: Observation directory {obs_path} does not exist.{Style.RESET_ALL}")
        sys.exit(1)
        
    # Create processor
    processor = AutoPipeProcessor(obs_path, autopipe_path, enable_calibration=args.calibrate)
    
    # Process existing files if requested
    if args.process_existing:
        print(f"{Style.BRIGHT + Fore.CYAN}Processing existing FITS files...{Style.RESET_ALL}")
        print(f"Press Ctrl+C to stop processing at any time.{Style.RESET_ALL}")
        fits_files = list(obs_path.rglob("*.fits"))
        fits_files.extend(list(obs_path.rglob("*.FITS")))
        
        if fits_files:
            print(f"Found {len(fits_files)} existing FITS files to process.")
            try:
                for i, file_path in enumerate(fits_files, 1):
                    if not processor.running:
                        print(f"\n{Style.BRIGHT + Fore.YELLOW}Processing stopped by user.{Style.RESET_ALL}")
                        break
                        
                    print(f"\n{Style.BRIGHT + Fore.CYAN}Processing file {i}/{len(fits_files)}: {file_path}{Style.RESET_ALL}")
                    processor.process_file(str(file_path))
                    
                    # Small sleep to make the loop more responsive to interrupts
                    time.sleep(0.1)
                    
            except KeyboardInterrupt:
                print(f"\n{Style.BRIGHT + Fore.YELLOW}Processing interrupted by user.{Style.RESET_ALL}")
                processor.running = False
        else:
            print("No existing FITS files found.")
    
    # Start monitoring
    processor.start_monitoring()


if __name__ == "__main__":
    main() 