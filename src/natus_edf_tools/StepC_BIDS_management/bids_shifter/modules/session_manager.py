# -*- coding: utf-8 -*-
"""
Session manipulation for BIDS Shifter GUI.
Handles shifting, swapping, and normalizing session numbers.
"""

import os
import re
import shutil
from .config import SESSION_PATTERN, BIDS_FILE_EXTENSIONS, EXCEPTION_DEBUG
from .utils import (
    extract_session_from_filename, 
    extract_session_from_basename,
    extract_session_number, 
    is_bids_file,
    check_session_discrepancy,
    log_line
)


class SessionManager:
    """Manages session manipulation operations."""
    
    def __init__(self, log_path=None):
        self.log_path = log_path
    
    def get_ordered_sessions(self, rows):
        """
        Get unique sessions from rows, sorted by session number.
        
        Args:
            rows: List of TSV row dicts
        
        Returns:
            List of session strings like ["ses-001", "ses-002", ...]
        """
        sessions = []
        seen = set()
        
        for row in rows:
            fn = row.get("filename", "")
            ses = extract_session_from_filename(fn)
            if ses and ses not in seen:
                seen.add(ses)
                sessions.append(ses)
        
        # Sort by numeric part
        sessions.sort(key=extract_session_number)
        return sessions
    
    def shift_sessions_in_range(self, rows, start, end, delta):
        """
        Shift session numbers within a range by a delta amount.
        
        Args:
            rows: List of TSV row dicts (modified in place)
            start: Start session number (inclusive)
            end: End session number (inclusive)
            delta: Amount to shift (positive or negative)
        
        Returns:
            Number of rows modified
        """
        modified = 0
        
        for row in rows:
            fn = row.get("filename", "")
            folder = extract_session_from_filename(fn)
            if not folder:
                continue
            
            num = extract_session_number(folder)
            if start <= num <= end:
                new_num = num + delta
                new_folder = f"ses-{new_num:03d}"
                row["filename"] = fn.replace(folder, new_folder)
                modified += 1
        
        log_line(self.log_path, f"Shifted sessions {start}-{end} by {delta} ({modified} rows)")
        return modified
    
    def swap_sessions(self, rows, ses_a, ses_b):
        """
        Swap two session identifiers in all rows.
        Uses a temp token to avoid collisions.
        
        Args:
            rows: List of TSV row dicts (modified in place)
            ses_a: First session string (e.g., "ses-110")
            ses_b: Second session string (e.g., "ses-111")
        
        Returns:
            True if swap was performed
        """
        if not ses_a or not ses_b or ses_a == ses_b:
            return False
        
        tmp = "__SES_SWAP_TMP__"
        
        # Pass 1: a -> tmp
        for row in rows:
            fn = row.get("filename", "")
            if ses_a in fn:
                row["filename"] = fn.replace(ses_a, tmp)
        
        # Pass 2: b -> a
        for row in rows:
            fn = row.get("filename", "")
            if ses_b in fn:
                row["filename"] = fn.replace(ses_b, ses_a)
        
        # Pass 3: tmp -> b
        for row in rows:
            fn = row.get("filename", "")
            if tmp in fn:
                row["filename"] = fn.replace(tmp, ses_b)
        
        log_line(self.log_path, f"Swapped sessions: {ses_a} <-> {ses_b}")
        return True
    
    def increment_session(self, rows, session):
        """
        Increment a session number by 1.
        
        Args:
            rows: List of TSV row dicts (modified in place)
            session: Session string to increment (e.g., "ses-002")
        
        Returns:
            New session string, or None if failed
        """
        if not session:
            return None
        
        num = extract_session_number(session)
        new_num = num + 1
        new_session = f"ses-{new_num:03d}"
        
        # Update all rows with this session
        modified = 0
        for row in rows:
            fn = row.get("filename", "")
            if extract_session_from_filename(fn) == session:
                row["filename"] = fn.replace(session, new_session)
                modified += 1
        
        if modified > 0:
            log_line(self.log_path, f"Incremented session: {session} -> {new_session} ({modified} rows)")
            return new_session
        return None
    
    def decrement_session(self, rows, session):
        """
        Decrement a session number by 1.
        
        Args:
            rows: List of TSV row dicts (modified in place)
            session: Session string to decrement (e.g., "ses-002")
        
        Returns:
            New session string, or None if failed or already at ses-001
        """
        if not session:
            return None
        
        num = extract_session_number(session)
        if num <= 1:
            return None  # Can't go below ses-001
        
        new_num = num - 1
        new_session = f"ses-{new_num:03d}"
        
        # Update all rows with this session
        modified = 0
        for row in rows:
            fn = row.get("filename", "")
            if extract_session_from_filename(fn) == session:
                row["filename"] = fn.replace(session, new_session)
                modified += 1
        
        if modified > 0:
            log_line(self.log_path, f"Decremented session: {session} -> {new_session} ({modified} rows)")
            return new_session
        return None
    
    def normalize_to_sequence(self, rows, original_rows, view_order):
        """
        Renumber sessions to ses-001..ses-N based on view order.
        
        Args:
            rows: Current TSV row dicts (modified in place)
            original_rows: Original TSV row dicts (for stable detection)
            view_order: List of session strings in desired order
        
        Returns:
            Dict mapping old session -> new session for changed sessions
        """
        if not view_order:
            return {}
        
        # Build mapping: current -> target
        target_map = {}
        for idx, ses in enumerate(view_order, start=1):
            target_map[ses] = f"ses-{idx:03d}"
        
        # Check if any changes needed
        if all(k == v for k, v in target_map.items()):
            return {}
        
        log_line(self.log_path, "===== NORMALIZE (preview) START =====")
        changes = {}
        
        # Perform remap using original rows for stable detection
        for i, (orig, cur) in enumerate(zip(original_rows, rows)):
            orig_fn = orig.get("filename", "")
            old_ses = extract_session_from_filename(orig_fn)
            if not old_ses:
                continue
            
            new_ses = target_map.get(old_ses)
            if not new_ses or new_ses == old_ses:
                continue
            
            cur["filename"] = orig_fn.replace(old_ses, new_ses)
            if old_ses != new_ses:
                changes[old_ses] = new_ses
                log_line(self.log_path, f"Map: {old_ses} -> {new_ses}")
        
        log_line(self.log_path, "===== NORMALIZE (preview) END =====")
        return changes
    
    def remap_session_in_filename(self, filename, old_ses, new_ses):
        """
        Replace session identifier in a filename path.
        
        Args:
            filename: Original filename path
            old_ses: Session to replace
            new_ses: New session value
        
        Returns:
            Updated filename
        """
        return filename.replace(old_ses, new_ses) if old_ses and new_ses else filename
    
    def find_discrepancies(self, rows):
        """
        Find rows where folder session doesn't match filename session.
        
        Args:
            rows: List of TSV row dicts
        
        Returns:
            List of (row_index, folder_session, filename_session) tuples
        """
        discrepancies = []
        
        for i, row in enumerate(rows):
            filepath = row.get("filename", "")
            if not filepath:
                continue
            
            basename = os.path.basename(filepath)
            result = check_session_discrepancy(filepath, basename)
            
            if result:
                folder_ses, filename_ses = result
                discrepancies.append((i, folder_ses, filename_ses))
                log_line(self.log_path, f"Discrepancy found: {filepath} (folder={folder_ses}, file={filename_ses})")
        
        return discrepancies


class FolderManager:
    """Manages filesystem operations for session folders."""
    
    def __init__(self, root_dir, log_path=None):
        self.root_dir = root_dir
        self.log_path = log_path
    
    def get_session_folders(self):
        """
        Get all session folders in root directory.
        
        Returns:
            Set of session folder names like {"ses-001", "ses-002"}
        """
        from .config import SESSION_FOLDER_PATTERN
        
        folders = set()
        if not self.root_dir or not os.path.isdir(self.root_dir):
            return folders
        
        for item in os.listdir(self.root_dir):
            if SESSION_FOLDER_PATTERN.match(item):
                full_path = os.path.join(self.root_dir, item)
                if os.path.isdir(full_path):
                    folders.add(item)
        
        return folders
    
    def find_empty_folders(self):
        """
        Find session folders that contain no EDF or TSV files.
        
        Returns:
            List of (folder_name, file_count) tuples for empty folders
            file_count is the number of other files (non-EDF, non-TSV)
        """
        from .config import SESSION_FOLDER_PATTERN
        
        empty_folders = []
        
        if not self.root_dir or not os.path.isdir(self.root_dir):
            return empty_folders
        
        for item in os.listdir(self.root_dir):
            if not SESSION_FOLDER_PATTERN.match(item):
                continue
            
            folder_path = os.path.join(self.root_dir, item)
            if not os.path.isdir(folder_path):
                continue
            
            # Count files by type
            edf_count = 0
            tsv_count = 0
            other_count = 0
            
            for root, dirs, files in os.walk(folder_path):
                for fn in files:
                    lower = fn.lower()
                    if lower.endswith(".edf"):
                        edf_count += 1
                    elif lower.endswith(".tsv"):
                        tsv_count += 1
                    else:
                        other_count += 1
            
            # Empty means no EDF and no TSV (other files can exist)
            if edf_count == 0 and tsv_count == 0:
                empty_folders.append((item, other_count))
                log_line(self.log_path, f"Empty folder found: {item} ({other_count} other files)")
        
        return empty_folders
    
    def delete_folder(self, folder_name):
        """
        Delete a session folder.
        
        Args:
            folder_name: Session folder name like "ses-001"
        
        Returns:
            True if deleted successfully
        """
        folder_path = os.path.join(self.root_dir, folder_name)
        
        if not os.path.isdir(folder_path):
            log_line(self.log_path, f"Folder not found: {folder_path}")
            return False
        
        try:
            shutil.rmtree(folder_path)
            log_line(self.log_path, f"Deleted folder: {folder_name}")
            return True
        except Exception as e:
            log_line(self.log_path, f"Error deleting folder {folder_name}: {e}")
            if EXCEPTION_DEBUG:
                raise e
            return False
    
    def sync_files_to_folders(self, dry_run=False):
        """
        Rename files to match their folder's session number.
        
        Args:
            dry_run: If True, only report what would be done
        
        Returns:
            List of (old_path, new_path, status) tuples
        """
        from .config import SESSION_FOLDER_PATTERN
        
        results = []
        
        if not self.root_dir or not os.path.isdir(self.root_dir):
            return results
        
        log_line(self.log_path, f"===== SYNC FILES TO FOLDERS {'(DRY RUN)' if dry_run else ''} =====")
        
        for session_folder in os.listdir(self.root_dir):
            if not SESSION_FOLDER_PATTERN.match(session_folder):
                continue
            
            folder_path = os.path.join(self.root_dir, session_folder)
            if not os.path.isdir(folder_path):
                continue
            
            folder_ses_num = session_folder.split("-")[1]  # "001"
            
            # Walk all files in this session folder
            for root, dirs, files in os.walk(folder_path):
                for fn in files:
                    # Check if this is a BIDS file with session in name
                    if not is_bids_file(fn):
                        continue
                    
                    file_ses = extract_session_from_basename(fn)
                    if not file_ses:
                        continue  # No session in filename
                    
                    # Check if mismatch
                    if file_ses == session_folder:
                        continue  # Already matches
                    
                    # Build new filename
                    new_fn = SESSION_PATTERN.sub(f"ses-{folder_ses_num}", fn)
                    
                    old_path = os.path.join(root, fn)
                    new_path = os.path.join(root, new_fn)
                    
                    if dry_run:
                        log_line(self.log_path, f"[DRY] Would rename: {fn} -> {new_fn}")
                        results.append((old_path, new_path, "dry_run"))
                    else:
                        try:
                            os.rename(old_path, new_path)
                            log_line(self.log_path, f"Renamed: {fn} -> {new_fn}")
                            results.append((old_path, new_path, "renamed"))
                        except Exception as e:
                            log_line(self.log_path, f"Error renaming {fn}: {e}")
                            results.append((old_path, new_path, f"error: {e}"))
                            if EXCEPTION_DEBUG:
                                raise e
        
        log_line(self.log_path, f"===== SYNC COMPLETE: {len(results)} files =====")
        return results
    
    def get_discrepant_files(self):
        """
        Find all files where filename session doesn't match folder session.
        
        Returns:
            List of (relative_path, folder_session, filename_session) tuples
        """
        from .config import SESSION_FOLDER_PATTERN
        
        discrepancies = []
        
        if not self.root_dir or not os.path.isdir(self.root_dir):
            return discrepancies
        
        for session_folder in os.listdir(self.root_dir):
            if not SESSION_FOLDER_PATTERN.match(session_folder):
                continue
            
            folder_path = os.path.join(self.root_dir, session_folder)
            if not os.path.isdir(folder_path):
                continue
            
            for root, dirs, files in os.walk(folder_path):
                for fn in files:
                    if not is_bids_file(fn):
                        continue
                    
                    file_ses = extract_session_from_basename(fn)
                    if not file_ses:
                        continue
                    
                    if file_ses != session_folder:
                        rel_path = os.path.relpath(os.path.join(root, fn), self.root_dir)
                        discrepancies.append((rel_path, session_folder, file_ses))
        
        return discrepancies
    
    def rename_folders(self, old_to_new_map, dry_run=False):
        """
        Rename session folders according to mapping.
        Uses temp prefix to handle collisions.
        
        Args:
            old_to_new_map: Dict mapping old session -> new session
            dry_run: If True, only log what would happen
        
        Returns:
            True if all renames succeeded (or dry run)
        """
        if not old_to_new_map:
            return True
        
        temp_prefix = "__tmp__"
        temp_map = {}  # temp_path -> final_folder
        
        try:
            if dry_run:
                log_line(self.log_path, "DRY RUN: Skipping filesystem renames.")
                for old, new in old_to_new_map.items():
                    log_line(self.log_path, f"[DRY] Would rename {old} -> {new}")
                return True
            
            # Phase 1: Rename to temp names
            for old_ses, new_ses in old_to_new_map.items():
                old_path = os.path.join(self.root_dir, old_ses)
                if not os.path.isdir(old_path):
                    log_line(self.log_path, f"WARNING: folder not found: {old_path}")
                    continue
                
                temp_name = f"{temp_prefix}{new_ses}"
                temp_path = os.path.join(self.root_dir, temp_name)
                
                # Handle collision with existing temp
                idx = 0
                base_temp = temp_path
                while os.path.exists(temp_path):
                    idx += 1
                    temp_path = f"{base_temp}_{idx}"
                
                os.rename(old_path, temp_path)
                log_line(self.log_path, f"RENAMED (temp): {old_ses} -> {os.path.basename(temp_path)}")
                temp_map[temp_path] = new_ses
            
            # Phase 2: Rename files inside and move to final names
            for temp_path, final_folder in temp_map.items():
                # Rename files with session numbers
                for root, dirs, files in os.walk(temp_path):
                    for fn in files:
                        match = SESSION_PATTERN.search(fn)
                        if match:
                            final_num = final_folder.split("-")[1]
                            new_fn = SESSION_PATTERN.sub(f"ses-{final_num}", fn)
                            if new_fn != fn:
                                os.rename(
                                    os.path.join(root, fn),
                                    os.path.join(root, new_fn)
                                )
                                log_line(self.log_path, f"RENAMED FILE: {fn} -> {new_fn}")
                
                # Move to final location
                final_path = os.path.join(self.root_dir, final_folder)
                if os.path.exists(final_path):
                    log_line(self.log_path, f"WARNING: final folder exists, adding suffix: {final_folder}")
                    idx = 1
                    while os.path.exists(final_path):
                        final_path = f"{final_path}_{idx}"
                        idx += 1
                
                os.rename(temp_path, final_path)
                log_line(self.log_path, f"RENAMED (final): {os.path.basename(temp_path)} -> {os.path.basename(final_path)}")
            
            return True
            
        except Exception as e:
            log_line(self.log_path, f"ERROR in folder rename: {e}")
            if EXCEPTION_DEBUG:
                raise e
            return False
    
    def find_edf_files(self):
        """
        Find all EDF files recursively in root directory.
        
        Returns:
            List of (full_path, relative_path) tuples
        """
        edf_files = []
        
        for root, dirs, files in os.walk(self.root_dir):
            for fn in files:
                if fn.lower().endswith(".edf"):
                    full_path = os.path.join(root, fn)
                    rel_path = os.path.relpath(full_path, self.root_dir).replace("\\", "/")
                    edf_files.append((full_path, rel_path))
        
        return edf_files
