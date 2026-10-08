"""Region of interest PNG views: file naming and layout, rendering, stretch limits."""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from astropy.io import fits

from astropipes.core import paths
from astropipes.core.naming import normalize_object_name
from astropipes.processing.stretch import (
    apply_stretch_to_uint8,
    two_point_stretch_limits,
)

try:
    import imageio.v3 as iio
except ImportError:
    import imageio as iio

# Linear two-point stretch (per crop); margin widens DN span to soften highlights
_REGION_VIEW_OUT_LOW = 30.0
_REGION_VIEW_OUT_HIGH = 210.0
_REGION_VIEW_HIGH_PERCENTILE = 99.5
_REGION_VIEW_HIGHLIGHT_MARGIN = 1.4



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
    old_dir = paths.region_views_path_for_region(target, old_name)
    new_dir = paths.region_views_path_for_region(target, new_name)
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


def render_difference_png(diff: np.ndarray, noise: float, output_path: str, n_sigma: float = 5.0) -> None:
    """
    Difference image PNG with a stretch centred on zero and scaled to the noise: -n_sigma is
    black, 0 mid-grey, +n_sigma white, so a source of given S/N looks the same every night.
    Pixels without data (no overlap between REF and NEW) are mid-grey.
    """
    limit = max(float(n_sigma) * float(noise), 1e-12)
    data = np.nan_to_num(diff.astype(np.float64), nan=0.0)
    uint8 = apply_stretch_to_uint8(data, -limit, limit)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    iio.imwrite(output_path, uint8)


def region_view_stretch_limits(crops: list) -> list:
    """Shared two-point stretch limits for a set of region crops (see two_point_stretch_limits)."""
    return two_point_stretch_limits(
        crops,
        high_percentile=_REGION_VIEW_HIGH_PERCENTILE,
        highlight_margin=_REGION_VIEW_HIGHLIGHT_MARGIN,
        out_low=_REGION_VIEW_OUT_LOW,
        out_high=_REGION_VIEW_OUT_HIGH,
    )


def target_from_fits_path(fits_path: str) -> Optional[str]:
    try:
        obj = fits.getheader(fits_path, ext=0).get("OBJECT")
        if obj:
            return normalize_object_name(str(obj))
    except Exception:
        pass
    return None
