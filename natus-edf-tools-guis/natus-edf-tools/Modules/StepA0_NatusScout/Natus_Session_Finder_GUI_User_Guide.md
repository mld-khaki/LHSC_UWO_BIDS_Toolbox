# NatusScout — User & Engineer Guide

**Version:** 1.2 (open source, single `.py`)
**Official name in code:** *Natus Session Finder GUI*
**Requires:** Windows, Python 3.8+ (standard library only; Tkinter)

## What NatusScout does
NatusScout scans top-level patient folders, shows summary stats, lets you select sessions, extract quick metadata from `.eeg/.ent`, run coverage checks with a Gantt chart, and export copy/move scripts that respect your site policy (exclude `.avi`). Key features include:

- Type-aware sorting for Duration, RecStart/End, Dominant Date, and humanized Size.
- “Quick metadata” extraction for `.eeg/.ent` to get StudyName, RecStart/End, EegNo, Machine.
- Coverage checker (selected rows only) with threshold (default 23 h) from the INI and a Gantt view (PNG+TSV export).
- Two-part export for copy/move: a standalone Python script + a paired `*_items.csv` of `(src_path, dest_subfolder)`.
- Excludes `.avi` by default in exports (policy).
- Session Save/Load with “Present/Missing/New” reconciliation, colored rows, and progress bar.

### What’s new
- **1.2:** Coverage & Gantt respect INI; inline multiple-session details; improved logs.
- **1.1:** Type-aware sorting; new Duration column; Coverage checker; context menu; INI-driven columns & threshold; two-part export; QoL fixes.
- **1.0:** Session reload prompt + progress; row highlighting; filters & bulk select; spacebar toggle; export CSV; copy script; scrollbars; save/load session.

---

## Folder naming & environment

- **Folder convention:** `<patient lastname>~ <firstname>_UID`
- **OS & Python:** Windows, Python 3.8+; Tkinter GUI is standard library only.
- **Distribution:** Single `.py` with a peer `.ini` auto-created on first run.

---

## First run & configuration (`.ini`)
On first run, NatusScout writes an INI next to the `.py` with sensible defaults. You can edit it to tune columns, coverage, and Gantt:

```ini
[columns]
selected=true
status=true
folder_name=true
dominant_date=false
dom_fraction=true
total_files=true
total_size=true
has_eeg=false
recent=true
study_name=true
rec_start=true
rec_end=true
duration=true
eegno=true
machine=true

[checker]
threshold_hours=23

[gantt]
gantt_show_grid=true
gantt_tick_hours=8
coverage_show_details=inline
gantt_dpi=150
gantt_width=1200
gantt_height=700
```

The app reads these at startup and builds the table accordingly. Gantt rendering uses these values for grid, tick interval, DPI, and figure size.

---

## UI tour

### Toolbar buttons (rows 1–3)
- **Quick metadata for selected** — peeks `.eeg/.ent` and fills StudyName/Start/End/EegNo/Machine.
- **Export CSV** — dumps the table (with all row fields) to CSV.
- **Select All / Select None** — fast bulk selection.
- **Save Session / Load Session** — persist and restore with reconciliation and a progress bar.
- **Script: move instead of copy** — toggles mode for exported scripts.
- **Export Copy/Move (code + CSV)** — two-part export (policy excludes `.avi`).
- **Check Coverage (Selected)** — opens report + Gantt window; configured by INI threshold.

### Table & columns
- Columns are enabled from the INI; headers, widths, and sorting are type-aware.
- Row color tags: **Missing** (red), **New** (blue), **Present** (black).

### Context menu (right-click)
- **Toggle selection**, **Delete item** (list only), **Refresh (selected item)**, **Quick metadata**.

### Keyboard shortcuts
- **Space** — toggle selection for the focused/highlighted rows.

---

## Typical workflows

### 1) Scan & select sessions
1. Choose the root directory that contains patient folders named like `<lastname>~ <firstname>_UID`.
2. (Optional) Use the **prefix filter** and **last N days** filter to narrow rows; “Recent” gets auto-labeled by days filter.
3. Use **Select All/None** or spacebar to toggle selection.

### 2) Quick metadata (lightweight)
- Click **Quick metadata for selected** to parse `.eeg/.ent` for StudyName, RecStart, RecEnd, EegNo, Machine; the table row updates inline.

### 3) Coverage check + Gantt
- Click **Check Coverage (Selected)**. The tool builds per-day unions, flags multiple/overlapping sessions, and tags **below-threshold days** (default 23 h/day) — *first and last day are excluded* from “below threshold” tagging because EMU days are rarely exactly 24 h.
- Use **Re-check** in the window to refresh against current selection; **Save…** writes **PNG + TSV** (union timeline + daily stats).

The coverage report includes per-day totals and inline **“Details for days with multiple sessions”**, **overlapping sessions**, and **below-threshold days**.

### 4) Export copy/move (policy-compliant)
- Click **Export Copy/Move (code + CSV)**. You’ll get:
  - A standalone **main script** that reads a paired `*_items.csv`, and
  - The **CSV** of `(src_path, dest_subfolder_name)` you selected.
- The generated scripts exclude `*.avi` by default (policy) and re-create folder structure while copying or moving.

---

## Gantt & coverage details

- **Threshold hours:** from INI `[checker].threshold_hours` (default 23).
- **Below-threshold** days **exclude the first/last day** in the selected window.
- **Multiple sessions** & **overlaps** are detected per-day, with union coverage shown faintly, and click-tooltips for bars (folder, time, EegNo, StudyName).
- **INI-driven Gantt look:** grid, tick size (hours), DPI, width/height.
- **Export:** “Save… (PNG + TSV)” on the Coverage window toolbar.

---

## Copy/move export — how it works

- **One-file script variant**: embeds the selected items and excludes `.avi` via `EXCLUDE_EXTS = ['.avi']`.
- **Two-part main script + CSV variant**: reads `ITEMS_CSV`, still excludes `.avi` by default.
- Both variants:
  - Recreate directory structure and skip excluded extensions.
  - Resolve **name collisions** by appending `_copyN`.
  - Comment **MISSING** items into the script (or omit from CSV).

---

## Privacy & PHI guidance
- Use **prefix filters** and **CSV exports** only on secure drives approved for PHI.
- Avoid screenshots that reveal patient names; prefer saving the **Gantt PNG + TSV** to secured storage.
- Copy/move only to approved destinations.

---

## Known interactions & notes
- **Save/Load Session** reconciles Present/Missing/New with progress feedback.
- **Refresh (selected)** re-analyzes that folder’s stats and updates the row + log.
- Adjust **gantt_tick_hours** if your chart is too dense.

---

## Changelog (short)
- **v1.2:** INI-driven coverage/Gantt; inline multiple-session details; clearer logs.
- **v1.1:** Type-aware sorting; Duration column; Coverage checker; context menu; INI defaults; two-part export; QoL.
- **v1.0:** Rescan prompt; progress bar; color states; filters; spacebar select; CSV; copy script; save/load; scrollbars.

## License & naming
- **Brand name:** NatusScout — short, meaningful, focused on finding/organizing Natus sessions.
- **Open source:** single-file distribution.
