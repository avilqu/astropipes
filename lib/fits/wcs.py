"""WCS (World Coordinate System) utilities for FITS files.
@author: Adrien Vilquin Barrajon <avilqu@gmail.com>
"""

import os
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import logging

from astropy.io import fits
from astropy.wcs import WCS
import warnings
from colorama import Style, Fore

# Set up logging
logger = logging.getLogger(__name__)

# Disable all logging to avoid INFO: output
logging.disable(logging.CRITICAL)

# Suppress WCS warnings for cleaner output
warnings.filterwarnings('ignore', category=UserWarning)


class WCSExtractionError(Exception):
    """Exception raised when WCS extraction fails."""
    pass


class WCSApplicationError(Exception):
    """Exception raised when WCS application fails."""
    pass


class ImageValidationError(Exception):
    """Exception raised when image validation fails."""
    pass


class ImageValidationResult:
    """Result of image validation with detailed information."""
    
    def __init__(self, is_valid: bool, reason: str = "", 
                 image_shape: Optional[Tuple[int, int]] = None,
                 existing_wcs: Optional[Dict[str, Union[str, float, int]]] = None,
                 ra_center: Optional[float] = None,
                 dec_center: Optional[float] = None,
                 pixel_scale: Optional[float] = None):
        self.is_valid = is_valid
        self.reason = reason
        self.image_shape = image_shape
        self.existing_wcs = existing_wcs
        self.ra_center = ra_center
        self.dec_center = dec_center
        self.pixel_scale = pixel_scale
    
    def __str__(self):
        status = "VALID" if self.is_valid else "INVALID"
        shape_str = f" ({self.image_shape[1]}x{self.image_shape[0]})" if self.image_shape else ""
        return f"{status}{shape_str}: {self.reason}"


def validate_fits_file(fits_file_path: str) -> ImageValidationResult:
    """
    Validate if a file is a valid FITS file suitable for platesolving.
    
    This function performs basic validation to ensure:
    - File exists and is readable
    - File is a valid FITS format
    - Contains 2D image data
    - Has reasonable dimensions and data characteristics
    
    Parameters:
    -----------
    fits_file_path : str
        Path to the FITS file to validate
        
    Returns:
    --------
    ImageValidationResult
        Object containing validation status and extracted information
    """
    try:
        # Check if file exists
        if not os.path.exists(fits_file_path):
            return ImageValidationResult(
                is_valid=False, 
                reason=f"File not found: {fits_file_path}"
            )
        
        # Check if file is readable
        if not os.access(fits_file_path, os.R_OK):
            return ImageValidationResult(
                is_valid=False, 
                reason=f"File not readable: {fits_file_path}"
            )
        
        print(f"Validating FITS file: {fits_file_path}")
        
        # Open and validate FITS structure
        with fits.open(fits_file_path) as hdul:
            # Check if file has any HDUs
            if len(hdul) == 0:
                return ImageValidationResult(
                    is_valid=False, 
                    reason="No HDUs found in FITS file"
                )
            
            # Get primary HDU
            primary_hdu = hdul[0]
            
            # Check if primary HDU has data
            if primary_hdu.data is None:
                return ImageValidationResult(
                    is_valid=False, 
                    reason="No data found in primary HDU"
                )
            
            # Check data dimensionality
            data = primary_hdu.data
            if len(data.shape) != 2:
                return ImageValidationResult(
                    is_valid=False, 
                    reason=f"Expected 2D image, got {len(data.shape)}D data"
                )
            
            # Check image dimensions
            height, width = data.shape
            if height < 100 or width < 100:
                return ImageValidationResult(
                    is_valid=False, 
                    reason=f"Image too small: {width}x{height} pixels (minimum 100x100)"
                )
            
            # Check for reasonable data range and contrast
            data_min = float(data.min())
            data_max = float(data.max())
            data_mean = float(data.mean())
            data_std = float(data.std())
            
            print(f"   Image stats: {width}x{height}, min={data_min:.1f}, max={data_max:.1f}, mean={data_mean:.1f}, std={data_std:.2f}")
        
        # Check for no contrast (all pixels same value)
        if data_min == data_max:
            return ImageValidationResult(
                is_valid=False, 
                reason="Image has no contrast (all pixels have same value)"
            )
        
        # Check for very low contrast
        if data_std < 1.0:
            return ImageValidationResult(
                is_valid=False, 
                reason=f"Image has very low contrast (std={data_std:.2f})"
            )
        
        # Check for reasonable signal levels
        if data_mean < 10 or data_max < 50:
            return ImageValidationResult(
                is_valid=False, 
                reason=f"Image appears too dark (mean={data_mean:.1f}, max={data_max:.1f})"
            )
        
        # Extract existing WCS information
        existing_wcs = extract_existing_wcs_from_header(primary_hdu.header)
        ra_center, dec_center, pixel_scale = extract_existing_wcs_info(fits_file_path)
        
        print(f"{Style.BRIGHT + Fore.GREEN}   Image appears valid for platesolving{Style.RESET_ALL}")
        
        return ImageValidationResult(
            is_valid=True,
            reason="Image appears valid for platesolving",
            image_shape=(height, width),
            existing_wcs=existing_wcs,
            ra_center=ra_center,
            dec_center=dec_center,
            pixel_scale=pixel_scale
        )
            
    except Exception as e:
        return ImageValidationResult(
            is_valid=False, 
            reason=f"Error reading FITS file: {e}"
        )


def extract_existing_wcs_from_header(header: fits.Header) -> Optional[Dict[str, Union[str, float, int]]]:
    """
    Extract existing WCS information from a FITS header.
    
    Parameters:
    -----------
    header : fits.Header
        FITS header object
        
    Returns:
    --------
    Optional[Dict[str, Union[str, float, int]]]
        Dictionary containing WCS header cards if found, None otherwise
    """
    # WCS keywords to look for
    wcs_keywords = [
        'CRPIX1', 'CRPIX2',      # Reference pixel coordinates
        'CRVAL1', 'CRVAL2',      # Reference world coordinates (RA, Dec)
        'CD1_1', 'CD1_2', 'CD2_1', 'CD2_2',  # CD matrix
        'CTYPE1', 'CTYPE2',      # Coordinate types
        'CUNIT1', 'CUNIT2',      # Coordinate units
        'LONPOLE', 'LATPOLE',    # Pole coordinates
        'PC1_1', 'PC1_2', 'PC2_1', 'PC2_2',  # PC matrix
        'CDELT1', 'CDELT2',      # Pixel scale
        'CROTA1', 'CROTA2'       # Rotation angles
    ]
    
    existing_wcs = {}
    for keyword in wcs_keywords:
        if keyword in header:
            existing_wcs[keyword] = header[keyword]
    # --- SIP extraction ---
    for key in header:
        if (
            key.startswith("A_") or key.startswith("B_") or
            key.startswith("AP_") or key.startswith("BP_") or
            key.endswith("_ORDER")
        ):
            existing_wcs[key] = header[key]
    # --- END SIP extraction ---
    if existing_wcs:
        print(f"   Found existing WCS with {len(existing_wcs)} keywords")
        if 'CRVAL1' in existing_wcs and 'CRVAL2' in existing_wcs:
            print(f"   Existing WCS center: RA={existing_wcs['CRVAL1']:.4f}°, Dec={existing_wcs['CRVAL2']:.4f}°")
        return existing_wcs
    else:
        print(f"   No existing WCS found in header")
        return None


def has_complete_wcs_solution(wcs_data: Dict[str, Union[str, float, int]]) -> bool:
    """
    Check if WCS data represents a complete WCS solution.
    
    Parameters:
    -----------
    wcs_data : Dict[str, Union[str, float, int]]
        Dictionary containing WCS header cards
        
    Returns:
    --------
    bool
        True if the WCS data represents a complete solution, False otherwise
    """
    if not wcs_data:
        return False
    
    # Check for minimum required keywords for a complete WCS
    required_keywords = ['CRPIX1', 'CRPIX2', 'CRVAL1', 'CRVAL2', 'CTYPE1', 'CTYPE2']
    
    # Check for required keywords
    for keyword in required_keywords:
        if keyword not in wcs_data:
            return False
    
    # Check for either CD matrix or PC matrix + CDELT
    has_cd_matrix = all(k in wcs_data for k in ['CD1_1', 'CD1_2', 'CD2_1', 'CD2_2'])
    has_pc_matrix = all(k in wcs_data for k in ['PC1_1', 'PC1_2', 'PC2_1', 'PC2_2', 'CDELT1', 'CDELT2'])
    
    return has_cd_matrix or has_pc_matrix


def get_platesolving_constraints(validation_result: ImageValidationResult) -> Dict[str, Union[float, bool]]:
    """
    Get platesolving constraints based on existing WCS information.
    
    Parameters:
    -----------
    validation_result : ImageValidationResult
        Result from validate_fits_file()
        
    Returns:
    --------
    Dict[str, Union[float, bool]]
        Dictionary containing constraints for platesolving:
        - 'ra': Right ascension in degrees (if available)
        - 'dec': Declination in degrees (if available)
        - 'radius': Search radius in degrees (15 if coordinates available, None for blind)
        - 'scale_est': Estimated pixel scale in arcsec/pixel (if available)
        - 'scale_err': Scale error as percentage (200% if scale available)
        - 'blind': Whether to use blind solving
    """
    constraints = {
        'blind': True,  # Default to blind solving
        'ra': None,
        'dec': None,
        'radius': None,
        'scale_est': None,
        'scale_err': None
    }
    
    # If we have center coordinates, use them for constrained solving
    if validation_result.ra_center is not None and validation_result.dec_center is not None:
        constraints['ra'] = validation_result.ra_center
        constraints['dec'] = validation_result.dec_center
        constraints['radius'] = 15.0  # 15 degree search radius
        constraints['blind'] = False
        print(f"{Style.BRIGHT + Fore.BLUE}   Using constrained solving: RA={validation_result.ra_center:.4f}°, Dec={validation_result.dec_center:.4f}°, radius=15°{Style.RESET_ALL}")
    
    # If we have pixel scale, use it for scale constraints
    if validation_result.pixel_scale is not None:
        constraints['scale_est'] = validation_result.pixel_scale
        constraints['scale_err'] = 200.0  # 200% error margin
        print(f"{Style.BRIGHT + Fore.BLUE}   Using scale constraint: {validation_result.pixel_scale:.3f} arcsec/pixel ±200%{Style.RESET_ALL}")
    
    if constraints['blind']:
        print(f"{Style.BRIGHT + Fore.BLUE}   Using blind solving (no constraints){Style.RESET_ALL}")
    
    return constraints


def extract_wcs_from_file(wcs_file_path: str) -> Dict[str, Union[str, float, int]]:
    """
    Extract WCS information from a WCS file generated by astrometry.net.
    
    Parameters:
    -----------
    wcs_file_path : str
        Path to the WCS file (.wcs extension)
        
    Returns:
    --------
    Dict[str, Union[str, float, int]]
        Dictionary containing WCS header cards and their values
        
    Raises:
    -------
    WCSExtractionError
        If the WCS file cannot be read or parsed
    """
    try:
        if not os.path.exists(wcs_file_path):
            raise WCSExtractionError(f"WCS file not found: {wcs_file_path}")
            
        # Read the WCS file
        with fits.open(wcs_file_path) as wcs_hdu:
            wcs_header = wcs_hdu[0].header
        
        # Safely get header length
        try:
            header_len = len(wcs_header) if wcs_header is not None else 0
            print(f"WCS file contains {header_len} header cards")
        except Exception:
            print(f"WCS file contains header cards (count unavailable)")
        
        # Extract WCS keywords
        wcs_keywords = [
            'CRPIX1', 'CRPIX2',      # Reference pixel coordinates
            'CRVAL1', 'CRVAL2',      # Reference world coordinates (RA, Dec)
            'CD1_1', 'CD1_2', 'CD2_1', 'CD2_2',  # CD matrix (linear transformation)
            'CTYPE1', 'CTYPE2',      # Coordinate types
            'CUNIT1', 'CUNIT2',      # Coordinate units
            'LONPOLE', 'LATPOLE',    # Pole coordinates
            'PC1_1', 'PC1_2', 'PC2_1', 'PC2_2',  # PC matrix (alternative to CD)
            'CDELT1', 'CDELT2',      # Pixel scale
            'CROTA1', 'CROTA2'       # Rotation angles
        ]
        
        extracted_wcs = {}
        for keyword in wcs_keywords:
            try:
                if keyword in wcs_header:
                    value = wcs_header[keyword]
                    # Skip None values and handle various edge cases
                    if value is not None:
                        # Try to convert to appropriate type to avoid formatting issues
                        try:
                            # For numeric keywords, ensure they're numeric
                            if keyword in ['CRPIX1', 'CRPIX2', 'CRVAL1', 'CRVAL2', 
                                         'CD1_1', 'CD1_2', 'CD2_1', 'CD2_2',
                                         'PC1_1', 'PC1_2', 'PC2_1', 'PC2_2',
                                         'CDELT1', 'CDELT2', 'CROTA1', 'CROTA2',
                                         'LONPOLE', 'LATPOLE']:
                                # Try to convert to float
                                float(value)
                            extracted_wcs[keyword] = value
                        except (ValueError, TypeError):
                            # Skip values that can't be converted
                            print(f"   Warning: Skipping {keyword} with invalid value: {value}")
            except Exception as e:
                # Skip keywords that cause errors when accessing
                print(f"   Warning: Error accessing {keyword}: {e}")
                continue
        # --- SIP extraction ---
        for key in wcs_header:
            try:
                if (
                    key.startswith("A_") or key.startswith("B_") or
                    key.startswith("AP_") or key.startswith("BP_") or
                    key.endswith("_ORDER")
                ):
                    value = wcs_header[key]
                    # Skip None values to avoid formatting errors later
                    if value is not None:
                        extracted_wcs[key] = value
            except Exception as e:
                # Skip keys that cause errors when accessing
                print(f"   Warning: Error accessing SIP key {key}: {e}")
                continue
        # --- END SIP extraction ---
        # Log summary of extracted WCS
        if extracted_wcs:
            try:
                print(f"   Extracted {len(extracted_wcs)} WCS keywords")
                if 'CRVAL1' in extracted_wcs and 'CRVAL2' in extracted_wcs:
                    try:
                        crval1 = float(extracted_wcs['CRVAL1'])
                        crval2 = float(extracted_wcs['CRVAL2'])
                        print(f"   Reference coordinates: RA={crval1:.4f}°, Dec={crval2:.4f}°")
                    except (ValueError, TypeError):
                        print(f"   Reference coordinates: RA={extracted_wcs['CRVAL1']}, Dec={extracted_wcs['CRVAL2']}")
            except Exception as e:
                print(f"   Extracted WCS keywords (summary unavailable: {e})")
        else:
            print(f"   No WCS keywords found in file")
            
        return extracted_wcs
        
    except Exception as e:
        # Safely format exception message to avoid formatting errors
        try:
            error_msg = str(e)
        except Exception:
            error_msg = f"Exception of type {type(e).__name__}"
        raise WCSExtractionError(f"Error extracting WCS from {wcs_file_path}: {error_msg}")


def extract_wcs_from_astrometry_net(job_id: str, temp_dir: str = ".") -> Dict[str, Union[str, float, int]]:
    """
    Download and extract WCS information from astrometry.net for a given job ID.
    
    Parameters:
    -----------
    job_id : str
        The astrometry.net job ID
    temp_dir : str
        Directory to store temporary WCS file
        
    Returns:
    --------
    Dict[str, Union[str, float, int]]
        Dictionary containing WCS header cards and their values
        
    Raises:
    -------
    WCSExtractionError
        If the WCS cannot be downloaded or extracted
    """
    wcs_url = f"http://nova.astrometry.net/wcs_file/{job_id}"
    wcs_filename = os.path.join(temp_dir, f"temp_wcs_{job_id}.wcs")
    
    try:
        print(f"Downloading WCS solution for job {job_id}...")
        urllib.request.urlretrieve(wcs_url, wcs_filename)
        
        # Extract WCS from the downloaded file
        wcs_data = extract_wcs_from_file(wcs_filename)
        
        # Clean up temporary file
        os.remove(wcs_filename)
        
        return wcs_data
        
    except Exception as e:
        # Clean up temporary file if it exists
        if os.path.exists(wcs_filename):
            try:
                os.remove(wcs_filename)
            except:
                pass
        raise WCSExtractionError(f"Error downloading WCS for job {job_id}: {e}")


def validate_wcs_solution(wcs_data: Dict[str, Union[str, float, int]]) -> bool:
    """
    Validate that a WCS solution contains the minimum required information.
    
    Parameters:
    -----------
    wcs_data : Dict[str, Union[str, float, int]]
        Dictionary containing WCS header cards
        
    Returns:
    --------
    bool
        True if the WCS solution is valid, False otherwise
    """
    # Minimum required keywords for a basic WCS solution
    required_keywords = ['CRPIX1', 'CRPIX2', 'CRVAL1', 'CRVAL2', 'CTYPE1', 'CTYPE2']
    
    # Check for required keywords
    for keyword in required_keywords:
        if keyword not in wcs_data:
            # logger.warning(f"Missing required WCS keyword: {keyword}") # Debug info removed
            return False
    
    # Check for either CD matrix or PC matrix + CDELT
    has_cd_matrix = all(k in wcs_data for k in ['CD1_1', 'CD1_2', 'CD2_1', 'CD2_2'])
    has_pc_matrix = all(k in wcs_data for k in ['PC1_1', 'PC1_2', 'PC2_1', 'PC2_2', 'CDELT1', 'CDELT2'])
    
    if not (has_cd_matrix or has_pc_matrix):
        # logger.warning("WCS solution missing transformation matrix (CD or PC+CDELT)") # Debug info removed
        return False
    
    # Validate coordinate types
    if wcs_data.get('CTYPE1', '').startswith('RA') and wcs_data.get('CTYPE2', '').startswith('DEC'):
        # logger.info("WCS solution appears valid") # Debug info removed
        return True
    else:
        # logger.warning("Invalid coordinate types in WCS solution") # Debug info removed
        return False


def apply_wcs_to_fits(fits_file_path: str, wcs_data: Dict[str, Union[str, float, int]], 
                     backup_original: bool = True) -> None:
    """
    Apply WCS solution to a FITS file header.
    
    Parameters:
    -----------
    fits_file_path : str
        Path to the FITS file to update
    wcs_data : Dict[str, Union[str, float, int]]
        Dictionary containing WCS header cards and their values
    backup_original : bool
        Whether to create a backup of the original file
        
    Raises:
    -------
    WCSApplicationError
        If the WCS cannot be applied to the file
    """
    try:
        # Validate WCS solution before applying
        if not validate_wcs_solution(wcs_data):
            raise WCSApplicationError("Invalid WCS solution")
        
        # Create backup if requested
        if backup_original:
            backup_path = fits_file_path + '.backup'
            if not os.path.exists(backup_path):
                import shutil
                shutil.copy2(fits_file_path, backup_path)
                # logger.info(f"Created backup: {backup_path}") # Debug info removed
        
        # Open the FITS file in update mode
        with fits.open(fits_file_path, mode='update') as hdul:
            header = hdul[0].header
            
            # Remove existing WCS keywords that might conflict
            wcs_keywords_to_remove = [
                'CRPIX1', 'CRPIX2', 'CRVAL1', 'CRVAL2',
                'CD1_1', 'CD1_2', 'CD2_1', 'CD2_2',
                'CTYPE1', 'CTYPE2', 'CUNIT1', 'CUNIT2',
                'LONPOLE', 'LATPOLE',
                'PC1_1', 'PC1_2', 'PC2_1', 'PC2_2',
                'CDELT1', 'CDELT2', 'CROTA1', 'CROTA2'
            ]
            
            for keyword in wcs_keywords_to_remove:
                if keyword in header:
                    del header[keyword]
                    # logger.debug(f"Removed existing {keyword}") # Debug info removed
            
            # Add new WCS keywords
            keywords_updated = 0
            for keyword, value in wcs_data.items():
                # Skip None values to avoid formatting errors
                if value is not None:
                    try:
                        header[keyword] = value
                        keywords_updated += 1
                    except Exception as e:
                        # Log but don't fail if a single keyword can't be set
                        print(f"   Warning: Could not set {keyword}: {e}")
                # logger.debug(f"Updated {keyword}: {value}") # Debug info removed
            
            # Add a comment indicating the file was plate solved
            header['HISTORY'] = 'Plate solved with astrometry.net'
            
            # Flush changes to disk
            hdul.flush()
        
        # logger.info(f"Successfully updated {keywords_updated} WCS headers in {fits_file_path}") # Debug info removed
        
    except Exception as e:
        # Safely format exception message to avoid formatting errors
        try:
            error_msg = str(e)
        except Exception:
            error_msg = f"Exception of type {type(e).__name__}"
        raise WCSApplicationError(f"Error applying WCS to {fits_file_path}: {error_msg}")


def extract_existing_wcs_info(fits_file_path: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Extract existing WCS information from a FITS file header.
    
    Parameters:
    -----------
    fits_file_path : str
        Path to the FITS file
        
    Returns:
    --------
    Tuple[Optional[float], Optional[float], Optional[float]]
        (ra_center, dec_center, pixel_scale) where:
        - ra_center: Right ascension in degrees (None if not found)
        - dec_center: Declination in degrees (None if not found)
        - pixel_scale: Pixel scale in arcsec/pixel (None if not found)
    """
    try:
        with fits.open(fits_file_path) as hdul:
            header = hdul[0].header
            
        ra_center = None
        dec_center = None
        pixel_scale = None
        
        # Try to get center coordinates from various header keywords
        if 'CRVAL1' in header and 'CRVAL2' in header:
            ra_center = float(header['CRVAL1'])
            dec_center = float(header['CRVAL2'])
            print(f"   Found WCS center: RA={ra_center:.4f}°, Dec={dec_center:.4f}°")
        elif 'RA' in header and 'DEC' in header:
            ra_center = float(header['RA'])
            dec_center = float(header['DEC'])
            print(f"   Found header center: RA={ra_center:.4f}°, Dec={dec_center:.4f}°")
        
        # Try to get pixel scale from WCS or header
        if 'CDELT1' in header and 'CDELT2' in header:
            # Convert from degrees to arcsec
            pixel_scale = abs(float(header['CDELT1'])) * 3600.0
            print(f"   Found WCS pixel scale: {pixel_scale:.3f} arcsec/pixel")
        elif 'PIXSCALE' in header:
            pixel_scale = float(header['PIXSCALE'])
            print(f"   Found header pixel scale: {pixel_scale:.3f} arcsec/pixel")
        
        return ra_center, dec_center, pixel_scale
        
    except Exception as e:
        # logger.warning(f"Error extracting existing WCS info from {fits_file_path}: {e}") # Debug info removed
        return None, None, None


def create_wcs_from_file(wcs_file_path: str) -> WCS:
    """
    Create an astropy WCS object from a WCS file.
    
    Parameters:
    -----------
    wcs_file_path : str
        Path to the WCS file
        
    Returns:
    --------
    WCS
        astropy WCS object
        
    Raises:
    -------
    WCSExtractionError
        If the WCS object cannot be created
    """
    try:
        with fits.open(wcs_file_path) as hdul:
            wcs = WCS(hdul[0].header)
        
        if not wcs.is_celestial:
            raise WCSExtractionError("WCS is not celestial")
            
        return wcs
        
    except Exception as e:
        raise WCSExtractionError(f"Error creating WCS object from {wcs_file_path}: {e}") 


def copy_wcs_from_reference(reference_header: fits.Header, target_header: fits.Header) -> fits.Header:
    """
    Copy WCS information from reference header to target header.
    
    This function is used during image alignment to ensure that aligned images
    have the same WCS information as the reference image, which is essential
    for maintaining coordinate consistency across aligned images.
    
    Parameters:
    -----------
    reference_header : fits.Header
        Reference header containing the WCS information to copy
    target_header : fits.Header
        Target header to receive the WCS information
        
    Returns:
    --------
    fits.Header
        New header with WCS information copied from reference
    """
    # Create a copy of the target header
    new_header = target_header.copy()
    
    # WCS keywords to copy from reference
    wcs_keywords = [
        'CTYPE1', 'CTYPE2',  # Coordinate types
        'CRPIX1', 'CRPIX2',  # Reference pixel coordinates
        'CRVAL1', 'CRVAL2',  # Reference pixel world coordinates
        'CD1_1', 'CD1_2', 'CD2_1', 'CD2_2',  # CD matrix
        'PC1_1', 'PC1_2', 'PC2_1', 'PC2_2',  # PC matrix (alternative to CD)
        'CUNIT1', 'CUNIT2',  # Coordinate units
        'EQUINOX',  # Equinox
        'RADESYS',  # Reference system
        'LONPOLE', 'LATPOLE',  # Pole coordinates
        'PV1_0', 'PV1_1', 'PV1_2', 'PV1_3', 'PV1_4', 'PV1_5', 'PV1_6', 'PV1_7', 'PV1_8', 'PV1_9', 'PV1_10',
        'PV2_0', 'PV2_1', 'PV2_2', 'PV2_3', 'PV2_4', 'PV2_5', 'PV2_6', 'PV2_7', 'PV2_8', 'PV2_9', 'PV2_10',
        'WCSAXES',  # Number of WCS axes
        'LTV1', 'LTV2',  # Linear transformation terms
        'LTM1_1', 'LTM1_2', 'LTM2_1', 'LTM2_2',  # Linear transformation matrix
    ]
    
    # Copy WCS keywords from reference to target
    for keyword in wcs_keywords:
        if keyword in reference_header:
            new_header[keyword] = reference_header[keyword]
        elif keyword in new_header:
            # Remove WCS keywords that don't exist in reference
            del new_header[keyword]
    
    # Also copy any WCS-related comments
    if 'COMMENT' in reference_header:
        for i, comment in enumerate(reference_header['COMMENT']):
            if any(wcs_term in comment.upper() for wcs_term in ['WCS', 'COORDINATE', 'ASTROMETRY', 'PLATE']):
                if 'COMMENT' not in new_header:
                    new_header['COMMENT'] = []
                new_header['COMMENT'].append(comment)
    
    return new_header 