#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TSV Coverage Mapper
- CLI mode: provide --tsv and optionally --out; exports PNG (main output).
- GUI mode: use the separate StepX_GUI_MiladCommander.py wrapper.
  (This file can still be imported and used programmatically.)

TSV assumption:
- Each row corresponds to one "file"
- Needs start and end timestamp columns (configurable via INI)
- Optional label column for the Y axis (configurable)
"""

from __future__ import annotations

import argparse
import configparser
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple, List

import pandas as pd
import matplotlib

matplotlib.use("Agg")  # headless-safe for CLI
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# -----------------------------
# INI defaults and management
# -----------------------------

DEFAULT_INI_NAME = "tsv_coverage_mapper.ini"


def _coerce_bool(s: str, default: bool = False) -> bool:
    if s is None:
        return default
    s = str(s).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def _ensure_ini(path: str) -> configparser.ConfigParser:
    """
    Create INI if missing; add missing required keys if partially present.
    """
    cfg = configparser.ConfigParser()

    # Default structure
    defaults = {
        "General": {
            "last_folder": "",
            "last_tsv": "",
            "output_dir": "",
        },
        "TSV": {
            # You can set these to either column names or 0-based indices
            # Examples:
            #   start_col = start_time
            #   start_col = 3
            "start_col": "start_time",
            "end_col": "end_time",
            "label_col": "file",  # y-axis label; can be "file", "path", etc.
            "sort_by": "start",   # start | label | none
            "delimiter": "\t",
            "encoding": "utf-8",
            "comment_prefix": "",  # e.g. "#" if your TSV has comment lines
        },
        "Time": {
            # Supported parsing modes:
            #   datetime_format = auto   -> pandas infer
            #   datetime_format = %Y-%m-%d %H:%M:%S
            "datetime_format": "auto",
            # If timestamps are numeric:
            #   unix_unit = s | ms | us | ns
            "unix_unit": "s",
            "timezone": "",  # e.g. "UTC" (kept simple; applied during parse where possible)
        },
        "Plot": {
            "title": "TSV Coverage Map",
            "xlabel": "Time",
            "ylabel": "Files",
            "bar_height": "0.8",
            "dpi": "200",
            "max_rows": "5000",  # safety for extremely large TSVs
            # Auto x-axis unit selection:
            # If total span <= threshold_hours -> show hours; else show days.
            "hour_threshold": "72",
            # If too many rows, optionally truncate:
            "truncate_when_exceeds_max_rows": "true",
        },
        "Extensibility": {
            # Placeholder for future functionality toggles
            "enabled": "true",
        }
    }

    changed = False
    if os.path.exists(path):
        cfg.read(path, encoding="utf-8")
    else:
        changed = True

    # Ensure sections/keys exist
    for section, kv in defaults.items():
        if not cfg.has_section(section):
            cfg.add_section(section)
            changed = True
        for k, v in kv.items():
            if not cfg.has_option(section, k):
                cfg.set(section, k, str(v))
                changed = True

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            cfg.write(f)

    return cfg


def _get_ini_path(next_to: str) -> str:
    base_dir = os.path.dirname(os.path.abspath(next_to))
    return os.path.join(base_dir, DEFAULT_INI_NAME)


def _maybe_set(cfg: configparser.ConfigParser, section: str, key: str, value: str) -> None:
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, key, value)


def _save_cfg(cfg: configparser.ConfigParser, ini_path: str) -> None:
    with open(ini_path, "w", encoding="utf-8") as f:
        cfg.write(f)


# -----------------------------
# Parsing utilities
# -----------------------------

def _as_col_ref(df: pd.DataFrame, col_ref: str) -> str:
    """
    col_ref can be a column name or a 0-based integer index (as string).
    Returns a column name.
    """
    col_ref = str(col_ref).strip()
    if col_ref == "":
        raise ValueError("Empty column reference in INI.")
    # Numeric index?
    if col_ref.isdigit():
        idx = int(col_ref)
        if idx < 0 or idx >= len(df.columns):
            raise ValueError(f"Column index {idx} out of range (0..{len(df.columns) - 1}).")
        return df.columns[idx]
    # Name
    if col_ref not in df.columns:
        raise ValueError(f"Column '{col_ref}' not found. Available columns: {list(df.columns)}")
    return col_ref


def _parse_time_series(
    series: pd.Series,
    datetime_format: str,
    unix_unit: str
) -> pd.Series:
    """
    Parse a time series that can be:
    - datetime strings
    - numeric unix timestamps (seconds, ms, etc.)
    """
    s = series.copy()

    # If already datetime dtype
    if pd.api.types.is_datetime64_any_dtype(s):
        return s

    # Try numeric unix parsing if mostly numeric
    numeric = pd.to_numeric(s, errors="coerce")
    numeric_ratio = numeric.notna().mean() if len(s) else 0.0

    if numeric_ratio >= 0.80:
        # treat as unix timestamps
        out = pd.to_datetime(numeric, unit=unix_unit, errors="coerce", utc=False)
        return out

    # Otherwise, treat as string datetime
    if datetime_format.strip().lower() == "auto":
        out = pd.to_datetime(s, errors="coerce", infer_datetime_format=True, utc=False)
    else:
        out = pd.to_datetime(s, errors="coerce", format=datetime_format, utc=False)
    return out


@dataclass
class CoverageRow:
    label: str
    start: datetime
    end: datetime


def read_coverage_rows(tsv_path: str, ini_path: Optional[str] = None) -> Tuple[List[CoverageRow], configparser.ConfigParser, str]:
    """
    Reads TSV and returns rows with label/start/end.
    Duration is assumed to be in HOURS.
    Returns: (rows, cfg, ini_path_used)
    """
    import pandas as pd
    import numpy as np

    if not os.path.exists(tsv_path):
        raise FileNotFoundError(f"TSV not found: {tsv_path}")

    if ini_path is None:
        ini_path = _get_ini_path(__file__)
    cfg = _ensure_ini(ini_path)

    # ----------------------------
    # Retrieve delimiter, ensure fallback
    # ----------------------------
    delimiter = cfg.get("TSV", "delimiter", fallback="\t").strip()
    if not delimiter:
        delimiter = "\t"
        cfg.set("TSV", "delimiter", delimiter)
        _save_cfg(cfg, ini_path)

    encoding = cfg.get("TSV", "encoding", fallback="utf-8")
    comment_prefix = cfg.get("TSV", "comment_prefix", fallback="").strip()

    read_kwargs = dict(
        sep=delimiter,
        dtype=str,
        keep_default_na=False,
    )
    if comment_prefix:
        read_kwargs["comment"] = comment_prefix

    df = pd.read_csv(tsv_path, **read_kwargs, encoding=encoding)

    if df.empty:
        raise ValueError("TSV has no data rows.")

    # ------------------------------------------------------------
    # Resolve columns according to INI
    # ------------------------------------------------------------
    start_col = _as_col_ref(df, cfg.get("TSV", "start_col", fallback="acq_time"))
    end_col = _as_col_ref(df, cfg.get("TSV", "end_col", fallback="duration"))
    label_col = _as_col_ref(df, cfg.get("TSV", "label_col", fallback="filename"))

    datetime_format = cfg.get("Time", "datetime_format", fallback="auto")
    unix_unit = cfg.get("Time", "unix_unit", fallback="s")

    # ------------------------------------------------------------
    # Parse start timestamp column
    # ------------------------------------------------------------
    start_dt = _parse_time_series(df[start_col], datetime_format, unix_unit)

    if start_dt.isna().any():
        raise ValueError(
            "Failed to parse start times.\n"
            f"Bad rows:\n{df[start_dt.isna()][[start_col]].head()}"
        )

    # ------------------------------------------------------------
    # Parse duration column (IN HOURS)
    # Clean whitespace, BOM, comma decimals
    # ------------------------------------------------------------
    durations_raw = df[end_col].astype(str).str.strip()
    durations_raw = durations_raw.str.replace("\ufeff", "", regex=False)
    durations_raw = durations_raw.str.replace(",", ".", regex=False)

    durations = pd.to_numeric(durations_raw, errors="coerce")

    if durations.isna().any():
        raise ValueError(
            f"Duration column '{end_col}' contains non-numeric values.\n"
            f"Bad rows:\n{df[durations.isna()][[end_col]].head()}"
        )

    # ------------------------------------------------------------
    # Compute end times = start + duration (hours)
    # ------------------------------------------------------------
    end_dt = start_dt + durations.apply(lambda h: pd.Timedelta(hours=float(h)))

    # ------------------------------------------------------------
    # Build CoverageRow list
    # ------------------------------------------------------------
    rows: List[CoverageRow] = []
    for i in range(len(df)):
        label = str(df.iloc[i][label_col]).strip()
        sdt = start_dt.iloc[i]
        edt = end_dt.iloc[i]

        if pd.isna(sdt) or pd.isna(edt):
            raise ValueError(
                f"Timestamp parse failed at row {i}: start={sdt}, end={edt}"
            )

        if edt < sdt:
            raise ValueError(
                f"Row {i}: end < start for label '{label}'. "
                f"start={sdt}, duration_hours={durations.iloc[i]}"
            )

        rows.append(
            CoverageRow(
                label=label if label else f"row_{i}",
                start=sdt.to_pydatetime(),
                end=edt.to_pydatetime(),
            )
        )

    # ------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------
    sort_by = cfg.get("TSV", "sort_by", fallback="start").strip().lower()
    if sort_by == "start":
        rows.sort(key=lambda r: (r.start, r.end, r.label))
    elif sort_by == "label":
        rows.sort(key=lambda r: (r.label, r.start, r.end))
    elif sort_by == "none":
        pass
    else:
        rows.sort(key=lambda r: (r.start, r.end, r.label))

    # ------------------------------------------------------------
    # Update INI
    # ------------------------------------------------------------
    _maybe_set(cfg, "General", "last_tsv", os.path.abspath(tsv_path))
    _maybe_set(cfg, "General", "last_folder", os.path.dirname(os.path.abspath(tsv_path)))
    _save_cfg(cfg, ini_path)

    return rows, cfg, ini_path


# -----------------------------
# Plotting
# -----------------------------

def _choose_time_axis(total_seconds: float, hour_threshold: float) -> str:
    # If span is small, show hours; else days
    if total_seconds <= hour_threshold * 3600.0:
        return "hours"
    return "days"

def _strip_common_prefix(labels: List[str]) -> List[str]:
    """
    Removes the longest common path prefix from all labels.
    Example:
        ses-001/ieeg/sub-076_file1.edf
        ses-002/ieeg/sub-076_file2.edf
    Output:
        sub-076_file1.edf
        sub-076_file2.edf
    """
    if not labels:
        return labels

    # Convert all to normalized paths
    norm = [os.path.normpath(x) for x in labels]

    # Find common prefix as a path
    common = os.path.commonprefix(norm)

    # Ensure we trim only full directory parts
    common = os.path.dirname(common)

    clean = []
    for x in norm:
        if x.startswith(common):
            trimmed = x[len(common):].lstrip(os.sep)
        else:
            trimmed = x
        clean.append(trimmed)
    return clean

def make_gantt_png(
    rows: List[CoverageRow],
    out_png: str,
    cfg: Optional[configparser.ConfigParser] = None,
    title_override: Optional[str] = None
) -> str:
    """
    Creates a gantt-like coverage plot and saves as PNG.
    Returns absolute output path.
    """
    if not rows:
        raise ValueError("No rows to plot.")

    if cfg is None:
        cfg = _ensure_ini(_get_ini_path(__file__))

    max_rows = int(cfg.get("Plot", "max_rows", fallback="5000"))
    truncate = _coerce_bool(cfg.get("Plot", "truncate_when_exceeds_max_rows", fallback="true"), True)
    if len(rows) > max_rows:
        if truncate:
            rows = rows[:max_rows]
        else:
            raise ValueError(
                f"Too many rows to plot ({len(rows)}). "
                f"Increase [Plot] max_rows or enable truncation."
            )

    starts = [r.start for r in rows]
    ends = [r.end for r in rows]
    tmin = min(starts)
    tmax = max(ends)
    total_seconds = (tmax - tmin).total_seconds()

    hour_threshold = float(cfg.get("Plot", "hour_threshold", fallback="72"))
    axis_unit = _choose_time_axis(total_seconds, hour_threshold)

    plot_title = title_override if title_override is not None else cfg.get("Plot", "title", fallback="TSV Coverage Map")
    xlabel = cfg.get("Plot", "xlabel", fallback="Time")
    ylabel = cfg.get("Plot", "ylabel", fallback="Files")
    bar_height = float(cfg.get("Plot", "bar_height", fallback="0.8"))
    dpi = int(cfg.get("Plot", "dpi", fallback="200"))

    # Figure sizing heuristic: more rows -> taller
    n = len(rows)
    fig_w = 14
    fig_h = max(4, min(0.25 * n + 2.5, 40))  # cap height
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    # Y positions
    y_positions = list(range(n))
    labels = _strip_common_prefix([r.label for r in rows])
    labels = [label.replace(f"\\ieeg\\",f"\\").replace(f".edf",f"") for label in labels]

    # Convert datetime to matplotlib date numbers
    start_nums = mdates.date2num(starts)
    end_nums = mdates.date2num(ends)
    widths = end_nums - start_nums  # in days

    ax.barh(
        y_positions,
        widths,
        left=start_nums,
        height=bar_height,
        align="center",
    )

    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels, fontsize=8)

    ax.set_title(plot_title)
    ax.set_xlabel(f"{xlabel} ({axis_unit})" if axis_unit else xlabel)
    ax.set_ylabel(ylabel)

    # Format x-axis depending on span
    if axis_unit == "hours":
        locator = mdates.AutoDateLocator(minticks=6, maxticks=12)
        formatter = mdates.ConciseDateFormatter(locator)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)
    else:
        locator = mdates.AutoDateLocator(minticks=6, maxticks=40)
        formatter = mdates.ConciseDateFormatter(locator)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)

    ax.grid(True, axis="x", linestyle="--", linewidth=0.5)
    ax.grid(True, axis="y", linestyle="--", linewidth=0.5)
    ax.set_ylim(-1, n)

    fig.tight_layout()

    out_png_abs = os.path.abspath(out_png)
    os.makedirs(os.path.dirname(out_png_abs) or ".", exist_ok=True)
    fig.savefig(out_png_abs, dpi=dpi)
    plt.close(fig)

    return out_png_abs


# -----------------------------
# CLI
# -----------------------------

def _default_out_path(tsv_path: str, cfg: configparser.ConfigParser) -> str:
    base = os.path.splitext(os.path.basename(tsv_path))[0]
    out_dir = cfg.get("General", "output_dir", fallback="").strip()
    if not out_dir:
        out_dir = os.path.dirname(os.path.abspath(tsv_path))
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"{base}_coverage.png")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a gantt-like coverage PNG from a TSV file (one row per file; start/end columns configurable via INI)."
    )
    parser.add_argument("--tsv", type=str, default="", help="Path to TSV file.")
    parser.add_argument(
        "--out",
        type=str,
        default="",
        help="Output PNG path. If omitted, uses TSV name + '_coverage.png'.",
    )
    parser.add_argument(
        "--ini",
        type=str,
        default="",
        help="Path to INI file. If omitted, uses INI next to this script.",
    )
    parser.add_argument("--title", type=str, default="", help="Override plot title.")
    args = parser.parse_args(argv)

    # If no args provided at all, do not launch a GUI from here.
    # Just print help and exit with a non-error code.
    if not (args.tsv or args.out or args.ini or args.title):
        parser.print_help()
        print("\nTip: run the GUI wrapper: python StepX_GUI_MiladCommander.py")
        return 0

    if not args.tsv:
        print("ERROR: --tsv is required in CLI mode.\n", file=sys.stderr)
        parser.print_help()
        return 2

    ini_path = args.ini.strip() or _get_ini_path(__file__)
    try:
        rows, cfg, ini_used = read_coverage_rows(args.tsv, ini_path=ini_path)
        out_png = args.out.strip() or _default_out_path(args.tsv, cfg)
        title_override = args.title.strip() if args.title.strip() else None
        out_abs = make_gantt_png(rows, out_png, cfg=cfg, title_override=title_override)
        print(f"OK: wrote PNG -> {out_abs}")
        print(f"INI: {os.path.abspath(ini_used)}")
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
