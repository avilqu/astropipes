"""
Source detection and analysis module for astro-pipelines.
Provides functions for detecting and analyzing astronomical sources in images.

IMPORTANT: HFR vs HFD Distinction
- HFR (Half Flux Radius): The radius containing half the total flux of a source
- HFD (Half Flux Diameter): The diameter containing half the total flux = 2 × HFR

The HFR values calculated here are RADIUS values, not diameter values.
"""

import numpy as np
from astropy import units as u
from astropy.wcs import WCS
from astropy.stats import sigma_clipped_stats
from photutils.segmentation import detect_sources, detect_threshold, SourceCatalog
from typing import List, Dict, Optional, Tuple
import logging
import time

from astropipes.core.memory import get_memory_usage

logger = logging.getLogger(__name__)


def get_image_scale_from_wcs(wcs):
    """
    Extract image scale (arcsec/pixel) from WCS information.
    
    Parameters:
    -----------
    wcs : WCS object
        World Coordinate System object
        
    Returns:
    --------
    float : Image scale in arcseconds per pixel, or None if not available
    """
    if wcs is None:
        return None
    
    try:
        # Check if WCS has a header with SCALE property
        if hasattr(wcs, 'header') and wcs.header is not None:
            header = wcs.header
            if 'SCALE' in header:
                scale_value = header['SCALE']
                logger.info(f"Found SCALE header: {scale_value} arcsec/pixel")
                return float(scale_value)
        
        # Fallback: try CDELT if available (degrees per pixel)
        if hasattr(wcs, 'cdelt') and wcs.cdelt is not None:
            try:
                cdelt_deg = wcs.cdelt[0]
                return abs(cdelt_deg) * 3600.0  # Convert degrees to arcseconds
            except (ValueError, TypeError, IndexError):
                pass
                
    except Exception as e:
        logger.debug(f"Could not extract image scale from WCS: {e}")
    
    return None


def calculate_source_hfr_fwhm(image, segment_map, source_id, background=0.0):
    """
    Calculate HFR and FWHM for a specific source using more accurate methods.
    
    Parameters:
    -----------
    image : np.ndarray
        2D image array
    segment_map : np.ndarray
        Segmentation map from photutils
    source_id : int
        Source ID in the segmentation map
    background : float
        Background level to subtract
        
    Returns:
    --------
    tuple : (hfr, fwhm) in pixels
    """
    try:
        # Create mask for this source
        source_mask = (segment_map == source_id)
        
        if not np.any(source_mask):
            return 0.0, 0.0
        
        # Get source region
        y_coords, x_coords = np.where(source_mask)
        y_min, y_max = y_coords.min(), y_coords.max()
        x_min, x_max = x_coords.min(), x_coords.max()
        
        # Extract source region
        source_region = image[y_min:y_max+1, x_min:x_max+1].copy()
        source_mask_region = source_mask[y_min:y_max+1, x_min:x_max+1]
        
        # Subtract background
        source_region = source_region - background
        
        # Calculate HFR (half flux radius)
        total_flux = np.sum(source_region * source_mask_region)
        half_flux = total_flux / 2.0
        
        if half_flux <= 0:
            return 0.0, 0.0
        
        # Find radius containing half the flux
        center_y, center_x = (y_max + y_min) / 2, (x_max + x_min) / 2
        
        # Calculate radial profile
        y_grid, x_grid = np.ogrid[y_min:y_max+1, x_min:x_max+1]
        r = np.sqrt((x_grid - center_x)**2 + (y_grid - center_y)**2)
        
        # Sort by radius and accumulate flux
        r_flat = r.flatten()
        flux_flat = source_region.flatten()
        mask_flat = source_mask_region.flatten()
        
        # Only consider pixels in the source
        valid_indices = mask_flat > 0
        r_valid = r_flat[valid_indices]
        flux_valid = flux_flat[valid_indices]
        
        if len(r_valid) == 0:
            return 0.0, 0.0
        
        # Sort by radius
        sort_indices = np.argsort(r_valid)
        r_sorted = r_valid[sort_indices]
        flux_sorted = flux_valid[sort_indices]
        
        # Find cumulative flux
        cumulative_flux = np.cumsum(flux_sorted)
        
        # Find radius at half flux
        half_flux_index = np.searchsorted(cumulative_flux, half_flux)
        if half_flux_index < len(r_sorted):
            hfr = r_sorted[half_flux_index]
        else:
            hfr = r_sorted[-1]
        
        # Calculate FWHM (simplified approach)
        # Use the semimajor axis from photutils if available, otherwise estimate
        fwhm = 2.355 * np.sqrt(np.var(r_valid))  # Approximate FWHM
        
        return hfr, fwhm
        
    except Exception as e:
        logger.warning(f"Error calculating HFR/FWHM for source {source_id}: {e}")
        return 0.0, 0.0


class SourceDetectionError(Exception):
    """Exception raised when source detection fails."""
    pass


class DetectedSource:
    """Class to represent a detected source in an astronomical image."""
    
    def __init__(self, id: int, x: float, y: float, ra: Optional[float] = None, 
                 dec: Optional[float] = None, flux: float = 0.0, 
                 area: float = 0.0, eccentricity: float = 0.0, 
                 semimajor_axis: float = 0.0, semiminor_axis: float = 0.0,
                 orientation: float = 0.0, peak_value: float = 0.0,
                 background: float = 0.0, snr: float = 0.0,
                 hfr: float = 0.0, fwhm: float = 0.0,
                 hfr_arcsec: float = 0.0, fwhm_arcsec: float = 0.0):
        self.id = id
        self.x = x  # pixel coordinates
        self.y = y  # pixel coordinates
        self.ra = ra  # degrees (if WCS is available)
        self.dec = dec  # degrees (if WCS is available)
        self.flux = flux  # total flux
        self.area = area  # area in pixels
        self.eccentricity = eccentricity  # eccentricity
        self.semimajor_axis = semimajor_axis  # semimajor axis in pixels
        self.semiminor_axis = semiminor_axis  # semiminor axis in pixels
        self.orientation = orientation  # orientation in degrees
        self.peak_value = peak_value  # peak pixel value
        self.background = background  # background level
        self.snr = snr  # signal-to-noise ratio
        self.hfr = hfr  # half flux radius in pixels (NOT diameter)
        self.fwhm = fwhm  # full width at half maximum in pixels
        self.hfr_arcsec = hfr_arcsec  # half flux radius in arcseconds (NOT diameter)
        self.fwhm_arcsec = fwhm_arcsec  # full width at half maximum in arcseconds
    
    def __str__(self):
        coord_str = f"({self.x:.2f}, {self.y:.2f})"
        if self.ra is not None and self.dec is not None:
            coord_str += f" [RA={self.ra:.6f}°, Dec={self.dec:.6f}°]"
        return f"Source {self.id}: {coord_str}, Flux={self.flux:.2f}, SNR={self.snr:.2f}"
    
    @property
    def hfd(self):
        """Half Flux Diameter (HFD) = 2 × HFR"""
        return 2.0 * self.hfr if self.hfr > 0 else 0.0
    
    @property
    def hfd_arcsec(self):
        """Half Flux Diameter in arcseconds = 2 × HFR_arcsec"""
        return 2.0 * self.hfr_arcsec if self.hfr_arcsec > 0 else 0.0


class SourceDetectionResult:
    """Result of a source detection operation."""
    
    def __init__(self, success: bool, message: str = "", 
                 sources: List[DetectedSource] = None,
                 background: Optional[np.ndarray] = None,
                 background_rms: Optional[np.ndarray] = None,
                 segmentation_map: Optional[np.ndarray] = None,
                 detection_threshold: Optional[float] = None):
        self.success = success
        self.message = message
        self.sources = sources if sources is not None else []
        self.background = background
        self.background_rms = background_rms
        self.segmentation_map = segmentation_map
        self.detection_threshold = detection_threshold
    
    def __str__(self):
        status = "SUCCESS" if self.success else "FAILED"
        result = f"{status}: {self.message}"
        if self.success:
            result += f" ({len(self.sources)} sources detected)"
        return result
    
    def to_dict(self) -> Dict:
        """Convert the result to a dictionary format."""
        sources_data = []
        for source in self.sources:
            source_dict = {
                'id': source.id,
                'x': source.x,
                'y': source.y,
                'ra': source.ra,
                'dec': source.dec,
                'flux': source.flux,
                'area': source.area,
                'eccentricity': source.eccentricity,
                'semimajor_axis': source.semimajor_axis,
                'semiminor_axis': source.semiminor_axis,
                'orientation': source.orientation,
                'peak_value': source.peak_value,
                'background': source.background,
                'snr': source.snr,
                'hfr': source.hfr,
                'fwhm': source.fwhm,
                'hfr_arcsec': source.hfr_arcsec,
                'fwhm_arcsec': source.fwhm_arcsec
            }
            sources_data.append(source_dict)
        
        return {
            'success': self.success,
            'message': self.message,
            'sources': sources_data,
            'detection_threshold': self.detection_threshold,
            'total_sources': len(self.sources)
        }


def detect_sources_in_image(image: np.ndarray, 
                           wcs: Optional[WCS] = None,
                           threshold_sigma: float = 2.0,
                           npixels: int = 5,
                           connectivity: int = 8,
                           deblend: bool = True,
                           deblend_nthresh: int = 32,
                           deblend_cont: float = 0.005,
                           background_box_size: int = 50,
                           background_filter_size: int = 3,
                           min_area: int = 5,
                           max_area: Optional[int] = None,
                           min_eccentricity: float = 0.0,
                           max_eccentricity: float = 1.0,
                           min_snr: float = 3.0) -> SourceDetectionResult:
    """
    Detect sources in an astronomical image using photutils.
    
    Parameters:
    -----------
    image : np.ndarray
        Input image as a 2D numpy array
    wcs : Optional[WCS]
        World Coordinate System object for converting pixel to sky coordinates
    threshold_sigma : float
        Number of sigma above background for detection threshold
    npixels : int
        Minimum number of connected pixels for a source
    connectivity : int
        Connectivity for source detection (4 or 8)
    deblend : bool
        Whether to deblend overlapping sources
    deblend_nthresh : int
        Number of thresholds for deblending
    deblend_cont : float
        Minimum contrast ratio for deblending
    background_box_size : int
        Box size for background estimation
    background_filter_size : int
        Filter size for background estimation
    min_area : int
        Minimum area in pixels for a source
    max_area : Optional[int]
        Maximum area in pixels for a source (None for no limit)
    min_eccentricity : float
        Minimum eccentricity for a source
    max_eccentricity : float
        Maximum eccentricity for a source
    min_snr : float
        Minimum signal-to-noise ratio for a source
    
    Returns:
    --------
    SourceDetectionResult
        Object containing detection results and metadata
    """
    try:
        # Debug: log all parameters received
        logger.info("DEBUG: Function received parameters:")
        logger.info(f"  threshold_sigma={threshold_sigma}")
        logger.info(f"  npixels={npixels}")
        logger.info(f"  connectivity={connectivity}")
        logger.info(f"  deblend={deblend}")
        logger.info(f"  background_box_size={background_box_size}")
        logger.info(f"  background_filter_size={background_filter_size}")
        logger.info(f"  min_area={min_area}")
        logger.info(f"  max_area={max_area}")
        logger.info(f"  min_eccentricity={min_eccentricity}")
        logger.info(f"  max_eccentricity={max_eccentricity}")
        logger.info(f"  min_snr={min_snr}")
        
        # Validate input
        if image is None or image.size == 0:
            raise SourceDetectionError("Input image is empty or None")
        
        if len(image.shape) != 2:
            raise SourceDetectionError("Input image must be 2D")
        
        logger.info("=" * 60)
        logger.info("STARTING SOURCE DETECTION")
        logger.info("=" * 60)
        logger.info(f"Image shape: {image.shape}")
        logger.info(f"Image size: {image.size} pixels")
        logger.info(f"Image memory usage: {image.nbytes / (1024*1024):.1f} MB")
        logger.info(f"Current process memory: {get_memory_usage():.1f} MB")
        logger.info(f"Parameters: threshold_sigma={threshold_sigma}, npixels={npixels}, min_area={min_area}, min_snr={min_snr}")
        
        # Estimate background
        logger.info("Step 1: Estimating background...")
        logger.info(f"Using box_size={background_box_size}, filter_size={background_filter_size}")
        
        # Always use simple background estimation for reliability
        logger.info("Using simple background estimation with sigma-clipped stats")
        start_time = time.time()
        
        logger.info("Computing sigma-clipped statistics...")
        logger.info("This may take a while for large images...")
        background_mean, background_median, background_std = sigma_clipped_stats(image, sigma=3.0)
        logger.info(f"Background estimation completed in {time.time() - start_time:.2f} seconds")
        logger.info(f"Memory usage after background estimation: {get_memory_usage():.1f} MB")
        logger.info(f"Simple background estimation: mean={background_mean:.2f}, median={background_median:.2f}, std={background_std:.2f}")
        
        # Create a simple background array
        logger.info("Creating background arrays...")
        start_time = time.time()
        bkg_background = np.full_like(image, background_median)
        bkg_background_rms = np.full_like(image, background_std)
        logger.info(f"Background arrays created in {time.time() - start_time:.2f} seconds")
        logger.info(f"Memory usage after background arrays: {get_memory_usage():.1f} MB")
        
        # Create a simple background object for compatibility
        class SimpleBackground:
            def __init__(self, background, background_rms):
                self.background = background
                self.background_rms = background_rms
        
        bkg = SimpleBackground(bkg_background, bkg_background_rms)
        
        logger.info("Background estimation completed")
        
        # Debug: print background statistics
        logger.info(f"Background mean: {np.mean(bkg.background):.2f}")
        logger.info(f"Background std: {np.std(bkg.background):.2f}")
        logger.info(f"Background min/max: {np.min(bkg.background):.2f} / {np.max(bkg.background):.2f}")
        
        # Subtract background
        logger.info("Step 2: Subtracting background...")
        start_time = time.time()
        logger.info("Subtracting background from image...")
        image_cleaned = image - bkg.background
        logger.info(f"Background subtraction completed in {time.time() - start_time:.2f} seconds")
        logger.info(f"Memory usage after background subtraction: {get_memory_usage():.1f} MB")
        
        # Debug: print cleaned image statistics
        logger.info(f"Cleaned image mean: {np.mean(image_cleaned):.2f}")
        logger.info(f"Cleaned image std: {np.std(image_cleaned):.2f}")
        logger.info(f"Cleaned image min/max: {np.min(image_cleaned):.2f} / {np.max(image_cleaned):.2f}")
        
        # Calculate detection threshold
        logger.info("Step 3: Calculating detection threshold...")
        logger.info(f"Using threshold_sigma={threshold_sigma}")
        start_time = time.time()
        
        logger.info("Calling detect_threshold...")
        logger.info("This is often the slowest step for large images...")
        threshold = detect_threshold(image_cleaned, nsigma=threshold_sigma)
        logger.info(f"Threshold calculation completed in {time.time() - start_time:.2f} seconds")
        logger.info(f"Memory usage after threshold calculation: {get_memory_usage():.1f} MB")
        
        # If threshold is an array, use the mean
        if hasattr(threshold, '__len__') and len(threshold) > 1:
            threshold_value = float(np.mean(threshold))
            logger.info(f"Threshold is an array with {len(threshold)} elements")
        else:
            threshold_value = float(threshold)
        logger.info(f"Detection threshold: {threshold_value:.4f}")
        
        # Debug: check if threshold is reasonable
        max_cleaned = np.max(image_cleaned)
        logger.info(f"Max value in cleaned image: {max_cleaned:.2f}")
        if threshold_value > max_cleaned:
            logger.warning(f"Threshold ({threshold_value:.2f}) is higher than max cleaned value ({max_cleaned:.2f})")
            # Use a more reasonable threshold
            threshold_value = max_cleaned * 0.1  # 10% of max value
            logger.info(f"Using adjusted threshold: {threshold_value:.2f}")
            threshold = threshold_value
        
        # Detect sources
        logger.info("Step 4: Detecting sources...")
        logger.info(f"Using npixels={npixels}, connectivity={connectivity}")
        start_time = time.time()
        
        logger.info("Calling detect_sources...")
        logger.info("This step creates the segmentation map...")
        segment_map = detect_sources(image_cleaned, threshold, npixels=npixels,
                                   connectivity=connectivity)
        logger.info(f"Source detection completed in {time.time() - start_time:.2f} seconds")
        logger.info(f"Memory usage after source detection: {get_memory_usage():.1f} MB")
        
        if segment_map is None:
            logger.info("No segmentation map returned")
            return SourceDetectionResult(
                success=True,
                message="No sources detected - segmentation map is None",
                detection_threshold=threshold
            )
        
        logger.info(f"Initial detection found {segment_map.nlabels} sources")
        
        if segment_map.nlabels == 0:
            return SourceDetectionResult(
                success=True,
                message="No sources detected above threshold",
                detection_threshold=threshold
            )
        
        # Deblend sources if requested
        if deblend:
            logger.info("Step 5: Deblending sources...")
            logger.info(f"Using deblend_nthresh={deblend_nthresh}, deblend_cont={deblend_cont}")
            start_time = time.time()
            from photutils.segmentation import deblend_sources
            logger.info("Calling deblend_sources...")
            logger.info("This step can be very slow for images with many sources...")
            segment_map = deblend_sources(image_cleaned, segment_map,
                                        npixels=npixels, nlevels=deblend_nthresh,
                                        contrast=deblend_cont, progress_bar=False)
            logger.info(f"Deblending completed in {time.time() - start_time:.2f} seconds")
            logger.info(f"Memory usage after deblending: {get_memory_usage():.1f} MB")
            logger.info(f"After deblending: {segment_map.nlabels} sources")
        
        # Extract source properties
        logger.info("Step 6: Extracting source properties...")
        start_time = time.time()
        logger.info("Creating SourceCatalog...")
        logger.info("This step analyzes each detected source...")
        cat = SourceCatalog(image_cleaned, segment_map, background=bkg.background)
        logger.info(f"Source catalog creation completed in {time.time() - start_time:.2f} seconds")
        logger.info(f"Memory usage after catalog creation: {get_memory_usage():.1f} MB")
        
        logger.info(f"Extracted {len(cat)} source properties")
        
        # Filter sources based on criteria
        logger.info("Step 7: Filtering sources...")
        logger.info(f"Filtering criteria: min_area={min_area}, min_snr={min_snr}")
        start_time = time.time()
        sources = []
        filtered_count = 0
        
        logger.info("Processing source properties...")
        logger.info(f"Will process {len(cat)} sources...")
        
        # More frequent progress updates for large catalogs
        progress_interval = max(1, len(cat) // 20)  # Show progress ~20 times
        
        for i, prop in enumerate(cat):
            if i % progress_interval == 0:  # Log progress more frequently
                logger.info(f"Processing source {i+1}/{len(cat)} ({i/len(cat)*100:.1f}%)...")
            
            # Convert properties to scalar values
            area = float(prop.area.value) if hasattr(prop.area, 'value') else float(prop.area)
            eccentricity = float(prop.eccentricity.value) if hasattr(prop.eccentricity, 'value') else float(prop.eccentricity)
            segment_flux = float(prop.segment_flux.value) if hasattr(prop.segment_flux, 'value') else float(prop.segment_flux)
            background_mean = float(prop.background_mean.value) if hasattr(prop.background_mean, 'value') else float(prop.background_mean)
            xcentroid = float(prop.xcentroid.value) if hasattr(prop.xcentroid, 'value') else float(prop.xcentroid)
            ycentroid = float(prop.ycentroid.value) if hasattr(prop.ycentroid, 'value') else float(prop.ycentroid)
            max_value = float(prop.max_value.value) if hasattr(prop.max_value, 'value') else float(prop.max_value)
            semimajor_sigma = float(prop.semimajor_sigma.value) if hasattr(prop.semimajor_sigma, 'value') else float(prop.semimajor_sigma)
            semiminor_sigma = float(prop.semiminor_sigma.value) if hasattr(prop.semiminor_sigma, 'value') else float(prop.semiminor_sigma)
            orientation = float(prop.orientation.to(u.deg).value)
            
            # Extract HFR and FWHM if available
            hfr = 0.0
            fwhm = 0.0
            
            # Try to get HFR (half flux radius) from photutils
            # Note: HFR is the RADIUS containing half the flux, not diameter
            if hasattr(prop, 'half_light_radius'):
                try:
                    hfr = float(prop.half_light_radius.value) if hasattr(prop.half_light_radius, 'value') else float(prop.half_light_radius)
                    logger.debug(f"Source {i}: HFR from photutils: {hfr:.3f} pixels")
                except:
                    hfr = 0.0
            
            # Try to get FWHM
            if hasattr(prop, 'fwhm'):
                try:
                    fwhm = float(prop.fwhm.value) if hasattr(prop.fwhm, 'value') else float(prop.fwhm)
                except:
                    fwhm = 0.0
            
            # If HFR is not available, estimate it from the area
            if hfr == 0.0 and area > 0:
                # More accurate HFR estimation: typically HFR ≈ 0.5 * sqrt(area)
                # This is based on typical source profiles where HFR is smaller than geometric radius
                hfr = 0.5 * np.sqrt(area / np.pi)  # Conservative estimate for HFR
                logger.debug(f"Source {i}: HFR estimated from area: {hfr:.3f} pixels (area={area:.1f})")
            
            # If FWHM is not available, estimate it from the sigma values
            if fwhm == 0.0 and semimajor_sigma > 0:
                fwhm = 2.355 * semimajor_sigma  # FWHM ≈ 2.355 * σ for Gaussian
            
            # Calculate arcsecond values from pixel values
            hfr_arcsec = 0.0
            fwhm_arcsec = 0.0
            
            # Get image scale from WCS if available
            image_scale = get_image_scale_from_wcs(wcs)
            
            # If no WCS scale, use a default value (common for many telescopes)
            if image_scale is None:
                # Default to 1 arcsec/pixel (common for many amateur setups)
                # This can be overridden by the user or extracted from FITS headers
                image_scale = 1.0
                logger.info("Using default image scale: 1.0 arcsec/pixel")
            else:
                logger.info(f"Using image scale from WCS: {image_scale:.3f} arcsec/pixel")
            
            # Convert pixel values to arcseconds
            hfr_arcsec = hfr * image_scale
            fwhm_arcsec = fwhm * image_scale
            
            # Apply filters
            if area < min_area:
                filtered_count += 1
                continue
            if max_area is not None and area > max_area:
                filtered_count += 1
                continue
            if eccentricity < min_eccentricity or eccentricity > max_eccentricity:
                filtered_count += 1
                continue
            
            # Calculate SNR
            snr = segment_flux / np.sqrt(segment_flux + area * background_mean)
            
            if snr < min_snr:
                filtered_count += 1
                continue
            
            # Convert pixel coordinates to sky coordinates if WCS is available
            ra, dec = None, None
            if wcs is not None:
                try:
                    sky_coords = wcs.pixel_to_world(xcentroid, ycentroid)
                    ra = sky_coords.ra.deg
                    dec = sky_coords.dec.deg
                except Exception as e:
                    logger.warning(f"Could not convert coordinates for source {i}: {e}")
            
            # Create source object
            source = DetectedSource(
                id=i + 1,
                x=xcentroid,
                y=ycentroid,
                ra=ra,
                dec=dec,
                flux=segment_flux,
                area=area,
                eccentricity=eccentricity,
                semimajor_axis=semimajor_sigma,
                semiminor_axis=semiminor_sigma,
                orientation=orientation,
                peak_value=max_value,
                background=background_mean,
                snr=snr,
                hfr=hfr,
                fwhm=fwhm,
                hfr_arcsec=hfr_arcsec,
                fwhm_arcsec=fwhm_arcsec
            )
            sources.append(source)
        
        logger.info(f"Source filtering completed in {time.time() - start_time:.2f} seconds")
        logger.info(f"Memory usage after filtering: {get_memory_usage():.1f} MB")
        logger.info(f"Filtered out {filtered_count} sources, kept {len(sources)} sources")
        
        logger.info("=" * 60)
        logger.info("SOURCE DETECTION COMPLETED")
        logger.info(f"Total sources detected: {len(sources)}")
        logger.info(f"Final memory usage: {get_memory_usage():.1f} MB")
        logger.info("=" * 60)
        
        return SourceDetectionResult(
            success=True,
            message=f"Successfully detected {len(sources)} sources",
            sources=sources,
            background=bkg.background,
            background_rms=bkg.background_rms,
            segmentation_map=segment_map.data,
            detection_threshold=threshold
        )
        
    except Exception as e:
        logger.error(f"Source detection failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return SourceDetectionResult(
            success=False,
            message=f"Source detection failed: {str(e)}"
        )


def detect_sources_from_fits(fits_file_path: str,
                            extension: int = 0,
                            **kwargs) -> SourceDetectionResult:
    """
    Detect sources from a FITS file.
    
    Parameters:
    -----------
    fits_file_path : str
        Path to the FITS file
    extension : int
        FITS extension to use (0 for primary)
    **kwargs
        Additional arguments passed to detect_sources_in_image
    
    Returns:
    --------
    SourceDetectionResult
        Object containing detection results and metadata
    """
    try:
        from astropy.io import fits
        
        # Read FITS file
        with fits.open(fits_file_path) as hdul:
            image = hdul[extension].data
            header = hdul[extension].header
            
            # Extract WCS if available
            wcs = None
            try:
                wcs = WCS(header)
            except Exception as e:
                logger.warning(f"Could not extract WCS from header: {e}")
        
        # Detect sources
        return detect_sources_in_image(image, wcs=wcs, **kwargs)
        
    except Exception as e:
        logger.error(f"Error reading FITS file {fits_file_path}: {e}")
        return SourceDetectionResult(
            success=False,
            message=f"Error reading FITS file: {str(e)}"
        )


def aperture_photometry_sources(image: np.ndarray,
                               sources: List[DetectedSource],
                               aperture_radius: float = 3.0,
                               background_annulus: Tuple[float, float] = (5.0, 8.0)) -> List[Dict]:
    """
    Perform aperture photometry on detected sources.
    
    Parameters:
    -----------
    image : np.ndarray
        Input image
    sources : List[DetectedSource]
        List of detected sources
    aperture_radius : float
        Radius of the circular aperture in pixels
    background_annulus : Tuple[float, float]
        Inner and outer radius of background annulus in pixels
    
    Returns:
    --------
    List[Dict]
        List of dictionaries containing photometry results
    """
    try:
        from photutils.aperture import CircularAperture, CircularAnnulus, aperture_photometry
        from astropy.stats import sigma_clipped_stats
        
        results = []
        
        for source in sources:
            # Create aperture
            position = (source.x, source.y)
            aperture = CircularAperture(position, r=aperture_radius)
            
            # Create background annulus
            annulus = CircularAnnulus(position, r_in=background_annulus[0], 
                                    r_out=background_annulus[1])
            
            # Perform photometry
            phot_table = aperture_photometry(image, aperture)
            
            # Calculate background
            annulus_masks = annulus.to_mask(method='center')
            annulus_data = annulus_masks.multiply(image)
            mask = annulus_masks.data
            annulus_data_1d = annulus_data[mask > 0]
            bkg_mean, bkg_median, bkg_std = sigma_clipped_stats(annulus_data_1d)
            
            # Calculate background-subtracted flux
            aperture_area = aperture.area
            bkg_sum = bkg_median * aperture_area
            final_sum = phot_table['aperture_sum'][0] - bkg_sum
            
            # Calculate error
            flux_error = np.sqrt(phot_table['aperture_sum'][0] + aperture_area * bkg_std**2)
            
            result = {
                'source_id': source.id,
                'x': source.x,
                'y': source.y,
                'ra': source.ra,
                'dec': source.dec,
                'aperture_sum': phot_table['aperture_sum'][0],
                'background_subtracted_sum': final_sum,
                'background_mean': bkg_mean,
                'background_median': bkg_median,
                'background_std': bkg_std,
                'flux_error': flux_error,
                'aperture_area': aperture_area,
                'snr': final_sum / flux_error if flux_error > 0 else 0.0
            }
            results.append(result)
        
        return results
        
    except Exception as e:
        logger.error(f"Aperture photometry failed: {e}")
        return []
