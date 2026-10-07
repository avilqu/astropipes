"""
Predicted positions of a solar-system object at the mid-exposure time of each loaded frame.
"""

import logging
from datetime import timedelta

from astropipes.astrometry.orbit import predict_position_findorb
from astropipes.db import get_db_manager
from astropipes.fits.metadata import get_mid_exposure_time

logger = logging.getLogger(__name__)

FINDORB_UNAVAILABLE = "Could not get orbital elements from Find_Orb. The service may be temporarily unavailable."


def _mid_exposure_from_database(fits_path):
    """Mid-exposure time (YYYY-MM-DDTHH:MM:SS) from the library record, or None."""
    try:
        db_entry = get_db_manager().get_fits_file_by_path(fits_path)
    except Exception as e:
        logger.debug(f"Failed to get date_obs from database for {fits_path}: {e}")
        return None
    if not db_entry or not db_entry.date_obs:
        return None
    start_time = db_entry.date_obs
    if getattr(db_entry, 'exptime', None):
        start_time = start_time + timedelta(seconds=db_entry.exptime / 2.0)
    return start_time.isoformat(sep='T', timespec='seconds')


def predict_positions_for_frames(object_name, fits_paths, log):
    """
    Ask Find_Orb for object_name's position at each frame's mid-exposure time (from the FITS
    header, else the library database). Frames without a date are skipped.

    Returns {'success', 'predicted_positions': [entry dicts with 'date_obs', 'RA', 'Dec', ...],
    'pseudo_mpec': str} or {'success': False, 'error'}.
    """
    dates_obs = []
    for fits_path in fits_paths:
        date_obs = get_mid_exposure_time(fits_path) or _mid_exposure_from_database(fits_path)
        if date_obs:
            logger.debug(f"{fits_path}: mid-exposure time {date_obs}")
            dates_obs.append(date_obs)
        else:
            log(f"No DATE-OBS for {fits_path}, skipping prediction.\n")

    if not dates_obs:
        return {'success': False, 'error': "No DATE-OBS found in loaded FITS files. Cannot compute predicted positions."}

    log(f"Requesting Find_Orb ephemerides for {len(dates_obs)} dates...\n")
    try:
        result = predict_position_findorb(object_name, dates_obs)
    except Exception as e:
        log(f"Failed to get predicted positions from Find_Orb: {e}\n")
        return {'success': False, 'error': FINDORB_UNAVAILABLE}
    if not result:
        return {'success': False, 'error': FINDORB_UNAVAILABLE}

    predicted_positions = []
    for date_obs in dates_obs:
        if date_obs in result:
            entry = result[date_obs]
            entry['date_obs'] = date_obs  # Ensure date_obs is included
            predicted_positions.append(entry)
        else:
            log(f"No position returned for {date_obs}\n")
    return {'success': True, 'predicted_positions': predicted_positions,
            'pseudo_mpec': result.get('pseudo_mpec', '')}
