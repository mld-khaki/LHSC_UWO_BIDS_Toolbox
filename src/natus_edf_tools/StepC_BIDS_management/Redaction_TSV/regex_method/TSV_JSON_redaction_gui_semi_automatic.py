#!/usr/bin/env python3
# edf_redactor_gui.py
# GUI wrapper + refactor of TSV/JSON redaction & anonymization tool
# Author: Dr. Milad Khaki (GUI version prepared by ChatGPT)
# Date: 2025-08-22
# License: MIT

import os
import sys
import json
import csv
import re
import time
import shutil
import threading
import queue
import traceback
import configparser
from functools import lru_cache

# Soft imports with helpful message
try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import ahocorasick
except ImportError:
    ahocorasick = None

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------------------------
# Defaults & Settings
# ---------------------------

APP_TITLE = "EDF TSV/JSON Redaction Tool (GUI)"
INI_PATH_DEFAULT = os.path.join(os.path.expanduser("~"), ".edf_redactor_gui.ini")

# Allow separators like space, underscore, dot, comma, pipe, semicolon, dash
SEP_CLASS = r"[ \t_\.,\|;\-]+"
END_BOUND = r"(?=$|[\s\.,;\|\-\]\)\}])"
START_BOUND = r"(?:(?<=^)|(?<=[\s:\(\[\{]))"

# Cache of "accept all" decisions for the exact matched text (lowercased result -> replacement string)
APPROVED_ACCEPT_ALL = {}  # key = matched_token.lower(), value = replacement used (".X." or ".x.")

# Default acceptable-words (ignore list) — editable in GUI:
DEFAULT_IGNORE_LIST = [
    "obscur","please","clean","leans","polyspik","adjustin","against","covering","fluttering",
    "leaving","technician","LIAN+","max 2","max 3","max 4","max 5","max 6","max 7","max 8",
    "max 9","max 0","max L","Max L","clear","polys","piano","todd's","todds","quivering",
    "ering","POLYSPIK","against","leaves","Todds","Todd's","sparkling","Clear","unpleasant",
    "leading","PLEASE","variant"," IAn","maximum","Maximum","MAXIMUM"," max ","LIAn","automatic",
    "automatically","auto"
]

# ---------------------------
# Core redaction logic
# ---------------------------

_IGNORE_RE = None  # compiled at runtime from GUI dictionary


def _compile_ignore_pattern(ignore_list):
    if not ignore_list:
        return None
    return re.compile(r'\b(?:' + '|'.join(map(re.escape, ignore_list)) + r')\b', re.IGNORECASE)


def _strip_ignored(text: str) -> str:
    if not _IGNORE_RE:
        return text
    return _IGNORE_RE.sub(" ", text)


@lru_cache(maxsize=4096)
def compiled_name_pattern(raw_name: str):
    """
    Build a robust regex that matches:
      - First Last  (with flexible separators, optional middle initial)
      - Last, First
      - Last, F or Last, F.
      - When given Last, F it will also match Last, FirstName (expanding the initial)
    """
    name = raw_name.strip()

    # Heuristics to detect "Last, First*" pattern (comma form)
    m_comma = re.match(r"^\s*([A-Za-z'`\-]+)\s*,\s*([A-Za-z])(?:\.|\b)?\s*$", name)
    if m_comma:
        last = re.escape(m_comma.group(1))
        first_initial = re.escape(m_comma.group(2))
        pat = START_BOUND + rf"{last}\s*,\s*{first_initial}[A-Za-z]*\.?" + END_BOUND
        return re.compile(pat, re.IGNORECASE)

    # Full comma form "Last, FirstName"
    m_comma_full = re.match(r"^\s*([A-Za-z'`\-]+)\s*,\s*([A-Za-z]+)\s*$", name)
    if m_comma_full:
        last = re.escape(m_comma_full.group(1))
        first = re.escape(m_comma_full.group(2))
        pat = START_BOUND + rf"{last}\s*,\s*{first[0]}[A-Za-z]*\.?" + END_BOUND
        return re.compile(pat, re.IGNORECASE)

    # "First Last" (with optional middle initial)
    m_space = re.match(r"^\s*([A-Za-z]+)\s+([A-Za-z'`\-]+)\s*$", name)
    if m_space:
        first = re.escape(m_space.group(1))
        last = re.escape(m_space.group(2))
        pat = START_BOUND + rf"{first}(?:{SEP_CLASS}[A-Za-z]\.?)?{SEP_CLASS}{last}" + END_BOUND
        return re.compile(pat, re.IGNORECASE)

    # Fallback: escape raw string but normalize separators
    sepified = re.sub(r"[ \t_\.,\|;\-]+", SEP_CLASS, re.escape(name))
    pat = START_BOUND + sepified + END_BOUND
    return re.compile(pat, re.IGNORECASE)


def replace_with_case_preserved(token: str) -> str:
    return ".X." if (len(token) and token[0].isupper()) else ".x."


def build_automaton(names):
    """Build an Aho–Corasick automaton for fast string matching (lowercased)."""
    A = ahocorasick.Automaton()
    for name in names:
        nm = (name or "").strip()
        if not nm:
            continue
        A.add_word(nm.lower(), nm)
    A.make_automaton()
    return A


def find_matches(text, automaton):
    """Find unique name candidates in text; prefer longer, non-overlapping spans."""
    all_matches = []
    s = text.lower()
    for end, original in automaton.iter(s):
        start = end - len(original) + 1
        all_matches.append((start, end, original))

    # Sort by start asc, end desc (longer first at same start)
    all_matches.sort(key=lambda x: (x[0], -x[1]))

    filtered = []
    if all_matches:
        cur = all_matches[0]
        filtered.append(cur)
        for m in all_matches[1:]:
            if m[0] > cur[1]:
                cur = m
                filtered.append(cur)
            elif m[0] == cur[0] and m[1] > cur[1]:
                filtered[-1] = m
                cur = m
    # Return the raw strings (original forms that were added to the automaton)
    return [m[2] for m in filtered]


def load_names_from_csv(csv_path):
    """Load names from a CSV file and generate variations."""
    df = pd.read_csv(csv_path, usecols=["lastname", "firstname"], dtype=str)
    df.dropna(subset=["lastname", "firstname"], inplace=True)

    last_names = set(df["lastname"].str.strip().tolist())
    first_names = set(df["firstname"].str.strip().tolist())

    full_variants = set()
    reverse_full_variants = set()

    seps = ["", "_", ",", ".", "|", ";", "-", "  ", ", ", ": ", " :", ":"]

    for _, row in df.iterrows():
        first = row["firstname"].strip()
        last = row["lastname"].strip()
        if not first or not last:
            continue

        # Core forms
        full_variants.add(f"{first} {last}")
        reverse_full_variants.add(f"{last} {first}")
        reverse_full_variants.add(f"{last}, {first}")
        reverse_full_variants.add(f"{last}, {first[0]}")
        reverse_full_variants.add(f"{last}, {first[0]}.")

        # Separator variations
        for sep in seps:
            full_variants.add(f"{first}{sep}{last}")
            reverse_full_variants.add(f"{last}{sep}{first}")
            reverse_full_variants.add(f"{last}{sep}{first[0]}")
            reverse_full_variants.add(f"{last}{sep}{first[0]}.")

    return last_names, first_names, full_variants, reverse_full_variants


# ---------------------------
# GUI Prompt plumbing
# ---------------------------

class PromptRequest:
    """Container for a prompt request/response passed between worker and UI threads."""
    def __init__(self, token, raw_name, line, file_path):
        self.token = token
        self.raw_name = raw_name
        self.line = line
        self.file_path = file_path
        self.result_queue = queue.Queue()  # 'yes' | 'no' | 'accept_all'


# ---------------------------
# Worker that uses GUI prompts
# ---------------------------

class RedactionWorker(threading.Thread):
    def __init__(self, app, params):
        super().__init__(daemon=True)
        self.app = app
        self.params = params
        self.stop_event = threading.Event()
        self.total_files = 0
        self.changed_files = 0

    def stop(self):
        self.stop_event.set()

    # ---- file helpers ----

    def move_to_backup(self, original_path, input_folder, backup_folder_org):
        """Move the original file to a backup folder while maintaining structure."""
        rel_path = os.path.relpath(original_path, input_folder)
        backup_path_org = os.path.join(backup_folder_org, rel_path)
        os.makedirs(os.path.dirname(backup_path_org), exist_ok=True)

        # If target exists, timestamp it.
        if os.path.exists(backup_path_org):
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            base, ext = os.path.splitext(backup_path_org)
            backup_path_org = f"{base}_{timestamp}{ext}"

        shutil.move(original_path, backup_path_org)
        return backup_path_org

    # ---- prompt handler ----

    def prompt_handler(self, token, raw_name, line, file_path):
        """
        Synchronous handler called from worker thread.
        If interactive is disabled, always 'yes'.
        Otherwise, dispatch a modal prompt on the UI thread and wait for result.
        """
        if not self.params["interactive"]:
            return "yes"

        # 'Accept all' cache
        key = token.lower()
        if key in APPROVED_ACCEPT_ALL:
            return "accept_all_cached"

        req = PromptRequest(token, raw_name, line, file_path)
        self.app.enqueue_prompt(req)
        try:
            decision = req.result_queue.get()  # block until user answers
            return decision
        except Exception:
            return "no"

    # ---- text replacement ----

    def apply_name_replacements(self, text: str, raw_name: str, file_path: str) -> (str, bool):
        """
        Apply replacements for `raw_name` inside `text`, prompting via GUI once per token
        and allowing an 'accept all' option cached for identical tokens.
        Returns (new_text, changed?).
        """
        pat = compiled_name_pattern(raw_name)

        def repl(m: re.Match) -> str:
            tok = m.group(0)
            key = tok.lower()

            # If user already chose "accept all" for this exact token, reuse that decision.
            if key in APPROVED_ACCEPT_ALL:
                return APPROVED_ACCEPT_ALL[key]

            # Ask user
            decision = self.prompt_handler(tok, raw_name, text, file_path)
            if decision == "yes" or decision == "accept_all_cached":
                return replace_with_case_preserved(tok)
            elif decision == "accept_all":
                rep = replace_with_case_preserved(tok)
                APPROVED_ACCEPT_ALL[key] = rep
                return rep
            else:
                return tok  # keep original

        new_text, num_subs = pat.subn(repl, text)
        return new_text, (num_subs > 0)

    # ---- processing functions ----

    def process_tsv(self, file_path, automaton):
        """Process and redact TSV files (safe temp + atomic replace)."""
        changed = False
        temp_file_path = file_path + ".tmp"

        try:
            with open(file_path, "r", encoding="utf-8", newline="") as infile, \
                 open(temp_file_path, "w", encoding="utf-8", newline="") as outfile:
                reader = csv.reader(infile, delimiter="\t")
                writer = csv.writer(outfile, delimiter="\t")

                for row in reader:
                    new_row = []
                    for cell in row:
                        matches = sorted(set(find_matches(cell, automaton)), key=len, reverse=True)
                        for raw_name in matches:
                            cell, did = self.apply_name_replacements(cell, raw_name, file_path)
                            if did:
                                changed = True
                        new_row.append(cell)
                    writer.writerow(new_row)
        except Exception as e:
            if os.path.exists(temp_file_path):
                try: os.remove(temp_file_path)
                except: pass
            self.app.log(f"ERROR (TSV): {file_path}\n{e}")
            return False

        if changed:
            rel_path = os.path.relpath(file_path, self.params["input_folder"])
            backup_path_upd = os.path.join(self.params["backup_folder_upd"], rel_path)
            os.makedirs(os.path.dirname(backup_path_upd), exist_ok=True)
            shutil.copyfile(temp_file_path, backup_path_upd)

            backup_path_org = self.move_to_backup(file_path, self.params["input_folder"], self.params["backup_folder_org"])
            os.replace(temp_file_path, file_path)
            self.app.log(f"Redacted TSV. Original → {backup_path_org}\nUpdated copy → {backup_path_upd}")
        else:
            os.remove(temp_file_path)
            self.app.log("No changes in TSV.")

        return changed

    def process_json(self, file_path, automaton):
        """Process and redact JSON files (safe temp + atomic replace)."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.app.log(f"ERROR: Invalid JSON: {file_path}\n{e}")
            return False

        def redact(obj):
            changed_local = False
            if isinstance(obj, dict):
                new_d = {}
                for k, v in obj.items():
                    nv, ch = redact(v)
                    new_d[k] = nv
                    changed_local |= ch
                return new_d, changed_local
            elif isinstance(obj, list):
                new_l = []
                for v in obj:
                    nv, ch = redact(v)
                    new_l.append(nv)
                    changed_local |= ch
                return new_l, changed_local
            elif isinstance(obj, str):
                s = obj
                matches = sorted(set(find_matches(s, automaton)), key=len, reverse=True)
                for raw_name in matches:
                    s, did = self.apply_name_replacements(s, raw_name, file_path)
                    if did:
                        changed_local = True
                return s, changed_local
            else:
                return obj, False

        modified, changed = redact(data)

        if not changed:
            self.app.log("No changes in JSON.")
            return False

        # Write to temp
        temp_file_path = file_path + ".tmp.json"
        try:
            with open(temp_file_path, "w", encoding="utf-8") as f:
                json.dump(modified, f, indent=4, ensure_ascii=False)
        except Exception as e:
            if os.path.exists(temp_file_path):
                try: os.remove(temp_file_path)
                except: pass
            self.app.log(f"ERROR writing temp JSON: {file_path}\n{e}")
            return False

        rel_path = os.path.relpath(file_path, self.params["input_folder"])
        backup_path_upd = os.path.join(self.params["backup_folder_upd"], rel_path)
        os.makedirs(os.path.dirname(backup_path_upd), exist_ok=True)
        shutil.copyfile(temp_file_path, backup_path_upd)

        backup_path_org = self.move_to_backup(file_path, self.params["input_folder"], self.params["backup_folder_org"])
        os.replace(temp_file_path, file_path)
        self.app.log(f"Redacted JSON. Original → {backup_path_org}\nUpdated copy → {backup_path_upd}")
        return True

    def enumerate_target_files(self):
        """Collect .tsv and .json files based on recursion flag."""
        exts = {".tsv", ".json"}
        input_folder = self.params["input_folder"]
        recurse = self.params["recursive"]
        targets = []

        if recurse:
            for root, _, files in os.walk(input_folder):
                for fn in files:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext in exts:
                        targets.append(os.path.join(root, fn))
        else:
            for fn in os.listdir(input_folder):
                p = os.path.join(input_folder, fn)
                if os.path.isfile(p):
                    ext = os.path.splitext(fn)[1].lower()
                    if ext in exts:
                        targets.append(p)
        return targets

    def run(self):
        start = time.time()
        self.app.log("=== Redaction started ===")

        # Safety checks
        if pd is None:
            self.app.log("ERROR: pandas is not installed. Please run: pip install pandas")
            self.app.on_worker_done()
            return
        if ahocorasick is None:
            self.app.log("ERROR: pyahocorasick is not installed. Please run: pip install pyahocorasick")
            self.app.on_worker_done()
            return

        csv_path = self.params["csv_path"]
        try:
            self.app.log(f"Loading names from CSV: {csv_path}")
            last_names, first_names, full_names, reverse_full_names = load_names_from_csv(csv_path)
            names_for_ac = set().union(last_names, first_names, full_names, reverse_full_names)
            automaton = build_automaton(names_for_ac)
        except Exception as e:
            self.app.log(f"ERROR loading CSV names:\n{e}")
            self.app.on_worker_done()
            return

        try:
            targets = self.enumerate_target_files()
        except Exception as e:
            self.app.log(f"ERROR enumerating files:\n{e}")
            self.app.on_worker_done()
            return

        self.total_files = len(targets)
        self.app.set_progress(0, self.total_files)
        self.app.log(f"Found {self.total_files} files to scan "
                     f"({'recursive' if self.params['recursive'] else 'non-recursive'}).")

        handlers = {
            ".tsv": self.process_tsv,
            ".json": self.process_json,
        }

        files_done = 0
        changed_count = 0
        for path in targets:
            if self.stop_event.is_set():
                self.app.log("=== Stopped by user ===")
                break

            ext = os.path.splitext(path)[1].lower()
            handler = handlers.get(ext)
            if not handler:
                files_done += 1
                self.app.set_progress(files_done, self.total_files)
                continue

            self.app.log(f"Processing: {path}")
            try:
                if handler(path, automaton):
                    changed_count += 1
            except Exception as e:
                self.app.log(f"ERROR during processing:\n{path}\n{traceback.format_exc()}")

            files_done += 1
            self.app.set_progress(files_done, self.total_files)

        self.changed_files = changed_count
        elapsed = time.time() - start
        self.app.log(f"=== Done. Files modified: {changed_count} | Elapsed: {elapsed:.2f}s ===")
        self.app.on_worker_done()


# ---------------------------
# Main GUI App
# ---------------------------

class RedactorApp:
    def __init__(self, master):
        self.master = master
        master.title(APP_TITLE)
        master.geometry("1000x720")

        self.ini_path = INI_PATH_DEFAULT
        self.state = {
            "csv_path": "e:/iEEG_Demographics.csv",
            "input_folder": "c:/tmp/all_tsv/",
            "backup_folder_org": "c:/tmp/backup/org/",
            "backup_folder_upd": "c:/tmp/backup2/upd/",
            "recursive": True,
            "interactive": True,
            "ignore_list": list(DEFAULT_IGNORE_LIST),
        }

        # Queues for cross-thread communications
        self.log_queue = queue.Queue()
        self.prompt_queue = queue.Queue()

        # Worker
        self.worker = None

        # Build UI
        self._build_widgets()

        # Load settings (if INI exists)
        self.load_settings()

        # Compile ignore regex initially
        self.recompile_ignore()

        # Poll queues
        self.master.after(100, self._poll_log_queue)
        self.master.after(100, self._poll_prompt_queue)

        # Save on exit
        self.master.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- UI construction ----------

    def _build_widgets(self):
        pad = {"padx": 8, "pady": 6}

        frm_top = ttk.Frame(self.master)
        frm_top.pack(fill="x", **pad)

        # CSV path
        ttk.Label(frm_top, text="CSV (firstname/lastname):").grid(row=0, column=0, sticky="w")
        self.var_csv = tk.StringVar()
        e_csv = ttk.Entry(frm_top, textvariable=self.var_csv, width=80)
        e_csv.grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(frm_top, text="Browse...", command=self.browse_csv).grid(row=0, column=2, sticky="e")

        # Input folder
        ttk.Label(frm_top, text="Input folder:").grid(row=1, column=0, sticky="w")
        self.var_input = tk.StringVar()
        e_in = ttk.Entry(frm_top, textvariable=self.var_input, width=80)
        e_in.grid(row=1, column=1, sticky="we", **pad)
        ttk.Button(frm_top, text="Browse...", command=lambda: self.browse_folder(self.var_input)).grid(row=1, column=2, sticky="e")

        # Backup org
        ttk.Label(frm_top, text="Backup (originals) folder:").grid(row=2, column=0, sticky="w")
        self.var_org = tk.StringVar()
        e_org = ttk.Entry(frm_top, textvariable=self.var_org, width=80)
        e_org.grid(row=2, column=1, sticky="we", **pad)
        ttk.Button(frm_top, text="Browse...", command=lambda: self.browse_folder(self.var_org)).grid(row=2, column=2, sticky="e")

        # Backup upd
        ttk.Label(frm_top, text="Backup (updated copies) folder:").grid(row=3, column=0, sticky="w")
        self.var_upd = tk.StringVar()
        e_upd = ttk.Entry(frm_top, textvariable=self.var_upd, width=80)
        e_upd.grid(row=3, column=1, sticky="we", **pad)
        ttk.Button(frm_top, text="Browse...", command=lambda: self.browse_folder(self.var_upd)).grid(row=3, column=2, sticky="e")

        # Options
        frm_opts = ttk.Frame(self.master)
        frm_opts.pack(fill="x", **pad)

        self.var_recursive = tk.BooleanVar(value=True)
        self.var_interactive = tk.BooleanVar(value=True)

        chk_rec = ttk.Checkbutton(frm_opts, text="Recurse into subfolders", variable=self.var_recursive)
        chk_int = ttk.Checkbutton(frm_opts, text="Interactive confirmations (token prompts)", variable=self.var_interactive)
        chk_rec.grid(row=0, column=0, sticky="w", **pad)
        chk_int.grid(row=0, column=1, sticky="w", **pad)

        # Dictionary editor
        frm_dict = ttk.LabelFrame(self.master, text="Acceptable Words (will NOT be considered for redaction) — one per line")
        frm_dict.pack(fill="both", expand=False, **pad)

        self.txt_dict = tk.Text(frm_dict, height=8, wrap="word")
        self.txt_dict.pack(fill="both", expand=True, padx=6, pady=6)

        frm_dict_btns = ttk.Frame(self.master)
        frm_dict_btns.pack(fill="x", **pad)
        ttk.Button(frm_dict_btns, text="Apply Dictionary", command=self.apply_dictionary).pack(side="left")
        ttk.Button(frm_dict_btns, text="Save Settings", command=self.save_settings).pack(side="left")

        # Progress & Controls
        frm_prog = ttk.Frame(self.master)
        frm_prog.pack(fill="x", **pad)

        self.prog = ttk.Progressbar(frm_prog, orient="horizontal", mode="determinate")
        self.prog.pack(fill="x", expand=True, side="left", padx=6, pady=6)
        self.lbl_prog = ttk.Label(frm_prog, text="0 / 0")
        self.lbl_prog.pack(side="left", padx=8)

        frm_ctrl = ttk.Frame(self.master)
        frm_ctrl.pack(fill="x", **pad)
        self.btn_start = ttk.Button(frm_ctrl, text="Start", command=self.start_worker)
        self.btn_stop = ttk.Button(frm_ctrl, text="Stop", command=self.stop_worker, state="disabled")
        self.btn_start.pack(side="left")
        self.btn_stop.pack(side="left", padx=6)

        # Log
        frm_log = ttk.LabelFrame(self.master, text="Log")
        frm_log.pack(fill="both", expand=True, **pad)
        self.txt_log = tk.Text(frm_log, wrap="word", height=18)
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=6)

        # Make entry columns expand
        frm_top.grid_columnconfigure(1, weight=1)

    # ---------- Handlers ----------

    def browse_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if path:
            self.var_csv.set(path)

    def browse_folder(self, var):
        folder = filedialog.askdirectory()
        if folder:
            var.set(folder if folder.endswith(os.sep) else folder + os.sep)

    def log(self, msg):
        self.log_queue.put(str(msg))

    def set_progress(self, done, total):
        total = max(total, 1)
        self.prog["maximum"] = total
        self.prog["value"] = done
        self.lbl_prog.config(text=f"{done} / {total}")
        self.master.update_idletasks()

    def enqueue_prompt(self, prompt_request: PromptRequest):
        self.prompt_queue.put(prompt_request)

    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.txt_log.insert("end", msg + "\n")
                self.txt_log.see("end")
        except queue.Empty:
            pass
        self.master.after(100, self._poll_log_queue)

    def _poll_prompt_queue(self):
        # Process at most one prompt per tick to remain responsive
        try:
            req = self.prompt_queue.get_nowait()
        except queue.Empty:
            self.master.after(100, self._poll_prompt_queue)
            return

        # Show blocking modal dialog on UI thread; return 'yes'|'no'|'accept_all'
        self._show_prompt_dialog(req)

        # Schedule next poll
        self.master.after(50, self._poll_prompt_queue)

    def _show_prompt_dialog(self, req: PromptRequest):
        # Build content with context stripped from acceptable words
        tmp_line = _strip_ignored(req.line)

        dlg = tk.Toplevel(self.master)
        dlg.title("Confirm redaction")
        dlg.transient(self.master)
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=10)
        frm.pack(fill="both", expand=True)

        lbl1 = ttk.Label(frm, text=f"File: {req.file_path}", wraplength=900, justify="left")
        lbl2 = ttk.Label(frm, text=f"Matched token: '{req.token}'  (from raw name: '{req.raw_name}')", wraplength=900, justify="left")
        lbl3 = ttk.Label(frm, text="Context (acceptable words removed for clarity):", justify="left")
        txt = tk.Text(frm, height=6, wrap="word")
        txt.insert("1.0", tmp_line.strip())
        txt.config(state="disabled")

        lbl1.pack(anchor="w", pady=(0, 6))
        lbl2.pack(anchor="w", pady=(0, 6))
        lbl3.pack(anchor="w")
        txt.pack(fill="both", expand=True, pady=(2, 8))

        # Buttons
        btns = ttk.Frame(frm)
        btns.pack(fill="x")
        def decide(value):
            if value == "accept_all":
                # cache immediately
                rep = ".X." if (len(req.token) and req.token[0].isupper()) else ".x."
                APPROVED_ACCEPT_ALL[req.token.lower()] = rep
            req.result_queue.put(value)
            dlg.destroy()

        ttk.Button(btns, text="Replace", command=lambda: decide("yes")).pack(side="left")
        ttk.Button(btns, text="Skip", command=lambda: decide("no")).pack(side="left", padx=8)
        ttk.Button(btns, text="Accept all (this exact token)", command=lambda: decide("accept_all")).pack(side="left")

        # Center dialog
        dlg.update_idletasks()
        x = self.master.winfo_x() + (self.master.winfo_width() // 2) - (dlg.winfo_width() // 2)
        y = self.master.winfo_y() + (self.master.winfo_height() // 2) - (dlg.winfo_height() // 2)
        dlg.geometry(f"+{x}+{y}")

        dlg.wait_window()

    def start_worker(self):
        if self.worker and self.worker.is_alive():
            return

        # Gather state
        params = {
            "csv_path": self.var_csv.get().strip(),
            "input_folder": self.var_input.get().strip(),
            "backup_folder_org": self.var_org.get().strip(),
            "backup_folder_upd": self.var_upd.get().strip(),
            "recursive": bool(self.var_recursive.get()),
            "interactive": bool(self.var_interactive.get()),
        }

        # Basic validation
        if not params["csv_path"] or not os.path.isfile(params["csv_path"]):
            messagebox.showerror("Missing CSV", "Please select a valid CSV file with firstname/lastname columns.")
            return
        if not params["input_folder"] or not os.path.isdir(params["input_folder"]):
            messagebox.showerror("Missing Input Folder", "Please select a valid input folder.")
            return
        if not params["backup_folder_org"]:
            messagebox.showerror("Missing Backup (Originals) Folder", "Please select a backup folder for originals.")
            return
        if not params["backup_folder_upd"]:
            messagebox.showerror("Missing Backup (Updated) Folder", "Please select a backup folder for updated copies.")
            return

        # Ensure backup folders exist
        os.makedirs(params["backup_folder_org"], exist_ok=True)
        os.makedirs(params["backup_folder_upd"], exist_ok=True)

        # Save settings on start
        self.save_settings()

        # Reset caches
        APPROVED_ACCEPT_ALL.clear()

        # Start worker
        self.worker = RedactionWorker(self, params)
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.set_progress(0, 0)
        self.log("")  # spacing
        self.worker.start()

    def stop_worker(self):
        if self.worker and self.worker.is_alive():
            self.worker.stop()

    def on_worker_done(self):
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")

    def apply_dictionary(self):
        words = self._read_dict_from_text()
        self.state["ignore_list"] = words
        self.recompile_ignore()
        self.save_settings()
        self.log(f"Applied dictionary with {len(words)} entries.")

    def recompile_ignore(self):
        global _IGNORE_RE
        _IGNORE_RE = _compile_ignore_pattern(self.state.get("ignore_list", []))

    # ---------- Settings (INI) ----------

    def load_settings(self):
        ini_path = self.ini_path
        if not os.path.exists(ini_path):
            # Seed defaults into UI
            self._state_to_ui(self.state)
            return

        cfg = configparser.ConfigParser()
        try:
            cfg.read(ini_path)
            s = cfg["Paths"] if "Paths" in cfg else {}
            o = cfg["Options"] if "Options" in cfg else {}
            d = cfg["Dictionary"] if "Dictionary" in cfg else {}

            self.state["csv_path"] = s.get("csv_path", self.state["csv_path"])
            self.state["input_folder"] = s.get("input_folder", self.state["input_folder"])
            self.state["backup_folder_org"] = s.get("backup_folder_org", self.state["backup_folder_org"])
            self.state["backup_folder_upd"] = s.get("backup_folder_upd", self.state["backup_folder_upd"])

            self.state["recursive"] = o.get("recursive", str(self.state["recursive"])).lower() == "true"
            self.state["interactive"] = o.get("interactive", str(self.state["interactive"])).lower() == "true"

            # Dictionary: prefer JSON for robustness
            words_json = d.get("words_json", "")
            if words_json.strip():
                try:
                    self.state["ignore_list"] = json.loads(words_json)
                except Exception:
                    # fallback: semicolon/newline delimited
                    raw = d.get("words", "")
                    self.state["ignore_list"] = [w.strip() for w in re.split(r"[;\n\r]+", raw) if w.strip()]
            else:
                raw = d.get("words", "")
                if raw:
                    self.state["ignore_list"] = [w.strip() for w in re.split(r"[;\n\r]+", raw) if w.strip()]
        except Exception as e:
            messagebox.showwarning("Settings", f"Failed to read INI. Using defaults.\n\n{e}")

        self._state_to_ui(self.state)

    def save_settings(self):
        self._ui_to_state()
        cfg = configparser.ConfigParser()

        cfg["Paths"] = {
            "csv_path": self.state["csv_path"],
            "input_folder": self.state["input_folder"],
            "backup_folder_org": self.state["backup_folder_org"],
            "backup_folder_upd": self.state["backup_folder_upd"],
        }
        cfg["Options"] = {
            "recursive": str(self.state["recursive"]),
            "interactive": str(self.state["interactive"]),
        }
        # Store both JSON and a joined list for human readability
        words = self.state.get("ignore_list", [])
        cfg["Dictionary"] = {
            "words_json": json.dumps(words, ensure_ascii=False),
            "words": "\n".join(words),
        }

        try:
            with open(self.ini_path, "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception as e:
            messagebox.showerror("Settings", f"Failed to write INI file.\n\n{e}")

    def _state_to_ui(self, st):
        self.var_csv.set(st["csv_path"])
        self.var_input.set(st["input_folder"])
        self.var_org.set(st["backup_folder_org"])
        self.var_upd.set(st["backup_folder_upd"])
        self.var_recursive.set(st["recursive"])
        self.var_interactive.set(st["interactive"])
        self.txt_dict.delete("1.0", "end")
        self.txt_dict.insert("1.0", "\n".join(st.get("ignore_list", [])))

    def _ui_to_state(self):
        self.state["csv_path"] = self.var_csv.get().strip()
        self.state["input_folder"] = self.var_input.get().strip()
        self.state["backup_folder_org"] = self.var_org.get().strip()
        self.state["backup_folder_upd"] = self.var_upd.get().strip()
        self.state["recursive"] = bool(self.var_recursive.get())
        self.state["interactive"] = bool(self.var_interactive.get())
        self.state["ignore_list"] = self._read_dict_from_text()

    def _read_dict_from_text(self):
        lines = self.txt_dict.get("1.0", "end").splitlines()
        words = [ln.strip() for ln in lines if ln.strip()]
        return words

    def on_close(self):
        try:
            self.save_settings()
        except Exception:
            pass
        self.master.destroy()


def main():
    root = tk.Tk()
    app = RedactorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
