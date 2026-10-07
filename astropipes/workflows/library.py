"""
Single-file library operations used by the viewer, the Library tables and the CLI:
plate-solving a file and updating its library record, deleting a file (database record and
disk), and recording source-analysis results.
"""

import os
from datetime import datetime

from colorama import Fore, Style

from astropipes.astrometry.platesolving import solve_single_image
from astropipes.db import get_db_manager
from astropipes.db.scan import get_file_database_info, rescan_single_file


def solve_and_update_library(fits_file_path: str, output_callback=None, **solve_kwargs):
    """
    Plate-solve a FITS file (see solve_single_image) and, if it is in the library, rescan
    it so its database record gets the new WCS. Returns the PlatesolvingResult.
    """
    result = solve_single_image(fits_file_path, output_callback=output_callback, **solve_kwargs)
    if result.success:
        update_library_after_solve(fits_file_path, output_callback)
    return result


def update_library_after_solve(fits_file_path: str, output_callback=None):
    """Rescan a plate-solved file into the library database if it is registered there."""
    def out(message):
        if output_callback:
            output_callback(f"{message}\n")
        else:
            print(message)

    out(f"{Style.BRIGHT + Fore.BLUE}Checking database status...{Style.RESET_ALL}")
    try:
        db_info = get_file_database_info(fits_file_path)
        if not db_info:
            out("   File is not present in database")
            return
        out(f"   File is present in database ({db_info['table']} table, ID: {db_info.get('id', 'Unknown')})")

        # Re-scan the file to update database with new WCS information
        out("Updating database entry...")
        rescan_result = rescan_single_file(fits_file_path)
        if not rescan_result['success']:
            out(f"   Error updating database: {rescan_result['message']}")
            return
        out("   Successfully updated database entry")
        updated_fields = rescan_result.get('updated_fields', {})
        if updated_fields.get('wcs_type') == 'celestial':
            out(f"   WCS type: {updated_fields['wcs_type']}")
        if updated_fields.get('image_scale') is not None:
            try:
                out(f"   Pixel scale: {float(updated_fields['image_scale']):.3f} arcsec/pixel")
            except (ValueError, TypeError):
                out(f"   Pixel scale: {updated_fields['image_scale']} arcsec/pixel")
        if updated_fields.get('ra_center') is not None and updated_fields.get('dec_center') is not None:
            try:
                out(f"   Center: RA={float(updated_fields['ra_center']):.4f}°, "
                    f"Dec={float(updated_fields['dec_center']):.4f}°")
            except (ValueError, TypeError):
                out(f"   Center: RA={updated_fields['ra_center']}, Dec={updated_fields['dec_center']}")
    except Exception as e:
        out(f"   Error checking/updating database: {e}")


def delete_library_file(path: str, fits_file_id: int = None) -> dict:
    """
    Delete a FITS file: its database record (if it has one) first, then the file on disk.
    The file is kept on disk if its database record can't be removed.

    fits_file_id: the record's id if already known; otherwise it is looked up by path.

    Returns {'in_db', 'db_deleted', 'file_deleted', 'missing_on_disk', 'error'}.
    """
    result = {'in_db': False, 'db_deleted': False, 'file_deleted': False,
              'missing_on_disk': False, 'error': None}
    db = get_db_manager()
    if fits_file_id is None:
        row = db.get_fits_file_by_path(path)
        fits_file_id = row.id if row else None
    if fits_file_id is not None:
        result['in_db'] = True
        result['db_deleted'] = db.delete_fits_file(fits_file_id)
        if not result['db_deleted']:
            result['error'] = "The file is in the database but could not be deleted from it."
            return result
    try:
        if os.path.exists(path):
            os.remove(path)
            result['file_deleted'] = True
        else:
            result['missing_on_disk'] = True
    except OSError as e:
        result['error'] = str(e)
    return result


def record_source_analysis(path: str, sources) -> dict:
    """
    Store source-detection results (average HFR in arcsec, source count) on the library record
    of path. Returns {'updated': bool, 'hfr': float or None, 'error': str or None}.
    """
    db = get_db_manager()
    row = db.get_fits_file_by_path(path)
    if row is None:
        return {'updated': False, 'hfr': None, 'error': 'File not found in database'}

    hfr_arcsec_values = [s.hfr_arcsec for s in sources if s.hfr_arcsec > 0]
    avg_hfr_arcsec = sum(hfr_arcsec_values) / len(hfr_arcsec_values) if hfr_arcsec_values else None
    updated = db.update_fits_file(row.id, {
        'hfr': avg_hfr_arcsec,
        'sources_count': len(sources),
        'analysis_status': 'analyzed',
        'analysis_date': datetime.now(),
        'analysis_method': 'photutils',
    })
    return {'updated': bool(updated), 'hfr': avg_hfr_arcsec, 'error': None if updated else 'Database update failed'}
