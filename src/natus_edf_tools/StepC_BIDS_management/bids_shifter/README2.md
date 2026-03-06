# BIDS Shifter GUI v2.1 - Update Notes

## Changed Files

Only the following files were modified. Replace these in your existing project:

```
bids_shifter_updated/
├── bids_shifter_gui.py          # Main GUI (heavily modified)
└── modules/
    ├── __init__.py              # Updated exports
    ├── config.py                # New tags and color legend
    ├── utils.py                 # New helper functions
    └── session_manager.py       # New methods
```

**Unchanged files** (keep your existing versions):
- `modules/duplicate_finder.py`
- `modules/edf_utils.py`
- `modules/import_manager.py`
- `modules/tsv_manager.py`
- `edfreader_mld2.py`

---

## New Features

### 1. Move Up/Down Now Increments/Decrements by 1
- **▲ Dec (-1)**: Decrements the selected session number (ses-002 → ses-001)
- **▼ Inc (+1)**: Increments the selected session number (ses-002 → ses-003)
- Works even when there are gaps in session numbers

### 2. Sync Files → Folders Button
- Finds all BIDS files where the filename's session doesn't match the folder
- Renames files to match their folder's session number
- Also updates the TSV entries
- Supports: `.edf`, `.tsv`, `.json`, `.vhdr`, `.vmrk`, `.eeg`, `.nii`, `.nii.gz`

### 3. Find Empty Folders Button
- Detects session folders with no EDF and no TSV files
- Highlights them in gray in the tree view
- Offers to delete them (with confirmation)
- Shows count of "other" files if present

### 4. Validate All Button
- Runs all checks at once:
  - TSV vs Folders consistency
  - Folder/filename discrepancies
  - Empty folders
  - Duplicate recordings
- Shows a summary with ✓/❌/⚠️ indicators

### 5. Auto-Check Discrepancies on Load
- Automatically detects folder/filename mismatches when loading
- Highlights them with yellow background
- Non-blocking - just updates title bar with warning count

### 6. Color Legend
- Shows at bottom of window
- Explains what each highlight color means

### 7. Undo Button
- Stores up to 10 undo states
- Allows reverting TSV changes before Apply
- Stack is cleared after successful Apply Changes

---

## New Tree Tags

| Tag | Color | Meaning |
|-----|-------|---------|
| `discrepancy` | Yellow bg | Filename session ≠ folder session |
| `empty_folder` | Gray bg | Folder has no EDF/TSV files |

---

## Usage Notes

1. **Sync Files → Folders** respects the Dry Run checkbox
2. **Find Empty Folders** will delete even if "other" files exist (with warning)
3. **Undo** only works for TSV changes, not filesystem changes
4. After **Apply Changes**, the undo stack is cleared

---

## Installation

1. Replace the changed files in your existing project
2. No new dependencies required
