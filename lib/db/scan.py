"""
FITS file scanner for importing files into the database.
"""

import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from .manager import get_db_manager
from ..fits import get_fits_header_as_json
import config


class FitsFileScanner:
    """Scanner for importing FITS files into the database."""
    
    def __init__(self, data_path: Optional[str] = None):
        """
        Initialize the scanner.
        
        Args:
            data_path: Path to scan for FITS files. If None, uses config.DATA_PATH.
        """
        if data_path is None:
            import config
            data_path = config.DATA_PATH
        
        self.data_path = Path(data_path)
        self.db_manager = get_db_manager()
        
        if not self.data_path.exists():
            raise FileNotFoundError(f"Data path does not exist: {self.data_path}")
    
    def scan_directory(self, verbose: bool = True) -> Dict[str, Any]:
        """
        Scan the data directory and import FITS files into the database.
        
        Args:
            verbose: Whether to print progress information
            
        Returns:
            Dictionary with scan results
        """
        if verbose:
            print(f"Scanning directory: {self.data_path}")
            print(f"Expected structure: {self.data_path}/Target/Filter/file.fits")
            print("-" * 60)
        
        results = {
            'total_files_found': 0,
            'files_imported': 0,
            'files_skipped': 0,
            'errors': [],
            'targets_found': set(),
            'filters_found': set()
        }
        
        # Walk through the directory structure
        for target_dir in self.data_path.iterdir():
            if not target_dir.is_dir():
                continue
                
            target_name = target_dir.name
            results['targets_found'].add(target_name)
            
            if verbose:
                print(f"Processing target: {target_name}")
            
            # Look for filter subdirectories
            for filter_dir in target_dir.iterdir():
                if not filter_dir.is_dir():
                    continue
                    
                filter_name = filter_dir.name
                results['filters_found'].add(filter_name)
                
                if verbose:
                    print(f"  Processing filter: {filter_name}")
                
                # Look for FITS files
                for fits_file in filter_dir.glob("*.fits"):
                    results['total_files_found'] += 1
                    
                    if verbose:
                        print(f"    Processing: {fits_file.name}")
                    
                    try:
                        success = self._process_fits_file(fits_file, target_name, filter_name)
                        if success:
                            results['files_imported'] += 1
                        else:
                            results['files_skipped'] += 1
                    except Exception as e:
                        error_msg = f"Error processing {fits_file}: {e}"
                        results['errors'].append(error_msg)
                        if verbose:
                            print(f"{error_msg}")
        
        # Convert sets to lists for JSON serialization
        results['targets_found'] = list(results['targets_found'])
        results['filters_found'] = list(results['filters_found'])
        
        if verbose:
            self._print_summary(results)
        
        return results
    
    def _process_fits_file(self, fits_file: Path, target_name: str, filter_name: str) -> bool:
        """
        Process a single FITS file and add it to the database.
        
        Args:
            fits_file: Path to the FITS file
            target_name: Name of the target (from directory structure)
            filter_name: Name of the filter (from directory structure)
            
        Returns:
            True if file was imported, False if it was skipped (already exists)
        """
        # Check if file already exists in database
        existing_file = self.db_manager.get_fits_file_by_path(str(fits_file))
        if existing_file:
            return False  # File already exists
        
        # Parse FITS header
        header_dict = get_fits_header_as_json(str(fits_file))
        
        # Extract key information from header
        def get_val(key):
            v = header_dict.get(key)
            return v[0] if isinstance(v, tuple) else v

        fits_data = {
            'path': str(fits_file),
            'target': normalize_object_name(get_val('OBJECT')),  # Normalized OBJECT from header as target
            'filter_name': filter_name,  # Use directory name as filter
            'date_obs': self._parse_date_obs(get_val('DATE-OBS')),
            'exptime': get_val('EXPTIME'),
            'gain': get_val('GAIN'),
            'offset': get_val('OFFSET'),
            'focus_position': get_val('FOCUSPOS'),
            'ccd_temp': get_val('CCD-TEMP'),
            'binning': self._format_binning(get_val('XBINNING'), get_val('YBINNING')),
            'size_x': get_val('NAXIS1'),
            'size_y': get_val('NAXIS2'),
            'image_scale': get_val('SCALE'),  # arcsec/pixel (was PIXSCALE)
            'ra_center': get_val('CRVAL1'),  # Right Ascension of center
            'dec_center': get_val('CRVAL2'),  # Declination of center
            'wcs_type': get_val('CTYPE1'),  # WCS solution type
            'header_json': json.dumps(header_dict),  # Full header as JSON
            'simbad_objects': '[]'  # Empty array for now
        }
        
        # Add to database
        self.db_manager.add_fits_file(fits_data)
        return True
    
    def _parse_date_obs(self, date_obs: Any) -> Optional[datetime]:
        """
        Parse the DATE-OBS header value into a datetime object.
        
        Args:
            date_obs: The DATE-OBS value from the header
            
        Returns:
            Parsed datetime object or None if parsing fails
        """
        if not date_obs:
            return None
        
        try:
            # Try to parse the date string
            if isinstance(date_obs, str):
                # Handle different date formats
                for fmt in ['%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']:
                    try:
                        return datetime.strptime(date_obs, fmt)
                    except ValueError:
                        continue
            return None
        except Exception:
            return None
    
    def _format_binning(self, xbin: Any, ybin: Any) -> str:
        """
        Format binning information as a string.
        
        Args:
            xbin: X binning value
            ybin: Y binning value
            
        Returns:
            Formatted binning string (e.g., "1x1", "2x2")
        """
        x = xbin if xbin is not None else 1
        y = ybin if ybin is not None else 1
        return f"{x}x{y}"
    
    def _print_summary(self, results: Dict[str, Any]):
        """Print a summary of the scan results."""
        print("\n" + "=" * 60)
        print("SCAN SUMMARY")
        print("=" * 60)
        print(f"Total files found: {results['total_files_found']}")
        print(f"Files imported: {results['files_imported']}")
        print(f"Files skipped (already in DB): {results['files_skipped']}")
        print(f"Errors: {len(results['errors'])}")
        
        if results['targets_found']:
            print(f"\nTargets found: {', '.join(sorted(results['targets_found']))}")
        
        if results['filters_found']:
            print(f"Filters found: {', '.join(sorted(results['filters_found']))}")
        
        if results['errors']:
            print(f"\nErrors encountered:")
            for error in results['errors']:
                print(f"  - {error}")


class CalibrationMasterScanner:
    """Scanner for importing calibration master FITS files into the database."""
    def __init__(self, calibration_path: str = None):
        if calibration_path is None:
            calibration_path = config.CALIBRATION_PATH
        self.calibration_path = Path(calibration_path)
        self.db_manager = get_db_manager()
        if not self.calibration_path.exists():
            raise FileNotFoundError(f"Calibration path does not exist: {self.calibration_path}")
        self.valid_folders = {"dark": "Dark", "flat": "Flat", "bias": "Bias"}

    def scan_directory(self, verbose: bool = True) -> Dict[str, Any]:
        if verbose:
            print(f"Scanning calibration directory: {self.calibration_path}")
            print(f"Expected structure: {self.calibration_path}/[dark|flat|bias]/master_*.fits")
            print("-" * 60)
        results = {
            'total_files_found': 0,
            'files_imported': 0,
            'files_skipped': 0,
            'errors': [],
            'frames_found': set(),
        }
        for folder, frame_type in self.valid_folders.items():
            folder_path = self.calibration_path / folder
            if not folder_path.is_dir():
                continue
            results['frames_found'].add(frame_type)
            if verbose:
                print(f"Processing frame type: {frame_type}")
            for fits_file in folder_path.glob("*.fits"):
                results['total_files_found'] += 1
                if verbose:
                    print(f"  Processing: {fits_file.name}")
                try:
                    success = self._process_calibration_file(fits_file, frame_type)
                    if success:
                        results['files_imported'] += 1
                    else:
                        results['files_skipped'] += 1
                except Exception as e:
                    error_msg = f"Error processing {fits_file}: {e}"
                    results['errors'].append(error_msg)
                    if verbose:
                        print(f"    ❌ {error_msg}")
        results['frames_found'] = list(results['frames_found'])
        if verbose:
            self._print_summary(results)
        return results

    def _process_calibration_file(self, fits_file: Path, frame_type: str) -> bool:
        # Check if file already exists in database
        existing = self.db_manager.get_calibration_master_by_path(str(fits_file))
        if existing:
            return False  # File already exists
        header_dict = get_fits_header_as_json(str(fits_file))
        def get_val(key):
            v = header_dict.get(key)
            return v[0] if isinstance(v, tuple) else v
        # Parse date (date only, no time)
        date_obs = get_val('DATE-OBS')
        date_str = None
        if date_obs:
            for fmt in ['%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']:
                try:
                    date_str = datetime.strptime(date_obs, fmt).strftime('%Y-%m-%d')
                    break
                except Exception:
                    continue
        master_data = {
            'path': str(fits_file),
            'date': date_str,
            'frame': frame_type,
            'filter_name': get_val('FILTER'),
            'exptime': get_val('EXPTIME'),
            'gain': get_val('GAIN'),
            'offset': get_val('OFFSET'),
            'focus_position': get_val('FOCUSPOS'),
            'ccd_temp': get_val('CCD-TEMP'),
            'binning': self._format_binning(get_val('XBINNING'), get_val('YBINNING')),
            'size_x': get_val('NAXIS1'),
            'size_y': get_val('NAXIS2'),
            'header_json': json.dumps(header_dict),
            'integration_count': get_val('NIMAGES'),
        }
        self.db_manager.add_calibration_master(master_data)
        return True

    def _format_binning(self, xbin, ybin) -> str:
        x = xbin if xbin is not None else 1
        y = ybin if ybin is not None else 1
        return f"{x}x{y}"

    def _print_summary(self, results: Dict[str, Any]):
        print("\n" + "=" * 60)
        print("CALIBRATION SCAN SUMMARY")
        print("=" * 60)
        print(f"Total files found: {results['total_files_found']}")
        print(f"Files imported: {results['files_imported']}")
        print(f"Files skipped (already in DB): {results['files_skipped']}")
        print(f"Errors: {len(results['errors'])}")
        if results['frames_found']:
            print(f"\nFrames found: {', '.join(sorted(results['frames_found']))}")
        if results['errors']:
            print(f"\nErrors encountered:")
            for error in results['errors']:
                print(f"  - {error}")

def scan_fits_library(data_path: Optional[str] = None, verbose: bool = True) -> Dict[str, Any]:
    """
    Convenience function to scan the FITS library.
    
    Args:
        data_path: Path to scan for FITS files. If None, uses config.DATA_PATH.
        verbose: Whether to print progress information
        
    Returns:
        Dictionary with scan results
    """
    scanner = FitsFileScanner(data_path)
    return scanner.scan_directory(verbose) 

def scan_calibration_masters(calibration_path: Optional[str] = None, verbose: bool = True) -> Dict[str, Any]:
    """
    Convenience function to scan the calibration master library.
    Args:
        calibration_path: Path to scan for calibration masters. If None, uses config.CALIBRATION_PATH.
        verbose: Whether to print progress information
    Returns:
        Dictionary with scan results
    """
    scanner = CalibrationMasterScanner(calibration_path)
    return scanner.scan_directory(verbose) 

def is_file_in_database(file_path: str) -> bool:
    """
    Check if a file is present in the database by its full path.
    
    Parameters:
    -----------
    file_path : str
        Full path to the FITS file to check
        
    Returns:
    --------
    bool
        True if the file exists in the database, False otherwise
    """
    from lib.db.manager import get_db_manager
    from lib.db.models import FitsFile, CalibrationMaster
    
    db_manager = get_db_manager()
    
    try:
        session = db_manager.get_session()
        
        # Check in FitsFile table
        fits_file = session.query(FitsFile).filter(FitsFile.path == file_path).first()
        if fits_file:
            session.close()
            return True
            
        # Check in CalibrationMaster table
        calib_file = session.query(CalibrationMaster).filter(CalibrationMaster.path == file_path).first()
        if calib_file:
            session.close()
            return True
            
        session.close()
        return False
        
    except Exception as e:
        print(f"Error checking database for file {file_path}: {e}")
        return False


def get_file_database_info(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Get database information for a file if it exists in the database.
    
    Parameters:
    -----------
    file_path : str
        Full path to the FITS file to check
        
    Returns:
    --------
    Optional[Dict[str, Any]]
        Dictionary with database info if file exists, None otherwise
    """
    from lib.db.manager import get_db_manager
    from lib.db.models import FitsFile, CalibrationMaster
    
    db_manager = get_db_manager()
    
    try:
        session = db_manager.get_session()
        
        # Check in FitsFile table
        fits_file = session.query(FitsFile).filter(FitsFile.path == file_path).first()
        if fits_file:
            result = {
                'table': 'FitsFile',
                'id': fits_file.id,
                'path': fits_file.path,
                'target': fits_file.target,
                'date_obs': fits_file.date_obs,
                'exptime': fits_file.exptime,
                'filter_name': fits_file.filter_name,
                'binning': fits_file.binning,
                'size_x': fits_file.size_x,
                'size_y': fits_file.size_y
            }
            session.close()
            return result
            
        # Check in CalibrationMaster table
        calib_file = session.query(CalibrationMaster).filter(CalibrationMaster.path == file_path).first()
        if calib_file:
            result = {
                'table': 'CalibrationMaster',
                'id': calib_file.id,
                'path': calib_file.path,
                'frame': calib_file.frame,
                'date': calib_file.date
            }
            session.close()
            return result
            
        session.close()
        return None
        
    except Exception as e:
        print(f"Error getting database info for file {file_path}: {e}")
        return None 

def rescan_single_file(file_path: str) -> Dict[str, Any]:
    """
    Re-scan a single FITS file and update its database entry.
    
    Parameters:
    -----------
    file_path : str
        Full path to the FITS file to re-scan
        
    Returns:
    --------
    Dict[str, Any]
        Dictionary with scan results including success status and updated fields
    """
    from lib.db.manager import get_db_manager
    from lib.db.models import FitsFile, CalibrationMaster
    from astropy.io import fits
    from astropy.wcs import WCS
    from astropy.wcs.utils import proj_plane_pixel_scales
    from datetime import datetime
    import os
    
    db_manager = get_db_manager()
    
    try:
        # Check if file exists in filesystem
        if not os.path.exists(file_path):
            return {
                'success': False,
                'message': f"File not found: {file_path}",
                'file_updated': False
            }
        
        # Get current database info
        db_info = get_file_database_info(file_path)
        if not db_info:
            return {
                'success': False,
                'message': f"File not found in database: {file_path}",
                'file_updated': False
            }
        
        # Read FITS header
        with fits.open(file_path) as hdu:
            header = hdu[0].header
            data = hdu[0].data
            
            # Get basic file info
            file_size = os.path.getsize(file_path)
            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            
            # Extract header values with defaults
            date_obs_str = header.get('DATE-OBS', '')
            target = normalize_object_name(header.get('OBJECT', ''))
            filter_name = header.get('FILTER', '')
            exptime = header.get('EXPTIME', 0.0)
            gain = header.get('GAIN', 0.0)
            offset = header.get('OFFSET', 0.0)
            focus_position = header.get('FOCUSPOS', 0)
            ccd_temp = header.get('CCD-TEMP', 0.0)
            
            # Handle binning - convert to strings first
            xbin = str(header.get('XBINNING', 1))
            ybin = str(header.get('YBINNING', 1))
            binning = f"{xbin}x{ybin}"
            
            # Image dimensions
            size_x = header.get('NAXIS1', 0)
            size_y = header.get('NAXIS2', 0)
            
            # WCS information
            # wcs_type = 'none'
            image_scale = None
            ra_center = None
            dec_center = None
            
            wcs_type = header.get('CTYPE1', None)
            
            try:
                wcs = WCS(header)
                if wcs.is_celestial:
                    # Calculate pixel scale
                    pixel_scales = proj_plane_pixel_scales(wcs)
                    image_scale = pixel_scales[0] * 3600  # Convert to arcsec/pixel
                    # Get center coordinates
                    center_x = size_x / 2
                    center_y = size_y / 2
                    ra_center, dec_center = wcs.all_pix2world(center_x, center_y, 0)
            except:
                pass
            
            # Parse date
            date_obs = None
            if date_obs_str:
                try:
                    # Try different date formats
                    for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%d %H:%M:%S']:
                        try:
                            date_obs = datetime.strptime(date_obs_str, fmt)
                            break
                        except ValueError:
                            continue
                except:
                    pass
        
        session = db_manager.get_session()
        
        try:
            if db_info['table'] == 'FitsFile':
                # Update FitsFile entry
                file_id = db_info.get('id')
                if file_id is None:
                    session.close()
                    return {
                        'success': False,
                        'message': f"FitsFile entry has no ID in database",
                        'file_updated': False
                    }
                fits_file = session.query(FitsFile).filter(FitsFile.id == file_id).first()
                if fits_file:
                    # Update all fields
                    fits_file.date_obs = date_obs
                    fits_file.target = target
                    fits_file.filter_name = filter_name
                    fits_file.exptime = exptime
                    fits_file.gain = gain
                    fits_file.offset = offset
                    fits_file.focus_position = focus_position
                    fits_file.ccd_temp = ccd_temp
                    fits_file.binning = binning
                    fits_file.size_x = size_x
                    fits_file.size_y = size_y
                    fits_file.image_scale = image_scale
                    fits_file.ra_center = ra_center
                    fits_file.dec_center = dec_center
                    fits_file.wcs_type = wcs_type
                    
                    session.commit()
                    
                    file_id = fits_file.id if fits_file.id is not None else 'Unknown'
                    return {
                        'success': True,
                        'message': f"Successfully updated FitsFile entry (ID: {file_id})",
                        'file_updated': True,
                        'table': 'FitsFile',
                        'id': fits_file.id,
                        'updated_fields': {
                            'date_obs': date_obs,
                            'target': target,
                            'filter_name': filter_name,
                            'exptime': exptime,
                            'wcs_type': wcs_type,
                            'image_scale': image_scale,
                            'ra_center': ra_center,
                            'dec_center': dec_center
                        }
                    }
                else:
                    session.rollback()
                    db_id = db_info.get('id', 'Unknown')
                    return {
                        'success': False,
                        'message': f"FitsFile entry not found in database (ID: {db_id})",
                        'file_updated': False
                    }
                    
            elif db_info['table'] == 'CalibrationMaster':
                # Update CalibrationMaster entry
                file_id = db_info.get('id')
                if file_id is None:
                    session.close()
                    return {
                        'success': False,
                        'message': f"CalibrationMaster entry has no ID in database",
                        'file_updated': False
                    }
                calib_file = session.query(CalibrationMaster).filter(CalibrationMaster.id == file_id).first()
                if calib_file:
                    # Update all fields
                    calib_file.date = date_obs.strftime('%Y-%m-%d') if date_obs else ''
                    calib_file.filter_name = filter_name
                    calib_file.exptime = exptime
                    calib_file.gain = gain
                    calib_file.offset = offset
                    calib_file.focus_position = focus_position
                    calib_file.ccd_temp = ccd_temp
                    calib_file.binning = binning
                    calib_file.size_x = size_x
                    calib_file.size_y = size_y
                    
                    session.commit()
                    
                    calib_id = calib_file.id if calib_file.id is not None else 'Unknown'
                    return {
                        'success': True,
                        'message': f"Successfully updated CalibrationMaster entry (ID: {calib_id})",
                        'file_updated': True,
                        'table': 'CalibrationMaster',
                        'id': calib_file.id,
                        'updated_fields': {
                            'date': calib_file.date,
                            'filter_name': filter_name,
                            'exptime': exptime,
                            'frame': calib_file.frame
                        }
                    }
                else:
                    session.rollback()
                    db_id = db_info.get('id', 'Unknown')
                    return {
                        'success': False,
                        'message': f"CalibrationMaster entry not found in database (ID: {db_id})",
                        'file_updated': False
                    }
            else:
                session.rollback()
                return {
                    'success': False,
                    'message': f"Unknown table type: {db_info['table']}",
                    'file_updated': False
                }
                
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
            
    except Exception as e:
        return {
            'success': False,
            'message': f"Error re-scanning file: {e}",
            'file_updated': False
        } 

def normalize_object_name(obj):
    """
    Normalize object name by replacing underscores with spaces and stripping whitespace.
    """
    if obj is None:
        return None
    return str(obj).replace('_', ' ').strip() 