#!/usr/bin/env python3
"""
Natus ENT → BIDS events.tsv completer (GUI)

Fixes truncated strings in events.tsv column: "event" by using complete strings found
in a Natus .ent file inside a selected session folder.

Key improvement vs time-of-day matching:
- Groups rows by the *exact truncated prefix string* and maps to ENT candidates in order.
- This is robust when many other events repeat (e.g., De-block start/end) and make absolute
  time-of-day matching ambiguous.

Output:
- Writes next to input TSV:
    *_events_completed.tsv

Requires:
- Python 3.x standard library only
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import os
import re
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------
# ENT parsing
# -----------------------------

def excel_serial_to_datetime(serial: float) -> _dt.datetime:
    """Convert OLE Automation / Excel serial date to datetime (base 1899-12-30)."""
    base = _dt.datetime(1899, 12, 30)
    return base + _dt.timedelta(days=float(serial))


def normalize_text(s: Any) -> str:
    """
    Normalize to make matching robust:
    - normalize newlines
    - decode ENT-style literal newline markers if present
    """
    if s is None:
        return ""
    s = str(s)

    # literal escape markers sometimes appear in ENT exports
    s = s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    s = s.replace("\\x0d", "\n").replace("\\x0a", "\n").replace("\\xd", "\n")

    # actual newlines normalization
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return s


@dataclass
class EntEvent:
    serial: float                 # CreationTime (Excel serial)
    stamp: int                    # Stamp (integer)
    dt: _dt.datetime              # datetime from CreationTime
    text: str                     # decoded Text
    text_norm: str                # normalized Text


def extract_ent_events(ent_file: str) -> List[EntEvent]:
    """
    Extract (CreationTime, Stamp, Text) from a .ent file using regex over bytes.

    Pattern:
      (."CreationTime", <float>) ... (."Stamp", <int>) ... (."Text", "<string>")
    """
    with open(ent_file, "rb") as f:
        data = f.read()

    pattern = re.compile(
        br'\(\.\s*"CreationTime",\s*([0-9]+\.[0-9]+)\s*\).*?'
        br'\(\.\s*"Stamp",\s*([0-9]+)\s*\).*?'
        br'\(\.\s*"Text",\s*"([^"]*)"',
        re.DOTALL,
    )

    out: List[EntEvent] = []
    for m in pattern.finditer(data):
        try:
            serial = float(m.group(1).decode("ascii", errors="ignore"))
            stamp = int(m.group(2).decode("ascii", errors="ignore"))
        except ValueError:
            continue

        txt = m.group(3).decode("latin-1", errors="replace")
        # common literal markers
        txt = txt.replace("\\xd\n", "\n").replace("\\xd", "\n")

        dt = excel_serial_to_datetime(serial)
        out.append(
            EntEvent(
                serial=serial,
                stamp=stamp,
                dt=dt,
                text=txt,
                text_norm=normalize_text(txt),
            )
        )

    # sort by CreationTime (chronological)
    out.sort(key=lambda e: e.serial)
    return out


def choose_best_ent_file(folder: str) -> Optional[str]:
    """
    Pick the "best" .ent file in a folder tree:
    - largest size
    - tie-breaker: newest modification time
    """
    best_path: Optional[str] = None
    best_key: Optional[Tuple[int, float]] = None

    for root, _, files in os.walk(folder):
        for fn in files:
            if fn.lower().endswith(".ent"):
                p = os.path.join(root, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                key = (int(st.st_size), float(st.st_mtime))
                if best_key is None or key > best_key:
                    best_key = key
                    best_path = p

    return best_path


def estimate_fs_from_ent(ent_events: List[EntEvent]) -> Optional[float]:
    """
    Roughly estimate sampling rate from ENT by comparing Stamp differences vs CreationTime differences.
    This is only used for relative timing comparisons; if it can't be estimated, we fall back to CreationTime.

    Returns fs (Hz) or None.
    """
    ratios: List[float] = []
    prev: Optional[EntEvent] = None

    for e in ent_events:
        if prev is None:
            prev = e
            continue
        ds = e.stamp - prev.stamp
        dt_sec = (e.serial - prev.serial) * 86400.0

        # avoid tiny dt (timer jitter) and weird jumps
        if ds > 0 and 0.5 <= dt_sec <= 60.0:
            ratios.append(ds / dt_sec)

        prev = e

    if len(ratios) < 30:
        return None

    ratios.sort()
    mid = len(ratios) // 2
    fs = ratios[mid] if (len(ratios) % 2 == 1) else (ratios[mid - 1] + ratios[mid]) / 2.0
    return float(fs)


# -----------------------------
# TSV I/O
# -----------------------------

def read_tsv_rows(tsv_path: str) -> Tuple[List[str], List[Dict[str, str]]]:
    with open(tsv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    return fieldnames, rows


def write_tsv_rows(tsv_path: str, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    with open(tsv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            delimiter="\t",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        writer.writerows(rows)


def safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(str(x).strip())
    except Exception:
        return None


# -----------------------------
# Completion logic (robust grouping)
# -----------------------------

def complete_events(
    events_tsv: str,
    natus_folder: str,
) -> Tuple[str, Dict[str, Any]]:
    """
    Complete truncated events.

    Strategy:
    1) Load ENT events (CreationTime, Stamp, Text), build candidate lookup.
    2) For each unique TSV event string, check if it's a prefix of any ENT text (and shorter).
    3) Group TSV rows by that truncated string.
    4) For each group:
        - collect ENT candidates whose text startswith that truncated string and is longer
        - if counts match: map in order (TSV by onset, ENT by CreationTime)
        - if ENT has extras: choose the best consecutive slice by matching relative timing
          (using stamp->seconds if fs estimated; else CreationTime->seconds)
        - write replacements
    """
    ent_file = choose_best_ent_file(natus_folder)
    if not ent_file:
        raise RuntimeError(f"No .ent file found under folder:\n{natus_folder}")

    ent_events = extract_ent_events(ent_file)
    if not ent_events:
        raise RuntimeError(f"Could not extract events from:\n{ent_file}")

    fs_est = estimate_fs_from_ent(ent_events)

    fieldnames, rows = read_tsv_rows(events_tsv)
    if "event" not in fieldnames:
        raise RuntimeError(f'Required column "event" not found. Columns: {fieldnames}')
    if "onset" not in fieldnames:
        raise RuntimeError(f'Required column "onset" not found. Columns: {fieldnames}')

    # Build ENT texts list for prefix checks
    ent_texts_norm = [e.text_norm for e in ent_events]

    # Determine which TSV unique event strings are "truncated" (prefix of an ENT text)
    unique_tsv_events: List[str] = sorted({normalize_text(r.get("event", "")) for r in rows})
    trunc_to_ent_candidates: Dict[str, List[EntEvent]] = {}

    for tev in unique_tsv_events:
        if not tev:
            continue
        cands = [e for e in ent_events if e.text_norm.startswith(tev) and len(e.text_norm) > len(tev)]
        if cands:
            trunc_to_ent_candidates[tev] = cands

    # Group TSV row indices by truncated event string
    groups: Dict[str, List[int]] = {}
    for i, r in enumerate(rows):
        tev = normalize_text(r.get("event", ""))
        if tev in trunc_to_ent_candidates:
            groups.setdefault(tev, []).append(i)

    fixed_preview: List[Dict[str, Any]] = []
    unmatched_preview: List[Dict[str, Any]] = []

    rows_fixed = 0
    rows_unmatched = 0
    groups_total = len(groups)
    groups_fully_fixed = 0
    groups_unmatched = 0

    # Helper for ENT time axis for relative timing
    def ent_seconds(e: EntEvent) -> float:
        if fs_est and fs_est > 1e-9:
            return float(e.stamp) / float(fs_est)
        return float(e.serial) * 86400.0

    # Process each group
    for trunc_str, idxs in groups.items():
        cands = trunc_to_ent_candidates[trunc_str]
        n = len(idxs)

        # Sort TSV indices by onset (chronological within TSV)
        idxs_sorted = sorted(
            idxs,
            key=lambda ii: (safe_float(rows[ii].get("onset")) is None, safe_float(rows[ii].get("onset")) or 0.0),
        )

        # Sort candidates in ENT chronological order (already sorted globally; keep stable order)
        cands_sorted = sorted(cands, key=lambda e: e.serial)

        if len(cands_sorted) < n:
            groups_unmatched += 1
            for ii in idxs_sorted:
                rows_unmatched += 1
                unmatched_preview.append(
                    {
                        "row_index": ii + 1,
                        "onset": rows[ii].get("onset", ""),
                        "time_abs": rows[ii].get("time_abs", ""),
                        "event": rows[ii].get("event", ""),
                        "reason": f"ENT has only {len(cands_sorted)} candidates for this prefix, TSV needs {n}.",
                    }
                )
            continue

        # If equal counts, map 1-to-1 in order
        chosen_slice: List[EntEvent]
        method_used = "group_order"

        if len(cands_sorted) == n:
            chosen_slice = cands_sorted
        else:
            # ENT has extras: pick best consecutive slice of length n by matching relative timing pattern
            # Compare TSV onset deltas vs ENT deltas (stamp->seconds if fs_est else CreationTime seconds)
            tsv_onsets: List[float] = []
            for ii in idxs_sorted:
                o = safe_float(rows[ii].get("onset"))
                if o is None:
                    o = 0.0
                tsv_onsets.append(o)

            best: Optional[Tuple[float, int]] = None  # (score, start_index)
            for start in range(0, len(cands_sorted) - n + 1):
                sl = cands_sorted[start : start + n]
                ent0 = ent_seconds(sl[0])
                tsv0 = tsv_onsets[0]

                # relative deltas must align (offset cancels)
                score = 0.0
                for k in range(n):
                    tsv_d = tsv_onsets[k] - tsv0
                    ent_d = ent_seconds(sl[k]) - ent0
                    d = tsv_d - ent_d
                    score += d * d
                cand_score = (score, start)
                if best is None or cand_score < best:
                    best = cand_score

            chosen_slice = cands_sorted[best[1] : best[1] + n]
            method_used = "group_best_slice"

        # Apply replacements
        group_fixed_here = 0
        for ii, ent_ev in zip(idxs_sorted, chosen_slice):
            old = rows[ii].get("event", "")
            new = ent_ev.text
            if old != new:
                rows[ii]["event"] = new
                rows_fixed += 1
                group_fixed_here += 1

                if len(fixed_preview) < 800:
                    fixed_preview.append(
                        {
                            "row_index": ii + 1,
                            "onset": rows[ii].get("onset", ""),
                            "time_abs": rows[ii].get("time_abs", ""),
                            "old_event": old,
                            "new_event": new,
                            "method": method_used,
                        }
                    )

        if group_fixed_here == n:
            groups_fully_fixed += 1
        else:
            # Some rows might already have been identical (rare, but track anyway)
            pass

    # Output path next to input
    in_name = os.path.basename(events_tsv)
    if in_name.endswith("_events.tsv"):
        out_name = in_name[: -len("_events.tsv")] + "_events_completed.tsv"
    elif in_name.lower().endswith(".tsv"):
        out_name = in_name[:-4] + "_events_completed.tsv"
    else:
        out_name = in_name + "_events_completed.tsv"

    out_path = os.path.join(os.path.dirname(events_tsv), out_name)
    write_tsv_rows(out_path, fieldnames, rows)

    summary = {
        "input_tsv": events_tsv,
        "output_tsv": out_path,
        "natus_folder": natus_folder,
        "ent_file": ent_file,
        "ent_events_extracted": len(ent_events),
        "fs_est_hz": fs_est,
        "rows_total": len(rows),
        "rows_with_completion_candidates": sum(len(v) for v in groups.values()),
        "rows_fixed": rows_fixed,
        "rows_unmatched": rows_unmatched,
        "groups_total": groups_total,
        "groups_fully_fixed": groups_fully_fixed,
        "groups_unmatched": groups_unmatched,
        "fixed_preview": fixed_preview,
        "unmatched_preview": unmatched_preview,
    }
    return out_path, summary


# -----------------------------
# GUI
# -----------------------------

def launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title("Natus ENT → events.tsv Completer (Robust)")
            self.geometry("1250x720")
            self.minsize(1050, 600)

            self.events_path = tk.StringVar(value="")
            self.natus_folder = tk.StringVar(value="")
            self.ent_path = tk.StringVar(value="(not selected)")
            self.status = tk.StringVar(value="Select an events.tsv and a Natus session folder.")

            self._build_ui()

        def _build_ui(self) -> None:
            outer = ttk.Frame(self, padding=10)
            outer.pack(fill="both", expand=True)

            sel = ttk.LabelFrame(outer, text="Inputs", padding=10)
            sel.pack(fill="x")

            ttk.Label(sel, text="events.tsv (column 'event' has truncated prefixes):").grid(row=0, column=0, sticky="w")
            ttk.Entry(sel, textvariable=self.events_path).grid(row=0, column=1, sticky="ew", padx=8)
            ttk.Button(sel, text="Browse…", command=self._browse_events).grid(row=0, column=2, sticky="ew")

            ttk.Label(sel, text="Natus session folder (contains .ent):").grid(row=1, column=0, sticky="w", pady=(8, 0))
            ttk.Entry(sel, textvariable=self.natus_folder).grid(row=1, column=1, sticky="ew", padx=8, pady=(8, 0))
            ttk.Button(sel, text="Browse…", command=self._browse_folder).grid(row=1, column=2, sticky="ew", pady=(8, 0))

            ttk.Label(sel, text="Auto-selected .ent:").grid(row=2, column=0, sticky="w", pady=(8, 0))
            ttk.Label(sel, textvariable=self.ent_path).grid(row=2, column=1, columnspan=2, sticky="w", pady=(8, 0))

            sel.columnconfigure(1, weight=1)

            runbar = ttk.Frame(outer)
            runbar.pack(fill="x", pady=(10, 0))
            ttk.Button(runbar, text="Run Completion", command=self._run).pack(side="left")
            ttk.Label(runbar, textvariable=self.status).pack(side="left", padx=12)

            nb = ttk.Notebook(outer)
            nb.pack(fill="both", expand=True, pady=(10, 0))

            self.tab_fixed = ttk.Frame(nb)
            self.tab_unmatched = ttk.Frame(nb)
            self.tab_log = ttk.Frame(nb)

            nb.add(self.tab_fixed, text="Fixed Preview")
            nb.add(self.tab_unmatched, text="Unmatched")
            nb.add(self.tab_log, text="Log")

            self._build_fixed_tab()
            self._build_unmatched_tab()
            self._build_log_tab()

        def _build_fixed_tab(self) -> None:
            cols = ("row", "onset", "time_abs", "method", "old_event", "new_event")
            self.fixed_tree = ttk.Treeview(self.tab_fixed, columns=cols, show="headings")
            for c, t in [
                ("row", "Row"),
                ("onset", "onset"),
                ("time_abs", "time_abs"),
                ("method", "Method"),
                ("old_event", "Old event"),
                ("new_event", "New event"),
            ]:
                self.fixed_tree.heading(c, text=t)

            self.fixed_tree.column("row", width=70, anchor="e")
            self.fixed_tree.column("onset", width=110, anchor="e")
            self.fixed_tree.column("time_abs", width=150, anchor="w")
            self.fixed_tree.column("method", width=140, anchor="w")
            self.fixed_tree.column("old_event", width=390, anchor="w")
            self.fixed_tree.column("new_event", width=390, anchor="w")

            ysb = ttk.Scrollbar(self.tab_fixed, orient="vertical", command=self.fixed_tree.yview)
            xsb = ttk.Scrollbar(self.tab_fixed, orient="horizontal", command=self.fixed_tree.xview)
            self.fixed_tree.configure(yscroll=ysb.set, xscroll=xsb.set)

            self.tab_fixed.rowconfigure(0, weight=1)
            self.tab_fixed.columnconfigure(0, weight=1)

            self.fixed_tree.grid(row=0, column=0, sticky="nsew")
            ysb.grid(row=0, column=1, sticky="ns")
            xsb.grid(row=1, column=0, sticky="ew")

        def _build_unmatched_tab(self) -> None:
            cols = ("row", "onset", "time_abs", "event", "reason")
            self.unmatched_tree = ttk.Treeview(self.tab_unmatched, columns=cols, show="headings")
            for c, t in [
                ("row", "Row"),
                ("onset", "onset"),
                ("time_abs", "time_abs"),
                ("event", "Event (unchanged)"),
                ("reason", "Reason"),
            ]:
                self.unmatched_tree.heading(c, text=t)

            self.unmatched_tree.column("row", width=70, anchor="e")
            self.unmatched_tree.column("onset", width=110, anchor="e")
            self.unmatched_tree.column("time_abs", width=150, anchor="w")
            self.unmatched_tree.column("event", width=520, anchor="w")
            self.unmatched_tree.column("reason", width=360, anchor="w")

            ysb = ttk.Scrollbar(self.tab_unmatched, orient="vertical", command=self.unmatched_tree.yview)
            xsb = ttk.Scrollbar(self.tab_unmatched, orient="horizontal", command=self.unmatched_tree.xview)
            self.unmatched_tree.configure(yscroll=ysb.set, xscroll=xsb.set)

            self.tab_unmatched.rowconfigure(0, weight=1)
            self.tab_unmatched.columnconfigure(0, weight=1)

            self.unmatched_tree.grid(row=0, column=0, sticky="nsew")
            ysb.grid(row=0, column=1, sticky="ns")
            xsb.grid(row=1, column=0, sticky="ew")

        def _build_log_tab(self) -> None:
            import tkinter as tk
            self.log_txt = tk.Text(self.tab_log, wrap="none")
            ysb = ttk.Scrollbar(self.tab_log, orient="vertical", command=self.log_txt.yview)
            xsb = ttk.Scrollbar(self.tab_log, orient="horizontal", command=self.log_txt.xview)
            self.log_txt.configure(yscroll=ysb.set, xscroll=xsb.set)

            self.tab_log.rowconfigure(0, weight=1)
            self.tab_log.columnconfigure(0, weight=1)

            self.log_txt.grid(row=0, column=0, sticky="nsew")
            ysb.grid(row=0, column=1, sticky="ns")
            xsb.grid(row=1, column=0, sticky="ew")

        def _append_log(self, msg: str) -> None:
            self.log_txt.insert("end", msg + "\n")
            self.log_txt.see("end")

        def _clear_tree(self, tree) -> None:
            for item in tree.get_children():
                tree.delete(item)

        def _browse_events(self) -> None:
            p = filedialog.askopenfilename(
                title="Select events.tsv",
                filetypes=[("TSV files", "*.tsv"), ("All files", "*.*")],
            )
            if not p:
                return
            self.events_path.set(p)
            self.status.set("Select a Natus folder, then click Run Completion.")

        def _browse_folder(self) -> None:
            p = filedialog.askdirectory(title="Select Natus session folder")
            if not p:
                return
            self.natus_folder.set(p)
            ent = choose_best_ent_file(p)
            if not ent:
                self.ent_path.set("(no .ent found)")
                messagebox.showerror("No .ent found", f"No .ent file was found under:\n{p}")
                return
            self.ent_path.set(ent)
            self.status.set("Ready. Click Run Completion.")

        def _run(self) -> None:
            events = self.events_path.get().strip()
            folder = self.natus_folder.get().strip()

            if not events or not os.path.isfile(events):
                messagebox.showerror("Missing file", "Please select a valid events.tsv file.")
                return
            if not folder or not os.path.isdir(folder):
                messagebox.showerror("Missing folder", "Please select a valid Natus session folder.")
                return

            self.status.set("Running…")
            self.update_idletasks()

            self._clear_tree(self.fixed_tree)
            self._clear_tree(self.unmatched_tree)
            self.log_txt.delete("1.0", "end")

            try:
                out_path, summary = complete_events(events, folder)

                self._append_log("=== Run Summary ===")
                self._append_log(f"Input TSV:    {summary['input_tsv']}")
                self._append_log(f"Natus folder: {summary['natus_folder']}")
                self._append_log(f"ENT used:     {summary['ent_file']}")
                self._append_log(f"Output TSV:   {summary['output_tsv']}")
                self._append_log("")
                self._append_log(f"ENT events extracted:              {summary['ent_events_extracted']}")
                self._append_log(f"Rows total:                        {summary['rows_total']}")
                self._append_log(f"Rows w/ completion candidates:     {summary['rows_with_completion_candidates']}")
                self._append_log(f"Rows fixed:                        {summary['rows_fixed']}")
                self._append_log(f"Rows unmatched (had candidates):   {summary['rows_unmatched']}")
                self._append_log("")
                self._append_log(f"Groups total:                      {summary['groups_total']}")
                self._append_log(f"Groups fully fixed:                {summary['groups_fully_fixed']}")
                self._append_log(f"Groups unmatched:                  {summary['groups_unmatched']}")
                self._append_log("")
                if summary["fs_est_hz"] is not None:
                    self._append_log(f"Estimated fs from ENT (rough):     {summary['fs_est_hz']:.3f} Hz")
                else:
                    self._append_log("Estimated fs from ENT (rough):     (not enough stable samples)")
                self._append_log("")

                # Populate fixed preview
                for item in summary["fixed_preview"][:600]:
                    self.fixed_tree.insert(
                        "",
                        "end",
                        values=(
                            item["row_index"],
                            item["onset"],
                            item["time_abs"],
                            item["method"],
                            item["old_event"],
                            item["new_event"],
                        ),
                    )

                # Populate unmatched preview
                for item in summary["unmatched_preview"][:600]:
                    self.unmatched_tree.insert(
                        "",
                        "end",
                        values=(
                            item["row_index"],
                            item["onset"],
                            item["time_abs"],
                            item["event"],
                            item["reason"],
                        ),
                    )

                self.status.set(f"Done. Wrote: {os.path.basename(out_path)}")
                messagebox.showinfo(
                    "Completed",
                    f"Finished!\n\nOutput written next to input TSV:\n{out_path}\n\n"
                    f"Fixed: {summary['rows_fixed']}\nUnmatched: {summary['rows_unmatched']}",
                )

            except Exception as e:
                self.status.set("Error.")
                self._append_log("ERROR:")
                self._append_log(str(e))
                self._append_log("")
                self._append_log(traceback.format_exc())
                messagebox.showerror("Error", f"{e}")

    App().mainloop()


# -----------------------------
# CLI entry
# -----------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Complete truncated BIDS events.tsv 'event' strings using a Natus .ent file (GUI or CLI)."
    )
    parser.add_argument("--events", help="Path to input *_events.tsv", default=None)
    parser.add_argument("--natus-folder", help="Path to Natus session folder containing .ent", default=None)

    args = parser.parse_args()

    if args.events and args.natus_folder:
        out_path, summary = complete_events(args.events, args.natus_folder)
        print("=== Run Summary ===")
        print(f"Input TSV:    {summary['input_tsv']}")
        print(f"Natus folder: {summary['natus_folder']}")
        print(f"ENT used:     {summary['ent_file']}")
        print(f"Output TSV:   {summary['output_tsv']}")
        print("")
        print(f"ENT events extracted:              {summary['ent_events_extracted']}")
        print(f"Rows total:                        {summary['rows_total']}")
        print(f"Rows w/ completion candidates:     {summary['rows_with_completion_candidates']}")
        print(f"Rows fixed:                        {summary['rows_fixed']}")
        print(f"Rows unmatched (had candidates):   {summary['rows_unmatched']}")
        print("")
        print(f"Groups total:                      {summary['groups_total']}")
        print(f"Groups fully fixed:                {summary['groups_fully_fixed']}")
        print(f"Groups unmatched:                  {summary['groups_unmatched']}")
        print("")
        if summary["fs_est_hz"] is not None:
            print(f"Estimated fs from ENT (rough):     {summary['fs_est_hz']:.3f} Hz")
        else:
            print("Estimated fs from ENT (rough):     (not enough stable samples)")
        print("")
        print(f"Done. Output: {out_path}")
        return

    # No CLI args → GUI
    launch_gui()


if __name__ == "__main__":
    main()