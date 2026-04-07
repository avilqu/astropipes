"""
Image integration module with motion tracking capabilities.

This module provides functions to integrate (stack) astronomical images while
keeping moving objects static based on ephemeris information. It combines
traditional WCS-based alignment with ephemeris-based motion tracking.
"""

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
from astropy import units as u
from astropy.stats import mad_std
from astropy.time import Time
import ccdproc as ccdp
from typing import List, Dict, Optional, Tuple, Union, Callable
from pathlib import Path
import warnings
from datetime import datetime
import os

# Import configuration
from config import (SIGMA_LOW, SIGMA_HIGH, TESTED_FITS_CARDS, 
                   INTEGRATION_MEMORY_LIMIT, INTEGRATION_CHUNK_SIZE, INTEGRATION_ENABLE_CHUNKED,
                   MOTION_TRACKING_SIGMA_CLIP, MOTION_TRACKING_METHOD)

# Memory management configuration
MEMORY_LIMIT = INTEGRATION_MEMORY_LIMIT
CHUNK_SIZE = INTEGRATION_CHUNK_SIZE
ENABLE_CHUNKED_PROCESSING = INTEGRATION_ENABLE_CHUNKED

# Import ephemeris functionality
from lib.sci.orbit import predict_position_findorb


class MotionTrackingIntegrationError(Exception):
    """Exception raised for errors in motion tracking integration."""
    pass


def check_sequence_consistency(files: List[str]) -> bool:
    """
    Check consistency of FITS sequence before integration.
    
    Parameters:
    -----------
    files : List[str]
        List of FITS file paths
        
    Returns:
    --------
    bool
        True if sequence is consistent, False otherwise
    """
    if not files:
        raise MotionTrackingIntegrationError("No input files provided")
    
    print(f"\nChecking FITS sequence consistency for {len(files)} files...")
    
    # Read headers
    headers = []
    for file_path in files:
        try:
            header = fits.getheader(file_path, ext=0)
            headers.append(header)
        except Exception as e:
            print(f"Warning: Could not read header from {file_path}: {e}")
            return False
    
    # Check consistency for each tested card
    res = True
    for card_config in TESTED_FITS_CARDS:
        card_name = card_config['name']
        tolerance = card_config['tolerance']
        
        values = []
        for header in headers:
            if card_name in header:
                values.append(header[card_name])
            else:
                print(f"Warning: Missing header card '{card_name}' in some files")
                res = False
                break
        
        if not values:
            continue
            
        if tolerance == 0:
            # Exact match required
            if len(set(values)) > 1:
                print(f"Warning: Multiple {card_name} values in sequence: {set(values)}")
                res = False
            else:
                print(f"✓ {card_name} values are consistent: {values[0]}")
        else:
            # Allow tolerance
            average = np.mean(values)
            max_deviation = max(abs(val - average) for val in values)
            print(f"✓ {card_name} average: {average:.2f}, max deviation: {max_deviation:.2f}")
            if max_deviation > tolerance:
                print(f"Warning: {card_name} values exceed tolerance")
                res = False
    
    if res:
        print("✓ FITS sequence is consistent")
    else:
        print("✗ FITS sequence has inconsistencies")
    
    return res


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
        raise MotionTrackingIntegrationError(f"Could not read {file_path}: {e}")


def get_observation_time(file_path: str) -> Optional[str]:
    """
    Extract observation time from FITS file.
    
    Parameters:
    -----------
    file_path : str
        Path to FITS file
        
    Returns:
    --------
    Optional[str]
        ISO format observation time string, or None if not found
    """
    try:
        header = fits.getheader(file_path, ext=0)
        date_obs = header.get('DATE-OBS')
        
        if not date_obs:
            return None
            
        # Format to ISO string
        import re
        from datetime import datetime
        
        match = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::(\d{2}))?", date_obs)
        if match:
            seconds = match.group(3) if match.group(3) is not None else '00'
            return f"{match.group(1)}T{match.group(2)}:{seconds}"
        else:
            # Fallback parsing
            try:
                dt = datetime.fromisoformat(date_obs.replace('Z', '+00:00'))
                return dt.strftime('%Y-%m-%dT%H:%M:%S')
            except Exception:
                return date_obs[:10] + 'T' + date_obs[11:16] + ':00'
                
    except Exception as e:
        print(f"Warning: Could not extract observation time from {file_path}: {e}")
        return None


def get_mid_exposure_time(file_path: str) -> Optional[str]:
    """
    Extract mid-exposure time from FITS file (start time + half exposure time).
    
    Parameters:
    -----------
    file_path : str
        Path to FITS file
        
    Returns:
    --------
    Optional[str]
        ISO format mid-exposure time string, or None if not found
    """
    try:
        header = fits.getheader(file_path, ext=0)
        date_obs = header.get('DATE-OBS')
        
        if not date_obs:
            return None
            
        # Get exposure time
        exp_sec = header.get('EXPTIME') or header.get('EXPOSURE') or header.get('EXP TIME') or 0.0
        try:
            exp_sec = float(exp_sec)
        except Exception:
            exp_sec = 0.0
        
        # Parse the start time
        import re
        from datetime import datetime, timedelta
        
        match = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::(\d{2}))?", date_obs)
        if match:
            seconds = match.group(3) if match.group(3) is not None else '00'
            start_time_str = f"{match.group(1)}T{match.group(2)}:{seconds}"
        else:
            # Fallback parsing
            try:
                dt = datetime.fromisoformat(date_obs.replace('Z', '+00:00'))
                start_time_str = dt.strftime('%Y-%m-%dT%H:%M:%S')
            except Exception:
                start_time_str = date_obs[:10] + 'T' + date_obs[11:16] + ':00'
        
        # Calculate mid-exposure time
        start_dt = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        mid_dt = start_dt + timedelta(seconds=exp_sec / 2.0)
        
        return mid_dt.strftime('%Y-%m-%dT%H:%M:%S')
                
    except Exception as e:
        print(f"Warning: Could not extract mid-exposure time from {file_path}: {e}")
        return None


def compute_mid_observation_time(files: List[str]) -> Optional[str]:
    """
    Compute the midpoint DATE-OBS for a sequence of FITS files.

    The midpoint is defined as halfway between the beginning of the first
    exposure and the end of the last exposure.  The end of the last exposure
    is calculated as DATE-OBS(last) + EXPTIME(last).
    
    Parameters
    ----------
    files : List[str]
        List of FITS filenames. They do not need to be sorted chronologically.

    Returns
    -------
    Optional[str]
        Mid-point observation time in ISO 8601 format (UTC) or ``None`` if it
        cannot be determined.
    """
    if not files:
        return None

    try:
        from astropy.io import fits  # Local import keeps import-time deps minimal
        from astropy.time import Time, TimeDelta

        min_start = None
        max_end = None

        for fp in files:
            try:
                hdr = fits.getheader(fp, ext=0)
            except Exception:
                continue

            date_obs = hdr.get('DATE-OBS')
            if not date_obs:
                continue

            try:
                t_start = Time(date_obs, format='isot', scale='utc')
            except Exception:
                # Skip unparsable DATE-OBS values
                continue

            # Exposure keyword variants
            exp_sec = hdr.get('EXPTIME') or hdr.get('EXPOSURE') or hdr.get('EXP TIME') or 0.0
            try:
                exp_sec = float(exp_sec)
            except Exception:
                exp_sec = 0.0

            t_end = t_start + TimeDelta(exp_sec, format='sec')

            if min_start is None or t_start < min_start:
                min_start = t_start
            if max_end is None or t_end > max_end:
                max_end = t_end

        if min_start is None or max_end is None:
            return None

        t_mid = min_start + (max_end - min_start) / 2
        return t_mid.isot

    except Exception as exc:
        print(f"Warning: could not compute midpoint DATE-OBS: {exc}")
        return None


def compute_mean_observation_time(files: List[str]) -> Optional[str]:
    """
    Mean of each input file's DATE-OBS (exposure start), as an ISO-8601 UTC string.

    Used for combined stacks so DATE-OBS reflects the set of frames, not a single
    reference header.
    """
    if not files:
        return None

    mjds = []
    for fp in files:
        try:
            hdr = fits.getheader(fp, ext=0)
        except Exception:
            continue
        date_obs = hdr.get('DATE-OBS')
        if not date_obs:
            continue
        try:
            t = Time(date_obs, format='isot', scale='utc')
        except Exception:
            try:
                t = Time(date_obs)
            except Exception:
                continue
        mjds.append(t.mjd)

    if not mjds:
        return None

    try:
        mean_mjd = float(np.mean(mjds))
        t_mean = Time(mean_mjd, format='mjd', scale='utc')
        return t_mean.isot
    except Exception as exc:
        print(f"Warning: could not compute mean DATE-OBS: {exc}")
        return None


def _copy_wcs_header(source_header, *, ra_mid: Optional[float] = None, dec_mid: Optional[float] = None, pad: Tuple[int,int,int,int] = (0,0,0,0)) -> dict:
    """Return a WCS header dictionary copied from *source_header*.

    The resulting header contains only WCS keywords.  Optionally override
    CRVAL1/2 with *ra_mid*, *dec_mid* and adjust CRPIX1/2 for any padding
    applied to the image data (left, right, top, bottom).
    """
    try:
        from astropy.wcs import WCS
        wcs_obj = WCS(source_header)
        hdr_out = wcs_obj.to_header()
    except Exception:
        # Fallback to manual subset of common keys
        wcs_keys = [k for k in source_header.keys() if k.startswith(('CRV', 'CRP', 'CTYP', 'CUNI', 'CD', 'PC', 'CDELT', 'CROTA'))]
        hdr_out = {k: source_header[k] for k in wcs_keys}

    # Override pointing if requested
    if ra_mid is not None and dec_mid is not None:
        hdr_out['CRVAL1'] = ra_mid
        hdr_out['CRVAL2'] = dec_mid

    # Adjust CRPIX for padding (left, right, top, bottom)
    left, right, top, bottom = pad
    if left or top:
        # Astropy uses 1-based pixel coordinates in headers
        if 'CRPIX1' in hdr_out:
            hdr_out['CRPIX1'] += left
        if 'CRPIX2' in hdr_out:
            hdr_out['CRPIX2'] += top
    return hdr_out


def compute_mid_wcs(files: List[str]) -> Optional[Tuple[float, float]]:
    """Compute the RA/Dec (CRVAL1/2) at the mid-point of the observing window.

    The mid-point is defined in the same way as for DATE-OBS: halfway between
    the start of the first exposure and the end of the last exposure.  We
    assume the plate scale and rotation are constant during the sequence so we
    only interpolate the pointing (CRVAL).  The function returns a tuple
    ``(ra_deg, dec_deg)`` in ICRS or ``None`` if the information cannot be
    derived.
    """
    if not files:
        return None

    try:
        from astropy.io import fits
        from astropy.time import Time, TimeDelta
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        import numpy as np

        min_start = None  # Earliest exposure start
        min_crval = None
        max_end = None    # Latest exposure end
        max_crval = None

        for fp in files:
            try:
                hdr = fits.getheader(fp, ext=0)
            except Exception:
                continue

            # --- timing
            date_obs = hdr.get('DATE-OBS')
            if not date_obs:
                continue
            try:
                t_start = Time(date_obs, format='isot', scale='utc')
            except Exception:
                continue

            exp_sec = hdr.get('EXPTIME') or hdr.get('EXPOSURE') or hdr.get('EXP TIME') or 0.0
            try:
                exp_sec = float(exp_sec)
            except Exception:
                exp_sec = 0.0
            t_end = t_start + TimeDelta(exp_sec, format='sec')

            # --- pointing
            ra = hdr.get('CRVAL1')
            dec = hdr.get('CRVAL2')
            if ra is None or dec is None:
                continue

            if min_start is None or t_start < min_start:
                min_start = t_start
                min_crval = (float(ra), float(dec))
            if max_end is None or t_end > max_end:
                max_end = t_end
                max_crval = (float(ra), float(dec))

        if min_start is None or max_end is None or min_crval is None or max_crval is None:
            return None

        # Spherical interpolation between the two pointings
        c1 = SkyCoord(min_crval[0]*u.deg, min_crval[1]*u.deg, frame='icrs')
        c2 = SkyCoord(max_crval[0]*u.deg, max_crval[1]*u.deg, frame='icrs')

        # Work in Cartesian space to avoid RA wrap problems
        v1 = c1.cartesian.xyz.value
        v2 = c2.cartesian.xyz.value
        v_mid = v1 + v2
        norm = np.linalg.norm(v_mid)
        if norm == 0:
            return min_crval  # identical vectors – just use one of them
        v_mid /= norm

        c_mid = SkyCoord(x=v_mid[0], y=v_mid[1], z=v_mid[2], representation_type='cartesian', frame='icrs')
        return (c_mid.ra.deg, c_mid.dec.deg)

    except Exception as exc:
        print(f"Warning: could not compute midpoint WCS: {exc}")
        return None


def calculate_motion_shifts(files: List[str], object_name: str, 
                          reference_time: Optional[str] = None,
                          ephemerides_data: Optional[List[Dict]] = None) -> Tuple[List[Tuple[float, float]], Optional[Tuple[float, float]]]:
    """
    Calculate pixel shifts needed to keep moving object static using motion rate and position angle.
    
    Parameters:
    -----------
    files : List[str]
        List of FITS file paths
    object_name : str
        Name of the moving object
    reference_time : Optional[str]
        Reference time for object position (ISO format). If None, uses first image.
    ephemerides_data : Optional[List[Dict]]
        Pre-computed ephemerides data. If provided, this will be used instead of calling FindOrb API.
        Each dict should contain 'date_obs', 'RA', 'Dec', 'motion_rate', 'motionPA' keys.
        
    Returns:
    --------
    Tuple[List[Tuple[float, float]], Optional[Tuple[float, float]]]
        List of (dx, dy) shifts for each image, and the reference position (x, y) in the first image
    """
    print(f"\nCalculating motion shifts for object {object_name} using motion rate and position angle...")

    from datetime import datetime
    import numpy as np
    from pathlib import Path
    from astropy.wcs import WCS
    from astropy.io import fits
    import astropy.units as u

    shifts = []
    ephemeris_data = []
    observation_times = []
    obs_time_map = {}  # Map file_path to obs_time
    obs_dt_map = {}    # Map file_path to obs_dt

    # First pass: collect all observation times (using mid-exposure time for precision)
    for i, file_path in enumerate(files):
        print(f"Collecting mid-exposure time for {i+1}/{len(files)}: {Path(file_path).name}")
        obs_time = get_mid_exposure_time(file_path)
        if not obs_time:
            print(f"Warning: No mid-exposure time for {file_path}, using zero shift")
            shifts.append((0.0, 0.0))
            continue
        try:
            if 'T' in obs_time:
                obs_dt = datetime.fromisoformat(obs_time.replace('Z', '+00:00'))
            else:
                obs_dt = datetime.strptime(obs_time, '%Y-%m-%d %H:%M:%S')
            observation_times.append(obs_time)
            obs_time_map[file_path] = obs_time
            obs_dt_map[file_path] = obs_dt
        except Exception as e:
            print(f"Warning: Could not parse mid-exposure time for {file_path}: {e}")
            shifts.append((0.0, 0.0))
            continue

    if not observation_times:
        print("Warning: No valid mid-exposure times found")
        return [(0.0, 0.0)] * len(files), None

    # Use provided ephemerides data if available, otherwise call FindOrb API
    if ephemerides_data is not None:
        print(f"Using provided ephemerides data for {len(ephemerides_data)} entries")
        result = {}
        for entry in ephemerides_data:
            date_obs = entry.get('date_obs')
            if date_obs:
                result[date_obs] = entry
    else:
        print("No ephemerides data provided, calling FindOrb API...")
        # Call predict_position_findorb ONCE for all mid-exposure times
        try:
            result = predict_position_findorb(object_name, observation_times)
        except Exception as e:
            print(f"Warning: Error getting ephemeris for all files: {e}")
            return [(0.0, 0.0)] * len(files), None

    # Gather motion rates and PAs from all results
    motion_rates = []
    motion_pas = []
    for file_path in files:
        obs_time = obs_time_map.get(file_path)
        if not obs_time or not result or obs_time not in result:
            print(f"Warning: No ephemeris result for {file_path}, using zero shift")
            shifts.append((0.0, 0.0))
            continue
        entry = result[obs_time]
        motion_rate = entry.get('motion_rate')
        motion_pa = entry.get('motionPA')
        if motion_rate is not None and motion_pa is not None:
            # Convert motion rate from arcsec/minute to arcsec/hour
            motion_rate_arcsec_per_hour = float(motion_rate) * 60.0
            motion_rates.append(motion_rate_arcsec_per_hour)
            motion_pas.append(float(motion_pa))
            ephemeris_data.append({
                'file_path': file_path,
                'obs_time': obs_time,
                'obs_dt': obs_dt_map[file_path],
            })
            print(f"  Motion rate: {motion_rate:.2f} arcsec/min = {motion_rate_arcsec_per_hour:.2f} arcsec/hour, PA: {motion_pa:.1f}°")
        else:
            print(f"Warning: Missing motion data for {file_path}")
            shifts.append((0.0, 0.0))
            continue

    if not ephemeris_data or not motion_rates or not motion_pas:
        print("Warning: No valid ephemeris data found")
        return [(0.0, 0.0)] * len(files), None

    avg_motion_rate = np.mean(motion_rates)
    avg_motion_pa = np.mean(motion_pas)

    print(f"\nAverage motion rate: {avg_motion_rate:.2f} arcsec/hour")
    print(f"Average motion position angle: {avg_motion_pa:.1f}°")
    print(f"Motion PA range: {min(motion_pas):.1f}° to {max(motion_pas):.1f}°")
    print(f"Motion rate range: {min(motion_rates):.2f} to {max(motion_rates):.2f} arcsec/hour")
    
    # Test coordinate system interpretation
    test_pa_rad = np.radians(avg_motion_pa)
    test_motion = 100.0  # arcsec
    test_dra = test_motion * np.cos(test_pa_rad)
    test_ddec = test_motion * np.sin(test_pa_rad)
    print(f"Test: For 100 arcsec motion at PA {avg_motion_pa:.1f}°:")
    print(f"  RA component: {test_dra:.1f} arcsec")
    print(f"  Dec component: {test_ddec:.1f} arcsec")
    print(f"  Ratio Dec/RA: {test_ddec/test_dra:.2f}")

    # Set reference time
    if reference_time is None:
        reference_time_dt = min(data['obs_dt'] for data in ephemeris_data)
        print(f"Using earliest observation time as reference: {reference_time_dt}")
    else:
        try:
            if 'T' in reference_time:
                reference_time_dt = datetime.fromisoformat(reference_time.replace('Z', '+00:00'))
            else:
                reference_time_dt = datetime.strptime(reference_time, '%Y-%m-%d %H:%M:%S')
            print(f"Using specified reference time: {reference_time_dt}")
        except Exception as e:
            print(f"Warning: Could not parse reference time, using earliest observation: {e}")
            reference_time_dt = min(data['obs_dt'] for data in ephemeris_data)

    print(f"\nCalculating shifts relative to reference time...")
    shifts = []
    reference_object_pixel = None # Initialize reference_object_pixel
    for file_path in files:
        # Find corresponding ephemeris data
        file_data = next((data for data in ephemeris_data if data['file_path'] == file_path), None)
        if not file_data:
            print(f"Warning: No ephemeris data found for {file_path}, using zero shift")
            shifts.append((0.0, 0.0))
            continue
        time_diff_hours = (file_data['obs_dt'] - reference_time_dt).total_seconds() / 3600.0
        angular_motion_arcsec = avg_motion_rate * time_diff_hours
        motion_pa_rad = np.radians(avg_motion_pa)
        
        # Try different coordinate system interpretations
        # Method 1: Standard astronomical PA (North=0°, East=90°)
        dra_arcsec = angular_motion_arcsec * np.cos(motion_pa_rad)
        ddec_arcsec = angular_motion_arcsec * np.sin(motion_pa_rad)
        
        # Method 2: Alternative interpretation (if Method 1 doesn't work)
        # dra_arcsec_alt = angular_motion_arcsec * np.sin(motion_pa_rad)
        # ddec_arcsec_alt = angular_motion_arcsec * np.cos(motion_pa_rad)
        
        # Method 3: Try swapping cos/sin (if PA is defined differently)
        # dra_arcsec_alt2 = angular_motion_arcsec * np.sin(motion_pa_rad)
        # ddec_arcsec_alt2 = angular_motion_arcsec * np.cos(motion_pa_rad)
        
        # For now, use Method 1 but add debugging
        if len(shifts) < 3:
            print(f"  Using standard PA interpretation: cos({avg_motion_pa:.1f}°) for RA, sin({avg_motion_pa:.1f}°) for Dec")
        
        try:
            wcs = WCS(fits.getheader(file_path, ext=0))
            if wcs.is_celestial:
                # Get pixel scale for debugging
                pixel_scale = wcs.pixel_scale_matrix.diagonal()
                pixel_scale_arcsec = (pixel_scale * u.deg).to(u.arcsec).value
                
                # Debug output for first few images
                if len(shifts) < 3:
                    print(f"  Motion PA: {avg_motion_pa:.1f}° ({motion_pa_rad:.3f} rad)")
                    print(f"  RA component: {dra_arcsec:.2f} arcsec")
                    print(f"  Dec component: {ddec_arcsec:.2f} arcsec")
                    print(f"  Pixel scale: {pixel_scale_arcsec[0]:.3f} arcsec/pix (RA), {pixel_scale_arcsec[1]:.3f} arcsec/pix (Dec)")
                    print(f"  Using WCS transformation for shift calculation")
                
                # Convert celestial motion to pixel shifts using WCS transformation
                # We need to calculate where the object should be in this image
                # and shift it to a fixed reference position
                
                # Get the object's predicted position for this image from the ephemeris
                obs_time = file_data['obs_time']
                if obs_time in result:
                    object_entry = result[obs_time]
                    object_ra = object_entry.get('RA')
                    object_dec = object_entry.get('Dec')
                    
                    if object_ra is not None and object_dec is not None:
                        # Convert object position to pixel coordinates
                        object_pixel = wcs.wcs_world2pix([[object_ra, object_dec]], 0)[0]
                        
                        # Use the first image's object position as the reference
                        if len(shifts) == 0:
                            # This is the reference image - no shift needed
                            reference_object_pixel = object_pixel
                            dx_pix = 0.0
                            dy_pix = 0.0
                        else:
                            # Calculate shift to move object to reference position
                            dx_pix = reference_object_pixel[0] - object_pixel[0]
                            dy_pix = reference_object_pixel[1] - object_pixel[1]
                        
                        # Additional debug for first few images
                        if len(shifts) < 3:
                            print(f"  Object RA/Dec: {object_ra:.6f}°, {object_dec:.6f}°")
                            print(f"  Object pixel: ({object_pixel[0]:.2f}, {object_pixel[1]:.2f})")
                            if len(shifts) == 0:
                                print(f"  Reference object pixel: ({reference_object_pixel[0]:.2f}, {reference_object_pixel[1]:.2f})")
                            else:
                                print(f"  Reference object pixel: ({reference_object_pixel[0]:.2f}, {reference_object_pixel[1]:.2f})")
                    else:
                        print(f"Warning: No RA/Dec in ephemeris for {file_path}")
                        dx_pix = 0.0
                        dy_pix = 0.0
                else:
                    print(f"Warning: No ephemeris entry for {file_path}")
                    dx_pix = 0.0
                    dy_pix = 0.0
                
                shifts.append((dx_pix, dy_pix))
                print(f"  Time diff: {time_diff_hours:.3f} hours")
                print(f"  Angular motion: {angular_motion_arcsec:.2f} arcsec")
                print(f"  Shift: dx={dx_pix:.2f} pix, dy={dy_pix:.2f} pix")
            else:
                print(f"Warning: No valid WCS in {file_path}")
                shifts.append((0.0, 0.0))
        except Exception as e:
            print(f"Warning: Error calculating pixel shift for {file_path}: {e}")
            print(f"Exception details: {type(e).__name__}: {str(e)}")
            shifts.append((0.0, 0.0))
    return shifts, reference_object_pixel


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


def calculate_required_padding(shifts: List[Tuple[float, float]]) -> Tuple[int, int, int, int]:
    """
    Calculate the required padding for motion tracking integration.
    
    Parameters:
    -----------
    shifts : List[Tuple[float, float]]
        List of (dx, dy) shifts for each image
        
    Returns:
    --------
    Tuple[int, int, int, int]
        Padding required: (left, right, top, bottom) in pixels
    """
    if not shifts:
        return (0, 0, 0, 0)
    
    # Find the maximum shifts in each direction
    max_dx_positive = max(0, max(dx for dx, dy in shifts))
    max_dx_negative = max(0, max(-dx for dx, dy in shifts))
    max_dy_positive = max(0, max(dy for dx, dy in shifts))
    max_dy_negative = max(0, max(-dy for dx, dy in shifts))
    
    # Add some extra padding for interpolation artifacts
    extra_padding = 2
    
    return (
        int(max_dx_positive) + extra_padding,  # left
        int(max_dx_negative) + extra_padding,  # right
        int(max_dy_positive) + extra_padding,  # top
        int(max_dy_negative) + extra_padding   # bottom
    )


def pad_image_for_motion_tracking(image: np.ndarray, padding: Tuple[int, int, int, int]) -> np.ndarray:
    """
    Pad an image for motion tracking to ensure all shifted positions have valid data.
    
    Parameters:
    -----------
    image : np.ndarray
        Input image array
    padding : Tuple[int, int, int, int]
        Padding: (left, right, top, bottom) in pixels
        
    Returns:
    --------
    np.ndarray
        Padded image
    """
    left, right, top, bottom = padding
    
    if left == 0 and right == 0 and top == 0 and bottom == 0:
        return image
    
    # Use 'constant' mode with edge values - this is widely supported
    # Get the edge values to use as fill
    if top > 0:
        top_val = image[0, :]
    if bottom > 0:
        bottom_val = image[-1, :]
    if left > 0:
        left_val = image[:, 0]
    if right > 0:
        right_val = image[:, -1]
    
    # Create padded array
    padded = np.zeros((image.shape[0] + top + bottom, image.shape[1] + left + right), dtype=image.dtype)
    
    # Copy original image to center
    padded[top:top+image.shape[0], left:left+image.shape[1]] = image
    
    # Fill borders with edge values
    if top > 0:
        for i in range(top):
            padded[i, left:left+image.shape[1]] = top_val
    if bottom > 0:
        for i in range(bottom):
            padded[top+image.shape[0]+i, left:left+image.shape[1]] = bottom_val
    if left > 0:
        for j in range(left):
            padded[top:top+image.shape[0], j] = left_val
    if right > 0:
        for j in range(right):
            padded[top:top+image.shape[0], left+image.shape[1]+j] = right_val
    
    return padded


def shift_image(image: np.ndarray, dx: float, dy: float, 
                interpolation: str = 'bilinear') -> np.ndarray:
    """
    Shift an image by the specified pixel offsets.
    
    Parameters:
    -----------
    image : np.ndarray
        Input image array
    dx : float
        X-axis shift in pixels
    dy : float
        Y-axis shift in pixels
    interpolation : str
        Interpolation method ('bilinear', 'bicubic', 'nearest')
        
    Returns:
    --------
    np.ndarray
        Shifted image
    """
    from scipy.ndimage import shift
    
    if dx == 0 and dy == 0:
        return image
    
    # Use 'constant' mode with the minimum value of the image
    # This avoids NaN values and is widely supported
    fill_value = np.nanmin(image) if np.isfinite(image).any() else 0.0
    shifted = shift(image, (dy, dx), order=1, mode='constant', cval=fill_value)
    
    return shifted


def integrate_chunked(files: List[str], 
                     object_name: str,
                     reference_time: Optional[str] = None,
                     method: str = 'average',
                     sigma_clip: bool = False,
                     scale: Optional[Callable] = None,
                     output_path: Optional[str] = None,
                     progress_callback: Optional[Callable] = None,
                     chunk_size: Optional[int] = None,
                     memory_limit: Optional[float] = None,
                     ephemerides_data: Optional[List[Dict]] = None) -> ccdp.CCDData:
    """
    Integrate images in chunks to prevent memory issues with large datasets.
    
    Parameters:
    -----------
    files : List[str]
        List of FITS file paths to integrate
    object_name : str
        Name of the moving object (e.g., '2025 BC')
    reference_time : Optional[str]
        Reference time for object position (ISO format). If None, uses first image.
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
    chunk_size : Optional[int]
        Number of images per chunk. If None, uses default CHUNK_SIZE.
    memory_limit : Optional[float]
        Memory limit in bytes. If None, uses default MEMORY_LIMIT.
    ephemerides_data : Optional[List[Dict]]
        Pre-computed ephemerides data. If provided, this will be used instead of calling FindOrb API.
        Each dict should contain 'date_obs', 'RA', 'Dec', 'motion_rate', 'motionPA' keys.
        
    Returns:
    --------
    ccdp.CCDData
        Integrated image with motion tracking applied (raw output by default)
    """
    if not files:
        raise MotionTrackingIntegrationError("No input files provided")
    
    # Use defaults if not specified
    chunk_size = chunk_size or CHUNK_SIZE
    memory_limit = memory_limit or MEMORY_LIMIT
    
    print(f"\nIntegrating {len(files)} images with chunked processing")
    print(f"Chunk size: {chunk_size} images")
    print(f"Memory limit: {memory_limit / 1e9:.1f} GB")
    
    # Check sequence consistency
    if not check_sequence_consistency(files):
        print("Warning: Sequence has inconsistencies, proceeding anyway...")
    
    # Calculate motion shifts for all files
    shifts, reference_object_pixel = calculate_motion_shifts(files, object_name, reference_time, ephemerides_data)
    
    # Calculate required padding
    padding = calculate_required_padding(shifts)
    print(f"Required padding: {padding}")
    
    # Get original image shape for cropping
    try:
        original_shape = extract_ccd_data(files[0]).data.shape
        print(f"Original image shape: {original_shape}")
    except Exception as e:
        print(f"Warning: Could not determine original shape: {e}")
        original_shape = None

    # Process in chunks
    total_chunks = (len(files) + chunk_size - 1) // chunk_size
    chunk_results = []
    
    # Store shift information for later reversal
    shift_info = []
    
    for chunk_idx in range(total_chunks):
        start_idx = chunk_idx * chunk_size
        end_idx = min(start_idx + chunk_size, len(files))
        chunk_files = files[start_idx:end_idx]
        chunk_shifts = shifts[start_idx:end_idx]
        
        print(f"\nProcessing chunk {chunk_idx + 1}/{total_chunks} ({len(chunk_files)} images)")
        
        # Load and shift images for this chunk
        shifted_images = []
        chunk_processed = 0
        chunk_skipped = 0
        
        for i, (file_path, (dx, dy)) in enumerate(zip(chunk_files, chunk_shifts)):
            if progress_callback:
                overall_progress = (chunk_idx * chunk_size + i) / len(files)
                progress_callback(overall_progress)
                
            print(f"  Processing {start_idx + i + 1}/{len(files)}: {Path(file_path).name}")
            
            try:
                # Load image
                ccd = extract_ccd_data(file_path)
                
                # Store shift information for this image
                shift_info.append({
                    'file_path': file_path,
                    'shift_x': dx,
                    'shift_y': dy,
                    'index': start_idx + i
                })
                
                # Pad image
                padded_data = pad_image_for_motion_tracking(ccd.data, padding)
                ccd.data = padded_data
                print(f"    Padded image: {ccd.data.shape} -> {padded_data.shape}")
                
                # Apply shift
                if dx != 0 or dy != 0:
                    shifted_data = shift_image(ccd.data, dx, dy)
                    ccd.data = shifted_data
                    print(f"    Applied shift: dx={dx:.2f}, dy={dy:.2f}")
                
                shifted_images.append(ccd)
                chunk_processed += 1
                
            except Exception as e:
                print(f"Warning: Error processing {file_path}: {e}")
                chunk_skipped += 1
                continue
        
        print(f"  Chunk {chunk_idx + 1} summary: {chunk_processed} processed, {chunk_skipped} skipped")
        
        if not shifted_images:
            print(f"Warning: No valid images in chunk {chunk_idx + 1}")
            continue
        
        # Integrate this chunk
        print(f"  Integrating chunk {chunk_idx + 1} ({len(shifted_images)} images)...")
        try:
            if sigma_clip:
                chunk_stack = ccdp.combine(
                    shifted_images,
                    method=method,
                    scale=scale,
                    sigma_clip=True,
                    sigma_clip_low_thresh=SIGMA_LOW,
                    sigma_clip_high_thresh=SIGMA_HIGH,
                    sigma_clip_func=np.ma.median,
                    sigma_clip_dev_func=mad_std,
                    mem_limit=memory_limit,
                    unit='adu',
                    dtype='float32'
                )
            else:
                chunk_stack = ccdp.combine(
                    shifted_images,
                    method=method,
                    scale=scale,
                    mem_limit=memory_limit,
                    unit='adu',
                    dtype='float32'
                )
            
            # Add chunk metadata
            safe_set_metadata(chunk_stack.meta, 'CHUNK_ID', chunk_idx)
            safe_set_metadata(chunk_stack.meta, 'CHUNK_SIZE', len(shifted_images))
            safe_set_metadata(chunk_stack.meta, 'TOTAL_CHUNKS', total_chunks)
            
            chunk_results.append(chunk_stack)
            
            # Clear memory
            del shifted_images
            import gc
            gc.collect()
            
        except Exception as e:
            print(f"Error integrating chunk {chunk_idx + 1}: {e}")
            continue
    
    if not chunk_results:
        raise MotionTrackingIntegrationError("No valid chunks to integrate")
    
    # Combine all chunks
    print(f"\nCombining {len(chunk_results)} chunks...")
    try:
        if len(chunk_results) == 1:
            # Only one chunk, use it directly
            final_stack = chunk_results[0]
        else:
            # Multiple chunks, combine them
            if sigma_clip:
                final_stack = ccdp.combine(
                    chunk_results,
                    method=method,
                    scale=scale,
                    sigma_clip=True,
                    sigma_clip_low_thresh=SIGMA_LOW,
                    sigma_clip_high_thresh=SIGMA_HIGH,
                    sigma_clip_func=np.ma.median,
                    sigma_clip_dev_func=mad_std,
                    mem_limit=memory_limit,
                    unit='adu',
                    dtype='float32'
                )
            else:
                final_stack = ccdp.combine(
                    chunk_results,
                    method=method,
                    scale=scale,
                    mem_limit=memory_limit,
                    unit='adu',
                    dtype='float32'
                )
        
        # Clean up metadata
        safe_set_metadata(final_stack.meta, 'COMBINED', True)
        safe_set_metadata(final_stack.meta, 'MOTION_TRACKED', True)
        safe_set_metadata(final_stack.meta, 'TRACKED_OBJECT', object_name)
        safe_set_metadata(final_stack.meta, 'CHUNKED_PROCESSING', True)
        safe_set_metadata(final_stack.meta, 'TOTAL_CHUNKS', total_chunks)
        if reference_time:
            safe_set_metadata(final_stack.meta, 'REFERENCE_TIME', reference_time)
        
        # Store shift information in header for later reversal
        import json
        safe_set_metadata(final_stack.meta, 'MOTION_SHIFTS', json.dumps(shift_info))
        safe_set_metadata(final_stack.meta, 'ORIGINAL_FILES', json.dumps(files))
        safe_set_metadata(final_stack.meta, 'PADDING', json.dumps(padding))
        
        # Update DATE-OBS and WCS to the midpoint of the observing window
        # Always attempt to propagate WCS from one of the input frames
        try:
            from astropy.io import fits as _fits_
            base_hdr = None
            for _fp in files:
                try:
                    _hdr_tmp = _fits_.getheader(_fp, ext=0)
                except Exception:
                    continue
                if 'CRVAL1' in _hdr_tmp and 'CRVAL2' in _hdr_tmp:
                    base_hdr = _hdr_tmp
                    break
            if base_hdr is not None:
                mid_wcs = compute_mid_wcs(files)
                if mid_wcs:
                    ra_mid, dec_mid = mid_wcs
                    wcs_hdr = _copy_wcs_header(base_hdr, ra_mid=ra_mid, dec_mid=dec_mid, pad=padding)
                    safe_set_metadata(final_stack.meta, 'MID_WCS', True)
                else:
                    wcs_hdr = _copy_wcs_header(base_hdr, pad=padding)
                for _k, _v in wcs_hdr.items():
                    safe_set_metadata(final_stack.meta, _k, _v)
                # Ensure DATE-OBS reflects midpoint
                mid_obs_time = compute_mid_observation_time(files)
                if mid_obs_time:
                    safe_set_metadata(final_stack.meta, 'DATE-OBS', mid_obs_time)
            else:
                print("Warning: No WCS found in any input file; stack will have no WCS.")
        except Exception as _e:
            print(f"Warning: could not copy WCS header: {_e}")
        
        # Store reference position if available
        if reference_object_pixel is not None:
            # Convert numpy array to list for JSON serialization
            reference_position_list = reference_object_pixel.tolist() if hasattr(reference_object_pixel, 'tolist') else list(reference_object_pixel)
            safe_set_metadata(final_stack.meta, 'REFERENCE_POSITION', json.dumps(reference_position_list))
        
        final_stack.uncertainty = None
        final_stack.mask = None
        final_stack.flags = None
        
        # Remove chunk-specific metadata
        for key in ['CHUNK_ID', 'CHUNK_SIZE']:
            if key in final_stack.meta:
                del final_stack.meta[key]
        
        print(f"✓ Chunked integration complete")
        
        # Crop the result to restore original dimensions
        if original_shape is not None and padding != (0, 0, 0, 0):
            final_stack = crop_integrated_image(final_stack, original_shape, padding)
        
        # Save if requested
        if output_path:
            print(f"Saving integrated image to {output_path}")
            final_stack.write(output_path, overwrite=True)
        
        if progress_callback:
            progress_callback(1.0)
            
        return final_stack
        
    except Exception as e:
        raise MotionTrackingIntegrationError(f"Error during chunk combination: {e}")


def integrate_with_motion_tracking(files: List[str], 
                                 object_name: str,
                                 reference_time: Optional[str] = None,
                                 method: str = 'average',
                                 sigma_clip: bool = False,
                                 scale: Optional[Callable] = None,
                                 output_path: Optional[str] = None,
                                 progress_callback: Optional[Callable] = None,
                                 force_chunked: bool = False,
                                 chunk_size: Optional[int] = None,
                                 memory_limit: Optional[float] = None,
                                 ephemerides_data: Optional[List[Dict]] = None) -> ccdp.CCDData:
    """
    Integrate a sequence of images while keeping a moving object static.
    
    Parameters:
    -----------
    files : List[str]
        List of FITS file paths to integrate
    object_name : str
        Name of the moving object (e.g., '2025 BC')
    reference_time : Optional[str]
        Reference time for object position (ISO format). If None, uses first image.
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
    force_chunked : bool
        Force chunked processing even for small datasets
    chunk_size : Optional[int]
        Number of images per chunk for chunked processing
    memory_limit : Optional[float]
        Memory limit in bytes for processing
    ephemerides_data : Optional[List[Dict]]
        Pre-computed ephemerides data. If provided, this will be used instead of calling FindOrb API.
        Each dict should contain 'date_obs', 'RA', 'Dec', 'motion_rate', 'motionPA' keys.
        
    Returns:
    --------
    ccdp.CCDData
        Integrated image with motion tracking applied (raw output by default)
    """
    if not files:
        raise MotionTrackingIntegrationError("No input files provided")
    
    # Determine if we should use chunked processing.
    #
    # Rationale: median-of-medians yields incorrect results if the last chunk
    # contains only a handful of images (e.g. 1–2).  To avoid that artefact we
    # require that *at least two full chunks* are available before enabling
    # chunked processing automatically.  For small data sets we process all
    # frames in one go – this is fast and avoids the statistical bias.
    min_images_for_chunked = CHUNK_SIZE * 2  # needs ≥ two complete chunks
    use_chunked = force_chunked or (
        ENABLE_CHUNKED_PROCESSING and len(files) >= min_images_for_chunked
    )
    
    if use_chunked:
        print(f"Using chunked processing for {len(files)} images")
        return integrate_chunked(
            files=files,
            object_name=object_name,
            reference_time=reference_time,
            method=method,
            sigma_clip=sigma_clip,
            scale=scale,
            output_path=output_path,
            progress_callback=progress_callback,
            chunk_size=chunk_size,
            memory_limit=memory_limit
        )
    
    print(f"\nIntegrating {len(files)} images with motion tracking for {object_name}")
    
    # Check sequence consistency
    if not check_sequence_consistency(files):
        print("Warning: Sequence has inconsistencies, proceeding anyway...")
    
    # Calculate motion shifts
    shifts, reference_object_pixel = calculate_motion_shifts(files, object_name, reference_time, ephemerides_data)
    
    # Calculate required padding
    padding = calculate_required_padding(shifts)
    print(f"Required padding: {padding}")
    
    # Get original image shape for cropping
    try:
        original_shape = extract_ccd_data(files[0]).data.shape
        print(f"Original image shape: {original_shape}")
    except Exception as e:
        print(f"Warning: Could not determine original shape: {e}")
        original_shape = None

    # Load and shift images
    print(f"\nLoading and shifting images...")
    shifted_images = []
    processed_count = 0
    skipped_count = 0
    
    # Store shift information for later reversal
    shift_info = []
    
    for i, (file_path, (dx, dy)) in enumerate(zip(files, shifts)):
        if progress_callback:
            progress_callback(i / len(files))
            
        print(f"Processing {i+1}/{len(files)}: {Path(file_path).name}")
        
        try:
            # Load image
            ccd = extract_ccd_data(file_path)
            
            # Store shift information for this image
            shift_info.append({
                'file_path': file_path,
                'shift_x': dx,
                'shift_y': dy,
                'index': i
            })
            
            # Pad image
            padded_data = pad_image_for_motion_tracking(ccd.data, padding)
            ccd.data = padded_data
            print(f"  Padded image: {ccd.data.shape} -> {padded_data.shape}")

            # Apply shift
            if dx != 0 or dy != 0:
                shifted_data = shift_image(ccd.data, dx, dy)
                ccd.data = shifted_data
                print(f"  Applied shift: dx={dx:.2f}, dy={dy:.2f}")
            
            shifted_images.append(ccd)
            processed_count += 1
            
        except Exception as e:
            print(f"Warning: Error processing {file_path}: {e}")
            skipped_count += 1
            continue
    
    print(f"\nProcessing summary:")
    print(f"  Total files: {len(files)}")
    print(f"  Successfully processed: {processed_count}")
    print(f"  Skipped: {skipped_count}")
    
    if not shifted_images:
        raise MotionTrackingIntegrationError("No valid images to integrate")
    
    print(f"\nIntegrating {len(shifted_images)} shifted images...")
    
    # Use configured memory limit
    mem_limit = memory_limit or MEMORY_LIMIT
    
    # Integrate using ccdproc
    try:
        if sigma_clip:
            stack = ccdp.combine(
                shifted_images,
                method=method,
                scale=scale,
                sigma_clip=True,
                sigma_clip_low_thresh=SIGMA_LOW,
                sigma_clip_high_thresh=SIGMA_HIGH,
                sigma_clip_func=np.ma.median,
                sigma_clip_dev_func=mad_std,
                mem_limit=mem_limit,
                unit='adu',
                dtype='float32'
            )
        else:
            stack = ccdp.combine(
                shifted_images,
                method=method,
                scale=scale,
                mem_limit=mem_limit,
                unit='adu',
                dtype='float32'
            )
        
        # Clean up metadata
        safe_set_metadata(stack.meta, 'COMBINED', True)
        safe_set_metadata(stack.meta, 'MOTION_TRACKED', True)
        safe_set_metadata(stack.meta, 'TRACKED_OBJECT', object_name)
        safe_set_metadata(stack.meta, 'CHUNKED_PROCESSING', False)
        if reference_time:
            safe_set_metadata(stack.meta, 'REFERENCE_TIME', reference_time)
        
        # Store shift information in header for later reversal
        import json
        safe_set_metadata(stack.meta, 'MOTION_SHIFTS', json.dumps(shift_info))
        safe_set_metadata(stack.meta, 'ORIGINAL_FILES', json.dumps(files))
        safe_set_metadata(stack.meta, 'PADDING', json.dumps(padding))
        
        # Update DATE-OBS and WCS to the midpoint of the observing window
        # Always attempt to propagate WCS from one of the input frames
        try:
            from astropy.io import fits as _fits_
            base_hdr = None
            for _fp in files:
                try:
                    _hdr_tmp = _fits_.getheader(_fp, ext=0)
                except Exception:
                    continue
                if 'CRVAL1' in _hdr_tmp and 'CRVAL2' in _hdr_tmp:
                    base_hdr = _hdr_tmp
                    break
            if base_hdr is not None:
                mid_wcs = compute_mid_wcs(files)
                if mid_wcs:
                    ra_mid, dec_mid = mid_wcs
                    wcs_hdr = _copy_wcs_header(base_hdr, ra_mid=ra_mid, dec_mid=dec_mid, pad=padding)
                    safe_set_metadata(stack.meta, 'MID_WCS', True)
                else:
                    wcs_hdr = _copy_wcs_header(base_hdr, pad=padding)
                for _k, _v in wcs_hdr.items():
                    safe_set_metadata(stack.meta, _k, _v)
                # Finally, ensure DATE-OBS reflects true midpoint (may have been overwritten)
                mid_obs_time = compute_mid_observation_time(files)
                if mid_obs_time:
                    safe_set_metadata(stack.meta, 'DATE-OBS', mid_obs_time)
            else:
                print("Warning: No WCS found in any input file; stack will have no WCS.")
        except Exception as _e:
            print(f"Warning: could not copy WCS header: {_e}")
        
        # Store reference position if available
        if reference_object_pixel is not None:
            # Convert numpy array to list for JSON serialization
            reference_position_list = reference_object_pixel.tolist() if hasattr(reference_object_pixel, 'tolist') else list(reference_object_pixel)
            safe_set_metadata(stack.meta, 'REFERENCE_POSITION', json.dumps(reference_position_list))
        
        stack.uncertainty = None
        stack.mask = None
        stack.flags = None
        
        print(f"✓ Integration complete")
        
        # Crop the result to restore original dimensions
        if original_shape is not None and padding != (0, 0, 0, 0):
            stack = crop_integrated_image(stack, original_shape, padding)
        
        # Save if requested
        if output_path:
            print(f"Saving integrated image to {output_path}")
            stack.write(output_path, overwrite=True)
        
        if progress_callback:
            progress_callback(1.0)
            
        return stack
        
    except Exception as e:
        raise MotionTrackingIntegrationError(f"Error during integration: {e}")


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
        raise MotionTrackingIntegrationError("No input files provided")
    
    print(f"\nIntegrating {len(files)} images (standard method)")
    
    # Check sequence consistency
    if not check_sequence_consistency(files):
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
        raise MotionTrackingIntegrationError("No valid images to integrate")
    
    print(f"Integrating {len(images)} images...")
    
    # Use configured memory limit
    mem_limit = memory_limit or MEMORY_LIMIT
    
    # Integrate using ccdproc
    try:
        if sigma_clip:
            stack = ccdp.combine(
                images,
                method=method,
                scale=scale,
                sigma_clip=True,
                sigma_clip_low_thresh=SIGMA_LOW,
                sigma_clip_high_thresh=SIGMA_HIGH,
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
        raise MotionTrackingIntegrationError(f"Error during integration: {e}") 


def crop_integrated_image(integrated_image: ccdp.CCDData, original_shape: Tuple[int, int], 
                         padding: Tuple[int, int, int, int]) -> ccdp.CCDData:
    """
    Crop the integrated image to remove padding and restore original dimensions.
    
    Parameters:
    -----------
    integrated_image : ccdp.CCDData
        The integrated image with padding
    original_shape : Tuple[int, int]
        Original image shape (height, width)
    padding : Tuple[int, int, int, int]
        Padding that was applied: (left, right, top, bottom)
        
    Returns:
    --------
    ccdp.CCDData
        Cropped image with original dimensions
    """
    left, right, top, bottom = padding
    
    if left == 0 and right == 0 and top == 0 and bottom == 0:
        return integrated_image
    
    # Calculate crop indices
    crop_top = top
    crop_bottom = integrated_image.data.shape[0] - bottom
    crop_left = left
    crop_right = integrated_image.data.shape[1] - right
    
    # Crop the image
    cropped_data = integrated_image.data[crop_top:crop_bottom, crop_left:crop_right]
    
    # Create new CCDData object with cropped data
    cropped_image = ccdp.CCDData(cropped_data, unit=integrated_image.unit)
    cropped_image.meta = integrated_image.meta.copy()
    
    # Update metadata
    safe_set_metadata(cropped_image.meta, 'CROPPED', True)
    safe_set_metadata(cropped_image.meta, 'ORIGINAL_SHAPE', original_shape)
    safe_set_metadata(cropped_image.meta, 'PADDING_REMOVED', padding)
    
    print(f"Cropped integrated image from {integrated_image.data.shape} to {cropped_data.shape}")
    
    return cropped_image 


def compute_object_positions_from_motion_tracked(
    stacked_image_path: str, 
    cursor_coords: Tuple[float, float],
    original_files: List[str] = None,
    loaded_files: List[str] = None,
    lspc_constants: Dict[str, float] = None
) -> List[Dict[str, any]]:
    """
    Compute the position of an object in each original image from its position in a motion tracked stacked image.
    
    This function reverses the motion tracking process by:
    1. Reading the shift information from the stacked image header
    2. Converting the cursor coordinates to the original coordinate system
    3. Applying the reverse shifts to get the position in each original image
    
    Parameters:
    -----------
    stacked_image_path : str
        Path to the motion tracked stacked image
    cursor_coords : Tuple[float, float]
        Pixel coordinates (x, y) in the stacked image where the user clicked
    original_files : List[str], optional
        List of original file paths. If None, will be read from header.
    loaded_files : List[str], optional
        List of loaded file paths. If provided, only motion-tracked stacks in this list
        will be added to the results.
    lspc_constants : Dict[str, float], optional
        LSPC plate constants (a, b, c, d, e, f) for improved astrometric precision.
        If provided, will be used to calculate LSPC RA/Dec coordinates.
        
    Returns:
    --------
    List[Dict[str, any]]
        List of dictionaries containing position information for each original image:
        - file_path: Path to the original image
        - original_x: X coordinate in original image
        - original_y: Y coordinate in original image
        - stacked_x: X coordinate in stacked image
        - stacked_y: Y coordinate in stacked image
        - shift_x: X shift that was applied during stacking
        - shift_y: Y shift that was applied during stacking
        - ra: Right ascension (if WCS available)
        - dec: Declination (if WCS available)
        - lspc_ra: LSPC-corrected right ascension (if LSPC constants provided)
        - lspc_dec: LSPC-corrected declination (if LSPC constants provided)
    """
    try:
        from astropy.io import fits
        from astropy.wcs import WCS
        import json
        
        # Read the stacked image header
        with fits.open(stacked_image_path) as hdul:
            header = hdul[0].header
            stacked_data = hdul[0].data
            
        # Check if this is a motion tracked image
        motion_tracked = header.get('MOTION_TRACKED', False)
        if not motion_tracked:
            raise ValueError("This is not a motion tracked stacked image")
        
        # Get shift information from header
        motion_shifts_json = header.get('MOTION_SHIFTS')
        if not motion_shifts_json:
            raise ValueError("No motion shift information found in header")
        
        motion_shifts = json.loads(motion_shifts_json)
        
        # Get original files from header if not provided
        if original_files is None:
            original_files_json = header.get('ORIGINAL_FILES')
            if not original_files_json:
                raise ValueError("No original files information found in header")
            original_files = json.loads(original_files_json)
        
        # Get padding information
        padding_json = header.get('PADDING')
        padding = json.loads(padding_json) if padding_json else (0, 0, 0, 0)
        
        # Get reference position from header
        reference_position_json = header.get('REFERENCE_POSITION')
        reference_position = json.loads(reference_position_json) if reference_position_json else None
        
        # Get WCS from stacked image if available
        stacked_wcs = None
        try:
            stacked_wcs = WCS(header)
        except Exception:
            pass
        
        # Convert cursor coordinates to sky coordinates if WCS is available
        sky_coords = None
        if stacked_wcs and stacked_wcs.is_celestial:
            try:
                sky_coords = stacked_wcs.pixel_to_world(cursor_coords[0], cursor_coords[1])
            except Exception:
                pass
        
        results = []
        
        # For each original image, compute the reverse position
        for shift_info in motion_shifts:
            file_path = shift_info['file_path']
            shift_x = shift_info['shift_x']
            shift_y = shift_info['shift_y']
            
            # Reverse the shift: subtract the shift that was applied during stacking
            # BUT: The shifts were calculated in the original image coordinate system,
            # while cursor_coords are in the cropped stacked image coordinate system.
            # Since the final image was cropped to remove padding, we need to adjust
            # the shifts to account for this coordinate system difference.
            
            # The shifts were calculated in the original image coordinate system
            # but applied to padded images. When the final result is cropped,
            # the coordinate systems align again, so we can simply subtract the shifts.
            
            # The shifts were calculated to move the object from its position in each image
            # to a fixed reference position (the first image's object position).
            # To reverse this, we need to calculate where the cursor position would be
            # in each original image by subtracting the shift.
            
            # If we have the reference position, we can calculate the original position more accurately
            if reference_position is not None:
                # The cursor position is in the stacked image coordinate system
                # The reference position is in the first image's coordinate system
                # The shifts move from each image's object position to the reference position
                # So to reverse: original_position = cursor_position - shift
                original_x = cursor_coords[0] - shift_x
                original_y = cursor_coords[1] - shift_y
            else:
                # Fallback to simple shift reversal
                original_x = cursor_coords[0] - shift_x
                original_y = cursor_coords[1] - shift_y
            
            # Debug output for first few positions
            if len(results) < 3:
                print(f"DEBUG: File: {os.path.basename(file_path)}")
                print(f"DEBUG: Cursor coords: ({cursor_coords[0]:.2f}, {cursor_coords[1]:.2f})")
                print(f"DEBUG: Shift: ({shift_x:.2f}, {shift_y:.2f})")
                print(f"DEBUG: Calculated original: ({original_x:.2f}, {original_y:.2f})")
                print(f"DEBUG: Padding: {padding}")
                print(f"DEBUG: Stacked image shape: {stacked_data.shape}")
            
            # The shifts were applied to padded images, but the final result was cropped.
            # Since we're working with the cropped result, we don't need to subtract padding
            # because the coordinate systems are already aligned after cropping.
            # The padding adjustment is not needed here.
            
            # Get WCS from original image if available
            original_ra = None
            original_dec = None
            try:
                with fits.open(file_path) as orig_hdul:
                    orig_header = orig_hdul[0].header
                    orig_wcs = WCS(orig_header)
                    if orig_wcs.is_celestial:
                        # Convert original pixel coordinates to sky coordinates
                        orig_sky = orig_wcs.pixel_to_world(original_x, original_y)
                        original_ra = orig_sky.ra.deg if hasattr(orig_sky, 'ra') else orig_sky[0].deg
                        original_dec = orig_sky.dec.deg if hasattr(orig_sky, 'dec') else orig_sky[1].deg
            except Exception:
                pass
            
            # Apply LSPC transformation if constants are provided
            lspc_ra = None
            lspc_dec = None
            if lspc_constants:
                model_type = lspc_constants.get('model_type', 'linear')
                image_center_x = lspc_constants.get('image_center_x', 0)
                image_center_y = lspc_constants.get('image_center_y', 0)
                norm_scale = lspc_constants.get('norm_scale', 1000)
                
                # Normalize coordinates
                norm_x = (original_x - image_center_x) / norm_scale
                norm_y = (original_y - image_center_y) / norm_scale
                
                # Apply the appropriate plate model
                if model_type == "linear":
                    a = lspc_constants.get('a')
                    b = lspc_constants.get('b')
                    c = lspc_constants.get('c')
                    d = lspc_constants.get('d')
                    e = lspc_constants.get('e')
                    f = lspc_constants.get('f')
                    
                    if all(v is not None for v in [a, b, c, d, e, f]):
                        lspc_ra = a * norm_x + b * norm_y + c
                        lspc_dec = d * norm_x + e * norm_y + f
                        
                elif model_type == "radial":
                    a = lspc_constants.get('a')
                    b = lspc_constants.get('b')
                    c = lspc_constants.get('c')
                    d = lspc_constants.get('d')
                    e = lspc_constants.get('e')
                    f = lspc_constants.get('f')
                    k1 = lspc_constants.get('k1')
                    k2 = lspc_constants.get('k2')
                    
                    if all(v is not None for v in [a, b, c, d, e, f, k1, k2]):
                        r_squared = norm_x**2 + norm_y**2
                        lspc_ra = a * norm_x + b * norm_y + c + k1 * r_squared * norm_x
                        lspc_dec = d * norm_x + e * norm_y + f + k2 * r_squared * norm_y
                        
                elif model_type == "quadratic":
                    a = lspc_constants.get('a')
                    b = lspc_constants.get('b')
                    c = lspc_constants.get('c')
                    d = lspc_constants.get('d')
                    e = lspc_constants.get('e')
                    f = lspc_constants.get('f')
                    g = lspc_constants.get('g')
                    h = lspc_constants.get('h')
                    i = lspc_constants.get('i')
                    j = lspc_constants.get('j')
                    k = lspc_constants.get('k')
                    l = lspc_constants.get('l')
                    
                    if all(v is not None for v in [a, b, c, d, e, f, g, h, i, j, k, l]):
                        lspc_ra = (a * norm_x + b * norm_y + c + 
                                  d * norm_x**2 + e * norm_x * norm_y + f * norm_y**2)
                        lspc_dec = (g * norm_x + h * norm_y + i + 
                                   j * norm_x**2 + k * norm_x * norm_y + l * norm_y**2)
            
            result = {
                'file_path': file_path,
                'original_x': original_x,
                'original_y': original_y,
                'stacked_x': cursor_coords[0],
                'stacked_y': cursor_coords[1],
                'shift_x': shift_x,
                'shift_y': shift_y,
                'ra': original_ra,
                'dec': original_dec,
                'lspc_ra': lspc_ra,
                'lspc_dec': lspc_dec
            }
            
            results.append(result)
        
        # Add an entry for the stacked image itself
        stacked_result = {
            'file_path': stacked_image_path,
            'original_x': cursor_coords[0],  # In the stacked image, original = stacked
            'original_y': cursor_coords[1],
            'stacked_x': cursor_coords[0],
            'stacked_y': cursor_coords[1],
            'shift_x': 0.0,  # No shift for the stacked image
            'shift_y': 0.0,
            'ra': sky_coords.ra.deg if sky_coords else None,
            'dec': sky_coords.dec.deg if sky_coords else None
        }
        
        results.append(stacked_result)
        
        # Also add entries for other motion-tracked stacks with the same original files
        # This ensures that when computing positions on one stack, both stacks get the same positions
        if loaded_files:
            try:
                # Look for other motion-tracked stacks in the loaded files list
                stacked_basename = os.path.basename(stacked_image_path)
                
                # Look for other motion-tracked stacks with the same object name
                # Extract object name from the current stack filename
                if 'motion_tracked_' in stacked_basename:
                    object_part = stacked_basename.split('motion_tracked_')[1]
                    if '_' in object_part:
                        object_name = object_part.split('_')[0]
                        
                        # Look for other motion-tracked stacks with the same object name in loaded_files
                        for loaded_file in loaded_files:
                            if loaded_file != stacked_image_path:
                                loaded_basename = os.path.basename(loaded_file)
                                if (loaded_basename.startswith(f"motion_tracked_{object_name}_") and 
                                    loaded_basename.endswith('.fits')):
                                    # Add entry for this other stack with the same coordinates
                                    other_stack_result = {
                                        'file_path': loaded_file,
                                        'original_x': cursor_coords[0],
                                        'original_y': cursor_coords[1],
                                        'stacked_x': cursor_coords[0],
                                        'stacked_y': cursor_coords[1],
                                        'shift_x': 0.0,
                                        'shift_y': 0.0,
                                        'ra': sky_coords.ra.deg if sky_coords else None,
                                        'dec': sky_coords.dec.deg if sky_coords else None
                                    }
                                    results.append(other_stack_result)
            except Exception as e:
                # If we can't find other stacks, just continue with the current stack
                pass
        
        return results
        
    except Exception as e:
        raise MotionTrackingIntegrationError(f"Error computing object positions: {e}") 