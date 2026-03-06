# -*- coding: utf-8 -*-
"""
Configuration constants for BIDS Shifter GUI.
"""

import re

# Debug flag - set to True to raise exceptions for debugging
EXCEPTION_DEBUG = True

# Session pattern: ses-XXX where XXX is 3 digits
SESSION_PATTERN = re.compile(r"ses-(\d{3})")
SESSION_FOLDER_PATTERN = re.compile(r"^ses-\d{3}$")

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
    "imported": {"background": "#b3e6b3", "foreground": "black"}
}
