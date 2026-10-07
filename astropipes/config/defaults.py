''' Default settings. User overrides live in the TOML file named by astropipes.config.CONFIG_PATH;
    only keys defined here are recognised.
'''

from pathlib import Path

_HOME = Path.home()

# astropipes writes calibration masters (and expects them to stay) in CALIBRATION_PATH.
CALIBRATION_PATH = str(_HOME / 'Astro' / 'calibration')
DATA_PATH = str(_HOME / 'Astro' / 'data')
STACKS_PATH = str(_HOME / 'Astro' / 'stacks')
ARCHIVE_PATH = str(_HOME / 'Astro' / 'archive')
# Scratch folder for calibrated / aligned intermediate files
PROCESSED_PATH = str(_HOME / '.cache' / 'astropipes')
# SQLite database file path (absolute path)
DATABASE_PATH = str(_HOME / 'Astro' / 'astropipes.db')

OBS_CODE = '500'
OBS_LON = 0.0
OBS_LAT = 0.0

# Solver options. Search radius in degrees.
SOLVER_DOWNSAMPLE = 2
SOLVER_SEARCH_RADIUS = 15

# Image alignment settings
# Default alignment method: "astroalign" (fast, asterism-based) or "wcs_reprojection" (slow, WCS-based)
DEFAULT_ALIGNMENT_METHOD = "astroalign"
# Fallback alignment method if the default method fails or is not available
FALLBACK_ALIGNMENT_METHOD = "wcs_reprojection"
# Show a dialog to choose the alignment method each time
SHOW_ALIGNMENT_METHOD_DIALOG = False
MAX_ALIGNMENT_IMAGES = 50
ALIGNMENT_MEMORY_LIMIT = 4e9  # Memory limit for alignment (in bytes)
ALIGNMENT_CHUNK_SIZE = 10     # Number of images to process in each chunk
ALIGNMENT_ENABLE_CHUNKED = True  # Enable chunked processing for large datasets
ALIGNMENT_SAVE_PROGRESSIVE = True  # Save aligned images progressively instead of all at once

# Integration settings
SIGMA_LOW = 4
SIGMA_HIGH = 3
INTEGRATION_MEMORY_LIMIT = 6e9  # Memory limit for integration (in bytes)
INTEGRATION_CHUNK_SIZE = 15     # Number of images to process in each chunk
INTEGRATION_ENABLE_CHUNKED = True  # Enable chunked processing for large datasets
MAX_INTEGRATION_IMAGES = 100    # Maximum number of images to integrate at once

# Motion tracking integration settings
MOTION_TRACKING_SIGMA_CLIP = False  # Disable sigma clipping by default for motion tracking to avoid border issues
MOTION_TRACKING_METHOD = 'average'  # Default integration method for motion tracking
MOTION_TRACKING_CREATE_BOTH_STACKS = True  # Create both median and average stacks

# Maximum age of calibration masters relative to the light frame, in days. 0 = no limit.
MAX_BIAS_AGE = 0
MAX_DARK_AGE = 0
MAX_FLAT_AGE = 0

# FITS cards that must match (within tolerance) across a sequence before integration
TESTED_FITS_CARDS = [
    {'name': 'GAIN', 'tolerance': 0},
    {'name': 'OFFSET', 'tolerance': 0},
    {'name': 'XBINNING', 'tolerance': 0},
    {'name': 'EXPTIME', 'tolerance': 1},
    {'name': 'FILTER', 'tolerance': 0},
    {'name': 'CCD-TEMP', 'tolerance': 2},
    {'name': 'NAXIS1', 'tolerance': 0},
    {'name': 'NAXIS2', 'tolerance': 0},
]

# 'UTC' or 'Local'
TIME_DISPLAY_MODE = 'UTC'
# Viewer blink interval
BLINK_PERIOD_MS = 1000

# Library: watch DATA_PATH and CALIBRATION_PATH and scan new files automatically
DATA_FOLDER_WATCH_ENABLED = True
DATA_FOLDER_WATCH_DEBOUNCE_MS = 1500

# Automatic processing (astropipes --watch): poll DATA_PATH, and stack each finished run of a
# follow-up target. A run ends when a frame of another target arrives, or after the idle time.
AUTOPROCESS_POLL_SECONDS = 30
AUTOPROCESS_RUN_IDLE_MINUTES = 30
AUTOPROCESS_FILE_SETTLE_SECONDS = 10  # Skip files modified more recently (still being written)
AUTOPROCESS_RECOVERY_HOURS = 36  # On startup, process missed runs that ended this recently
