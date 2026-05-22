"""Region of interest geometry, field matching, cropping, and PNG export."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

import config
from lib.fits.display_stretch import (
    apply_stretch_to_uint8,
    two_point_stretch_limits,
)
from lib.db.scan import normalize_object_name

try:
    import imageio.v3 as iio
except ImportError:
    import imageio as iio

# Linear two-point stretch (per crop); margin widens DN span to soften highlights
_REGION_VIEW_OUT_LOW = 30.0
_REGION_VIEW_OUT_HIGH = 210.0
_REGION_VIEW_HIGH_PERCENTILE = 99.5
_REGION_VIEW_HIGHLIGHT_MARGIN = 1.4


@dataclass
class SkyRegion:
    ra_min: float
    ra_max: float
    dec_min: float
    dec_max: float

    @classmethod
    def from_pixel_rect(
        cls,
        wcs: WCS,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> "SkyRegion":
        xs = sorted([x0, x1])
        ys = sorted([y0, y1])
        corners_px = [
            (xs[0], ys[0]),
            (xs[1], ys[0]),
            (xs[1], ys[1]),
            (xs[0], ys[1]),
        ]
        ras, decs = [], []
        for px, py in corners_px:
            world = wcs.pixel_to_world(px, py)
            if hasattr(world, "ra"):
                ras.append(float(world.ra.deg))
                decs.append(float(world.dec.deg))
            else:
                ras.append(float(world[0]))
                decs.append(float(world[1]))
        ra_min, ra_max = min(ras), max(ras)
        dec_min, dec_max = min(decs), max(decs)
        if ra_max - ra_min > 180:
            # RA wrap: use mean-based span (rare for small ROIs)
            ra_c = (ra_min + ra_max) / 2
            ra_min, ra_max = ra_c - 0.05, ra_c + 0.05
        return cls(ra_min=ra_min, ra_max=ra_max, dec_min=dec_min, dec_max=dec_max)


def _header_wcs_and_shape(fits_path: str) -> Optional[Tuple[WCS, Tuple[int, int]]]:
    """Build WCS and (ny, nx) from the primary HDU header without reading image data."""
    try:
        header = fits.getheader(fits_path, ext=0)
        nx = int(header["NAXIS1"])
        ny = int(header["NAXIS2"])
        if nx < 1 or ny < 1:
            return None
        w = WCS(header)
        if not w.has_celestial:
            return None
        return w, (ny, nx)
    except Exception:
        return None


def wcs_from_fits_path(fits_path: str) -> Optional[WCS]:
    parsed = _header_wcs_and_shape(fits_path)
    return parsed[0] if parsed else None


def _pixel_corners_for_region(wcs: WCS, region: SkyRegion, shape: Tuple[int, int]) -> Optional[np.ndarray]:
    """Return Nx2 pixel coords for region corners, or None if entirely off-image."""
    ny, nx = shape
    ra_vals = [region.ra_min, region.ra_max, region.ra_max, region.ra_min]
    dec_vals = [region.dec_min, region.dec_min, region.dec_max, region.dec_max]
    try:
        pix = wcs.world_to_pixel_values(ra_vals, dec_vals)
    except Exception:
        return None
    px = np.asarray(pix[0], dtype=float)
    py = np.asarray(pix[1], dtype=float)
    return np.column_stack([px, py])


def pixel_bbox_for_region(
    wcs: WCS,
    region: SkyRegion,
    shape: Tuple[int, int],
) -> Optional[Tuple[float, float, float, float]]:
    """Return (x0, y0, x1, y1) image pixel bounds for a sky region, or None if off-image."""
    corners = _pixel_corners_for_region(wcs, region, shape)
    if corners is None:
        return None
    xs, ys = corners[:, 0], corners[:, 1]
    if np.any(np.isnan(xs)) or np.any(np.isnan(ys)):
        return None
    return float(np.min(xs)), float(np.min(ys)), float(np.max(xs)), float(np.max(ys))


def region_in_image_field(
    fits_path: str,
    region: SkyRegion,
    *,
    margin_px: float = 2.0,
    min_area_px: float = 100.0,
) -> bool:
    parsed = _header_wcs_and_shape(fits_path)
    if parsed is None:
        return False
    wcs, shape = parsed
    corners = _pixel_corners_for_region(wcs, region, shape)
    if corners is None:
        return False
    xs, ys = corners[:, 0], corners[:, 1]
    if np.any(np.isnan(xs)) or np.any(np.isnan(ys)):
        return False
    x0, x1 = float(np.min(xs)), float(np.max(xs))
    y0, y1 = float(np.min(ys)), float(np.max(ys))
    ny, nx = shape
    if x1 < margin_px or y1 < margin_px or x0 > nx - margin_px or y0 > ny - margin_px:
        return False
    ix0 = max(0, int(np.floor(x0)))
    iy0 = max(0, int(np.floor(y0)))
    ix1 = min(nx, int(np.ceil(x1)))
    iy1 = min(ny, int(np.ceil(y1)))
    if (ix1 - ix0) * (iy1 - iy0) < min_area_px:
        return False
    return True


def crop_region_from_fits(fits_path: str, region: SkyRegion) -> Optional[np.ndarray]:
    parsed = _header_wcs_and_shape(fits_path)
    if parsed is None:
        return None
    wcs, shape = parsed
    corners = _pixel_corners_for_region(wcs, region, shape)
    if corners is None:
        return None
    xs, ys = corners[:, 0], corners[:, 1]
    if np.any(np.isnan(xs)) or np.any(np.isnan(ys)):
        return None
    x0 = max(0, int(np.floor(np.min(xs))))
    x1 = min(shape[1], int(np.ceil(np.max(xs))))
    y0 = max(0, int(np.floor(np.min(ys))))
    y1 = min(shape[0], int(np.ceil(np.max(ys))))
    if x1 <= x0 or y1 <= y0:
        return None
    try:
        with fits.open(fits_path, memmap=True) as hdul:
            data = hdul[0].data
            if data is None or data.ndim != 2:
                return None
            return np.asarray(data[y0:y1, x0:x1], dtype=np.float64)
    except Exception:
        return None


def relocate_region_views_directory(
    target: str,
    old_name: str,
    new_name: str,
    views: list,
) -> None:
    """
    Move STACKS_PATH/<target>/views/<old>/ to .../<new>/ and update view png_path values.
    Raises ValueError if the destination directory already exists.
    """
    old_dir = config.region_views_path_for_region(target, old_name)
    new_dir = config.region_views_path_for_region(target, new_name)
    if old_dir.resolve() == new_dir.resolve():
        return
    if new_dir.exists():
        raise ValueError(
            f"Cannot rename region: views folder already exists:\n{new_dir}"
        )
    if old_dir.exists():
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_dir), str(new_dir))
    else:
        new_dir.mkdir(parents=True, exist_ok=True)
    for view in views:
        png = getattr(view, "png_path", None)
        if not png:
            continue
        view.png_path = str(new_dir / Path(png).name)


def png_filename_for_stack(
    region_name: str,
    date_obs: datetime,
    filter_name: str,
    stack_fits_path: str = "",
) -> str:
    safe_region = re.sub(r'[^\w\-.]+', '_', str(region_name))
    filt = (filter_name or "unknown").replace(" ", "_")
    if date_obs:
        ts = date_obs.strftime("%Y%m%d_%H%M%S")
    else:
        ts = "unknown"
    stem = Path(stack_fits_path).stem if stack_fits_path else ""
    if stem:
        return f"{safe_region}_{ts}_{filt}_{stem}.png"
    return f"{safe_region}_{ts}_{filt}.png"


def render_region_png(
    crop: np.ndarray,
    display_min: float,
    display_max: float,
    output_path: str,
    *,
    out_low: float = _REGION_VIEW_OUT_LOW,
    out_high: float = _REGION_VIEW_OUT_HIGH,
) -> None:
    data = crop.astype(np.float64) if crop.dtype != np.float64 else crop
    uint8 = apply_stretch_to_uint8(
        data, display_min, display_max, out_low=out_low, out_high=out_high
    )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    iio.imwrite(output_path, uint8)


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
    from lib.db import get_db_manager

    log = log or (lambda m: None)
    should_cancel = should_cancel or (lambda: False)
    sky = SkyRegion(
        ra_min=region.ra_min,
        ra_max=region.ra_max,
        dec_min=region.dec_min,
        dec_max=region.dec_max,
    )
    out_dir = config.region_views_path_for_region(region.target, region.name)
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

    limits = two_point_stretch_limits(
        [c for _, c in crops_data],
        high_percentile=_REGION_VIEW_HIGH_PERCENTILE,
        highlight_margin=_REGION_VIEW_HIGHLIGHT_MARGIN,
        out_low=_REGION_VIEW_OUT_LOW,
        out_high=_REGION_VIEW_OUT_HIGH,
    )
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


def target_from_fits_path(fits_path: str) -> Optional[str]:
    try:
        obj = fits.getheader(fits_path, ext=0).get("OBJECT")
        if obj:
            return normalize_object_name(str(obj))
    except Exception:
        pass
    return None
