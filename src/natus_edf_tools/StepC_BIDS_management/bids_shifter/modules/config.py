# -*- coding: utf-8 -*-
"""
Configuration constants for BIDS Shifter GUI.
"""

import re

# Debug flag - set to True to raise exceptions for debugging
EXCEPTION_DEBUG = False

# Session pattern: ses-XXX where XXX is 3 digits
SESSION_PATTERN = re.compile(r"ses-(\d{3})")
SESSION_FOLDER_PATTERN = re.compile(r"^ses-\d{3}$")

# BIDS file extensions that contain session info in filename
BIDS_FILE_EXTENSIONS = {".edf", ".tsv", ".json", ".vhdr", ".vmrk", ".eeg", ".nii", ".nii.gz"}

# Default TSV columns
DEFAULT_TSV_COLUMNS = ["filename", "acq_time", "duration", "edf_type"]

# Tree view column configuration
TREE_COLUMNS = [
    ("Folder", 120),
    ("Filename", 520),
    ("Acq Time", 200),
    ("Duration (h)", 120),
    ("EDF Type", 100)
]

# Column width ratios for auto-resize
COLUMN_WIDTH_RATIOS = [0.12, 0.48, 0.2, 0.12, 0.08]

# Tag colors for tree view
TREE_TAGS = {
    "changed": {"foreground": "red"},
    "missing_folder": {"background": "red", "foreground": "white"},
    "extra_folder": {"background": "orange", "foreground": "black"},
    "good_day": {"background": "#c3f7c3"},
    "warn_day": {"background": "#ffd59c"},
    "err_day": {"background": "#ff9c9c"},
    "multi_day": {"background": "#b3ccff"},
    "dup_row": {"background": "#e5b3e6", "foreground": "black"},
    "imported": {"background": "#b3e6b3", "foreground": "black"},
    # New tags
    "discrepancy": {"background": "#ffffb3", "foreground": "black"},  # Yellow for folder/file mismatch
    "empty_folder": {"background": "#d3d3d3", "foreground": "#666666"},  # Gray for empty folders
}

# Color legend descriptions for UI
COLOR_LEGEND = {
    "changed": ("Red text", "Session number changed (pending)"),
    "missing_folder": ("Red bg", "Folder missing on disk"),
    "extra_folder": ("Orange bg", "Folder exists but not in TSV"),
    "discrepancy": ("Yellow bg", "Filename session ≠ folder"),
    "empty_folder": ("Gray bg", "Empty folder (no EDF/TSV)"),
    "dup_row": ("Purple bg", "Duplicate (same date+duration)"),
    "imported": ("Green bg", "Recently imported"),
    "good_day": ("Light green", "Good recording day (≥23h)"),
    "warn_day": ("Light orange", "Partial day (first/last)"),
    "err_day": ("Light red", "Short recording day (<23h)"),
    "multi_day": ("Light blue", "Multiple sessions same day"),
}
