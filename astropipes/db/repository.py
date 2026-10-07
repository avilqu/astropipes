"""
Library database access: DatabaseManager queries and updates, and the shared instance
returned by get_db_manager(). No filesystem changes happen here (see astropipes.workflows).
"""

from sqlalchemy import func
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from .engine import create_database_engine
from .models import (
    FitsFile,
    Source,
    CalibrationMaster,
    Run,
    MPCLog,
    FollowUpFilter,
    RegionOfInterest,
    RegionView,
)
from astropipes.core.timefmt import to_display_time

class DatabaseManager:
    """Manages database connections and operations for astro-pipelines."""
    
    def __init__(self, db_path: str = None):
        """Initialize the database manager.
        
        Args:
            db_path: Path to the SQLite database file. If None, uses default location from config.
        """
        if db_path is None:
            # Use default location from config
            from astropipes.config import settings
            db_path = settings.DATABASE_PATH
        
        self.db_path = db_path
        self.engine = None
        self.SessionLocal = None
        self._initialize_database()
    
    def _initialize_database(self):
        """Create the engine (tables and migrations included) and the session factory."""
        try:
            self.engine = create_database_engine(self.db_path)
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
            print(f"Database initialized at: {self.db_path}")
        except SQLAlchemyError as e:
            print(f"Error initializing database: {e}")
            raise

    def refresh(self):
        """Dispose pooled connections and re-create the engine so reads see changes made by
        other threads or processes."""
        if self.engine:
            self.engine.dispose()
        self._initialize_database()

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

    def follow_up_set_filters(self, target_name: str, filter_names: list) -> None:
        """Replace follow-up filter selections for a target."""
        session = self.get_session()
        try:
            session.query(FollowUpFilter).filter(FollowUpFilter.target_name == target_name).delete()
            for fn in filter_names:
                session.add(FollowUpFilter(target_name=target_name, filter_name=fn))
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            raise
        finally:
            session.close()

    def rename_target_records(self, old_target: str, new_target: str, moved_folders=()):
        """Rename a target in the database, after its folders were renamed on disk.

        moved_folders: (old_dir, new_dir) pairs; stored file and region-view paths under old_dir
        are rewritten to new_dir.

        Updates FitsFile target (and paths), detaching files from their runs (runs are per target;
        the old runs are updated or deleted), follow-up flags, region targets and region-view paths.
        Raises ValueError, without changing anything, if new_target already has a region with the
        same name as one of old_target's.

        Returns the list of (old_path, new_path) for the target's files.
        """
        import os

        def moved(path):
            for old_dir, new_dir in moved_folders:
                old_dir, new_dir = str(old_dir), str(new_dir)
                if path and (path == old_dir or path.startswith(old_dir + os.sep)):
                    return new_dir + path[len(old_dir):]
            return path

        session = self.get_session()
        try:
            regions = session.query(RegionOfInterest).filter(RegionOfInterest.target == old_target).all()
            taken = {r.name for r in session.query(RegionOfInterest).filter(RegionOfInterest.target == new_target)}
            clashes = sorted(r.name for r in regions if r.name in taken)
            if clashes:
                raise ValueError(f"Target '{new_target}' already has region(s) named: {', '.join(clashes)}")

            for row in session.query(FollowUpFilter).filter(FollowUpFilter.target_name == old_target).all():
                session.delete(row)
                session.add(FollowUpFilter(target_name=new_target, filter_name=row.filter_name))

            for region in regions:
                region.target = new_target
            for view in session.query(RegionView).all():
                view.png_path = moved(view.png_path)
                view.stack_fits_path = moved(view.stack_fits_path)

            renamed = []
            runs_to_maintain = set()
            for fits_file in session.query(FitsFile).filter(FitsFile.target == old_target).all():
                new_path = moved(fits_file.path)
                renamed.append((fits_file.path, new_path))
                fits_file.path = new_path
                fits_file.target = new_target
                if fits_file.run_id:
                    runs_to_maintain.add(fits_file.run_id)
                fits_file.run_id = None

            session.flush()
            for run_id in runs_to_maintain:
                self._maintain_run_after_file_removal(session, run_id)
            session.commit()
            return renamed
        except SQLAlchemyError:
            session.rollback()
            raise
        finally:
            session.close()

    def follow_up_clear(self, target_name: str) -> None:
        """Remove follow-up flag and stored filters for a target."""
        session = self.get_session()
        try:
            session.query(FollowUpFilter).filter(FollowUpFilter.target_name == target_name).delete()
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            raise
        finally:
            session.close()

    def follow_up_get_targets(self) -> list:
        """Distinct target names that have at least one follow-up filter row."""
        session = self.get_session()
        try:
            rows = (
                session.query(FollowUpFilter.target_name)
                .distinct()
                .order_by(FollowUpFilter.target_name)
                .all()
            )
            return [r[0] for r in rows]
        finally:
            session.close()

    def follow_up_get_filters(self, target_name: str) -> list:
        """Filter names selected for follow-up for this target."""
        session = self.get_session()
        try:
            rows = (
                session.query(FollowUpFilter.filter_name)
                .filter(FollowUpFilter.target_name == target_name)
                .order_by(FollowUpFilter.filter_name)
                .all()
            )
            return [r[0] for r in rows]
        finally:
            session.close()

    def follow_up_is_flagged(self, target_name: str) -> bool:
        session = self.get_session()
        try:
            n = session.query(FollowUpFilter).filter(FollowUpFilter.target_name == target_name).count()
            return n > 0
        finally:
            session.close()

    def add_region_of_interest(
        self,
        name: str,
        target: str,
        ra_min: float,
        ra_max: float,
        dec_min: float,
        dec_max: float,
        defined_from_path: str = None,
        created_at=None,
    ) -> RegionOfInterest:
        from datetime import datetime

        session = self.get_session()
        try:
            region = RegionOfInterest(
                name=name,
                target=target,
                ra_min=ra_min,
                ra_max=ra_max,
                dec_min=dec_min,
                dec_max=dec_max,
                defined_from_path=defined_from_path,
                created_at=created_at or datetime.utcnow(),
            )
            session.add(region)
            session.commit()
            session.refresh(region)
            return region
        except SQLAlchemyError as e:
            session.rollback()
            raise
        finally:
            session.close()

    def get_all_regions(self) -> list:
        session = self.get_session()
        try:
            return (
                session.query(RegionOfInterest)
                .order_by(RegionOfInterest.target, RegionOfInterest.name)
                .all()
            )
        finally:
            session.close()

    def get_region_by_id(self, region_id: int):
        session = self.get_session()
        try:
            return session.query(RegionOfInterest).filter(RegionOfInterest.id == region_id).first()
        finally:
            session.close()

    def delete_region(self, region_id: int) -> bool:
        session = self.get_session()
        try:
            region = session.query(RegionOfInterest).filter(RegionOfInterest.id == region_id).first()
            if not region:
                return False
            session.delete(region)
            session.commit()
            return True
        except SQLAlchemyError:
            session.rollback()
            raise
        finally:
            session.close()

    def rename_region(self, region_id: int, new_name: str, relocate_views=None) -> RegionOfInterest:
        """Rename a region. relocate_views(target, old_name, new_name, views), if given, is called
        before committing so it can move the view files and update the views' png_path."""
        new_name = (new_name or "").strip()
        if not new_name:
            raise ValueError("Region name cannot be empty.")
        session = self.get_session()
        try:
            region = (
                session.query(RegionOfInterest)
                .filter(RegionOfInterest.id == region_id)
                .first()
            )
            if not region:
                raise ValueError("Region not found.")
            old_name = region.name
            if old_name == new_name:
                return region
            conflict = (
                session.query(RegionOfInterest)
                .filter(
                    RegionOfInterest.target == region.target,
                    RegionOfInterest.name == new_name,
                    RegionOfInterest.id != region_id,
                )
                .first()
            )
            if conflict:
                raise ValueError(
                    f"A region named '{new_name}' already exists for target '{region.target}'."
                )
            views = (
                session.query(RegionView)
                .filter(RegionView.region_id == region_id)
                .all()
            )
            if relocate_views:
                relocate_views(region.target, old_name, new_name, views)
            region.name = new_name
            session.commit()
            session.refresh(region)
            return region
        except SQLAlchemyError as e:
            session.rollback()
            raise ValueError(f"Could not rename region: {e}") from e
        finally:
            session.close()

    def add_or_update_region_view(
        self,
        region_id: int,
        stack_fits_path: str,
        png_path: str,
        date_obs=None,
        display_min=None,
        display_max=None,
    ) -> RegionView:
        session = self.get_session()
        try:
            existing = (
                session.query(RegionView)
                .filter(
                    RegionView.region_id == region_id,
                    RegionView.stack_fits_path == stack_fits_path,
                )
                .first()
            )
            if existing:
                existing.png_path = png_path
                existing.date_obs = date_obs
                existing.display_min = display_min
                existing.display_max = display_max
                session.commit()
                session.refresh(existing)
                return existing
            view = RegionView(
                region_id=region_id,
                stack_fits_path=stack_fits_path,
                png_path=png_path,
                date_obs=date_obs,
                display_min=display_min,
                display_max=display_max,
            )
            session.add(view)
            session.commit()
            session.refresh(view)
            return view
        except SQLAlchemyError:
            session.rollback()
            raise
        finally:
            session.close()

    def get_region_views(self, region_id: int) -> list:
        session = self.get_session()
        try:
            return (
                session.query(RegionView)
                .filter(RegionView.region_id == region_id)
                .order_by(RegionView.date_obs.desc())
                .all()
            )
        finally:
            session.close()

    def delete_region_view(self, view_id: int) -> bool:
        session = self.get_session()
        try:
            view = session.query(RegionView).filter(RegionView.id == view_id).first()
            if not view:
                return False
            session.delete(view)
            session.commit()
            return True
        except SQLAlchemyError:
            session.rollback()
            raise
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