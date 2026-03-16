#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EDF Archive Inspector  v1.1
────────────────────────────────────────────────────────────────────────────────
Standalone GUI tool that peeks inside a compressed archive (.zip, .tar.gz,
.gz, .7z, .rar) containing a single EDF/BDF file, without extracting the full
file to disk.

From the first N MB of the compressed stream it recovers:
  • Full EDF/BDF header  (patient, recording, date/time, file structure)
  • Per-channel metadata (label, unit, sample rate, phys/dig ranges, prefilter)
  • EDF+ / BDF+ TAL annotations (all that fall within the peeked records)
  • Per-channel signal statistics  (mean ± std, min, max) via numpy

Archive support
  .zip      → stdlib zipfile              (streaming ✓)
  .tar.gz / .tgz / .tar.bz2 / .tar.xz
            → stdlib tarfile              (streaming ✓)
  .edf.gz   → stdlib gzip (bare)         (streaming ✓)
  .7z       → 7z CLI subprocess first,   (streaming ✓)
              then py7zr fallback         (full decompress ✗ for large files)
  .rar      → rarfile package             (streaming ✓)

Optional dependencies (pip install as needed):
  py7zr     – .7z fallback when 7z CLI is unavailable
  rarfile   – .rar support

Author:  based on edfreader_mld2.py  (Dr. Milad Khaki / Teunis van Beelen)
────────────────────────────────────────────────────────────────────────────────
"""

import io
import os
import queue
import struct
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from pathlib import Path

# numpy is required for fast signal stats
try:
    import numpy as np
    _NUMPY = True
except ImportError:
    _NUMPY = False


# ══════════════════════════════════════════════════════════════════════════════
#  ARCHIVE STREAMING
#  Each format returns (BytesIO with first n_bytes, edf_filename_in_archive)
# ══════════════════════════════════════════════════════════════════════════════

class ArchiveStreamError(Exception):
    pass


def _is_edf_like(name: str) -> bool:
    return name.lower().endswith((".edf", ".bdf"))


MB      = 1024 * 1024
_CHUNK  = 256 * 1024   # 256 KB read chunks — small enough for smooth progress updates


def _chunked_read(fileobj, n_bytes: int, progress_cb=None) -> bytes:
    """
    Read up to n_bytes from fileobj in _CHUNK-sized pieces.
    Calls progress_cb(bytes_read, n_bytes) after every chunk if provided.
    Safe against short reads (EOF before n_bytes).
    """
    chunks   = []
    received = 0
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


def stream_edf_bytes(archive_path: str, n_bytes: int, progress_cb=None):
    """
    Open the archive, find the single EDF/BDF inside, and return
    (BytesIO with first n_bytes, edf_filename).

    progress_cb(bytes_received: int, total: int) is called after each chunk
    so callers can drive a progress bar.  Pass None to disable.

    Raises ArchiveStreamError on any problem.
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

    # ── TAR (any flavour) ────────────────────────────────────────────────────
    if any(p.endswith(s) for s in (".tar.gz", ".tgz", ".tar.bz2",
                                    ".tar.xz", ".tar")):
        import tarfile
        with tarfile.open(archive_path, "r:*") as tf:
            edfs = [m for m in tf.getmembers() if _is_edf_like(m.name)]
            _assert_one_edf([m.name for m in edfs], archive_path)
            fobj = tf.extractfile(edfs[0])
            if fobj is None:
                raise ArchiveStreamError("Could not open EDF member in tar archive.")
            data = _chunked_read(fobj, n_bytes, progress_cb)
        return io.BytesIO(data), edfs[0].name

    # ── BARE .gz (not tar — assumes file is named  something.edf.gz) ─────────
    if p.endswith(".gz"):
        import gzip
        with gzip.open(archive_path, "rb") as f:
            data = _chunked_read(f, n_bytes, progress_cb)
        fname = Path(archive_path).stem   # strip .gz → keeps .edf
        return io.BytesIO(data), fname

    # ── 7Z ───────────────────────────────────────────────────────────────────
    if p.endswith(".7z"):
        return _stream_7z(archive_path, n_bytes, progress_cb)

    # ── RAR ───────────────────────────────────────────────────────────────────
    if p.endswith(".rar"):
        return _stream_rar(archive_path, n_bytes, progress_cb)

    raise ArchiveStreamError(
        f"Unsupported archive extension: '{Path(archive_path).suffix}'\n"
        f"Supported: .zip  .tar.gz  .tgz  .tar.bz2  .tar.xz  .tar  .gz  .7z  .rar"
    )


def _subprocess_kwargs() -> dict:
    """Extra kwargs for subprocess on Windows: hide the console window."""
    kw = {}
    if sys.platform == "win32":
        import subprocess as _sp
        kw["creationflags"] = _sp.CREATE_NO_WINDOW
    return kw


def _assert_one_edf(names: list, archive_path: str):
    if not names:
        raise ArchiveStreamError(
            f"No EDF or BDF file found inside:\n{archive_path}"
        )
    if len(names) > 1:
        raise ArchiveStreamError(
            f"Expected exactly 1 EDF/BDF inside archive, found {len(names)}:\n"
            + "\n".join(f"  • {n}" for n in names)
        )


def _stream_7z(archive_path: str, n_bytes: int, progress_cb=None):
    """
    Strategy 1: pipe via '7z e -so' CLI (fast, no full decompression).
    Strategy 2: py7zr fallback  (decompresses entire file — slow for >1 GB).
    """
    import subprocess

    # ── Try 7z CLI ────────────────────────────────────────────────────────────
    def _try_cli():
        try:
            res = subprocess.run(
                ["7z", "l", "-ba", "-slt", archive_path],
                capture_output=True, text=True, timeout=15,
                **_subprocess_kwargs()
            )
            if res.returncode != 0:
                return None, None
            edf_name = None
            for line in res.stdout.splitlines():
                if line.strip().startswith("Path ="):
                    candidate = line.split("=", 1)[1].strip()
                    if _is_edf_like(candidate):
                        edf_name = candidate
                        break
            if not edf_name:
                return None, None
            proc = subprocess.Popen(
                ["7z", "e", "-so", archive_path, edf_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **_subprocess_kwargs()
            )
            chunks, remaining, received = [], n_bytes, 0
            while remaining > 0:
                chunk = proc.stdout.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                received  += len(chunk)
                remaining -= len(chunk)
                if progress_cb:
                    progress_cb(received, n_bytes)
            # Must close our pipe end BEFORE kill/wait on Windows — otherwise
            # proc.wait() deadlocks if the subprocess still has buffered output.
            try: proc.stdout.close()
            except Exception: pass
            try: proc.kill()
            except Exception: pass
            try: proc.wait(timeout=5)
            except Exception: pass
            return io.BytesIO(b"".join(chunks)), edf_name
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
            return None, None
    try:
        import py7zr
    except ImportError:
        raise ArchiveStreamError(
            ".7z support requires either:\n"
            "  • The '7z' command-line tool on your PATH  (preferred — no full decompression)\n"
            "  • py7zr   (pip install py7zr)              (WARNING: decompresses full file into memory)\n\n"
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
    RAR streaming — three strategies in order:
      1. 'unrar p -inul' CLI             (fast, streaming, no full decompression)
      2. WinRAR CLI 'WinRAR.exe p -inul' (Windows fallback if unrar not on PATH)
      3. rarfile Python package           (also needs unrar or bsdtar under the hood)
    """
    import subprocess

    def _try_cli(cmd_list: str):
        """
        Try to stream via a CLI command.
        cmd_list: name of the CLI executable ('unrar' or full path to WinRAR.exe).
        Returns (BytesIO, edf_name) or (None, None).
        """
        try:
            # List members
            res = subprocess.run(
                [cmd_list, "lb", archive_path],
                capture_output=True, text=True, timeout=15,
                **_subprocess_kwargs()
            )
            if res.returncode not in (0, 1):   # unrar returns 1 on warnings
                return None, None
            # Find the EDF member — may be a bare filename or a path
            edfs = [
                l.strip() for l in res.stdout.splitlines()
                if _is_edf_like(l.strip())
            ]
            if not edfs:
                return None, None
            edf_name = edfs[0]

            proc = subprocess.Popen(
                [cmd_list, "p", "-inul", archive_path, edf_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **_subprocess_kwargs()
            )
            chunks, remaining, received = [], n_bytes, 0
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
            try: proc.stdout.close()
            except Exception: pass
            try: proc.kill()
            except Exception: pass
            try: proc.wait(timeout=5)
            except Exception: pass
            return io.BytesIO(b"".join(chunks)), edf_name
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
            return None, None

    # Strategy 1: unrar (cross-platform)
    stream, name = _try_cli("unrar")
    if stream is not None:
        return stream, name

    # Strategy 2: WinRAR.exe bundled CLI (Windows only)
    if sys.platform == "win32":
        for wr_path in [
            r"C:\Program Files\WinRAR\UnRAR.exe",
            r"C:\Program Files\WinRAR\WinRAR.exe",
            r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
            r"C:\Program Files (x86)\WinRAR\WinRAR.exe",
        ]:
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
            "  • WinRAR  (https://www.rarlab.com)  — already on most Windows machines\n"
            "  • UnRAR   (https://www.rarlab.com/rar_add.htm)  — free CLI tool\n"
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
#  EDF PEEK READER
#  BytesIO-native, truncation-tolerant.
#  Architecture follows edfreader_mld2.py (edfreader by Teunis van Beelen,
#  updated by Dr. Milad Khaki).
# ══════════════════════════════════════════════════════════════════════════════

class EDFPeekError(Exception):
    pass


class EDFPeekReader:
    """
    Reads EDF/BDF header, TAL annotations and per-channel signal stats
    from a (potentially truncated) BytesIO peek stream.

    Public attributes after construction:
        header           dict   – all fixed and per-signal-header fields
        signals          list   – one dict per channel (see _parse_signal_header)
        annotations      list   – dicts {onset, duration, description}
        signal_stats     list   – dicts {label, unit, n_samples, mean, std, min, max}
        records_available int   – number of complete data records that were parsed
        is_bdf           bool
        is_edfplus        bool
        format_str       str    – 'EDF' | 'EDF+C' | 'EDF+D' | 'BDF' | 'BDF+C' | 'BDF+D'
    """

    # edfreader_mld2 stores raw 16-char labels like "EDF Annotations "
    # but _ascii() strips spaces, so compare against stripped versions
    _ANNOT_LABELS = {"EDF Annotations", "BDF Annotations"}
    _MAX_SIGNALS  = 640
    _BDF_MAGIC    = b'\xffBIOSEMI'

    def __init__(self, stream: io.BytesIO):
        self._s               = stream
        self.header           = {}
        self.signals          = []
        self.annotations      = []
        self.signal_stats     = []
        self.records_available = 0
        self.is_bdf           = False
        self.is_edfplus       = False
        self.format_str       = "EDF"
        self._bytes_per_smp   = 2   # 2 for EDF, 3 for BDF
        self._hdrsize         = 256
        self._recordsize      = 0
        self._parse()

    # ── Convenience ──────────────────────────────────────────────────────────

    def duration_str(self) -> str:
        """Total recording duration as HH:MM:SS.xx, or 'unknown'."""
        nr = self.header.get("num_records", -1)
        dr = self.header.get("record_duration", 0.0)
        if nr < 0 or dr <= 0:
            return "unknown"
        total = nr * dr
        h = int(total // 3600)
        m = int((total % 3600) // 60)
        s = total % 60
        return f"{h:02d}:{m:02d}:{s:05.2f}"

    def peek_duration_str(self) -> str:
        """Duration actually parsed from peeked data."""
        dr = self.header.get("record_duration", 0.0)
        total = self.records_available * dr
        h = int(total // 3600)
        m = int((total % 3600) // 60)
        s = total % 60
        return f"{h:02d}:{m:02d}:{s:05.2f}"

    # ── Internal: top-level parser ────────────────────────────────────────────

    def _parse(self):
        self._s.seek(0)
        self._parse_fixed_header()
        self._parse_signal_header()
        self._parse_data_records()

    # ── Fixed header (first 256 bytes) ───────────────────────────────────────

    def _parse_fixed_header(self):
        raw = self._safe_read(256)
        if len(raw) < 256:
            raise EDFPeekError(
                f"Stream too short for EDF fixed header "
                f"(need 256 bytes, got {len(raw)})."
            )

        # Version / format detection (mirrors edfreader_mld2 __checkEDFheader)
        if raw[:8] == self._BDF_MAGIC:
            self.is_bdf = True
            self._bytes_per_smp = 3
            self.format_str = "BDF"
        elif raw[0] == ord("0"):
            self.format_str = "EDF"
        else:
            raise EDFPeekError(
                "Byte 0 of stream is neither '0' (EDF) nor 0xFF (BDF). "
                "Is this really an EDF/BDF file?"
            )

        h = {}
        h["patient"]          = self._ascii(raw[8:88])
        h["recording"]        = self._ascii(raw[88:168])
        h["startdate_raw"]    = self._ascii(raw[168:176])
        h["starttime_raw"]    = self._ascii(raw[176:184])
        try:
            h["header_bytes"]     = int(self._ascii(raw[184:192]))
        except ValueError:
            h["header_bytes"]     = 256
        h["reserved"]         = self._ascii(raw[192:236])
        try:
            h["num_records"]      = int(self._ascii(raw[236:244]))
        except ValueError:
            h["num_records"]      = -1
        try:
            h["record_duration"]  = float(self._ascii(raw[244:252]))
        except ValueError:
            h["record_duration"]  = 0.0
        try:
            h["num_signals"]      = int(self._ascii(raw[252:256]))
        except ValueError:
            raise EDFPeekError("Could not read number of signals from header.")

        # EDF+ / BDF+ detection
        res = h["reserved"]
        if res.startswith("EDF+C"):
            self.is_edfplus = True
            self.format_str = "EDF+C"
        elif res.startswith("EDF+D"):
            self.is_edfplus = True
            self.format_str = "EDF+D"
        elif res.startswith("BDF+C"):
            self.is_edfplus = True
            self.format_str = "BDF+C"
        elif res.startswith("BDF+D"):
            self.is_edfplus = True
            self.format_str = "BDF+D"

        self._hdrsize = h["header_bytes"]

        # Parse start date / time into human-readable strings
        sd = h["startdate_raw"]  # dd.mm.yy
        st = h["starttime_raw"]  # hh.mm.ss
        try:
            dd, mm, yy = sd.split(".")
            yy_full = 2000 + int(yy) if int(yy) <= 84 else 1900 + int(yy)
            h["startdate"] = f"{dd}.{mm}.{yy_full}"
        except Exception:
            h["startdate"] = sd
        try:
            hh, mn, ss = st.split(".")
            h["starttime"] = f"{hh}:{mn}:{ss}"
        except Exception:
            h["starttime"] = st

        # EDF+ structured patient / recording subfields
        if self.is_edfplus:
            h.update(self._parse_edfplus_patient(h["patient"]))
            h.update(self._parse_edfplus_recording(h["recording"]))

        self.header = h

    def _parse_edfplus_patient(self, s: str) -> dict:
        """
        EDF+ patient field: code sex birthdate name [additional]
        Dots stand for unknown/not-provided fields.
        """
        parts = s.split()
        out = {}
        if len(parts) >= 1: out["patient_code"]       = parts[0]
        if len(parts) >= 2: out["patient_sex"]        = parts[1]
        if len(parts) >= 3: out["patient_birthdate"]  = parts[2]
        if len(parts) >= 4: out["patient_name"]       = parts[3]
        if len(parts) >= 5: out["patient_additional"] = " ".join(parts[4:])
        return out

    def _parse_edfplus_recording(self, s: str) -> dict:
        """
        EDF+ recording field:
          Startdate DD-MMM-YYYY admincode technician equipment [additional]
        """
        parts = s.split()
        out = {}
        if len(parts) >= 2 and parts[0].upper() == "STARTDATE":
            out["recording_startdate"]   = parts[1]
            if len(parts) >= 3: out["recording_admincode"]   = parts[2]
            if len(parts) >= 4: out["recording_technician"]  = parts[3]
            if len(parts) >= 5: out["recording_equipment"]   = parts[4]
            if len(parts) >= 6: out["recording_additional"]  = " ".join(parts[5:])
        return out

    # ── Per-signal header (ns × 256 bytes after fixed header) ─────────────────

    def _parse_signal_header(self):
        ns = self.header.get("num_signals", 0)
        if ns <= 0 or ns > self._MAX_SIGNALS:
            raise EDFPeekError(f"Invalid number of signals: {ns}")

        # Re-read the full header block into memory
        self._s.seek(0)
        full_hdr = self._safe_read(self._hdrsize)
        if len(full_hdr) < self._hdrsize:
            raise EDFPeekError(
                f"Stream too short for full signal header "
                f"(need {self._hdrsize} bytes, got {len(full_hdr)})."
            )

        base = 256  # signal header starts after the 256-byte fixed header

        def _field(offset_per_sig: int, width: int) -> list:
            start = base + offset_per_sig * ns
            return [
                self._ascii(full_hdr[start + i * width : start + i * width + width])
                for i in range(ns)
            ]

        labels      = _field(0,   16)
        transducers = _field(16,  80)
        phys_dims   = _field(96,   8)
        phys_mins   = _field(104,  8)
        phys_maxs   = _field(112,  8)
        dig_mins    = _field(120,  8)
        dig_maxs    = _field(128,  8)
        prefilters  = _field(136, 80)
        ns_per_rec  = _field(216,  8)
        # reserved  = _field(224, 32)  # not displayed

        record_size = 0
        dr = self.header.get("record_duration", 1.0) or 1.0

        for i in range(ns):
            try:
                dmin = int(dig_mins[i])
                dmax = int(dig_maxs[i])
            except ValueError:
                dmin, dmax = -32768, 32767
            try:
                pmin = float(phys_mins[i])
                pmax = float(phys_maxs[i])
            except ValueError:
                pmin, pmax = float(dmin), float(dmax)

            try:
                n_smp = int(ns_per_rec[i])
            except ValueError:
                n_smp = 0

            ddiff = dmax - dmin
            pdiff = pmax - pmin
            gain   = pdiff / ddiff if ddiff != 0 else 1.0
            offset = (pmax / gain - dmax) if gain != 0 else 0.0

            is_annot = labels[i] in self._ANNOT_LABELS

            self.signals.append({
                "label":        labels[i],
                "transducer":   transducers[i],
                "unit":         phys_dims[i],
                "phys_min":     pmin,
                "phys_max":     pmax,
                "dig_min":      dmin,
                "dig_max":      dmax,
                "prefilter":    prefilters[i],
                "ns_per_rec":   n_smp,
                "srate":        n_smp / dr,
                "gain":         gain,
                "offset":       offset,
                "is_annotation": is_annot,
            })
            record_size += n_smp * self._bytes_per_smp

        self._recordsize = record_size

    # ── Data records ──────────────────────────────────────────────────────────

    def _parse_data_records(self):
        """
        Iterate over complete data records within the peeked stream.
        • Annotation channels → TAL parser
        • Signal channels     → numpy stats (online accumulation per channel)
        """
        ns = len(self.signals)
        if ns == 0 or self._recordsize <= 0:
            return

        self._s.seek(self._hdrsize)
        num_records = self.header.get("num_records", -1)

        # Per-channel accumulators for Welford online mean/variance + extrema
        # We keep them as lists of numpy arrays to avoid huge Python loops
        raw_accum  = [[] for _ in range(ns)]   # list of 1-D numpy arrays

        records_parsed = 0
        while True:
            rec = self._safe_read(self._recordsize)
            if len(rec) < self._recordsize:
                break  # truncated — stop cleanly
            if num_records > 0 and records_parsed >= num_records:
                break

            offset_b = 0
            for i, sig in enumerate(self.signals):
                n_smp   = sig["ns_per_rec"]
                n_bytes = n_smp * self._bytes_per_smp
                chunk   = rec[offset_b : offset_b + n_bytes]
                offset_b += n_bytes

                if sig["is_annotation"]:
                    self._parse_tal_chunk(chunk)
                else:
                    if _NUMPY:
                        if self._bytes_per_smp == 2:
                            arr = np.frombuffer(chunk, dtype="<i2").astype(np.float64)
                        else:
                            arr = self._decode_bdf_chunk(chunk, n_smp)
                        raw_accum[i].append(arr)

            records_parsed += 1

        self.records_available = records_parsed

        # Finalise stats per channel
        for i, sig in enumerate(self.signals):
            if sig["is_annotation"]:
                continue

            if not _NUMPY or not raw_accum[i]:
                self.signal_stats.append({
                    "label": sig["label"], "unit": sig["unit"],
                    "n_samples": 0,
                    "mean": None, "std": None, "min": None, "max": None,
                })
                continue

            all_raw  = np.concatenate(raw_accum[i])
            phys     = (all_raw + sig["offset"]) * sig["gain"]
            self.signal_stats.append({
                "label":    sig["label"],
                "unit":     sig["unit"],
                "n_samples": len(phys),
                "mean":     float(np.mean(phys)),
                "std":      float(np.std(phys)),
                "min":      float(np.min(phys)),
                "max":      float(np.max(phys)),
            })

    @staticmethod
    def _decode_bdf_chunk(chunk: bytes, n_smp: int) -> "np.ndarray":
        """Decode n_smp × 3-byte signed little-endian (BDF) samples."""
        arr = np.zeros(n_smp, dtype=np.int32)
        for k in range(min(n_smp, len(chunk) // 3)):
            b = chunk[k*3 : k*3+3]
            val = b[0] | (b[1] << 8) | (b[2] << 16)
            if val & 0x800000:
                val -= 0x1000000
            arr[k] = val
        return arr.astype(np.float64)

    # ── TAL parser (EDF+ annotations) ─────────────────────────────────────────

    def _parse_tal_chunk(self, chunk: bytes):
        """
        Parse a TAL (Time-stamped Annotations List) block from one data record.

        TAL format (EDF+ spec §2.2.4):
          +onset[.subsec]\x14[duration\x14]description\x14[\x00]
          Multiple TALs are concatenated and the block is zero-padded.

        The first TAL in every record is a "time-keeping" annotation with
        empty description — we skip those.
        """
        # Each TAL is terminated by \x00; split on that
        for raw_tal in chunk.split(b"\x00"):
            if not raw_tal:
                continue

            # Split on \x14 (ASCII 20 = Unicode "Device Control 4")
            parts = raw_tal.split(b"\x14")
            if not parts or not parts[0]:
                continue

            # ── Onset ────────────────────────────────────────────────────────
            onset_raw = parts[0]
            try:
                onset_str = onset_raw.decode("latin-1", errors="replace").strip()
                onset = float(onset_str.lstrip("+"))
            except (ValueError, UnicodeDecodeError):
                continue  # malformed onset — skip TAL

            if len(parts) < 2:
                continue

            # ── Duration (optional) ──────────────────────────────────────────
            # parts[1] is duration if it parses as a non-negative float
            # AND there is at least one more field after it (the description).
            duration = ""
            desc_start = 1
            if len(parts) >= 3 and parts[1]:
                try:
                    dur_val = float(
                        parts[1].decode("latin-1", errors="replace").strip()
                    )
                    if dur_val >= 0:
                        duration = dur_val
                        desc_start = 2
                except ValueError:
                    pass  # parts[1] is a description, not a duration

            # ── Descriptions ─────────────────────────────────────────────────
            for p in parts[desc_start:]:
                if not p:
                    continue
                try:
                    desc = p.decode("utf-8", errors="replace").strip()
                except Exception:
                    continue
                if not desc:
                    continue  # skip time-keeping annotations (empty description)
                self.annotations.append({
                    "onset":       onset,
                    "duration":    duration,
                    "description": desc,
                })

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _safe_read(self, n: int) -> bytes:
        """Read up to n bytes — never raises on short read."""
        return self._s.read(n)

    @staticmethod
    def _ascii(b: bytes) -> str:
        return b.decode("latin-1", errors="replace").strip()


# ══════════════════════════════════════════════════════════════════════════════
#  GUI
# ══════════════════════════════════════════════════════════════════════════════

ARCHIVE_FILETYPES = [
    ("Archive files",  "*.zip *.gz *.tar.gz *.tgz *.tar.bz2 *.7z *.rar"),
    ("ZIP",            "*.zip"),
    ("GZip",           "*.gz *.tar.gz *.tgz"),
    ("7-Zip",          "*.7z"),
    ("RAR",            "*.rar"),
    ("All files",      "*.*"),
]

_HEADER_BG  = "#1E2B3C"
_ACCENT     = "#4DA6FF"
_LIGHT_TEXT = "#E0E8F0"
_MONO       = ("Courier", 10)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EDF Archive Inspector  v1.0")
        self.configure(bg=_HEADER_BG)
        self.minsize(960, 680)
        self._build_style()
        self._build_ui()

    # ── Style ─────────────────────────────────────────────────────────────────

    def _build_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TNotebook",        background=_HEADER_BG, borderwidth=0)
        s.configure("TNotebook.Tab",    background="#2C3E50",  foreground=_LIGHT_TEXT,
                    padding=[10, 4], font=("", 10))
        s.map("TNotebook.Tab",
              background=[("selected", "#1A252F")],
              foreground=[("selected", _ACCENT)])
        s.configure("TFrame",           background="#1A252F")
        s.configure("Treeview",         background="#1A252F", foreground=_LIGHT_TEXT,
                    fieldbackground="#1A252F", rowheight=22, font=("", 10))
        s.configure("Treeview.Heading", background="#2C3E50", foreground=_ACCENT,
                    font=("", 10, "bold"))
        s.map("Treeview", background=[("selected", "#2E5077")])
        s.configure("TScrollbar",       background="#2C3E50", troughcolor="#1A252F")
        s.configure("Horizontal.TProgressbar",
                    troughcolor="#1A252F", background=_ACCENT)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Top toolbar ──────────────────────────────────────────────────────
        top = tk.Frame(self, bg=_HEADER_BG, padx=10, pady=8)
        top.pack(side=tk.TOP, fill=tk.X)

        tk.Label(top, text="Archive:", bg=_HEADER_BG,
                 fg=_LIGHT_TEXT, font=("", 10)).pack(side=tk.LEFT)

        self._path_var = tk.StringVar()
        path_entry = tk.Entry(top, textvariable=self._path_var, width=58,
                              bg="#2C3E50", fg=_LIGHT_TEXT, insertbackground=_LIGHT_TEXT,
                              relief=tk.FLAT, font=("", 10))
        path_entry.pack(side=tk.LEFT, padx=6)

        tk.Button(top, text="Browse…", command=self._browse,
                  bg="#2C3E50", fg=_LIGHT_TEXT, relief=tk.FLAT,
                  activebackground="#3D5166", font=("", 10)).pack(side=tk.LEFT)

        tk.Label(top, text="    Peek (MB):", bg=_HEADER_BG,
                 fg=_LIGHT_TEXT, font=("", 10)).pack(side=tk.LEFT)
        self._peek_var = tk.IntVar(value=100)
        tk.Spinbox(top, from_=1, to=4000, width=6,
                   textvariable=self._peek_var,
                   bg="#2C3E50", fg=_LIGHT_TEXT, buttonbackground="#2C3E50",
                   relief=tk.FLAT, font=("", 10)).pack(side=tk.LEFT, padx=6)

        self._inspect_btn = tk.Button(
            top, text="  Inspect ▶  ", command=self._start_inspect,
            bg=_ACCENT, fg="#0A1520", font=("", 10, "bold"),
            relief=tk.FLAT, activebackground="#3399FF", cursor="hand2"
        )
        self._inspect_btn.pack(side=tk.LEFT, padx=10)

        # ── Notebook ──────────────────────────────────────────────────────────
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self._tab_header    = self._make_text_tab(nb)
        self._tab_channels  = self._make_tree_tab(nb, (
            "Label", "Unit", "Srate (Hz)", "Phys Min", "Phys Max",
            "Dig Min", "Dig Max", "Prefilter", "ns / rec"
        ))
        self._tab_annots    = self._make_text_tab(nb)
        self._tab_stats     = self._make_tree_tab(nb, (
            "Channel", "Unit", "N samples", "Mean", "Std Dev", "Min", "Max"
        ))
        self._tab_log       = self._make_text_tab(nb)

        nb.add(self._tab_header[0],   text="  📋  Header  ")
        nb.add(self._tab_channels[0], text="  📡  Channels  ")
        nb.add(self._tab_annots[0],   text="  📝  Annotations  ")
        nb.add(self._tab_stats[0],    text="  📊  Signal Stats  ")
        nb.add(self._tab_log[0],      text="  🪵  Log  ")

        # ── Progress + status ─────────────────────────────────────────────────
        progress_row = tk.Frame(self, bg=_HEADER_BG)
        progress_row.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(0, 2))

        self._pct_var = tk.StringVar(value="")
        tk.Label(progress_row, textvariable=self._pct_var, width=7,
                 anchor=tk.E, bg=_HEADER_BG, fg=_ACCENT,
                 font=("", 9, "bold")).pack(side=tk.RIGHT, padx=(4, 0))

        self._progress = ttk.Progressbar(progress_row, mode="determinate",
                                         maximum=100,
                                         style="Horizontal.TProgressbar")
        self._progress.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._status_var = tk.StringVar(value="Ready — select an archive and press Inspect.")
        tk.Label(self, textvariable=self._status_var, anchor=tk.W,
                 bg=_HEADER_BG, fg="#8AACCC", font=("", 9),
                 padx=10).pack(side=tk.BOTTOM, fill=tk.X)

    def _make_text_tab(self, nb):
        frame = ttk.Frame(nb)
        txt = scrolledtext.ScrolledText(
            frame, font=_MONO, wrap=tk.NONE,
            bg="#0F1A26", fg=_LIGHT_TEXT,
            insertbackground=_LIGHT_TEXT,
            selectbackground="#2E5077",
            relief=tk.FLAT
        )
        txt.pack(fill=tk.BOTH, expand=True)
        txt.config(state=tk.DISABLED)
        return frame, txt

    def _make_tree_tab(self, nb, columns):
        frame = ttk.Frame(nb)
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        col_widths = {
            "Label": 150, "Channel": 150, "Unit": 60, "Srate (Hz)": 90,
            "Phys Min": 90, "Phys Max": 90, "Dig Min": 80, "Dig Max": 80,
            "Prefilter": 160, "ns / rec": 80, "N samples": 100,
            "Mean": 110, "Std Dev": 110, "Min": 110, "Max": 110,
        }
        for col in columns:
            tree.heading(col, text=col,
                         command=lambda c=col, t=tree: self._sort_tree(t, c))
            tree.column(col, width=col_widths.get(col, 100), anchor=tk.W)

        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL,   command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return frame, tree

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select compressed EDF archive",
            filetypes=ARCHIVE_FILETYPES
        )
        if path:
            self._path_var.set(path)

    def _start_inspect(self):
        path = self._path_var.get().strip()
        if not path:
            messagebox.showwarning("No file", "Please select an archive file first.")
            return
        if not os.path.isfile(path):
            messagebox.showerror("File not found", f"Cannot find:\n{path}")
            return
        if not _NUMPY:
            messagebox.showwarning(
                "numpy not found",
                "numpy is not installed. Signal stats will be unavailable.\n"
                "Install with:  pip install numpy"
            )

        n_bytes = self._peek_var.get() * MB
        self._inspect_btn.config(state=tk.DISABLED)
        self._reset_progress()
        self._set_status(f"Streaming first {self._peek_var.get()} MB …")
        self._log_clear()
        self._log(f"Archive : {path}")
        self._log(f"Peek    : {self._peek_var.get()} MB  ({n_bytes:,} bytes)")

        # ── Queue that the worker posts events into ───────────────────────────
        # Event tuples:
        #   ("progress", received_bytes, total_bytes)
        #   ("log",      message_str)
        #   ("done",     EDFPeekReader, edf_name, n_bytes)
        #   ("error",    traceback_str)
        self._q = queue.Queue()
        threading.Thread(
            target=self._worker, args=(path, n_bytes, self._q), daemon=True
        ).start()
        # Start polling — 50 ms interval is fast enough for smooth progress
        self.after(50, self._poll_queue)

    def _worker(self, path: str, n_bytes: int, q: queue.Queue):
        """Runs entirely on the background thread. Communicates via q only."""
        def progress_cb(received, total):
            q.put(("progress", received, total))

        def log(msg):
            q.put(("log", msg))

        try:
            log(f"Opening archive …")
            stream, edf_name = stream_edf_bytes(path, n_bytes, progress_cb)
            log(f"Stream OK  →  {edf_name}  ({len(stream.getbuffer()):,} bytes buffered)")
            log("Parsing EDF header …")
            reader = EDFPeekReader(stream)
            log(f"Format       : {reader.format_str}")
            log(f"Signals      : {len(reader.signals)}")
            log(f"Records avail: {reader.records_available} / "
                f"{reader.header.get('num_records', '?')}")
            log(f"Annotations  : {len(reader.annotations)}")
            q.put(("done", reader, edf_name, n_bytes))
        except Exception:
            q.put(("error", traceback.format_exc()))

    def _poll_queue(self):
        """
        Drain all pending events from the worker queue.
        Called on the main thread every 50 ms via self.after().
        Reschedules itself until a 'done' or 'error' event arrives.
        """
        keep_polling = True
        try:
            while True:                         # drain everything available now
                event = self._q.get_nowait()
                kind  = event[0]

                if kind == "progress":
                    _, received, total = event
                    pct = min(100.0, received / total * 100) if total > 0 else 0.0
                    self._progress["value"] = pct
                    self._pct_var.set(f"{pct:.0f}%")
                    self._set_status(
                        f"Streaming …  "
                        f"{received/MB:.1f} / {total/MB:.0f} MB  ({pct:.0f}%)"
                    )

                elif kind == "log":
                    self._log(event[1])

                elif kind == "done":
                    _, reader, edf_name, n_bytes = event
                    self._progress["value"] = 100
                    self._pct_var.set("✓ done")
                    self._inspect_btn.config(state=tk.NORMAL)
                    nr_total     = reader.header.get("num_records", -1)
                    nr_total_str = str(nr_total) if nr_total > 0 else "?"
                    self._set_status(
                        f"✓  {edf_name}  │  "
                        f"Peek: {n_bytes // MB} MB  │  "
                        f"Records: {reader.records_available}/{nr_total_str}  │  "
                        f"Peek dur: {reader.peek_duration_str()}  │  "
                        f"Total dur: {reader.duration_str()}  │  "
                        f"Annots: {len(reader.annotations)}"
                    )
                    self._populate_header(reader)
                    self._populate_channels(reader)
                    self._populate_annotations(reader)
                    self._populate_stats(reader)
                    keep_polling = False

                elif kind == "error":
                    _, tb = event
                    self._reset_progress()
                    self._inspect_btn.config(state=tk.NORMAL)
                    self._set_status("Error — see Log tab for details.")
                    self._log("─" * 60)
                    self._log("ERROR:")
                    self._log(tb)
                    # Also show messagebox with a short summary
                    short = tb.strip().splitlines()[-1]
                    messagebox.showerror("Inspection failed", short)
                    keep_polling = False

        except queue.Empty:
            pass    # nothing left in queue right now

        if keep_polling:
            self.after(50, self._poll_queue)   # reschedule

    def _reset_progress(self):
        self._progress["value"] = 0
        self._pct_var.set("")

    # ── Populate all tabs ─────────────────────────────────────────────────────

    def _populate_header(self, r: EDFPeekReader):
        _, txt = self._tab_header
        h = r.header

        def row(label, key, default=""):
            return f"  {label:<26}  {h.get(key, default)}"

        # EDF+ structured fields only if present
        patient_section = [
            row("Patient field",    "patient"),
        ]
        if r.is_edfplus:
            patient_section += [
                row("  Code",            "patient_code"),
                row("  Name",            "patient_name"),
                row("  Sex",             "patient_sex"),
                row("  Birthdate",       "patient_birthdate"),
                row("  Additional",      "patient_additional"),
            ]

        recording_section = [
            row("Recording field",  "recording"),
        ]
        if r.is_edfplus:
            recording_section += [
                row("  Startdate",       "recording_startdate"),
                row("  Admin code",      "recording_admincode"),
                row("  Technician",      "recording_technician"),
                row("  Equipment",       "recording_equipment"),
                row("  Additional",      "recording_additional"),
            ]

        lines = [
            f"  Format                      {r.format_str}",
            "",
            "  ── Patient ──────────────────────────────────────────────────",
            *patient_section,
            "",
            "  ── Recording ────────────────────────────────────────────────",
            *recording_section,
            "",
            "  ── Timing ───────────────────────────────────────────────────",
            row("Start date",        "startdate"),
            row("Start time",        "starttime"),
            f"  {'Record duration':<26}  {h.get('record_duration', '')} s",
            f"  {'Num data records':<26}  {h.get('num_records', '')}",
            f"  {'Total duration':<26}  {r.duration_str()}",
            f"  {'Parsed peek duration':<26}  {r.peek_duration_str()}  "
            f"({r.records_available} records)",
            "",
            "  ── File structure ────────────────────────────────────────────",
            f"  {'Num signals':<26}  {h.get('num_signals', '')}",
            f"  {'Header bytes':<26}  {h.get('header_bytes', '')}",
            row("Reserved",          "reserved"),
        ]
        self._set_text(txt, "\n".join(lines))

    def _populate_channels(self, r: EDFPeekReader):
        _, tree = self._tab_channels
        tree.delete(*tree.get_children())
        for sig in r.signals:
            tag = "annot" if sig["is_annotation"] else "normal"
            tree.insert("", tk.END, values=(
                sig["label"],
                sig["unit"],
                f"{sig['srate']:.2f}",
                f"{sig['phys_min']:.5g}",
                f"{sig['phys_max']:.5g}",
                str(sig["dig_min"]),
                str(sig["dig_max"]),
                sig["prefilter"],
                str(sig["ns_per_rec"]),
            ), tags=(tag,))
        tree.tag_configure("annot",  foreground="#7A9BBB")
        tree.tag_configure("normal", foreground=_LIGHT_TEXT)

    def _populate_annotations(self, r: EDFPeekReader):
        _, txt = self._tab_annots
        if not r.annotations:
            self._set_text(
                txt,
                "  (No annotations found in the peeked data records.\n"
                f"   {r.records_available} records parsed "
                f"[{r.peek_duration_str()} of data].)"
            )
            return

        col_onset = 14
        col_dur   = 12
        header_row = (
            f"  {'Onset (s)':>{col_onset}}  {'Duration':>{col_dur}}  "
            f"Description"
        )
        sep = "  " + "─" * 74
        rows = [header_row, sep]

        for a in r.annotations:
            dur_str = (
                f"{a['duration']:.3f}" if isinstance(a["duration"], float)
                else str(a["duration"])
            )
            rows.append(
                f"  {a['onset']:>{col_onset}.3f}  {dur_str:>{col_dur}}  "
                f"{a['description']}"
            )
        self._set_text(txt, "\n".join(rows))

    def _populate_stats(self, r: EDFPeekReader):
        _, tree = self._tab_stats
        tree.delete(*tree.get_children())

        if not _NUMPY:
            tree.insert("", tk.END, values=(
                "numpy not installed — stats unavailable",
                *[""] * 6
            ))
            return

        def _fmt(v):
            if v is None:
                return "—"
            return f"{v:.4g}"

        for st in r.signal_stats:
            tree.insert("", tk.END, values=(
                st["label"],
                st["unit"],
                str(st["n_samples"]) if st["n_samples"] else "—",
                _fmt(st["mean"]),
                _fmt(st["std"]),
                _fmt(st["min"]),
                _fmt(st["max"]),
            ))

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _sort_tree(tree: ttk.Treeview, col: str):
        """Click-to-sort column header (numeric where possible)."""
        data = [(tree.set(child, col), child) for child in tree.get_children("")]
        try:
            data.sort(key=lambda t: float(t[0].replace("—", "nan")))
        except ValueError:
            data.sort(key=lambda t: t[0].lower())
        for idx, (_, child) in enumerate(data):
            tree.move(child, "", idx)

    def _set_text(self, widget, text: str):
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, text)
        widget.config(state=tk.DISABLED)

    def _log(self, msg: str):
        """Append a timestamped line to the Log tab (main thread only)."""
        import datetime
        _, txt = self._tab_log
        txt.config(state=tk.NORMAL)
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        txt.insert(tk.END, f"[{ts}]  {msg}\n")
        txt.see(tk.END)
        txt.config(state=tk.DISABLED)
        # Also mirror to stdout so running from terminal shows progress
        print(f"[EDF Inspector] {msg}", flush=True)

    def _log_clear(self):
        _, txt = self._tab_log
        txt.config(state=tk.NORMAL)
        txt.delete("1.0", tk.END)
        txt.config(state=tk.DISABLED)

    def _set_status(self, msg: str):
        self._status_var.set(msg)


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
