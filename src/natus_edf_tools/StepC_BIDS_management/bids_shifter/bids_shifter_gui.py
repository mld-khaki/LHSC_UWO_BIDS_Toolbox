# -*- coding: utf-8 -*-
"""
BIDS Session Shifter & TSV Tools - Main GUI

A graphical tool for managing BIDS session data:
- Shift/renumber sessions
- Find and resolve duplicates  
- Check TSV vs folder consistency
- Import sessions from another folder
- Generate TSV from EDF files
- Sync files to folder session numbers
- Find and delete empty folders
- Validate all checks at once

Modular version with bug fixes:
- Fixed: Duplicate finder now correctly shows session numbers
- Fixed: Move up/down now increments/decrements by 1 (not swap)
- New: Import sessions from another subject folder
- New: Sync files to folder session numbers
- New: Find empty folders
- New: Validate All button
- New: Color legend
- New: Undo functionality
- New: Auto-check discrepancies on load

Author: Based on original by Nasim
Version: 2.1.0 (Enhanced)
"""

import os
import sys
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime

# Optional pandas for duration checks
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# Import our modules
from modules import (
    EXCEPTION_DEBUG,
    TREE_TAGS,
    COLOR_LEGEND,
    DEFAULT_TSV_COLUMNS,
    log_line,
    todays_log_path,
    extract_session_from_filename,
    extract_session_from_basename,
    extract_session_number,
    normalize_date,
    format_duration_key,
    get_timestamp_suffix,
    check_session_discrepancy,
    TSVManager,
    SessionManager,
    FolderManager,
    DuplicateFinder,
    ImportManager,
    is_edfreader_available,
    generate_tsv_records,
)
from modules.config import TREE_COLUMNS, COLUMN_WIDTH_RATIOS


class BIDSShifterGUI:
    """Main GUI application for BIDS session management."""
    
    def __init__(self, root):
        self.root = root
        self.root.title("BIDS Session Shifter & TSV Tools v2.1")
        self.root.geometry("1400x900")
        
        # Core state
        self.root_dir = ""
        self.log_path = None
        
        # Manager instances
        self.tsv_manager = TSVManager()
        self.session_manager = SessionManager()
        self.folder_manager = None  # Created when root selected
        self.duplicate_finder = DuplicateFinder()
        self.import_manager = ImportManager()
        
        # UI state
        self.dry_run = tk.BooleanVar(value=True)
        self.sort_sessions = tk.BooleanVar(value=False)
        
        # Undo state - stores snapshots before operations
        self.undo_stack = []
        self.max_undo = 10
        
        # Current discrepancies (for highlighting)
        self.current_discrepancies = set()  # Set of row indices
        
        # Build UI
        self._build_ui()
    
    # ==================== UI BUILDING ====================
    
    def _build_ui(self):
        """Build the main user interface."""
        self._build_toolbar()
        self._build_shift_controls()
        self._build_table()
        self._build_legend()
        self._configure_tags()
    
    def _build_toolbar(self):
        """Build the top toolbar with buttons."""
        toolbar = tk.Frame(self.root)
        toolbar.pack(fill="x", padx=8, pady=6)
        
        # Left side buttons
        left = tk.Frame(toolbar)
        left.pack(side="left")
        
        tk.Button(left, text="Select Subject Root", 
                  command=self.select_root).pack(side="left", padx=2)
        tk.Button(left, text="Load TSV", 
                  command=self.load_tsv_dialog).pack(side="left", padx=2)
        
        ttk.Separator(left, orient="vertical").pack(side="left", padx=6, fill="y")
        
        tk.Button(left, text="Refresh Folder", 
                  command=self.refresh_folder).pack(side="left", padx=2)
        tk.Button(left, text="Refresh TSV", 
                  command=self.refresh_tsv).pack(side="left", padx=2)
        tk.Button(left, text="Generate TSV", 
                  command=self.generate_tsv_from_edfs).pack(side="left", padx=2)
        
        ttk.Separator(left, orient="vertical").pack(side="left", padx=6, fill="y")
        
        tk.Button(left, text="Check TSV vs Folders", 
                  command=self.check_tsv_vs_folders).pack(side="left", padx=2)
        tk.Button(left, text="Check Durations", 
                  command=self.check_durations).pack(side="left", padx=2)
        tk.Button(left, text="Find Duplicates", 
                  command=self.find_duplicates).pack(side="left", padx=2)
        
        ttk.Separator(left, orient="vertical").pack(side="left", padx=6, fill="y")
        
        # New buttons
        tk.Button(left, text="Find Empty Folders", 
                  command=self.find_empty_folders,
                  bg="#fff3cd").pack(side="left", padx=2)
        tk.Button(left, text="Sync Files→Folders", 
                  command=self.sync_files_to_folders,
                  bg="#cce5ff").pack(side="left", padx=2)
        tk.Button(left, text="Validate All", 
                  command=self.validate_all,
                  bg="#d4edda").pack(side="left", padx=2)
        
        ttk.Separator(left, orient="vertical").pack(side="left", padx=6, fill="y")
        
        tk.Button(left, text="Import Sessions...", 
                  command=self.import_sessions_dialog,
                  bg="#d4edda").pack(side="left", padx=2)
        
        # Right side checkboxes
        right = tk.Frame(toolbar)
        right.pack(side="right")
        
        tk.Checkbutton(right, text="Dry Run", 
                       variable=self.dry_run).pack(side="right", padx=4)
        tk.Checkbutton(right, text="Sort by Session #", 
                       variable=self.sort_sessions,
                       command=self.refresh_table).pack(side="right", padx=4)
    
    def _build_shift_controls(self):
        """Build the session shift controls."""
        frame = tk.Frame(self.root)
        frame.pack(fill="x", padx=8, pady=4)
        
        # Left: Range shift
        left = tk.Frame(frame)
        left.pack(side="left")
        
        tk.Label(left, text="Shift range  ses-").pack(side="left")
        self.ent_start = tk.Entry(left, width=5)
        self.ent_start.pack(side="left")
        tk.Label(left, text=" to ").pack(side="left")
        self.ent_end = tk.Entry(left, width=5)
        self.ent_end.pack(side="left")
        tk.Label(left, text="  by ").pack(side="left")
        self.ent_delta = tk.Entry(left, width=5)
        self.ent_delta.insert(0, "1")
        self.ent_delta.pack(side="left")
        tk.Button(left, text="Shift", command=self.shift_range).pack(side="left", padx=6)
        
        ttk.Separator(left, orient="vertical").pack(side="left", padx=8, fill="y")
        
        # Move buttons - now increment/decrement
        tk.Button(left, text="▲ Dec (-1)", command=self.move_session_up).pack(side="left", padx=2)
        tk.Button(left, text="▼ Inc (+1)", command=self.move_session_down).pack(side="left", padx=2)
        tk.Button(left, text="Normalize 1..N", command=self.normalize_sessions).pack(side="left", padx=6)
        
        ttk.Separator(left, orient="vertical").pack(side="left", padx=8, fill="y")
        
        # Undo button
        tk.Button(left, text="↶ Undo", command=self.undo_last,
                  bg="#f8d7da").pack(side="left", padx=2)
        
        # Right: Apply
        tk.Button(frame, text="Apply Changes", 
                  command=self.apply_changes,
                  bg="#ffcccc").pack(side="right", padx=6)
    
    def _build_table(self):
        """Build the treeview table."""
        # Create frame with scrollbar
        table_frame = tk.Frame(self.root)
        table_frame.pack(fill="both", expand=True, padx=8, pady=6)
        
        scrollbar = ttk.Scrollbar(table_frame)
        scrollbar.pack(side="right", fill="y")
        
        cols = [c[0] for c in TREE_COLUMNS]
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings",
                                  yscrollcommand=scrollbar.set)
        
        for col, width in TREE_COLUMNS:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="w")
        
        self.tree.pack(fill="both", expand=True)
        scrollbar.config(command=self.tree.yview)
        
        # Auto-resize on window resize
        self.tree.bind("<Configure>", self._auto_resize_columns)
    
    def _build_legend(self):
        """Build the color legend at the bottom."""
        legend_frame = tk.LabelFrame(self.root, text="Color Legend", padx=5, pady=5)
        legend_frame.pack(fill="x", padx=8, pady=4)
        
        # Create a horizontal layout of color swatches
        row_frame = tk.Frame(legend_frame)
        row_frame.pack(fill="x")
        
        # Select key colors to show
        key_colors = ["changed", "discrepancy", "missing_folder", "extra_folder", 
                      "empty_folder", "dup_row", "imported"]
        
        for i, tag in enumerate(key_colors):
            if tag not in COLOR_LEGEND:
                continue
            
            color_desc, explanation = COLOR_LEGEND[tag]
            tag_config = TREE_TAGS.get(tag, {})
            
            # Create color swatch
            swatch = tk.Frame(row_frame, width=16, height=16, 
                            bg=tag_config.get("background", "#ffffff"),
                            highlightbackground="black", highlightthickness=1)
            swatch.pack(side="left", padx=2)
            swatch.pack_propagate(False)
            
            # If foreground color, add inner text indicator
            if "foreground" in tag_config and "background" not in tag_config:
                lbl = tk.Label(swatch, text="A", 
                              fg=tag_config["foreground"], 
                              font=("TkDefaultFont", 8))
                lbl.pack(expand=True)
            
            # Label
            tk.Label(row_frame, text=f"{explanation}", 
                    font=("TkDefaultFont", 9)).pack(side="left", padx=(0, 12))
    
    def _configure_tags(self):
        """Configure treeview tags for colored rows."""
        for tag_name, config in TREE_TAGS.items():
            self.tree.tag_configure(tag_name, **config)
    
    def _auto_resize_columns(self, event):
        """Auto-resize columns based on window width."""
        total = event.width
        cols = [c[0] for c in TREE_COLUMNS]
        for col, ratio in zip(cols, COLUMN_WIDTH_RATIOS):
            self.tree.column(col, width=int(total * ratio))
    
    # ==================== UNDO FUNCTIONALITY ====================
    
    def _save_undo_state(self, description=""):
        """Save current state to undo stack."""
        if not self.tsv_manager.rows:
            return
        
        state = {
            "rows": [dict(r) for r in self.tsv_manager.rows],
            "original_rows": [dict(r) for r in self.tsv_manager.original_rows],
            "description": description
        }
        
        self.undo_stack.append(state)
        
        # Limit stack size
        if len(self.undo_stack) > self.max_undo:
            self.undo_stack.pop(0)
        
        log_line(self.log_path, f"Saved undo state: {description}")
    
    def undo_last(self):
        """Restore the last saved state."""
        if not self.undo_stack:
            messagebox.showinfo("Undo", "Nothing to undo.")
            return
        
        state = self.undo_stack.pop()
        self.tsv_manager.rows = state["rows"]
        self.tsv_manager.original_rows = state["original_rows"]
        
        log_line(self.log_path, f"Restored undo state: {state['description']}")
        self.refresh_table()
        messagebox.showinfo("Undo", f"Restored: {state['description']}")
    
    # ==================== FILE/FOLDER SELECTION ====================
    
    def select_root(self):
        """Select subject root folder."""
        path = filedialog.askdirectory(title="Select sub-### root folder")
        if not path:
            return
        
        self.root_dir = path
        self.log_path = todays_log_path(self.root_dir)
        log_line(self.log_path, f"Selected root: {self.root_dir}")
        
        # Update managers
        self.tsv_manager.log_path = self.log_path
        self.session_manager.log_path = self.log_path
        self.duplicate_finder.log_path = self.log_path
        self.import_manager.log_path = self.log_path
        self.folder_manager = FolderManager(self.root_dir, self.log_path)
        
        # Try to load default TSV
        base = os.path.basename(os.path.normpath(self.root_dir))
        default_tsv = os.path.join(self.root_dir, f"{base}_scans.tsv")
        
        if os.path.exists(default_tsv):
            self.tsv_manager.load(default_tsv)
        else:
            self.tsv_manager.tsv_path = default_tsv
            self.tsv_manager.rows = []
            self.tsv_manager.original_rows = []
        
        self.refresh_table()
        
        # Auto-check for discrepancies (non-blocking)
        self._auto_check_discrepancies()
    
    def _auto_check_discrepancies(self):
        """Automatically check for discrepancies after loading (non-blocking)."""
        if not self.tsv_manager.rows:
            return
        
        # Find discrepancies in TSV rows
        discrepancies = self.session_manager.find_discrepancies(self.tsv_manager.rows)
        
        if discrepancies:
            self.current_discrepancies = {d[0] for d in discrepancies}
            self.refresh_table()
            
            # Show non-blocking notification in status/title
            count = len(discrepancies)
            self.root.title(f"BIDS Shifter v2.1 - ⚠️ {count} discrepancies found")
            log_line(self.log_path, f"Auto-check: {count} folder/filename discrepancies found")
        else:
            self.current_discrepancies = set()
            self.root.title("BIDS Session Shifter & TSV Tools v2.1")
    
    def load_tsv_dialog(self):
        """Show dialog to select TSV file."""
        path = filedialog.askopenfilename(
            title="Select scans.tsv file",
            filetypes=[("TSV files", "*.tsv"), ("All files", "*.*")]
        )
        if path:
            self.tsv_manager.load(path)
            self.refresh_table()
            self._auto_check_discrepancies()
    
    def refresh_tsv(self):
        """Reload current TSV file."""
        if not self.tsv_manager.tsv_path:
            messagebox.showinfo("Info", "No TSV selected.")
            return
        self.tsv_manager.load(self.tsv_manager.tsv_path)
        self.refresh_table()
        self._auto_check_discrepancies()
    
    def refresh_folder(self):
        """Refresh the table display."""
        if not self.root_dir:
            messagebox.showinfo("Info", "No root folder selected.")
            return
        self.refresh_table()
        self._auto_check_discrepancies()
    
    # ==================== TABLE DISPLAY ====================
    
    def refresh_table(self):
        """Refresh the table with current data."""
        self.tree.delete(*self.tree.get_children())
        
        rows = self._get_display_rows()
        
        if self.sort_sessions.get():
            rows.sort(key=lambda r: extract_session_number(r[0]))
        
        for row in rows:
            tags = tuple(row[5]) if row[5] else ()
            self.tree.insert("", "end", values=row[:5], tags=tags)
    
    def _get_display_rows(self):
        """
        Get rows for table display.
        
        Returns:
            List of (folder, filename, acq_time, duration, edf_type, tags_set)
        """
        rows = []
        
        for i, r in enumerate(self.tsv_manager.rows):
            fn = r.get("filename", "")
            acq = r.get("acq_time", "")
            dur = r.get("duration", "")
            edt = r.get("edf_type", "")
            
            folder = extract_session_from_filename(fn)
            basename = os.path.basename(fn)
            
            tags = set()
            
            # Check if changed from original
            if i < len(self.tsv_manager.original_rows):
                orig = self.tsv_manager.original_rows[i]
                if orig.get("filename", "") != fn:
                    tags.add("changed")
            
            # Check if imported
            if r.get("_imported"):
                tags.add("imported")
            
            # Check for discrepancy (folder session != filename session)
            if i in self.current_discrepancies:
                tags.add("discrepancy")
            else:
                # Also check dynamically
                discrepancy = check_session_discrepancy(fn, basename)
                if discrepancy:
                    tags.add("discrepancy")
            
            rows.append((folder, basename, acq, str(dur), edt, tags))
        
        return rows
    
    def _get_sessions_in_view_order(self):
        """Get session IDs in current view order."""
        seen = set()
        ordered = []
        for iid in self.tree.get_children(""):
            s = self.tree.set(iid, "Folder")
            if s and s not in seen:
                seen.add(s)
                ordered.append(s)
        return ordered
    
    def _get_selected_session(self):
        """Get session from first selected row."""
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.set(sel[0], "Folder") or None
    
    # ==================== SESSION OPERATIONS ====================
    
    def shift_range(self):
        """Shift sessions in a range."""
        if not self.tsv_manager.rows:
            messagebox.showinfo("Info", "Load a TSV first.")
            return
        
        try:
            start = int(self.ent_start.get())
            end = int(self.ent_end.get())
            delta = int(self.ent_delta.get())
        except ValueError:
            messagebox.showerror("Error", "Enter valid integers for start, end, and shift.")
            return
        
        if start > end:
            messagebox.showerror("Error", "Start must be <= end.")
            return
        
        self._save_undo_state(f"Shift ses-{start:03d} to ses-{end:03d} by {delta}")
        
        count = self.session_manager.shift_sessions_in_range(
            self.tsv_manager.rows, start, end, delta
        )
        
        log_line(self.log_path, f"Shifted sessions {start}-{end} by {delta} ({count} rows)")
        self.refresh_table()
    
    def move_session_up(self):
        """Decrement selected session number by 1."""
        cur = self._get_selected_session()
        if not cur:
            messagebox.showinfo("Info", "Select a row to move up (decrement).")
            return
        
        cur_num = extract_session_number(cur)
        if cur_num <= 1:
            messagebox.showinfo("Info", f"{cur} is already at minimum (ses-001).")
            return
        
        self._save_undo_state(f"Decrement {cur}")
        
        new_ses = self.session_manager.decrement_session(self.tsv_manager.rows, cur)
        if new_ses:
            self.refresh_table()
            log_line(self.log_path, f"Decremented: {cur} -> {new_ses}")
        else:
            messagebox.showinfo("Info", f"Could not decrement {cur}.")
    
    def move_session_down(self):
        """Increment selected session number by 1."""
        cur = self._get_selected_session()
        if not cur:
            messagebox.showinfo("Info", "Select a row to move down (increment).")
            return
        
        self._save_undo_state(f"Increment {cur}")
        
        new_ses = self.session_manager.increment_session(self.tsv_manager.rows, cur)
        if new_ses:
            self.refresh_table()
            log_line(self.log_path, f"Incremented: {cur} -> {new_ses}")
        else:
            messagebox.showinfo("Info", f"Could not increment {cur}.")
    
    def normalize_sessions(self):
        """Renumber sessions to 1..N."""
        if not self.tsv_manager.rows:
            messagebox.showinfo("Info", "Load a TSV first.")
            return
        
        view_order = self._get_sessions_in_view_order()
        if not view_order:
            messagebox.showinfo("Info", "No sessions found.")
            return
        
        # Build preview
        target_map = {}
        for idx, ses in enumerate(view_order, start=1):
            target_map[ses] = f"ses-{idx:03d}"
        
        if all(k == v for k, v in target_map.items()):
            messagebox.showinfo("Info", "Sessions already normalized.")
            return
        
        changes = [f"{k} -> {v}" for k, v in target_map.items() if k != v]
        if not messagebox.askyesno("Confirm", 
                f"Renumber sessions to:\n\n" + "\n".join(changes) + "\n\nProceed?"):
            return
        
        self._save_undo_state("Normalize 1..N")
        
        self.session_manager.normalize_to_sequence(
            self.tsv_manager.rows,
            self.tsv_manager.original_rows,
            view_order
        )
        self.refresh_table()
        messagebox.showinfo("Done", "Sessions renumbered in preview. Use 'Apply Changes' to save.")
    
    # ==================== APPLY CHANGES ====================
    
    def apply_changes(self):
        """Apply pending changes to filesystem and TSV."""
        if not self.root_dir or not self.tsv_manager.tsv_path:
            messagebox.showinfo("Info", "Need root folder and TSV loaded first.")
            return
        
        old_to_new = self.tsv_manager.get_changed_sessions()
        
        if not old_to_new:
            messagebox.showinfo("Info", "No changes to apply.")
            return
        
        # Show preview
        preview = "\n".join([f"{k} -> {v}" for k, v in 
                           sorted(old_to_new.items(), key=lambda x: extract_session_number(x[0]))])
        
        if not messagebox.askyesno("Confirm", 
                f"Apply these changes?\n\n{preview}\n\nThis will rename folders and update TSV."):
            return
        
        log_line(self.log_path, "===== APPLY START =====")
        
        # Backup TSV
        backup = self.tsv_manager.backup()
        if not backup and not self.dry_run.get():
            messagebox.showerror("Error", "Failed to create TSV backup.")
            return
        
        # Rename folders
        if self.folder_manager:
            success = self.folder_manager.rename_folders(old_to_new, self.dry_run.get())
            if not success:
                messagebox.showerror("Error", "Folder rename failed. Check log.")
                return
        
        # Save TSV
        if not self.dry_run.get():
            if not self.tsv_manager.save():
                messagebox.showerror("Error", "Failed to save TSV.")
                return
            self.tsv_manager.commit_changes()
            
            # Clear undo stack after successful apply
            self.undo_stack.clear()
        
        log_line(self.log_path, "===== APPLY END =====")
        
        msg = "Dry run complete." if self.dry_run.get() else "Changes applied."
        messagebox.showinfo("Done", msg)
        self.refresh_table()
    
    # ==================== CHECKS ====================
    
    def check_tsv_vs_folders(self):
        """Check consistency between TSV and folders."""
        if not self.root_dir:
            messagebox.showinfo("Info", "Select a subject root first.")
            return
        
        # Get sessions from TSV
        tsv_sessions = self.tsv_manager.get_all_sessions()
        
        # Get sessions from folders
        folder_sessions = self.folder_manager.get_session_folders() if self.folder_manager else set()
        
        missing = sorted(tsv_sessions - folder_sessions, key=extract_session_number)
        extra = sorted(folder_sessions - tsv_sessions, key=extract_session_number)
        
        log_line(self.log_path, f"TSV vs Folders — Missing: {len(missing)}, Extra: {len(extra)}")
        
        # Refresh and tag
        self.refresh_table()
        
        for iid in self.tree.get_children(""):
            folder = self.tree.set(iid, "Folder")
            if folder in missing:
                tags = tuple(set(self.tree.item(iid, "tags")) | {"missing_folder"})
                self.tree.item(iid, tags=tags)
        
        # Add extra folders
        for ex in extra:
            self.tree.insert("", "end", 
                           values=(ex, "N/A", "N/A", "N/A", "N/A"),
                           tags=("extra_folder",))
        
        msg = f"Missing folders (in TSV but not disk): {len(missing)}\n"
        msg += f"Extra folders (on disk but not in TSV): {len(extra)}"
        if missing:
            msg += f"\n\nMissing: {', '.join(missing)}"
        if extra:
            msg += f"\n\nExtra: {', '.join(extra)}"
        
        messagebox.showinfo("TSV vs Folders", msg)
    
    def check_durations(self):
        """Check recording durations by day."""
        if not self.tsv_manager.tsv_path:
            messagebox.showinfo("Info", "Load a TSV first.")
            return
        
        if not PANDAS_AVAILABLE:
            messagebox.showerror("Error", "pandas required for duration checks.")
            return
        
        try:
            df = pd.read_csv(self.tsv_manager.tsv_path, sep="\t")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read TSV:\n{e}")
            return
        
        required = ["filename", "acq_time", "duration"]
        if not all(c in df.columns for c in required):
            messagebox.showerror("Error", f"TSV must have columns: {required}")
            return
        
        try:
            df["acq_time"] = pd.to_datetime(df["acq_time"])
            df["duration"] = df["duration"].astype(float)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse data:\n{e}")
            return
        
        df["date"] = df["acq_time"].dt.date
        daily = df.groupby("date")["duration"].sum()
        counts = df.groupby("date")["filename"].count()
        
        if daily.empty:
            messagebox.showinfo("Info", "No data to check.")
            return
        
        first, last = daily.index[0], daily.index[-1]
        all_dates = pd.date_range(start=first, end=last).date
        
        log_line(self.log_path, f"===== DURATION CHECK ({first} to {last}) =====")
        
        # Check for issues
        missing = set(all_dates) - set(daily.index)
        if missing:
            log_line(self.log_path, f"Missing dates: {sorted(missing)}")
        
        multi = counts[counts > 1]
        if not multi.empty:
            log_line(self.log_path, f"Multi-session days: {dict(multi)}")
        
        # Color code days
        day_status = {}
        for date in all_dates:
            if date in daily:
                total = daily[date]
                if date in (first, last):
                    day_status[date] = "warn_day" if total < 23 else "good_day"
                else:
                    day_status[date] = "good_day" if total >= 23 else "err_day"
        
        # Apply to tree
        self.refresh_table()
        
        for iid in self.tree.get_children(""):
            acq = self.tree.set(iid, "Acq Time")
            try:
                dt = datetime.strptime(acq, "%Y-%m-%dT%H:%M:%S").date()
            except ValueError:
                continue
            
            tags = set(self.tree.item(iid, "tags"))
            if dt in day_status:
                tags.add(day_status[dt])
            if dt in multi.index:
                tags.add("multi_day")
            self.tree.item(iid, tags=tuple(tags))
        
        log_line(self.log_path, "===== DURATION CHECK END =====")
        messagebox.showinfo("Duration Check", "Complete. See colors and log.")
    
    def find_duplicates(self):
        """Find duplicate recordings by (date, duration)."""
        if not self.tsv_manager.rows:
            messagebox.showinfo("Info", "Load a TSV first.")
            return
        
        # Find duplicates
        duplicates = self.duplicate_finder.find_duplicates(self.tsv_manager.rows)
        
        # Refresh and tag
        self.refresh_table()
        
        if not duplicates:
            messagebox.showinfo("Duplicates", "No duplicates found.")
            log_line(self.log_path, "Duplicate check: none found.")
            return
        
        # Tag duplicate rows
        tagged = 0
        for iid in self.tree.get_children(""):
            acq = self.tree.set(iid, "Acq Time")
            dur = self.tree.set(iid, "Duration (h)")
            
            if self.duplicate_finder.is_duplicate_display_values(acq, dur, duplicates):
                tags = set(self.tree.item(iid, "tags"))
                tags.add("dup_row")
                self.tree.item(iid, tags=tuple(tags))
                tagged += 1
        
        # Show summary (with bug fix - now shows session numbers prominently)
        summary = self.duplicate_finder.format_duplicate_summary(duplicates)
        
        # Log details
        self.duplicate_finder.log_duplicate_details(duplicates)
        
        messagebox.showinfo("Duplicates Found", summary)
    
    # ==================== NEW: EMPTY FOLDERS ====================
    
    def find_empty_folders(self):
        """Find and optionally delete empty session folders."""
        if not self.root_dir or not self.folder_manager:
            messagebox.showinfo("Info", "Select a subject root first.")
            return
        
        empty = self.folder_manager.find_empty_folders()
        
        if not empty:
            messagebox.showinfo("Empty Folders", "No empty folders found.")
            return
        
        # Refresh table and show empty folders
        self.refresh_table()
        
        # Add empty folders to tree
        for folder_name, other_count in empty:
            note = f"({other_count} other files)" if other_count > 0 else "(completely empty)"
            self.tree.insert("", "end",
                           values=(folder_name, note, "N/A", "N/A", "N/A"),
                           tags=("empty_folder",))
        
        # Build message
        msg = f"Found {len(empty)} empty folders (no EDF or TSV files):\n\n"
        for folder_name, other_count in empty:
            note = f" ({other_count} other files)" if other_count > 0 else ""
            msg += f"  • {folder_name}{note}\n"
        
        msg += "\nWould you like to delete these folders?"
        
        if not messagebox.askyesno("Empty Folders", msg):
            return
        
        # Confirm deletion
        if not messagebox.askyesno("Confirm Delete", 
                "Are you sure? This cannot be undone."):
            return
        
        # Delete folders
        deleted = 0
        for folder_name, _ in empty:
            if self.folder_manager.delete_folder(folder_name):
                deleted += 1
        
        self.refresh_table()
        messagebox.showinfo("Deleted", f"Deleted {deleted} of {len(empty)} empty folders.")
    
    # ==================== NEW: SYNC FILES TO FOLDERS ====================
    
    def sync_files_to_folders(self):
        """Sync file session numbers to match their folder session numbers."""
        if not self.root_dir or not self.folder_manager:
            messagebox.showinfo("Info", "Select a subject root first.")
            return
        
        # First check for discrepancies
        discrepancies = self.folder_manager.get_discrepant_files()
        
        if not discrepancies:
            messagebox.showinfo("Sync Files", "No discrepancies found. All files match their folders.")
            return
        
        # Show preview
        msg = f"Found {len(discrepancies)} files with mismatched session numbers:\n\n"
        
        for rel_path, folder_ses, file_ses in discrepancies[:15]:  # Limit display
            basename = os.path.basename(rel_path)
            msg += f"  • {basename}\n"
            msg += f"      Folder: {folder_ses}, File: {file_ses}\n"
        
        if len(discrepancies) > 15:
            msg += f"\n  ... and {len(discrepancies) - 15} more\n"
        
        msg += "\nThis will rename files to match their folder's session number."
        msg += "\nProceed?"
        
        if not messagebox.askyesno("Sync Files to Folders", msg):
            return
        
        # Perform sync
        results = self.folder_manager.sync_files_to_folders(self.dry_run.get())
        
        # Also update TSV if not dry run
        if not self.dry_run.get() and self.tsv_manager.rows:
            self._save_undo_state("Sync files to folders (TSV update)")
            
            # Update TSV rows to match
            for i, row in enumerate(self.tsv_manager.rows):
                filepath = row.get("filename", "")
                if not filepath:
                    continue
                
                folder_ses = extract_session_from_filename(filepath)
                basename = os.path.basename(filepath)
                file_ses = extract_session_from_basename(basename)
                
                if folder_ses and file_ses and folder_ses != file_ses:
                    # Update the filename in TSV
                    new_basename = basename.replace(file_ses, folder_ses)
                    new_filepath = filepath.replace(basename, new_basename)
                    row["filename"] = new_filepath
            
            # Save TSV
            if not self.tsv_manager.save():
                messagebox.showwarning("Warning", "Files renamed but TSV save failed.")
        
        self.refresh_table()
        self._auto_check_discrepancies()
        
        msg = "Dry run complete." if self.dry_run.get() else f"Synced {len(results)} files."
        messagebox.showinfo("Sync Complete", msg)
    
    # ==================== NEW: VALIDATE ALL ====================
    
    def validate_all(self):
        """Run all validation checks at once."""
        if not self.root_dir:
            messagebox.showinfo("Info", "Select a subject root first.")
            return
        
        log_line(self.log_path, "===== VALIDATE ALL START =====")
        
        results = []
        
        # 1. Check TSV vs Folders
        tsv_sessions = self.tsv_manager.get_all_sessions()
        folder_sessions = self.folder_manager.get_session_folders() if self.folder_manager else set()
        missing_folders = sorted(tsv_sessions - folder_sessions, key=extract_session_number)
        extra_folders = sorted(folder_sessions - tsv_sessions, key=extract_session_number)
        
        if missing_folders:
            results.append(f"❌ Missing folders: {len(missing_folders)}")
        else:
            results.append("✓ All TSV sessions have folders")
        
        if extra_folders:
            results.append(f"⚠️ Extra folders (not in TSV): {len(extra_folders)}")
        
        # 2. Check discrepancies
        discrepancies = self.session_manager.find_discrepancies(self.tsv_manager.rows)
        self.current_discrepancies = {d[0] for d in discrepancies}
        
        if discrepancies:
            results.append(f"⚠️ Folder/filename discrepancies: {len(discrepancies)}")
        else:
            results.append("✓ All filenames match their folders")
        
        # 3. Check empty folders
        empty_folders = self.folder_manager.find_empty_folders() if self.folder_manager else []
        if empty_folders:
            results.append(f"⚠️ Empty folders: {len(empty_folders)}")
        else:
            results.append("✓ No empty folders")
        
        # 4. Check duplicates
        duplicates = self.duplicate_finder.find_duplicates(self.tsv_manager.rows)
        if duplicates:
            total_dup = sum(len(v) for v in duplicates.values())
            results.append(f"⚠️ Duplicate recordings: {len(duplicates)} groups ({total_dup} files)")
        else:
            results.append("✓ No duplicate recordings")
        
        # Refresh and apply all highlighting
        self.refresh_table()
        
        # Apply missing folder tags
        for iid in self.tree.get_children(""):
            folder = self.tree.set(iid, "Folder")
            tags = set(self.tree.item(iid, "tags"))
            
            if folder in missing_folders:
                tags.add("missing_folder")
            
            # Check duplicates
            acq = self.tree.set(iid, "Acq Time")
            dur = self.tree.set(iid, "Duration (h)")
            if self.duplicate_finder.is_duplicate_display_values(acq, dur, duplicates):
                tags.add("dup_row")
            
            self.tree.item(iid, tags=tuple(tags))
        
        # Add extra folders
        for ex in extra_folders:
            self.tree.insert("", "end",
                           values=(ex, "N/A", "N/A", "N/A", "N/A"),
                           tags=("extra_folder",))
        
        # Add empty folders
        for folder_name, other_count in empty_folders:
            note = f"({other_count} other files)" if other_count > 0 else "(empty)"
            self.tree.insert("", "end",
                           values=(folder_name, note, "N/A", "N/A", "N/A"),
                           tags=("empty_folder",))
        
        log_line(self.log_path, "===== VALIDATE ALL END =====")
        
        # Show summary
        msg = "Validation Results:\n\n" + "\n".join(results)
        messagebox.showinfo("Validate All", msg)
    
    # ==================== IMPORT SESSIONS ====================
    
    def import_sessions_dialog(self):
        """Show dialog to import sessions from another folder."""
        if not self.root_dir:
            messagebox.showinfo("Info", "Select a subject root first.")
            return
        
        # Select source folder
        source = filedialog.askdirectory(
            title="Select SOURCE subject folder to import from"
        )
        if not source:
            return
        
        # Scan source
        scan = self.import_manager.scan_source_folder(source)
        
        if not scan["sessions"]:
            messagebox.showinfo("Info", f"No sessions found in:\n{source}")
            return
        
        # Show what was found
        msg = f"Found in source:\n"
        msg += f"  Sessions: {', '.join(scan['sessions'])}\n"
        msg += f"  EDF files: {scan['edf_count']}\n"
        msg += f"  TSV: {'Yes' if scan['tsv_path'] else 'No'}\n\n"
        
        # Get current sessions
        dest_sessions = self.tsv_manager.get_all_sessions()
        
        # Calculate mapping
        mapping = self.import_manager.calculate_import_mapping(
            scan["sessions"], dest_sessions
        )
        
        msg += "Import mapping:\n"
        for src, dst in mapping.items():
            msg += f"  {src} -> {dst}\n"
        
        msg += "\nDefault action: MOVE (source folders will be relocated)"
        msg += "\nClick Yes to MOVE, No to COPY instead, Cancel to abort."
        
        # Three-way dialog: Yes=Move, No=Copy, Cancel=Abort
        result = messagebox.askyesnocancel("Import Sessions", msg)
        
        if result is None:  # Cancel
            return
        
        use_copy = not result  # Yes=Move (False), No=Copy (True)
        action = "copy" if use_copy else "move"
        
        # Get subject names
        dest_subject = os.path.basename(os.path.normpath(self.root_dir))
        src_subject = os.path.basename(os.path.normpath(source))
        
        # Perform import
        imported_rows = self.import_manager.import_sessions(
            source, self.root_dir, mapping,
            dest_subject, self.dry_run.get(), use_copy=use_copy
        )
        
        # If source has TSV, use that for metadata
        if scan["tsv_path"]:
            tsv_rows = self.import_manager.import_tsv_rows(
                scan["tsv_path"], mapping, src_subject, dest_subject
            )
            if tsv_rows:
                imported_rows = tsv_rows
        
        # Add to current TSV
        if imported_rows and not self.dry_run.get():
            self.tsv_manager.add_rows(imported_rows)
        
        self.refresh_table()
        
        msg = f"Import {'preview' if self.dry_run.get() else 'complete'} ({action}).\n"
        msg += f"Added {len(imported_rows)} files."
        messagebox.showinfo("Import", msg)
    
    # ==================== GENERATE TSV ====================
    
    def generate_tsv_from_edfs(self):
        """Generate TSV from EDF files in root directory."""
        if not self.root_dir:
            messagebox.showinfo("Info", "Select a subject root first.")
            return
        
        if not is_edfreader_available():
            messagebox.showerror("Error", "EDFreader not available.")
            return
        
        base = os.path.basename(os.path.normpath(self.root_dir))
        out_path = os.path.join(self.root_dir, f"{base}_scans.tsv")
        
        # Backup if exists
        if os.path.exists(out_path):
            ts = get_timestamp_suffix()
            backup = os.path.join(self.root_dir, f"{base}_scans_backup_{ts}.tsv")
            try:
                shutil.copy2(out_path, backup)
                log_line(self.log_path, f"Backup: {backup}")
            except Exception as e:
                messagebox.showerror("Error", f"Backup failed:\n{e}")
                return
        
        # Generate records
        records = generate_tsv_records(self.root_dir, self.log_path)
        
        if not records:
            messagebox.showinfo("Info", "No EDF files found.")
            return
        
        # Write TSV
        try:
            import csv
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter="\t", lineterminator="\n")
                writer.writerow(DEFAULT_TSV_COLUMNS)
                for rec in records:
                    writer.writerow(list(rec))
            
            log_line(self.log_path, f"Generated TSV: {out_path}")
            messagebox.showinfo("Generate TSV", f"Created:\n{out_path}\n\n{len(records)} records.")
            
            # Reload
            self.tsv_manager.load(out_path)
            self.refresh_table()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to write TSV:\n{e}")
            if EXCEPTION_DEBUG:
                raise e


# ==================== MAIN ====================

def main():
    """Main entry point."""
    root = tk.Tk()
    app = BIDSShifterGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
