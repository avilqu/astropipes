from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class FitsFile(Base):
    """Model representing a FITS file in the database."""
    __tablename__ = 'fits_files'
    
    # Primary key
    id = Column(Integer, primary_key=True)
    
    # File information
    path = Column(String, unique=True, nullable=False)
    date_obs = Column(DateTime, nullable=False)
    target = Column(String)
    
    # Image parameters
    filter_name = Column(String)  # Astronomical filter (L, R, G, B, Ha, O, S, V, etc.)
    exptime = Column(Float)
    gain = Column(Float)
    offset = Column(Float)
    focus_position = Column(Integer)  # From FOCUSPOS header
    ccd_temp = Column(Float)
    binning = Column(String)  # e.g., "1x1", "2x2"
    
    # Image dimensions
    size_x = Column(Integer)  # NAXIS1
    size_y = Column(Integer)  # NAXIS2
    
    # Astrometric information
    image_scale = Column(Float)  # arcsec/pixel
    ra_center = Column(Float)    # Right Ascension of center
    dec_center = Column(Float)   # Declination of center
    wcs_type = Column(String)    # WCS solution type
    
    # Full FITS header (stored as JSON for complete flexibility)
    header_json = Column(Text)  # Complete FITS header as JSON
    
    # SIMBAD objects (stored as JSON string for flexibility)
    simbad_objects = Column(Text)  # JSON string of SIMBAD objects
    
    # Source analysis fields
    analysis_status = Column(String, default='not_analyzed')  # 'not_analyzed', 'analyzed', 'failed'
    analysis_date = Column(DateTime)  # When the analysis was performed
    analysis_method = Column(String)  # e.g., 'photutils', 'sextractor', etc.
    hfr = Column(Float)  # Half-Flux Radius (populated after source analysis)
    sources_count = Column(Integer)  # Number of detected sources (populated after source analysis)
    
    # Run association
    run_id = Column(Integer, ForeignKey('runs.id'), nullable=True)
    
    # Relationships
    sources = relationship("Source", back_populates="fits_file", cascade="all, delete-orphan")
    run = relationship("Run", back_populates="fits_files")
    
    def __repr__(self):
        return f"<FitsFile(id={self.id}, path='{self.path}', target='{self.target}')>"

class Source(Base):
    """Model representing a detected source in a FITS file."""
    __tablename__ = 'sources'
    
    # Primary key
    id = Column(Integer, primary_key=True)
    
    # Foreign key to FitsFile
    fits_file_id = Column(Integer, ForeignKey('fits_files.id'), nullable=False)
    
    # Source coordinates (pixel coordinates)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    
    # World coordinates for cross-image matching
    ra = Column(Float)  # Right Ascension (deg)
    dec = Column(Float)  # Declination (deg)
    source_id = Column(String)  # Unique identifier for cross-image matching
    
    # Source properties
    fwhm = Column(Float)
    magnitude = Column(Float)
    flux = Column(Float)
    
    # Additional source metadata (stored as JSON for flexibility)
    source_metadata = Column(Text)  # JSON string for additional properties
    
    # Relationship
    fits_file = relationship("FitsFile", back_populates="sources")
    
    def __repr__(self):
        return f"<Source(id={self.id}, x={self.x}, y={self.y}, magnitude={self.magnitude})>" 

class CalibrationMaster(Base):
    """Model representing a calibration master FITS file (e.g., master dark, flat, bias)."""
    __tablename__ = 'calibration_masters'

    # Primary key
    id = Column(Integer, primary_key=True)

    # File information
    path = Column(String, unique=True, nullable=False)
    date = Column(String, nullable=False)  # Only the date part (YYYY-MM-DD)

    # Calibration frame type
    frame = Column(String, nullable=False)  # 'Dark', 'Flat', or 'Bias'

    # Image parameters
    filter_name = Column(String)  # Astronomical filter (L, R, G, B, Ha, O, S, V, etc.)
    exptime = Column(Float)
    gain = Column(Float)
    offset = Column(Float)
    focus_position = Column(Integer)  # From FOCUSPOS header
    ccd_temp = Column(Float)
    binning = Column(String)  # e.g., "1x1", "2x2"

    # Image dimensions
    size_x = Column(Integer)  # NAXIS1
    size_y = Column(Integer)  # NAXIS2

    # FITS header (stored as JSON)
    header_json = Column(Text)  # Complete FITS header as JSON

    # Number of images integrated to create this master file
    integration_count = Column(Integer)

    def __repr__(self):
        return f"<CalibrationMaster(id={self.id}, path='{self.path}', frame='{self.frame}', date='{self.date}')>"

class Run(Base):
    """Model representing a run - a set of shots of the same target taken around the same time."""
    __tablename__ = 'runs'
    
    # Primary key
    id = Column(Integer, primary_key=True)
    
    # Run information
    target = Column(String, nullable=False)
    start_time = Column(DateTime, nullable=False)  # Earliest file in the run
    end_time = Column(DateTime, nullable=False)    # Latest file in the run
    
    # User-defined comment
    comment = Column(Text, nullable=True)
    
    # Relationships
    # Note: cascade is NOT set to delete-orphan - we want to keep runs even if files are deleted
    # Run cleanup is handled by DatabaseManager methods
    fits_files = relationship("FitsFile", back_populates="run")
    
    def __repr__(self):
        return f"<Run(id={self.id}, target='{self.target}', start_time='{self.start_time}', end_time='{self.end_time}')>" 