# -*- coding: utf-8 -*-
"""
BIDS Shifter GUI Modules

A modular toolkit for managing BIDS session data.
"""

from .config import EXCEPTION_DEBUG, TREE_TAGS, DEFAULT_TSV_COLUMNS
from .utils import (
    log_line,
    todays_log_path,
    iso_fmt_T,
    extract_session_from_filename,
    extract_session_number,
    normalize_date,
    format_duration_key,
    get_timestamp_suffix
)
from .tsv_manager import TSVManager
from .session_manager import SessionManager, FolderManager
from .duplicate_finder import DuplicateFinder, DuplicateInfo
from .import_manager import ImportManager
from .edf_utils import is_edfreader_available, read_edf_metadata, generate_tsv_records

__all__ = [
    # Config
    'EXCEPTION_DEBUG',
    'TREE_TAGS',
    'DEFAULT_TSV_COLUMNS',
    
    # Utils
    'log_line',
    'todays_log_path',
    'iso_fmt_T',
    'extract_session_from_filename',
    'extract_session_number',
    'normalize_date',
    'format_duration_key',
    'get_timestamp_suffix',
    
    # Managers
    'TSVManager',
    'SessionManager',
    'FolderManager',
    'DuplicateFinder',
    'DuplicateInfo',
    'ImportManager',
    
    # EDF Utils
    'is_edfreader_available',
    'read_edf_metadata',
    'generate_tsv_records',
]
