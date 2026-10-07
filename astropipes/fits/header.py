"""
FITS header parsing utilities.
"""

import json
from astropy.io import fits
from typing import Dict, Any


def get_fits_header_as_json(fits_file_path: str) -> Dict[str, Any]:
    """
    Read a FITS file and return its header as a JSON-serializable dictionary.
    Each key maps to a (value, comment) tuple.
    """
    try:
        with fits.open(fits_file_path) as hdul:
            header = hdul[0].header
            header_dict = {}
            for card in header.cards:
                key = card.keyword
                value = card.value
                comment = card.comment
                # Convert special FITS objects to strings
                if hasattr(value, '__str__'):
                    value = str(value)
                header_dict[key] = (value, comment)
            return header_dict
    except FileNotFoundError:
        raise FileNotFoundError(f"FITS file not found: {fits_file_path}")
    except OSError as e:
        raise OSError(f"Error opening FITS file {fits_file_path}: {e}")


def get_fits_header_json_string(fits_file_path: str) -> str:
    """
    Read a FITS file and return its header as a JSON string.
    
    Args:
        fits_file_path: Path to the FITS file
        
    Returns:
        JSON string containing all header cards and their values
        
    Raises:
        FileNotFoundError: If the FITS file doesn't exist
        OSError: If the file can't be opened as a FITS file
        ValueError: If header can't be serialized to JSON
    """
    header_dict = get_fits_header_as_json(fits_file_path)
    
    try:
        return json.dumps(header_dict)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Error serializing header to JSON: {e}") 


def set_fits_header_value(fits_file_path: str, key: str, value: str, comment: str = None) -> None:
    """
    Update a FITS header card (e.g., OBJECT) in-place.
    Args:
        fits_file_path: Path to the FITS file
        key: Header keyword to update (e.g., 'OBJECT')
        value: New value for the header card
        comment: Optional comment for the header card
    Raises:
        FileNotFoundError: If the FITS file doesn't exist
        OSError: If the file can't be opened for update
    """
    try:
        with fits.open(fits_file_path, mode='update') as hdul:
            header = hdul[0].header
            if comment is not None:
                header[key] = (value, comment)
            else:
                header[key] = value
            hdul.flush()
    except FileNotFoundError:
        raise FileNotFoundError(f"FITS file not found: {fits_file_path}")
    except OSError as e:
        raise OSError(f"Error updating FITS file {fits_file_path}: {e}") 