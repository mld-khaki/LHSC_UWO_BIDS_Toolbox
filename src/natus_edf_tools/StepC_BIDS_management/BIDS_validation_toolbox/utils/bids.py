from __future__ import annotations

import os
import re
from typing import Optional


_SUBJECT_RE = re.compile(r"^sub-[A-Za-z0-9]+$")
_SESSION_RE = re.compile(r"^ses-[A-Za-z0-9]+$")

# Internal marker used when a subject folder has no ses-* subfolders.
NO_SESSION = "__NO_SESSION__"


def list_bids_subjects(source_bids_dir: str) -> list[str]:
    """
    Returns subject directory names like: ['sub-001', 'sub-002', ...]
    """
    if not os.path.isdir(source_bids_dir):
        raise NotADirectoryError(f"Not a directory: {source_bids_dir}")

    subs: list[str] = []
    for name in os.listdir(source_bids_dir):
        p = os.path.join(source_bids_dir, name)
        if os.path.isdir(p) and _SUBJECT_RE.match(name):
            subs.append(name)

    subs.sort()
    return subs


def is_bids_subject_dir(path: str) -> bool:
    if not path:
        return False
    if not os.path.isdir(path):
        return False
    return _SUBJECT_RE.match(os.path.basename(os.path.abspath(path))) is not None


def is_bids_root_dir(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    try:
        return len(list_bids_subjects(path)) > 0
    except Exception:
        return False


def resolve_subject_dir(bids_path: str, subject: Optional[str] = None) -> tuple[str, str]:
    """Resolve a subject directory path.

    bids_path may be:
      - a BIDS subject folder (ends with sub-XXX) -> returns (bids_path, 'sub-XXX')
      - a BIDS root folder containing sub-* -> requires subject, returns (root/sub-XXX, 'sub-XXX')
    """
    if not bids_path:
        raise ValueError("BIDS path is blank.")

    bids_path = os.path.abspath(bids_path)

    if is_bids_subject_dir(bids_path):
        return bids_path, os.path.basename(bids_path)

    if is_bids_root_dir(bids_path):
        subject = (subject or "").strip()
        if not subject:
            raise ValueError("BIDS root provided but subject is not specified.")
        if not _SUBJECT_RE.match(subject):
            raise ValueError(f"Invalid subject id: {subject} (expected like 'sub-001')")
        subj_dir = os.path.join(bids_path, subject)
        if not os.path.isdir(subj_dir):
            raise NotADirectoryError(f"Subject folder not found: {subj_dir}")
        return subj_dir, subject

    raise NotADirectoryError(f"Not a BIDS root or subject directory: {bids_path}")


def list_subject_sessions(subject_dir: str) -> list[str]:
    """List ses-* folders under a subject directory. If none exist, returns [NO_SESSION]."""
    if not is_bids_subject_dir(subject_dir):
        raise NotADirectoryError(f"Not a BIDS subject directory: {subject_dir}")

    sessions: list[str] = []
    for name in os.listdir(subject_dir):
        p = os.path.join(subject_dir, name)
        if os.path.isdir(p) and _SESSION_RE.match(name):
            sessions.append(name)

    sessions.sort()
    return sessions if sessions else [NO_SESSION]


def _has_any_files_recursive(path: str, *, ignore_dir_pred=None) -> bool:
    if os.path.isfile(path):
        return True
    if not os.path.isdir(path):
        return False

    for root, dirs, files in os.walk(path):
        if ignore_dir_pred is not None:
            dirs[:] = [d for d in dirs if not ignore_dir_pred(os.path.join(root, d))]

        if files:
            return True
    return False


def session_has_any_files(subject_dir: str, session: str) -> bool:
    """Return True if the given session contains at least one file.

    For NO_SESSION, checks for any files directly under the subject directory,
    ignoring ses-* folders.
    """
    if session == NO_SESSION:
        def _ignore(p: str) -> bool:
            return _SESSION_RE.match(os.path.basename(p) or "") is not None
        return _has_any_files_recursive(subject_dir, ignore_dir_pred=_ignore)

    if not _SESSION_RE.match(session or ""):
        raise ValueError(f"Invalid session name: {session}")

    sess_dir = os.path.join(subject_dir, session)
    return _has_any_files_recursive(sess_dir)
