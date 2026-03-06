from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Callable, Iterable, Optional


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def safe_copy_file(src: str, dst: str, overwrite: bool = False) -> None:
    """Copy a single file with optional overwrite. Creates destination directories."""
    if not os.path.isfile(src):
        raise FileNotFoundError(f"Source file not found: {src}")
    dst_dir = os.path.dirname(dst)
    if dst_dir:
        ensure_dir(dst_dir)
    if os.path.exists(dst) and not overwrite:
        return
    shutil.copy2(src, dst)


@dataclass
class CopyStats:
    dirs_created: int = 0
    files_copied: int = 0
    files_overwritten: int = 0
    files_skipped_existing: int = 0


def _default_ignore(_src_root: str, _name: str) -> bool:
    return False


def safe_copy_tree(
    src_dir: str,
    dst_dir: str,
    *,
    overwrite: bool = False,
    ignore: Optional[Callable[[str, str], bool]] = None,
) -> CopyStats:
    """Copy a directory tree from src_dir into dst_dir.

    - If overwrite=False, existing files in dst are kept (skipped).
    - If overwrite=True, existing files in dst are overwritten.
    - ignore(src_root, name) -> True skips the entry 'name' under 'src_root'.

    Returns simple copy statistics.
    """
    if not os.path.isdir(src_dir):
        raise NotADirectoryError(f"Source directory not found: {src_dir}")

    ignore = ignore or _default_ignore
    stats = CopyStats()

    ensure_dir(dst_dir)

    for root, dirs, files in os.walk(src_dir):
        # Filter dirs in-place so os.walk doesn't descend into ignored paths
        dirs[:] = [d for d in dirs if not ignore(root, d)]

        rel_root = os.path.relpath(root, src_dir)
        dst_root = dst_dir if rel_root == os.curdir else os.path.join(dst_dir, rel_root)

        if not os.path.isdir(dst_root):
            os.makedirs(dst_root, exist_ok=True)
            stats.dirs_created += 1

        for fn in files:
            if ignore(root, fn):
                continue
            src_path = os.path.join(root, fn)
            rel_path = os.path.relpath(src_path, src_dir)
            dst_path = os.path.join(dst_dir, rel_path)

            dst_parent = os.path.dirname(dst_path)
            if dst_parent and not os.path.isdir(dst_parent):
                os.makedirs(dst_parent, exist_ok=True)
                stats.dirs_created += 1

            if os.path.exists(dst_path):
                if not overwrite:
                    stats.files_skipped_existing += 1
                    continue
                stats.files_overwritten += 1

            shutil.copy2(src_path, dst_path)
            stats.files_copied += 1

    return stats


def has_any_files(path: str) -> bool:
    """Return True if path contains at least one file anywhere under it."""
    if os.path.isfile(path):
        return True
    if not os.path.isdir(path):
        return False
    for _root, _dirs, files in os.walk(path):
        if files:
            return True
    return False
