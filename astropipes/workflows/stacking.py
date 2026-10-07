"""
Stacking pipelines: calibrate → align → integrate library files.

- generate_session_stacks: one stack per observing session of a target (daily stacks, and the
  follow-up session stacks written to STACKS_PATH).
- generate_follow_up_session_stacks: session stacks for every follow-up target and filter, then
  register them in the library and plate-solve them.
- generate_filter_masters: one integrated image per filter of a target.

Each takes log(text) and should_cancel() callables and returns a result dict with 'success'
(and 'error' on failure).
"""

import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from astropy.io import fits
from colorama import Fore, Style

from astropipes.config import settings
from astropipes.core import paths
from astropipes.core.log import log_banner
from astropipes.core.naming import data_path_target_folder_name, path_slug
from astropipes.db import get_db_manager
from astropipes.db.scan import FitsFileScanner
from astropipes.processing.alignment import align_images_chunked, aligned_frame_header, choose_alignment_method
from astropipes.processing.calibration import CalibrationManager
from astropipes.processing.integration import integrate_standard
from astropipes.workflows.library import solve_and_update_library
from astropipes.workflows.sessions import group_files_by_session, norm_path, resolve_alignment_reference_raw

CANCELLED = {'error': 'Cancelled by user', 'success': False}


# --- Shared steps ---

def calibrate_files(files, log, should_cancel, calibration_manager=None):
    """Calibrate library files in the given order.

    Returns {file: calibrated_path} for the files that calibrated, or None if cancelled.
    """
    calibration_manager = calibration_manager or CalibrationManager()
    file_to_calibrated = {}
    for i, file in enumerate(files):
        if should_cancel():
            return None
        log(f"  [{i+1}/{len(files)}] Calibrating: {os.path.basename(file.path)}\n")
        try:
            result = calibration_manager.calibrate_file(file.path)
            if result.get('success') and 'calibrated_path' in result:
                calibrated_path = result['calibrated_path']
                file_to_calibrated[file] = calibrated_path
                log(f"    ✓ Calibrated: {os.path.basename(calibrated_path)}\n")
            else:
                log(f"    ✗ Failed: {result.get('error', 'Unknown error')}\n")
        except Exception as e:
            log(f"    ✗ Error: {e}\n")
    return file_to_calibrated


def load_images(fits_paths, log, should_cancel):
    """Read data and headers of FITS files, skipping unreadable ones.

    Returns (image_datas, headers, loaded_paths), or None if cancelled.
    """
    image_datas, headers, loaded_paths = [], [], []
    for path in fits_paths:
        if should_cancel():
            return None
        try:
            with fits.open(path) as hdul:
                image_datas.append(hdul[0].data)
                headers.append(hdul[0].header.copy())
                loaded_paths.append(path)
        except Exception as e:
            log(f"  Warning: Could not load {path}: {e}\n")
    return image_datas, headers, loaded_paths


def align_loaded_images(image_datas, headers, log):
    """Align images to the first one with the configured method. Raises AlignmentError."""
    method, notice = choose_alignment_method(None, headers)
    if notice:
        log(f"{Fore.YELLOW}{notice}{Style.RESET_ALL}\n")
    log(f"  Using alignment method: {method}\n")

    def log_callback(msg):
        msg_str = str(msg)
        if not msg_str.endswith('\n'):
            msg_str += '\n'
        log(f"  {msg_str}")

    return align_images_chunked(
        image_datas,
        headers,
        method=method,
        reference_index=0,
        chunk_size=settings.ALIGNMENT_CHUNK_SIZE,
        memory_limit=settings.ALIGNMENT_MEMORY_LIMIT,
        log_callback=log_callback,
    )


def write_aligned_frames(aligned_datas, headers, source_paths, reference_header, out_dir, *,
                         header_base, alignref):
    """Write aligned_<name> FITS files to out_dir. Returns {source_path: aligned_path}.

    header_base: see aligned_frame_header. alignref: (value, comment) for the ALIGNREF card, or None.
    """
    os.makedirs(out_dir, exist_ok=True)
    source_to_aligned = {}
    for aligned_data, header, source_path in zip(aligned_datas, headers, source_paths):
        aligned_header = aligned_frame_header(header, reference_header, aligned_data.shape, base=header_base)
        aligned_header['ALIGNED'] = (True, 'Image has been aligned')
        if alignref:
            aligned_header['ALIGNREF'] = alignref
        aligned_path = os.path.join(out_dir, f"aligned_{os.path.basename(source_path)}")
        fits.PrimaryHDU(data=aligned_data, header=aligned_header).writeto(aligned_path, overwrite=True)
        source_to_aligned[source_path] = aligned_path
    return source_to_aligned


# --- Session stacks ---

def generate_session_stacks(
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
    alignment_reference_raw_path=None,
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

    alignment_reference_raw_path: if set, force this raw FITS as the alignment reference
    (used for cross-filter session stacks). Otherwise resolve via resolve_alignment_reference_raw
    from skip_existing_stack_paths and earliest date_obs in files.

    All stacks and aligned intermediates store ALIGNREF as that raw file's absolute path.
    """
    if not files:
        return {'error': 'No files found for target', 'success': False}

    filter_info = f" (filter: {filter_name})" if filter_name else ""
    log(f"{Style.BRIGHT + Fore.BLUE}Starting daily stacks generation for target: {target_name}{filter_info}{Style.RESET_ALL}")
    log(f"Total files: {len(files)}\n")

    log_banner(log, "Step 1: Grouping files by session (12h threshold)")

    sessions = group_files_by_session(files)

    if not sessions:
        return {'error': 'No valid sessions found (files must have date_obs)', 'success': False}

    if len(sessions) == 1 and not allow_single_session:
        return {
            'error': 'Only one session found for this target. Daily stacks generation requires multiple sessions.',
            'success': False,
            'single_session': True,
        }

    stacks_dir = output_stacks_dir or paths.work_dir("daily_stacks", target_name)
    os.makedirs(stacks_dir, exist_ok=True)
    existing_paths = {norm_path(p) for p in skip_existing_stack_paths or [] if p}

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
        if norm_path(output_path) in existing_paths:
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

    ref_raw = resolve_alignment_reference_raw(
        files,
        existing_stack_paths=skip_existing_stack_paths,
        override_raw_path=alignment_reference_raw_path,
    )
    align_ref_str = norm_path(ref_raw) if ref_raw else None

    job_path_norms = {norm_path(p) for p in files_to_process_paths if p}
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

    log_banner(log, f"Step 2: Calibrating {len(files_to_process)} images for pending sessions")

    file_to_calibrated = calibrate_files(sorted_files, log, should_cancel, calibration_manager)
    if file_to_calibrated is None:
        return CANCELLED
    if not file_to_calibrated:
        return {'error': 'No files could be calibrated', 'success': False}

    ref_cal_path = None
    if align_ref_str:
        for f in files_to_process:
            if f.path and norm_path(f.path) == align_ref_str:
                ref_cal_path = file_to_calibrated.get(f)
                break
    if ref_cal_path is None:
        ref_cal_path = extra_ref_calibrated_path
    if ref_cal_path is None:
        # Designated raw (ALIGNREF or earliest light) may fail calibration (e.g. flat size
        # mismatch) while later subs still calibrate; use first successful light as ref.
        for f in sorted_files:
            cp = file_to_calibrated.get(f)
            if cp:
                ref_cal_path = cp
                log(
                    f"\n{Fore.YELLOW}Alignment reference raw had no calibrated frame in this batch; "
                    f"using first calibrated light: {os.path.basename(f.path)}{Style.RESET_ALL}\n"
                )
                break

    if not ref_cal_path:
        return {'error': 'Could not resolve calibrated alignment reference frame', 'success': False}

    others_sorted = [f for f in sorted_files if f.path and norm_path(f.path) != align_ref_str]
    ordered_cal_paths = [ref_cal_path]
    for f in others_sorted:
        cp = file_to_calibrated.get(f)
        if cp and cp != ref_cal_path:
            ordered_cal_paths.append(cp)

    if align_ref_str:
        log(
            f"\n{Fore.GREEN}✓ Using alignment reference raw (ALIGNREF): {align_ref_str}{Style.RESET_ALL}\n"
        )

    log(f"\n{Fore.GREEN}✓ Calibrated {len(file_to_calibrated)} images for sessions"
        + (" (+1 reference)" if extra_ref_calibrated_path else "")
        + f"{Style.RESET_ALL}\n")

    log_banner(log, f"Step 3: Aligning all {len(ordered_cal_paths)} images together")

    loaded = load_images(ordered_cal_paths, log, should_cancel)
    if loaded is None:
        return CANCELLED
    image_datas, headers, calibrated_paths_ordered = loaded
    if not image_datas:
        return {'error': 'No images could be loaded for alignment', 'success': False}

    try:
        aligned_datas, reference_header = align_loaded_images(image_datas, headers, log)
        log(f"\n{Fore.GREEN}✓ Aligned {len(aligned_datas)} images{Style.RESET_ALL}\n")
    except Exception as e:
        error_msg = f"Alignment failed: {e}"
        log(f"{Fore.RED}✗ {error_msg}{Style.RESET_ALL}\n")
        return {'error': error_msg, 'success': False}

    log_banner(log, "Step 4: Saving aligned images and generating stacks")

    calibrated_to_aligned = write_aligned_frames(
        aligned_datas, headers, calibrated_paths_ordered, reference_header,
        aligned_output_dir if aligned_output_dir is not None else os.path.join(stacks_dir, "aligned"),
        header_base="reference",
        alignref=(align_ref_str, 'Absolute path to raw used as alignment reference') if align_ref_str else None,
    )
    log(f"  Saved {len(calibrated_to_aligned)} aligned images\n")

    stack_paths = []
    for session_idx, session, output_filename, output_path in session_jobs:
        if should_cancel():
            return CANCELLED

        log(f"\n{Style.BRIGHT}Processing session {session_idx}/{len(sessions)} ({len(session)} files){Style.RESET_ALL}\n")

        session_aligned_paths = []
        for file in session:
            calibrated_path = file_to_calibrated.get(file)
            if calibrated_path in calibrated_to_aligned:
                session_aligned_paths.append(calibrated_to_aligned[calibrated_path])

        if not session_aligned_paths:
            log(f"  Warning: No aligned images for session {session_idx}, skipping\n")
            continue

        try:
            log(f"  Integrating {len(session_aligned_paths)} images...\n")

            integrate_standard(
                session_aligned_paths,
                method='average',
                sigma_clip=True,
                output_path=output_path,
                progress_callback=lambda progress: log(f"  Progress: {progress*100:.1f}%\n"),
                memory_limit=settings.INTEGRATION_MEMORY_LIMIT,
                alignment_reference_raw_path=align_ref_str,
            )

            stack_paths.append(output_path)
            log(f"  ✓ Stack saved: {output_filename}\n")

        except Exception as e:
            log(f"  ✗ Integration failed for session {session_idx}: {e}\n")
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
        'alignment_reference_raw_path': align_ref_str,
    }


def _files_matching_filter(raw_files, filter_name: str):
    if filter_name == "Unknown":
        return [f for f in raw_files if not f.filter_name or f.filter_name == "Unknown"]
    return [f for f in raw_files if f.filter_name == filter_name]


def generate_follow_up_session_stacks(log, should_cancel):
    """
    Session stacks for every follow-up target and flagged filter, written to STACKS_PATH/<target>/.
    New stacks are registered in the library and plate-solved. All filters of a target share
    one alignment reference raw frame.
    """
    results = {"success": True, "errors": []}
    db = get_db_manager()
    targets = db.follow_up_get_targets()
    if not targets:
        return {"success": False, "error": "No targets flagged for follow-up."}

    scanner = FitsFileScanner()
    for target in targets:
        if should_cancel():
            break
        filter_names = db.follow_up_get_filters(target)
        files_all = db.get_files_by_target(target)
        raw_files = [f for f in files_all if not paths.is_session_stack_fits_file(f)]
        existing_stack_paths = {
            f.path for f in files_all if paths.is_session_stack_fits_file(f) and f.path
        }
        target_align_ref = resolve_alignment_reference_raw(
            raw_files,
            existing_stack_paths=existing_stack_paths,
        )
        if target_align_ref:
            log(f"\nTarget alignment reference (all filters): {target_align_ref}\n")
        for fn in filter_names:
            if should_cancel():
                break
            subset = _files_matching_filter(raw_files, fn)
            if not subset:
                log(f"\nNo light frames for target {target!r} with filter {fn!r} — skipping.\n")
                continue
            out_dir = paths.stacks_path_for_target(target)
            out_dir.mkdir(parents=True, exist_ok=True)
            aligned_dir = Path(paths.work_dir(
                "session_stacks_work", data_path_target_folder_name(target), path_slug(fn), "aligned"
            ))
            aligned_dir.mkdir(parents=True, exist_ok=True)
            log_banner(log, f"Session stacks: {target} / {fn}")
            res = generate_session_stacks(
                target,
                subset,
                fn,
                log,
                should_cancel,
                output_stacks_dir=str(out_dir),
                allow_single_session=True,
                aligned_output_dir=str(aligned_dir),
                skip_existing_stack_paths=existing_stack_paths,
                stack_filename_include_session_index=False,
                alignment_reference_raw_path=target_align_ref,
            )
            if not res.get("success"):
                err = res.get("error", "unknown error")
                results["errors"].append((target, fn, err))
                log(f"✗ Stack generation failed: {err}\n")
                continue
            skipped_existing = res.get("stacks_skipped_existing", 0)
            if skipped_existing:
                log(f"  ↷ Skipped {skipped_existing} stack(s) already present in database\n")
            ref_from_run = res.get("alignment_reference_raw_path")
            if ref_from_run:
                target_align_ref = ref_from_run
            for p in res.get("stack_paths", []):
                existing_stack_paths.add(p)
                if should_cancel():
                    break
                path = Path(p)
                imported = scanner.import_fits_with_layout_target(
                    path, target, filter_fallback=fn
                )
                if imported:
                    log(f"  Registered in database: {path.name}\n")
                else:
                    log(f"  (Skipped DB import — already registered: {path.name})\n")

                sol = solve_and_update_library(str(path), output_callback=log)
                if not sol.success:
                    msg = getattr(sol, "message", "platesolve failed")
                    results["errors"].append((target, fn, str(path), msg))
                    log(f"  ✗ Platesolve failed: {msg}\n")
                else:
                    log(f"  ✓ Platesolved: {path.name}\n")

    if should_cancel():
        results["success"] = False
        results["cancelled"] = True
    return results


# --- Per-filter masters ---

def generate_filter_masters(target_name, files, log, should_cancel):
    """
    Calibrate and align all files of a target together, then integrate one image per filter
    into PROCESSED_PATH/integrated/<target>/.
    """
    if not files:
        return {'error': 'No files found for target', 'success': False}

    log(f"{Style.BRIGHT + Fore.BLUE}Starting masters generation for target: {target_name}{Style.RESET_ALL}\n")
    log(f"Total files: {len(files)}\n\n")

    # Group files by filter for later integration
    files_by_filter = defaultdict(list)
    for file in files:
        files_by_filter[file.filter_name or "Unknown"].append(file)
    log(f"Found {len(files_by_filter)} filter(s): {', '.join(files_by_filter.keys())}\n\n")

    # Step 1: Calibrate all images (regardless of filter)
    log_banner(log, f"Step 1: Calibrating all {len(files)} images")
    sorted_files = sorted(files, key=lambda f: f.date_obs or datetime.min)
    file_to_calibrated = calibrate_files(sorted_files, log, should_cancel)
    if file_to_calibrated is None:
        return CANCELLED
    if not file_to_calibrated:
        return {'error': 'No images were successfully calibrated', 'success': False}
    calibrated_paths = [file_to_calibrated[f] for f in sorted_files if f in file_to_calibrated]
    log(f"\n{Fore.GREEN}✓ Calibrated {len(calibrated_paths)}/{len(sorted_files)} images{Style.RESET_ALL}\n\n")

    # Step 2: Align all calibrated images together (regardless of filter)
    log_banner(log, f"Step 2: Aligning all {len(calibrated_paths)} calibrated images")
    loaded = load_images(calibrated_paths, log, should_cancel)
    if loaded is None:
        return CANCELLED
    image_datas, headers, loaded_paths = loaded

    if len(image_datas) < 2:
        log(f"{Fore.YELLOW}Warning: Only {len(image_datas)} image(s), skipping alignment{Style.RESET_ALL}\n\n")
        path_to_aligned = {path: path for path in loaded_paths}
    else:
        try:
            aligned_datas, reference_header = align_loaded_images(image_datas, headers, log)
            path_to_aligned = write_aligned_frames(
                aligned_datas, headers, loaded_paths, reference_header,
                paths.work_dir("aligned", target_name),
                header_base="frame",
                alignref=(os.path.basename(loaded_paths[0]), 'Reference image for alignment'),
            )
            log(f"\n{Fore.GREEN}✓ Aligned {len(path_to_aligned)} images{Style.RESET_ALL}\n\n")
        except Exception as e:
            error_msg = f"Alignment failed: {e}"
            log(f"{Fore.RED}✗ {error_msg}{Style.RESET_ALL}\n")
            return {'error': error_msg, 'success': False}

    # Step 3: Integrate images per filter
    log_banner(log, "Step 3: Integrating images per filter")
    results = {}
    for filter_name, filter_files in files_by_filter.items():
        if should_cancel():
            return CANCELLED
        log(f"\n{Style.BRIGHT}Processing filter: {filter_name} ({len(filter_files)} files){Style.RESET_ALL}\n")
        aligned_paths = [
            path_to_aligned[file_to_calibrated[f]]
            for f in filter_files
            if f in file_to_calibrated and file_to_calibrated[f] in path_to_aligned
        ]
        if not aligned_paths:
            error_msg = f"No aligned images found for filter {filter_name}"
            log(f"{Fore.RED}✗ {error_msg}{Style.RESET_ALL}\n")
            results[filter_name] = {'error': error_msg, 'success': False}
            continue
        results[filter_name] = _integrate_filter(target_name, filter_name, aligned_paths, log)

    successful = sum(1 for r in results.values() if r.get('success', False))
    failed = len(results) - successful
    log_banner(log, "Masters Generation Summary")
    log(f"Filters processed: {len(results)}\n")
    log(f"Successful: {successful}\n")
    log(f"Failed: {failed}\n\n")

    return {
        'success': successful > 0,
        'results': results,
        'total_filters': len(results),
        'successful_filters': successful,
        'failed_filters': failed,
    }


def _integrate_filter(target_name, filter_name, aligned_paths, log):
    """Integrate aligned images for a single filter."""
    try:
        output_dir = paths.work_dir("integrated", target_name)
        os.makedirs(output_dir, exist_ok=True)
        safe_filter = filter_name.replace(' ', '_').replace('/', '_')
        output_path = os.path.join(output_dir, f"{target_name}_{safe_filter}_integrated.fits")

        log(f"  Integrating {len(aligned_paths)} images...\n")

        def progress_callback(progress):
            if progress < 1.0:
                log(f"    Progress: {progress*100:.1f}%\n")

        integrate_standard(
            files=aligned_paths,
            method='average',
            sigma_clip=False,
            output_path=output_path,
            progress_callback=progress_callback,
            memory_limit=settings.INTEGRATION_MEMORY_LIMIT,
        )

        log(f"  {Fore.GREEN}✓ Integration complete{Style.RESET_ALL}\n")
        log(f"    Output: {output_path}\n\n")
        return {
            'success': True,
            'aligned_count': len(aligned_paths),
            'integrated_path': output_path,
            'filter': filter_name,
        }
    except Exception as e:
        error_msg = f"Integration failed: {e}"
        log(f"  {Fore.RED}✗ {error_msg}{Style.RESET_ALL}\n\n")
        return {'error': error_msg, 'success': False}
