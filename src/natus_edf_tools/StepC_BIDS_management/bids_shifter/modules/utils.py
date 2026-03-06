# -*- coding: utf-8 -*-
"""
Utility functions for BIDS Shifter GUI.
Includes logging, date formatting, and session parsing.
"""

import os
from datetime import datetime
from .config import SESSION_PATTERN, EXCEPTION_DEBUG


def iso_fmt_T(dt):
    """Return ISO-8601 string with 'T' separator."""
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    return str(dt)


def todays_log_path(root_dir):
    """Generate log file path for today."""
    return os.path.join(root_dir, f"BIDS_Shifter_log_{datetime.now().strftime('%Y-%m-%d')}.txt")


def log_line(log_path, msg):
    """Write a timestamped log line to console and optionally to file."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            print(f"Warning: Could not write to log file: {e}")


def extract_session_from_filename(filename_value):
    """
    Extract session folder name from a BIDS filename path.
    
    Args:
        filename_value: Path like "ses-110/ieeg/sub-xxx_ses-110_....edf"
    
    Returns:
        Session string like "ses-110" or empty string if not found.
    """
    if not filename_value:
        return ""
    try:
        # First segment should be the session folder
        seg = filename_value.split("/")[0]
        if seg.startswith("ses-") and len(seg) == 7 and seg[4:].isdigit():
            return seg
    except Exception as e:
        if EXCEPTION_DEBUG:
            raise e
    return ""


def extract_session_number(session_str):
    """
    Extract numeric part from session string.
    
    Args:
        session_str: String like "ses-110"
    
    Returns:
        Integer like 110, or 0 if parsing fails.
    """
    if not session_str:
        return 0
    try:
        return int(session_str.split("-")[1])
    except (IndexError, ValueError) as e:
        if EXCEPTION_DEBUG:
            raise e
        return 0


def normalize_date(acq_time):
    """
    Extract date portion from acquisition time string.
    
    Args:
        acq_time: String like "YYYY-MM-DDTHH:MM:SS" or "YYYY-MM-DD HH:MM:SS"
    
    Returns:
        Date string "YYYY-MM-DD" or empty string.
    """
    if not acq_time:
        return ""
    # Accept "YYYY-MM-DDTHH:MM:SS" or "YYYY-MM-DD HH:MM:SS"
    if "T" in acq_time:
        return acq_time.split("T", 1)[0]
    return acq_time.split(" ", 1)[0]


def format_duration_key(duration_str):
    """
    Format duration to 3 decimal places for comparison.
    
    Args:
        duration_str: Duration string or number
    
    Returns:
        Formatted string like "22.727" or original string if parsing fails.
    """
    try:
        return f"{float(duration_str):.3f}"
    except (ValueError, TypeError):
        return str(duration_str).strip()


def get_timestamp_suffix():
    """Get a timestamp string suitable for backup file names."""
    return datetime.now().strftime("%Y_%m_%d__%H_%M_%S")
