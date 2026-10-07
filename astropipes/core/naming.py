''' Normalisation of target names and conversion of names to folder-safe segments. '''

import os


def normalize_object_name(obj):
    """
    Normalize object name by replacing underscores with spaces and stripping whitespace.
    """
    if obj is None:
        return None
    return str(obj).replace('_', ' ').strip()


def data_path_target_folder_name(target_name: str) -> str:
    """Directory name under DATA_PATH (or STACKS_PATH) for a target (spaces → underscores)."""
    if target_name is None:
        return ''
    return str(target_name).replace(' ', '_')


def path_slug(name) -> str:
    """Single folder segment for a name: spaces and path separators become underscores."""
    return str(name).replace(" ", "_").replace(os.sep, "_")
