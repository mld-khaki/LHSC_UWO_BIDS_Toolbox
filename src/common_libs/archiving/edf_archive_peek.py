# -*- coding: utf-8 -*-
"""
edf_archive_peek.py  –  Archive streaming helpers for EDF/BDF files
────────────────────────────────────────────────────────────────────
Extracts the first N bytes from an EDF/BDF file stored inside a
compressed archive without decompressing the entire archive to disk.

Supported archive formats
  .zip      → stdlib zipfile              (true streaming ✓)
  .tar.gz / .tgz / .tar.bz2 / .tar.xz / .tar
            → stdlib tarfile              (true streaming ✓)
  .edf.gz / .bdf.gz (bare gzip)
            → stdlib gzip                 (true streaming ✓)
  .7z       → 7z CLI subprocess first     (true streaming ✓)
              then py7zr fallback          (full decompress — slow for large files)
  .rar      → unrar CLI, then WinRAR CLI, (true streaming ✓)
              then rarfile package fallback

Optional dependencies (install as needed):
  py7zr     – .7z fallback when 7z CLI is unavailable
  rarfile   – .rar package fallback

Public API
──────────
  ArchiveStreamError          – raised on any archive-related problem
  ARCHIVE_SUFFIXES            – frozenset of supported archive extensions
  EDF_SUFFIXES                – frozenset of EDF/BDF extensions
  stream_edf_bytes(path, n_bytes, progress_cb=None)
      → (BytesIO with first n_bytes, edf_filename_in_archive)

Internal helpers (used by stream_edf_bytes; not part of the public API):
  _is_edf_like(name)
  _chunked_read(fileobj, n_bytes, progress_cb)
  _assert_one_edf(names, archive_path)
  _subprocess_kwargs()
  _stream_7z(archive_path, n_bytes, progress_cb)
  _stream_rar(archive_path, n_bytes, progress_cb)

Canonical location: src/common_libs/archiving/edf_archive_peek.py

Author: Dr. Milad Khaki (LHSC / Western University)
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════════
#  Public constants
# ══════════════════════════════════════════════════════════════════════════════

EDF_SUFFIXES: frozenset[str] = frozenset({".edf", ".bdf"})

ARCHIVE_SUFFIXES: frozenset[str] = frozenset({
    ".zip",
    ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar",
    ".gz",   # bare gzip — expected to contain a single .edf/.bdf
    ".7z",
    ".rar",
})


# ══════════════════════════════════════════════════════════════════════════════
#  Exception
# ══════════════════════════════════════════════════════════════════════════════

class ArchiveStreamError(Exception):
    """Raised when archive reading fails for any reason."""


# ══════════════════════════════════════════════════════════════════════════════
#  Low-level helpers
# ══════════════════════════════════════════════════════════════════════════════

MB: int      = 1024 * 1024
_CHUNK: int  = 256 * 1024   # 256 KB — small enough for smooth progress updates


def _is_edf_like(name: str) -> bool:
    """Return True if *name* ends with .edf or .bdf (case-insensitive)."""
    return Path(name).suffix.lower() in EDF_SUFFIXES


def _chunked_read(fileobj, n_bytes: int, progress_cb=None) -> bytes:
    """
    Read up to *n_bytes* from *fileobj* in _CHUNK-sized pieces.

    Calls ``progress_cb(bytes_read, n_bytes)`` after each chunk when provided.
    Safe against short reads (EOF before n_bytes is reached).
    """
    chunks:   list[bytes] = []
    received: int         = 0
    while received < n_bytes:
        want  = min(_CHUNK, n_bytes - received)
        chunk = fileobj.read(want)
        if not chunk:
            break
        chunks.append(chunk)
        received += len(chunk)
        if progress_cb:
            progress_cb(received, n_bytes)
    return b"".join(chunks)


def _assert_one_edf(names: list[str], archive_path: str) -> None:
    """Raise ArchiveStreamError unless *names* contains exactly one entry."""
    if not names:
        raise ArchiveStreamError(
            f"No EDF or BDF file found inside:\n{archive_path}"
        )
    if len(names) > 1:
        raise ArchiveStreamError(
            f"Expected exactly 1 EDF/BDF inside archive, found {len(names)}:\n"
            + "\n".join(f"  • {n}" for n in names)
        )


def _subprocess_kwargs() -> dict:
    """Extra kwargs for subprocess.run / Popen on Windows: hide console window."""
    kw: dict = {}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kw


# ══════════════════════════════════════════════════════════════════════════════
#  Format-specific streamers
# ══════════════════════════════════════════════════════════════════════════════

def _stream_7z(archive_path: str, n_bytes: int, progress_cb=None):
    """
    Extract the first *n_bytes* of the single EDF/BDF inside a .7z archive.

    Strategy 1 (preferred): pipe via ``7z e -so`` CLI — true streaming, no
    full decompression.
    Strategy 2 (fallback): py7zr — decompresses the entire file into memory.
    Only used when the 7z CLI is not on PATH.
    """
    # ── Strategy 1: 7z CLI ───────────────────────────────────────────────────
    def _try_cli():
        try:
            # List archive contents to find the EDF member name.
            res = subprocess.run(
                ["7z", "l", "-ba", "-slt", archive_path],
                capture_output=True, text=True, timeout=15,
                **_subprocess_kwargs()
            )
            if res.returncode != 0:
                return None, None

            edf_name: str | None = None
            for line in res.stdout.splitlines():
                if line.strip().startswith("Path ="):
                    candidate = line.split("=", 1)[1].strip()
                    if _is_edf_like(candidate):
                        edf_name = candidate
                        break
            if not edf_name:
                return None, None

            # Stream the EDF to stdout; read only the first n_bytes.
            proc = subprocess.Popen(
                ["7z", "e", "-so", archive_path, edf_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **_subprocess_kwargs()
            )
            chunks: list[bytes] = []
            remaining = n_bytes
            received  = 0
            while remaining > 0:
                chunk = proc.stdout.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                received  += len(chunk)
                remaining -= len(chunk)
                if progress_cb:
                    progress_cb(received, n_bytes)

            # Close our pipe end BEFORE kill/wait — prevents deadlock on Windows
            # when the subprocess still has buffered output in the kernel pipe.
            try:
                proc.stdout.close()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass

            return io.BytesIO(b"".join(chunks)), edf_name

        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
            return None, None

    # Attempt CLI first.
    stream, name = _try_cli()
    if stream is not None:
        return stream, name

    # ── Strategy 2: py7zr fallback ───────────────────────────────────────────
    try:
        import py7zr
    except ImportError:
        raise ArchiveStreamError(
            ".7z support requires either:\n"
            "  • The '7z' command-line tool on your PATH  "
            "(preferred — true streaming, no full decompression)\n"
            "  • py7zr   (pip install py7zr)              "
            "(WARNING: decompresses full file into memory)\n\n"
            "Neither was found."
        )

    with py7zr.SevenZipFile(archive_path, "r") as zf:
        names = zf.getnames()
        edfs  = [n for n in names if _is_edf_like(n)]
        _assert_one_edf(edfs, archive_path)
        result = zf.read(targets=[edfs[0]])
        buf    = result[edfs[0]]
        data   = _chunked_read(buf, n_bytes, progress_cb)

    return io.BytesIO(data), edfs[0]


def _stream_rar(archive_path: str, n_bytes: int, progress_cb=None):
    """
    Extract the first *n_bytes* of the single EDF/BDF inside a .rar archive.

    Strategy 1: ``unrar p -inul``    CLI  (cross-platform, true streaming)
    Strategy 2: ``WinRAR.exe p -inul``    (Windows fallback, true streaming)
    Strategy 3: rarfile Python package    (also needs unrar/bsdtar on PATH)
    """
    def _try_cli(cmd: str):
        """
        Attempt streaming via the CLI executable at *cmd*.
        Returns (BytesIO, edf_name) on success, (None, None) on failure.
        """
        try:
            # List members.
            res = subprocess.run(
                [cmd, "lb", archive_path],
                capture_output=True, text=True, timeout=15,
                **_subprocess_kwargs()
            )
            if res.returncode not in (0, 1):   # unrar returns 1 on warnings
                return None, None

            edfs = [
                line.strip()
                for line in res.stdout.splitlines()
                if _is_edf_like(line.strip())
            ]
            if not edfs:
                return None, None
            edf_name = edfs[0]

            proc = subprocess.Popen(
                [cmd, "p", "-inul", archive_path, edf_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **_subprocess_kwargs()
            )
            chunks: list[bytes] = []
            remaining = n_bytes
            received  = 0
            while remaining > 0:
                chunk = proc.stdout.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                received  += len(chunk)
                remaining -= len(chunk)
                if progress_cb:
                    progress_cb(received, n_bytes)

            # Close pipe end first — prevents deadlock on Windows.
            try:
                proc.stdout.close()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass

            return io.BytesIO(b"".join(chunks)), edf_name

        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
            return None, None

    # Strategy 1: unrar (cross-platform)
    stream, name = _try_cli("unrar")
    if stream is not None:
        return stream, name

    # Strategy 2: WinRAR / UnRAR.exe (Windows only, several common install paths)
    if sys.platform == "win32":
        _winrar_candidates = [
            r"C:\Program Files\WinRAR\UnRAR.exe",
            r"C:\Program Files\WinRAR\WinRAR.exe",
            r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
            r"C:\Program Files (x86)\WinRAR\WinRAR.exe",
        ]
        # Also look for UnRAR.exe shipped alongside this toolbox.
        _here = Path(__file__).parent
        _winrar_candidates.insert(0, str(_here / "UnRAR.exe"))

        for wr_path in _winrar_candidates:
            if os.path.isfile(wr_path):
                stream, name = _try_cli(wr_path)
                if stream is not None:
                    return stream, name

    # Strategy 3: rarfile package
    try:
        import rarfile
    except ImportError:
        raise ArchiveStreamError(
            ".rar support: no working extractor found.\n\n"
            "Install one of the following:\n"
            "  • WinRAR  (https://www.rarlab.com)            "
            "— already on most Windows machines\n"
            "  • UnRAR   (https://www.rarlab.com/rar_add.htm) "
            "— free standalone CLI tool\n"
            "  • rarfile Python package:  pip install rarfile\n"
            "    (rarfile also requires unrar or bsdtar on your PATH)"
        )

    with rarfile.RarFile(archive_path) as rf:
        edfs = [m for m in rf.namelist() if _is_edf_like(m)]
        _assert_one_edf(edfs, archive_path)
        with rf.open(edfs[0]) as f:
            data = _chunked_read(f, n_bytes, progress_cb)

    return io.BytesIO(data), edfs[0]


# ══════════════════════════════════════════════════════════════════════════════
#  Main public function
# ══════════════════════════════════════════════════════════════════════════════

def stream_edf_bytes(
    archive_path: str,
    n_bytes: int,
    progress_cb=None,
):
    """
    Open an archive, locate the single EDF/BDF inside, and return the first
    *n_bytes* as a ``(BytesIO, edf_filename)`` tuple.

    Parameters
    ----------
    archive_path : str
        Path to the compressed archive file.
    n_bytes : int
        Maximum number of bytes to read from the EDF/BDF stream.
        Actual bytes returned may be less if the compressed EDF is smaller.
    progress_cb : callable, optional
        Called as ``progress_cb(bytes_received: int, total: int)`` after each
        read chunk.  Suitable for driving a progress bar.

    Returns
    -------
    (io.BytesIO, str)
        BytesIO containing the first *n_bytes* of the EDF, and the member
        filename as stored in the archive.

    Raises
    ------
    ArchiveStreamError
        On unsupported format, missing EDF member, ambiguous contents, or
        any extraction error.
    """
    p = archive_path.lower()

    # ── ZIP ──────────────────────────────────────────────────────────────────
    if p.endswith(".zip"):
        import zipfile
        with zipfile.ZipFile(archive_path, "r") as zf:
            edfs = [m for m in zf.namelist() if _is_edf_like(m)]
            _assert_one_edf(edfs, archive_path)
            with zf.open(edfs[0]) as f:
                data = _chunked_read(f, n_bytes, progress_cb)
        return io.BytesIO(data), edfs[0]

    # ── TAR (any flavour: .tar.gz .tgz .tar.bz2 .tar.xz .tar) ───────────────
    if any(p.endswith(s) for s in (".tar.gz", ".tgz", ".tar.bz2",
                                    ".tar.xz", ".tar")):
        import tarfile
        with tarfile.open(archive_path, "r:*") as tf:
            members = [m for m in tf.getmembers() if _is_edf_like(m.name)]
            _assert_one_edf([m.name for m in members], archive_path)
            fobj = tf.extractfile(members[0])
            if fobj is None:
                raise ArchiveStreamError(
                    "Could not open EDF member in tar archive."
                )
            data = _chunked_read(fobj, n_bytes, progress_cb)
        return io.BytesIO(data), members[0].name

    # ── Bare .gz (not tar — assumes filename is something.edf.gz) ────────────
    if p.endswith(".gz"):
        import gzip
        with gzip.open(archive_path, "rb") as f:
            data = _chunked_read(f, n_bytes, progress_cb)
        fname = Path(archive_path).stem   # strip .gz, keeps .edf
        return io.BytesIO(data), fname

    # ── 7Z ───────────────────────────────────────────────────────────────────
    if p.endswith(".7z"):
        return _stream_7z(archive_path, n_bytes, progress_cb)

    # ── RAR ──────────────────────────────────────────────────────────────────
    if p.endswith(".rar"):
        return _stream_rar(archive_path, n_bytes, progress_cb)

    raise ArchiveStreamError(
        f"Unsupported archive extension: '{Path(archive_path).suffix}'\n"
        f"Supported: .zip  .tar.gz  .tgz  .tar.bz2  .tar.xz  .tar  "
        f".gz  .7z  .rar"
    )
