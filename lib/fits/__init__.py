"""
FITS file utilities for astro-pipelines.
"""

from .header import get_fits_header_as_json, get_fits_header_json_string, set_fits_header_value
from .wcs import (
    extract_wcs_from_file,
    extract_wcs_from_astrometry_net,
    validate_wcs_solution,
    apply_wcs_to_fits,
    extract_existing_wcs_info,
    create_wcs_from_file,
    validate_fits_file,
    extract_existing_wcs_from_header,
    has_complete_wcs_solution,
    get_platesolving_constraints,
    ImageValidationResult,
    WCSExtractionError,
    WCSApplicationError,
    ImageValidationError
)
from .calibration import CalibrationManager
from .masters import (
    CalibrationMasterGenerationError,
    CalibrationMasterGenerator,
    generate_calibration_master
)
from .integration import (
    integrate_with_motion_tracking,
    integrate_standard,
    calculate_motion_shifts,
    check_sequence_consistency,
    compute_object_positions_from_motion_tracked,
    MotionTrackingIntegrationError
)

__all__ = [
    'get_fits_header_as_json', 
    'get_fits_header_json_string',
    'set_fits_header_value',
    'extract_wcs_from_file',
    'extract_wcs_from_astrometry_net',
    'validate_wcs_solution',
    'apply_wcs_to_fits',
    'extract_existing_wcs_info',
    'create_wcs_from_file',
    'validate_fits_file',
    'extract_existing_wcs_from_header',
    'has_complete_wcs_solution',
    'get_platesolving_constraints',
    'ImageValidationResult',
    'WCSExtractionError',
    'WCSApplicationError',
    'ImageValidationError',
    'CalibrationManager',
    'CalibrationMasterGenerationError',
    'CalibrationMasterGenerator',
    'generate_calibration_master',
    'integrate_with_motion_tracking',
    'integrate_standard',
    'calculate_motion_shifts',
    'check_sequence_consistency',
    'compute_object_positions_from_motion_tracked',
    'MotionTrackingIntegrationError'
] 