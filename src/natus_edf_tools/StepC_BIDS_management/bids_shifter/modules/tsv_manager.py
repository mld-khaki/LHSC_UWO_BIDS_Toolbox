# -*- coding: utf-8 -*-
"""
TSV file management for BIDS Shifter GUI.
Handles loading, saving, and backup of TSV files.
"""

import os
import csv
import shutil
from .config import DEFAULT_TSV_COLUMNS, EXCEPTION_DEBUG
from .utils import log_line, get_timestamp_suffix


class TSVManager:
    """Manages TSV file operations for BIDS scans files."""
    
    def __init__(self, log_path=None):
        self.log_path = log_path
        self.header = []
        self.rows = []
        self.original_rows = []
        self.tsv_path = ""
    
    def load(self, path):
        """
        Load a TSV file.
        
        Args:
            path: Path to TSV file
        
        Returns:
            True if successful, False otherwise
        
        Raises:
            Exception if EXCEPTION_DEBUG is True and loading fails
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                self.header = reader.fieldnames if reader.fieldnames else []
                self.rows = [row for row in reader]
                self.original_rows = [dict(r) for r in self.rows]
            self.tsv_path = path
            log_line(self.log_path, f"Loaded TSV: {path}")
            return True
        except Exception as e:
            log_line(self.log_path, f"ERROR loading TSV: {e}")
            if EXCEPTION_DEBUG:
                raise e
            return False
    
    def save(self, path=None):
        """
        Save TSV to file.
        
        Args:
            path: Path to save to (uses current path if None)
        
        Returns:
            True if successful, False otherwise
        """
        save_path = path or self.tsv_path
        if not save_path:
            log_line(self.log_path, "ERROR: No TSV path specified for save")
            return False
        
        try:
            header = self.header if self.header else DEFAULT_TSV_COLUMNS
            with open(save_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f, 
                    fieldnames=header, 
                    delimiter="\t", 
                    lineterminator="\n",
                    extrasaction="ignore"
                )
                writer.writeheader()
                for row in self.rows:
                    writer.writerow(row)
            log_line(self.log_path, f"TSV saved: {save_path}")
            return True
        except Exception as e:
            log_line(self.log_path, f"ERROR saving TSV: {e}")
            if EXCEPTION_DEBUG:
                raise e
            return False
    
    def backup(self, path=None):
        """
        Create a backup of the TSV file.
        
        Args:
            path: Path to backup (uses current path if None)
        
        Returns:
            Backup file path if successful, None otherwise
        """
        source_path = path or self.tsv_path
        if not source_path or not os.path.exists(source_path):
            return None
        
        ts = get_timestamp_suffix()
        base, ext = os.path.splitext(source_path)
        backup_path = f"{base}_backup_{ts}{ext}"
        
        try:
            shutil.copy2(source_path, backup_path)
            log_line(self.log_path, f"Backup created: {backup_path}")
            return backup_path
        except Exception as e:
            log_line(self.log_path, f"ERROR creating backup: {e}")
            if EXCEPTION_DEBUG:
                raise e
            return None
    
    def has_changes(self):
        """Check if there are unsaved changes."""
        if len(self.rows) != len(self.original_rows):
            return True
        for orig, cur in zip(self.original_rows, self.rows):
            if orig.get("filename", "") != cur.get("filename", ""):
                return True
        return False
    
    def commit_changes(self):
        """Mark current rows as the new baseline (after successful save)."""
        self.original_rows = [dict(r) for r in self.rows]
    
    def get_changed_sessions(self):
        """
        Get mapping of old session -> new session for changed rows.
        
        Returns:
            Dict mapping old session names to new session names
        """
        from .utils import extract_session_from_filename
        
        old_to_new = {}
        for orig, cur in zip(self.original_rows, self.rows):
            orig_fn = orig.get("filename", "")
            cur_fn = cur.get("filename", "")
            orig_ses = extract_session_from_filename(orig_fn)
            cur_ses = extract_session_from_filename(cur_fn)
            if orig_ses and cur_ses and orig_ses != cur_ses:
                old_to_new[orig_ses] = cur_ses
        return old_to_new
    
    def add_rows(self, new_rows):
        """
        Add new rows to the TSV.
        
        Args:
            new_rows: List of dict rows to add
        """
        self.rows.extend(new_rows)
        # Sort by acq_time
        self.rows.sort(key=lambda r: r.get("acq_time", ""))
        log_line(self.log_path, f"Added {len(new_rows)} rows to TSV")
    
    def get_all_sessions(self):
        """
        Get all unique session identifiers from current rows.
        
        Returns:
            Set of session strings like {"ses-001", "ses-002", ...}
        """
        from .utils import extract_session_from_filename
        
        sessions = set()
        for row in self.rows:
            ses = extract_session_from_filename(row.get("filename", ""))
            if ses:
                sessions.add(ses)
        return sessions
