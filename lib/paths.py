''' On-disk layout for stacks and region views, and session-stack detection.
    Paths are read from config at call time so settings reloads take effect.
'''

import os
from pathlib import Path

import config

# Follow-up session stacks are written under STACKS_PATH/<folder>/ where <folder> is
# data_path_target_folder_name(target). Legacy stacks may still live under
# DATA_PATH/<folder>/Stacks/. Legacy DB rows may have filter_name == SESSION_STACK_FILTER_NAME;
# new session stacks store the real FILTER card and are recognized by path.
SESSION_STACK_FILTER_NAME = 'Stacks'

VIEWS_FOLDER_NAME = 'views'


def data_path_target_folder_name(target_name: str) -> str:
    """Directory name under DATA_PATH (or STACKS_PATH) for a target (spaces → underscores)."""
    if target_name is None:
        return ''
    return str(target_name).replace(' ', '_')


def stacks_path_for_target(target_name: str) -> Path:
    """Directory for final integrated session stacks for this target."""
    return Path(config.STACKS_PATH) / data_path_target_folder_name(target_name)


def legacy_stacks_path_for_target(target_name: str) -> Path:
    """Legacy session-stack directory DATA_PATH/<target>/Stacks/."""
    return Path(config.DATA_PATH) / data_path_target_folder_name(target_name) / SESSION_STACK_FILTER_NAME


def views_path_for_target(target_name: str) -> Path:
    """Directory for region-of-interest PNG views for this target."""
    return stacks_path_for_target(target_name) / VIEWS_FOLDER_NAME


def region_views_path_for_region(target_name: str, region_name: str) -> Path:
    """Directory for PNGs of a named region under STACKS_PATH/<target>/views/<region>/."""
    safe_region = str(region_name).replace(" ", "_").replace(os.sep, "_")
    return views_path_for_target(target_name) / safe_region


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
        if not p.is_relative_to(Path(config.STACKS_PATH).resolve()):
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
