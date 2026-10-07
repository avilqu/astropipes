"""
Parsing of common FITS header values: DATE-OBS, exposure time, binning, numeric cards.
"""

import re
from datetime import datetime, timedelta
from typing import Any, List, Optional

import numpy as np
from astropy.io import fits
from astropy.time import Time, TimeDelta


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_date_obs(value: Any) -> Optional[datetime]:
    """Parse a DATE-OBS value into a naive (UTC) datetime, or None if it can't be parsed."""
    if not value:
        return None

    date_string = str(value).replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_string.split("+")[0], fmt)
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(date_string).replace(tzinfo=None)
    except ValueError:
        return None


def format_binning(xbin: Any, ybin: Any) -> str:
    """Binning string as stored in the library database (e.g. "1x1", "2x2"); None counts as 1."""
    x = xbin if xbin is not None else 1
    y = ybin if ybin is not None else 1
    return f"{x}x{y}"


def binning_from_header(header: fits.Header) -> str:
    """Binning string from XBINNING/YBINNING (YBINNING defaults to XBINNING)."""
    xbin = safe_int(header.get("XBINNING", 1))
    return format_binning(xbin, safe_int(header.get("YBINNING", xbin)))


def exposure_seconds(header: fits.Header) -> float:
    """Exposure time from EXPTIME / EXPOSURE / EXP TIME, 0.0 if missing."""
    return safe_float(header.get('EXPTIME') or header.get('EXPOSURE') or header.get('EXP TIME') or 0.0)


def _date_obs_to_isot_seconds(date_obs: str) -> str:
    """DATE-OBS truncated to whole seconds, as YYYY-MM-DDTHH:MM:SS."""
    match = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::(\d{2}))?", date_obs)
    if match:
        seconds = match.group(3) if match.group(3) is not None else '00'
        return f"{match.group(1)}T{match.group(2)}:{seconds}"
    try:
        dt = datetime.fromisoformat(date_obs.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%dT%H:%M:%S')
    except Exception:
        return date_obs[:10] + 'T' + date_obs[11:16] + ':00'


def get_observation_time(file_path: str) -> Optional[str]:
    """Exposure start (DATE-OBS) of a FITS file as YYYY-MM-DDTHH:MM:SS, or None."""
    try:
        date_obs = fits.getheader(file_path, ext=0).get('DATE-OBS')
        if not date_obs:
            return None
        return _date_obs_to_isot_seconds(date_obs)
    except Exception as e:
        print(f"Warning: Could not extract observation time from {file_path}: {e}")
        return None


def get_mid_exposure_time(file_path: str) -> Optional[str]:
    """Mid-exposure time (DATE-OBS + EXPTIME/2) of a FITS file as YYYY-MM-DDTHH:MM:SS, or None."""
    try:
        header = fits.getheader(file_path, ext=0)
        date_obs = header.get('DATE-OBS')
        if not date_obs:
            return None
        start_dt = datetime.fromisoformat(_date_obs_to_isot_seconds(date_obs))
        mid_dt = start_dt + timedelta(seconds=exposure_seconds(header) / 2.0)
        return mid_dt.strftime('%Y-%m-%dT%H:%M:%S')
    except Exception as e:
        print(f"Warning: Could not extract mid-exposure time from {file_path}: {e}")
        return None


def compute_mid_observation_time(files: List[str]) -> Optional[str]:
    """
    Midpoint of a sequence: halfway between the start of the first exposure and the end
    (DATE-OBS + EXPTIME) of the last one, as an ISO 8601 UTC string, or None.
    Files do not need to be sorted.
    """
    if not files:
        return None

    try:
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

            t_end = t_start + TimeDelta(exposure_seconds(hdr), format='sec')

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
