import sys
import os
import shutil
from pathlib import Path
from lib.db.manager import get_db_manager
from lib.db.models import FitsFile, Run
from lib.fits import set_fits_header_value
from lib.db.scan import normalize_object_name, rescan_single_file
from sqlalchemy.orm import Session
import config

def rename_target_folder(old_target: str, new_target: str) -> dict:
    """
    Rename the target folder in the data directory.
    Args:
        old_target: The current (old) target name
        new_target: The new target name to set
    Returns:
        dict: Summary of the folder operation
    """
    results = {
        'folder_renamed': False,
        'old_path': None,
        'new_path': None,
        'error': None
    }
    
    try:
        # Construct the old and new folder paths
        old_path = Path(config.DATA_PATH) / old_target
        new_path = Path(config.DATA_PATH) / new_target
        
        # Check if old folder exists
        if not old_path.exists():
            results['error'] = f"Old target folder does not exist: {old_path}"
            return results
        
        # Check if new folder already exists
        if new_path.exists():
            results['error'] = f"New target folder already exists: {new_path}"
            return results
        
        # Rename the folder
        old_path.rename(new_path)
        
        results['folder_renamed'] = True
        results['old_path'] = str(old_path)
        results['new_path'] = str(new_path)
        
    except Exception as e:
        results['error'] = str(e)
    
    return results

def rename_target_across_database(old_target: str, new_target: str, commit: bool = True):
    """
    Rename a target across the database, FITS files, and folder structure.
    Args:
        old_target: The current (old) target name
        new_target: The new target name to set
        commit: Whether to commit DB changes (default True)
    Returns:
        dict: Summary of the operation
    """
    db = get_db_manager()
    session: Session = db.get_session()
    old_norm = normalize_object_name(old_target)
    new_norm = normalize_object_name(new_target)
    results = {
        'files_updated': 0,
        'errors': [],
        'files': [],
        'folder_renamed': False,
        'folder_error': None
    }
    
    try:
        # First, rename the folder
        folder_result = rename_target_folder(old_target, new_target)
        if folder_result['error']:
            results['folder_error'] = folder_result['error']
            return results  # Don't proceed if folder rename failed
        else:
            results['folder_renamed'] = folder_result['folder_renamed']
        
        # Get all files for this target before updating paths
        files = session.query(FitsFile).filter(FitsFile.target == old_norm).all()
        
        # Collect run IDs that will need maintenance after target change
        runs_to_maintain = set()
        
        # Update file paths in the database to reflect the new folder name
        for fits_file in files:
            try:
                # Update the file path to use the new target name
                old_path = Path(fits_file.path)
                # Replace the target name in the path: /path/to/old_target/filter/file.fits -> /path/to/new_target/filter/file.fits
                path_parts = old_path.parts
                target_index = path_parts.index(old_target)
                new_path_parts = list(path_parts)
                new_path_parts[target_index] = new_target
                new_path = Path(*new_path_parts)
                
                print(f"Updating path: {old_path} -> {new_path}")  # Debug output
                
                fits_file.path = str(new_path)
                
                # Store old run_id for run maintenance
                if fits_file.run_id:
                    runs_to_maintain.add(fits_file.run_id)
                
                # Update the target field
                fits_file.target = new_norm
                
                # Remove from old run (target changed, so file doesn't belong to that run anymore)
                fits_file.run_id = None
                
                if commit:
                    session.commit()
                
                # Now update the FITS header using the new path
                set_fits_header_value(str(new_path), 'OBJECT', new_norm)
                
                # Rescan the file to update any other metadata
                rescan_result = rescan_single_file(str(new_path))
                results['files_updated'] += 1
                results['files'].append({'path': str(new_path), 'rescan': rescan_result})
                
            except Exception as e:
                session.rollback()
                results['errors'].append({'path': fits_file.path, 'error': str(e)})
        
        # Maintain runs that had files removed (update times or delete if empty)
        # Use a helper function to maintain runs
        from sqlalchemy import func
        for run_id in runs_to_maintain:
            # Check if run still has files
            file_count = session.query(func.count(FitsFile.id)).filter(
                FitsFile.run_id == run_id
            ).scalar()
            
            if file_count == 0:
                # Run is empty, delete it
                run = session.query(Run).filter(Run.id == run_id).first()
                if run:
                    session.delete(run)
            else:
                # Update run times based on remaining files
                result = session.query(
                    func.min(FitsFile.date_obs),
                    func.max(FitsFile.date_obs)
                ).filter(FitsFile.run_id == run_id).first()
                
                if result and result[0] and result[1]:
                    run = session.query(Run).filter(Run.id == run_id).first()
                    if run:
                        run.start_time = result[0]
                        run.end_time = result[1]
        
        if commit:
            session.commit()
    finally:
        session.close()
    return results

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m lib.db.edit <old_target> <new_target>")
        sys.exit(1)
    old_target, new_target = sys.argv[1], sys.argv[2]
    summary = rename_target_across_database(old_target, new_target)
    
    # Show folder renaming results
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