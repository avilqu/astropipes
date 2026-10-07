''' Conversion of stored UTC datetimes to the user's display timezone. '''

from datetime import timezone

import tzlocal

from astropipes.config import settings


def to_display_time(dt_utc):
    """Convert a UTC datetime to local time if TIME_DISPLAY_MODE is 'Local', else return as UTC."""
    if dt_utc is None:
        return None
    # Read at call time: the settings dialog reloads settings.
    if settings.TIME_DISPLAY_MODE == 'Local':
        return dt_utc.replace(tzinfo=timezone.utc).astimezone(tzlocal.get_localzone())
    return dt_utc.replace(tzinfo=timezone.utc)
