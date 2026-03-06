# BIDS Session Shifter & TSV Tools v2.0

A modular graphical tool for managing BIDS (Brain Imaging Data Structure) session data from intracranial EEG recordings.

## Features

- **Session Management**: Shift, swap, and renumber session folders
- **Duplicate Detection** (BUG FIX): Now correctly identifies and displays session numbers for duplicate recordings
- **TSV Management**: Load, edit, and generate scans.tsv files
- **Folder Consistency Checks**: Verify TSV matches filesystem
- **Duration Analysis**: Check recording coverage by day
- **Import Sessions** (NEW): Import sessions from another subject folder with automatic renumbering

## Installation

### Requirements
- Python 3.8+
- tkinter (usually included with Python)
- Optional: pandas (for duration checks)

### Setup
```bash
# The project structure should be:
bids_shifter/
├── bids_shifter_gui.py      # Main GUI application
├── edfreader_mld2.py        # EDF file reader
├── modules/
│   ├── __init__.py
│   ├── config.py            # Configuration constants
│   ├── utils.py             # Utility functions
│   ├── tsv_manager.py       # TSV file operations
│   ├── session_manager.py   # Session manipulation
│   ├── duplicate_finder.py  # Duplicate detection (bug fixed)
│   ├── import_manager.py    # Session import (new feature)
│   └── edf_utils.py         # EDF file utilities
```

## Usage

```bash
python bids_shifter_gui.py
```

### Basic Workflow

1. **Select Subject Root**: Choose your `sub-XXX` folder
2. **Load/Generate TSV**: Load existing or generate from EDF files
3. **Make Changes**: Use shift controls or move buttons
4. **Review**: Changes appear in red; duplicates in purple
5. **Apply**: Uncheck "Dry Run" and click "Apply Changes"

### Import Sessions (New Feature)

1. Click "Import Sessions..."
2. Select the source subject folder
3. Review the mapping (source sessions → new numbers)
4. Confirm to copy sessions and update TSV

## Bug Fixes in v2.0

### Duplicate Detection Fix
The previous version showed incorrect session numbers when reporting duplicates. The fix:

**Before (buggy)**:
```
Found duplicates:
- 2025-03-11 | 22.727 h -> 2 rows
    ses-110/ieeg/sub-167_ses-110_task-full_run-01_ieeg.edf
    ses-111/ieeg/sub-167_ses-111_task-full_run-01_ieeg.edf
```

**After (fixed)**:
```
═══ Date: 2025-03-11 | Duration: 22.727h ═══
    Sessions involved: ses-110, ses-111
    Files (2):
      [ses-110] ses-110/ieeg/sub-167_ses-110_task-full_run-01_ieeg.edf
      [ses-111] ses-111/ieeg/sub-167_ses-111_task-full_run-01_ieeg.edf
```

The session number is now:
- Extracted explicitly from each filename
- Displayed prominently with `[ses-XXX]` prefix
- Summarized as "Sessions involved" for quick reference

## Module Documentation

### `modules/config.py`
Configuration constants like patterns and tag colors.

### `modules/utils.py`
Utility functions:
- `log_line()`: Timestamped logging
- `extract_session_from_filename()`: Parse session from path
- `normalize_date()`: Extract date from datetime string

### `modules/tsv_manager.py`
TSV file operations:
- `load()`, `save()`, `backup()`
- `get_changed_sessions()`: Detect pending changes
- `add_rows()`: Add imported rows

### `modules/session_manager.py`
Session manipulation:
- `shift_sessions_in_range()`: Bulk shift
- `swap_sessions()`: Swap two sessions
- `normalize_to_sequence()`: Renumber to 1..N

### `modules/duplicate_finder.py`
Duplicate detection:
- `find_duplicates()`: Find by (date, duration)
- `format_duplicate_summary()`: Human-readable output

### `modules/import_manager.py`
Import from another folder:
- `scan_source_folder()`: Discover sessions
- `calculate_import_mapping()`: Plan renumbering
- `import_sessions()`: Copy and rename

## Color Coding

| Color | Meaning |
|-------|---------|
| Red text | Pending changes |
| Purple bg | Duplicate recording |
| Red bg | Missing folder |
| Orange bg | Extra folder (not in TSV) |
| Green bg | Good recording day (23+ hrs) |
| Orange bg | Partial day (first/last) |
| Red bg | Missing hours |
| Blue bg | Multiple sessions same day |
| Light green bg | Imported session |

## Logs

Logs are written to `BIDS_Shifter_log_YYYY-MM-DD.txt` in the subject folder.

## Tips

1. **Always use Dry Run first** to preview changes
2. **Backups are automatic** when applying changes
3. **Sort by Session #** to see sessions in order
4. **Check TSV vs Folders** after imports to verify consistency
