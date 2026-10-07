"""
MPC (Minor Planet Center) utilities: submission report format, observatory code lookup.

This module provides functions to generate MPC submission reports
following the official format described at:
https://minorplanetcenter.net/iau/info/OpticalObs.html
"""

from astropy.coordinates import Angle
import astropy.units as u
from astropy.time import Time
import math
import re
import urllib.request


def generate_mpc_submission(observations, object_designation, observatory_code, 
                           is_discovery=False, note1="", note2="C", 
                           magnitude=None, magnitude_band="V"):
    """
    Generate MPC submission format from observations.
    
    Parameters
    ----------
    observations : list of dict
        List of observation dictionaries. Each dict should contain:
        - 'date_obs': observation date/time (ISO string or Time object)
        - 'ra_deg': right ascension in degrees
        - 'dec_deg': declination in degrees
    object_designation : str
        Object designation (e.g., "C34UMY1", "2023 ABC123")
    observatory_code : str
        Observatory code (e.g., "R56")
    is_discovery : bool, optional
        Whether this is a discovery observation (adds asterisk to first observation)
    note1 : str, optional
        Program code or other note (column 14)
    note2 : str, optional
        Observation method code (column 15). Default "C" for CCD.
        Valid codes: P, e, C, B, T, M, V, R, S, E, O, H, N, n
    magnitude : float, optional
        Observed magnitude (not included if None)
    magnitude_band : str, optional
        Magnitude band (V, R, B, etc.)
    
    Returns
    -------
    str
        MPC submission text in the official 80-column format
    """
    
    if not observations:
        raise ValueError("No observations provided")
    
    if not object_designation:
        raise ValueError("Object designation is required")
    
    if not observatory_code:
        raise ValueError("Observatory code is required")
    
    # Validate note2 code
    valid_note2_codes = ["P", "e", "C", "B", "T", "M", "V", "R", "S", "E", "O", "H", "N", "n"]
    if note2 not in valid_note2_codes:
        raise ValueError(f"Invalid note2 code '{note2}'. Valid codes: {valid_note2_codes}")
    
    mpc_lines = []
    
    for i, observation in enumerate(observations):
        try:
            mpc_line = _format_mpc_line(
                observation=observation,
                designation=object_designation,
                is_discovery=is_discovery and i == 0,  # Only first observation gets asterisk
                note1=note1,
                note2=note2,
                magnitude=magnitude,
                magnitude_band=magnitude_band,
                observatory_code=observatory_code
            )
            mpc_lines.append(mpc_line)
        except Exception as e:
            raise ValueError(f"Error formatting observation {i+1}: {str(e)}")
    
    return "\n".join(mpc_lines)


def _format_mpc_line(observation, designation, is_discovery, note1, note2, 
                    magnitude, magnitude_band, observatory_code):
    """
    Format a single observation into MPC submission format.
    
    This follows the official 80-column format:
    - Columns 1-12: Designation
    - Column 13: Discovery asterisk
    - Columns 14-15: Notes
    - Columns 16-32: Date (YYYY MM DD.dddddd)
    - Columns 33-44: RA (HH MM SS.dd)
    - Columns 45-56: Dec (sDD MM SS.d)
    - Columns 57-65: Blank
    - Columns 66-71: Magnitude and band
    - Columns 72-77: Blank
    - Columns 78-80: Observatory code
    """
    
    # Columns 1-12: Designation (right-justified, space-padded)
    designation_field = designation.ljust(12)
    
    # Column 13: Discovery asterisk
    discovery_field = "*" if is_discovery else " "
    
    # Columns 14-15: Notes
    note1_field = note1[:1] if note1 else " "
    note2_field = note2[:1] if note2 else " "
    
    # Columns 16-32: Date (YYYY MM DD.dddddd)
    try:
        date_obs = observation['date_obs']
        if isinstance(date_obs, str):
            # Parse ISO format date
            time_obj = Time(date_obs, format='isot', scale='utc')
        else:
            time_obj = Time(date_obs, scale='utc')
        
        # Format as YYYY MM DD.dddddd
        year = time_obj.datetime.year
        month = time_obj.datetime.month
        day = time_obj.datetime.day
        hour = time_obj.datetime.hour
        minute = time_obj.datetime.minute
        second = time_obj.datetime.second
        
        # Calculate decimal day
        decimal_day = day + (hour + minute/60 + second/3600) / 24
        
        date_field = f"{year:04d} {month:02d} {decimal_day:08.6f}"
        # Ensure proper width for date field (17 characters: YYYY MM DD.dddddd)
        if len(date_field) != 17:
            # Pad or truncate as needed
            date_field = date_field.ljust(17)[:17]
    except Exception as e:
        raise ValueError(f"Error formatting date: {e}")
    
    # Columns 33-44: RA (HH MM SS.dd) - 12 characters
    try:
        ra_deg = observation['ra_deg']
        ra_angle = Angle(ra_deg, unit=u.deg)
        ra_hms = ra_angle.to_string(unit='hourangle', sep=' ', precision=2, pad=True)
        ra_field = ra_hms.replace('h', ' ').replace('m', ' ').replace('s', '').strip()
        # Ensure proper width for RA field (12 characters: HH MM SS.dd)
        ra_parts = ra_field.split()
        if len(ra_parts) >= 3:
            ra_field = f"{ra_parts[0]:>2} {ra_parts[1]:>2} {ra_parts[2]:>5}"
        # Ensure exact width
        ra_field = ra_field.ljust(12)[:12]
    except Exception as e:
        raise ValueError(f"Error formatting RA: {e}")
    
    # Columns 45-56: Dec (sDD MM SS.d) - 12 characters
    try:
        dec_deg = observation['dec_deg']
        dec_angle = Angle(dec_deg, unit=u.deg)
        dec_dms = dec_angle.to_string(unit='deg', sep=' ', precision=1, pad=True, alwayssign=True)
        dec_field = dec_dms.replace('d', ' ').replace('m', ' ').replace('s', '').strip()
        # Ensure proper width for Dec field (12 characters: sDD MM SS.d)
        dec_parts = dec_field.split()
        if len(dec_parts) >= 3:
            dec_field = f"{dec_parts[0]:>3} {dec_parts[1]:>2} {dec_parts[2]:>4}"
        # Ensure exact width
        dec_field = dec_field.ljust(12)[:12]
    except Exception as e:
        raise ValueError(f"Error formatting Dec: {e}")
    
    # Columns 57-65: Blank
    blank1 = " " * 9
    
    # Columns 66-71: Magnitude and band
    if magnitude is not None:
        mag_field = f"{float(magnitude):5.2f}{magnitude_band}"
    else:
        mag_field = " " * 6
    
    # Columns 72-77: Blank
    blank2 = " " * 6
    
    # Columns 78-80: Observatory code
    obs_field = observatory_code.rjust(3)
    
    # Combine all fields
    mpc_line = (designation_field + discovery_field + note1_field + note2_field + 
               date_field + ra_field + dec_field + blank1 + mag_field + blank2 + obs_field)
    
    # Validate line length (should be exactly 80 characters)
    if len(mpc_line) != 80:
        raise ValueError(f"MPC line length is {len(mpc_line)} characters, should be 80")
    
    return mpc_line


def query_mpc_observatory_code(obs_code):
    """
    Query the MPC observatory codes file to get coordinates for a given observatory code.

    Args:
        obs_code (str): The observatory code to look up

    Returns:
        tuple: (longitude, latitude) in degrees, or (None, None) if not found
    """
    try:
        # Fetch the MPC observatory codes file
        url = "https://www.minorplanetcenter.net/iau/lists/ObsCodes.html"
        with urllib.request.urlopen(url, timeout=20) as response:
            content = response.read().decode('utf-8')

        # Parse the content line by line
        lines = content.split('\n')
        for line in lines:
            # Skip header lines and empty lines
            if not line.strip() or line.startswith('Code') or line.startswith('----'):
                continue

            # Split the line into fields
            parts = line.split()
            if len(parts) >= 2:
                code = parts[0]
                if code == obs_code:
                    # The format can be: CODE LONGITUDE COS SIN NAME
                    # But sometimes values are concatenated like: R56 170.483890.720473-0.691324Scott
                    # We need to parse the second field more carefully

                    # Try to extract longitude, cos, and sin from the second field
                    second_field = parts[1]

                    # Check if the second field contains a sign (+ or -) to determine if it's concatenated
                    has_sign = re.search(r'[+-]', second_field) is not None

                    if has_sign:
                        # Try to parse concatenated format like: 170.483890.720473-0.691324
                        # Find the sign (+ or -) to separate cos and sin

                        # Look for a sign followed by a decimal number
                        sign_match = re.search(r'([+-])(\d+\.\d+)', second_field)
                        if sign_match:
                            sign_pos = sign_match.start()
                            sign = sign_match.group(1)
                            sin_str = sign_match.group(2)

                            # Extract the part before the sign
                            before_sign = second_field[:sign_pos]

                            # Find the second decimal point in the before_sign part
                            decimal_points = [i for i, char in enumerate(before_sign) if char == '.']
                            if len(decimal_points) >= 2:
                                # First decimal point is for longitude
                                first_decimal = decimal_points[0]

                                # Find the start of the cos component (first "0." after longitude)
                                cos_start = before_sign.find('0.', first_decimal + 4)
                                if cos_start != -1:
                                    # Extract longitude up to the start of cos
                                    longitude_str = before_sign[:cos_start]

                                    # For better precision, let's extract the full cos value
                                    # Find where the cos value ends (before the sign)
                                    cos_end = before_sign.find('+', cos_start)
                                    if cos_end == -1:
                                        cos_end = before_sign.find('-', cos_start)
                                    if cos_end != -1:
                                        cos_str = before_sign[cos_start:cos_end]
                                    else:
                                        # Fallback: use the rest of the string before the sign
                                        cos_str = before_sign[cos_start:]
                                else:
                                    # Fallback to old method if no "0." found
                                    longitude_str = before_sign[:first_decimal + 4]  # Include 3 decimal places
                                    # Find the second decimal point for cos
                                    second_decimal = decimal_points[1]
                                    cos_str = before_sign[first_decimal + 4:second_decimal + 6]  # Include 5 decimal places

                                try:
                                    longitude = float(longitude_str)
                                    cos_val = float(cos_str)
                                    sin_val = float(sign + sin_str)
                                except ValueError:
                                    continue
                            else:
                                continue
                        else:
                            continue
                    elif len(parts) >= 4:
                        # Try the simple approach with separate fields
                        try:
                            longitude = float(parts[1])
                            cos_val = float(parts[2])
                            sin_val = float(parts[3])
                        except (ValueError, IndexError):
                            continue
                    else:
                        continue

                    # Calculate latitude from cos and sin
                    # The cos and sin values represent cos(latitude) and sin(latitude)
                    # We can use either to calculate latitude
                    if abs(cos_val) <= 1.0:
                        # Use arccos if cos value is valid
                        latitude = math.degrees(math.acos(cos_val))
                        # Determine sign from sin value
                        if sin_val < 0:
                            latitude = -latitude
                    else:
                        # Fallback to arcsin
                        latitude = math.degrees(math.asin(sin_val))

                    return longitude, latitude

        return None, None

    except Exception as e:
        print(f"Error querying MPC observatory codes: {e}")
        return None, None
