"""Copy oldest and newest region-view PNGs for the latest observing session."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Set, Tuple

import config
from lib.fits.region_views import SkyRegion, region_in_image_field


def _view_sort_key(view) -> datetime:
    if view.date_obs:
        return view.date_obs
    try:
        return datetime.fromtimestamp(os.path.getmtime(view.png_path))
    except OSError:
        return datetime.min


def _region_export_filename(region_name: str, role: str) -> str:
    """Build dest name like 'NGC 2997 - 01-NEW.png' (role is REF or NEW)."""
    safe = region_name
    for ch in ("/", "\\"):
        safe = safe.replace(ch, "_")
    return f"{safe}-{role}.png"


def _unique_dest_path(dest_dir: Path, basename: str) -> Path:
    dest = dest_dir / basename
    if not dest.exists():
        return dest
    stem = Path(basename).stem
    suffix = Path(basename).suffix
    n = 2
    while True:
        candidate = dest_dir / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def _stack_in_session_window(stack, session_start: datetime, session_end: datetime) -> bool:
    if not stack.date_obs:
        return False
    return session_start <= stack.date_obs <= session_end


def run_latest_regions_update(
    log: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Find the latest observing session, its session stacks and region views, then copy
    the oldest and newest PNG per region into PROCESSED_PATH/regions/ (flat folder),
    as RegionName-REF.png and RegionName-NEW.png for easy alphabetical browsing.
    """
    from lib.db import get_db_manager
    from lib.gui.library.daily_stacks_thread import group_files_by_session

    log = log or (lambda _m: None)
    db = get_db_manager()
    all_files = db.get_all_fits_files()
    raw_files = [f for f in all_files if not config.is_session_stack_fits_file(f) and f.date_obs]
    if not raw_files:
        return {"success": False, "error": "No light frames with DATE-OBS in the database."}

    sessions = group_files_by_session(raw_files, session_threshold_hours=12)
    if not sessions:
        return {"success": False, "error": "Could not determine observing sessions."}

    last_session = sessions[-1]
    session_start = min(f.date_obs for f in last_session)
    session_end = max(f.date_obs for f in last_session)
    session_date = session_start.date()

    stacks = [
        f
        for f in all_files
        if config.is_session_stack_fits_file(f)
        and _stack_in_session_window(f, session_start, session_end)
    ]
    if not stacks:
        return {
            "success": False,
            "error": (
                f"No session stacks found for the latest session "
                f"({session_date.isoformat()}, {session_start} – {session_end})."
            ),
        }

    stack_paths: Set[str] = set()
    for f in stacks:
        if f.path:
            try:
                stack_paths.add(str(Path(f.path).resolve()))
            except OSError:
                stack_paths.add(os.path.normpath(os.path.abspath(f.path)))

    regions = db.get_all_regions()
    if not regions:
        return {"success": False, "error": "No regions of interest defined."}

    dest_dir = Path(config.PROCESSED_PATH) / "regions"
    dest_dir.mkdir(parents=True, exist_ok=True)

    log(
        f"Latest session: {session_date.isoformat()} "
        f"({len(last_session)} light frame(s), {len(stacks)} stack(s))\n"
    )
    log(f"Output folder: {dest_dir}\n\n")

    copied = 0
    skipped_regions = 0
    errors: List[Tuple[str, str]] = []

    for region in regions:
        sky = SkyRegion(
            ra_min=region.ra_min,
            ra_max=region.ra_max,
            dec_min=region.dec_min,
            dec_max=region.dec_max,
        )
        session_stacks_for_region = [
            s for s in stacks if s.path and region_in_image_field(s.path, sky)
        ]
        if not session_stacks_for_region:
            continue

        region_stack_paths = set()
        for s in session_stacks_for_region:
            if not s.path:
                continue
            try:
                region_stack_paths.add(str(Path(s.path).resolve()))
            except OSError:
                region_stack_paths.add(os.path.normpath(os.path.abspath(s.path)))

        all_views = [
            v
            for v in db.get_region_views(region.id)
            if v.png_path and os.path.isfile(v.png_path)
        ]
        session_views = [
            v
            for v in all_views
            if not v.stack_fits_path
            or _norm_stack_path(v.stack_fits_path) in region_stack_paths
        ]
        if not session_views:
            skipped_regions += 1
            log(f"  {region.name} ({region.target}): no PNG views for this session — skipped\n")
            continue

        all_views.sort(key=_view_sort_key)
        session_views.sort(key=_view_sort_key)
        ref_view = all_views[0]
        new_view = session_views[-1]
        to_copy = [("REF", ref_view), ("NEW", new_view)]

        log(
            f"  {region.name} ({region.target}): "
            f"{len(session_views)} session view(s), {len(all_views)} total — copying REF + NEW\n"
        )
        for role, view in to_copy:
            src = Path(view.png_path)
            dest = _unique_dest_path(
                dest_dir, _region_export_filename(region.name, role)
            )
            try:
                shutil.copy2(src, dest)
                copied += 1
                log(f"    → {dest.name}\n")
            except OSError as e:
                errors.append((region.name, str(e)))
                log(f"    ✗ {role}: {e}\n")

    if copied == 0 and not errors:
        return {
            "success": False,
            "error": "No region view PNGs found for stacks from the latest session.",
            "session_date": session_date.isoformat(),
            "skipped_regions": skipped_regions,
        }

    return {
        "success": True,
        "session_date": session_date.isoformat(),
        "session_start": session_start,
        "session_end": session_end,
        "stacks": len(stacks),
        "copied": copied,
        "skipped_regions": skipped_regions,
        "dest_dir": str(dest_dir),
        "errors": errors,
    }


def _norm_stack_path(path: str) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return os.path.normpath(os.path.abspath(path))
