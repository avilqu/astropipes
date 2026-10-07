''' On-disk layout: stacks, region views, PROCESSED_PATH work folders, and session-stack detection.
    Paths are read from settings at call time so settings reloads take effect.
'''

import glob
import os
import shutil
from pathlib import Path

from astropipes.config import settings
from astropipes.core.naming import data_path_target_folder_name, path_slug

# Follow-up session stacks are written under STACKS_PATH/<folder>/ where <folder> is
# data_path_target_folder_name(target). Legacy stacks may still live under
# DATA_PATH/<folder>/Stacks/. Legacy DB rows may have filter_name == SESSION_STACK_FILTER_NAME;
# new session stacks store the real FILTER card and are recognized by path.
SESSION_STACK_FILTER_NAME = 'Stacks'

VIEWS_FOLDER_NAME = 'views'


def stacks_path_for_target(target_name: str) -> Path:
    """Directory for final integrated session stacks for this target."""
    return Path(settings.STACKS_PATH) / data_path_target_folder_name(target_name)


def legacy_stacks_path_for_target(target_name: str) -> Path:
    """Legacy session-stack directory DATA_PATH/<target>/Stacks/."""
    return Path(settings.DATA_PATH) / data_path_target_folder_name(target_name) / SESSION_STACK_FILTER_NAME


def views_path_for_target(target_name: str) -> Path:
    """Directory for region-of-interest PNG views for this target."""
    return stacks_path_for_target(target_name) / VIEWS_FOLDER_NAME


def region_views_path_for_region(target_name: str, region_name: str) -> Path:
    """Directory for PNGs of a named region under STACKS_PATH/<target>/views/<region>/."""
    return views_path_for_target(target_name) / path_slug(region_name)


def path_indicates_session_stack(file_path: str) -> bool:
    """
    True if this filesystem path is a session-stack location: legacy .../Stacks/... tree
    or any file under STACKS_PATH.
    """
    if not file_path:
        return False
    try:
        p = Path(file_path).resolve()
        if SESSION_STACK_FILTER_NAME in p.parts:
            return True
        if not p.is_relative_to(Path(settings.STACKS_PATH).resolve()):
            return False
        # PNG views and other non-stack assets under .../views/ are not session stacks
        return VIEWS_FOLDER_NAME not in p.parts
    except (ValueError, OSError):
        return False


def is_session_stack_fits_file(fits_file) -> bool:
    """
    True if this library row is a session stack (Follow-up), not a raw light frame.
    Uses filter_name and path (STACKS_PATH tree or legacy .../Stacks/...) so rows stay
    correct after platesolve/rescan.
    """
    fn = (getattr(fits_file, 'filter_name', None) or '').strip()
    if fn == SESSION_STACK_FILTER_NAME:
        return True
    path = getattr(fits_file, 'path', None) or ''
    return path_indicates_session_stack(path)


# PROCESSED_PATH subfolders emptied by clean_work_dirs() ("Clean temporary files" in the Library)
CLEANABLE_WORK_DIRS = ("solved", "calibrated", "stacked", "aligned", "substacks", "session_stacks_work")


def work_dir(*parts) -> str:
    """Path of a work folder under PROCESSED_PATH, e.g. work_dir("aligned", target)."""
    return os.path.join(settings.PROCESSED_PATH, *parts)


def clean_work_dirs():
    """Delete everything inside the CLEANABLE_WORK_DIRS folders of PROCESSED_PATH."""
    for name in CLEANABLE_WORK_DIRS:
        temp_dir = work_dir(name)
        if not os.path.exists(temp_dir):
            continue
        for filename in glob.glob(os.path.join(temp_dir, "*")):
            try:
                if os.path.isfile(filename) or os.path.islink(filename):
                    os.unlink(filename)
                elif os.path.isdir(filename):
                    shutil.rmtree(filename)
            except Exception as e:
                print(f"Failed to delete {filename}: {e}")
