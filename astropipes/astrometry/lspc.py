"""
Least-squares plate constants (LSPC): fit a plate model mapping pixel positions to sky
coordinates from catalog stars, and apply it to measured object positions.
"""

import logging
import os

import numpy as np
from astropy.io import fits
from scipy.optimize import least_squares

logger = logging.getLogger(__name__)

MODEL_PARAMETERS = {
    "linear": ['a', 'b', 'c', 'd', 'e', 'f'],
    "radial": ['a', 'b', 'c', 'd', 'e', 'f', 'k1', 'k2'],
    "quadratic": ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l'],
}


def _apply_model(params, x_norm, y_norm, model_type):
    """Apply the plate model to normalized coordinates. Returns (ra, dec) in degrees."""
    if model_type == "linear":
        # 6-parameter linear model: RA = a*x + b*y + c, Dec = d*x + e*y + f
        a, b, c, d, e, f = params
        ra_pred = a * x_norm + b * y_norm + c
        dec_pred = d * x_norm + e * y_norm + f

    elif model_type == "radial":
        # 8-parameter model with radial distortion
        # RA = a*x + b*y + c + k1*r²*x
        # Dec = d*x + e*y + f + k2*r²*y
        # where r² = x² + y²
        a, b, c, d, e, f, k1, k2 = params
        r_squared = x_norm**2 + y_norm**2
        ra_pred = a * x_norm + b * y_norm + c + k1 * r_squared * x_norm
        dec_pred = d * x_norm + e * y_norm + f + k2 * r_squared * y_norm

    elif model_type == "quadratic":
        # 12-parameter model with full quadratic terms
        # RA = a*x + b*y + c + d*x² + e*xy + f*y²
        # Dec = g*x + h*y + i + j*x² + k*xy + l*y²
        a, b, c, d, e, f, g, h, i, j, k, l = params
        ra_pred = (a * x_norm + b * y_norm + c +
                   d * x_norm**2 + e * x_norm * y_norm + f * y_norm**2)
        dec_pred = (g * x_norm + h * y_norm + i +
                    j * x_norm**2 + k * x_norm * y_norm + l * y_norm**2)

    return ra_pred, dec_pred


def plate_constants_to_sky(constants: dict, x, y):
    """
    Sky position (ra, dec in degrees) of pixel (x, y) using plate constants as returned by
    fit_plate_constants. Returns (None, None) if constants for the model are missing.
    """
    model_type = constants.get('model_type', 'linear')
    params = [constants.get(p) for p in MODEL_PARAMETERS.get(model_type, [])]
    if not params or any(v is None for v in params):
        return None, None
    norm_x = (x - constants.get('image_center_x', 0)) / constants.get('norm_scale', 1000)
    norm_y = (y - constants.get('image_center_y', 0)) / constants.get('norm_scale', 1000)
    return _apply_model(params, norm_x, norm_y, model_type)


def fit_plate_constants(gaia_detection_results, positions):
    """
    Least-squares plate constants (LSPC) from Gaia stars matched to detected sources, applied to
    the measured object positions.

    gaia_detection_results: (GaiaObject, DetectedSource, distance_arcsec) tuples; needs >= 6 stars.
    The model grows with the number of stars: 6-parameter linear, 8-parameter radial (>= 8 stars),
    12-parameter quadratic (>= 12 stars); it falls back to linear if the fit fails.
    positions: dicts with original_x / original_y / file_path; stacked images are skipped.

    Returns {plate_constants, rms_ra, rms_dec (degrees), comparison_stars, lspc_positions
    (positions with lspc_ra / lspc_dec added), model_type, num_parameters}.
    Raises ValueError when there are too few stars or the fit does not converge.
    """
    """Calculate LSPC using matched Gaia stars with higher-order distortion model."""

    # Extract comparison star data
    # gaia_detection_results is a list of (GaiaObject, DetectedSource, distance_arcsec) tuples
    comparison_stars = []
    for gaia_obj, detected_source, distance_arcsec in gaia_detection_results:
        # Validate that all required data is present and numeric
        if (gaia_obj.ra is None or gaia_obj.dec is None or 
            detected_source.x is None or detected_source.y is None):
            logger.warning(f"Skipping star with None coordinates: Gaia RA={gaia_obj.ra}, Dec={gaia_obj.dec}, X={detected_source.x}, Y={detected_source.y}")
            continue

        comparison_stars.append({
            'catalog_ra': gaia_obj.ra,      # Catalog RA (degrees)
            'catalog_dec': gaia_obj.dec,    # Catalog Dec (degrees)
            'measured_x': detected_source.x, # Measured pixel X
            'measured_y': detected_source.y, # Measured pixel Y
            'gaia_id': gaia_obj.source_id,
            'distance_arcsec': distance_arcsec  # Matching distance for weighting
        })

    # Check if we have enough valid comparison stars after filtering
    min_stars_needed = 6  # Need at least 6 stars for higher-order model
    if len(comparison_stars) < min_stars_needed:
        raise ValueError(f"Only {len(comparison_stars)} valid comparison stars found after filtering. At least {min_stars_needed} are required for higher-order LSPC calculation.")

    logger.debug(f"Using {len(comparison_stars)} stars for higher-order plate model")

    # Collect data for least squares
    catalog_ras = np.array([star['catalog_ra'] for star in comparison_stars])
    catalog_decs = np.array([star['catalog_dec'] for star in comparison_stars])
    measured_xs = np.array([star['measured_x'] for star in comparison_stars])
    measured_ys = np.array([star['measured_y'] for star in comparison_stars])
    distances = np.array([star['distance_arcsec'] for star in comparison_stars])

    # Calculate image center for normalized coordinates
    image_center_x = np.mean(measured_xs)
    image_center_y = np.mean(measured_ys)

    # Normalize coordinates to improve numerical stability
    # This helps with convergence and reduces correlation between parameters
    norm_scale = max(np.std(measured_xs), np.std(measured_ys))
    if norm_scale == 0:
        norm_scale = 1000  # fallback if all stars are at same position

    norm_xs = (measured_xs - image_center_x) / norm_scale
    norm_ys = (measured_ys - image_center_y) / norm_scale

    logger.debug(f"Image center: ({image_center_x:.1f}, {image_center_y:.1f})")
    logger.debug(f"Normalization scale: {norm_scale:.1f}")

    # Choose plate model based on number of available stars
    if len(comparison_stars) >= 12:
        # 12-parameter model with quadratic distortion
        model_type = "quadratic"
        logger.debug("Using 12-parameter quadratic distortion model")
    elif len(comparison_stars) >= 8:
        # 8-parameter model with radial distortion
        model_type = "radial"
        logger.debug("Using 8-parameter radial distortion model")
    else:
        # 6-parameter linear model (fallback)
        model_type = "linear"
        logger.debug("Using 6-parameter linear model (fallback)")

    # Define residuals function with robust weighting
    def residuals(params):
        ra_pred, dec_pred = _apply_model(params, norm_xs, norm_ys, model_type)

        ra_residuals = ra_pred - catalog_ras
        dec_residuals = dec_pred - catalog_decs

        # Apply weights based on matching distance (closer matches get higher weight)
        # Convert distances to weights: smaller distance = higher weight
        weights = 1.0 / (1.0 + distances**2)  # Avoid division by zero
        weights = weights / np.mean(weights)  # Normalize weights

        # Apply weights to residuals
        weighted_ra_residuals = ra_residuals * np.sqrt(weights)
        weighted_dec_residuals = dec_residuals * np.sqrt(weights)

        return np.concatenate([weighted_ra_residuals, weighted_dec_residuals])

    # Set initial parameter guesses based on model type
    if model_type == "linear":
        # 6 parameters: a, b, c, d, e, f
        initial_guess = [0.001, 0.0, np.mean(catalog_ras), 
                       0.0, -0.001, np.mean(catalog_decs)]
    elif model_type == "radial":
        # 8 parameters: a, b, c, d, e, f, k1, k2
        initial_guess = [0.001, 0.0, np.mean(catalog_ras), 
                       0.0, -0.001, np.mean(catalog_decs),
                       0.0, 0.0]  # k1, k2 distortion coefficients
    elif model_type == "quadratic":
        # 12 parameters: a, b, c, d, e, f, g, h, i, j, k, l
        initial_guess = [0.001, 0.0, np.mean(catalog_ras), 0.0, 0.0, 0.0,  # RA terms
                       0.0, -0.001, np.mean(catalog_decs), 0.0, 0.0, 0.0]  # Dec terms

    logger.debug(f"Initial parameter guess: {len(initial_guess)} parameters")

    # Solve least squares with robust fitting
    try:
        result = least_squares(residuals, initial_guess, method='lm', max_nfev=1000)

        if not result.success:
            logger.debug(f"First attempt failed: {result.message}")
            # Try with different method
            result = least_squares(residuals, initial_guess, method='trf', max_nfev=2000)

        if not result.success:
            raise ValueError(f"LSPC calculation failed to converge: {result.message}")

    except Exception as e:
        logger.debug(f"Higher-order model failed: {e}")
        # Fallback to linear model
        if model_type != "linear":
            logger.debug("Falling back to linear model")
            model_type = "linear"
            initial_guess = [0.001, 0.0, np.mean(catalog_ras), 
                           0.0, -0.001, np.mean(catalog_decs)]
            result = least_squares(residuals, initial_guess, method='lm')
            if not result.success:
                raise ValueError(f"Even linear LSPC calculation failed: {result.message}")
        else:
            raise e

    fitted_params = result.x
    logger.debug(f"Fitted {len(fitted_params)} parameters successfully")

    # Calculate RMS residuals (unweighted for display purposes)
    ra_pred_final, dec_pred_final = _apply_model(fitted_params, norm_xs, norm_ys, model_type)
    ra_residuals_final = ra_pred_final - catalog_ras
    dec_residuals_final = dec_pred_final - catalog_decs

    ra_rms = np.sqrt(np.mean(ra_residuals_final**2))
    dec_rms = np.sqrt(np.mean(dec_residuals_final**2))

    logger.debug(f"Final RMS residuals: RA = {ra_rms*3600:.2f} arcsec, Dec = {dec_rms*3600:.2f} arcsec")

    # Apply LSPC to the computed positions (only for individual images, not stacked images)
    lspc_positions = []
    individual_positions = []
    logger.debug(f"Applying LSPC transformation to {len(positions)} positions")

    # First pass: identify individual vs stacked images
    for i, pos in enumerate(positions):
        original_x = pos.get('original_x')
        original_y = pos.get('original_y')
        file_path = pos.get('file_path', '')

        logger.debug(f"Position {i}: original_x={original_x}, original_y={original_y}, file={os.path.basename(file_path)}")

        # Skip positions with invalid coordinates
        if original_x is None or original_y is None:
            logger.warning(f"Skipping position with None coordinates: {pos}")
            continue

        # Check if this is a stacked image
        is_stacked = False
        try:
            with fits.open(file_path) as hdul:
                header = hdul[0].header
                # Check for motion tracking flag or other stacking indicators
                if header.get('MOTION_TRACKED', False) or 'STACK' in file_path.upper():
                    is_stacked = True
                    logger.debug(f"Skipping stacked image: {os.path.basename(file_path)}")
        except Exception as e:
            logger.debug(f"Could not check header for {file_path}: {e}")
            # If we can't check the header, assume it's not stacked

        if is_stacked:
            logger.debug(f"Skipping stacked image position {i}")
            continue

        # This is an individual image, collect it for LSPC
        individual_positions.append(pos)

    # Second pass: apply LSPC transformation to individual images only
    logger.debug(f"Applying LSPC to {len(individual_positions)} individual images")
    for pos in individual_positions:
        original_x = pos.get('original_x')
        original_y = pos.get('original_y')

        # Normalize coordinates for transformation
        norm_x = (original_x - image_center_x) / norm_scale
        norm_y = (original_y - image_center_y) / norm_scale

        # Apply LSPC transformation using the fitted model
        lspc_ra, lspc_dec = _apply_model(fitted_params, np.array([norm_x]), np.array([norm_y]), model_type)
        lspc_ra = lspc_ra[0]  # Extract scalar from array
        lspc_dec = lspc_dec[0]

        logger.debug(f"LSPC RA={lspc_ra:.6f}, LSPC Dec={lspc_dec:.6f}")

        lspc_positions.append({
            **pos,
            'lspc_ra': lspc_ra,
            'lspc_dec': lspc_dec
        })

    # Store plate constants in a format compatible with the coordinate transformation
    if model_type == "linear":
        plate_constants = {
            'a': fitted_params[0], 'b': fitted_params[1], 'c': fitted_params[2],
            'd': fitted_params[3], 'e': fitted_params[4], 'f': fitted_params[5]
        }
    elif model_type == "radial":
        plate_constants = {
            'a': fitted_params[0], 'b': fitted_params[1], 'c': fitted_params[2],
            'd': fitted_params[3], 'e': fitted_params[4], 'f': fitted_params[5],
            'k1': fitted_params[6], 'k2': fitted_params[7]
        }
    elif model_type == "quadratic":
        plate_constants = {
            'a': fitted_params[0], 'b': fitted_params[1], 'c': fitted_params[2],
            'd': fitted_params[3], 'e': fitted_params[4], 'f': fitted_params[5],
            'g': fitted_params[6], 'h': fitted_params[7], 'i': fitted_params[8],
            'j': fitted_params[9], 'k': fitted_params[10], 'l': fitted_params[11]
        }

    # Add normalization parameters needed for coordinate transformation
    plate_constants.update({
        'model_type': model_type,
        'image_center_x': image_center_x,
        'image_center_y': image_center_y,
        'norm_scale': norm_scale
    })

    result = {
        'plate_constants': plate_constants,
        'rms_ra': ra_rms,
        'rms_dec': dec_rms,
        'comparison_stars': comparison_stars,
        'lspc_positions': lspc_positions,
        'model_type': model_type,
        'num_parameters': len(fitted_params)
    }

    logger.debug("LSPC calculation completed successfully")
    logger.debug(f"Result keys: {list(result.keys())}")
    logger.debug(f"Number of LSPC positions: {len(lspc_positions)}")

    return result
