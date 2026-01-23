import requests
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astropy import units as u
from astropy.wcs import WCS
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Tuple, Union
import logging
import os
import time
from pathlib import Path
import subprocess
from subprocess import run, TimeoutExpired
import shutil
from colorama import Style, Fore

# Import catalog classes from new location
from lib.sci.catalogs import SolarSystemObject, SIMBADObject, GaiaObject, AstrometryCatalog

# Import our FITS utilities
from lib.fits.wcs import (
    validate_fits_file, 
    ImageValidationResult, 
    get_platesolving_constraints,
    extract_wcs_from_file,
    apply_wcs_to_fits,
    WCSExtractionError,
    WCSApplicationError
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Disable all logging to avoid INFO: output
logging.disable(logging.CRITICAL)


class PlatesolvingError(Exception):
    """Exception raised when platesolving fails."""
    pass


class PlatesolvingResult:
    """Result of a platesolving operation."""
    
    def __init__(self, success: bool, message: str = "", 
                 wcs_file_path: Optional[str] = None,
                 ra_center: Optional[float] = None,
                 dec_center: Optional[float] = None,
                 pixel_scale: Optional[float] = None,
                 orientation: Optional[float] = None,
                 radius: Optional[float] = None):
        self.success = success
        self.message = message
        self.wcs_file_path = wcs_file_path
        self.ra_center = ra_center
        self.dec_center = dec_center
        self.pixel_scale = pixel_scale
        self.orientation = orientation
        self.radius = radius
    
    def __str__(self):
        status = "SUCCESS" if self.success else "FAILED"
        result = f"{status}: {self.message}"
        if self.success and self.ra_center is not None and self.dec_center is not None:
            try:
                ra_center = float(self.ra_center)
                dec_center = float(self.dec_center)
                result += f" (RA={ra_center:.4f}°, Dec={dec_center:.4f}°)"
            except (ValueError, TypeError):
                # Skip formatting if values can't be converted to float
                result += f" (RA={self.ra_center}, Dec={self.dec_center})"
        return result


class AstrometryEngine:
    """Interface to the astrometry.net solve-field engine."""
    
    def __init__(self, solve_field_path: str = "solve-field", 
                 output_dir: str = "/tmp/astropipes/solved", timeout: int = 300):
        """
        Initialize the astrometry engine interface.
        
        Parameters:
        -----------
        solve_field_path : str
            Path to the solve-field executable
        output_dir : str
            Directory for temporary output files
        timeout : int
            Timeout in seconds for solve-field execution
        """
        self.solve_field_path = solve_field_path
        self.output_dir = output_dir
        self.timeout = timeout
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
    
    def solve_image(self, fits_file_path: str, constraints: Dict[str, Union[float, bool]], output_callback=None, process_callback=None) -> PlatesolvingResult:
        """
        Solve a single image using the astrometry.net engine.
        
        Parameters:
        -----------
        fits_file_path : str
            Path to the FITS file to solve
        constraints : Dict[str, Union[float, bool]]
            Solving constraints from get_platesolving_constraints()
            
        Returns:
        --------
        PlatesolvingResult
            Result of the solving operation
        """
        try:
            # Generate output filenames
            base_name = Path(fits_file_path).stem
            new_filename = os.path.join(self.output_dir, f"{base_name}.new")
            
            # Build solve-field command
            cmd = [
                self.solve_field_path,
                "--dir", self.output_dir,
                "--no-plots",
                "--no-verify",
                "--overwrite",
                "--downsample", "2",
                # "-t", "3",
                "--new-fits", new_filename,
                fits_file_path
            ]
            
            # Add constraints if not blind solving
            if not constraints.get('blind', True):
                if constraints.get('ra') is not None:
                    cmd.extend(["--ra", str(constraints['ra'])])
                if constraints.get('dec') is not None:
                    cmd.extend(["--dec", str(constraints['dec'])])
                if constraints.get('radius') is not None:
                    cmd.extend(["--radius", str(constraints['radius'])])
                # Note: solve-field doesn't use scale constraints for offline solving
                # Scale constraints are only used for online astrometry.net
            else:
                # Blind solving - add guess-scale option
                cmd.append("--guess-scale")
            
            # Debug: Show the exact command being executed
            if output_callback:
                output_callback(f"   Command: {' '.join(cmd)}\n")
            else:
                print(f"   Command: {' '.join(cmd)}")
            
            # Run solve-field with live output
            start_time = time.time()
            if output_callback:
                output_callback(f"{Style.BRIGHT + Fore.BLUE}Running solve-field...{Style.RESET_ALL}\n")
            else:
                print(f"{Style.BRIGHT + Fore.BLUE}Running solve-field...{Style.RESET_ALL}")
            
            # Run solve-field and capture output in real-time
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                bufsize=1, 
                universal_newlines=True
            )
            if process_callback:
                process_callback(process)
            
            # Read output in real-time
            for line in process.stdout:
                if output_callback:
                    output_callback(line)
                else:
                    print(line, end='')
            
            # Wait for process to complete
            # Use wait() instead of poll() to ensure we get a real return code
            return_code = process.wait()
            solve_time = time.time() - start_time
            
            if return_code != 0:
                # Ensure returncode is not None (wait() should always return a code, but be safe)
                safe_return_code = return_code if return_code is not None else -1
                raise subprocess.CalledProcessError(safe_return_code, cmd)
            
            # Check if .new file was created
            if os.path.exists(new_filename):
                if output_callback:
                    output_callback(f"   Solution file generated: {new_filename}\n")
                else:
                    print(f"   Solution file generated: {new_filename}")
                
                # Extract solution information
                solution_info = self._extract_solution_info(new_filename, fits_file_path)
                
                # Don't clean up yet - the file is needed for WCS application
                # Cleanup will be done after WCS application in solve_single_image
                
                return PlatesolvingResult(
                    success=True,
                    message="Image successfully solved",
                    wcs_file_path=new_filename,
                    ra_center=solution_info.get('ra_center'),
                    dec_center=solution_info.get('dec_center'),
                    pixel_scale=solution_info.get('pixel_scale'),
                    orientation=solution_info.get('orientation'),
                    radius=solution_info.get('radius')
                )
            else:
                if output_callback:
                    output_callback(f"   No solution file generated by solve-field\n")
                else:
                    print(f"   No solution file generated by solve-field")
                self._cleanup_temp_files(base_name)
                return PlatesolvingResult(
                    success=False,
                    message="No WCS solution generated"
                )
                
        except TimeoutExpired:
            logger.error(f"solve-field timed out after {self.timeout}s")
            self._cleanup_temp_files(Path(fits_file_path).stem)
            return PlatesolvingResult(
                success=False,
                message=f"solve-field timed out after {self.timeout}s"
            )
        except subprocess.CalledProcessError as e:
            # Handle CalledProcessError specially to avoid formatting issues with None returncode
            if e.returncode is not None:
                error_msg = f"Command '{' '.join(cmd)}' returned non-zero exit status {e.returncode}"
            else:
                error_msg = f"Command '{' '.join(cmd)}' failed with unknown exit status"
            logger.error(f"Error running solve-field: {error_msg}")
            self._cleanup_temp_files(Path(fits_file_path).stem)
            return PlatesolvingResult(
                success=False,
                message=f"Error running solve-field: {error_msg}"
            )
        except Exception as e:
            # Safely format exception message to avoid formatting errors
            # (subprocess.CalledProcessError.__str__ uses % formatting which can fail if returncode is None)
            try:
                error_msg = str(e)
            except Exception as format_error:
                error_msg = f"Exception of type {type(e).__name__} (could not format: {type(format_error).__name__})"
            
            logger.error(f"Error running solve-field: {error_msg}")
            self._cleanup_temp_files(Path(fits_file_path).stem)
            return PlatesolvingResult(
                success=False,
                message=f"Error running solve-field: {error_msg}"
            )
    
    def _extract_solution_info(self, solution_file_path: str, original_file_path: str) -> Dict[str, Union[float, int]]:
        """
        Extract solution information from the solution file.
        
        Parameters:
        -----------
        solution_file_path : str
            Path to the generated solution file (.new)
        original_file_path : str
            Path to the original FITS file
            
        Returns:
        --------
        Dict[str, Union[float, int]]
            Dictionary containing solution information
        """
        try:
            from astropy.io import fits
            
            # Extract WCS data from the solution file
            wcs_data = extract_wcs_from_file(solution_file_path)
            print(f"[DEBUG] WCS header extracted: {wcs_data}")  # Debug print
            
            # Create WCS object for calculations
            wcs = WCS(solution_file_path)
            
            # Get image dimensions from original file
            with fits.open(original_file_path) as hdul:
                image_shape = hdul[0].data.shape
            
            # Calculate center coordinates
            center_x = image_shape[1] / 2
            center_y = image_shape[0] / 2
            center_coords = wcs.pixel_to_world(center_x, center_y)
            
            # Calculate pixel scale: prefer SCALE, then CDELT1, then compute from CD matrix
            pixel_scale = None
            if 'SCALE' in wcs_data:
                pixel_scale = float(wcs_data['SCALE'])
            elif 'CDELT1' in wcs_data:
                pixel_scale = abs(float(wcs_data['CDELT1'])) * 3600.0  # Convert to arcsec
            elif 'CD1_1' in wcs_data and 'CD2_2' in wcs_data:
                # Compute pixel scale from CD matrix (arcsec/pixel)
                cd11 = float(wcs_data['CD1_1'])
                cd12 = float(wcs_data.get('CD1_2', 0.0))
                cd21 = float(wcs_data.get('CD2_1', 0.0))
                cd22 = float(wcs_data['CD2_2'])
                # Pixel scale is sqrt of determinant, convert deg to arcsec
                scale_x = np.sqrt(cd11**2 + cd21**2) * 3600.0
                scale_y = np.sqrt(cd12**2 + cd22**2) * 3600.0
                pixel_scale = (scale_x + scale_y) / 2.0
            
            # Calculate orientation
            orientation = None
            if 'CROTA2' in wcs_data:
                orientation = float(wcs_data['CROTA2'])
            
            # Calculate field radius
            corners = wcs.calc_footprint()
            radius = None
            if corners is not None:
                ra_center = center_coords.ra.deg
                dec_center = center_coords.dec.deg
                max_radius = 0
                for corner_ra, corner_dec in corners:
                    dra = (corner_ra - ra_center) * np.cos(np.radians(dec_center))
                    ddec = corner_dec - dec_center
                    corner_radius = np.sqrt(dra**2 + ddec**2)
                    max_radius = max(max_radius, corner_radius)
                radius = max_radius
            
            return {
                'ra_center': center_coords.ra.deg,
                'dec_center': center_coords.dec.deg,
                'pixel_scale': pixel_scale,
                'orientation': orientation,
                'radius': radius,
            }
            
        except Exception as e:
            # Safely format exception message to avoid formatting errors
            try:
                error_msg = str(e)
            except Exception:
                error_msg = f"Exception of type {type(e).__name__}"
            print(f"   Error extracting solution info: {error_msg}")
            return {}
    
    def _cleanup_temp_files(self, base_name: str):
        """
        Clean up temporary files generated by solve-field.
        
        Parameters:
        -----------
        base_name : str
            Base name of the input file (without extension)
        """
        temp_extensions = ['.xyls', '.axy', '.corr', '.match', '.rdls', '.solved', '.new']
        
        for ext in temp_extensions:
            temp_file = os.path.join(self.output_dir, f"{base_name}{ext}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    logger.debug(f"Cleaned up: {temp_file}")
                except Exception as e:
                    logger.warning(f"Could not remove {temp_file}: {e}")


def solve_single_image(fits_file_path: str, 
                      solve_field_path: str = "solve-field",
                      output_dir: str = "/tmp/astropipes/solved",
                      timeout: int = 300,
                      apply_solution: bool = True,
                      output_callback=None,
                      process_callback=None) -> PlatesolvingResult:
    """
    Solve a single FITS image using the complete platesolving pipeline.
    
    This function performs the complete platesolving workflow:
    1. Validate the FITS file
    2. Extract existing WCS information
    3. Generate solving constraints
    4. Run astrometry.net engine
    5. Apply solution to original file (if requested)
    
    Parameters:
    -----------
    fits_file_path : str
        Path to the FITS file to solve
    solve_field_path : str
        Path to the solve-field executable
    output_dir : str
        Directory for temporary output files
    timeout : int
        Timeout in seconds for solve-field execution
    apply_solution : bool
        Whether to apply the solution to the original FITS file
        
    Returns:
    --------
    PlatesolvingResult
        Result of the platesolving operation
    """
    try:
        # Step 1: Validate the FITS file
        if output_callback:
            output_callback(f"{Style.BRIGHT + Fore.BLUE}Validating FITS file...{Style.RESET_ALL}\n")
        else:
            print(f"{Style.BRIGHT + Fore.BLUE}Validating FITS file...{Style.RESET_ALL}")
        validation_result = validate_fits_file(fits_file_path)
        
        if not validation_result.is_valid:
            # Print error message in bold red
            if output_callback:
                output_callback(f"{Style.BRIGHT + Fore.RED}Image validation failed: {validation_result.reason}{Style.RESET_ALL}\n")
            else:
                print(f"{Style.BRIGHT + Fore.RED}Image validation failed: {validation_result.reason}{Style.RESET_ALL}")
            return PlatesolvingResult(
                success=False,
                message=f"Image validation failed: {validation_result.reason}"
            )
        
        if output_callback:
            output_callback(f"{Style.BRIGHT + Fore.GREEN}Image validation passed{Style.RESET_ALL}\n")
        else:
            print(f"{Style.BRIGHT + Fore.GREEN}Image validation passed{Style.RESET_ALL}")
        
        # Step 2: Extract existing WCS information and generate constraints
        if output_callback:
            output_callback(f"{Style.BRIGHT + Fore.BLUE}Generating solving constraints...{Style.RESET_ALL}\n")
        else:
            print(f"{Style.BRIGHT + Fore.BLUE}Generating solving constraints...{Style.RESET_ALL}")
        constraints = get_platesolving_constraints(validation_result)
        
        # Step 3: Run astrometry.net engine
        if output_callback:
            output_callback(f"{Style.BRIGHT + Fore.BLUE}Running astrometry.net engine...{Style.RESET_ALL}\n")
        else:
            print(f"{Style.BRIGHT + Fore.BLUE}Running astrometry.net engine...{Style.RESET_ALL}")
        engine = AstrometryEngine(solve_field_path, output_dir, timeout)
        solve_result = engine.solve_image(fits_file_path, constraints, output_callback, process_callback)
        
        if not solve_result.success:
            # Print error message in bold red
            if output_callback:
                output_callback(f"{Style.BRIGHT + Fore.RED}Could not solve {fits_file_path}{Style.RESET_ALL}\n")
            else:
                print(f"{Style.BRIGHT + Fore.RED}Could not solve {fits_file_path}{Style.RESET_ALL}")
            return solve_result
        
        # Step 4: Apply solution to original file (if requested)
        if apply_solution and solve_result.wcs_file_path:
            if output_callback:
                output_callback(f"{Style.BRIGHT + Fore.BLUE}Applying solution to original file...{Style.RESET_ALL}\n")
            else:
                print(f"{Style.BRIGHT + Fore.BLUE}Applying solution to original file...{Style.RESET_ALL}")
            try:
                wcs_data = extract_wcs_from_file(solve_result.wcs_file_path)
                apply_wcs_to_fits(fits_file_path, wcs_data, backup_original=False)
                if output_callback:
                    output_callback(f"   Successfully applied WCS solution to {fits_file_path}\n")
                else:
                    print(f"   Successfully applied WCS solution to {fits_file_path}")
                
                # Clean up the solution file after applying
                os.remove(solve_result.wcs_file_path)
                solve_result.wcs_file_path = None
                
            except (WCSExtractionError, WCSApplicationError) as e:
                if output_callback:
                    output_callback(f"{Style.BRIGHT + Fore.RED}Error applying WCS solution: {e}{Style.RESET_ALL}\n")
                else:
                    print(f"{Style.BRIGHT + Fore.RED}Error applying WCS solution: {e}{Style.RESET_ALL}")
                return PlatesolvingResult(
                    success=False,
                    message=f"Error applying WCS solution: {e}"
                )
        
        # Clean up any remaining temporary files
        base_name = Path(fits_file_path).stem
        engine._cleanup_temp_files(base_name)
        
        # Print success message in bold green
        if output_callback:
            output_callback(f"{Style.BRIGHT + Fore.GREEN}Successfully solved {fits_file_path}{Style.RESET_ALL}\n")
        else:
            print(f"{Style.BRIGHT + Fore.GREEN}Successfully solved {fits_file_path}{Style.RESET_ALL}")
        if solve_result.ra_center is not None and solve_result.dec_center is not None:
            try:
                ra_center = float(solve_result.ra_center)
                dec_center = float(solve_result.dec_center)
                if output_callback:
                    output_callback(f"{Style.BRIGHT + Fore.GREEN}   Center: RA={ra_center:.4f}°, Dec={dec_center:.4f}°{Style.RESET_ALL}\n")
                else:
                    print(f"{Style.BRIGHT + Fore.GREEN}   Center: RA={ra_center:.4f}°, Dec={dec_center:.4f}°{Style.RESET_ALL}")
            except (ValueError, TypeError):
                # Skip formatting if values can't be converted to float
                if output_callback:
                    output_callback(f"{Style.BRIGHT + Fore.GREEN}   Center: RA={solve_result.ra_center}, Dec={solve_result.dec_center}{Style.RESET_ALL}\n")
                else:
                    print(f"{Style.BRIGHT + Fore.GREEN}   Center: RA={solve_result.ra_center}, Dec={solve_result.dec_center}{Style.RESET_ALL}")
        if solve_result.pixel_scale is not None:
            try:
                pixel_scale = float(solve_result.pixel_scale)
                if output_callback:
                    output_callback(f"{Style.BRIGHT + Fore.GREEN}   Pixel scale: {pixel_scale:.3f} arcsec/pixel{Style.RESET_ALL}\n")
                else:
                    print(f"{Style.BRIGHT + Fore.GREEN}   Pixel scale: {pixel_scale:.3f} arcsec/pixel{Style.RESET_ALL}")
            except (ValueError, TypeError):
                # Skip formatting if value can't be converted to float
                if output_callback:
                    output_callback(f"{Style.BRIGHT + Fore.GREEN}   Pixel scale: {solve_result.pixel_scale} arcsec/pixel{Style.RESET_ALL}\n")
                else:
                    print(f"{Style.BRIGHT + Fore.GREEN}   Pixel scale: {solve_result.pixel_scale} arcsec/pixel{Style.RESET_ALL}")
        
        # Check if file is in database and update if needed
        if output_callback:
            output_callback(f"{Style.BRIGHT + Fore.BLUE}Checking database status...{Style.RESET_ALL}\n")
        else:
            print(f"{Style.BRIGHT + Fore.BLUE}Checking database status...{Style.RESET_ALL}")
        try:
            from lib.db.scan import is_file_in_database, get_file_database_info, rescan_single_file
            
            if is_file_in_database(fits_file_path):
                db_info = get_file_database_info(fits_file_path)
                if db_info:
                    db_id = db_info.get('id', 'Unknown')
                    if output_callback:
                        output_callback(f"   File is present in database ({db_info['table']} table, ID: {db_id})\n")
                    else:
                        print(f"   File is present in database ({db_info['table']} table, ID: {db_id})")
                    
                    # Re-scan the file to update database with new WCS information
                    if output_callback:
                        output_callback(f"Updating database entry...\n")
                    else:
                        print(f"Updating database entry...")
                    rescan_result = rescan_single_file(fits_file_path)
                    
                    if rescan_result['success']:
                        if output_callback:
                            output_callback(f"   Successfully updated database entry\n")
                        else:
                            print(f"   Successfully updated database entry")
                        updated_fields = rescan_result.get('updated_fields', {})
                        if 'wcs_type' in updated_fields and updated_fields['wcs_type'] == 'celestial':
                            if output_callback:
                                output_callback(f"   WCS type: {updated_fields['wcs_type']}\n")
                            else:
                                print(f"   WCS type: {updated_fields['wcs_type']}")
                        if 'image_scale' in updated_fields and updated_fields['image_scale'] is not None:
                            try:
                                image_scale = float(updated_fields['image_scale'])
                                if output_callback:
                                    output_callback(f"   Pixel scale: {image_scale:.3f} arcsec/pixel\n")
                                else:
                                    print(f"   Pixel scale: {image_scale:.3f} arcsec/pixel")
                            except (ValueError, TypeError):
                                # Skip formatting if value can't be converted to float
                                if output_callback:
                                    output_callback(f"   Pixel scale: {updated_fields['image_scale']} arcsec/pixel\n")
                                else:
                                    print(f"   Pixel scale: {updated_fields['image_scale']} arcsec/pixel")
                        if 'ra_center' in updated_fields and updated_fields['ra_center'] is not None and 'dec_center' in updated_fields and updated_fields['dec_center'] is not None:
                            try:
                                ra_center = float(updated_fields['ra_center'])
                                dec_center = float(updated_fields['dec_center'])
                                if output_callback:
                                    output_callback(f"   Center: RA={ra_center:.4f}°, Dec={dec_center:.4f}°\n")
                                else:
                                    print(f"   Center: RA={ra_center:.4f}°, Dec={dec_center:.4f}°")
                            except (ValueError, TypeError):
                                # Skip formatting if values can't be converted to float
                                if output_callback:
                                    output_callback(f"   Center: RA={updated_fields['ra_center']}, Dec={updated_fields['dec_center']}\n")
                                else:
                                    print(f"   Center: RA={updated_fields['ra_center']}, Dec={updated_fields['dec_center']}")
                    else:
                        if output_callback:
                            output_callback(f"   Error updating database: {rescan_result['message']}\n")
                        else:
                            print(f"   Error updating database: {rescan_result['message']}")
                else:
                    if output_callback:
                        output_callback(f"   File is not present in database\n")
                    else:
                        print(f"   File is not present in database")
            else:
                if output_callback:
                    output_callback(f"   File is not present in database\n")
                else:
                    print(f"   File is not present in database")
                
        except Exception as e:
            if output_callback:
                output_callback(f"   Error checking/updating database: {e}\n")
            else:
                print(f"   Error checking/updating database: {e}")
        
        return solve_result
        
    except Exception as e:
        # Safely format exception message to avoid formatting errors
        import traceback
        try:
            error_msg = str(e)
        except Exception as format_error:
            # If even str(e) fails, use a safe fallback
            error_msg = f"Exception of type {type(e).__name__} (could not format: {type(format_error).__name__})"
        
        # Get traceback for debugging
        try:
            tb_str = traceback.format_exc()
            # Only show last few lines to avoid clutter
            tb_lines = tb_str.strip().split('\n')
            if len(tb_lines) > 10:
                tb_str = '\n'.join(tb_lines[-10:])
        except Exception:
            tb_str = "Could not get traceback"
        
        if output_callback:
            output_callback(f"{Style.BRIGHT + Fore.RED}Error in platesolving pipeline: {error_msg}{Style.RESET_ALL}\n")
            output_callback(f"{Style.BRIGHT + Fore.YELLOW}Traceback (last 10 lines):{Style.RESET_ALL}\n{tb_str}\n")
        else:
            print(f"{Style.BRIGHT + Fore.RED}Error in platesolving pipeline: {error_msg}{Style.RESET_ALL}")
            print(f"{Style.BRIGHT + Fore.YELLOW}Traceback (last 10 lines):{Style.RESET_ALL}\n{tb_str}")
        return PlatesolvingResult(
            success=False,
            message=f"Error in platesolving pipeline: {error_msg}"
        ) 