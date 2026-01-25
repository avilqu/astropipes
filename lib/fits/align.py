import numpy as np
from astropy.wcs import WCS
from astropy.io import fits
from typing import List, Tuple, Optional
import gc
import os

# Try to import psutil for memory tracking
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    from reproject import reproject_interp
except ImportError:
    reproject_interp = None  # Will raise error if used without install

try:
    import astroalign as aa
    ASTROALIGN_AVAILABLE = True
except ImportError:
    ASTROALIGN_AVAILABLE = False

# Import configuration
from config import (ALIGNMENT_MEMORY_LIMIT, ALIGNMENT_CHUNK_SIZE, 
                   ALIGNMENT_ENABLE_CHUNKED, ALIGNMENT_SAVE_PROGRESSIVE)

class AlignmentError(Exception):
    pass

def get_memory_usage():
    """Get current memory usage in MB."""
    if PSUTIL_AVAILABLE:
        try:
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / (1024 * 1024)
        except Exception:
            return 0.0
    else:
        return 0.0

def check_memory_limit(current_usage_mb=None, limit_mb=None):
    """Check if current memory usage exceeds the limit."""
    if limit_mb is None:
        limit_mb = ALIGNMENT_MEMORY_LIMIT / (1024 * 1024)
    
    if current_usage_mb is None:
        current_usage_mb = get_memory_usage()
    
    return current_usage_mb > limit_mb

def force_garbage_collection():
    """Force garbage collection to free memory."""
    gc.collect()
    if hasattr(gc, 'collect'):
        gc.collect(2)  # Full collection

def check_all_have_wcs(headers: List[fits.Header]) -> bool:
    """Return True if all headers have valid WCS, else False."""
    for header in headers:
        try:
            wcs = WCS(header)
            if not wcs.has_celestial:
                return False
        except Exception:
            return False
    return True

def check_pixel_scales_match(headers: List[fits.Header]) -> bool:
    """Return True if all images have the same pixel scale within 0.01 arcsec tolerance."""
    scales = []
    for header in headers:
        wcs = WCS(header)
        try:
            # Pixel scale in degrees per pixel
            scale_deg = np.abs(wcs.pixel_scale_matrix.diagonal())
            scales.append(scale_deg)
        except Exception:
            return False
    # Convert to arcsec per pixel
    scales_arcsec = [s * 3600 for s in scales]
    ref = scales_arcsec[0]
    for s in scales_arcsec[1:]:
        if not np.all(np.abs(ref - s) <= 0.01):
            return False
    return True

def compute_padded_reference_wcs(headers: List[fits.Header], paddings: Tuple[int, int]=(0, 0)) -> Tuple[WCS, Tuple[int, int]]:
    """
    Use the WCS of the first header as the reference, with no extra padding.
    Returns: (new_wcs, (new_nx, new_ny))
    """
    ref_header = headers[0].copy()
    wcs = WCS(ref_header)
    # No padding: use original CRPIX and NAXIS values
    new_nx = ref_header['NAXIS1']
    new_ny = ref_header['NAXIS2']
    return WCS(ref_header), (new_nx, new_ny)

def reproject_images_to_common_wcs(image_datas: List[np.ndarray], headers: List[fits.Header], common_wcs: WCS, shape_out: Tuple[int, int], progress_callback=None) -> List[np.ndarray]:
    """
    Reproject all images to the common WCS frame.
    progress_callback: optional function(progress: float) for UI updates.
    Returns list of reprojected images.
    """
    if reproject_interp is None:
        raise ImportError("reproject package is required for WCS alignment.")
    result = []
    n = len(image_datas)
    for i, (data, header) in enumerate(zip(image_datas, headers)):
        wcs = WCS(header)
        array, _ = reproject_interp((data, wcs), common_wcs, shape_out=shape_out, order='bilinear')
        result.append(array)
        if progress_callback:
            progress_callback((i+1)/n)
    return result

# New astroalign-based alignment functions
def _fix_byte_order_for_astroalign(image: np.ndarray) -> np.ndarray:
    """
    Convert image to native byte order for astroalign compatibility.
    
    Parameters:
    -----------
    image : np.ndarray
        Input image array
        
    Returns:
    --------
    np.ndarray
        Image with native byte order
    """
    if image.dtype.byteorder == '>':  # Big-endian
        return image.astype(image.dtype.newbyteorder('='))
    else:
        return image

def align_images_with_astroalign(image_datas: List[np.ndarray], headers: List[fits.Header], reference_index: int = 0, progress_callback=None) -> Tuple[List[np.ndarray], fits.Header]:
    """
    Align images using astroalign's asterism matching.
    
    Parameters:
    -----------
    image_datas : List[np.ndarray]
        List of image arrays to align
    headers : List[fits.Header]
        List of FITS headers corresponding to the images
    reference_index : int
        Index of the reference image (default: 0)
    progress_callback : callable, optional
        Progress callback function(progress: float)
        
    Returns:
    --------
    Tuple[List[np.ndarray], fits.Header]
        List of aligned images and the reference header with WCS information
    """
    if not ASTROALIGN_AVAILABLE:
        raise ImportError("astroalign package is required for asterism-based alignment.")
    
    if len(image_datas) < 2:
        return image_datas, headers[0] if headers else None
    
    # Use the first image as reference
    reference_image = image_datas[reference_index]
    reference_header = headers[reference_index] if headers else None
    aligned_images = [reference_image]  # Reference image stays unchanged
    
    n = len(image_datas) - 1  # Exclude reference image
    current = 0
    
    for i, image in enumerate(image_datas):
        if i == reference_index:
            continue
            
        try:
            # Fix byte order issues for astroalign compatibility
            # Convert to native byte order if needed
            image_native = _fix_byte_order_for_astroalign(image)
            reference_native = _fix_byte_order_for_astroalign(reference_image)
            
            # Align current image to reference
            aligned_image, _ = aa.register(image_native, reference_native)
            aligned_images.append(aligned_image)
            
            current += 1
            if progress_callback:
                progress_callback(current / n)
                
        except Exception as e:
            print(f"Warning: Failed to align image {i} using astroalign: {e}")
            # If astroalign fails, use the original image
            aligned_images.append(image)
            current += 1
            if progress_callback:
                progress_callback(current / n)
    
    # Reorder to match original order
    result = [None] * len(image_datas)
    result[reference_index] = reference_image
    
    current = 0
    for i in range(len(image_datas)):
        if i != reference_index:
            result[i] = aligned_images[current + 1]  # +1 because aligned_images[0] is reference
            current += 1
    
    return result, reference_header

def find_transform_with_astroalign(source_image: np.ndarray, target_image: np.ndarray) -> Tuple[np.ndarray, List[Tuple[float, float]]]:
    """
    Find the transformation matrix between two images using astroalign.
    
    Parameters:
    -----------
    source_image : np.ndarray
        Source image
    target_image : np.ndarray
        Target image
        
    Returns:
    --------
    Tuple[np.ndarray, List[Tuple[float, float]]]
        Transformation matrix and list of matched source points
    """
    if not ASTROALIGN_AVAILABLE:
        raise ImportError("astroalign package is required for asterism-based alignment.")
    
    try:
        # Fix byte order issues for astroalign compatibility
        source_native = _fix_byte_order_for_astroalign(source_image)
        target_native = _fix_byte_order_for_astroalign(target_image)
        
        # Find transformation matrix
        transform_matrix, (source_stars, target_stars) = aa.find_transform(source_native, target_native)
        return transform_matrix, source_stars
    except Exception as e:
        raise AlignmentError(f"Failed to find transformation: {e}")

def apply_transform_with_astroalign(image: np.ndarray, transform_matrix: np.ndarray, target_shape: Optional[Tuple[int, int]] = None) -> np.ndarray:
    """
    Apply transformation matrix to an image.
    
    Parameters:
    -----------
    image : np.ndarray
        Image to transform
    transform_matrix : np.ndarray
        Transformation matrix from astroalign
    target_shape : Tuple[int, int], optional
        Target shape for the output image
        
    Returns:
    --------
    np.ndarray
        Transformed image
    """
    if not ASTROALIGN_AVAILABLE:
        raise ImportError("astroalign package is required for asterism-based alignment.")
    
    try:
        # Fix byte order issues for astroalign compatibility
        image_native = _fix_byte_order_for_astroalign(image)
        
        if target_shape is None:
            target_shape = image.shape
        
        transformed_image = aa.apply_transform(transform_matrix, image_native, target_shape)
        return transformed_image
    except Exception as e:
        raise AlignmentError(f"Failed to apply transformation: {e}")

def check_astroalign_available() -> bool:
    """Check if astroalign is available for use."""
    return ASTROALIGN_AVAILABLE

def get_alignment_methods() -> List[str]:
    """Get list of available alignment methods."""
    methods = ["wcs_reprojection"]
    if ASTROALIGN_AVAILABLE:
        methods.append("astroalign")
    return methods

def align_images_chunked(image_datas: List[np.ndarray], 
                        headers: List[fits.Header], 
                        method: str = "astroalign",
                        reference_index: int = 0,
                        chunk_size: Optional[int] = None,
                        memory_limit: Optional[float] = None,
                        progress_callback=None,
                        log_callback=None) -> Tuple[List[np.ndarray], fits.Header]:
    """
    Align images in chunks to prevent memory issues with large datasets.
    
    Parameters:
    -----------
    image_datas : List[np.ndarray]
        List of image arrays to align
    headers : List[fits.Header]
        List of FITS headers corresponding to the images
    method : str
        Alignment method ("astroalign" or "wcs_reprojection")
    reference_index : int
        Index of the reference image
    chunk_size : Optional[int]
        Number of images per chunk. If None, uses default ALIGNMENT_CHUNK_SIZE.
    memory_limit : Optional[float]
        Memory limit in bytes. If None, uses default ALIGNMENT_MEMORY_LIMIT.
    progress_callback : callable, optional
        Progress callback function(progress: float)
    log_callback : callable, optional
        Log callback function(message: str) for console output
        
    Returns:
    --------
    Tuple[List[np.ndarray], fits.Header]
        List of aligned images and the reference header
    """
    def log(message):
        if log_callback:
            log_callback(message)
        else:
            print(message)
    
    if len(image_datas) < 2:
        return image_datas, headers[0] if headers else None
    
    # Use defaults if not specified
    chunk_size = chunk_size or ALIGNMENT_CHUNK_SIZE
    memory_limit = memory_limit or ALIGNMENT_MEMORY_LIMIT
    
    log(f"\nAligning {len(image_datas)} images with chunked processing\n")
    log(f"Chunk size: {chunk_size} images\n")
    log(f"Memory limit: {memory_limit / 1e9:.1f} GB\n")
    log(f"Method: {method}\n")
    
    # Get reference image and header
    reference_image = image_datas[reference_index]
    reference_header = headers[reference_index] if headers else None
    
    # Initialize result list with reference image
    aligned_images = [None] * len(image_datas)
    aligned_images[reference_index] = reference_image
    
    # Process images in chunks
    total_chunks = (len(image_datas) + chunk_size - 1) // chunk_size
    processed_count = 0
    
    for chunk_idx in range(total_chunks):
        start_idx = chunk_idx * chunk_size
        end_idx = min(start_idx + chunk_size, len(image_datas))
        
        # Skip reference image if it's in this chunk
        chunk_indices = [i for i in range(start_idx, end_idx) if i != reference_index]
        
        if not chunk_indices:
            continue
            
        log(f"\nProcessing chunk {chunk_idx + 1}/{total_chunks} (indices {chunk_indices})\n")
        
        # Check memory before processing chunk
        current_memory = get_memory_usage()
        log(f"Memory before chunk: {current_memory:.1f} MB\n")
        
        if check_memory_limit(current_memory, memory_limit / (1024 * 1024)):
            log(f"Warning: Memory usage ({current_memory:.1f} MB) is high, forcing garbage collection\n")
            force_garbage_collection()
        
        # Process each image in the chunk
        for i, image_idx in enumerate(chunk_indices):
            try:
                log(f"  Aligning image {image_idx + 1}/{len(image_datas)}\n")
                
                if method == "astroalign":
                    aligned_image = _align_single_image_astroalign(
                        image_datas[image_idx], reference_image, image_idx, log_callback
                    )
                else:  # wcs_reprojection
                    aligned_image = _align_single_image_wcs(
                        image_datas[image_idx], headers[image_idx], reference_header, image_idx, log_callback
                    )
                
                aligned_images[image_idx] = aligned_image
                processed_count += 1
                
                # Update progress
                if progress_callback:
                    progress_callback(processed_count / (len(image_datas) - 1))
                
                # Check memory after each image
                current_memory = get_memory_usage()
                if check_memory_limit(current_memory, memory_limit / (1024 * 1024)):
                    log(f"Warning: High memory usage ({current_memory:.1f} MB), forcing cleanup\n")
                    force_garbage_collection()
                
            except Exception as e:
                log(f"Warning: Failed to align image {image_idx}: {e}\n")
                # Use original image if alignment fails
                aligned_images[image_idx] = image_datas[image_idx]
                processed_count += 1
        
        # Force cleanup after each chunk
        log(f"Cleaning up after chunk {chunk_idx + 1}")
        force_garbage_collection()
        
        # Check memory after chunk
        current_memory = get_memory_usage()
        log(f"Memory after chunk: {current_memory:.1f} MB\n")
    
    log(f"\nChunked alignment complete. Processed {processed_count} images.\n")
    return aligned_images, reference_header

def _align_single_image_astroalign(image: np.ndarray, reference_image: np.ndarray, image_idx: int, log_callback=None) -> np.ndarray:
    """Align a single image to reference using astroalign."""
    def log(message):
        if log_callback:
            log_callback(message)
        else:
            print(message)
    
    if not ASTROALIGN_AVAILABLE:
        raise ImportError("astroalign package is required for asterism-based alignment.")
    
    try:
        # Fix byte order issues for astroalign compatibility
        image_native = _fix_byte_order_for_astroalign(image)
        reference_native = _fix_byte_order_for_astroalign(reference_image)
        
        # Align current image to reference
        aligned_image, _ = aa.register(image_native, reference_native)
        return aligned_image
        
    except Exception as e:
        log(f"Warning: astroalign failed for image {image_idx}: {e}")
        # Return original image if alignment fails
        return image

def _align_single_image_wcs(image: np.ndarray, header: fits.Header, reference_header: fits.Header, image_idx: int, log_callback=None) -> np.ndarray:
    """Align a single image to reference using WCS reprojection."""
    def log(message):
        if log_callback:
            log_callback(message)
        else:
            print(message)
    
    if reproject_interp is None:
        raise ImportError("reproject package is required for WCS alignment.")
    
    try:
        # Create WCS objects
        wcs = WCS(header)
        ref_wcs = WCS(reference_header)
        
        # Get target shape from reference
        target_shape = (reference_header['NAXIS2'], reference_header['NAXIS1'])
        
        # Reproject image
        aligned_image, _ = reproject_interp((image, wcs), ref_wcs, shape_out=target_shape, order='bilinear')
        return aligned_image
        
    except Exception as e:
        log(f"Warning: WCS reprojection failed for image {image_idx}: {e}")
        # Return original image if alignment fails
        return image 