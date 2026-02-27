from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class DemographicsRow:
    participant_id: str
    age: Optional[int]
    sex: str
    group: str


def _normalize_sex(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    s_low = s.lower()

    if s_low in ("m", "male", "man", "1"):
        return "m"
    if s_low in ("f", "female", "woman", "0"):
        return "f"

    # keep normalized string for unknown cases
    return s_low


def _normalize_participant_id(pid: str) -> str:
    return (pid or "").strip()


def _resolve_column(df: pd.DataFrame, requested: str) -> str:
    """
    Resolve a column name in a case/whitespace-insensitive way.
    """
    req = (requested or "").strip()
    if not req:
        raise ValueError("Requested column name is blank.")

    if req in df.columns:
        return req

    # case/whitespace-insensitive lookup
    req_key = req.casefold()
    for c in df.columns:
        if str(c).strip().casefold() == req_key:
            return c

    raise ValueError(f"Excel is missing required column '{req}'. Available columns: {list(df.columns)}")


def read_demographics_excel(
    excel_path: str,
    sheet_name: str,
    col_participant_id: str,
    col_age: str,
    col_sex: str,
    col_group: str | None,
    default_group: str,
) -> pd.DataFrame:
    """
    Returns a DataFrame with columns:
      participant_id, age, sex, group
    """
    if not excel_path or not os.path.isfile(excel_path):
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    sn = sheet_name.strip() if sheet_name else 0
    df = pd.read_excel(excel_path, sheet_name=sn, engine=None)

    pid_col = _resolve_column(df, col_participant_id)
    age_col = _resolve_column(df, col_age)
    sex_col = _resolve_column(df, col_sex)

    out = pd.DataFrame()
    out["participant_id"] = df[pid_col].astype(str).map(_normalize_participant_id)

    def parse_age(x):
        if pd.isna(x):
            return None
        try:
            return int(float(str(x).strip()))
        except Exception:
            return None

    out["age"] = df[age_col].map(parse_age)
    out["sex"] = df[sex_col].map(_normalize_sex)

    # Optional group column
    group_col = (col_group or "").strip()
    if group_col:
        try:
            resolved_group_col = _resolve_column(df, group_col)
            out["group"] = df[resolved_group_col].astype(str).map(lambda x: str(x).strip())
        except Exception:
            # If user typed a group col but it's not found, fall back to default group
            out["group"] = (default_group.strip() if default_group else "patient")
    else:
        out["group"] = (default_group.strip() if default_group else "patient")

    out["group"] = out["group"].map(lambda x: x if str(x).strip() else (default_group.strip() if default_group else "patient"))

    # Drop empty participant ids
    out = out[out["participant_id"].map(lambda x: bool(str(x).strip()))].copy()

    return out
