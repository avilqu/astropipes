"""
Calibration master generation utilities.

This module contains the active, non-legacy implementation for creating
master bias, dark, and flat frames from raw calibration FITS files.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
from astropy.io import fits
from astropy.stats import mad_std
from astropy.nddata import CCDData
from colorama import Fore, Style
import ccdproc as ccdp

import config
from lib.fits.calibration import CalibrationManager


class CalibrationMasterGenerationError(Exception):
    """Raised when a calibration master cannot be generated."""


@dataclass
class FitsMetadata:
    """Small FitsFile-compatible object used for master lookup."""

    path: str
    binning: str
    filter_name: str
    gain: float
    offset: float
    ccd_temp: float
    exptime: float
    date_obs: datetime


def _parse_date_obs(value: Any) -> datetime:
    if not value:
        return datetime.now()

    date_string = str(value).replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_string.split("+")[0], fmt)
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(date_string).replace(tzinfo=None)
    except ValueError:
        return datetime.now()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _binning_from_header(header: fits.Header) -> str:
    xbin = _safe_int(header.get("XBINNING", 1))
    ybin = _safe_int(header.get("YBINNING", xbin))
    return f"{xbin}x{ybin}"


def _metadata_from_file(file_path: str) -> FitsMetadata:
    header = fits.getheader(file_path, ext=0)
    return FitsMetadata(
        path=file_path,
        binning=_binning_from_header(header),
        filter_name=str(header.get("FILTER", "Unknown")),
        gain=_safe_float(header.get("GAIN")),
        offset=_safe_float(header.get("OFFSET")),
        ccd_temp=_safe_float(header.get("CCD-TEMP")),
        exptime=_safe_float(header.get("EXPTIME")),
        date_obs=_parse_date_obs(header.get("DATE-OBS")),
    )


def _format_date_for_filename(header: fits.Header) -> str:
    return _parse_date_obs(header.get("DATE-OBS")).strftime("%Y%m%d")


def _round_header_value(header: fits.Header, key: str, default: float = 0.0) -> str:
    return str(round(_safe_float(header.get(key), default)))


def _validate_files(files: Iterable[str]) -> List[str]:
    valid_files: List[str] = []
    for file_path in files:
        if not os.path.exists(file_path):
            raise CalibrationMasterGenerationError(f"File not found: {file_path}")
        if not file_path.lower().endswith((".fits", ".fit")):
            raise CalibrationMasterGenerationError(f"File must be a FITS file: {file_path}")
        valid_files.append(file_path)

    if not valid_files:
        raise CalibrationMasterGenerationError("No input files provided")

    return valid_files


def _check_sequence_consistency(files: List[str], required_cards: List[str]) -> None:
    headers = [fits.getheader(file_path, ext=0) for file_path in files]

    print(f"\n{Style.BRIGHT}Checking FITS sequence consistency...{Style.RESET_ALL}")
    for card_name in required_cards:
        values = []
        for header in headers:
            if card_name not in header:
                raise CalibrationMasterGenerationError(f"Missing required header card {card_name}")
            values.append(header[card_name])

        tolerance = 0
        for card_config in config.TESTED_FITS_CARDS:
            if card_config["name"] == card_name:
                tolerance = card_config["tolerance"]
                break

        if tolerance:
            numeric_values = [_safe_float(value) for value in values]
            average = float(np.mean(numeric_values))
            max_deviation = max(abs(value - average) for value in numeric_values)
            print(f"-- {card_name} average: {average:.2f}, max deviation: {max_deviation:.2f}")
            if max_deviation > tolerance:
                raise CalibrationMasterGenerationError(
                    f"{card_name} values exceed tolerance: {max_deviation:.2f} > {tolerance}"
                )
        elif len(set(values)) > 1:
            raise CalibrationMasterGenerationError(f"Multiple {card_name} values in sequence: {set(values)}")
        else:
            print(f"{Fore.GREEN}-- {card_name} values are consistent: {values[0]}{Style.RESET_ALL}")


def _combine_files(files: List[str], flat: bool = False) -> CCDData:
    scale = None
    if flat:
        def inv_median(data):
            return 1 / np.median(data)
        scale = inv_median

    stack = ccdp.combine(
        files,
        method="average",
        scale=scale,
        sigma_clip=True,
        sigma_clip_low_thresh=config.SIGMA_LOW,
        sigma_clip_high_thresh=config.SIGMA_HIGH,
        sigma_clip_func=np.ma.median,
        sigma_clip_dev_func=mad_std,
        mem_limit=config.INTEGRATION_MEMORY_LIMIT,
        unit="adu",
        dtype="float32",
    )
    stack.meta["COMBINED"] = True
    stack.meta["NIMAGES"] = len(files)
    stack.uncertainty = None
    stack.mask = None
    stack.flags = None
    return stack


def _prepare_output_path(filename: str, output_dir: Optional[str]) -> Path:
    destination = Path(output_dir or config.CALIBRATION_PATH)
    destination.mkdir(parents=True, exist_ok=True)
    return destination / filename


def _register_master(output_path: Path) -> None:
    try:
        from lib.db import scan_calibration_masters

        scan_calibration_masters(str(output_path.parent), verbose=False)
    except Exception as exc:
        print(f"{Style.BRIGHT + Fore.YELLOW}Warning: could not register master in database: {exc}{Style.RESET_ALL}")


class CalibrationMasterGenerator:
    """Generate master bias, dark, and flat frames."""

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = output_dir
        self._calibration_manager: Optional[CalibrationManager] = None

    @property
    def calibration_manager(self) -> CalibrationManager:
        if self._calibration_manager is None:
            self._calibration_manager = CalibrationManager()
        return self._calibration_manager

    def _ensure_calibration_index(self) -> None:
        try:
            from lib.db import scan_calibration_masters

            scan_calibration_masters(verbose=False)
        except Exception as exc:
            print(f"{Style.BRIGHT + Fore.YELLOW}Warning: could not refresh calibration database: {exc}{Style.RESET_ALL}")

    def generate_master_bias(self, files: Iterable[str]) -> Dict[str, Any]:
        valid_files = _validate_files(files)
        _check_sequence_consistency(valid_files, ["GAIN", "OFFSET", "XBINNING", "CCD-TEMP", "NAXIS1", "NAXIS2"])

        print(f"\n{Style.BRIGHT}Generating master bias from {len(valid_files)} files.{Style.RESET_ALL}")
        stack = _combine_files(valid_files)
        header = stack.header

        ccd_temp = _round_header_value(header, "CCD-TEMP")
        gain = _round_header_value(header, "GAIN")
        offset = _round_header_value(header, "OFFSET")
        binning = _binning_from_header(header)
        date_string = _format_date_for_filename(header)
        filename = f"master_bias_{ccd_temp}C_{gain}g{offset}o_{binning}_{date_string}.fits"
        output_path = _prepare_output_path(filename, self.output_dir)

        stack.meta["FRAME"] = "Bias"
        stack.meta["IMAGETYP"] = "Master Bias"
        print(f"Writing {output_path}...")
        stack.write(output_path, overwrite=True)
        _register_master(output_path)

        return {"success": True, "frame": "Bias", "path": str(output_path), "files_used": len(valid_files)}

    def generate_master_dark(self, files: Iterable[str]) -> Dict[str, Any]:
        valid_files = _validate_files(files)
        _check_sequence_consistency(valid_files, ["GAIN", "OFFSET", "XBINNING", "EXPTIME", "CCD-TEMP", "NAXIS1", "NAXIS2"])
        self._ensure_calibration_index()

        print(f"\n{Style.BRIGHT}Generating master dark from {len(valid_files)} files.{Style.RESET_ALL}")
        calibrated_files: List[str] = []
        with tempfile.TemporaryDirectory(prefix="astropipes_master_dark_") as temp_dir:
            for index, file_path in enumerate(valid_files, 1):
                print(f"\n{Style.BRIGHT}[{index}/{len(valid_files)}] Calibrating {os.path.basename(file_path)}...{Style.RESET_ALL}")
                metadata = _metadata_from_file(file_path)
                master_bias = self.calibration_manager.find_master_bias(metadata)
                if not master_bias:
                    raise CalibrationMasterGenerationError("Cannot generate master dark without a matching master bias")

                calibrated_image = self.calibration_manager.subtract_bias(file_path, master_bias)
                calibrated_path = Path(temp_dir) / f"b_{os.path.basename(file_path)}"
                print(f"-- Writing {calibrated_path}...")
                calibrated_image.write(calibrated_path, overwrite=True)
                calibrated_files.append(str(calibrated_path))

            stack = _combine_files(calibrated_files)

        header = stack.header
        exptime = _round_header_value(header, "EXPTIME")
        ccd_temp = _round_header_value(header, "CCD-TEMP")
        gain = _round_header_value(header, "GAIN")
        offset = _round_header_value(header, "OFFSET")
        binning = _binning_from_header(header)
        date_string = _format_date_for_filename(header)
        filename = f"master_dark_{exptime}_{ccd_temp}C_{gain}g{offset}o_{binning}_{date_string}.fits"
        output_path = _prepare_output_path(filename, self.output_dir)

        stack.meta["FRAME"] = "Dark"
        stack.meta["IMAGETYP"] = "Master Dark"
        print(f"Writing {output_path}...")
        stack.write(output_path, overwrite=True)
        _register_master(output_path)

        return {"success": True, "frame": "Dark", "path": str(output_path), "files_used": len(valid_files)}

    def generate_master_flat(self, files: Iterable[str]) -> Dict[str, Any]:
        valid_files = _validate_files(files)
        _check_sequence_consistency(valid_files, ["FILTER", "GAIN", "OFFSET", "XBINNING", "CCD-TEMP", "NAXIS1", "NAXIS2"])
        self._ensure_calibration_index()

        print(f"\n{Style.BRIGHT}Generating master flat from {len(valid_files)} files.{Style.RESET_ALL}")
        calibrated_files: List[str] = []
        with tempfile.TemporaryDirectory(prefix="astropipes_master_flat_") as temp_dir:
            for index, file_path in enumerate(valid_files, 1):
                print(f"\n{Style.BRIGHT}[{index}/{len(valid_files)}] Calibrating {os.path.basename(file_path)}...{Style.RESET_ALL}")
                metadata = _metadata_from_file(file_path)
                master_bias = self.calibration_manager.find_master_bias(metadata)
                if not master_bias:
                    raise CalibrationMasterGenerationError("Cannot generate master flat without a matching master bias")

                master_dark = self.calibration_manager.find_master_dark(metadata)
                if not master_dark:
                    raise CalibrationMasterGenerationError("Cannot generate master flat without a matching master dark")

                calibrated_image = self.calibration_manager.subtract_bias(file_path, master_bias)
                calibrated_image = self.calibration_manager.subtract_dark(calibrated_image, master_dark, metadata.exptime)
                calibrated_path = Path(temp_dir) / f"b_d_{os.path.basename(file_path)}"
                print(f"-- Writing {calibrated_path}...")
                calibrated_image.write(calibrated_path, overwrite=True)
                calibrated_files.append(str(calibrated_path))

            stack = _combine_files(calibrated_files, flat=True)

        header = stack.header
        filter_code = str(header.get("FILTER", "Unknown")).strip().replace(" ", "_").replace("/", "_")
        ccd_temp = _round_header_value(header, "CCD-TEMP")
        gain = _round_header_value(header, "GAIN")
        offset = _round_header_value(header, "OFFSET")
        binning = _binning_from_header(header)
        date_string = _format_date_for_filename(header)
        filename = f"master_flat_{filter_code}_{ccd_temp}C_{gain}g{offset}o_{binning}_{date_string}.fits"
        output_path = _prepare_output_path(filename, self.output_dir)

        stack.meta["FRAME"] = "Flat"
        stack.meta["IMAGETYP"] = "Master Flat"
        print(f"Writing {output_path}...")
        stack.write(output_path, overwrite=True)
        _register_master(output_path)

        return {"success": True, "frame": "Flat", "path": str(output_path), "files_used": len(valid_files)}

    def generate(self, frame_type: str, files: Iterable[str]) -> Dict[str, Any]:
        frame = frame_type.lower()
        if frame == "bias":
            return self.generate_master_bias(files)
        if frame == "dark":
            return self.generate_master_dark(files)
        if frame == "flat":
            return self.generate_master_flat(files)
        raise CalibrationMasterGenerationError(f"Unsupported calibration master type: {frame_type}")


def generate_calibration_master(frame_type: str, files: Iterable[str], output_dir: Optional[str] = None) -> Dict[str, Any]:
    """Generate a calibration master of the requested type."""

    return CalibrationMasterGenerator(output_dir=output_dir).generate(frame_type, files)
