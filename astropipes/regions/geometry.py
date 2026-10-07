"""Region of interest geometry: sky rectangles, whether they fall in an image, pixel boxes, crops."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS


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
