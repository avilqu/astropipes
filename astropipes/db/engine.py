"""
SQLite engine for the library database: connection settings, table creation and schema migrations.
"""

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.pool import NullPool

from .models import Base, FollowUpFilter, MPCLog, RegionOfInterest, RegionView, Run


def create_database_engine(db_path: str):
    """Engine for the SQLite file at db_path, with tables created and migrations applied."""
    # NullPool: close SQLite connections when sessions close (avoids cross-thread pool reuse).
    # WAL + busy_timeout: reduce "database is locked" when GUI + worker threads access DB.
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        poolclass=NullPool,
        connect_args={"check_same_thread": False, "timeout": 60.0},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_on_connect(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=60000")
        finally:
            cursor.close()

    Base.metadata.create_all(engine)
    migrate_database(engine)
    return engine


def migrate_database(engine):
    """Migrate existing database schema to add new columns and tables."""
    """Migrate existing database schema to add new columns and tables."""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    
    # Check if runs table exists
    if 'runs' not in existing_tables:
        # Create runs table using the model definition
        Run.__table__.create(engine, checkfirst=True)
        print("Created 'runs' table")
    
    # Check if fits_files.run_id column exists
    if 'fits_files' in existing_tables:
        columns = [col['name'] for col in inspector.get_columns('fits_files')]
        if 'run_id' not in columns:
            # Add run_id column to fits_files table
            # Note: SQLite doesn't support adding foreign key constraints via ALTER TABLE,
            # but the column will work for our purposes. The relationship is handled by SQLAlchemy.
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE fits_files ADD COLUMN run_id INTEGER"))
                conn.commit()
            print("Added 'run_id' column to 'fits_files' table")
    
    # Check if mpc_log table exists
    if 'mpc_log' not in existing_tables:
        # Create mpc_log table using the model definition
        MPCLog.__table__.create(engine, checkfirst=True)
        print("Created 'mpc_log' table")
    
    # Check if runs.badges column exists
    if 'runs' in existing_tables:
        columns = [col['name'] for col in inspector.get_columns('runs')]
        if 'badges' not in columns:
            # Add badges column to runs table
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE runs ADD COLUMN badges TEXT"))
                conn.commit()
            print("Added 'badges' column to 'runs' table")

    if 'follow_up_filters' not in existing_tables:
        FollowUpFilter.__table__.create(engine, checkfirst=True)
        print("Created 'follow_up_filters' table")

    if 'fits_files' in existing_tables:
        columns = [col['name'] for col in inspector.get_columns('fits_files')]
        if 'stack_frame_count' not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE fits_files ADD COLUMN stack_frame_count INTEGER"))
                conn.commit()
            print("Added 'stack_frame_count' column to 'fits_files' table")

    if 'regions_of_interest' not in existing_tables:
        RegionOfInterest.__table__.create(engine, checkfirst=True)
        print("Created 'regions_of_interest' table")
    if 'region_views' not in existing_tables:
        RegionView.__table__.create(engine, checkfirst=True)
        print("Created 'region_views' table")
