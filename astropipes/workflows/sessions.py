"""
Observing sessions and runs: grouping library files into nights and into runs, and choosing the
raw frame that all stacks of a target are aligned to (ALIGNREF).
"""

import os
from pathlib import Path

from astropy.io import fits

# Images more than this many hours apart belong to different sessions
SESSION_THRESHOLD_HOURS = 12
# Consecutive frames of the same target at most this many minutes apart belong to the same run
RUN_TIME_WINDOW_MINUTES = 30


def norm_path(p):
    """Resolved absolute path string (None for empty input)."""
    if not p:
        return None
    try:
        return str(Path(p).resolve())
    except (OSError, ValueError):
        return os.path.normpath(os.path.abspath(p))


def group_files_by_session(files, session_threshold_hours=SESSION_THRESHOLD_HOURS):
    """
    Group files by session. Images taken during the same night - any image with more than
    session_threshold_hours difference is from another session.

    Args:
        files: List of FitsFile objects with date_obs attribute
        session_threshold_hours: Time difference in hours to consider a new session (default: 12)

    Returns:
        List of lists, where each inner list contains files from the same session
    """
    if not files:
        return []

    # Sort files by date_obs
    sorted_files = sorted([f for f in files if f.date_obs], key=lambda f: f.date_obs)

    if not sorted_files:
        return []

    sessions = []
    current_session = [sorted_files[0]]

    for i in range(1, len(sorted_files)):
        time_diff = sorted_files[i].date_obs - sorted_files[i-1].date_obs
        if time_diff.total_seconds() / 3600 > session_threshold_hours:
            # New session
            sessions.append(current_session)
            current_session = [sorted_files[i]]
        else:
            # Same session
            current_session.append(sorted_files[i])

    # Add the last session
    if current_session:
        sessions.append(current_session)

    return sessions


def split_into_runs(files, window_minutes=RUN_TIME_WINDOW_MINUTES):
    """
    Split files, in the given order, into runs: consecutive files of the same target whose
    date_obs are at most window_minutes apart. Returns a list of lists.
    """
    runs = []
    current_run = []
    for file in files:
        if current_run:
            last_file = current_run[-1]
            if file.date_obs and last_file.date_obs:
                gap = abs((file.date_obs - last_file.date_obs).total_seconds() / 60)
            else:
                gap = float('inf')
            if file.target == last_file.target and gap <= window_minutes:
                current_run.append(file)
                continue
            runs.append(current_run)
        current_run = [file]
    if current_run:
        runs.append(current_run)
    return runs


def _read_alignref_raw_from_stack_fits(stack_path: str):
    """Return absolute raw path from ALIGNREF if present and the file exists on disk."""
    try:
        h = fits.getheader(stack_path, ext=0)
        v = h.get('ALIGNREF')
        if v is None:
            return None
        if isinstance(v, tuple):
            v = v[0]
        s = str(v).strip().split('\n', 1)[0].strip()
        if not s:
            return None
        p = Path(s)
        if p.is_file():
            return str(p.resolve())
    except Exception:
        return None
    return None


def _alignment_ref_raw_from_existing_stacks(stack_paths):
    """Use ALIGNREF from any existing stack FITS (sorted paths for stable choice)."""
    for p in sorted(stack_paths or []):
        r = _read_alignref_raw_from_stack_fits(p)
        if r:
            return r
    return None


def resolve_alignment_reference_raw(
    files,
    *,
    existing_stack_paths=None,
    override_raw_path=None,
):
    """
    Pick one raw light path for ALIGNREF (shared across filters when stacking a target).

    Priority: explicit override, ALIGNREF on existing stacks, earliest date_obs in files.
    """
    if override_raw_path:
        p = norm_path(override_raw_path)
        if p and Path(p).is_file():
            return p
    ref = _alignment_ref_raw_from_existing_stacks(existing_stack_paths)
    if ref:
        return ref
    dated = sorted(
        [f for f in files if getattr(f, "date_obs", None)],
        key=lambda f: f.date_obs,
    )
    if dated and getattr(dated[0], "path", None):
        return norm_path(dated[0].path)
    return None
