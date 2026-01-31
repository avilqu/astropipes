import os
import json
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from .models import Base, FitsFile, Source, CalibrationMaster, Run, MPCLog
from config import to_display_time

class DatabaseManager:
    """Manages database connections and operations for astro-pipelines."""
    
    def __init__(self, db_path: str = None):
        """Initialize the database manager.
        
        Args:
            db_path: Path to the SQLite database file. If None, uses default location from config.
        """
        if db_path is None:
            # Use default location from config
            import config
            db_path = config.DATABASE_PATH
        
        self.db_path = db_path
        self.engine = None
        self.SessionLocal = None
        self._initialize_database()
    
    def _initialize_database(self):
        """Initialize the database engine and create tables if they don't exist."""
        try:
            # Create SQLite engine
            self.engine = create_engine(f'sqlite:///{self.db_path}', echo=False)
            
            # Create all tables
            Base.metadata.create_all(self.engine)
            
            # Run migrations for existing databases
            self._migrate_database()
            
            # Create session factory
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
            
            print(f"Database initialized at: {self.db_path}")
            
        except SQLAlchemyError as e:
            print(f"Error initializing database: {e}")
            raise
    
    def _migrate_database(self):
        """Migrate existing database schema to add new columns and tables."""
        from sqlalchemy import inspect, text
        
        inspector = inspect(self.engine)
        existing_tables = inspector.get_table_names()
        
        # Check if runs table exists
        if 'runs' not in existing_tables:
            # Create runs table using the model definition
            Run.__table__.create(self.engine, checkfirst=True)
            print("Created 'runs' table")
        
        # Check if fits_files.run_id column exists
        if 'fits_files' in existing_tables:
            columns = [col['name'] for col in inspector.get_columns('fits_files')]
            if 'run_id' not in columns:
                # Add run_id column to fits_files table
                # Note: SQLite doesn't support adding foreign key constraints via ALTER TABLE,
                # but the column will work for our purposes. The relationship is handled by SQLAlchemy.
                with self.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE fits_files ADD COLUMN run_id INTEGER"))
                    conn.commit()
                print("Added 'run_id' column to 'fits_files' table")
        
        # Check if mpc_log table exists
        if 'mpc_log' not in existing_tables:
            # Create mpc_log table using the model definition
            MPCLog.__table__.create(self.engine, checkfirst=True)
            print("Created 'mpc_log' table")
        
        # Check if runs.badges column exists
        if 'runs' in existing_tables:
            columns = [col['name'] for col in inspector.get_columns('runs')]
            if 'badges' not in columns:
                # Add badges column to runs table
                with self.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE runs ADD COLUMN badges TEXT"))
                    conn.commit()
                print("Added 'badges' column to 'runs' table")
    
    def get_session(self) -> Session:
        """Get a new database session.
        
        Returns:
            SQLAlchemy session object
        """
        if self.SessionLocal is None:
            raise RuntimeError("Database not initialized")
        return self.SessionLocal()
    
    def add_fits_file(self, fits_data: dict) -> FitsFile:
        """Add a new FITS file to the database.
        
        Args:
            fits_data: Dictionary containing FITS file data
            
        Returns:
            The created FitsFile object
        """
        session = self.get_session()
        try:
            # Create new FitsFile object
            fits_file = FitsFile(**fits_data)
            session.add(fits_file)
            session.commit()
            session.refresh(fits_file)
            return fits_file
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error adding FITS file: {e}")
            raise
        finally:
            session.close()
    
    def get_fits_file_by_path(self, path: str) -> FitsFile:
        """Get a FITS file by its path.
        
        Args:
            path: File path to search for
            
        Returns:
            FitsFile object if found, None otherwise
        """
        session = self.get_session()
        try:
            return session.query(FitsFile).filter(FitsFile.path == path).first()
        finally:
            session.close()
    
    def get_all_fits_files(self) -> list:
        """Get all FITS files in the database.
        
        Returns:
            List of all FitsFile objects
        """
        session = self.get_session()
        try:
            return session.query(FitsFile).all()
        finally:
            session.close()
    
    def update_fits_file(self, fits_file_id: int, update_data: dict) -> bool:
        """Update an existing FITS file.
        Automatically maintains runs if target or date_obs changes.
        
        Args:
            fits_file_id: ID of the FITS file to update
            update_data: Dictionary containing fields to update
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            fits_file = session.query(FitsFile).filter(FitsFile.id == fits_file_id).first()
            if fits_file:
                # Store old values for run maintenance
                old_run_id = fits_file.run_id
                old_target = fits_file.target
                old_date_obs = fits_file.date_obs
                
                # Update fields
                for key, value in update_data.items():
                    if hasattr(fits_file, key):
                        setattr(fits_file, key, value)
                
                session.commit()
                
                # Maintain runs if target or date_obs changed
                new_target = fits_file.target
                new_date_obs = fits_file.date_obs
                
                # If target changed, remove from old run
                if old_target and new_target and old_target != new_target:
                    if old_run_id:
                        fits_file.run_id = None
                        session.commit()
                        self._maintain_run_after_file_removal(session, old_run_id)
                        session.commit()
                
                # If date_obs changed, update run times
                elif old_run_id and old_date_obs and new_date_obs and old_date_obs != new_date_obs:
                    self._update_run_times(session, old_run_id)
                    session.commit()
                
                return True
            return False
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error updating FITS file: {e}")
            return False
        finally:
            session.close()
    
    def delete_fits_file(self, fits_file_id: int) -> bool:
        """Delete a FITS file and its associated sources.
        Automatically maintains runs (updates times or deletes empty runs).
        
        Args:
            fits_file_id: ID of the FITS file to delete
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            fits_file = session.query(FitsFile).filter(FitsFile.id == fits_file_id).first()
            if fits_file:
                # Store run_id before deletion for cleanup
                run_id = fits_file.run_id
                
                session.delete(fits_file)
                session.commit()
                
                # Maintain the run after file deletion
                if run_id:
                    self._maintain_run_after_file_removal(session, run_id)
                    session.commit()
                
                return True
            return False
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error deleting FITS file: {e}")
            return False
        finally:
            session.close()
    
    def add_sources_to_fits_file(self, fits_file_id: int, sources_data: list) -> bool:
        """Add sources to a FITS file.
        
        Args:
            fits_file_id: ID of the FITS file
            sources_data: List of dictionaries containing source data
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            fits_file = session.query(FitsFile).filter(FitsFile.id == fits_file_id).first()
            if not fits_file:
                return False
            
            for source_data in sources_data:
                source_data['fits_file_id'] = fits_file_id
                source = Source(**source_data)
                session.add(source)
            
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error adding sources: {e}")
            return False
        finally:
            session.close()
    
    def get_sources_for_fits_file(self, fits_file_id: int) -> list:
        """Get all sources for a FITS file.
        
        Args:
            fits_file_id: ID of the FITS file
            
        Returns:
            List of Source objects
        """
        session = self.get_session()
        try:
            return session.query(Source).filter(Source.fits_file_id == fits_file_id).all()
        finally:
            session.close()
    
    def get_unique_targets(self) -> list:
        """Get all unique targets from the database."""
        session = self.get_session()
        try:
            return [row[0] for row in session.query(FitsFile.target).distinct().order_by(FitsFile.target).all() if row[0]]
        finally:
            session.close()

    def get_unique_targets_by_last_image(self) -> list:
        """Get unique targets ordered by last image taken (most recent first)."""
        session = self.get_session()
        try:
            rows = (
                session.query(FitsFile.target)
                .filter(FitsFile.target.isnot(None), FitsFile.target != '')
                .group_by(FitsFile.target)
                .order_by(func.max(FitsFile.date_obs).desc())
                .all()
            )
            return [row[0] for row in rows]
        finally:
            session.close()

    def get_unique_dates(self) -> list:
        """Get all unique observation dates (YYYY-MM-DD) from the database."""
        session = self.get_session()
        try:
            # Extract date part from datetime, return as string
            dates = session.query(FitsFile.date_obs).distinct().all()
            date_strs = set()
            for (dt,) in dates:
                if dt:
                    date_strs.add(dt.strftime('%Y-%m-%d'))
            return sorted(date_strs)
        finally:
            session.close()

    def get_unique_local_dates(self) -> list:
        """Get all unique observation dates (YYYY-MM-DD) in local time from the database."""
        session = self.get_session()
        try:
            dates = session.query(FitsFile.date_obs).distinct().all()
            date_strs = set()
            for (dt,) in dates:
                if dt:
                    dt_disp = to_display_time(dt)
                    date_strs.add(dt_disp.strftime('%Y-%m-%d'))
            return sorted(date_strs)
        finally:
            session.close()

    def get_file_count_by_target(self, target: str) -> int:
        """Get the number of files for a specific target."""
        session = self.get_session()
        try:
            return session.query(FitsFile).filter(FitsFile.target == target).count()
        finally:
            session.close()

    def get_file_count_by_date(self, date: str) -> int:
        """Get the number of files for a specific date."""
        session = self.get_session()
        try:
            # Convert date string to datetime for comparison
            from datetime import datetime, timedelta
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            next_date = date_obj + timedelta(days=1)
            return session.query(FitsFile).filter(
                FitsFile.date_obs >= date_obj,
                FitsFile.date_obs < next_date
            ).count()
        finally:
            session.close()

    def get_file_count_by_local_date(self, date: str) -> int:
        """Get the number of files for a specific local date (YYYY-MM-DD)."""
        session = self.get_session()
        try:
            from datetime import datetime, timedelta
            files = session.query(FitsFile.date_obs).all()
            count = 0
            for (dt,) in files:
                if dt:
                    dt_disp = to_display_time(dt)
                    if dt_disp.strftime('%Y-%m-%d') == date:
                        count += 1
            return count
        finally:
            session.close()

    def get_total_file_count(self) -> int:
        """Get the total number of files in the database."""
        session = self.get_session()
        try:
            return session.query(FitsFile).count()
        finally:
            session.close()

    def get_calibration_file_count(self, frame_type: str) -> int:
        """Get the number of calibration files of a specific type."""
        session = self.get_session()
        try:
            return session.query(CalibrationMaster).filter(CalibrationMaster.frame == frame_type).count()
        finally:
            session.close()
    
    def add_calibration_master(self, master_data: dict) -> CalibrationMaster:
        """Add a new CalibrationMaster to the database.
        Args:
            master_data: Dictionary containing calibration master data
        Returns:
            The created CalibrationMaster object
        """
        session = self.get_session()
        try:
            master = CalibrationMaster(**master_data)
            session.add(master)
            session.commit()
            session.refresh(master)
            return master
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error adding CalibrationMaster: {e}")
            raise
        finally:
            session.close()

    def get_calibration_master_by_path(self, path: str) -> CalibrationMaster:
        """Get a CalibrationMaster by its path.
        Args:
            path: File path to search for
        Returns:
            CalibrationMaster object if found, None otherwise
        """
        session = self.get_session()
        try:
            return session.query(CalibrationMaster).filter(CalibrationMaster.path == path).first()
        finally:
            session.close()

    def get_files_by_target(self, target: str) -> list:
        """Get all FITS files for a specific target.
        
        Args:
            target: Target name to search for
            
        Returns:
            List of FitsFile objects for the target
        """
        session = self.get_session()
        try:
            return session.query(FitsFile).filter(FitsFile.target == target).all()
        finally:
            session.close()

    def get_files_by_date(self, date: str) -> list:
        """Get all FITS files for a specific date (YYYY-MM-DD).
        
        Args:
            date: Date string in YYYY-MM-DD format
            
        Returns:
            List of FitsFile objects for the date
        """
        session = self.get_session()
        try:
            from datetime import datetime
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            next_date = datetime.strptime(date, '%Y-%m-%d').replace(day=date_obj.day + 1)
            return session.query(FitsFile).filter(
                FitsFile.date_obs >= date_obj,
                FitsFile.date_obs < next_date
            ).all()
        finally:
            session.close()

    def get_files_by_local_date(self, date: str) -> list:
        """Get all FITS files for a specific local date (YYYY-MM-DD).
        
        Args:
            date: Date string in YYYY-MM-DD format (local time)
            
        Returns:
            List of FitsFile objects for the date
        """
        session = self.get_session()
        try:
            files = session.query(FitsFile).all()
            matching_files = []
            for file in files:
                if file.date_obs:
                    dt_disp = to_display_time(file.date_obs)
                    if dt_disp.strftime('%Y-%m-%d') == date:
                        matching_files.append(file)
            return matching_files
        finally:
            session.close()

    def move_target_to_archive(self, target: str, archive_path: str) -> dict:
        """Move all files for a target to the archive and remove from database.
        
        Args:
            target: Target name to archive
            archive_path: Base path for the archive directory
            
        Returns:
            Dictionary with results: {'files_moved': int, 'files_removed': int, 'errors': list}
        """
        import os
        import shutil
        from pathlib import Path
        
        session = self.get_session()
        results = {'files_moved': 0, 'files_removed': 0, 'errors': []}
        
        try:
            # Get all files for this target
            files = session.query(FitsFile).filter(FitsFile.target == target).all()
            
            print(f"Found {len(files)} files in database for target '{target}'")
            for i, f in enumerate(files):
                print(f"  {i+1}. {f.path} (exists: {Path(f.path).exists()})")
            
            if not files:
                print("No files found for target, nothing to archive")
                return results
            
            # Create archive directory structure
            archive_base = Path(archive_path)
            archive_base.mkdir(parents=True, exist_ok=True)
            
            # Track directories that will become empty
            directories_to_cleanup = set()
            
            for fits_file in files:
                try:
                    # Get the original file path
                    original_path = Path(fits_file.path)
                    print(f"Processing file: {fits_file.path}")
                    print(f"  Original path: {original_path}")
                    print(f"  Path exists: {original_path.exists()}")
                    print(f"  Path is file: {original_path.is_file()}")
                    print(f"  Path is dir: {original_path.is_dir()}")
                    
                    if not original_path.exists():
                        print(f"  File doesn't exist, removing from database only")
                        # File doesn't exist, just remove from database
                        session.delete(fits_file)
                        results['files_removed'] += 1
                        continue
                    
                    # Determine archive path (maintain directory structure relative to DATA_PATH)
                    import config
                    data_path = Path(config.DATA_PATH)
                    try:
                        relative_path = original_path.relative_to(data_path)
                        # Track the directory for cleanup
                        directories_to_cleanup.add(original_path.parent)
                    except ValueError:
                        # File is not under DATA_PATH, use filename only
                        relative_path = original_path.name
                    
                    archive_file_path = archive_base / relative_path
                    archive_file_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Move the file to archive
                    print(f"Moving file: {original_path} -> {archive_file_path}")
                    shutil.move(str(original_path), str(archive_file_path))
                    
                    # Verify the move was successful
                    if original_path.exists():
                        print(f"ERROR: File still exists at original location: {original_path}")
                    else:
                        print(f"SUCCESS: File moved successfully, original location no longer exists")
                    
                    # Remove from database
                    session.delete(fits_file)
                    
                    results['files_moved'] += 1
                    results['files_removed'] += 1
                    
                except Exception as e:
                    error_info = {
                        'path': str(fits_file.path),
                        'error': str(e)
                    }
                    results['errors'].append(error_info)
            
            # Clean up empty directories after moving files
            import config
            data_path = Path(config.DATA_PATH)
            
            # Try different variations of the target name to find the actual directory
            target_variations = [
                target,  # Original target name (e.g., "NGC 247")
                target.replace(" ", "_"),  # Replace spaces with underscores (e.g., "NGC_247")
                target.replace("_", " ")   # Replace underscores with spaces (e.g., "NGC_247" -> "NGC 247")
            ]
            
            # Remove duplicates while preserving order
            target_variations = list(dict.fromkeys(target_variations))
            
            print(f"\n=== DIRECTORY CLEANUP START ===")
            print(f"Cleaning up empty directories for target: {target}")
            print(f"Target variations to check: {target_variations}")
            
            # Find the actual target directory that exists on disk
            actual_target_dir = None
            for target_variant in target_variations:
                test_dir = data_path / target_variant
                if test_dir.exists():
                    actual_target_dir = test_dir
                    print(f"Found actual target directory: {actual_target_dir}")
                    break
            
            # If no directory found by name, try to find it by looking at where the files actually are
            if actual_target_dir is None:
                print(f"No target directory found by name, checking file locations...")
                
                # Look at the actual file paths to see where they are located
                if files:
                    file_dirs = set()
                    for fits_file in files:
                        if fits_file.path:
                            file_path = Path(fits_file.path)
                            if file_path.exists():
                                # Get the directory containing this file
                                file_dir = file_path.parent
                                # Check if this directory is under the data path
                                try:
                                    relative_path = file_dir.relative_to(data_path)
                                    # The first part of the relative path should be the target directory
                                    if len(relative_path.parts) > 0:
                                        potential_target_dir = data_path / relative_path.parts[0]
                                        if potential_target_dir.exists():
                                            file_dirs.add(potential_target_dir)
                                except ValueError:
                                    pass
                    
                    if file_dirs:
                        print(f"Found potential target directories from file locations: {[str(d) for d in file_dirs]}")
                        # Use the first one found
                        actual_target_dir = list(file_dirs)[0]
                        print(f"Using target directory from file locations: {actual_target_dir}")
                    else:
                        print(f"Could not determine target directory from file locations")
            
            if actual_target_dir is None:
                print(f"Warning: No target directory found for any variation: {target_variations}")
                print(f"Data path: {data_path}")
                # List what's actually in the data directory
                if data_path.exists():
                    print("Contents of data directory:")
                    for item in data_path.iterdir():
                        if item.is_dir():
                            print(f"  DIR: {item.name}")
                return results
            
            target_dir = actual_target_dir
            print(f"Using target directory: {target_dir}")
            print(f"Target directory exists: {target_dir.exists()}")
            
            # Show the directory structure before cleanup
            if target_dir.exists():
                print(f"\nDirectory structure before cleanup:")
                for item in target_dir.rglob('*'):
                    if item.is_file():
                        print(f"  FILE: {item}")
                    elif item.is_dir():
                        print(f"  DIR:  {item}")
            
            if target_dir.exists():
                print("Target directory exists, checking contents...")
                
                # Check if there are any remaining files by doing a fresh scan
                remaining_files = []
                remaining_dirs = []
                
                print("Scanning target directory contents:")
                for item in target_dir.iterdir():
                    if item.is_file():
                        remaining_files.append(item)
                        print(f"  FILE: {item}")
                    elif item.is_dir():
                        remaining_dirs.append(item)
                        print(f"  DIR:  {item}")
                        # Check subdirectory contents
                        for subitem in item.iterdir():
                            if subitem.is_file():
                                print(f"    SUBFILE: {subitem}")
                            elif subitem.is_dir():
                                print(f"    SUBDIR:  {subitem}")
                
                print(f"Found {len(remaining_files)} remaining files and {len(remaining_dirs)} directories")
                
                if remaining_files:
                    print("Warning: Files still exist, cannot safely clean up directories:")
                    for f in remaining_files:
                        print(f"  {f}")
                else:
                    print("No files remaining - proceeding with directory cleanup")
                    
                    # Remove all subdirectories (deepest first)
                    if remaining_dirs:
                        # Sort by depth for safe removal
                        remaining_dirs.sort(key=lambda x: len(list(x.rglob('*'))), reverse=True)
                        
                        print(f"Removing {len(remaining_dirs)} subdirectories...")
                        for subdir in remaining_dirs:
                            try:
                                if subdir.exists():
                                    # Double-check it's empty before removing
                                    subdir_contents = list(subdir.iterdir())
                                    if not subdir_contents:
                                        subdir.rmdir()
                                        print(f"  Removed empty subdirectory: {subdir}")
                                    else:
                                        print(f"  Subdirectory {subdir} has {len(subdir_contents)} items, skipping")
                                        for item in subdir_contents:
                                            print(f"    Item: {item}")
                            except Exception as e:
                                print(f"  Error removing subdirectory {subdir}: {e}")
                                results['errors'].append({
                                    'path': f'cleanup_subdirectory_{subdir}',
                                    'error': f'Failed to remove subdirectory {subdir}: {str(e)}'
                                })
                    else:
                        print("No subdirectories to remove")
                    
                    # Now try to remove the target directory itself
                    try:
                        if target_dir.exists():
                            # Final check - make sure it's really empty
                            final_contents = list(target_dir.iterdir())
                            if not final_contents:
                                target_dir.rmdir()
                                print(f"Successfully removed target directory: {target_dir}")
                            else:
                                print(f"Target directory {target_dir} still has {len(final_contents)} items, cannot remove:")
                                for item in final_contents:
                                    print(f"  {item}")
                        else:
                            print(f"Target directory {target_dir} no longer exists")
                    except Exception as e:
                        print(f"Error removing target directory {target_dir}: {e}")
                        results['errors'].append({
                            'path': f'cleanup_target_directory_{target}',
                            'error': f'Failed to remove target directory {target_dir}: {str(e)}'
                        })
            else:
                print(f"Target directory {target_dir} does not exist")
            
            # Commit all changes
            session.commit()
            
        except Exception as e:
            session.rollback()
            results['errors'].append({
                'path': 'database_operation',
                'error': f'Database error: {str(e)}'
            })
        finally:
            session.close()
        
        return results
    
    def create_or_get_run(self, target: str, start_time, end_time, fits_file_ids: list = None) -> Run:
        """Create a new run or get existing run if files already belong to one.
        
        Args:
            target: Target name
            start_time: Start time (datetime)
            end_time: End time (datetime)
            fits_file_ids: Optional list of FITS file IDs to associate with the run
            
        Returns:
            Run object
        """
        session = self.get_session()
        try:
            # Check if any of the files already belong to a run
            if fits_file_ids:
                existing_run = session.query(Run).join(FitsFile).filter(
                    FitsFile.id.in_(fits_file_ids)
                ).first()
                if existing_run:
                    # Update times if needed
                    if start_time < existing_run.start_time:
                        existing_run.start_time = start_time
                    if end_time > existing_run.end_time:
                        existing_run.end_time = end_time
                    session.commit()
                    session.refresh(existing_run)
                    return existing_run
            
            # Create new run
            run = Run(
                target=target,
                start_time=start_time,
                end_time=end_time
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            
            # Associate files with the run
            if fits_file_ids:
                for file_id in fits_file_ids:
                    fits_file = session.query(FitsFile).filter(FitsFile.id == file_id).first()
                    if fits_file:
                        fits_file.run_id = run.id
                session.commit()
            
            return run
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error creating/getting run: {e}")
            raise
        finally:
            session.close()
    
    def get_run_by_id(self, run_id: int) -> Run:
        """Get a run by its ID.
        
        Args:
            run_id: Run ID
            
        Returns:
            Run object if found, None otherwise
        """
        session = self.get_session()
        try:
            return session.query(Run).filter(Run.id == run_id).first()
        finally:
            session.close()
    
    def get_runs_for_files(self, fits_file_ids: list) -> dict:
        """Get run information for a list of FITS file IDs.
        
        Args:
            fits_file_ids: List of FITS file IDs
            
        Returns:
            Dictionary mapping file_id -> Run object (or None)
        """
        session = self.get_session()
        try:
            files = session.query(FitsFile).filter(FitsFile.id.in_(fits_file_ids)).all()
            result = {}
            for file in files:
                result[file.id] = file.run
            return result
        finally:
            session.close()
    
    def update_run_comment(self, run_id: int, comment: str) -> bool:
        """Update the comment for a run.
        
        Args:
            run_id: Run ID
            comment: Comment text (can be None to clear)
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            run = session.query(Run).filter(Run.id == run_id).first()
            if run:
                run.comment = comment
                session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error updating run comment: {e}")
            return False
        finally:
            session.close()
    
    def add_run_badge(self, run_id: int, badge: str) -> bool:
        """Add a badge to a run.
        
        Args:
            run_id: Run ID
            badge: Badge name to add (e.g., "mpc")
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            run = session.query(Run).filter(Run.id == run_id).first()
            if run:
                current_badges = run.badges or ""
                badges_list = [b.strip() for b in current_badges.split(",") if b.strip()]
                if badge not in badges_list:
                    badges_list.append(badge)
                    run.badges = ",".join(badges_list)
                    session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error adding run badge: {e}")
            return False
        finally:
            session.close()
    
    def clear_run_badges(self, run_id: int) -> bool:
        """Clear all badges from a run.
        
        Args:
            run_id: Run ID
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            run = session.query(Run).filter(Run.id == run_id).first()
            if run:
                run.badges = None
                session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error clearing run badges: {e}")
            return False
        finally:
            session.close()
    
    def assign_files_to_run(self, run_id: int, fits_file_ids: list) -> bool:
        """Assign FITS files to a run.
        
        Args:
            run_id: Run ID
            fits_file_ids: List of FITS file IDs to assign
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            run = session.query(Run).filter(Run.id == run_id).first()
            if not run:
                return False
            
            for file_id in fits_file_ids:
                fits_file = session.query(FitsFile).filter(FitsFile.id == file_id).first()
                if fits_file:
                    fits_file.run_id = run.id
                    # Update run times if needed
                    if fits_file.date_obs:
                        if fits_file.date_obs < run.start_time:
                            run.start_time = fits_file.date_obs
                        if fits_file.date_obs > run.end_time:
                            run.end_time = fits_file.date_obs
            
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error assigning files to run: {e}")
            return False
        finally:
            session.close()
    
    def _maintain_run_after_file_removal(self, session, run_id: int):
        """Maintain a run after a file is removed from it.
        Updates run times or deletes the run if it's empty.
        
        Args:
            session: Database session
            run_id: ID of the run to maintain
        """
        from sqlalchemy import func
        
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
            self._update_run_times(session, run_id)
    
    def _update_run_times(self, session, run_id: int):
        """Update start_time and end_time for a run based on its files.
        
        Args:
            session: Database session
            run_id: ID of the run to update
        """
        from sqlalchemy import func
        
        # Get min and max date_obs from files in this run
        result = session.query(
            func.min(FitsFile.date_obs),
            func.max(FitsFile.date_obs)
        ).filter(FitsFile.run_id == run_id).first()
        
        if result and result[0] and result[1]:
            run = session.query(Run).filter(Run.id == run_id).first()
            if run:
                run.start_time = result[0]
                run.end_time = result[1]
    
    def add_mpc_log_entry(self, mpc_data: dict) -> MPCLog:
        """Add a new MPC log entry to the database.
        
        Args:
            mpc_data: Dictionary containing MPC log data with keys:
                - observation_date: DateTime (start of observation)
                - target_name: str
                - ra_center: float (degrees)
                - dec_center: float (degrees)
                - num_images: int
                - single_exposure: float (seconds)
                - total_exposure: float (seconds)
                - magnitude: float
                - motion: float (arcseconds per minute)
                - status: str ('Found' or 'Not Found')
                - comment: str (optional)
                
        Returns:
            The created MPCLog object
        """
        session = self.get_session()
        try:
            mpc_log = MPCLog(**mpc_data)
            session.add(mpc_log)
            session.commit()
            session.refresh(mpc_log)
            return mpc_log
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error adding MPC log entry: {e}")
            raise
        finally:
            session.close()
    
    def delete_mpc_log_entry(self, mpc_log_id: int) -> bool:
        """Delete an MPC log entry from the database.
        
        Args:
            mpc_log_id: ID of the MPC log entry to delete
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            mpc_log = session.query(MPCLog).filter(MPCLog.id == mpc_log_id).first()
            if mpc_log:
                session.delete(mpc_log)
                session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error deleting MPC log entry: {e}")
            return False
        finally:
            session.close()
    
    def close(self):
        """Close the database connection."""
        if self.engine:
            self.engine.dispose()

# Global database manager instance
db_manager = None

def get_db_manager(db_path: str = None) -> DatabaseManager:
    """Get the global database manager instance.
    
    Args:
        db_path: Optional custom database path
        
    Returns:
        DatabaseManager instance
    """
    global db_manager
    if db_manager is None:
        db_manager = DatabaseManager(db_path)
    return db_manager 