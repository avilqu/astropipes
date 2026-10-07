''' Process memory measurement for chunked alignment / integration. '''

import gc
import os

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


def get_memory_usage():
    """Get current memory usage in MB (0.0 if psutil is unavailable)."""
    if PSUTIL_AVAILABLE:
        try:
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / (1024 * 1024)
        except Exception:
            return 0.0
    else:
        return 0.0


def check_memory_limit(current_usage_mb, limit_mb):
    """Check if current memory usage (None = measure now) exceeds the limit."""
    if current_usage_mb is None:
        current_usage_mb = get_memory_usage()
    return current_usage_mb > limit_mb


def force_garbage_collection():
    """Force a full garbage collection to free memory."""
    gc.collect(2)
