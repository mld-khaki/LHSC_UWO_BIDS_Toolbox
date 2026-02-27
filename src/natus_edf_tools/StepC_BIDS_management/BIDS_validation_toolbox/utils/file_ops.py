from __future__ import annotations

import os
import shutil


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def safe_copy_file(src: str, dst: str, overwrite: bool = False) -> None:
    if not os.path.isfile(src):
        raise FileNotFoundError(f"Source file not found: {src}")
    dst_dir = os.path.dirname(dst)
    if dst_dir:
        ensure_dir(dst_dir)
    if os.path.exists(dst) and not overwrite:
        return
    shutil.copy2(src, dst)
