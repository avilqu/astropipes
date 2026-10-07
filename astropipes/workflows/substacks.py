"""
Motion-tracked substacks: split a sequence of individual frames into three consecutive
thirds and stack each on a moving object, so its position can be measured at three epochs.
"""

import json
import os
import re
from datetime import datetime

from astropy.io import fits

from astropipes.config import settings
from astropipes.core.paths import work_dir
from astropipes.db import get_db_manager
from astropipes.processing.motion_tracking import integrate_with_motion_tracking


def individual_frames(files):
    """Drop stacked images (COMBINED header card) from files; unreadable files are kept."""
    individual_files = []
    for file_path in files:
        try:
            with fits.open(file_path) as hdul:
                combined = hdul[0].header.get('COMBINED', False)
            if isinstance(combined, str):
                combined = combined.lower() in ('true', '1', 'yes')
            if not combined:
                individual_files.append(file_path)
            else:
                print(f"Excluding stacked image: {os.path.basename(file_path)}")
        except Exception as e:
            # If we can't read the header, assume it's an individual image
            print(f"Warning: Could not read header for {file_path}: {e}")
            individual_files.append(file_path)
    return individual_files


def sort_files_by_date(files):
    """Sort files by DATE-OBS (header, else library database, else file modification time)."""
    file_dates = []
    for file_path in files:
        date_obs = None
        try:
            with fits.open(file_path) as hdul:
                date_obs = hdul[0].header.get('DATE-OBS')
        except Exception:
            pass

        # If not found in header, try database
        if not date_obs:
            try:
                db_entry = get_db_manager().get_fits_file_by_path(file_path)
                if db_entry and db_entry.date_obs:
                    date_obs = db_entry.date_obs.isoformat(sep='T', timespec='seconds')
            except Exception:
                pass

        # Use file modification time as fallback
        if not date_obs:
            date_obs = datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat()

        file_dates.append((file_path, date_obs))

    file_dates.sort(key=lambda x: x[1])
    return [file_path for file_path, _ in file_dates]


def split_in_thirds(sorted_files):
    """Three consecutive groups of len // 3 files; the last one takes the remainder."""
    size = len(sorted_files) // 3
    return [sorted_files[:size], sorted_files[size:2 * size], sorted_files[2 * size:]]


def reference_positions(positions, substack_files):
    """
    Object pixel position for each substack: the measured position on its first file.

    In a motion-tracked stack the object is shifted so that the pixel position of the FIRST
    image becomes the reference for the whole substack, so averaging the positions would add
    an offset of about half the object's motion within the substack.
    positions: dicts with file_path / original_x / original_y. None where no file matches.
    """
    result = []
    for file_list in substack_files:
        match = None
        for fp in file_list:
            match = next((p for p in positions if p['file_path'] == fp), None)
            if match is not None:
                break
        result.append((match['original_x'], match['original_y']) if match else None)
    return result


def parse_pixel_position(object_position):
    """(x, y) floats from a tuple/list, or a string such as "(1158.9, 863.2)" or "1158.9, 863.2"."""
    try:
        if isinstance(object_position, (tuple, list)) and len(object_position) == 2:
            return float(object_position[0]), float(object_position[1])
        if isinstance(object_position, str):
            numbers = re.findall(r'[-+]?\d*\.?\d+', object_position)
            if len(numbers) >= 2:
                return float(numbers[0]), float(numbers[1])
        raise ValueError(f"Could not parse coordinates from: {object_position}")
    except (ValueError, TypeError) as e:
        raise Exception(f"Invalid object position coordinates: {object_position}. "
                        f"Expected numeric values. Error: {str(e)}")


def write_measurement_marker(fits_path, object_position):
    """
    Store the expected object position (pixel coordinates) in the MEAS_POS header card so
    that the viewer can show a yellow measurement marker.
    """
    if object_position is None:
        return
    try:
        x, y = parse_pixel_position(object_position)
        with fits.open(fits_path, mode='update') as hdul:
            hdul[0].header['MEAS_POS'] = json.dumps([float(x), float(y)])
            hdul.flush()
    except Exception as exc:
        print(f"Warning: could not write MEAS_POS to {fits_path}: {exc}")


def generate_substacks(substack_files, object_name, object_positions, ephemerides_data, log, should_cancel):
    """
    Median motion-tracked stack of each file group in substack_files, written to
    PROCESSED_PATH/substacks/substack<N>_<object>_<timestamp>.fits with a MEAS_POS marker
    at object_positions[N-1].

    Returns {'success', 'message', 'output_files'}.
    """
    output_dir = work_dir("substacks")
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_object_name = object_name.replace(' ', '_').replace('/', '_').replace('\\', '_')

    log(f"\033[1;34mStarting substack generation for {object_name}\033[0m\n")
    log(f"\033[1;34mTotal individual files: {sum(len(files) for files in substack_files)}\033[0m\n")
    log("\033[1;34mStacking method: Median\033[0m\n")
    log("\033[1;34mNote: Only individual images are used (stacked images are excluded)\033[0m\n")
    for i, position in enumerate(object_positions or []):
        if position is not None:
            x, y = parse_pixel_position(position)
            log(f"\033[1;34mObject position for substack {i+1}: ({x:.1f}, {y:.1f})\033[0m\n")
    log("\n")

    output_files = []
    for n, files in enumerate(substack_files, start=1):
        if should_cancel():
            return {'success': False, 'message': 'Cancelled by user', 'output_files': output_files}
        log(f"\033[1;33m=== SUBSTACK {n} ===\033[0m\n")
        log(f"Files ({len(files)}):\n")
        for i, file_path in enumerate(files, 1):
            log(f"  {i:2d}. {os.path.basename(file_path)}\n")
        log("\n")

        output_file = os.path.join(output_dir, f"substack{n}_{safe_object_name}_{timestamp}.fits")
        log(f"\033[1;33mCreating substack {n} (median)...\033[0m\n")
        try:
            integrate_with_motion_tracking(
                files=files,
                object_name=object_name,
                method='median',  # Force median stacking for substacks
                sigma_clip=settings.MOTION_TRACKING_SIGMA_CLIP,
                output_path=output_file,
                ephemerides_data=ephemerides_data,
            )
        except Exception as e:
            raise Exception(f"Error creating motion tracked stack: {str(e)}")
        output_files.append(output_file)
        log(f"\033[1;32m✓ Substack {n} completed: {os.path.basename(output_file)}\033[0m\n")

        write_measurement_marker(output_file, object_positions[n - 1] if object_positions else None)
        log("\n")

    message = "Successfully generated 3 motion-tracked substacks\n"
    message += f"Object: {object_name}\n"
    message += "Method: Median stacking\n"
    for n, (files, output_file) in enumerate(zip(substack_files, output_files), start=1):
        message += f"  – Substack {n}: {len(files)} files → {os.path.basename(output_file)}\n"
    message += f"Output directory: {output_dir}"
    return {'success': True, 'message': message, 'output_files': output_files}
