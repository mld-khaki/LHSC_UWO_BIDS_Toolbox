# -*- coding: utf-8 -*-
"""
Import manager for BIDS Shifter GUI.
Handles importing sessions from another subject folder into the current one.
"""

import os
import re
import shutil
from .config import SESSION_PATTERN, SESSION_FOLDER_PATTERN, EXCEPTION_DEBUG
from .utils import extract_session_from_filename, extract_session_number, log_line


class ImportManager:
    """Manages importing sessions from external folders."""
    
    def __init__(self, log_path=None):
        self.log_path = log_path
    
    def scan_source_folder(self, source_root):
        """
        Scan a source folder to find available sessions.
        
        Args:
            source_root: Path to source subject folder (e.g., sub-167_old)
        
        Returns:
            Dict with:
                - sessions: List of session folder names found
                - tsv_path: Path to scans.tsv if found, None otherwise
                - edf_count: Total number of EDF files found
        """
        if not source_root or not os.path.isdir(source_root):
            return {"sessions": [], "tsv_path": None, "edf_count": 0}
        
        sessions = []
        edf_count = 0
        tsv_path = None
        
        # Find sessions
        for item in os.listdir(source_root):
            item_path = os.path.join(source_root, item)
            if SESSION_FOLDER_PATTERN.match(item) and os.path.isdir(item_path):
                sessions.append(item)
                # Count EDFs in this session
                for root, dirs, files in os.walk(item_path):
                    edf_count += sum(1 for f in files if f.lower().endswith(".edf"))
        
        # Find TSV
        base = os.path.basename(os.path.normpath(source_root))
        possible_tsv = os.path.join(source_root, f"{base}_scans.tsv")
        if os.path.exists(possible_tsv):
            tsv_path = possible_tsv
        
        sessions.sort(key=extract_session_number)
        
        return {
            "sessions": sessions,
            "tsv_path": tsv_path,
            "edf_count": edf_count
        }
    
    def calculate_import_mapping(self, source_sessions, dest_sessions, start_number=None):
        """
        Calculate how source sessions should be renumbered for import.
        
        Args:
            source_sessions: List of session strings from source
            dest_sessions: Set of existing session strings in destination
            start_number: Optional starting session number; if None, uses next available
        
        Returns:
            Dict mapping source_session -> new_session
        """
        if not source_sessions:
            return {}
        
        # Find the highest existing session number in destination
        max_dest = 0
        for ses in dest_sessions:
            num = extract_session_number(ses)
            if num > max_dest:
                max_dest = num
        
        # Start numbering after existing sessions (or at specified start)
        if start_number is not None:
            next_num = start_number
        else:
            next_num = max_dest + 1
        
        mapping = {}
        for src_ses in sorted(source_sessions, key=extract_session_number):
            new_ses = f"ses-{next_num:03d}"
            
            # Avoid collisions
            while new_ses in dest_sessions or new_ses in mapping.values():
                next_num += 1
                new_ses = f"ses-{next_num:03d}"
            
            mapping[src_ses] = new_ses
            next_num += 1
        
        return mapping
    
    def import_sessions(self, source_root, dest_root, session_mapping, 
                        dest_subject_name, dry_run=False, use_copy=False):
        """
        Import sessions from source to destination with renumbering.
        
        Args:
            source_root: Path to source subject folder
            dest_root: Path to destination subject folder
            session_mapping: Dict mapping source_session -> new_session
            dest_subject_name: Subject name for destination (e.g., "sub-167")
            dry_run: If True, only log what would happen
            use_copy: If True, copy instead of move (default: False = move)
        
        Returns:
            List of imported TSV rows (for merging into dest TSV)
        """
        if not session_mapping:
            return []
        
        action = "COPY" if use_copy else "MOVE"
        log_line(self.log_path, f"===== IMPORT START ({action} mode) =====")
        imported_rows = []
        
        # Extract source subject name for replacement
        source_subject = os.path.basename(os.path.normpath(source_root))
        
        for src_ses, new_ses in session_mapping.items():
            src_path = os.path.join(source_root, src_ses)
            dest_path = os.path.join(dest_root, new_ses)
            
            if not os.path.isdir(src_path):
                log_line(self.log_path, f"WARNING: Source session not found: {src_path}")
                continue
            
            if dry_run:
                log_line(self.log_path, f"[DRY] Would {action.lower()} {src_ses} -> {new_ses}")
                # Still collect info for preview
                imported_rows.extend(
                    self._collect_session_info(src_path, src_ses, new_ses, 
                                               source_subject, dest_subject_name)
                )
                continue
            
            try:
                # Check destination doesn't exist
                if os.path.exists(dest_path):
                    log_line(self.log_path, f"WARNING: Destination exists, skipping: {dest_path}")
                    continue
                
                # Move or copy the session folder
                if use_copy:
                    shutil.copytree(src_path, dest_path)
                    log_line(self.log_path, f"COPIED: {src_ses} -> {new_ses}")
                else:
                    shutil.move(src_path, dest_path)
                    log_line(self.log_path, f"MOVED: {src_ses} -> {new_ses}")
                
                # Rename files to update session and subject references
                self._rename_files_in_session(dest_path, src_ses, new_ses,
                                              source_subject, dest_subject_name)
                
                # Collect TSV row info
                imported_rows.extend(
                    self._collect_session_info(dest_path, src_ses, new_ses,
                                               source_subject, dest_subject_name,
                                               is_imported=True)
                )
                
            except Exception as e:
                log_line(self.log_path, f"ERROR importing {src_ses}: {e}")
                if EXCEPTION_DEBUG:
                    raise e
        
        log_line(self.log_path, f"===== IMPORT END ({len(imported_rows)} files) =====")
        return imported_rows
    
    def _rename_files_in_session(self, session_path, old_ses, new_ses, 
                                  old_subject, new_subject):
        """
        Rename files within an imported session folder.
        Updates both session number and subject name in filenames.
        """
        for root, dirs, files in os.walk(session_path):
            for fn in files:
                new_fn = fn
                
                # Replace session number
                if SESSION_PATTERN.search(fn):
                    new_num = new_ses.split("-")[1]
                    new_fn = SESSION_PATTERN.sub(f"ses-{new_num}", new_fn)
                
                # Replace subject name if different
                if old_subject != new_subject and old_subject in new_fn:
                    new_fn = new_fn.replace(old_subject, new_subject)
                
                if new_fn != fn:
                    old_path = os.path.join(root, fn)
                    new_path = os.path.join(root, new_fn)
                    os.rename(old_path, new_path)
                    log_line(self.log_path, f"  RENAMED: {fn} -> {new_fn}")
    
    def _collect_session_info(self, session_path, old_ses, new_ses,
                               old_subject, new_subject, is_imported=False):
        """
        Collect file information for TSV rows.
        
        Returns:
            List of dict rows for TSV
        """
        rows = []
        
        # Try to read EDF metadata
        try:
            # Delayed import to handle optional dependency
            from edfreader_mld2 import EDFreader
            edf_available = True
        except ImportError:
            try:
                from common_libs.edflib_fork_mld.edfreader_mld2 import EDFreader
                edf_available = True
            except ImportError:
                edf_available = False
        
        session_root = os.path.dirname(session_path.rstrip("/\\"))
        
        for root, dirs, files in os.walk(session_path):
            for fn in files:
                if not fn.lower().endswith(".edf"):
                    continue
                
                full_path = os.path.join(root, fn)
                
                # Build the relative path as it will appear in destination
                rel_from_session = os.path.relpath(full_path, session_path)
                
                # Update filename with new session and subject
                new_fn = fn
                if SESSION_PATTERN.search(fn):
                    new_num = new_ses.split("-")[1]
                    new_fn = SESSION_PATTERN.sub(f"ses-{new_num}", new_fn)
                if old_subject != new_subject and old_subject in new_fn:
                    new_fn = new_fn.replace(old_subject, new_subject)
                
                # Build the path as it will appear in TSV
                rel_dir = os.path.dirname(rel_from_session)
                if rel_dir:
                    tsv_filename = f"{new_ses}/{rel_dir}/{new_fn}".replace("\\", "/")
                else:
                    tsv_filename = f"{new_ses}/{new_fn}".replace("\\", "/")
                
                # Try to get EDF metadata
                acq_time = ""
                duration = ""
                edf_type = "EDF+C"
                
                if edf_available:
                    try:
                        reader = EDFreader(full_path, read_annotations=False)
                        start_dt = reader.getStartDateTime()
                        dur_sec = reader.getFileDuration()
                        reader.close()
                        
                        acq_time = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
                        dur_hours = float(dur_sec) / (3600.0 * 1e7)
                        duration = f"{dur_hours:.3f}"
                    except Exception as e:
                        log_line(self.log_path, f"WARNING: Could not read EDF metadata: {fn}")
                
                rows.append({
                    "filename": tsv_filename,
                    "acq_time": acq_time,
                    "duration": duration,
                    "edf_type": edf_type,
                    "_imported": is_imported  # Internal flag for highlighting
                })
        
        return rows
    
    def import_tsv_rows(self, source_tsv_path, session_mapping, 
                        old_subject, new_subject):
        """
        Read source TSV and remap rows for import.
        
        Args:
            source_tsv_path: Path to source scans.tsv
            session_mapping: Dict mapping source_session -> new_session  
            old_subject: Source subject name
            new_subject: Destination subject name
        
        Returns:
            List of remapped TSV row dicts
        """
        import csv
        
        if not source_tsv_path or not os.path.exists(source_tsv_path):
            return []
        
        rows = []
        
        try:
            with open(source_tsv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    filename = row.get("filename", "")
                    src_ses = extract_session_from_filename(filename)
                    
                    if src_ses not in session_mapping:
                        continue
                    
                    new_ses = session_mapping[src_ses]
                    new_filename = filename.replace(src_ses, new_ses)
                    
                    # Update subject name if different
                    if old_subject != new_subject:
                        new_filename = new_filename.replace(old_subject, new_subject)
                    
                    new_row = dict(row)
                    new_row["filename"] = new_filename
                    new_row["_imported"] = True
                    rows.append(new_row)
            
            log_line(self.log_path, f"Read {len(rows)} rows from source TSV")
            
        except Exception as e:
            log_line(self.log_path, f"ERROR reading source TSV: {e}")
            if EXCEPTION_DEBUG:
                raise e
        
        return rows
