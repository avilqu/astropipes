#!/usr/bin/env python3
"""
Daily Stacks Generation Thread
Handles daily stacks generation (group by session, calibrate, align, integrate) in a background thread for the GUI.
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from PyQt6.QtCore import QThread, pyqtSignal
from colorama import init, Fore, Style
from astropy.io import fits
import config

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from lib.fits.calibration import CalibrationManager
from lib.fits.align import align_images_chunked, check_astroalign_available
from lib.fits.integration import integrate_standard
from config import DEFAULT_ALIGNMENT_METHOD, ALIGNMENT_MEMORY_LIMIT, ALIGNMENT_CHUNK_SIZE, INTEGRATION_MEMORY_LIMIT, SIGMA_LOW, SIGMA_HIGH


class RealtimeStdout:
    """A stdout-like object that emits output immediately via a signal."""
    def __init__(self, output_signal):
        self.output_signal = output_signal
        self.buffer = ""
    
    def write(self, text):
        """Write text and emit immediately."""
        if text:
            self.buffer += text
            # Emit complete lines immediately
            while '\n' in self.buffer:
                line, self.buffer = self.buffer.split('\n', 1)
                if line:
                    self.output_signal.emit(line + '\n')
            # If buffer is getting large, emit it anyway (for long lines without newlines)
            if len(self.buffer) > 200:
                self.output_signal.emit(self.buffer)
                self.buffer = ""
    
    def flush(self):
        """Flush any remaining buffer."""
        if self.buffer:
            self.output_signal.emit(self.buffer)
            self.buffer = ""
    
    def isatty(self):
        """Return False to indicate this is not a TTY (helps with some buffering)."""
        return False


def group_files_by_session(files, session_threshold_hours=12):
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


def _resolved_path_set(paths):
    s = set()
    for p in paths or []:
        if not p:
            continue
        try:
            s.add(str(Path(p).resolve()))
        except (OSError, ValueError):
            s.add(os.path.normpath(os.path.abspath(p)))
    return s


def _norm_path_str(p):
    if not p:
        return None
    try:
        return str(Path(p).resolve())
    except (OSError, ValueError):
        return os.path.normpath(os.path.abspath(p))


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


def generate_daily_stacks_impl(
    target_name,
    files,
    filter_name,
    log,
    should_cancel,
    *,
    output_stacks_dir=None,
    allow_single_session=False,
    aligned_output_dir=None,
    skip_existing_stack_paths=None,
    stack_filename_include_session_index=True,
):
    """
    Core daily/session stack generation.

    output_stacks_dir: directory for final integrated stack FITS only (if None, uses
    PROCESSED_PATH/daily_stacks/<target_name>).

    aligned_output_dir: where to write per-image aligned FITS intermediates. If None,
    uses output_stacks_dir/aligned (legacy layout). Set to a PROCESSED_PATH subtree for
    session stacks so STACKS_PATH/<target> (or legacy DATA_PATH/.../Stacks) contains
    only final stacks.

    stack_filename_include_session_index: if True (default daily stacks), names are
    stack_<target>_<filter>_<YYYYMMDD>_sessionN.fits. If False (follow-up session stacks),
    names are stack_<target>_<filter>_<YYYYMMDD>.fits; duplicate nights on the same run
    get _2, _3, etc. before .fits.

    Alignment reference raw: read from ALIGNREF on any path in skip_existing_stack_paths
    (existing stacks); otherwise the earliest date_obs light in the batch. All stacks and
    aligned intermediates store ALIGNREF as that raw file's absolute path.
    """
    if not files:
        return {'error': 'No files found for target', 'success': False}

    filter_info = f" (filter: {filter_name})" if filter_name else ""
    log(f"{Style.BRIGHT + Fore.BLUE}Starting daily stacks generation for target: {target_name}{filter_info}{Style.RESET_ALL}")
    log(f"Total files: {len(files)}\n")

    log(f"\n{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    log(f"{Style.BRIGHT + Fore.CYAN}Step 1: Grouping files by session (12h threshold){Style.RESET_ALL}")
    log(f"{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")

    sessions = group_files_by_session(files, session_threshold_hours=12)

    if not sessions:
        return {'error': 'No valid sessions found (files must have date_obs)', 'success': False}

    if len(sessions) == 1 and not allow_single_session:
        return {
            'error': 'Only one session found for this target. Daily stacks generation requires multiple sessions.',
            'success': False,
            'single_session': True,
        }

    stacks_dir = output_stacks_dir or os.path.join(config.PROCESSED_PATH, "daily_stacks", target_name)
    os.makedirs(stacks_dir, exist_ok=True)
    existing_paths = _resolved_path_set(skip_existing_stack_paths)

    # Build per-session output paths first, so we can skip already-existing stacks
    session_jobs = []
    skipped_existing = 0
    date_base_counts = {}
    for i, session in enumerate(sessions):
        if session:
            start_time = session[0].date_obs
            end_time = session[-1].date_obs
            log(f"  Session {i+1}: {len(session)} files, from {start_time} to {end_time}\n")
            filter_suffix = f"_{filter_name}" if filter_name else ""
            session_date_str = session[0].date_obs.strftime('%Y%m%d')
            if stack_filename_include_session_index:
                output_filename = f"stack_{target_name}{filter_suffix}_{session_date_str}_session{i+1}.fits"
            else:
                base_key = (target_name, filter_name or '', session_date_str)
                n = date_base_counts.get(base_key, 0)
                date_base_counts[base_key] = n + 1
                if n == 0:
                    output_filename = f"stack_{target_name}{filter_suffix}_{session_date_str}.fits"
                else:
                    output_filename = (
                        f"stack_{target_name}{filter_suffix}_{session_date_str}_{n+1}.fits"
                    )
        else:
            output_filename = f"stack_{target_name}_{i+1}.fits"
        output_path = os.path.join(stacks_dir, output_filename)
        try:
            out_resolved = str(Path(output_path).resolve())
        except (OSError, ValueError):
            out_resolved = os.path.normpath(os.path.abspath(output_path))
        if out_resolved in existing_paths:
            skipped_existing += 1
            log(f"  ↷ Stack already in DB, skipping session {i+1}: {output_filename}\n")
            continue
        session_jobs.append((i + 1, session, output_filename, output_path))

    if not session_jobs:
        if skipped_existing:
            log(f"\n{Fore.YELLOW}↷ Skipped {skipped_existing} existing stack(s){Style.RESET_ALL}\n")
            return {
                'success': True,
                'target_name': target_name,
                'sessions_processed': len(sessions),
                'stacks_generated': 0,
                'stacks_skipped_existing': skipped_existing,
                'stack_paths': [],
            }
        return {'error': 'No stacks could be generated', 'success': False}

    calibration_manager = CalibrationManager()

    # Calibrate only files from sessions that still need stack generation
    files_to_process_paths = {
        f.path
        for _, session, _, _ in session_jobs
        for f in session
        if getattr(f, 'path', None)
    }
    files_to_process = [f for f in files if getattr(f, 'path', None) in files_to_process_paths]

    sorted_files = sorted(files_to_process, key=lambda f: f.date_obs or datetime.min)

    ref_raw = _alignment_ref_raw_from_existing_stacks(skip_existing_stack_paths)
    if not ref_raw and sorted_files:
        ref_raw = _norm_path_str(sorted_files[0].path)
    align_ref_str = _norm_path_str(ref_raw) if ref_raw else None

    job_path_norms = {_norm_path_str(p) for p in files_to_process_paths if p}
    extra_ref_calibrated_path = None
    if align_ref_str and align_ref_str not in job_path_norms:
        log(
            f"\n{Style.BRIGHT}Alignment reference raw is not in this batch; calibrating it for registration only:{Style.RESET_ALL}\n"
            f"  {align_ref_str}\n"
        )
        try:
            res = calibration_manager.calibrate_file(align_ref_str)
            if res.get('success'):
                extra_ref_calibrated_path = res['calibrated_path']
                log(f"    ✓ Calibrated reference: {os.path.basename(extra_ref_calibrated_path)}\n")
            else:
                return {
                    'error': f"Could not calibrate alignment reference frame: {res.get('error', 'unknown')}",
                    'success': False,
                }
        except Exception as e:
            return {'error': f"Could not calibrate alignment reference frame: {e}", 'success': False}

    log(f"\n{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    log(f"{Style.BRIGHT + Fore.CYAN}Step 2: Calibrating {len(files_to_process)} images for pending sessions{Style.RESET_ALL}")
    log(f"{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")

    calibrated_paths = []
    file_to_calibrated = {}
    calibrated_to_file = {}

    for i, file in enumerate(sorted_files):
        if should_cancel():
            return {'error': 'Cancelled by user', 'success': False}

        log(f"  [{i+1}/{len(sorted_files)}] Calibrating: {os.path.basename(file.path)}\n")

        try:
            result = calibration_manager.calibrate_file(file.path)
            if result.get('success'):
                calibrated_path = result['calibrated_path']
                calibrated_paths.append(calibrated_path)
                file_to_calibrated[file] = calibrated_path
                calibrated_to_file[calibrated_path] = file
                log(f"    ✓ Calibrated: {os.path.basename(calibrated_path)}\n")
            else:
                error = result.get('error', 'Unknown error')
                log(f"    ✗ Failed: {error}\n")
        except Exception as e:
            log(f"    ✗ Error: {str(e)}\n")

    if not calibrated_paths:
        return {'error': 'No files could be calibrated', 'success': False}

    ref_cal_path = None
    if align_ref_str:
        for f in files_to_process:
            if f.path and _norm_path_str(f.path) == align_ref_str:
                ref_cal_path = file_to_calibrated.get(f)
                break
    if ref_cal_path is None:
        ref_cal_path = extra_ref_calibrated_path
    if ref_cal_path is None:
        ref_cal_path = file_to_calibrated.get(sorted_files[0])

    if not ref_cal_path:
        return {'error': 'Could not resolve calibrated alignment reference frame', 'success': False}

    others_sorted = [f for f in sorted_files if f.path and _norm_path_str(f.path) != align_ref_str]
    ordered_cal_paths = [ref_cal_path]
    for f in others_sorted:
        cp = file_to_calibrated.get(f)
        if cp and cp != ref_cal_path:
            ordered_cal_paths.append(cp)

    if align_ref_str:
        log(
            f"\n{Fore.GREEN}✓ Using alignment reference raw (ALIGNREF): {align_ref_str}{Style.RESET_ALL}\n"
        )

    log(f"\n{Fore.GREEN}✓ Calibrated {len(calibrated_paths)} images for sessions"
        + (f" (+1 reference)" if extra_ref_calibrated_path else "")
        + f"{Style.RESET_ALL}\n")

    log(f"\n{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    log(f"{Style.BRIGHT + Fore.CYAN}Step 3: Aligning all {len(ordered_cal_paths)} images together{Style.RESET_ALL}")
    log(f"{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")

    image_datas = []
    headers = []
    calibrated_paths_ordered = []

    for calibrated_path in ordered_cal_paths:
        if should_cancel():
            return {'error': 'Cancelled by user', 'success': False}

        try:
            with fits.open(calibrated_path) as hdul:
                image_data = hdul[0].data
                header = hdul[0].header.copy()
                image_datas.append(image_data)
                headers.append(header)
                calibrated_paths_ordered.append(calibrated_path)
        except Exception as e:
            log(f"  Warning: Could not load {calibrated_path}: {e}\n")
            continue

    if not image_datas:
        return {'error': 'No images could be loaded for alignment', 'success': False}

    alignment_method = DEFAULT_ALIGNMENT_METHOD
    if alignment_method == "astroalign" and not check_astroalign_available():
        log(f"{Fore.YELLOW}astroalign not available, using WCS reprojection{Style.RESET_ALL}\n")
        alignment_method = "wcs_reprojection"

    log(f"  Using alignment method: {alignment_method}\n")

    try:
        def log_callback(msg):
            msg_str = str(msg)
            if not msg_str.endswith('\n'):
                msg_str += '\n'
            log(f"  {msg_str}")

        aligned_datas, reference_header = align_images_chunked(
            image_datas,
            headers,
            method=alignment_method,
            reference_index=0,
            chunk_size=ALIGNMENT_CHUNK_SIZE,
            memory_limit=ALIGNMENT_MEMORY_LIMIT,
            log_callback=log_callback,
        )

        log(f"\n{Fore.GREEN}✓ Aligned {len(aligned_datas)} images{Style.RESET_ALL}\n")

    except Exception as e:
        error_msg = f"Alignment failed: {e}"
        log(f"{Fore.RED}✗ {error_msg}{Style.RESET_ALL}\n")
        return {'error': error_msg, 'success': False}

    log(f"\n{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    log(f"{Style.BRIGHT + Fore.CYAN}Step 4: Saving aligned images and generating stacks{Style.RESET_ALL}")
    log(f"{Style.BRIGHT + Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")

    if aligned_output_dir is not None:
        aligned_dir = aligned_output_dir
    else:
        aligned_dir = os.path.join(stacks_dir, "aligned")
    os.makedirs(aligned_dir, exist_ok=True)

    calibrated_to_aligned = {}
    for i, calibrated_path in enumerate(calibrated_paths_ordered):
        if i < len(aligned_datas):
            aligned_data = aligned_datas[i]
            aligned_header = reference_header.copy()
            aligned_header['NAXIS1'] = aligned_data.shape[1]
            aligned_header['NAXIS2'] = aligned_data.shape[0]

            from lib.fits.wcs import copy_wcs_from_reference
            aligned_header = copy_wcs_from_reference(reference_header, aligned_header)

            # Keep each frame's observation time (reference header would duplicate DATE-OBS on all)
            _orig = headers[i]
            for _key in ('DATE-OBS', 'TIME-OBS', 'MJD-OBS', 'DATE-END'):
                if _key in _orig:
                    aligned_header[_key] = _orig[_key]

            aligned_header['ALIGNED'] = (True, 'Image has been aligned')
            if align_ref_str:
                aligned_header['ALIGNREF'] = (align_ref_str, 'Absolute path to raw used as alignment reference')

            base_name = os.path.basename(calibrated_path)
            aligned_path = os.path.join(aligned_dir, f"aligned_{base_name}")

            hdu = fits.PrimaryHDU(data=aligned_data, header=aligned_header)
            hdu.writeto(aligned_path, overwrite=True)

            calibrated_to_aligned[calibrated_path] = aligned_path

    log(f"  Saved {len(calibrated_to_aligned)} aligned images\n")

    stack_paths = []
    for session_idx, session, output_filename, output_path in session_jobs:
        if should_cancel():
            return {'error': 'Cancelled by user', 'success': False}

        log(f"\n{Style.BRIGHT}Processing session {session_idx}/{len(sessions)} ({len(session)} files){Style.RESET_ALL}\n")

        session_aligned_paths = []

        for file in session:
            if file in file_to_calibrated:
                calibrated_path = file_to_calibrated[file]
                if calibrated_path in calibrated_to_aligned:
                    session_aligned_paths.append(calibrated_to_aligned[calibrated_path])

        if not session_aligned_paths:
            log(f"  Warning: No aligned images for session {session_idx + 1}, skipping\n")
            continue

        try:
            log(f"  Integrating {len(session_aligned_paths)} images...\n")

            def progress_callback(progress):
                log(f"  Progress: {progress*100:.1f}%\n")

            integrate_standard(
                session_aligned_paths,
                method='average',
                sigma_clip=True,
                output_path=output_path,
                progress_callback=progress_callback,
                memory_limit=INTEGRATION_MEMORY_LIMIT,
                alignment_reference_raw_path=align_ref_str,
            )

            stack_paths.append(output_path)
            log(f"  ✓ Stack saved: {output_filename}\n")

        except Exception as e:
            error_msg = f"Integration failed for session {session_idx}: {e}"
            log(f"  ✗ {error_msg}\n")
            continue

    if not stack_paths and skipped_existing == 0:
        return {'error': 'No stacks could be generated', 'success': False}

    if stack_paths:
        log(f"\n{Fore.GREEN}✓ Generated {len(stack_paths)} stack(s){Style.RESET_ALL}\n")
    if skipped_existing:
        log(f"\n{Fore.YELLOW}↷ Skipped {skipped_existing} existing stack(s){Style.RESET_ALL}\n")

    return {
        'success': True,
        'target_name': target_name,
        'sessions_processed': len(sessions),
        'stacks_generated': len(stack_paths),
        'stacks_skipped_existing': skipped_existing,
        'stack_paths': stack_paths,
    }


class DailyStacksGenerationThread(QThread):
    """Thread for performing daily stacks generation (group by session, calibrate, align, integrate) for a target."""
    
    output = pyqtSignal(str)  # Emit process output
    finished = pyqtSignal(dict)  # Emit final result
    
    def __init__(self, target_name, files, filter_name=None, output_stacks_dir=None, allow_single_session=False):
        """
        Initialize the daily stacks generation thread.
        
        Args:
            target_name: Name of the target
            files: List of FitsFile objects for the target (already filtered by filter if provided)
            filter_name: Optional filter name for display purposes
            output_stacks_dir: If set, write stacks here; else PROCESSED_PATH/daily_stacks/<target>
            allow_single_session: If True, allow a single session (session stacks); else require 2+
        """
        super().__init__()
        self.target_name = target_name
        self.files = files
        self.filter_name = filter_name
        self._output_stacks_dir = output_stacks_dir
        self._allow_single_session = allow_single_session
        self._running = True
        
        # Initialize colorama
        init(autoreset=False)
    
    def stop(self):
        """Stop the thread execution."""
        self._running = False
    
    def _log(self, message):
        """Log a message via the output signal."""
        self.output.emit(message)
    
    def run(self):
        """Run the daily stacks generation process."""
        try:
            result = self._generate_daily_stacks()
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit({'error': str(e), 'success': False})
    
    def _generate_daily_stacks(self):
        """Generate daily stacks for all sessions of the target."""
        stacks_dir = self._output_stacks_dir or os.path.join(config.PROCESSED_PATH, "daily_stacks", self.target_name)
        return generate_daily_stacks_impl(
            self.target_name,
            self.files,
            self.filter_name,
            self._log,
            lambda: not self._running,
            output_stacks_dir=stacks_dir,
            allow_single_session=self._allow_single_session,
        )
