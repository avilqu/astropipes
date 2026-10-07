"""
NEOfixer (NEOCP objects and observations) and Find_Orb (ephemerides) online services.
"""

import logging
from typing import Any, List

import requests

from astropipes.config import settings

logger = logging.getLogger(__name__)


def get_neofixer_observations(object_designation: str) -> List[Any]:
    """
    Query NEOCP observations using the NEOfixer API.
    Returns observations for objects on the Near Earth Object Confirmation Page.
    
    Args:
        object_designation (str): The NEOCP object designation (e.g., 'C34UMY1').
    Returns:
        List[Any]: List of observations from NEOCP via NEOfixer.
    Raises:
        Exception: For errors during query.
    """
    try:
        # NEOfixer observations API endpoint - returns text format
        url = "https://neofixerapi.arizona.edu/obs/"
        
        # Parameters for the request
        params = {
            'object': object_designation
        }
        
        # Make the request
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        # Observations come back as text; errors (e.g. unknown object) as a JSON-RPC error, still with HTTP 200
        if 'json' in response.headers.get('Content-Type', ''):
            error = response.json().get('error') or {}
            raise Exception(f"NEOfixer: {error.get('message', response.text.strip())}")

        observations_text = response.text
        
        if not observations_text.strip():
            return []
        
        # Parse the text observations into a list of lines
        # Each line represents one observation
        observations = []
        for line in observations_text.strip().split('\n'):
            if line.strip():
                observations.append(line.strip())
        
        return observations
        
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to query NEOCP observations for {object_designation}: {e}")
    except Exception as e:
        raise Exception(f"Error processing NEOCP data for {object_designation}: {e}")


def get_neocp_objects(site: str = None, num: int = 40) -> List[Any]:
    """
    Get the current list of objects on the NEOCP using the NEOfixer API.
    Returns the list of NEOCP objects with their designations and basic information.
    
    Args:
        site (str): The NEOfixer telescope or site name (typically 3 character MPC code);
            defaults to settings.OBS_CODE.
        num (int): Number of objects to retrieve.
    Returns:
        List[Any]: List of NEOCP objects.
    Raises:
        Exception: For errors during query.
    """
    try:
        # NEOfixer targets API endpoint
        url = "https://neofixerapi.arizona.edu/targets/"
        
        # Parameters for the request
        params = {
            'site': site or settings.OBS_CODE,
            'num': num
        }
        
        # Make the request
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        # Parse the response
        data = response.json()
        
        # Check for errors in the response
        if 'error' in data:
            raise Exception(f"NEOfixer API error: {data['error']}")
        
        # Return the objects from the result
        result = data.get('result', {})
        objects = result.get('objects', {})
        
        # Convert the objects dictionary to a list
        return list(objects.values())
        
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to query NEOCP objects: {e}")
    except Exception as e:
        raise Exception(f"Error processing NEOCP objects data: {e}")


def predict_position_findorb(object_designation: str, dates_obs: list):
    """
    Query Find_Orb online service for ephemeris and return interpolated positions for multiple dates.
    Args:
        object_designation (str): The object name (e.g., '2025 BC').
        dates_obs (list): List of observation dates/times in ISO format (e.g., ['2025-01-22T11:36:18', '2025-01-22T12:36:18']).
    Returns:
        dict: Dictionary with date_obs as keys and interpolated positions as values, plus "pseudo_mpec" key with HTML text content.
    """
    import requests
    from datetime import datetime
    import json
    from bs4 import BeautifulSoup
    
    if not dates_obs:
        return {}
    
    # Find the date range to cover all requested dates
    parsed_dates = []
    for date_obs in dates_obs:
        if 'T' in date_obs:
            obs_dt = datetime.fromisoformat(date_obs.replace('Z', '+00:00'))
        else:
            obs_dt = datetime.strptime(date_obs, '%Y-%m-%d %H:%M:%S')
        parsed_dates.append(obs_dt)
    
    # Use the start date for the API call to ensure we cover all dates from the beginning
    sorted_dates = sorted(parsed_dates)
    start_date = sorted_dates[0]
    
    # Calculate time span needed to cover all dates
    time_span = (sorted_dates[-1] - sorted_dates[0]).total_seconds() / 3600  # hours
    # Add padding to ensure we have entries before the first date and after the last date
    time_span = max(time_span + 4, 6)  # at least 6 hours coverage with 2 hours padding on each side
    
    # Calculate number of steps needed (1 step per minute for high precision, minimum 360 steps = 6 hours)
    n_steps = max(int(time_span * 60) + 120, 360)  # Convert hours to minutes + 2 hours padding
    
    findorb_url = "https://www.projectpluto.com/cgi-bin/fo/fo_serve.cgi"
    data = {
        "TextArea": "",
        "obj_name": object_designation,
        "year": start_date.strftime('%Y-%m-%dT%H:%M:%S'),
        "n_steps": str(n_steps),
        "stepsize": "1m",  # 1 minute steps for high precision
        "mpc_code": settings.OBS_CODE,
        "faint_limit": "99",
        "ephem_type": "0",
        "sigmas": "on",
        "total_motion": "on",
        "element_center": "-2",
        "epoch": "",
        "resids": "0",
        "language": "e",
        "file_no": "3",  # JSON output
    }
    files = {
        "upfile": ("", b""),
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer': 'https://www.projectpluto.com/fo.htm',
        'Accept': 'application/json, text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://www.projectpluto.com',
        'Connection': 'keep-alive',
    }
    
    logger.debug(f"Making Find_Orb API call for {len(dates_obs)} dates")
    logger.debug(f"Date range: {start_date} to {sorted_dates[-1]} (span: {time_span:.1f} hours)")
    logger.debug(f"Querying ephemeris starting from {start_date} with {n_steps} steps at 1-minute resolution")
    
    try:
        resp = requests.post(findorb_url, data=data, files=files, headers=headers, timeout=60)
        resp.raise_for_status()
        
        # Make second API call with file_no=0 to get HTML output
        data_html = data.copy()
        data_html['file_no'] = "0"  # HTML output
        
        logger.debug(f"Making second Find_Orb API call for HTML output")
        resp_html = requests.post(findorb_url, data=data_html, files=files, headers=headers, timeout=60)
        resp_html.raise_for_status()
        
        # Extract text from <pre> tags in HTML response
        pseudo_mpec_text = ""
        try:
            soup = BeautifulSoup(resp_html.text, 'html.parser')
            pre_tags = soup.find_all('pre')
            if len(pre_tags) >= 2:
                # Combine text from both <pre> tags
                for pre_tag in pre_tags[:2]:
                    # Remove <b> and <a> tags while preserving text content
                    for tag in pre_tag.find_all(['b', 'a']):
                        tag.unwrap()  # This removes the tag but keeps its content
                    pseudo_mpec_text += pre_tag.get_text() + "\n"
                logger.debug(f"Extracted {len(pseudo_mpec_text)} characters from HTML <pre> tags")
            else:
                logger.debug(f"Found {len(pre_tags)} <pre> tags, expected at least 2")
        except Exception as e:
            logger.debug(f"Failed to parse HTML response: {e}")
            pseudo_mpec_text = ""
        
        try:
            result_json = resp.json()
        except Exception as e:
            # Try to extract JSON from the response text even if resp.json() fails
            logger.debug(f"resp.json() failed: {e}, attempting to extract JSON from text...")
            text = resp.text
            # Find the first '{' and last '}'
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = text[start:end+1]
                try:
                    result_json = json.loads(json_str)
                except Exception as e2:
                    logger.debug(f"Failed to parse JSON from response text: {e2}")
                    print(text[:2000])
                    return {'pseudo_mpec': pseudo_mpec_text}
            else:
                logger.debug("Could not find JSON object in response text.")
                print(text[:2000])
                return {'pseudo_mpec': pseudo_mpec_text}
        
        # Parse ephemeris entries
        if 'ephemeris' not in result_json or 'entries' not in result_json['ephemeris']:
            print("No ephemeris data found in response")
            return {'pseudo_mpec': pseudo_mpec_text}
        
        entries = result_json['ephemeris']['entries']
        if len(entries) < 2:
            print(f"Expected at least 2 ephemeris entries, got {len(entries)}")
            return {'pseudo_mpec': pseudo_mpec_text}
        
        # Convert entries to list and sort by time
        ephemeris_entries = []
        for key, entry in entries.items():
            time_str = entry.get('ISO_time', entry.get('Date', ''))
            try:
                if 'T' in time_str:
                    dt = datetime.strptime(time_str[:19], '%Y-%m-%dT%H:%M:%S')
                else:
                    dt = datetime.strptime(time_str[:16], '%Y-%m-%dT%H:%M')
                ephemeris_entries.append((dt, entry))
            except ValueError:
                logger.debug(f"Could not parse time from entry: {time_str}")
                continue
        
        ephemeris_entries.sort(key=lambda x: x[0])  # Sort by datetime
        
        # Interpolate positions for each requested date
        results = {}
        for date_obs in dates_obs:
            if 'T' in date_obs:
                obs_dt = datetime.fromisoformat(date_obs.replace('Z', '+00:00'))
            else:
                obs_dt = datetime.strptime(date_obs, '%Y-%m-%d %H:%M:%S')
            
            # Find the two ephemeris entries that bracket the observation time
            before_entry = None
            after_entry = None
            
            # Find the closest entries before and after the observation time
            for i, (ephem_dt, entry) in enumerate(ephemeris_entries):
                if ephem_dt <= obs_dt:
                    # Update before_entry to the latest entry that's <= obs_dt
                    if before_entry is None or ephem_dt > before_entry[0]:
                        before_entry = (ephem_dt, entry)
                else:
                    # Found first entry > obs_dt, this is our after_entry
                    after_entry = (ephem_dt, entry)
                    break
            
            # If we didn't find an after_entry, check if there are more entries
            if after_entry is None and len(ephemeris_entries) > 0:
                # All entries are before obs_dt, use the last two entries
                if len(ephemeris_entries) >= 2:
                    before_entry = ephemeris_entries[-2]
                    after_entry = ephemeris_entries[-1]
                else:
                    # Only one entry, use it for both
                    after_entry = ephemeris_entries[-1]
            
            # If we didn't find a before_entry, check if there are entries after obs_dt
            if before_entry is None and len(ephemeris_entries) > 0:
                # All entries are after obs_dt, use the first two entries
                if len(ephemeris_entries) >= 2:
                    before_entry = ephemeris_entries[0]
                    after_entry = ephemeris_entries[1]
                else:
                    # Only one entry, use it for both
                    before_entry = ephemeris_entries[0]
            
            # Ensure we have both entries for interpolation
            if before_entry is None or after_entry is None:
                logger.debug(f"Could not find suitable ephemeris entries for {date_obs}")
                continue
            
            # Interpolate between the two entries
            dt1, entry1 = before_entry
            dt2, entry2 = after_entry
            
            # Only show debug for first 3 and last 3 interpolations to avoid spam
            show_debug = len(results) < 3 or len(results) >= len(dates_obs) - 3
            
            if show_debug:
                logger.debug(f"Interpolating between {dt1} (RA={entry1.get('RA', 0):.6f}, Dec={entry1.get('Dec', 0):.6f}) and {dt2} (RA={entry2.get('RA', 0):.6f}, Dec={entry2.get('Dec', 0):.6f}) for {obs_dt}")
            
            if dt1 == dt2:
                # No interpolation needed
                interpolated_result = entry1.copy()
                if show_debug:
                    logger.debug(f"No interpolation needed, times are identical")
            else:
                # Linear interpolation
                total_time_diff = (dt2 - dt1).total_seconds()
                obs_time_diff = (obs_dt - dt1).total_seconds()
                interpolation_factor = obs_time_diff / total_time_diff
                
                ra1 = float(entry1.get('RA', 0))
                ra2 = float(entry2.get('RA', 0))
                dec1 = float(entry1.get('Dec', 0))
                dec2 = float(entry2.get('Dec', 0))
                
                # Handle RA wrap-around
                if abs(ra2 - ra1) > 180:
                    if ra2 > ra1:
                        ra1 += 360
                    else:
                        ra2 += 360
                
                interpolated_ra = ra1 + interpolation_factor * (ra2 - ra1)
                interpolated_dec = dec1 + interpolation_factor * (dec2 - dec1)
                interpolated_ra = interpolated_ra % 360.0
                
                interpolated_result = entry1.copy()
                interpolated_result['RA'] = interpolated_ra
                interpolated_result['Dec'] = interpolated_dec
                
                if show_debug:
                    logger.debug(f"Interpolation factor: {interpolation_factor:.6f}, time diff: {obs_time_diff:.1f}s / {total_time_diff:.1f}s")
            
            interpolated_result['date_obs'] = date_obs
            interpolated_result['Date'] = obs_dt.strftime('%Y-%m-%d %H:%M:%S')
            results[date_obs] = interpolated_result
            
            print(f"Interpolated position at {obs_dt}: RA={interpolated_result['RA']:.6f}, Dec={interpolated_result['Dec']:.6f}")
        
        # Add pseudo_mpec text to the results
        results['pseudo_mpec'] = pseudo_mpec_text
        
        return results
        
    except Exception as e:
        print(f"Failed to query Find_Orb or parse JSON: {e}")
        if 'resp' in locals():
            print(resp.text[:2000])
        return {'pseudo_mpec': ''}


