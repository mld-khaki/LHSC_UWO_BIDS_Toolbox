# -*- coding: utf-8 -*-
"""
Duplicate detection for BIDS Shifter GUI.
Finds duplicate recordings based on (date, duration) combinations.

BUG FIX: Now correctly extracts and displays session numbers for each duplicate,
showing them prominently in the summary rather than just showing full filenames.
"""

from collections import defaultdict
from .utils import (
    extract_session_from_filename, 
    normalize_date, 
    format_duration_key,
    log_line
)


class DuplicateInfo:
    """Information about a duplicate entry."""
    
    def __init__(self, filename, session, date, duration, acq_time):
        self.filename = filename
        self.session = session
        self.date = date
        self.duration = duration
        self.acq_time = acq_time
    
    def __repr__(self):
        return f"DuplicateInfo(session={self.session}, date={self.date}, duration={self.duration})"


class DuplicateFinder:
    """Finds duplicate recordings in BIDS TSV data."""
    
    def __init__(self, log_path=None):
        self.log_path = log_path
    
    def find_duplicates(self, rows):
        """
        Find duplicate rows based on (date, duration) combination.
        
        A duplicate occurs when two or more recordings have:
        - Same date (extracted from acq_time)
        - Same duration (compared at 3 decimal places)
        
        Args:
            rows: List of TSV row dicts with keys: filename, acq_time, duration
        
        Returns:
            Dict mapping (date, duration_key) -> list of DuplicateInfo objects
            Only includes groups with 2+ items (actual duplicates)
        """
        groups = defaultdict(list)
        
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
            groups[key].append(info)
        
        # Filter to only duplicates (2+ items)
        duplicates = {k: v for k, v in groups.items() if len(v) > 1}
        
        if duplicates:
            log_line(self.log_path, f"Found {len(duplicates)} duplicate groups")
        
        return duplicates
    
    def format_duplicate_summary(self, duplicates):
        """
        Format duplicate findings into a human-readable summary.
        
        BUG FIX: Now prominently shows session numbers, not just full filenames.
        
        Args:
            duplicates: Dict from find_duplicates()
        
        Returns:
            Formatted string for display
        """
        if not duplicates:
            return "No duplicates found."
        
        total_dup_rows = sum(len(v) for v in duplicates.values())
        lines = [
            f"Found {len(duplicates)} duplicate (date, duration) groups",
            f"Total duplicate rows: {total_dup_rows}",
            ""
        ]
        
        # Sort by date for cleaner output
        for (date, duration), infos in sorted(duplicates.items()):
            # Extract unique sessions in this duplicate group
            sessions = sorted(set(info.session for info in infos if info.session))
            session_str = ", ".join(sessions) if sessions else "unknown"
            
            lines.append(f"═══ Date: {date} | Duration: {duration}h ═══")
            lines.append(f"    Sessions involved: {session_str}")
            lines.append(f"    Files ({len(infos)}):")
            
            for info in infos:
                # Show session prominently, then filename
                ses_display = f"[{info.session}]" if info.session else "[no session]"
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
        for infos in duplicates.values():
            for info in infos:
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
    
    def log_duplicate_details(self, duplicates):
        """
        Log detailed duplicate information.
        
        Args:
            duplicates: Dict from find_duplicates()
        """
        if not duplicates:
            log_line(self.log_path, "Duplicate check: none found.")
            return
        
        log_line(self.log_path, "===== DUPLICATE CHECK =====")
        
        for (date, duration), infos in sorted(duplicates.items()):
            sessions = [info.session for info in infos]
            log_line(self.log_path, f"Duplicate group: {date} | {duration}h")
            log_line(self.log_path, f"  Sessions: {sessions}")
            for info in infos:
                log_line(self.log_path, f"    [{info.session}] {info.filename}")
        
        log_line(self.log_path, "===== END DUPLICATE CHECK =====")
