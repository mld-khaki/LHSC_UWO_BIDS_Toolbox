# -*- coding: utf-8 -*-
"""
File lock checker for BIDS Shifter GUI.
Tests files and folders for accessibility before performing rename/move operations.

Strategy: Temporarily rename files/folders to detect access violations early.
If any file is locked, report it to the user and abort the operation.
"""

import os
import tempfile
from .config import SESSION_FOLDER_PATTERN, BIDS_FILE_EXTENSIONS, EXCEPTION_DEBUG
from .utils import log_line


class LockCheckResult:
    """Result of a lock check operation."""
    
    def __init__(self):
        self.locked_files = []      # List of (path, error_message)
        self.locked_folders = []    # List of (path, error_message)
        self.accessible_files = []  # List of paths that passed the check
        self.accessible_folders = [] # List of folders that passed the check
        self.total_checked = 0
    
    @property
    def has_locks(self):
        """Return True if any files or folders are locked."""
        return len(self.locked_files) > 0 or len(self.locked_folders) > 0
    
    @property
    def all_accessible(self):
        """Return True if all checked items are accessible."""
        return not self.has_locks
    
    def format_summary(self):
        """Format a human-readable summary of the lock check."""
        if self.all_accessible:
            return f"✓ All {self.total_checked} items are accessible."
        
        lines = []
        lines.append(f"❌ Found {len(self.locked_files)} locked files and {len(self.locked_folders)} locked folders")
        lines.append("")
        
        if self.locked_folders:
            lines.append("Locked Folders:")
            for path, error in self.locked_folders[:10]:  # Limit display
                folder_name = os.path.basename(path)
                lines.append(f"  • {folder_name}: {error}")
            if len(self.locked_folders) > 10:
                lines.append(f"  ... and {len(self.locked_folders) - 10} more")
            lines.append("")
        
        if self.locked_files:
            lines.append("Locked Files:")
            for path, error in self.locked_files[:10]:
                filename = os.path.basename(path)
                lines.append(f"  • {filename}: {error}")
            if len(self.locked_files) > 10:
                lines.append(f"  ... and {len(self.locked_files) - 10} more")
        
        return "\n".join(lines)
    
    def format_detailed_report(self):
        """Format a detailed report for logging."""
        lines = ["===== LOCK CHECK REPORT ====="]
        lines.append(f"Total checked: {self.total_checked}")
        lines.append(f"Accessible files: {len(self.accessible_files)}")
        lines.append(f"Accessible folders: {len(self.accessible_folders)}")
        lines.append(f"Locked files: {len(self.locked_files)}")
        lines.append(f"Locked folders: {len(self.locked_folders)}")
        
        if self.locked_folders:
            lines.append("\n--- Locked Folders ---")
            for path, error in self.locked_folders:
                lines.append(f"  {path}: {error}")
        
        if self.locked_files:
            lines.append("\n--- Locked Files ---")
            for path, error in self.locked_files:
                lines.append(f"  {path}: {error}")
        
        lines.append("===== END LOCK CHECK REPORT =====")
        return "\n".join(lines)


class FileLockChecker:
    """
    Checks files and folders for accessibility before rename/move operations.
    
    Strategy:
    1. For files: Try to temporarily rename from file.ext to file_.ext_
    2. If rename succeeds, rename back immediately
    3. If rename fails, the file is locked
    4. Collect all locked items and report before proceeding
    """
    
    def __init__(self, log_path=None):
        self.log_path = log_path
        self._temp_suffix = "_.lock_test_"
    
    def check_file_accessibility(self, filepath):
        """
        Check if a single file can be renamed (i.e., is not locked).
        
        Args:
            filepath: Full path to the file
        
        Returns:
            Tuple of (is_accessible: bool, error_message: str or None)
        """
        if not os.path.exists(filepath):
            return False, "File does not exist"
        
        if not os.path.isfile(filepath):
            return False, "Path is not a file"
        
        # Create temporary name
        base, ext = os.path.splitext(filepath)
        temp_path = f"{base}{self._temp_suffix}{ext}"
        
        # Ensure temp path doesn't already exist
        counter = 0
        while os.path.exists(temp_path):
            counter += 1
            temp_path = f"{base}{self._temp_suffix}{counter}{ext}"
        
        try:
            # Try to rename to temp
            os.rename(filepath, temp_path)
            
            # Immediately rename back
            os.rename(temp_path, filepath)
            
            return True, None
            
        except PermissionError as e:
            return False, f"Permission denied: {e}"
        except OSError as e:
            # Try to restore if partial rename happened
            if os.path.exists(temp_path) and not os.path.exists(filepath):
                try:
                    os.rename(temp_path, filepath)
                except:
                    pass
            return False, f"OS error: {e}"
        except Exception as e:
            # Try to restore
            if os.path.exists(temp_path) and not os.path.exists(filepath):
                try:
                    os.rename(temp_path, filepath)
                except:
                    pass
            return False, f"Unexpected error: {e}"
    
    def check_folder_accessibility(self, folderpath):
        """
        Check if a folder can be renamed (i.e., is not locked).
        
        Args:
            folderpath: Full path to the folder
        
        Returns:
            Tuple of (is_accessible: bool, error_message: str or None)
        """
        if not os.path.exists(folderpath):
            return False, "Folder does not exist"
        
        if not os.path.isdir(folderpath):
            return False, "Path is not a folder"
        
        # Create temporary name
        temp_path = f"{folderpath}{self._temp_suffix}"
        
        # Ensure temp path doesn't already exist
        counter = 0
        while os.path.exists(temp_path):
            counter += 1
            temp_path = f"{folderpath}{self._temp_suffix}{counter}"
        
        try:
            # Try to rename to temp
            os.rename(folderpath, temp_path)
            
            # Immediately rename back
            os.rename(temp_path, folderpath)
            
            return True, None
            
        except PermissionError as e:
            return False, f"Permission denied: {e}"
        except OSError as e:
            # Try to restore if partial rename happened
            if os.path.exists(temp_path) and not os.path.exists(folderpath):
                try:
                    os.rename(temp_path, folderpath)
                except:
                    pass
            return False, f"OS error: {e}"
        except Exception as e:
            # Try to restore
            if os.path.exists(temp_path) and not os.path.exists(folderpath):
                try:
                    os.rename(temp_path, folderpath)
                except:
                    pass
            return False, f"Unexpected error: {e}"
    
    def check_session_folder(self, session_path, check_files=True):
        """
        Check if a session folder and all its contents can be renamed.
        
        Args:
            session_path: Full path to the session folder
            check_files: If True, also check all files inside
        
        Returns:
            LockCheckResult object
        """
        result = LockCheckResult()
        
        if not os.path.isdir(session_path):
            result.locked_folders.append((session_path, "Folder does not exist"))
            result.total_checked = 1
            return result
        
        # First check the folder itself
        accessible, error = self.check_folder_accessibility(session_path)
        result.total_checked += 1
        
        if accessible:
            result.accessible_folders.append(session_path)
        else:
            result.locked_folders.append((session_path, error))
            # If folder itself is locked, don't bother checking files
            return result
        
        if not check_files:
            return result
        
        # Check all files in the folder
        for root, dirs, files in os.walk(session_path):
            for fn in files:
                filepath = os.path.join(root, fn)
                result.total_checked += 1
                
                accessible, error = self.check_file_accessibility(filepath)
                
                if accessible:
                    result.accessible_files.append(filepath)
                else:
                    result.locked_files.append((filepath, error))
        
        return result
    
    def check_sessions_for_operation(self, root_dir, sessions_to_check):
        """
        Check multiple session folders before a rename/move operation.
        
        Args:
            root_dir: Root directory containing session folders
            sessions_to_check: List of session names (e.g., ["ses-001", "ses-002"])
        
        Returns:
            LockCheckResult object with all results combined
        """
        log_line(self.log_path, f"===== LOCK CHECK START ({len(sessions_to_check)} sessions) =====")
        
        combined_result = LockCheckResult()
        
        for session in sessions_to_check:
            session_path = os.path.join(root_dir, session)
            
            if not os.path.exists(session_path):
                log_line(self.log_path, f"  Skipping {session} (does not exist)")
                continue
            
            log_line(self.log_path, f"  Checking {session}...")
            
            result = self.check_session_folder(session_path, check_files=True)
            
            # Merge results
            combined_result.locked_files.extend(result.locked_files)
            combined_result.locked_folders.extend(result.locked_folders)
            combined_result.accessible_files.extend(result.accessible_files)
            combined_result.accessible_folders.extend(result.accessible_folders)
            combined_result.total_checked += result.total_checked
        
        # Log summary
        if combined_result.has_locks:
            log_line(self.log_path, combined_result.format_detailed_report())
        else:
            log_line(self.log_path, f"  All {combined_result.total_checked} items accessible")
        
        log_line(self.log_path, "===== LOCK CHECK END =====")
        
        return combined_result
    
    def check_import_source(self, source_root, sessions_to_import):
        """
        Check source sessions before import operation.
        
        Args:
            source_root: Source subject directory
            sessions_to_import: List of session names to import
        
        Returns:
            LockCheckResult object
        """
        log_line(self.log_path, f"===== IMPORT SOURCE LOCK CHECK =====")
        return self.check_sessions_for_operation(source_root, sessions_to_import)
    
    def check_destination_conflicts(self, dest_root, new_session_names):
        """
        Check if destination paths would conflict with existing folders.
        
        Args:
            dest_root: Destination directory
            new_session_names: List of new session names that will be created
        
        Returns:
            List of (session_name, conflict_path) tuples for conflicts found
        """
        conflicts = []
        
        for session in new_session_names:
            dest_path = os.path.join(dest_root, session)
            if os.path.exists(dest_path):
                conflicts.append((session, dest_path))
        
        if conflicts:
            log_line(self.log_path, f"Found {len(conflicts)} destination conflicts")
            for session, path in conflicts:
                log_line(self.log_path, f"  Conflict: {session} already exists at {path}")
        
        return conflicts


def check_before_operation(root_dir, sessions, log_path=None):
    """
    Convenience function to check sessions before an operation.
    
    Args:
        root_dir: Root directory containing sessions
        sessions: List of session names or dict with session mappings
        log_path: Optional log file path
    
    Returns:
        Tuple of (can_proceed: bool, result: LockCheckResult)
    """
    checker = FileLockChecker(log_path)
    
    # Handle both list and dict inputs
    if isinstance(sessions, dict):
        session_list = list(sessions.keys())
    else:
        session_list = list(sessions)
    
    result = checker.check_sessions_for_operation(root_dir, session_list)
    
    return result.all_accessible, result
