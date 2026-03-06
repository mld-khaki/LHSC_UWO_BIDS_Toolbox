# -*- coding: utf-8 -*-
"""
BIDS Shifter GUI modules package.
"""

from .config import (
    EXCEPTION_DEBUG,
    SESSION_PATTERN,
    SESSION_FOLDER_PATTERN,
    BIDS_FILE_EXTENSIONS,
    DEFAULT_TSV_COLUMNS,
    TREE_COLUMNS,
    COLUMN_WIDTH_RATIOS,
    TREE_TAGS,
    COLOR_LEGEND,
)

from .utils import (
    iso_fmt_T,
    todays_log_path,
    log_line,
    extract_session_from_filename,
    extract_session_from_basename,
    extract_session_number,
    normalize_date,
    format_duration_key,
    get_timestamp_suffix,
    is_bids_file,
    get_session_from_path,
    check_session_discrepancy,
)

from .tsv_manager import TSVManager
from .session_manager import SessionManager, FolderManager
from .duplicate_finder import DuplicateFinder, DuplicateInfo
from .import_manager import ImportManager
from .edf_utils import is_edfreader_available, read_edf_metadata, generate_tsv_records

__all__ = [
    # Config
    "EXCEPTION_DEBUG",
    "SESSION_PATTERN",
    "SESSION_FOLDER_PATTERN",
    "BIDS_FILE_EXTENSIONS",
    "DEFAULT_TSV_COLUMNS",
    "TREE_COLUMNS",
    "COLUMN_WIDTH_RATIOS",
    "TREE_TAGS",
    "COLOR_LEGEND",
    # Utils
    "iso_fmt_T",
    "todays_log_path",
    "log_line",
    "extract_session_from_filename",
    "extract_session_from_basename",
    "extract_session_number",
    "normalize_date",
    "format_duration_key",
    "get_timestamp_suffix",
    "is_bids_file",
    "get_session_from_path",
    "check_session_discrepancy",
    # Managers
    "TSVManager",
    "SessionManager",
    "FolderManager",
    "DuplicateFinder",
    "DuplicateInfo",
    "ImportManager",
    # EDF utils
    "is_edfreader_available",
    "read_edf_metadata",
    "generate_tsv_records",
]
