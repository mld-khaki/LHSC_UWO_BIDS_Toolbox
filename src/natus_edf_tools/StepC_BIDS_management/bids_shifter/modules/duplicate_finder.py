# -*- coding: utf-8 -*-
"""
Enhanced duplicate detection for BIDS Shifter GUI.
Finds duplicate recordings based on (date, duration) combinations.

ENHANCEMENT: Now checks all associated files in a session (not just EDF).
Each EDF file may have associated .json, .tsv, .vhdr, .vmrk, .eeg files with
the same subject, session, and task identifiers. The duplicate finder now:
1. Groups EDF duplicates as before (by date + duration)
2. For each duplicate group, finds all associated files
3. Compares CONTENT of files (first 100KB hash) to verify true duplicates
4. Reports whether it's a "full match" (all files identical) or "partial"
"""

import os
import re
import hashlib
from collections import defaultdict
from .config import SESSION_PATTERN, BIDS_FILE_EXTENSIONS
from .utils import (
    extract_session_from_filename, 
    extract_session_from_basename,
    normalize_date, 
    format_duration_key,
    log_line
)


# Size limit for content comparison (100KB)
CONTENT_COMPARE_SIZE = 100 * 1024  # 100KB

# Pattern to extract BIDS components from filename
# e.g., sub-167_ses-001_task-yoy_run-01_ieeg.edf
BIDS_COMPONENTS_PATTERN = re.compile(
    r'^(?P<subject>sub-[^_]+)_'
    r'(?P<session>ses-[^_]+)_'
    r'(?P<task>task-[^_]+)?'
    r'(?:_(?P<run>run-[^_]+))?'
    r'(?:_(?P<acquisition>acq-[^_]+))?'
)


def compute_file_hash(filepath, max_bytes=CONTENT_COMPARE_SIZE):
    """
    Compute MD5 hash of the first max_bytes of a file.
    
    Args:
        filepath: Path to the file
        max_bytes: Maximum bytes to read (default 100KB)
    
    Returns:
        Hex digest string, or None if file cannot be read
    """
    try:
        hasher = hashlib.md5()
        with open(filepath, 'rb') as f:
            data = f.read(max_bytes)
            hasher.update(data)
        return hasher.hexdigest()
    except Exception:
        return None


def get_file_size(filepath):
    """Get file size in bytes, or -1 if cannot be determined."""
    try:
        return os.path.getsize(filepath)
    except Exception:
        return -1


class FileInfo:
    """Information about a single file including content hash."""
    
    def __init__(self, filepath, relative_path=None):
        self.filepath = filepath
        self.relative_path = relative_path or filepath
        self.basename = os.path.basename(filepath)
        self.extension = os.path.splitext(self.basename.lower())[1]
        self.size = get_file_size(filepath)
        self._hash = None
        self._hash_computed = False
    
    @property
    def content_hash(self):
        """Lazy-compute content hash on first access."""
        if not self._hash_computed:
            self._hash = compute_file_hash(self.filepath)
            self._hash_computed = True
        return self._hash
    
    def matches_content(self, other):
        """
        Check if this file has the same content as another file.
        
        Uses size check first (fast), then hash comparison.
        
        Args:
            other: Another FileInfo object
        
        Returns:
            True if content matches, False otherwise
        """
        # Quick size check first
        if self.size != other.size:
            return False
        
        # If both sizes are 0 or negative, consider no match determinable
        if self.size <= 0:
            return False
        
        # Compare hashes
        return self.content_hash == other.content_hash and self.content_hash is not None
    
    def __repr__(self):
        return f"FileInfo({self.basename}, size={self.size}, hash={self._hash[:8] if self._hash else 'N/A'})"


class FileGroup:
    """Represents a group of associated files (EDF + sidecars) with content info."""
    
    def __init__(self, edf_filename, session_folder, root_dir=None):
        self.edf_filename = edf_filename
        self.session_folder = session_folder
        self.root_dir = root_dir
        
        # FileInfo objects for EDF and sidecars
        self.edf_info = None
        self.sidecar_infos = {}  # extension -> FileInfo
        
        # Extract BIDS components
        self.subject = None
        self.session = None
        self.task = None
        self.run = None
        self._extract_components()
    
    def _extract_components(self):
        """Extract BIDS components from EDF filename."""
        basename = os.path.basename(self.edf_filename)
        match = BIDS_COMPONENTS_PATTERN.match(basename)
        if match:
            self.subject = match.group('subject')
            self.session = match.group('session')
            self.task = match.group('task')
            self.run = match.group('run')
    
    @property
    def base_pattern(self):
        """Get the base pattern for finding associated files."""
        # Build pattern from components
        parts = []
        if self.subject:
            parts.append(self.subject)
        if self.session:
            parts.append(self.session)
        if self.task:
            parts.append(self.task)
        if self.run:
            parts.append(self.run)
        
        return "_".join(parts) if parts else None
    
    def find_and_analyze_files(self, root_dir=None):
        """
        Find all files associated with this EDF and compute their hashes.
        
        Args:
            root_dir: Root directory to search in
        
        Returns:
            Dict mapping extension -> FileInfo
        """
        root_dir = root_dir or self.root_dir
        if not root_dir:
            return {}
        
        session_path = os.path.join(root_dir, self.session_folder)
        
        if not os.path.isdir(session_path):
            return {}
        
        # Find the EDF file first
        for dirpath, dirs, files in os.walk(session_path):
            for fn in files:
                full_path = os.path.join(dirpath, fn)
                rel_path = os.path.relpath(full_path, root_dir).replace("\\", "/")
                
                # Check if this is our EDF
                if fn.lower().endswith('.edf') and self.base_pattern and self.base_pattern in fn:
                    self.edf_info = FileInfo(full_path, rel_path)
                
                # Check for sidecars
                elif self.base_pattern and self.base_pattern in fn:
                    ext = os.path.splitext(fn.lower())[1]
                    if ext in ['.json', '.tsv', '.vhdr', '.vmrk', '.eeg', '.set', '.fdt']:
                        self.sidecar_infos[ext] = FileInfo(full_path, rel_path)
        
        return self.sidecar_infos
    
    def get_all_files(self):
        """Get all FileInfo objects (EDF + sidecars)."""
        files = {}
        if self.edf_info:
            files['.edf'] = self.edf_info
        files.update(self.sidecar_infos)
        return files
    
    def get_extensions(self):
        """Get set of extensions for all files."""
        extensions = set()
        if self.edf_info:
            extensions.add('.edf')
        extensions.update(self.sidecar_infos.keys())
        return extensions
    
    def __repr__(self):
        return f"FileGroup({self.edf_filename}, {len(self.sidecar_infos)} sidecars)"


class ContentMatchResult:
    """Result of content comparison between duplicate file groups."""
    
    def __init__(self):
        self.matching_files = []      # List of (extension, is_match, details)
        self.mismatched_files = []    # List of (extension, reason)
        self.missing_files = []       # List of (extension, which_session_missing)
        self.total_compared = 0
    
    @property
    def is_full_match(self):
        """True if all files match in content."""
        return (len(self.mismatched_files) == 0 and 
                len(self.missing_files) == 0 and 
                self.total_compared > 0)
    
    @property
    def is_partial_match(self):
        """True if some but not all files match."""
        return (len(self.matching_files) > 0 and 
                (len(self.mismatched_files) > 0 or len(self.missing_files) > 0))
    
    @property
    def is_no_match(self):
        """True if no files match or all are different."""
        return len(self.matching_files) == 0 or all(
            not m[1] for m in self.matching_files
        )
    
    def format_status(self):
        """Get human-readable match status."""
        if self.total_compared == 0:
            return "⚠️ NO FILES COMPARED"
        
        matching_count = sum(1 for m in self.matching_files if m[1])
        total_extensions = len(self.matching_files) + len(self.missing_files)
        
        if self.is_full_match:
            return f"✓ FULL CONTENT MATCH ({matching_count}/{total_extensions} files identical)"
        elif self.is_partial_match:
            mismatch_count = len(self.mismatched_files)
            missing_count = len(self.missing_files)
            issues = []
            if mismatch_count > 0:
                issues.append(f"{mismatch_count} content differs")
            if missing_count > 0:
                issues.append(f"{missing_count} missing in one")
            return f"⚠️ PARTIAL MATCH ({matching_count} identical, {', '.join(issues)})"
        else:
            return f"❌ CONTENT DIFFERS ({len(self.mismatched_files)} files different)"
    
    def format_details(self):
        """Get detailed breakdown of match results."""
        lines = []
        
        if self.matching_files:
            lines.append("  Identical files:")
            for ext, is_match, details in self.matching_files:
                status = "✓" if is_match else "✗"
                lines.append(f"    {status} {ext}: {details}")
        
        if self.mismatched_files:
            lines.append("  Different content:")
            for ext, reason in self.mismatched_files:
                lines.append(f"    ✗ {ext}: {reason}")
        
        if self.missing_files:
            lines.append("  Missing in one session:")
            for ext, which in self.missing_files:
                lines.append(f"    ? {ext}: missing in {which}")
        
        return "\n".join(lines)


class DuplicateInfo:
    """Information about a duplicate entry."""
    
    def __init__(self, filename, session, date, duration, acq_time):
        self.filename = filename
        self.session = session
        self.date = date
        self.duration = duration
        self.acq_time = acq_time
        self.file_group = None  # FileGroup object once populated
    
    def __repr__(self):
        return f"DuplicateInfo(session={self.session}, date={self.date}, duration={self.duration})"


class DuplicateGroup:
    """A group of duplicate recordings with content comparison."""
    
    def __init__(self, date, duration):
        self.date = date
        self.duration = duration
        self.infos = []  # List of DuplicateInfo
        self.content_match_result = None  # ContentMatchResult
    
    @property
    def sessions(self):
        """Get unique sessions in this group."""
        return sorted(set(info.session for info in self.infos if info.session))
    
    @property
    def is_full_match(self):
        """True if all files have identical content."""
        if self.content_match_result:
            return self.content_match_result.is_full_match
        return None
    
    def compare_content(self):
        """
        Compare content of all files across duplicate sessions.
        
        This compares each file type (EDF, JSON, TSV, etc.) across all
        sessions in this duplicate group.
        
        Returns:
            ContentMatchResult object
        """
        result = ContentMatchResult()
        
        if len(self.infos) < 2:
            self.content_match_result = result
            return result
        
        # Collect all file groups
        file_groups = [info.file_group for info in self.infos if info.file_group]
        
        if len(file_groups) < 2:
            self.content_match_result = result
            return result
        
        # Get all extensions across all groups
        all_extensions = set()
        for fg in file_groups:
            all_extensions.update(fg.get_extensions())
        
        # Compare each extension across groups
        for ext in sorted(all_extensions):
            # Collect FileInfo for this extension from each group
            file_infos = []
            missing_in = []
            
            for i, fg in enumerate(file_groups):
                all_files = fg.get_all_files()
                if ext in all_files:
                    file_infos.append((self.infos[i].session, all_files[ext]))
                else:
                    missing_in.append(self.infos[i].session)
            
            # If missing in some sessions
            if missing_in:
                result.missing_files.append((ext, ", ".join(missing_in)))
                continue
            
            # Compare content across all sessions
            if len(file_infos) >= 2:
                result.total_compared += 1
                
                # Use first file as reference
                ref_session, ref_info = file_infos[0]
                all_match = True
                mismatch_sessions = []
                
                for other_session, other_info in file_infos[1:]:
                    if not ref_info.matches_content(other_info):
                        all_match = False
                        mismatch_sessions.append(other_session)
                
                if all_match:
                    size_kb = ref_info.size / 1024
                    details = f"identical ({size_kb:.1f}KB, hash={ref_info.content_hash[:8]})"
                    result.matching_files.append((ext, True, details))
                else:
                    reason = f"differs in {', '.join(mismatch_sessions)}"
                    result.mismatched_files.append((ext, reason))
                    result.matching_files.append((ext, False, reason))
        
        self.content_match_result = result
        return result
    
    def format_match_status(self):
        """Get a human-readable match status."""
        if self.content_match_result:
            return self.content_match_result.format_status()
        return "⚠️ Not analyzed"


class DuplicateFinder:
    """Finds duplicate recordings in BIDS TSV data with content comparison."""
    
    def __init__(self, log_path=None):
        self.log_path = log_path
        self.root_dir = None
    
    def find_duplicates(self, rows, root_dir=None):
        """
        Find duplicate rows based on (date, duration) combination.
        
        A duplicate occurs when two or more recordings have:
        - Same date (extracted from acq_time)
        - Same duration (compared at 3 decimal places)
        
        Args:
            rows: List of TSV row dicts with keys: filename, acq_time, duration
            root_dir: Optional root directory for scanning and comparing files
        
        Returns:
            Dict mapping (date, duration_key) -> DuplicateGroup object
            Only includes groups with 2+ items (actual duplicates)
        """
        self.root_dir = root_dir
        groups = defaultdict(lambda: DuplicateGroup(None, None))
        
        for row in rows:
            acq_time = row.get("acq_time", "")
            duration_str = row.get("duration", "")
            filename = row.get("filename", "")
            
            # Extract components
            date_part = normalize_date(acq_time)
            duration_key = format_duration_key(duration_str)
            session = extract_session_from_filename(filename)
            
            # Create info object
            info = DuplicateInfo(
                filename=filename,
                session=session,
                date=date_part,
                duration=duration_key,
                acq_time=acq_time
            )
            
            key = (date_part, duration_key)
            
            # Initialize group if new
            if groups[key].date is None:
                groups[key].date = date_part
                groups[key].duration = duration_key
            
            groups[key].infos.append(info)
        
        # Filter to only duplicates (2+ items)
        duplicates = {k: v for k, v in groups.items() if len(v.infos) > 1}
        
        # If root_dir provided, scan files and compare content
        if root_dir and duplicates:
            self._analyze_duplicate_content(duplicates, root_dir)
        
        if duplicates:
            log_line(self.log_path, f"Found {len(duplicates)} duplicate groups")
        
        return duplicates
    
    def _analyze_duplicate_content(self, duplicates, root_dir):
        """
        Analyze file content for each duplicate group.
        
        Args:
            duplicates: Dict of duplicate groups
            root_dir: Root directory for file scanning
        """
        log_line(self.log_path, "Analyzing duplicate content (comparing first 100KB)...")
        
        for group in duplicates.values():
            # Create file groups and scan for files
            for info in group.infos:
                session = extract_session_from_filename(info.filename)
                file_group = FileGroup(info.filename, session, root_dir)
                file_group.find_and_analyze_files(root_dir)
                info.file_group = file_group
            
            # Compare content across the group
            group.compare_content()
            
            if group.content_match_result:
                status = "FULL MATCH" if group.is_full_match else "DIFFERS"
                log_line(self.log_path, 
                    f"  {group.date} {group.duration}h: {status}")
    
    def format_duplicate_summary(self, duplicates):
        """
        Format duplicate findings into a human-readable summary.
        
        ENHANCED: Now shows content comparison results.
        
        Args:
            duplicates: Dict from find_duplicates()
        
        Returns:
            Formatted string for display
        """
        if not duplicates:
            return "No duplicates found."
        
        total_dup_rows = sum(len(g.infos) for g in duplicates.values())
        full_matches = sum(1 for g in duplicates.values() if g.is_full_match is True)
        partial_or_diff = len(duplicates) - full_matches
        
        lines = [
            f"Found {len(duplicates)} duplicate (date, duration) groups",
            f"Total duplicate rows: {total_dup_rows}",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"CONTENT COMPARISON (first 100KB of each file):",
            f"  ✓ Full content matches: {full_matches}",
            f"  ⚠️ Partial/different: {partial_or_diff}",
            ""
        ]
        
        # Sort by date for cleaner output
        for (date, duration), group in sorted(duplicates.items()):
            sessions = group.sessions
            session_str = ", ".join(sessions) if sessions else "unknown"
            
            lines.append(f"═══ Date: {date} | Duration: {duration}h ═══")
            lines.append(f"    Sessions: {session_str}")
            lines.append(f"    {group.format_match_status()}")
            
            # Show content comparison details if available
            if group.content_match_result:
                result = group.content_match_result
                
                # Show matching files
                if result.matching_files:
                    matching = [f"{ext}" for ext, is_match, _ in result.matching_files if is_match]
                    if matching:
                        lines.append(f"    Identical: {', '.join(matching)}")
                
                # Show different files
                if result.mismatched_files:
                    different = [f"{ext}" for ext, _ in result.mismatched_files]
                    lines.append(f"    DIFFERENT: {', '.join(different)}")
                
                # Show missing files
                if result.missing_files:
                    missing = [f"{ext}" for ext, _ in result.missing_files]
                    lines.append(f"    Missing in one: {', '.join(missing)}")
            
            lines.append(f"    Files ({len(group.infos)}):")
            
            for info in group.infos:
                ses_display = f"[{info.session}]" if info.session else "[no session]"
                
                # Show file info
                if info.file_group:
                    all_files = info.file_group.get_all_files()
                    sidecar_count = len(all_files) - 1  # Exclude EDF
                
                    # Get EDF hash for display
                    edf_hash = ""
                    if '.edf' in all_files:
                        h = all_files['.edf'].content_hash
                        if h:
                            edf_hash = f" [hash:{h[:8]}]"
                    
                    assoc_str = f" (+{sidecar_count} sidecars)" if sidecar_count > 0 else ""
                    lines.append(f"      {ses_display} {info.filename}{assoc_str}{edf_hash}")
                else:
                    lines.append(f"      {ses_display} {info.filename}")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def get_duplicate_filenames(self, duplicates):
        """
        Get set of all filenames that are duplicates.
        
        Args:
            duplicates: Dict from find_duplicates()
        
        Returns:
            Set of filename strings
        """
        filenames = set()
        for group in duplicates.values():
            for info in group.infos:
                filenames.add(info.filename)
        return filenames
    
    def get_duplicate_keys_for_row(self, row, duplicates):
        """
        Check if a row is part of a duplicate group.
        
        Args:
            row: TSV row dict
            duplicates: Dict from find_duplicates()
        
        Returns:
            The (date, duration) key if row is duplicate, None otherwise
        """
        acq_time = row.get("acq_time", "")
        duration_str = row.get("duration", "")
        
        date_part = normalize_date(acq_time)
        duration_key = format_duration_key(duration_str)
        
        key = (date_part, duration_key)
        return key if key in duplicates else None
    
    def is_duplicate_display_values(self, acq_display, dur_display, duplicates):
        """
        Check if display values match a duplicate key.
        Used for tagging tree view items.
        
        Args:
            acq_display: Acquisition time as displayed (e.g., "2025-03-11T07:58:18")
            dur_display: Duration as displayed (e.g., "22.727")
            duplicates: Dict from find_duplicates()
        
        Returns:
            True if this matches a duplicate group
        """
        date_part = normalize_date(acq_display)
        duration_key = format_duration_key(dur_display)
        return (date_part, duration_key) in duplicates
    
    def get_all_duplicate_files(self, duplicates):
        """
        Get all files (EDF + associated) involved in duplicates.
        
        Args:
            duplicates: Dict from find_duplicates()
        
        Returns:
            Set of all file paths involved
        """
        all_files = set()
        for group in duplicates.values():
            for info in group.infos:
                all_files.add(info.filename)
                if info.file_group:
                    for fi in info.file_group.get_all_files().values():
                        all_files.add(fi.relative_path)
        return all_files
    
    def get_identical_duplicates(self, duplicates):
        """
        Get only the duplicate groups where all content matches.
        
        Args:
            duplicates: Dict from find_duplicates()
        
        Returns:
            Dict of duplicate groups with full content match
        """
        return {k: v for k, v in duplicates.items() if v.is_full_match is True}
    
    def get_different_duplicates(self, duplicates):
        """
        Get only the duplicate groups where content differs.
        
        Args:
            duplicates: Dict from find_duplicates()
        
        Returns:
            Dict of duplicate groups with content differences
        """
        return {k: v for k, v in duplicates.items() if v.is_full_match is False}
    
    def log_duplicate_details(self, duplicates):
        """
        Log detailed duplicate information including content comparison.
        
        Args:
            duplicates: Dict from find_duplicates()
        """
        if not duplicates:
            log_line(self.log_path, "Duplicate check: none found.")
            return
        
        log_line(self.log_path, "===== DUPLICATE CHECK (WITH CONTENT COMPARISON) =====")
        
        for (date, duration), group in sorted(duplicates.items()):
            sessions = group.sessions
            log_line(self.log_path, f"Duplicate group: {date} | {duration}h")
            log_line(self.log_path, f"  Sessions: {sessions}")
            log_line(self.log_path, f"  {group.format_match_status()}")
            
            # Log content comparison details
            if group.content_match_result:
                result = group.content_match_result
                if result.matching_files:
                    for ext, is_match, details in result.matching_files:
                        status = "MATCH" if is_match else "DIFFER"
                        log_line(self.log_path, f"    {ext}: {status} - {details}")
                if result.missing_files:
                    for ext, which in result.missing_files:
                        log_line(self.log_path, f"    {ext}: MISSING in {which}")
            
            for info in group.infos:
                log_line(self.log_path, f"    [{info.session}] {info.filename}")
                if info.file_group:
                    for ext, fi in info.file_group.get_all_files().items():
                        hash_str = fi.content_hash[:8] if fi.content_hash else "N/A"
                        log_line(self.log_path, 
                            f"        {ext}: {fi.size}B, hash={hash_str}")
        
        log_line(self.log_path, "===== END DUPLICATE CHECK =====")

    def find_orphaned_sidecars(self, root_dir, rows):
        """
        Find sidecar files that don't have a corresponding EDF.
        
        Args:
            root_dir: Root directory to scan
            rows: TSV rows
        
        Returns:
            List of orphaned sidecar file paths
        """
        # Get all EDF base patterns
        edf_patterns = set()
        for row in rows:
            filename = row.get("filename", "")
            session = extract_session_from_filename(filename)
            if session:
                fg = FileGroup(filename, session)
                if fg.base_pattern:
                    edf_patterns.add(fg.base_pattern)
        
        orphans = []
        
        # Scan for files without matching EDF
        for session_folder in os.listdir(root_dir):
            session_path = os.path.join(root_dir, session_folder)
            if not os.path.isdir(session_path):
                continue
            
            for dirpath, dirs, files in os.walk(session_path):
                for fn in files:
                    if fn.lower().endswith('.edf'):
                        continue
                    
                    # Check if any EDF pattern matches this file
                    has_match = any(pattern in fn for pattern in edf_patterns)
                    
                    if not has_match:
                        # This might be an orphan
                        # But only flag it if it looks like a BIDS sidecar
                        if any(fn.lower().endswith(ext) for ext in ['.json', '.tsv', '.vhdr', '.vmrk', '.eeg']):
                            rel_path = os.path.relpath(
                                os.path.join(dirpath, fn), root_dir
                            ).replace("\\", "/")
                            orphans.append(rel_path)
        
        return orphans
