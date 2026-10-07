"""
Region-of-interest workflows: PNG views of regions on session stacks (recorded in the library),
and export of the oldest / newest view per region for the latest session.
"""

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from astropipes.core import paths
from astropipes.db import get_db_manager
from astropipes.regions.geometry import SkyRegion, crop_region_from_fits, region_in_image_field
from astropipes.regions.views import png_filename_for_stack, region_view_stretch_limits, render_region_png
from astropipes.workflows.sessions import group_files_by_session, norm_path


def generate_views_for_region(
    region,
    stack_files: list,
    log=None,
    should_cancel=None,
    *,
    skip_existing: bool = True,
) -> dict:
    """
    Generate PNGs for all stack_files that contain region. Returns summary dict.
    stack_files: list of FitsFile-like objects with .path, .date_obs, .filter_name
    """
    log = log or (lambda m: None)
    should_cancel = should_cancel or (lambda: False)
    sky = SkyRegion(
        ra_min=region.ra_min,
        ra_max=region.ra_max,
        dec_min=region.dec_min,
        dec_max=region.dec_max,
    )
    out_dir = paths.region_views_path_for_region(region.target, region.name)
    out_dir.mkdir(parents=True, exist_ok=True)

    eligible = []
    for f in stack_files:
        if should_cancel():
            break
        path = getattr(f, "path", None) or f
        if not path or not os.path.isfile(path):
            continue
        if not region_in_image_field(path, sky):
            continue
        eligible.append(f)

    if not eligible:
        return {"generated": 0, "skipped": 0, "errors": []}

    crops_data = []
    for f in eligible:
        path = f.path
        crop = crop_region_from_fits(path, sky)
        if crop is not None:
            crops_data.append((f, crop))

    if not crops_data:
        return {"generated": 0, "skipped": 0, "errors": ["No valid crops"]}

    limits = region_view_stretch_limits([c for _, c in crops_data])
    db = get_db_manager()
    generated = 0
    skipped = 0
    errors = []

    for (f, _crop), (dmin, dmax, crop, out_lo, out_hi) in zip(crops_data, limits):
        if should_cancel():
            break
        png_name = png_filename_for_stack(
            region.name, f.date_obs, f.filter_name, f.path
        )
        png_path = str(out_dir / png_name)
        if skip_existing and os.path.isfile(png_path):
            skipped += 1
            db.add_or_update_region_view(
                region.id, f.path, png_path, f.date_obs, dmin, dmax
            )
            continue
        try:
            render_region_png(crop, dmin, dmax, png_path, out_low=out_lo, out_high=out_hi)
            db.add_or_update_region_view(
                region.id, f.path, png_path, f.date_obs, dmin, dmax
            )
            generated += 1
            log(f"  ✓ {png_name}\n")
        except Exception as e:
            errors.append((f.path, str(e)))
            log(f"  ✗ {os.path.basename(f.path)}: {e}\n")

    return {"generated": generated, "skipped": skipped, "errors": errors}


def generate_all_region_views(log, should_cancel) -> dict:
    """Generate PNG views of every region of interest on every session stack that contains it."""
    results = {"success": True, "regions": 0, "generated": 0, "skipped": 0, "errors": []}
    db = get_db_manager()
    regions = db.get_all_regions()
    if not regions:
        return {"success": False, "error": "No regions of interest defined."}

    stacks = [f for f in db.get_all_fits_files() if paths.is_session_stack_fits_file(f)]
    if not stacks:
        return {"success": False, "error": "No session stacks in the database."}

    log(f"Found {len(regions)} region(s), {len(stacks)} stack(s).\n\n")

    for region in regions:
        if should_cancel():
            results["cancelled"] = True
            break
        log(f"Region: {region.name} (target {region.target})\n")
        sub = generate_views_for_region(region, stacks, log=log, should_cancel=should_cancel)
        results["regions"] += 1
        results["generated"] += sub.get("generated", 0)
        results["skipped"] += sub.get("skipped", 0)
        for err in sub.get("errors", []):
            results["errors"].append((region.name, err))

    return results


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


def run_latest_regions_update(log=None, should_cancel=None) -> dict:
    """
    Find the latest observing session, its session stacks and region views, then copy
    the oldest and newest PNG per region into PROCESSED_PATH/regions/ (flat folder),
    as RegionName-REF.png and RegionName-NEW.png for easy alphabetical browsing.
    """
    log = log or (lambda _m: None)
    db = get_db_manager()
    all_files = db.get_all_fits_files()
    raw_files = [f for f in all_files if not paths.is_session_stack_fits_file(f) and f.date_obs]
    if not raw_files:
        return {"success": False, "error": "No light frames with DATE-OBS in the database."}

    sessions = group_files_by_session(raw_files)
    if not sessions:
        return {"success": False, "error": "Could not determine observing sessions."}

    last_session = sessions[-1]
    session_start = min(f.date_obs for f in last_session)
    session_end = max(f.date_obs for f in last_session)
    session_date = session_start.date()

    stacks = [
        f
        for f in all_files
        if paths.is_session_stack_fits_file(f)
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

    regions = db.get_all_regions()
    if not regions:
        return {"success": False, "error": "No regions of interest defined."}

    dest_dir = Path(paths.work_dir("regions"))
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

        region_stack_paths = {norm_path(s.path) for s in session_stacks_for_region if s.path}

        all_views = [
            v
            for v in db.get_region_views(region.id)
            if v.png_path and os.path.isfile(v.png_path)
        ]
        session_views = [
            v
            for v in all_views
            if not v.stack_fits_path
            or norm_path(v.stack_fits_path) in region_stack_paths
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

