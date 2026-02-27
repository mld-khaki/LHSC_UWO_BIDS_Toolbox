# Unified EDF Post-Conversion Cleanup — Help

**Platform:** Windows  
**Interface:** Tkinter GUI (single window)  
**Purpose:** Safely finalize Natus→EDF conversions by archiving source folders, moving non-provenance media to a _deletable_ area, and marking verified EDFs — all with a simple Scan→Run flow and centralized logging.

---

## 1) Overview

This app consolidates three previous scripts into **one end-to-end tool**:

1. **Discover candidates** where:
   - `<subject>.edf` exists in **Folder B**,
   - `<subject>.edf_pass` exists (no `edf_fail`) beside the EDF,
   - a **subject folder with the exact same name** exists in **Folder A**, and
   - **size constraint holds**: `size(EDF) ≥ size(subject folder)`.

2. **Process each candidate** (when you click **Run**):
   - Move `*.avi` and `*.erd` from the subject folder to the **Deletable** area (pre-archive).
   - Create `FolderA\<subject>.rar` using **WinRAR** and **block** until it completes.
   - **Test** the archive with `WinRAR t`.
   - If the test passes, move the **remaining subject folder** to Deletable (post-archive).
   - **Rename** `subject.edf` and `subject.edf_pass` → `subject_verified_stpAcln.*`.

**Safety model:** The app never hard-deletes. It **moves** removable content to a Deletable area so you can restore if needed.

---

## 2) Requirements

- **OS:** Windows (only)
- **Python:** 3.10+ (uses modern type hints)
- **Packages:** Standard library only (Tkinter is included with Python on Windows)
- **WinRAR:** Installed; default path assumed:  
  `C:\Program Files\WinRAR\WinRAR.exe`  
  (You can browse to a different path in the GUI.)

---

## 3) Key Concepts

- **Folder A (Natus root):** Directory containing the per-subject **source folders** (one folder per subject).
- **Folder B (EDFs root):** Directory containing the generated **`<subject>.edf`** files and sidecars.
- **Exact match rule:** The **EDF basename** must equal the **subject folder name**.  
  Example: `FolderB\patient123.edf` ↔ `FolderA\patient123\`
- **Sidecars:**  
  - `subject.edf_pass` → **compatibility passed** (required)  
  - `subject.edf_fail` → **compatibility failed** (if present, subject is skipped)
- **Size constraint:** `size(EDF) ≥ size(subject folder)`  
  Rationale: You’re using **EDF+** (no discontinuities), which can introduce **zero padding** and make EDF **larger** than raw segments. If EDF is **smaller**, the conversion may be incomplete, so the subject is skipped.
- **Deletable area:**  
  - Default: `FolderA\deletable\` (auto-created)  
  - You can choose a different **Deletable root** in the GUI.  
  - Pre-archive media go to: `deletable\<subject>\pre_archive\...`  
  - Post-archive folder goes to: `deletable\<subject>\post_archive\...`

---

## 4) What the App Does (Step by Step)

### A) Scan
- Validates your selections (Folder A, Folder B, WinRAR).
- Builds a list of **candidates** by checking:
  1. `FolderB\<subject>.edf` exists.
  2. `FolderB\<subject>.edf_pass` exists **and** `FolderB\<subject>.edf_fail` **does not** exist.
  3. `FolderA\<subject>\` folder exists (exact name match).
  4. `size(EDF) ≥ size(subject folder)`.
- Populates the **Candidates** table with:
  - `subject`  
  - `edf` (full path)  
  - `edf_size` and `folder_size` (human-readable)  
  - `size_ok` (YES/NO)  
  - `status` (Pending/Running/OK/Failed/Skipped)  
  - `details` (informational messages)

> If size check fails or required files/folders are missing, the subject is **skipped** and explained in the log.

### B) Run
For each candidate (sequentially):
1. **Move deletable files (pre-archive)**  
   - Extensions: `*.avi`, `*.erd` (hard-coded, case-insensitive).  
   - Original subfolder structure is preserved under `deletable\<subject>\pre_archive\`.  
   - Name collisions receive `*_dupN` suffixes.
2. **Archive subject folder**  
   - `FolderA\<subject>.rar` using **WinRAR**:  
     `winrar a -r -ep1 "<subject>.rar" "<subject>\*"`  
     (`-ep1` strips the drive/leading path; `-r` recurses.)
   - The app **waits** for WinRAR to finish.
3. **Test archive**  
   - `winrar t "<subject>.rar"`  
   - If test fails, the subject is marked **Failed**, and processing stops for that subject.
4. **Move remaining subject folder (post-archive)**  
   - The **entire** `FolderA\<subject>\` is moved to  
     `deletable\<subject>\post_archive\` (or your custom Deletable root).  
   - If the folder is already empty, the log notes it.
5. **Rename EDF & PASS**  
   - `subject.edf` → `subject_verified_stpAcln.edf`  
   - `subject.edf_pass` → `subject_verified_stpAcln.edf_pass`  
   - If targets exist, numeric `*_dupN` suffixes are applied.

**Progress bars:**  
- **Overall**: advances per subject.  
- **Item**: coarse indicator (WinRAR inner progress isn’t parsed).  

**Cancel:** Stops **after** the current subject finishes; remaining subjects won’t start.

---

## 5) User Interface

**Inputs & Options (top):**
- **Folder A (Natus root):** Browse to the parent of your subject folders.
- **Folder B (EDFs root):** Browse to directory with `*.edf` files.
- **WinRAR.exe:** Path to WinRAR executable.
- **Deletable root (optional):** Leave blank to default to `FolderA\deletable\`.
- **Dry-run (preview only):** If checked, **no changes** are made — operations are logged as `[DRY] Would ...`.

**Actions (middle):**
- **Scan:** Build the candidate list using the rules above.
- **Run:** Process all candidates in order.
- **Cancel:** Request cancellation (takes effect between subjects).

**Progress:**
- **Item:** Rough per-subject progress.
- **Overall:** Completed subjects vs total.

**Candidates (table):**
- `subject`, `edf`, `edf_size`, `folder_size`, `size_ok`, `status`, `details`.

**Log (bottom):**
- Live log pane with timestamps.
- A **centralized, timestamped log file** is also written per run:
  - `.\logs\edf_cleanup_run_YYYYMMDD_HHMMSS.log`

---

## 6) Configuration & Defaults

- **Deletable extensions:** `[".avi", ".erd"]`  
  (Hard-coded by design; adjust in source if you need more.)
- **Rename suffix:** `"_verified_stpAcln"`  
  Resulting filenames: `subject_verified_stpAcln.edf` and `.edf_pass`.
- **Archive name:** `FolderA\<subject>.rar`
- **WinRAR default path:**  
  `C:\Program Files\WinRAR\WinRAR.exe`
- **Deletable root default:** `FolderA\deletable\`
- **Logging directory:** `.\logs\` (relative to the program’s current working directory)

---

## 7) Directory Examples

FolderA (Natus root)
├─ patient001\
│  ├─ data1.bin
│  ├─ video.avi          ← moved to deletable\<subject>\pre_archive\
│  └─ events.erd         ← moved to deletable\<subject>\pre_archive\
├─ patient001.rar        ← created after archiving & testing
└─ deletable\
   └─ patient001\
      ├─ pre_archive\... ← pre-archive removals
      └─ post_archive\...← moved remaining subject folder
