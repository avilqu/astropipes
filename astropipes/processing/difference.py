"""
Difference imaging of a region of interest between two session stacks (REF and NEW).

NEW is reprojected onto REF's pixel grid, both are background-subtracted, the sharper one is
blurred with a Gaussian kernel to match the other's seeing, NEW is scaled to REF's flux using
field stars, and REF is subtracted. Stars are measured on a padded crop around the region, and
the result is trimmed back to the same pixel box as the region's REF view.
"""

from __future__ import annotations

import os
import warnings
from typing import Optional

import numpy as np
from astropy.io import fits
from astropy.stats import SigmaClip, sigma_clipped_stats
from astropy.wcs import WCS, FITSFixedWarning
from photutils.aperture import CircularAperture, aperture_photometry
from photutils.background import Background2D, MedianBackground
from photutils.centroids import centroid_com, centroid_sources
from photutils.psf import fit_fwhm
from photutils.segmentation import SourceCatalog, detect_sources
from reproject import reproject_interp
from scipy.ndimage import gaussian_filter, shift as nd_shift
from scipy.signal import fftconvolve

from astropipes.regions.geometry import SkyRegion, pixel_bbox_for_region

FWHM_TO_SIGMA = 1.0 / (2.0 * np.sqrt(2.0 * np.log(2.0)))

MIN_PAD_PX = 64            # Minimum padding around the region crop, for star measurements
PAD_FRACTION = 0.5         # Padding as a fraction of the region's larger side
STAR_DETECT_SIGMA = 10.0   # Detection threshold for matching stars
MIN_STARS = 3              # Fewer matched stars than this: no difference image
FEW_STARS = 6              # Fewer than this: flagged
MAX_STARS = 40             # Brightest unsaturated stars kept for measurements
SEEING_RATIO_FLAG = 2.0    # Flag when one image's FWHM is this many times the other's
FLUX_SCALE_FLAG = 2.5      # Flag when NEW needs this much scaling (clouds, ~1 mag lost)


def _header_wcs_shape(path: str):
    header = fits.getheader(path, ext=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        wcs = WCS(header).celestial
    if not wcs.has_celestial:
        raise ValueError(f"No celestial WCS in {path}")
    return header, wcs, (int(header["NAXIS2"]), int(header["NAXIS1"]))


def _int_box(x0, y0, x1, y1, shape):
    """Integer pixel box, rounded and clipped the same way as regions.geometry.crop_region_from_fits."""
    ny, nx = shape
    return (
        max(0, int(np.floor(x0))),
        max(0, int(np.floor(y0))),
        min(nx, int(np.ceil(x1))),
        min(ny, int(np.ceil(y1))),
    )


def _read_box(path: str, box) -> np.ndarray:
    x0, y0, x1, y1 = box
    with fits.open(path, memmap=True) as hdul:
        data = hdul[0].data
        if data is None or data.ndim != 2:
            raise ValueError(f"No 2D image data in {path}")
        return np.asarray(data[y0:y1, x0:x1], dtype=np.float64)


def _subtract_background(data: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Returns (data minus a smooth background, data minus the median sky level, background rms).
    The first is for star measurements; the second keeps all the light of large galaxies, which
    a local background estimate partly absorbs (differently on sharp and blurred images).
    """
    invalid = ~np.isfinite(data)
    ny, nx = data.shape
    box = int(max(16, min(64, ny // 4, nx // 4)))
    sigma_clip = SigmaClip(sigma=3.0, maxiters=10)
    # First pass to find sources, second pass with them masked
    bkg = Background2D(
        data, box, coverage_mask=invalid, sigma_clip=sigma_clip,
        bkg_estimator=MedianBackground(), exclude_percentile=50.0,
    )
    sub = data - bkg.background
    rms = float(np.nanmedian(bkg.background_rms))
    segm = detect_sources(np.nan_to_num(sub), 2.0 * rms, n_pixels=10, mask=invalid)
    mask = segm.make_source_mask(size=11) if segm is not None else None
    bkg = Background2D(
        data, box, mask=mask, coverage_mask=invalid, sigma_clip=sigma_clip,
        bkg_estimator=MedianBackground(), exclude_percentile=50.0,
    )
    sub = data - bkg.background
    sub[invalid] = np.nan
    flat = data - float(np.median(bkg.background))
    flat[invalid] = np.nan
    return sub, flat, float(np.nanmedian(bkg.background_rms))


def _select_stars(data: np.ndarray, rms: float, valid: np.ndarray) -> np.ndarray:
    """Positions (N x 2, x/y) of bright, compact, unsaturated, isolated stars."""
    filled = np.where(valid, data, 0.0)
    segm = detect_sources(filled, STAR_DETECT_SIGMA * rms, n_pixels=5, mask=~valid)
    if segm is None:
        return np.empty((0, 2))
    cat = SourceCatalog(filled, segm)
    ny, nx = data.shape
    x = np.asarray(cat.x_centroid, dtype=float)
    y = np.asarray(cat.y_centroid, dtype=float)
    peak = np.asarray(cat.max_value, dtype=float)
    keep = (
        np.isfinite(x) & np.isfinite(y)
        & (np.asarray(cat.elongation, dtype=float) < 1.4)
        & (np.asarray(cat.area.value, dtype=float) < 400)   # excludes galaxies
        & (x > 12) & (x < nx - 13) & (y > 12) & (y < ny - 13)
    )
    if not np.any(keep):
        return np.empty((0, 2))
    # Drop the brightest peaks, which may be saturated
    peak_limit = np.nanpercentile(peak[keep], 90) if keep.sum() >= 10 else np.inf
    keep &= peak < peak_limit
    order = np.argsort(-peak[keep])[:MAX_STARS]
    return np.column_stack([x[keep][order], y[keep][order]])


def _fwhm_at(data: np.ndarray, xy: np.ndarray, guess: float = 3.0) -> np.ndarray:
    try:
        values = np.asarray(fit_fwhm(np.nan_to_num(data), xypos=xy, fwhm=guess, fit_shape=11), dtype=float)
    except Exception:
        return np.full(len(xy), np.nan)
    values[(values < 0.8) | (values > 30)] = np.nan
    return values


def _aperture_flux(data: np.ndarray, xy: np.ndarray, radius: float) -> np.ndarray:
    table = aperture_photometry(np.nan_to_num(data), CircularAperture(xy, r=radius))
    return np.asarray(table["aperture_sum"], dtype=float)


def difference_region(ref_path: str, new_path: str, sky: SkyRegion) -> dict:
    """
    REF−NEW difference image of a sky region, on the REF view's pixel box.

    Returns {'success': True, 'diff': float32 array (NEW − REF, in REF units), 'wcs': WCS of the
    diff, 'fwhm_ref', 'fwhm_new', 'kernel_sigma', 'blurred' ('REF' / 'NEW' / ''), 'flux_scale',
    'noise', 'n_stars', 'flags': [...]} or {'success': False, 'error': ...}.
    """
    try:
        _, ref_wcs, ref_shape = _header_wcs_shape(ref_path)
        _, new_wcs, new_shape = _header_wcs_shape(new_path)
    except Exception as e:
        return {"success": False, "error": f"Cannot read WCS: {e}"}

    bbox = pixel_bbox_for_region(ref_wcs, sky, ref_shape)
    if bbox is None:
        return {"success": False, "error": "Region is outside the REF stack."}
    inner = _int_box(*bbox, ref_shape)
    width, height = inner[2] - inner[0], inner[3] - inner[1]
    if width < 8 or height < 8:
        return {"success": False, "error": "Region crop is too small."}
    pad = max(MIN_PAD_PX, int(PAD_FRACTION * max(width, height)))
    outer = _int_box(inner[0] - pad, inner[1] - pad, inner[2] + pad, inner[3] + pad, ref_shape)
    out_shape = (outer[3] - outer[1], outer[2] - outer[0])
    ref_wcs_outer = ref_wcs.slice((slice(outer[1], outer[3]), slice(outer[0], outer[2])))

    # Part of NEW covering the padded REF box, with a margin for interpolation
    corners_x = [outer[0], outer[2], outer[2], outer[0]]
    corners_y = [outer[1], outer[1], outer[3], outer[3]]
    try:
        world = ref_wcs.pixel_to_world_values(corners_x, corners_y)
        nx_px, ny_px = new_wcs.world_to_pixel_values(*world)
    except Exception as e:
        return {"success": False, "error": f"WCS transform failed: {e}"}
    new_box = _int_box(
        np.min(nx_px) - 8, np.min(ny_px) - 8, np.max(nx_px) + 8, np.max(ny_px) + 8, new_shape
    )
    if new_box[2] - new_box[0] < 8 or new_box[3] - new_box[1] < 8:
        return {"success": False, "error": "Region is outside the NEW stack."}

    try:
        ref = _read_box(ref_path, outer)
        new_raw = _read_box(new_path, new_box)
    except Exception as e:
        return {"success": False, "error": str(e)}
    new_wcs_box = new_wcs.slice((slice(new_box[1], new_box[3]), slice(new_box[0], new_box[2])))
    new, footprint = reproject_interp((new_raw, new_wcs_box), ref_wcs_outer, shape_out=out_shape)
    new[footprint < 0.99] = np.nan
    ref[~np.isfinite(ref)] = np.nan

    try:
        ref, ref_flat, ref_rms = _subtract_background(ref)
        new, new_flat, _ = _subtract_background(new)
    except Exception as e:
        return {"success": False, "error": f"Background estimation failed: {e}"}
    valid = np.isfinite(ref) & np.isfinite(new)

    # Stars found on REF, measured at the same positions on both images
    stars = _select_stars(ref, ref_rms, valid)
    if len(stars) < MIN_STARS:
        return {"success": False, "error": f"Too few stars to match the images ({len(stars)})."}
    fwhm_ref_all = _fwhm_at(ref, stars)
    fwhm_new_all = _fwhm_at(new, stars)
    good = np.isfinite(fwhm_ref_all) & np.isfinite(fwhm_new_all)
    if good.sum() < MIN_STARS:
        return {"success": False, "error": f"Too few measurable stars ({int(good.sum())})."}
    stars = stars[good]
    fwhm_ref = float(np.median(fwhm_ref_all[good]))
    fwhm_new = float(np.median(fwhm_new_all[good]))

    # Residual offset left by the WCS reprojection, from star centroids
    shift_x, shift_y = _star_offset(ref, new, stars, max(fwhm_ref, fwhm_new))
    if abs(shift_x) > 0.05 or abs(shift_y) > 0.05:
        new = _shift(new, -shift_x, -shift_y)
        new_flat = _shift(new_flat, -shift_x, -shift_y)
        valid &= np.isfinite(new)

    # Blur the sharper image to the other's seeing: a kernel fitted on the stars (copes with
    # defocus, coma, trailing), or a Gaussian if the fit is not possible
    kernel_sigma = np.sqrt(abs(fwhm_new**2 - fwhm_ref**2)) * FWHM_TO_SIGMA
    blurred = ""
    kernel_type = "NONE"
    if kernel_sigma >= 0.3:
        blurred = "REF" if fwhm_ref < fwhm_new else "NEW"
        sharp, blurry = (ref, new) if blurred == "REF" else (new, ref)
        kernel = _fit_kernel(sharp, blurry, stars, kernel_sigma, max(fwhm_ref, fwhm_new))
        if kernel is not None:
            match = lambda d: _convolve(d, kernel)
            kernel_type = "EMPIRICAL"
        else:
            match = lambda d: _blur(d, kernel_sigma)
            kernel_type = "GAUSSIAN"
        if blurred == "REF":
            ref, ref_flat = match(ref), match(ref_flat)
        else:
            new, new_flat = match(new), match(new_flat)
        valid &= np.isfinite(ref) & np.isfinite(new)
    else:
        kernel_sigma = 0.0

    # Flux scale from star photometry, in an aperture of 1.5 × the matched FWHM
    radius = 1.5 * max(fwhm_ref, fwhm_new)
    flux_ref = _aperture_flux(ref, stars, radius)
    flux_new = _aperture_flux(new, stars, radius)
    ok = (flux_ref > 0) & (flux_new > 0)
    if ok.sum() < MIN_STARS:
        return {"success": False, "error": "Too few stars with positive flux in both images."}
    _, flux_scale, _ = sigma_clipped_stats(flux_ref[ok] / flux_new[ok], sigma=2.5)
    flux_scale = float(flux_scale)

    # Galaxies cancel in the difference, so its remaining smooth background (sky gradients that
    # differ between the nights) can be removed without touching them
    diff_outer = new_flat * flux_scale - ref_flat
    diff_outer[~valid] = np.nan
    try:
        diff_outer, _, _ = _subtract_background(diff_outer)
    except Exception:
        diff_outer -= np.nanmedian(diff_outer)
    x0, y0 = inner[0] - outer[0], inner[1] - outer[1]
    diff = diff_outer[y0:y0 + height, x0:x0 + width].astype(np.float32)
    finite = diff_outer[np.isfinite(diff_outer)]
    if finite.size < 100:
        return {"success": False, "error": "REF and NEW barely overlap on this region."}
    _, _, noise = sigma_clipped_stats(finite, sigma=3.0)

    flags = []
    if max(fwhm_ref, fwhm_new) > SEEING_RATIO_FLAG * min(fwhm_ref, fwhm_new):
        flags.append("SEEING")
    if flux_scale > FLUX_SCALE_FLAG or flux_scale < 1.0 / FLUX_SCALE_FLAG:
        flags.append("TRANSP")
    if int(ok.sum()) < FEW_STARS:
        flags.append("FEWSTARS")

    return {
        "success": True,
        "diff": diff,
        "wcs": ref_wcs.slice((slice(inner[1], inner[3]), slice(inner[0], inner[2]))),
        "fwhm_ref": fwhm_ref,
        "fwhm_new": fwhm_new,
        "kernel_sigma": float(kernel_sigma),
        "blurred": blurred,
        "kernel_type": kernel_type,
        "flux_scale": flux_scale,
        "noise": float(noise),
        "n_stars": int(ok.sum()),
        "shift": (shift_x, shift_y),
        "flags": flags,
    }


def _star_offset(ref: np.ndarray, new: np.ndarray, stars: np.ndarray, fwhm: float) -> tuple[float, float]:
    """Median (dx, dy) of NEW star centroids relative to REF, in pixels (0, 0 if unreliable)."""
    box = int(2 * np.ceil(1.5 * fwhm) + 1)
    try:
        rx, ry = centroid_sources(np.nan_to_num(ref), stars[:, 0], stars[:, 1], box_size=box, centroid_func=centroid_com)
        nx, ny = centroid_sources(np.nan_to_num(new), stars[:, 0], stars[:, 1], box_size=box, centroid_func=centroid_com)
    except Exception:
        return 0.0, 0.0
    dx, dy = np.asarray(nx) - np.asarray(rx), np.asarray(ny) - np.asarray(ry)
    ok = np.isfinite(dx) & np.isfinite(dy) & (np.hypot(dx, dy) < 3.0)
    if ok.sum() < MIN_STARS:
        return 0.0, 0.0
    _, sx, _ = sigma_clipped_stats(dx[ok], sigma=2.5)
    _, sy, _ = sigma_clipped_stats(dy[ok], sigma=2.5)
    return float(sx), float(sy)


def _shift(data: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Sub-pixel shift (cubic spline); pixels that pull in missing data become NaN."""
    valid = np.isfinite(data)
    out = nd_shift(np.where(valid, data, 0.0), (dy, dx), order=3, mode="constant", cval=0.0)
    coverage = nd_shift(valid.astype(np.float64), (dy, dx), order=1, mode="constant", cval=0.0)
    out[coverage < 0.99] = np.nan
    return out


def _fit_kernel(sharp, blurry, stars, sigma, fwhm) -> Optional[np.ndarray]:
    """
    Pixel kernel K (unit sum) such that sharp convolved with K matches blurry, fitted by least
    squares on star stamps plus a constant background term (Bramich 2008). None if unreliable.
    """
    half = int(np.clip(np.ceil(3.0 * sigma), 2, 12))
    stamp = int(np.ceil(2.0 * fwhm)) + 2
    size = 2 * half + 1
    rows, targets = [], []
    ny, nx = sharp.shape
    for x, y in np.round(stars).astype(int):
        y0, y1 = y - stamp - half, y + stamp + half + 1
        x0, x1 = x - stamp - half, x + stamp + half + 1
        if y0 < 0 or x0 < 0 or y1 > ny or x1 > nx:
            continue
        s = sharp[y0:y1, x0:x1]
        b = blurry[y - stamp:y + stamp + 1, x - stamp:x + stamp + 1]
        if not (np.all(np.isfinite(s)) and np.all(np.isfinite(b))):
            continue
        # Column (v, u) holds sharp shifted by (v - half, u - half): (K*R)(y, x) = sum K[v, u] R(y - v + half, x - u + half)
        n = 2 * stamp + 1
        cols = [s[size - 1 - v:size - 1 - v + n, size - 1 - u:size - 1 - u + n].ravel()
                for v in range(size) for u in range(size)]
        rows.append(np.column_stack(cols + [np.ones(n * n)]))
        targets.append(b.ravel())
    n_unknowns = size * size + 1
    if len(rows) < MIN_STARS or sum(len(t) for t in targets) < 4 * n_unknowns:
        return None
    a = np.vstack(rows)
    t = np.concatenate(targets)
    ata = a.T @ a
    ridge = 1e-4 * np.trace(ata) / n_unknowns
    try:
        coef = np.linalg.solve(ata + ridge * np.eye(n_unknowns), a.T @ t)
    except np.linalg.LinAlgError:
        return None
    kernel = coef[:-1].reshape(size, size)
    total = kernel.sum()
    if not np.isfinite(total) or total <= 0:
        return None
    return kernel / total


def _convolve(data: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Convolve with kernel; pixels within the kernel's reach of missing data become NaN."""
    valid = np.isfinite(data)
    out = fftconvolve(np.where(valid, data, 0.0), kernel, mode="same")
    reach = fftconvolve((~valid).astype(np.float64), np.ones_like(kernel), mode="same")
    out[reach > 0.5] = np.nan
    return out


def _blur(data: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur that ignores NaN pixels (normalized convolution)."""
    valid = np.isfinite(data)
    num = gaussian_filter(np.where(valid, data, 0.0), sigma)
    den = gaussian_filter(valid.astype(np.float64), sigma)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / den
    out[~valid] = np.nan
    return out


def write_difference_fits(
    result: dict,
    output_path: str,
    ref_path: str,
    new_path: str,
    filter_name: Optional[str] = None,
) -> None:
    """Write a difference_region() result as a float32 FITS file with REF's WCS and match metrics."""
    header = result["wcs"].to_header(relax=True)
    header["REFFILE"] = (os.path.basename(ref_path), "Reference session stack")
    header["NEWFILE"] = (os.path.basename(new_path), "New session stack")
    if filter_name:
        header["FILTER"] = (str(filter_name), "Filter of REF and NEW")
    header["FWHMREF"] = (round(result["fwhm_ref"], 3), "[px] REF star FWHM")
    header["FWHMNEW"] = (round(result["fwhm_new"], 3), "[px] NEW star FWHM")
    header["KERNSIG"] = (round(result["kernel_sigma"], 3), "[px] Gaussian blur sigma")
    header["KERNEL"] = (result["kernel_type"], "Seeing-matching kernel")
    header["BLURRED"] = (result["blurred"] or "NONE", "Image blurred to match seeing")
    header["FLXSCALE"] = (round(result["flux_scale"], 5), "Factor applied to NEW")
    header["DIFFRMS"] = (float(f"{result['noise']:.6g}"), "Robust noise of the difference")
    header["NSTARS"] = (result["n_stars"], "Stars used for matching")
    header["DIFFFLAG"] = (",".join(result["flags"]) or "OK", "Quality flags")
    header["COMMENT"] = "Difference image NEW*FLXSCALE - REF, astropipes"
    fits.PrimaryHDU(result["diff"], header=header).writeto(output_path, overwrite=True)
