#!/home/tan/dev/astropipes/.venv/bin/python

""" Main entry for astropipes.
    @author: A. Vilquin Barrajon <avilqu@gmail.com>
"""

import os
import sys

# --- ADD THIS BLOCK IMMEDIATELY AFTER THE ABOVE IMPORTS ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# ----------------------------------------------------------

# Initialize database
from lib.db import get_db_manager
import config
db_manager = get_db_manager(config.DATABASE_PATH)

VIEWER_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), 'lib/gui/viewer/index.py'))

if __name__ == "__main__":
    import argparse
    import sys
    from colorama import Fore, Style
    import warnings
    import logging
    import traceback

    # Silencing warning and info messages
    from astropy import wcs
    from astropy.utils.exceptions import AstropyUserWarning

    warnings.filterwarnings("ignore", category=wcs.FITSFixedWarning)
    warnings.filterwarnings("ignore", category=AstropyUserWarning)
    logging.disable(sys.maxsize)

    parser = argparse.ArgumentParser(
        description="Astronomical Image Processing and Library Management Tool"
    )
    parser.add_argument(
        "-G", "--gui", nargs="?", const="", metavar="FITS_FILE",
        help="open GUI viewer (optionally with a FITS file to load)"
    )
    parser.add_argument(
        "--config", action="store_true", help="print current config"
    )
    parser.add_argument(
        "--scan", action="store_true", help="scan and import image FITS files into database"
    )
    parser.add_argument(
        "--scan-calibration", action="store_true", help="scan and import calibration master FITS files into database"
    )
    parser.add_argument(
        "--scan-all", action="store_true", help="scan and import both image and calibration FITS files into database"
    )
    parser.add_argument(
        "-S", "--solve", nargs="+", metavar="FITS_FILE", 
        help="solve one or more FITS files using astrometry.net"
    )
    parser.add_argument(
        "-C", "--calibrate", nargs="+", metavar="FITS_FILE", 
        help="calibrate one or more FITS files using master bias, dark, and flat"
    )
    parser.add_argument(
        "-A", "--align", nargs="+", metavar="FITS_FILE", 
        help="align multiple FITS files using the first as reference (supports WCS reprojection & astroalign)"
    )
    parser.add_argument(
        "-I", "--integrate", nargs="+", metavar="FITS_FILE", 
        help="integrate multiple FITS files using standard stacking (no motion tracking)"
    )
    parser.add_argument(
        "--integration-method", choices=['average', 'median', 'sum'], default='average',
        help="integration method for stacking (default: average)"
    )
    parser.add_argument(
        "--sigma-clip", action="store_true",
        help="apply sigma clipping during integration to reject outliers"
    )
    parser.add_argument(
        "--get-obs", metavar="OBJECT_DESIGNATION", help="download and display MPC observations for the given asteroid designation"
    )
    parser.add_argument(
        "--get-neocp-obs", metavar="NEOCP_DESIGNATION", help="download and display NEOCP observations for the given object designation"
    )
    parser.add_argument(
        "--get-neocp-objects", action="store_true", help="get the current list of objects on the NEOCP"
    )
    
    args = parser.parse_args()

    def launch_gui():
        """Launch the PyQt6 GUI viewer"""
        try:
            from PyQt6.QtWidgets import QApplication
            from lib.gui.library.index import AstroLibraryGUI
            
            app = QApplication(sys.argv)
            window = AstroLibraryGUI()
            window.show()
            
            # TODO: Load file if provided (will be implemented later)
            # if args.gui and args.gui.strip():
            #     window.load_file_from_path(args.gui.strip())
            
            sys.exit(app.exec())
        except ImportError as e:
            print(f"{Style.BRIGHT + Fore.RED}Error: PyQt6 is required for GUI functionality.{Style.RESET_ALL}")
            print(f"Install with: pip install PyQt6")
            print(f"ImportError details: {e}")
            traceback.print_exc()
            sys.exit(1)
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error launching GUI: {e}{Style.RESET_ALL}")
            traceback.print_exc()
            sys.exit(1)

    def show_config():
        """Display current configuration"""
        import config
        print(f"{Style.BRIGHT + Fore.BLUE}Config:{Style.RESET_ALL}")
        print(f"Calibration Path: {config.CALIBRATION_PATH}")
        print(f"Data Path: {config.DATA_PATH}")
        print(f"Obs Path: {config.OBS_PATH}")

    def scan_library():
        """Scan and import FITS files into the database"""
        try:
            from lib.db import scan_fits_library
            import config
            
            print(f"{Style.BRIGHT + Fore.GREEN}Starting FITS library scan...{Style.RESET_ALL}")
            print(f"Scanning directory: {config.DATA_PATH}")
            print(f"Database: {db_manager.db_path}")
            
            results = scan_fits_library()
            
            print(f"\n{Style.BRIGHT + Fore.GREEN}Scan completed successfully!{Style.RESET_ALL}")
            print(f"Database updated with {results['files_imported']} new files")
            
        except ImportError as e:
            print(f"{Style.BRIGHT + Fore.RED}Error: Required modules not found.{Style.RESET_ALL}")
            print(f"Error details: {e}")
            sys.exit(1)
        except FileNotFoundError as e:
            print(f"{Style.BRIGHT + Fore.RED}Error: {e}{Style.RESET_ALL}")
            sys.exit(1)
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error during scan: {e}{Style.RESET_ALL}")
            sys.exit(1)

    def scan_calibration():
        """Scan and import calibration master FITS files into the database"""
        try:
            from lib.db import scan_calibration_masters
            import config
            print(f"{Style.BRIGHT + Fore.GREEN}Starting calibration master scan...{Style.RESET_ALL}")
            print(f"Scanning calibration directory: {config.CALIBRATION_PATH}")
            print(f"Database: {db_manager.db_path}")
            results = scan_calibration_masters()
            print(f"\n{Style.BRIGHT + Fore.GREEN}Calibration scan completed successfully!{Style.RESET_ALL}")
            print(f"Database updated with {results['files_imported']} new calibration master files")
        except ImportError as e:
            print(f"{Style.BRIGHT + Fore.RED}Error: Required modules not found.{Style.RESET_ALL}")
            print(f"Error details: {e}")
            sys.exit(1)
        except FileNotFoundError as e:
            print(f"{Style.BRIGHT + Fore.RED}Error: {e}{Style.RESET_ALL}")
            sys.exit(1)
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error during calibration scan: {e}{Style.RESET_ALL}")
            sys.exit(1)

    def scan_all():
        """Scan and import both image and calibration master FITS files into the database"""
        print(f"{Style.BRIGHT + Fore.CYAN}Starting full scan (image + calibration)...{Style.RESET_ALL}")
        scan_library()
        print(f"\n{Style.BRIGHT + Fore.CYAN}Proceeding to calibration master scan...{Style.RESET_ALL}")
        scan_calibration()
        print(f"\n{Style.BRIGHT + Fore.CYAN}Full scan completed!{Style.RESET_ALL}")

    def solve_image():
        """Solve one or more FITS images using astrometry.net"""
        try:
            from lib.sci.platesolving import solve_single_image
            import os
            import logging
            
            fits_files = args.solve
            
            # Validate all files first
            valid_files = []
            for fits_file in fits_files:
                # Check if file exists
                if not os.path.exists(fits_file):
                    print(f"{Style.BRIGHT + Fore.RED}Error: File not found: {fits_file}{Style.RESET_ALL}")
                    continue
                
                # Check if file has .fits extension
                if not fits_file.lower().endswith(('.fits', '.fit')):
                    print(f"{Style.BRIGHT + Fore.RED}Error: File must be a FITS file (.fits or .fit extension): {fits_file}{Style.RESET_ALL}")
                    continue
                
                valid_files.append(fits_file)
            
            if not valid_files:
                print(f"{Style.BRIGHT + Fore.RED}No valid FITS files found to solve{Style.RESET_ALL}")
                sys.exit(1)
            
            print(f"{Style.BRIGHT + Fore.BLUE}Starting platesolving for {len(valid_files)} file(s)...{Style.RESET_ALL}")
            
            # Track results
            successful_solves = 0
            failed_solves = 0
            
            # Temporarily enable logging for platesolving
            logging.disable(logging.NOTSET)
            
            # Solve each file
            for i, fits_file in enumerate(valid_files, 1):
                print(f"\n{Style.BRIGHT + Fore.CYAN}[{i}/{len(valid_files)}] Processing: {os.path.basename(fits_file)}{Style.RESET_ALL}")
                
                # Run the platesolving pipeline
                result = solve_single_image(
                    fits_file_path=fits_file,
                    solve_field_path="solve-field",
                    output_dir="/tmp/astropipes/solved",
                    timeout=300,
                    apply_solution=True
                )
                
                if result.success:
                    print(f"{Style.BRIGHT + Fore.GREEN}✓ Platesolving completed successfully!{Style.RESET_ALL}")
                    successful_solves += 1
                else:
                    print(f"{Style.BRIGHT + Fore.RED}✗ Platesolving failed{Style.RESET_ALL}")
                    failed_solves += 1
            
            # Disable logging again after platesolving
            logging.disable(sys.maxsize)
            
            # Print summary
            print(f"\n{Style.BRIGHT + Fore.BLUE}Platesolving Summary:{Style.RESET_ALL}")
            print(f"  Total files processed: {len(valid_files)}")
            print(f"  Successful solves: {Style.BRIGHT + Fore.GREEN}{successful_solves}{Style.RESET_ALL}")
            print(f"  Failed solves: {Style.BRIGHT + Fore.RED}{failed_solves}{Style.RESET_ALL}")
            
            # Exit with error code if any solves failed
            if failed_solves > 0:
                sys.exit(1)
                
        except ImportError as e:
            print(f"{Style.BRIGHT + Fore.RED}Error: Required modules not found.{Style.RESET_ALL}")
            print(f"Error details: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error during platesolving: {e}{Style.RESET_ALL}")
            sys.exit(1)

    def calibrate_image():
        """Calibrate one or more FITS images using master bias, dark, and flat"""
        try:
            from lib.fits.calibration import CalibrationManager
            import os
            
            fits_files = args.calibrate
            
            # Validate all files first
            valid_files = []
            for fits_file in fits_files:
                # Check if file exists
                if not os.path.exists(fits_file):
                    print(f"{Style.BRIGHT + Fore.RED}Error: File not found: {fits_file}{Style.RESET_ALL}")
                    continue
                
                # Check if file has .fits extension
                if not fits_file.lower().endswith(('.fits', '.fit')):
                    print(f"{Style.BRIGHT + Fore.RED}Error: File must be a FITS file (.fits or .fit extension): {fits_file}{Style.RESET_ALL}")
                    continue
                
                valid_files.append(fits_file)
            
            if not valid_files:
                print(f"{Style.BRIGHT + Fore.RED}No valid FITS files found to calibrate{Style.RESET_ALL}")
                sys.exit(1)
            
            print(f"{Style.BRIGHT + Fore.BLUE}Starting calibration for {len(valid_files)} file(s)...{Style.RESET_ALL}")
            
            # Initialize calibration manager
            calib_manager = CalibrationManager()
            
            # Track results
            successful_calibrations = 0
            failed_calibrations = 0
            
            # Calibrate each file
            for i, fits_file in enumerate(valid_files, 1):
                print(f"\n{Style.BRIGHT + Fore.CYAN}[{i}/{len(valid_files)}] Processing: {os.path.basename(fits_file)}{Style.RESET_ALL}")
                
                # Calibrate the file
                result = calib_manager.calibrate_file_simple(fits_file)
                
                if 'error' in result:
                    print(f"{Style.BRIGHT + Fore.RED}Calibration failed: {result['error']}{Style.RESET_ALL}")
                    failed_calibrations += 1
                    continue
                
                if result['success']:
                    print(f"{Style.BRIGHT + Fore.GREEN}✓ Calibration completed successfully!{Style.RESET_ALL}")
                    print(f"  Original file: {result['original_path']}")
                    print(f"  Calibrated file: {result['calibrated_path']}")
                    print(f"  Filename: {result['filename']}")
                    successful_calibrations += 1
                else:
                    print(f"{Style.BRIGHT + Fore.RED}✗ Calibration failed for unknown reason{Style.RESET_ALL}")
                    failed_calibrations += 1
            
            # Print summary
            print(f"\n{Style.BRIGHT + Fore.BLUE}Calibration Summary:{Style.RESET_ALL}")
            print(f"  Total files processed: {len(valid_files)}")
            print(f"  Successful calibrations: {Style.BRIGHT + Fore.GREEN}{successful_calibrations}{Style.RESET_ALL}")
            print(f"  Failed calibrations: {Style.BRIGHT + Fore.RED}{failed_calibrations}{Style.RESET_ALL}")
            
            # Exit with error code if any calibrations failed
            if failed_calibrations > 0:
                sys.exit(1)
                
        except ImportError as e:
            print(f"{Style.BRIGHT + Fore.RED}Error: Required modules not found.{Style.RESET_ALL}")
            print(f"Error details: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error during calibration: {e}{Style.RESET_ALL}")
            sys.exit(1)

    def align_images_cli():
        """Align multiple FITS images using the first as reference with memory protection"""
        try:
            from lib.fits.align import (get_alignment_methods, get_memory_usage, 
                                      check_all_have_wcs, check_pixel_scales_match, 
                                      check_astroalign_available, align_images_chunked)
            from astropy.io import fits
            import os
            import tempfile
            import config
            
            fits_files = args.align
            
            # Validate all files first
            valid_files = []
            for fits_file in fits_files:
                # Check if file exists
                if not os.path.exists(fits_file):
                    print(f"{Style.BRIGHT + Fore.RED}Error: File not found: {fits_file}{Style.RESET_ALL}")
                    continue
                
                # Check if file has .fits extension
                if not fits_file.lower().endswith(('.fits', '.fit')):
                    print(f"{Style.BRIGHT + Fore.RED}Error: File must be a FITS file (.fits or .fit extension): {fits_file}{Style.RESET_ALL}")
                    continue
                
                valid_files.append(fits_file)
            
            if not valid_files:
                print(f"{Style.BRIGHT + Fore.RED}No valid FITS files found to align{Style.RESET_ALL}")
                sys.exit(1)
            
            if len(valid_files) < 2:
                print(f"{Style.BRIGHT + Fore.RED}At least 2 FITS files are required for alignment{Style.RESET_ALL}")
                sys.exit(1)
            
            print(f"{Style.BRIGHT + Fore.BLUE}Starting image alignment for {len(valid_files)} file(s)...{Style.RESET_ALL}")
            print(f"{Style.BRIGHT + Fore.CYAN}Reference image: {os.path.basename(valid_files[0])}{Style.RESET_ALL}")
            
            # Load all images and headers
            print(f"\n{Style.BRIGHT + Fore.CYAN}Loading FITS files...{Style.RESET_ALL}")
            image_datas = []
            headers = []
            total_memory_estimate = 0
            
            for i, fits_file in enumerate(valid_files):
                print(f"  [{i+1}/{len(valid_files)}] Loading: {os.path.basename(fits_file)}")
                try:
                    with fits.open(fits_file) as hdul:
                        img = hdul[0].data
                        hdr = hdul[0].header
                        image_datas.append(img)
                        headers.append(hdr)
                        total_memory_estimate += img.nbytes
                except Exception as e:
                    print(f"{Style.BRIGHT + Fore.RED}Error loading {fits_file}: {e}{Style.RESET_ALL}")
                    sys.exit(1)
            
            # Memory analysis
            current_memory = get_memory_usage()
            estimated_alignment_memory = total_memory_estimate * 2  # Rough estimate for aligned images
            total_estimated_memory = current_memory + (estimated_alignment_memory / (1024 * 1024))
            
            print(f"\n{Style.BRIGHT + Fore.BLUE}Memory Analysis:{Style.RESET_ALL}")
            print(f"  Current memory usage: {current_memory:.1f} MB")
            print(f"  Images to align: {len(image_datas)}")
            print(f"  Total image data size: {total_memory_estimate / (1024*1024):.1f} MB")
            print(f"  Estimated alignment memory: {estimated_alignment_memory / (1024*1024):.1f} MB")
            print(f"  Total estimated memory: {total_estimated_memory:.1f} MB")
            print(f"  Memory limit: {config.ALIGNMENT_MEMORY_LIMIT / (1024*1024):.1f} MB")
            
            # Check memory limits
            if total_estimated_memory > (config.ALIGNMENT_MEMORY_LIMIT / (1024 * 1024)):
                print(f"\n{Style.BRIGHT + Fore.YELLOW}Warning: Estimated memory usage exceeds limit{Style.RESET_ALL}")
                if not config.ALIGNMENT_ENABLE_CHUNKED:
                    print(f"{Style.BRIGHT + Fore.RED}Chunked processing is disabled. Consider enabling it in config.py{Style.RESET_ALL}")
                    sys.exit(1)
                print(f"{Style.BRIGHT + Fore.CYAN}Chunked processing will be used to manage memory{Style.RESET_ALL}")
            
            # Check image count limit
            if len(image_datas) > config.MAX_ALIGNMENT_IMAGES:
                print(f"\n{Style.BRIGHT + Fore.YELLOW}Warning: {len(image_datas)} images exceeds the limit of {config.MAX_ALIGNMENT_IMAGES}{Style.RESET_ALL}")
                reply = input("Continue anyway? (y/N): ").strip().lower()
                if reply not in ['y', 'yes']:
                    print("Alignment cancelled.")
                    return
            
            # Determine alignment method
            available_methods = get_alignment_methods()
            method = config.DEFAULT_ALIGNMENT_METHOD
            
            # Validate method availability
            if method not in available_methods:
                if config.FALLBACK_ALIGNMENT_METHOD in available_methods:
                    print(f"{Style.BRIGHT + Fore.YELLOW}Warning: Default method '{method}' not available. Using fallback '{config.FALLBACK_ALIGNMENT_METHOD}'{Style.RESET_ALL}")
                    method = config.FALLBACK_ALIGNMENT_METHOD
                else:
                    print(f"{Style.BRIGHT + Fore.RED}Error: No alignment methods available{Style.RESET_ALL}")
                    sys.exit(1)
            
            # Method-specific validation
            if method == "wcs_reprojection":
                if not check_all_have_wcs(headers):
                    print(f"{Style.BRIGHT + Fore.RED}Error: One or more images is not platesolved (missing WCS).{Style.RESET_ALL}")
                    print(f"Consider using astroalign method instead or platesolve the images first.")
                    sys.exit(1)
                
                if not check_pixel_scales_match(headers):
                    print(f"{Style.BRIGHT + Fore.RED}Error: Pixel scales do not match between images.{Style.RESET_ALL}")
                    print(f"Consider using astroalign method instead.")
                    sys.exit(1)
            
            elif method == "astroalign":
                if not check_astroalign_available():
                    print(f"{Style.BRIGHT + Fore.RED}Error: astroalign package is not available.{Style.RESET_ALL}")
                    print(f"Install with: pip install astroalign")
                    sys.exit(1)
            
            print(f"\n{Style.BRIGHT + Fore.CYAN}Alignment Method: {method}{Style.RESET_ALL}")
            if method == "astroalign":
                print("  Using fast asterism-based alignment")
            else:
                print("  Using precise WCS reprojection")
            
            # Create output directory
            output_dir = "/tmp/astropipes/aligned"
            os.makedirs(output_dir, exist_ok=True)
            
            # Create unique subdirectory for this alignment session
            temp_dir = tempfile.mkdtemp(dir=output_dir, prefix="")
            print(f"\n{Style.BRIGHT + Fore.CYAN}Output directory: {temp_dir}{Style.RESET_ALL}")
            
            # Progress callback for console output
            def progress_callback(progress):
                percentage = int(progress * 100)
                print(f"\r  Progress: {percentage}%", end="", flush=True)
            
            # Log callback for detailed output
            def log_callback(message):
                print(f"\n  {message}")
            
            # Perform alignment
            print(f"\n{Style.BRIGHT + Fore.CYAN}Starting alignment...{Style.RESET_ALL}")
            try:
                aligned_datas, reference_header = align_images_chunked(
                    image_datas=image_datas,
                    headers=headers,
                    method=method,
                    reference_index=0,
                    chunk_size=config.ALIGNMENT_CHUNK_SIZE,
                    memory_limit=config.ALIGNMENT_MEMORY_LIMIT,
                    progress_callback=progress_callback,
                    log_callback=log_callback
                )
                print(f"\n{Style.BRIGHT + Fore.GREEN}✓ Alignment completed successfully!{Style.RESET_ALL}")
                
            except Exception as e:
                print(f"\n{Style.BRIGHT + Fore.RED}✗ Alignment failed: {e}{Style.RESET_ALL}")
                sys.exit(1)
            
            # Save aligned images
            print(f"\n{Style.BRIGHT + Fore.CYAN}Saving aligned images...{Style.RESET_ALL}")
            new_file_paths = []
            successful_saves = 0
            
            for i, (aligned_data, original_path) in enumerate(zip(aligned_datas, valid_files)):
                try:
                    # Create updated header
                    new_header = headers[i].copy()
                    new_header['NAXIS1'] = aligned_data.shape[1]
                    new_header['NAXIS2'] = aligned_data.shape[0]
                    new_header['ALIGN_MTH'] = method
                    if method == "astroalign":
                        new_header['COMMENT'] = 'Aligned using astroalign asterism matching'
                    else:
                        new_header['COMMENT'] = 'Aligned using WCS reprojection'
                    
                    # Create filename
                    original_filename = os.path.basename(original_path)
                    name, ext = os.path.splitext(original_filename)
                    aligned_filename = f"aligned_{name}{ext}"
                    aligned_path = os.path.join(temp_dir, aligned_filename)
                    
                    # Save aligned image
                    hdu = fits.PrimaryHDU(aligned_data, new_header)
                    hdu.writeto(aligned_path, overwrite=True)
                    
                    new_file_paths.append(aligned_path)
                    successful_saves += 1
                    
                    print(f"  [{i+1}/{len(aligned_datas)}] Saved: {aligned_filename}")
                    
                    # Progressive memory cleanup
                    if config.ALIGNMENT_SAVE_PROGRESSIVE and (i + 1) % 5 == 0:
                        import gc
                        gc.collect()
                        print(f"    Memory cleanup performed")
                
                except Exception as e:
                    print(f"  [{i+1}/{len(aligned_datas)}] Error saving {os.path.basename(original_path)}: {e}")
            
            # Final memory cleanup
            import gc
            gc.collect()
            print(f"\n{Style.BRIGHT + Fore.CYAN}Final memory cleanup completed{Style.RESET_ALL}")
            
            # Print summary
            print(f"\n{Style.BRIGHT + Fore.BLUE}Alignment Summary:{Style.RESET_ALL}")
            print(f"  Total files processed: {len(valid_files)}")
            print(f"  Successful alignments: {Style.BRIGHT + Fore.GREEN}{successful_saves}{Style.RESET_ALL}")
            print(f"  Failed alignments: {Style.BRIGHT + Fore.RED}{len(valid_files) - successful_saves}{Style.RESET_ALL}")
            print(f"  Method used: {method}")
            print(f"  Output directory: {temp_dir}")
            
            if successful_saves == len(valid_files):
                print(f"\n{Style.BRIGHT + Fore.GREEN}All images aligned successfully!{Style.RESET_ALL}")
            else:
                print(f"\n{Style.BRIGHT + Fore.YELLOW}Some images failed to align. Check the output above.{Style.RESET_ALL}")
                sys.exit(1)
                
        except ImportError as e:
            print(f"{Style.BRIGHT + Fore.RED}Error: Required modules not found.{Style.RESET_ALL}")
            print(f"Error details: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error during alignment: {e}{Style.RESET_ALL}")
            sys.exit(1)

    def integrate_images_cli():
        """Integrate multiple FITS images using standard stacking (no motion tracking)."""
        try:
            from lib.fits.integration import integrate_standard
            from lib.fits.align import get_memory_usage
            from astropy.io import fits
            import os
            import tempfile
            import config
            
            fits_files = args.integrate
            
            # Validate all files first
            valid_files = []
            for fits_file in fits_files:
                # Check if file exists
                if not os.path.exists(fits_file):
                    print(f"{Style.BRIGHT + Fore.RED}Error: File not found: {fits_file}{Style.RESET_ALL}")
                    continue
                
                # Check if file has .fits extension
                if not fits_file.lower().endswith(('.fits', '.fit')):
                    print(f"{Style.BRIGHT + Fore.RED}Error: File must be a FITS file (.fits or .fit extension): {fits_file}{Style.RESET_ALL}")
                    continue
                
                valid_files.append(fits_file)
            
            if not valid_files:
                print(f"{Style.BRIGHT + Fore.RED}No valid FITS files found to integrate{Style.RESET_ALL}")
                sys.exit(1)
            
            if len(valid_files) < 2:
                print(f"{Style.BRIGHT + Fore.RED}At least 2 FITS files are required for integration{Style.RESET_ALL}")
                sys.exit(1)
            
            print(f"{Style.BRIGHT + Fore.BLUE}Starting image integration for {len(valid_files)} file(s)...{Style.RESET_ALL}")
            
            # Check image count limit
            if len(valid_files) > config.MAX_INTEGRATION_IMAGES:
                print(f"\n{Style.BRIGHT + Fore.YELLOW}Warning: {len(valid_files)} images exceeds the limit of {config.MAX_INTEGRATION_IMAGES}{Style.RESET_ALL}")
                reply = input("Continue anyway? (y/N): ").strip().lower()
                if reply not in ['y', 'yes']:
                    print("Integration cancelled.")
                    return
            
            # Create output directory
            output_dir = "/tmp/astropipes/integrated"
            os.makedirs(output_dir, exist_ok=True)
            
            # Create unique subdirectory for this integration session
            temp_dir = tempfile.mkdtemp(dir=output_dir, prefix="")
            print(f"\n{Style.BRIGHT + Fore.CYAN}Output directory: {temp_dir}{Style.RESET_ALL}")
            
            # Progress callback for console output
            def progress_callback(progress):
                percentage = int(progress * 100)
                print(f"\r  Progress: {percentage}%", end="", flush=True)
            
            # Perform integration using the standard integration function
            print(f"\n{Style.BRIGHT + Fore.CYAN}Starting integration...{Style.RESET_ALL}")
            try:
                # Use the integrate_standard function from the integration module
                integrated_result = integrate_standard(
                    files=valid_files,
                    method=args.integration_method,  # Use command line method
                    sigma_clip=args.sigma_clip,      # Use command line sigma clip option
                    output_path=None,  # We'll save manually
                    progress_callback=progress_callback,
                    memory_limit=config.INTEGRATION_MEMORY_LIMIT
                )
                print(f"\n{Style.BRIGHT + Fore.GREEN}✓ Integration completed successfully!{Style.RESET_ALL}")
                
            except Exception as e:
                print(f"\n{Style.BRIGHT + Fore.RED}✗ Integration failed: {e}{Style.RESET_ALL}")
                sys.exit(1)
            
            # Save integrated image
            print(f"\n{Style.BRIGHT + Fore.CYAN}Saving integrated image...{Style.RESET_ALL}")
            
            # Generate output filename based on input files
            if len(valid_files) <= 5:
                # For small numbers of files, include their names in the output filename
                base_names = [os.path.splitext(os.path.basename(f))[0] for f in valid_files[:3]]
                if len(valid_files) > 3:
                    base_names.append(f"+{len(valid_files)-3}_more")
                output_filename = f"integrated_{'_'.join(base_names)}.fits"
            else:
                # For many files, use a generic name
                output_filename = f"integrated_{len(valid_files)}_images.fits"
            
            new_file_path = os.path.join(temp_dir, output_filename)
            
            try:
                # Save the integrated result
                integrated_result.write(new_file_path, overwrite=True)
                print(f"  Saved: {output_filename}")
                
            except Exception as e:
                print(f"  Error saving integrated image: {e}")
                sys.exit(1)
            
            # Print summary
            print(f"\n{Style.BRIGHT + Fore.BLUE}Integration Summary:{Style.RESET_ALL}")
            print(f"  Total files processed: {len(valid_files)}")
            print(f"  Method used: Standard Stacking ({args.integration_method})")
            print(f"  Sigma clipping: {'Enabled' if args.sigma_clip else 'Disabled'}")
            print(f"  Output directory: {temp_dir}")
            print(f"  Output file: {output_filename}")
            
            if os.path.exists(new_file_path):
                print(f"\n{Style.BRIGHT + Fore.GREEN}Integrated image saved successfully!{Style.RESET_ALL}")
                print(f"  File size: {os.path.getsize(new_file_path) / (1024*1024):.1f} MB")
            else:
                print(f"\n{Style.BRIGHT + Fore.YELLOW}Integration failed. Check the output above.{Style.RESET_ALL}")
                sys.exit(1)
                
        except ImportError as e:
            print(f"{Style.BRIGHT + Fore.RED}Error: Required modules not found.{Style.RESET_ALL}")
            print(f"Error details: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error during integration: {e}{Style.RESET_ALL}")
            sys.exit(1)

    def get_observations():
        """Download and display MPC observations for a given asteroid designation using mpcq."""
        try:
            from lib.sci.orbit import get_asteroid_observations
            designation = args.get_obs
            print(f"{Style.BRIGHT + Fore.BLUE}Querying MPC observations for: {designation}{Style.RESET_ALL}")
            observations = get_asteroid_observations(designation)
            # Try to display as a table using pandas if possible
            try:
                import pandas as pd
                if hasattr(observations, 'to_pandas'):
                    df = observations.to_pandas()
                elif hasattr(observations, 'to_dataframe'):
                    df = observations.to_dataframe()
                else:
                    df = pd.DataFrame(observations)
                # Select only the specified columns
                columns_to_show = ['trksub', 'provid', 'stn', 'submission._id', 'ra', 'dec', 'mag']
                available_columns = [col for col in columns_to_show if col in df.columns]
                if available_columns:
                    df_filtered = df[available_columns]
                    print(df_filtered.to_string(index=False))
                else:
                    print(f"{Style.BRIGHT + Fore.YELLOW}None of the requested columns found. Available columns: {list(df.columns)}{Style.RESET_ALL}")
                    print(df.to_string(index=False))
            except Exception as e:
                print(f"{Style.BRIGHT + Fore.YELLOW}Could not display as table: {e}{Style.RESET_ALL}")
                print(observations)
        except ImportError as e:
            print(f"{Style.BRIGHT + Fore.RED}Error: mpcq library is required for this feature.{Style.RESET_ALL}")
            print(f"Install with: pip install mpcq")
            print(f"ImportError details: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error fetching observations: {e}{Style.RESET_ALL}")
            sys.exit(1)

    def get_neocp_observations():
        """Download and display NEOCP observations for a given object designation."""
        try:
            from lib.sci.orbit import get_neocp_observations
            designation = args.get_neocp_obs
            print(f"{Style.BRIGHT + Fore.BLUE}Querying NEOCP observations for: {designation}{Style.RESET_ALL}")
            observations = get_neocp_observations(designation)
            
            if not observations:
                print(f"{Fore.YELLOW}No observations found for {designation}{Style.RESET_ALL}")
                return
            
            print(f"{Style.BRIGHT}Found {len(observations)} observations:{Style.RESET_ALL}")
            print()
            
            # Display each observation line
            for i, obs in enumerate(observations, 1):
                print(f"{Fore.CYAN}{i:3d}.{Style.RESET_ALL} {obs}")
            
            print()
            print(f"{Style.BRIGHT}Total: {len(observations)} observations{Style.RESET_ALL}")
            
        except ImportError:
            print(f"{Fore.RED}Error: Could not import orbit module{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Error fetching NEOCP observations: {e}{Style.RESET_ALL}")

    def get_neocp_objects():
        """Get and display the current list of objects on the NEOCP."""
        try:
            from lib.sci.orbit import get_neocp_objects
            print(f"{Style.BRIGHT + Fore.BLUE}Querying current NEOCP objects...{Style.RESET_ALL}")
            objects = get_neocp_objects()
            # Try to display as a table using pandas if possible
            try:
                import pandas as pd
                df = pd.DataFrame(objects)
                if not df.empty:
                    # Select key columns for NEOCP objects
                    columns_to_show = ['packed', 'priority', 'score', 'vmag', 'ra', 'dec', 'uncert', 'status', 'neocp']
                    available_columns = [col for col in columns_to_show if col in df.columns]
                    if available_columns:
                        df_filtered = df[available_columns]
                        print(df_filtered.to_string(index=False))
                    else:
                        print(f"{Style.BRIGHT + Fore.YELLOW}None of the requested columns found. Available columns: {list(df.columns)}{Style.RESET_ALL}")
                        print(df.to_string(index=False))
                else:
                    print(f"{Style.BRIGHT + Fore.YELLOW}No NEOCP objects found{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Style.BRIGHT + Fore.YELLOW}Could not display as table: {e}{Style.RESET_ALL}")
                print(objects)
        except ImportError as e:
            print(f"{Style.BRIGHT + Fore.RED}Error: requests library is required for this feature.{Style.RESET_ALL}")
            print(f"Install with: pip install requests")
            print(f"ImportError details: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error fetching NEOCP objects: {e}{Style.RESET_ALL}")
            sys.exit(1)

    # Handle arguments
    if args.gui is not None:
        launch_gui()
    elif args.config:
        show_config()
    elif args.scan:
        scan_library()
    elif args.scan_calibration:
        scan_calibration()
    elif args.scan_all:
        scan_all()
    elif args.solve:
        solve_image()
    elif args.calibrate:
        calibrate_image()
    elif args.align:
        align_images_cli()
    elif args.integrate:
        integrate_images_cli()
    elif args.get_obs:
        get_observations()
    elif args.get_neocp_obs:
        get_neocp_observations()
    elif args.get_neocp_objects:
        get_neocp_objects()
    else:
        # Default behavior: show help
        parser.print_help()