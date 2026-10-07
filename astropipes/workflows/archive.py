"""
Library operations that move or rename files on disk together with their database records:
archiving a target, renaming a target, renaming a region of interest.
"""

import shutil
import sys
from pathlib import Path

from astropipes.config import settings
from astropipes.core import paths
from astropipes.core.naming import data_path_target_folder_name, normalize_object_name
from astropipes.db import get_db_manager
from astropipes.db.scan import rescan_single_file
from astropipes.fits.header import set_fits_header_value
from astropipes.regions.views import relocate_region_views_directory


def archive_target(target: str, archive_path: str = None, log=print) -> dict:
    """Move all files of a target to the archive and remove them from the database.

    Session stacks (and follow-up flags) are deleted rather than archived. Light frames keep
    their path relative to DATA_PATH under archive_path (default settings.ARCHIVE_PATH), then
    the target's now-empty folders under DATA_PATH are removed.

    Returns {'files_moved': int, 'files_removed': int, 'errors': [{'path', 'error'}]}.
    """
    archive_base = Path(archive_path or settings.ARCHIVE_PATH)
    data_path = Path(settings.DATA_PATH)
    db = get_db_manager()
    results = {'files_moved': 0, 'files_removed': 0, 'errors': []}

    # Remove follow-up flags and session stacks (DB + disk) before archiving raw data
    db.follow_up_clear(target)
    for row in db.get_files_by_target(target):
        if paths.is_session_stack_fits_file(row) and db.delete_fits_file(row.id):
            results['files_removed'] += 1
    for tree in (paths.stacks_path_for_target(target), paths.legacy_stacks_path_for_target(target)):
        if tree.exists():
            try:
                shutil.rmtree(tree)
            except Exception as e:
                results['errors'].append({'path': str(tree), 'error': str(e)})

    files = db.get_files_by_target(target)
    log(f"Found {len(files)} files in database for target '{target}'")
    if not files:
        return results

    archive_base.mkdir(parents=True, exist_ok=True)
    for fits_file in files:
        original_path = Path(fits_file.path)
        try:
            if original_path.exists():
                try:
                    relative_path = original_path.relative_to(data_path)
                except ValueError:
                    # File is not under DATA_PATH, use filename only
                    relative_path = original_path.name
                archive_file_path = archive_base / relative_path
                archive_file_path.parent.mkdir(parents=True, exist_ok=True)
                log(f"Moving file: {original_path} -> {archive_file_path}")
                shutil.move(str(original_path), str(archive_file_path))
                results['files_moved'] += 1
            else:
                log(f"File doesn't exist, removing from database only: {original_path}")
            if db.delete_fits_file(fits_file.id):
                results['files_removed'] += 1
            else:
                results['errors'].append({'path': str(original_path), 'error': 'Could not remove database entry'})
        except Exception as e:
            results['errors'].append({'path': str(original_path), 'error': str(e)})

    target_dir = _target_data_dir(target, files, data_path)
    if target_dir is None:
        log(f"No data folder found for target '{target}' under {data_path}; nothing to clean up")
    else:
        _remove_empty_dirs(target_dir, results, log)
    return results


def _target_data_dir(target, files, data_path):
    """The target's folder under DATA_PATH: by name (as is, spaces↔underscores), else from the
    location of files that are still there."""
    for variant in dict.fromkeys([target, target.replace(" ", "_"), target.replace("_", " ")]):
        if (data_path / variant).is_dir():
            return data_path / variant
    for fits_file in files:
        try:
            relative = Path(fits_file.path).parent.relative_to(data_path)
        except ValueError:
            continue
        if relative.parts and (data_path / relative.parts[0]).is_dir():
            return data_path / relative.parts[0]
    return None


def _remove_empty_dirs(root: Path, results: dict, log):
    """Remove empty folders under root (deepest first), then root itself if empty. Never deletes files."""
    for directory in sorted((p for p in root.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
        except OSError as e:
            results['errors'].append({'path': str(directory), 'error': f'Failed to remove folder: {e}'})
    try:
        if not any(root.iterdir()):
            root.rmdir()
            log(f"Removed target folder: {root}")
        else:
            log(f"Target folder {root} is not empty; left in place")
    except OSError as e:
        results['errors'].append({'path': str(root), 'error': f'Failed to remove target folder: {e}'})


def _existing_target_dir(root: Path, target: str):
    """The target's folder under root: the usual underscore folder name, else the raw name."""
    for name in dict.fromkeys([data_path_target_folder_name(target), target]):
        if (root / name).is_dir():
            return root / name
    return None


def rename_target(old_target: str, new_target: str) -> dict:
    """Rename a target: its folders under DATA_PATH and STACKS_PATH, its database records
    (files, follow-up flags, regions and region views) and the OBJECT card of its files.

    Returns {'files_updated', 'errors', 'files', 'folder_renamed', 'folder_error'}.
    """
    results = {'files_updated': 0, 'errors': [], 'files': [], 'folder_renamed': False, 'folder_error': None}
    old_norm, new_norm = normalize_object_name(old_target), normalize_object_name(new_target)
    new_folder = data_path_target_folder_name(new_norm)

    # Plan folder moves: the data folder must exist; the stacks folder is optional
    moves = []
    for root, required in ((Path(settings.DATA_PATH), True), (Path(settings.STACKS_PATH), False)):
        old_dir = _existing_target_dir(root, old_norm)
        if old_dir is None:
            if required:
                results['folder_error'] = (f"Target folder does not exist: "
                                           f"{root / data_path_target_folder_name(old_norm)}")
                return results
            continue
        new_dir = root / new_folder
        if new_dir.exists() and new_dir != old_dir:
            results['folder_error'] = f"New target folder already exists: {new_dir}"
            return results
        if new_dir != old_dir:
            moves.append((old_dir, new_dir))

    done = []
    try:
        for old_dir, new_dir in moves:
            old_dir.rename(new_dir)
            done.append((old_dir, new_dir))
        renamed = get_db_manager().rename_target_records(old_norm, new_norm, moves)
    except Exception as e:
        for old_dir, new_dir in reversed(done):  # put the folders back
            new_dir.rename(old_dir)
        results['folder_error'] = str(e)
        return results
    results['folder_renamed'] = bool(moves)

    for _old_path, new_path in renamed:
        try:
            set_fits_header_value(new_path, 'OBJECT', new_norm)
            rescan_result = rescan_single_file(new_path)
            results['files_updated'] += 1
            results['files'].append({'path': new_path, 'rescan': rescan_result})
        except Exception as e:
            results['errors'].append({'path': new_path, 'error': str(e)})
    return results


def rename_region(region_id: int, new_name: str):
    """Rename a region of interest and move its PNG views folder. Raises ValueError."""
    return get_db_manager().rename_region(region_id, new_name, relocate_views=relocate_region_views_directory)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m astropipes.workflows.archive <old_target> <new_target>")
        sys.exit(1)
    old_target, new_target = sys.argv[1], sys.argv[2]
    summary = rename_target(old_target, new_target)

    if summary['folder_renamed']:
        print(f"Folder renamed successfully from '{old_target}' to '{new_target}'")
    elif summary['folder_error']:
        print(f"Folder rename failed: {summary['folder_error']}")
        sys.exit(1)

    print(f"Updated {summary['files_updated']} files and database records.")
    if summary['errors']:
        print("File update errors:")
        for err in summary['errors']:
            print(f"  {err['path']}: {err['error']}")
    else:
        print("All files processed successfully!")
