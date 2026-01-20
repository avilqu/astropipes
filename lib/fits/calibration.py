"""
Calibration module for astro-pipelines.
Handles finding and applying calibration masters to FITS files.
"""

import os
import tempfile
import shutil
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from sqlalchemy import and_, or_, func
from colorama import Fore, Style

from astropy import units as u
import ccdproc as ccdp
from astropy.nddata import CCDData
from astropy.io import fits

from lib.db.manager import get_db_manager
from lib.db.models import CalibrationMaster, FitsFile
import config


class CalibrationManager:
    """Manages calibration operations for FITS files."""
    
    def __init__(self):
        """Initialize the calibration manager."""
        self.db_manager = get_db_manager()
    
    def find_master_bias(self, fits_file: FitsFile) -> Optional[CalibrationMaster]:
        """
        Find the most suitable master bias for a given FITS file.
        
        For bias frames, we match on binning, filter, gain, offset, and CCD temperature,
        and choose the nearest PREVIOUS available bias (not future dates).
        Optionally applies age constraint based on MAX_BIAS_AGE config.
        
        Args:
            fits_file: The FitsFile object to find calibration for
            
        Returns:
            CalibrationMaster object if found, None otherwise
        """
        session = self.db_manager.get_session()
        try:
            # Get tolerance values from config
            ccd_temp_tolerance = 2  # From config.TESTED_FITS_CARDS
            
            # Build base query constraints
            # Note: Bias frames should NOT be filtered by astronomical filter
            # since bias is independent of the filter used
            constraints = [
                CalibrationMaster.frame == 'Bias',
                CalibrationMaster.binning == fits_file.binning,
                CalibrationMaster.gain == fits_file.gain,
                CalibrationMaster.offset == fits_file.offset,
                CalibrationMaster.ccd_temp.between(
                    fits_file.ccd_temp - ccd_temp_tolerance,
                    fits_file.ccd_temp + ccd_temp_tolerance
                )
            ]
            
            # Apply age constraint if MAX_BIAS_AGE > 0, otherwise no date constraint
            age_constraint_msg = ""
            if config.MAX_BIAS_AGE > 0:
                oldest_allowed_date = fits_file.date_obs - timedelta(days=config.MAX_BIAS_AGE)
                constraints.append(CalibrationMaster.date >= oldest_allowed_date.strftime('%Y-%m-%d'))
                age_constraint_msg = f", age <= {config.MAX_BIAS_AGE} days"
            
            # Get all bias masters that match the constraints
            query = session.query(CalibrationMaster).filter(and_(*constraints)).order_by(CalibrationMaster.date.desc())
            
            masters = query.all()
            
            if not masters:
                print(f"{Style.BRIGHT + Fore.RED}Could not find a suitable master bias.{Style.RESET_ALL}")
                print(f"  Required: binning={fits_file.binning}")
                print(f"  Gain={fits_file.gain}, offset={fits_file.offset}, ccd_temp={fits_file.ccd_temp}±{ccd_temp_tolerance}°C")
                if age_constraint_msg:
                    print(f"  Date constraint: >= {(fits_file.date_obs - timedelta(days=config.MAX_BIAS_AGE)).strftime('%Y-%m-%d')}{age_constraint_msg}")
                return None
            
            # Return the most recent one (closest previous date)
            selected_master = masters[0]
            print(f"Selected master bias: {selected_master.path}")
            print(f"  Date: {selected_master.date}, Binning: {selected_master.binning}, Filter: {selected_master.filter_name}")
            print(f"  Gain: {selected_master.gain}, Offset: {selected_master.offset}, Temp: {selected_master.ccd_temp}°C")
            
            return selected_master
            
        finally:
            session.close()
    
    def find_master_dark(self, fits_file: FitsFile) -> Optional[CalibrationMaster]:
        """
        Find the most suitable master dark for a given FITS file.
        
        For dark frames, we match on binning, gain, offset, and CCD temperature,
        and require exposure time >= the target file. If multiple options exist,
        choose the one with closest date_obs.
        Optionally applies age constraint based on MAX_DARK_AGE config.
        
        Args:
            fits_file: The FitsFile object to find calibration for
            
        Returns:
            CalibrationMaster object if found, None otherwise
        """
        session = self.db_manager.get_session()
        try:
            # Get tolerance values from config
            ccd_temp_tolerance = 2  # From config.TESTED_FITS_CARDS
            
            # Build base query constraints
            constraints = [
                CalibrationMaster.frame == 'Dark',
                CalibrationMaster.binning == fits_file.binning,
                CalibrationMaster.gain == fits_file.gain,
                CalibrationMaster.offset == fits_file.offset,
                CalibrationMaster.ccd_temp.between(
                    fits_file.ccd_temp - ccd_temp_tolerance,
                    fits_file.ccd_temp + ccd_temp_tolerance
                ),
                CalibrationMaster.exptime >= fits_file.exptime
            ]
            
            # Apply age constraint if MAX_DARK_AGE > 0
            age_constraint_msg = ""
            if config.MAX_DARK_AGE > 0:
                oldest_allowed_date = fits_file.date_obs - timedelta(days=config.MAX_DARK_AGE)
                constraints.append(CalibrationMaster.date >= oldest_allowed_date.strftime('%Y-%m-%d'))
                age_constraint_msg = f", age <= {config.MAX_DARK_AGE} days"
            
            # Get all dark masters that match the constraints
            query = session.query(CalibrationMaster).filter(and_(*constraints))
            
            masters = query.all()
            
            if not masters:
                print(f"{Style.BRIGHT + Fore.RED}Could not find a suitable master dark.{Style.RESET_ALL}")
                print(f"  Required: binning={fits_file.binning}, gain={fits_file.gain}, "
                      f"offset={fits_file.offset}, ccd_temp={fits_file.ccd_temp}±{ccd_temp_tolerance}°C")
                print(f"  Exposure constraint: >= {fits_file.exptime}s")
                if age_constraint_msg:
                    print(f"  Date constraint: >= {(fits_file.date_obs - timedelta(days=config.MAX_DARK_AGE)).strftime('%Y-%m-%d')}{age_constraint_msg}")
                return None
            
            # Find the one with closest date_obs
            closest_master = None
            min_date_diff = float('inf')
            
            for master in masters:
                # Parse the date from the master
                master_date = datetime.strptime(master.date, '%Y-%m-%d')
                date_diff = abs((master_date - fits_file.date_obs).days)
                
                if date_diff < min_date_diff:
                    min_date_diff = date_diff
                    closest_master = master
            
            if closest_master:
                print(f"Selected master dark: {closest_master.path}")
                print(f"  Date: {closest_master.date}, Exposure: {closest_master.exptime}s")
                print(f"  Binning: {closest_master.binning}, Gain: {closest_master.gain}, "
                      f"Offset: {closest_master.offset}, Temp: {closest_master.ccd_temp}°C")
            
            return closest_master
            
        finally:
            session.close()
    
    def find_master_flat(self, fits_file: FitsFile) -> Optional[CalibrationMaster]:
        """
        Find the most suitable master flat for a given FITS file.
        
        For flat frames, we match on binning and filter, and choose the nearest
        PREVIOUS available flat (not future dates).
        Optionally applies age constraint based on MAX_FLAT_AGE config.
        
        Args:
            fits_file: The FitsFile object to find calibration for
            
        Returns:
            CalibrationMaster object if found, None otherwise
        """
        session = self.db_manager.get_session()
        try:
            # Build base query constraints
            constraints = [
                CalibrationMaster.frame == 'Flat',
                CalibrationMaster.binning == fits_file.binning,
                CalibrationMaster.filter_name == fits_file.filter_name,
                CalibrationMaster.date <= fits_file.date_obs.strftime('%Y-%m-%d')
            ]
            
            # Apply age constraint if MAX_FLAT_AGE > 0
            age_constraint_msg = ""
            if config.MAX_FLAT_AGE > 0:
                oldest_allowed_date = fits_file.date_obs - timedelta(days=config.MAX_FLAT_AGE)
                constraints.append(CalibrationMaster.date >= oldest_allowed_date.strftime('%Y-%m-%d'))
                age_constraint_msg = f", age <= {config.MAX_FLAT_AGE} days"
            
            # Get all flat masters that match the constraints
            query = session.query(CalibrationMaster).filter(and_(*constraints)).order_by(CalibrationMaster.date.desc())
            
            masters = query.all()
            
            if not masters:
                print(f"{Style.BRIGHT + Fore.RED}Could not find a suitable master flat.{Style.RESET_ALL}")
                print(f"  Required: binning={fits_file.binning}, filter={fits_file.filter_name}")
                print(f"  Date constraint: <= {fits_file.date_obs.strftime('%Y-%m-%d')}{age_constraint_msg}")
                return None
            
            # Return the most recent one (closest previous date)
            selected_master = masters[0]
            print(f"Selected master flat: {selected_master.path}")
            print(f"  Date: {selected_master.date}, Binning: {selected_master.binning}, Filter: {selected_master.filter_name}")
            
            return selected_master
            
        finally:
            session.close()
    
    def find_calibration_masters(self, fits_file: FitsFile) -> Dict[str, Optional[CalibrationMaster]]:
        """
        Find all suitable calibration masters for a given FITS file.
        
        Args:
            fits_file: The FitsFile object to find calibration for
            
        Returns:
            Dictionary with keys 'bias', 'dark', 'flat' containing the selected masters
        """
        print(f"\n{Style.BRIGHT}Finding calibration masters for: {fits_file.path}{Style.RESET_ALL}")
        print(f"  Date: {fits_file.date_obs.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Filter: {fits_file.filter_name}, Binning: {fits_file.binning}")
        print(f"  Gain: {fits_file.gain}, Offset: {fits_file.offset}, Temp: {fits_file.ccd_temp}°C")
        print(f"  Exposure: {fits_file.exptime}s")
        
        masters = {
            'bias': self.find_master_bias(fits_file),
            'dark': self.find_master_dark(fits_file),
            'flat': self.find_master_flat(fits_file)
        }
        
        # Summary
        print(f"\n{Style.BRIGHT}Calibration masters summary:{Style.RESET_ALL}")
        for calib_type, master in masters.items():
            if master:
                print(f"  {calib_type.upper()}: ✓ Found ({master.path})")
            else:
                print(f"  {calib_type.upper()}: ✗ Not found")
        
        return masters
    
    def get_fits_file_by_path(self, file_path: str) -> Optional[FitsFile]:
        """
        Get a FitsFile object from the database by its path.
        
        Args:
            file_path: Path to the FITS file
            
        Returns:
            FitsFile object if found, None otherwise
        """
        return self.db_manager.get_fits_file_by_path(file_path)
    
    def calibrate_file(self, file_path: str) -> Dict[str, Any]:
        """
        Find calibration masters for a given file path.
        
        Args:
            file_path: Path to the FITS file to calibrate
            
        Returns:
            Dictionary containing the calibration masters and status
        """
        # Get the FITS file from database
        fits_file = self.get_fits_file_by_path(file_path)
        if not fits_file:
            print(f"{Style.BRIGHT + Fore.RED}File not found in database: {file_path}{Style.RESET_ALL}")
            return {'error': 'File not found in database'}
        
        # Find calibration masters
        masters = self.find_calibration_masters(fits_file)
        
        return {
            'fits_file': fits_file,
            'masters': masters,
            'success': all(masters.values())  # True if all masters were found
        }
    
    def _extract_ccd(self, image_path: str) -> CCDData:
        """
        Extract CCDData from a FITS file path.
        
        Args:
            image_path: Path to the FITS file
            
        Returns:
            CCDData object
        """
        return CCDData.read(image_path, unit='adu')
    
    def _create_temp_dir(self, output_dir: Optional[str] = None) -> Path:
        """
        Create and return a temporary directory for calibration files.
        
        Args:
            output_dir: Optional custom output directory. If None, uses default /tmp location.
        
        Returns:
            Path to the temporary directory
        """
        if output_dir:
            temp_dir = Path(output_dir)
        else:
            temp_dir = Path("/tmp/astropipes/calibrated")
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir
    
    def subtract_bias(self, image_path: str, bias_master: CalibrationMaster) -> CCDData:
        """
        Subtract master bias from FITS image.
        
        Args:
            image_path: Path to the FITS file to calibrate
            bias_master: CalibrationMaster object for bias
            
        Returns:
            CCDData object with bias subtracted
        """
        print(f"{Style.BRIGHT + Fore.GREEN}Bias subtraction...{Style.RESET_ALL}")
        
        # Load the images
        image = self._extract_ccd(image_path)
        bias = self._extract_ccd(bias_master.path)
        
        # Perform bias subtraction
        calibrated_image = ccdp.subtract_bias(image, bias)
        calibrated_image.data = calibrated_image.data.astype('float32')
        
        return calibrated_image
    
    def subtract_dark(self, image: CCDData, dark_master: CalibrationMaster, original_exptime: float) -> CCDData:
        """
        Subtract master dark from FITS image with proper scaling.
        
        Args:
            image: CCDData object (already bias-subtracted)
            dark_master: CalibrationMaster object for dark
            original_exptime: Original exposure time of the target image
            
        Returns:
            CCDData object with dark subtracted
        """
        print(f"{Style.BRIGHT + Fore.GREEN}Dark subtraction...{Style.RESET_ALL}")
        
        # Load the dark master
        dark = self._extract_ccd(dark_master.path)
        
        # Perform dark subtraction with scaling
        calibrated_image = ccdp.subtract_dark(
            image, dark, 
            exposure_time='EXPTIME', 
            exposure_unit=u.second, 
            scale=True
        )
        calibrated_image.data = calibrated_image.data.astype('float32')
        
        return calibrated_image
    
    def correct_flat(self, image: CCDData, flat_master: CalibrationMaster) -> CCDData:
        """
        Apply flat correction to FITS image.
        
        Args:
            image: CCDData object (already bias and dark subtracted)
            flat_master: CalibrationMaster object for flat
            
        Returns:
            CCDData object with flat correction applied
        """
        print(f"{Style.BRIGHT + Fore.GREEN}Flat correction...{Style.RESET_ALL}")
        
        # Load the flat master
        flat = self._extract_ccd(flat_master.path)
        
        # Apply flat correction
        calibrated_image = ccdp.flat_correct(image, flat)
        calibrated_image.data = calibrated_image.data.astype('float32')
        
        return calibrated_image
    
    def restore_wcs_header(self, original_path: str, calibrated_path: str):
        """
        Restore WCS header from original file to calibrated file.
        
        Args:
            original_path: Path to original FITS file
            calibrated_path: Path to calibrated FITS file
        """
        with fits.open(original_path) as orig, fits.open(calibrated_path, mode='update') as cal:
            wcs_keys = ['CTYPE1', 'CTYPE2', 'CRPIX1', 'CRPIX2', 'CRVAL1', 'CRVAL2', 'CD1_1', 'CD1_2', 'CD2_1', 'CD2_2']
            copied_keys = []
            for key in wcs_keys:
                if key in orig[0].header:
                    cal[0].header[key] = orig[0].header[key]
                    copied_keys.append(key)
            removed_keys = []
            for key in ['CDELT1', 'CDELT2', 'CROTA1', 'CROTA2']:
                if key in cal[0].header:
                    del cal[0].header[key]
                    removed_keys.append(key)
            cal.flush()
    
    def _add_origfile_header(self, calibrated_path: str, original_path: str):
        """
        Add ORIGFILE header to calibrated image for database lookup.
        
        Args:
            calibrated_path: Path to the calibrated image
            original_path: Path to the original raw file
        """
        try:
            with fits.open(calibrated_path, mode='update') as hdul:
                header = hdul[0].header
                
                # Convert to absolute paths for reliability
                original_path = os.path.abspath(original_path)
                
                # Add ORIGFILE header
                header['ORIGFILE'] = original_path
                header.comments['ORIGFILE'] = 'Original file path for database lookup'
                
                # Also add ORIGPATH as an alternative
                header['ORIGPATH'] = original_path
                header.comments['ORIGPATH'] = 'Original file path (alternative keyword)'
                
                # Add timestamp of when this was added
                from datetime import datetime
                header['ORIGDATE'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                header.comments['ORIGDATE'] = 'Date when ORIGFILE header was added'
                
        except Exception as e:
            print(f"Error adding ORIGFILE header: {e}")
            raise
    
    def _extract_fits_metadata(self, file_path: str) -> Optional[FitsFile]:
        """
        Extract FITS metadata directly from file header to create a FitsFile-like object.
        This allows calibration of files not in the database.
        
        Args:
            file_path: Path to the FITS file
            
        Returns:
            FitsFile-like object with metadata, or None if file cannot be read
        """
        try:
            with fits.open(file_path) as hdul:
                header = hdul[0].header
                
                # Extract required metadata from header
                # Use get() with defaults for optional fields
                
                # Handle binning - check for XBINNING/YBINNING or BINNING
                xbinning = header.get('XBINNING', 1)
                ybinning = header.get('YBINNING', 1)
                if xbinning == ybinning:
                    binning = f"{xbinning}x{xbinning}"
                else:
                    binning = f"{xbinning}x{ybinning}"
                
                filter_name = header.get('FILTER', 'Unknown')
                gain = header.get('GAIN', 0.0)
                offset = header.get('OFFSET', 0.0)
                ccd_temp = header.get('CCD-TEMP', 0.0)
                exptime = header.get('EXPTIME', 0.0)
                
                # Parse date
                date_str = header.get('DATE-OBS', '')
                if date_str:
                    try:
                        # Try to parse the date
                        if 'T' in date_str:
                            date_obs = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        else:
                            date_obs = datetime.strptime(date_str, '%Y-%m-%d')
                    except:
                        date_obs = datetime.now()
                else:
                    date_obs = datetime.now()
                
                # Create a simple object with the required attributes
                class FitsFileLike:
                    def __init__(self, path, binning, filter_name, gain, offset, ccd_temp, exptime, date_obs):
                        self.path = path
                        self.binning = binning
                        self.filter_name = filter_name
                        self.gain = gain
                        self.offset = offset
                        self.ccd_temp = ccd_temp
                        self.exptime = exptime
                        self.date_obs = date_obs
                
                return FitsFileLike(
                    path=file_path,
                    binning=binning,
                    filter_name=filter_name,
                    gain=gain,
                    offset=offset,
                    ccd_temp=ccd_temp,
                    exptime=exptime,
                    date_obs=date_obs
                )
                
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error reading FITS file {file_path}: {e}{Style.RESET_ALL}")
            return None

    def calibrate_file(self, file_path: str, steps: Dict[str, bool] = None, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Calibrate a FITS file using the found calibration masters.
        
        Args:
            file_path: Path to the FITS file to calibrate
            steps: Dictionary specifying which calibration steps to apply
                   {'bias': True, 'dark': True, 'flat': True}
            output_dir: Optional custom output directory. If None, uses default /tmp location.
            
        Returns:
            Dictionary containing calibration results
        """
        if steps is None:
            steps = {
                'bias': True,
                'dark': True,
                'flat': True,
            }
        
        # Try to get the FITS file from database first
        fits_file = self.get_fits_file_by_path(file_path)
        
        # If not in database, extract metadata directly from the file
        if not fits_file:
            print(f"{Style.BRIGHT + Fore.YELLOW}File not found in database, extracting metadata from file header...{Style.RESET_ALL}")
            fits_file = self._extract_fits_metadata(file_path)
            if not fits_file:
                print(f"{Style.BRIGHT + Fore.RED}Could not read FITS file: {file_path}{Style.RESET_ALL}")
                return {'error': 'Could not read FITS file'}
        
        # Find calibration masters
        masters = self.find_calibration_masters(fits_file)
        
        # Check which masters are missing and warn, but proceed with available ones
        missing_masters = []
        available_masters = []
        for step, required in steps.items():
            if required and not masters.get(step):
                missing_masters.append(step)
            elif required and masters.get(step):
                available_masters.append(step)
        
        if missing_masters:
            print(f"{Style.BRIGHT + Fore.YELLOW}Warning: missing masters for {', '.join(missing_masters)}, proceeding with available calibrations{Style.RESET_ALL}")
        
        if not available_masters:
            print(f"{Style.BRIGHT + Fore.RED}Cannot calibrate: no calibration masters found{Style.RESET_ALL}")
            return {'error': 'No calibration masters found'}
        
        print(f"\n{Style.BRIGHT}Calibrating {os.path.basename(file_path)} using: {', '.join(available_masters)}...{Style.RESET_ALL}")
        
        # Create temporary directory
        temp_dir = self._create_temp_dir(output_dir)
        
        try:
            # Start with the original image
            calibrated_image = self._extract_ccd(file_path)
            new_filename = os.path.basename(file_path)
            
            # Apply calibration steps
            if steps['bias'] and masters['bias']:
                calibrated_image = self.subtract_bias(file_path, masters['bias'])
                new_filename = f"b_{new_filename}"
            
            if steps['dark'] and masters['dark']:
                calibrated_image = self.subtract_dark(calibrated_image, masters['dark'], fits_file.exptime)
                new_filename = f"d_{new_filename}"
            
            if steps['flat'] and masters['flat']:
                calibrated_image = self.correct_flat(calibrated_image, masters['flat'])
                new_filename = f"f_{new_filename}"
            
            # Write the calibrated image
            output_path = temp_dir / new_filename
            print(f"{Style.BRIGHT + Fore.GREEN}Writing calibrated image: {output_path}{Style.RESET_ALL}")
            calibrated_image.write(output_path, overwrite=True)
            
            # Add ORIGFILE header for database lookup
            try:
                self._add_origfile_header(str(output_path), file_path)
                print(f"{Style.BRIGHT + Fore.GREEN}ORIGFILE header added{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Style.BRIGHT + Fore.YELLOW}Warning: Could not add ORIGFILE header: {e}{Style.RESET_ALL}")
            
            # Restore WCS header if it exists
            try:
                self.restore_wcs_header(file_path, str(output_path))
                print(f"{Style.BRIGHT + Fore.GREEN}WCS header restored{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Style.BRIGHT + Fore.YELLOW}Warning: Could not restore WCS header: {e}{Style.RESET_ALL}")
            
            return {
                'success': True,
                'original_path': file_path,
                'calibrated_path': str(output_path),
                'filename': new_filename,
                'masters_used': masters,
                'applied_calibrations': available_masters,
                'missing_masters': missing_masters
            }
            
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error during calibration: {e}{Style.RESET_ALL}")
            return {'error': str(e)}
    
    def calibrate_file_simple(self, file_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Simple calibration interface that finds masters and calibrates in one step.
        
        Args:
            file_path: Path to the FITS file to calibrate
            output_dir: Optional custom output directory. If None, uses default /tmp location.
            
        Returns:
            Dictionary containing calibration results
        """
        return self.calibrate_file(file_path, output_dir=output_dir)
    
    def add_origfile_header_manually(self, calibrated_path: str, original_path: str) -> bool:
        """
        Manually add ORIGFILE header to an existing calibrated image.
        This is useful for images that were calibrated outside of this system.
        
        Args:
            calibrated_path: Path to the calibrated image
            original_path: Path to the original raw file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self._add_origfile_header(calibrated_path, original_path)
            print(f"{Style.BRIGHT + Fore.GREEN}ORIGFILE header added to: {calibrated_path}{Style.RESET_ALL}")
            print(f"  Original file: {original_path}")
            return True
        except Exception as e:
            print(f"{Style.BRIGHT + Fore.RED}Error adding ORIGFILE header: {e}{Style.RESET_ALL}")
            return False 