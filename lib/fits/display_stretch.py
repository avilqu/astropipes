"""Headless histogram stretch for FITS crops (shared by viewer and region PNG export)."""

import numpy as np


def stretch_data(image_data: np.ndarray, stretch_mode: str = "linear") -> np.ndarray:
    if stretch_mode == "log":
        data = image_data.astype(float)
        mask = data > 0
        log_data = np.zeros_like(data)
        log_data[mask] = np.log10(data[mask])
        return log_data
    return image_data.astype(float) if image_data.dtype != np.float64 else image_data


def auto_display_minmax(
    image_data: np.ndarray,
    *,
    clipping: bool = False,
    sigma_clip: float = 3.0,
    stretch_mode: str = "linear",
    percentiles: tuple | None = None,
) -> tuple:
    data = stretch_data(image_data, stretch_mode)
    if clipping:
        finite_vals = data[np.isfinite(data)]
        if finite_vals.size > 0:
            mean = float(np.mean(finite_vals))
            std = float(np.std(finite_vals))
            return mean - sigma_clip * std, mean + sigma_clip * std
        return float(np.min(data)), float(np.max(data))
    finite_vals = data[np.isfinite(data)]
    if finite_vals.size > 0:
        if percentiles is not None:
            lo, hi = np.nanpercentile(finite_vals, percentiles)
            return float(lo), float(hi)
        histo = np.histogram(finite_vals, 60, None, True)
        return float(histo[1][0]), float(histo[1][-1])
    return float(np.min(data)), float(np.max(data))


def _border_pixel_values(image_data: np.ndarray, fraction: float = 0.15) -> np.ndarray:
    """Finite pixels along the crop edges (usually sky in small ROIs)."""
    h, w = image_data.shape
    if h < 3 or w < 3:
        return image_data[np.isfinite(image_data)]
    margin_y = max(1, int(h * fraction))
    margin_x = max(1, int(w * fraction))
    border_mask = np.zeros(image_data.shape, dtype=bool)
    border_mask[:margin_y, :] = True
    border_mask[-margin_y:, :] = True
    border_mask[:, :margin_x] = True
    border_mask[:, -margin_x:] = True
    vals = image_data[border_mask]
    return vals[np.isfinite(vals)]


def estimate_sky_background(
    image_data: np.ndarray,
    display_min: float | None = None,
    *,
    border_fraction: float = 0.15,
    fallback_percentile: float = 25.0,
) -> float:
    """
    Sky level in display (stretched) space: median of border pixels, else low percentile.
    display_min is ignored when border sampling is sufficient (legacy callers may pass it).
    """
    border = _border_pixel_values(image_data, border_fraction)
    if border.size >= 10:
        return float(np.median(border))
    finite = image_data[np.isfinite(image_data)]
    if finite.size == 0:
        return float(display_min) if display_min is not None else 0.0
    if display_min is not None:
        sky = finite[finite <= display_min]
        if sky.size >= 10:
            return float(np.median(sky))
    return float(np.nanpercentile(finite, fallback_percentile))


def estimate_highlight_level(
    image_data: np.ndarray,
    sky: float,
    *,
    high_percentile: float = 99.0,
    min_span: float | None = None,
) -> float:
    """Upper anchor for two-point stretch: high percentile with minimum span above sky."""
    finite = image_data[np.isfinite(image_data)]
    if finite.size == 0:
        return sky + 1.0
    high = float(np.nanpercentile(finite, high_percentile))
    if min_span is None:
        std = float(np.std(finite))
        min_span = max(std * 0.05, abs(sky) * 0.01, 1e-6)
    if high <= sky + min_span:
        high = sky + min_span
    return high


def apply_stretch_to_uint8(
    image_data: np.ndarray,
    display_min: float,
    display_max: float,
    *,
    out_low: float = 0.0,
    out_high: float = 255.0,
) -> np.ndarray:
    if np.isnan(image_data).any():
        finite_vals = image_data[np.isfinite(image_data)]
        fill_value = np.min(finite_vals) if finite_vals.size > 0 else 0
        image_data = np.nan_to_num(image_data, nan=fill_value)
    if display_max > display_min:
        clipped = np.clip(image_data, display_min, display_max)
        normalized = (clipped - display_min) / (display_max - display_min)
    else:
        normalized = image_data - image_data.min()
        if normalized.max() > 0:
            normalized = normalized / normalized.max()
    return (normalized * (out_high - out_low) + out_low).astype(np.uint8)


def two_point_stretch_limits(
    crops: list,
    *,
    sky_border_fraction: float = 0.15,
    high_percentile: float = 99.0,
    highlight_margin: float = 1.0,
    out_low: float = 25.0,
    out_high: float = 230.0,
) -> list:
    """
    Per-crop linear two-point limits: sky (border median) -> out_low, highlight -> out_high.

    highlight_margin > 1 widens the linear DN span above sky (softer; fewer clipped highlights).
    Each crop keeps its own contrast span; skies align in output gray level.
    Returns list of (display_min, display_max, raw_crop, out_low, out_high).
    """
    if not crops:
        return []
    margin = max(1.0, float(highlight_margin))
    out = []
    for crop in crops:
        data = crop.astype(np.float64) if crop.dtype != np.float64 else crop
        sky = estimate_sky_background(data, border_fraction=sky_border_fraction)
        high = estimate_highlight_level(data, sky, high_percentile=high_percentile)
        if margin > 1.0:
            high = sky + (high - sky) * margin
        out.append((sky, high, crop, out_low, out_high))
    return out


def consistent_stretch_limits(
    crops: list,
    *,
    clipping: bool = False,
    sigma_clip: float = 3.0,
    stretch_mode: str = "linear",
    percentiles: tuple | None = None,
    lock_display_max: bool = True,
    sky_border_fraction: float = 0.15,
) -> list:
    """
    Per-crop display limits with matched sky background and optional shared contrast.

    - Sky: median of border pixels in stretched space (stable with log + percentiles).
    - display_min shifted so batch skies align to the median sky level.
    - display_max: median across crops when lock_display_max (shared contrast).

    crops: list of 2D numpy arrays (already sliced).
    Returns list of (display_min, display_max, raw_crop) same length as crops.
    """
    if not crops:
        return []
    per = []
    backgrounds = []
    for crop in crops:
        stretched = stretch_data(crop, stretch_mode)
        dmin, dmax = auto_display_minmax(
            crop,
            clipping=clipping,
            sigma_clip=sigma_clip,
            stretch_mode=stretch_mode,
            percentiles=percentiles,
        )
        bg = estimate_sky_background(
            stretched,
            dmin,
            border_fraction=sky_border_fraction,
        )
        per.append((dmin, dmax, crop, bg))
        backgrounds.append(bg)
    ref_bg = float(np.median(backgrounds))
    shared_dmax = float(np.median([dmax for _, dmax, _, _ in per])) if lock_display_max else None
    out = []
    for dmin, dmax, crop, bg in per:
        dmin_adj = dmin + (bg - ref_bg)
        dmax_out = shared_dmax if shared_dmax is not None else dmax
        if dmax_out <= dmin_adj:
            dmax_out = max(dmax, dmin_adj + 1e-6)
        out.append((dmin_adj, dmax_out, crop))
    return out
