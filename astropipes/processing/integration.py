"""
Standard image integration (stacking) of aligned frames, with optional sigma clipping.
Motion-tracked integration is in astropipes.processing.motion_tracking.
"""

import numpy as np
from astropy.io import fits
from astropy.stats import mad_std
import ccdproc as ccdp
from typing import List, Optional, Callable
from pathlib import Path

from astropipes.fits.metadata import compute_mean_observation_time
from astropipes.fits.validation import sequence_inconsistencies
from astropipes.config import settings


class IntegrationError(Exception):
    """Raised when images can't be read or integrated."""
    pass


def extract_ccd_data(file_path: str) -> ccdp.CCDData:
    """
    Extract CCDData from a FITS file.
    
    Parameters:
    -----------
    file_path : str
        Path to FITS file
        
    Returns:
    --------
    ccdp.CCDData
        CCDData object
    """
    try:
        return ccdp.CCDData.read(file_path, unit='adu')
    except Exception as e:
        raise IntegrationError(f"Could not read {file_path}: {e}")


def safe_set_metadata(meta_dict: dict, key: str, value) -> None:
    """
    Safely set metadata value ensuring it's compatible with FITS headers.
    
    Parameters:
    -----------
    meta_dict : dict
        Metadata dictionary to update
    key : str
        Metadata key
    value : any
        Value to set (will be converted to string if needed)
    """
    # Convert value to string if it's not a basic type that FITS supports
    if isinstance(value, (bool, int, float, str)):
        meta_dict[key] = value
    else:
        meta_dict[key] = str(value)


def integrate_standard(files: List[str],
                      method: str = 'average',
                      sigma_clip: bool = False,
                      scale: Optional[Callable] = None,
                      output_path: Optional[str] = None,
                      progress_callback: Optional[Callable] = None,
                      memory_limit: Optional[float] = None,
                      alignment_reference_raw_path: Optional[str] = None) -> ccdp.CCDData:
    """
    Standard image integration without motion tracking.
    
    Parameters:
    -----------
    files : List[str]
        List of FITS file paths to integrate
    method : str
        Integration method ('average', 'median', 'sum')
    sigma_clip : bool
        Whether to apply sigma clipping (default: False for raw output)
    scale : Optional[Callable]
        Scaling function (e.g., for flat fielding)
    output_path : Optional[str]
        Path to save the integrated image
    progress_callback : Optional[Callable]
        Progress callback function(progress: float)
    memory_limit : Optional[float]
        Memory limit in bytes for processing
    alignment_reference_raw_path : Optional[str]
        If set, written to ALIGNREF on the output stack (absolute path to the raw light used as alignment reference).

    Returns:
    --------
    ccdp.CCDData
        Integrated image (raw output by default)
    """
    if not files:
        raise IntegrationError("No input files provided")
    
    print(f"\nIntegrating {len(files)} images (standard method)")
    
    # Check sequence consistency
    if sequence_inconsistencies(files):
        print("Warning: Sequence has inconsistencies, proceeding anyway...")
    
    # Load images
    print(f"Loading images...")
    images = []
    
    for i, file_path in enumerate(files):
        if progress_callback:
            progress_callback(i / len(files))
            
        try:
            ccd = extract_ccd_data(file_path)
            images.append(ccd)
        except Exception as e:
            print(f"Warning: Error loading {file_path}: {e}")
            continue
    
    if not images:
        raise IntegrationError("No valid images to integrate")
    
    print(f"Integrating {len(images)} images...")
    
    # Use configured memory limit
    mem_limit = memory_limit or settings.INTEGRATION_MEMORY_LIMIT
    
    # Integrate using ccdproc
    try:
        if sigma_clip:
            stack = ccdp.combine(
                images,
                method=method,
                scale=scale,
                sigma_clip=True,
                sigma_clip_low_thresh=settings.SIGMA_LOW,
                sigma_clip_high_thresh=settings.SIGMA_HIGH,
                sigma_clip_func=np.ma.median,
                sigma_clip_dev_func=mad_std,
                mem_limit=mem_limit,
                unit='adu',
                dtype='float32'
            )
        else:
            stack = ccdp.combine(
                images,
                method=method,
                scale=scale,
                mem_limit=mem_limit,
                unit='adu',
                dtype='float32'
            )
        
        # Clean up metadata
        safe_set_metadata(stack.meta, 'COMBINED', True)
        safe_set_metadata(stack.meta, 'MOTION_TRACKED', False)
        safe_set_metadata(stack.meta, 'CHUNKED_PROCESSING', False)
        stack.uncertainty = None
        stack.mask = None
        stack.flags = None

        mean_date_obs = compute_mean_observation_time(files)
        if mean_date_obs:
            safe_set_metadata(stack.meta, 'DATE-OBS', mean_date_obs)

        safe_set_metadata(stack.meta, 'NCOMBINE', int(len(images)))
        try:
            for fp in files:
                try:
                    hdr0 = fits.getheader(fp, ext=0)
                    if 'FILTER' in hdr0:
                        safe_set_metadata(stack.meta, 'FILTER', hdr0['FILTER'])
                        break
                except Exception:
                    continue
        except Exception:
            pass

        if alignment_reference_raw_path:
            safe_set_metadata(stack.meta, 'ALIGNREF', str(Path(alignment_reference_raw_path).resolve()))

        print(f"✓ Integration complete")
        
        # Save if requested
        if output_path:
            print(f"Saving integrated image to {output_path}")
            stack.write(output_path, overwrite=True)
        
        if progress_callback:
            progress_callback(1.0)
            
        return stack
        
    except Exception as e:
        raise IntegrationError(f"Error during integration: {e}") 


