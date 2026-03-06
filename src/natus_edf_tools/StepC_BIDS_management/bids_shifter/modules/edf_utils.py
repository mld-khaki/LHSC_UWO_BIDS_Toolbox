# -*- coding: utf-8 -*-
"""
EDF file utilities for BIDS Shifter GUI.
Handles EDF file reading and metadata extraction.
"""

import os
from .config import EXCEPTION_DEBUG
from .utils import iso_fmt_T, log_line


# Try to import EDFreader from various locations
_EDFreader = None

def _init_edfreader():
    """Initialize EDFreader on first use."""
    global _EDFreader
    
    if _EDFreader is not None:
        return _EDFreader
    
    try:
        from edfreader_mld2 import EDFreader
        _EDFreader = EDFreader
    except ImportError:
        try:
            from edfreader_mld2 import EDFreader
            _EDFreader = EDFreader
        except ImportError:
            _EDFreader = False  # Mark as unavailable
    
    return _EDFreader


def is_edfreader_available():
    """Check if EDFreader is available."""
    reader = _init_edfreader()
    return reader is not False and reader is not None


def read_edf_metadata(filepath, log_path=None):
    """
    Read metadata from an EDF file.
    
    Args:
        filepath: Path to EDF file
        log_path: Optional log file path
    
    Returns:
        Dict with:
            - acq_time: ISO formatted acquisition time
            - duration: Duration in hours (3 decimal places)
            - edf_type: EDF type string
        Or None if reading failed
    """
    EDFreader = _init_edfreader()
    
    if not EDFreader:
        log_line(log_path, "ERROR: EDFreader not available")
        return None
    
    try:
        reader = EDFreader(filepath, read_annotations=False)
        start_dt = reader.getStartDateTime()
        dur_sec = reader.getFileDuration()
        reader.close()
        
        acq_time = iso_fmt_T(start_dt)
        dur_hours = float(dur_sec) / (3600.0 * 1e7)
        
        return {
            "acq_time": acq_time,
            "duration": f"{dur_hours:.3f}",
            "edf_type": "EDF+C"
        }
    
    except Exception as e:
        log_line(log_path, f"ERROR reading EDF {filepath}: {e}")
        if EXCEPTION_DEBUG:
            raise e
        return None


def generate_tsv_records(root_dir, log_path=None):
    """
    Generate TSV records from all EDF files in a directory.
    
    Args:
        root_dir: Root directory to scan
        log_path: Optional log file path
    
    Returns:
        List of (relative_path, acq_time, duration, edf_type) tuples,
        sorted by acquisition time
    """
    records = []
    
    for root, dirs, files in os.walk(root_dir):
        for fn in files:
            if not fn.lower().endswith(".edf"):
                continue
            
            full_path = os.path.join(root, fn)
            rel_path = os.path.relpath(full_path, root_dir).replace("\\", "/")
            
            metadata = read_edf_metadata(full_path, log_path)
            
            if metadata:
                records.append((
                    rel_path,
                    metadata["acq_time"],
                    metadata["duration"],
                    metadata["edf_type"]
                ))
    
    # Sort by acquisition time (ISO 8601 is sortable)
    records.sort(key=lambda t: t[1])
    
    return records
