from __future__ import annotations

import os
import re


_SUBJECT_RE = re.compile(r"^sub-[A-Za-z0-9]+$")


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
