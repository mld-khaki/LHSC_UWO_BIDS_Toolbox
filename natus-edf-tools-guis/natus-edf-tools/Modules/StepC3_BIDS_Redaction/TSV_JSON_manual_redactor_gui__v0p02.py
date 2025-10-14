#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import queue
import threading
import traceback
from pathlib import Path
from configparser import ConfigParser

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

APP_TITLE = "Redaction GUI"
DEFAULT_INI_NAME = "redaction_dict.ini"

# ---------- Utility: tokenization and patterns ----------

# Timestamp patterns: 01:09:39 or 01:09:39.865723
TIME_HHMMSS_RE = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?\b")
# Pure number (int/float, positive/negative)
NUMERIC_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

# Word-ish tokens (keep emails/usernames as a single token when possible)
TOKEN_RE = re.compile(r"[A-Za-z0-9_@.\-']+")

def is_timestamp_like(token: str) -> bool:
    """Return True if the token is a time-like token or purely numeric timestamp."""
    if NUMERIC_RE.match(token):
        return True
    return bool(TIME_HHMMSS_RE.search(token))

def extract_tokens(text: str):
    """Yield tokens (string) with their spans for later replacement, if needed."""
    for m in TOKEN_RE.finditer(text):
        yield m.group(0), m.start(), m.end()

def normalize_token(tok: str) -> str:
    """Normalization for dictionary keys (case-insensitive, strip)."""
    return tok.strip().lower()

def redaction_replacement(token: str) -> str:
    """What to put in place of a redacted token."""
    return "[REDACTED]"

# ---------- Config (INI) persistence ----------

class RedactionDictionary:
    """
    Maintains a dictionary mapping normalized tokens -> bool (True=redactable, False=not).
    Persists to INI under section [dictionary], value '1' or '0'.
    """
    def __init__(self, ini_path: Path):
        self.ini_path = ini_path
        self._map = {}  # str -> bool

    def load(self):
        self._map.clear()
        cfg = ConfigParser()
        if self.ini_path.exists():
            cfg.read(self.ini_path, encoding="utf-8")
            if cfg.has_section("dictionary"):
                for k, v in cfg.items("dictionary"):
                    self._map[k] = (v.strip() == "1")

    def save(self):
        cfg = ConfigParser()
        cfg.add_section("dictionary")
        for k, v in sorted(self._map.items()):
            cfg.set("dictionary", k, "1" if v else "0")
        with open(self.ini_path, "w", encoding="utf-8") as f:
            cfg.write(f)

    def set(self, token_norm: str, redactable: bool):
        self._map[token_norm] = redactable

    def get(self, token_norm: str):
        return self._map.get(token_norm, None)

    def items(self):
        return self._map.items()

    def remove(self, token_norm: str):
        if token_norm in self._map:
            del self._map[token_norm]

# ---------- Core redaction helpers ----------

def _select_non_overlapping_tokens(tokens):
    """
    Given tokens as (tok, start, end) sorted by longest-first then left-to-right,
    choose a non-overlapping set (greedy), then return sorted by start asc.
    """
    chosen = []
    covered = []
    for tok, s, e in tokens:
        if any(s < ce and e > cs for cs, ce in covered):
            continue
        chosen.append((tok, s, e))
        covered.append((s, e))
    chosen.sort(key=lambda x: x[1])  # left-to-right for reconstruction
    return chosen

def _reconstruct_with_spans(src, spans):
    """
    Rebuild string from src using spans = list of (start, end, replacement_or_None).
    If replacement_or_None is None, keep original slice.
    Spans must be sorted by start asc and non-overlapping.
    """
    out = []
    cursor = 0
    for s, e, repl in spans:
        if cursor < s:
            out.append(src[cursor:s])
        if repl is None:
            out.append(src[s:e])
        else:
            out.append(repl)
        cursor = e
    if cursor < len(src):
        out.append(src[cursor:])
    return "".join(out)

def redact_string_using_dict(s: str, rdict: RedactionDictionary, app=None):
    """
    Redact tokens in a string based on the dictionary.
    - Skip timestamps and pure numerics
    - Handle tokens with numbers at start or end separately (keep)
    - Always prioritize longest tokens first; resolve overlaps
    Returns (redacted_string, unknown_token_set)
    """
    unknown = set()

    # Collect tokens and sort longest-first (then left-to-right for tiebreak)
    tokens = [(tok, start, end) for tok, start, end in extract_tokens(s)]
    tokens.sort(key=lambda x: (-len(x[0]), x[1]))

    # Choose non-overlapping tokens
    chosen = _select_non_overlapping_tokens(tokens)

    # Build spans with replacements where applicable
    spans = []
    for tok, start, end in chosen:
        # Numeric prefix/suffix are kept (not redacted, not asked)
        if tok[0].isdigit() or tok[-1].isdigit():
            spans.append((start, end, None))
            continue

        if is_timestamp_like(tok):
            spans.append((start, end, None))
            continue

        key = normalize_token(tok)

        # Session-only decisions first
        if app and key in app.session_redact_once:
            spans.append((start, end, redaction_replacement(tok)))
            continue
        if app and key in app.session_skip_once:
            spans.append((start, end, None))
            continue

        known = rdict.get(key)
        if known is None:
            unknown.add(key)
            spans.append((start, end, None))  # leave as-is until user decides
        else:
            spans.append((start, end, redaction_replacement(tok) if known else None))

    # Reconstruct the line from spans
    spans.sort(key=lambda x: x[0])
    redacted_text = _reconstruct_with_spans(s, spans)
    return redacted_text, unknown

def traverse_and_redact_json(obj, rdict: RedactionDictionary, app=None):
    """
    Traverse JSON (dict/list/str/etc). Redact strings. Collect unknown tokens.
    Returns (new_obj, unknown_set)
    """
    unknown = set()
    if isinstance(obj, dict):
        new_d = {}
        for k, v in obj.items():
            nv, u = traverse_and_redact_json(v, rdict, app)
            new_d[k] = nv
            unknown |= u
        return new_d, unknown
    elif isinstance(obj, list):
        new_l = []
        for it in obj:
            nv, u = traverse_and_redact_json(it, rdict, app)
            new_l.append(nv)
            unknown |= u
        return new_l, unknown
    elif isinstance(obj, str):
        ns, u = redact_string_using_dict(obj, rdict, app)
        return ns, u
    else:
        return obj, set()

# ---------- Main Application (Review-tab driven) ----------

class RedactionApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # Session-only decisions (not persisted in INI)
        self.session_redact_once = set()
        self.session_skip_once = set()

        self.title(APP_TITLE)
        self.geometry("980x720")

        # State
        self.folders = []  # list of Paths
        self.ini_path = Path(DEFAULT_INI_NAME).resolve()
        self.rdict = RedactionDictionary(self.ini_path)
        self.rdict.load()

        # UI
        self._build_menu()
        self._build_main_layout()

        # Worker thread for scanning (keeps UI responsive)
        self.scan_thread = None
        self.scan_queue = queue.Queue()

        # Used by review-tab blocking wait
        self._choice_var = tk.StringVar(value="")  # "yes"|"no"|"skip"|"once"

        self._log(f"Loaded dictionary from: {self.ini_path}")

    # ----- UI Builders -----

    def _build_menu(self):
        menubar = tk.Menu(self)
        # File
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Add Folder...", command=self.add_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Load Dictionary...", command=self.load_ini_dialog)
        file_menu.add_command(label="Save Dictionary", command=self.save_ini)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        # Dictionary
        dict_menu = tk.Menu(menubar, tearoff=0)
        dict_menu.add_command(label="Add Entry...", command=self.add_dict_entry_dialog)
        dict_menu.add_command(label="Remove Selected Entry", command=self.remove_selected_dict_entry)
        menubar.add_cascade(label="Dictionary", menu=dict_menu)

        self.config(menu=menubar)

    def _build_main_layout(self):
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Left: folders and dictionary
        left = ttk.Frame(paned, padding=8)
        paned.add(left, weight=1)

        # Right: preview + review + log (Notebook on right)
        right = ttk.Frame(paned, padding=8)
        paned.add(right, weight=3)

        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # --- Preview tab ---
        self.preview_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.preview_tab, text="Preview")
        self.preview_text = tk.Text(self.preview_tab, wrap="word", height=20)
        self.preview_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # --- Review tab ---
        self.review_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.review_tab, text="Review")

        self.review_text = tk.Text(self.review_tab, wrap="word", height=20)
        self.review_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Styling tags
        self.review_text.tag_configure("context", foreground="blue")
        self.review_text.tag_configure("token", foreground="red", font=("TkDefaultFont", 10, "bold"))

        # Decision buttons
        btnfrm = ttk.Frame(self.review_tab)
        btnfrm.pack(fill=tk.X, pady=8)
        ttk.Button(btnfrm, text="Redact (Enter)", command=lambda: self._set_choice("yes")).pack(side=tk.LEFT, padx=4)
        ttk.Button(btnfrm, text="Redact Once (Ctrl+Enter)", command=lambda: self._set_choice("once")).pack(side=tk.LEFT, padx=4)
        ttk.Button(btnfrm, text="Don't Redact (Esc)", command=lambda: self._set_choice("no")).pack(side=tk.LEFT, padx=4)
        ttk.Button(btnfrm, text="Skip (Space)", command=lambda: self._set_choice("skip")).pack(side=tk.LEFT, padx=4)

        # Key bindings for decisions
        self.bind("<Return>", lambda e: self._set_choice("yes"))
        self.bind("<Control-Return>", lambda e: self._set_choice("once"))
        self.bind("<Escape>", lambda e: self._set_choice("no"))
        self.bind("<space>", lambda e: self._set_choice("skip"))

        # Folders group
        folders_labelframe = ttk.LabelFrame(left, text="Folders to Scan (.tsv, .json)")
        folders_labelframe.pack(fill=tk.BOTH, expand=False, pady=(0, 8))
        self.folders_list = tk.Listbox(folders_labelframe, height=6)
        self.folders_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=8)
        fbtns = ttk.Frame(folders_labelframe)
        fbtns.pack(side=tk.RIGHT, padx=8, pady=8, anchor="n")
        ttk.Button(fbtns, text="Add...", command=self.add_folder).pack(fill=tk.X, pady=2)
        ttk.Button(fbtns, text="Remove Selected", command=self.remove_selected_folder).pack(fill=tk.X, pady=2)
        ttk.Button(fbtns, text="Clear All", command=self.clear_folders).pack(fill=tk.X, pady=2)

        # Dictionary group
        dict_labelframe = ttk.LabelFrame(left, text="Dictionary (token → redactable?)")
        dict_labelframe.pack(fill=tk.BOTH, expand=True)
        self.dict_tree = ttk.Treeview(dict_labelframe, columns=("token", "redact"), show="headings", height=12)
        self.dict_tree.heading("token", text="Token (normalized)")
        self.dict_tree.heading("redact", text="Redactable")
        self.dict_tree.column("token", width=220, anchor="w")
        self.dict_tree.column("redact", width=120, anchor="center")
        self.dict_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=8)

        dict_btns = ttk.Frame(dict_labelframe)
        dict_btns.pack(side=tk.RIGHT, padx=8, pady=8, anchor="n")
        ttk.Button(dict_btns, text="Refresh", command=self.refresh_dict_view).pack(fill=tk.X, pady=2)
        ttk.Button(dict_btns, text="Toggle Selected", command=self.toggle_selected_dict_entry).pack(fill=tk.X, pady=2)
        ttk.Button(dict_btns, text="Save INI", command=self.save_ini).pack(fill=tk.X, pady=2)

        self.refresh_dict_view()

        # Actions + labels
        actions = ttk.Frame(right)
        actions.pack(fill=tk.X, expand=False)
        ttk.Button(actions, text="Scan Folders", command=self.scan_folders).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(actions, text="Save Redacted Copy of Current Preview", command=self.save_current_preview_copy)\
            .pack(side=tk.LEFT)

        self.current_file_var = tk.StringVar(value="No file preview")
        ttk.Label(right, textvariable=self.current_file_var).pack(anchor="w", pady=(8, 0))

        # Redacted Preview (separate labeled frame)
        preview_frame = ttk.LabelFrame(right, text="Redacted Preview")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 8))
        self.preview_text2 = tk.Text(preview_frame, wrap="word", height=20)
        self.preview_text2.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Log text
        log_frame = ttk.LabelFrame(right, text="Log")
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_frame, wrap="word", height=10, state="disabled")
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    # ----- Helpers for Review tab -----

    def _present_in_review(self, token_norm: str, context: str):
        """Display the token (red) within its context (blue) and switch to Review tab."""
        self.review_text.configure(state="normal")
        self.review_text.delete("1.0", tk.END)

        # Insert context first (blue)
        ctx = context if context is not None else ""
        self.review_text.insert("1.0", ctx, "context")

        # Highlight the first case-insensitive match of token in the context
        if token_norm:
            idx = self.review_text.search(token_norm, "1.0", stopindex="end", nocase=True)
            if idx:
                end_idx = f"{idx}+{len(token_norm)}c"
                self.review_text.tag_add("token", idx, end_idx)

        self.review_text.configure(state="disabled")
        self.notebook.select(self.review_tab)

    def _set_choice(self, val):
        """Button/key callback to set the decision and release the wait."""
        self._choice_var.set(val)

    def _get_choice_from_review(self, token_norm: str, context: str):
        """Show in review pane and block (without a modal dialog) until user chooses."""
        self._present_in_review(token_norm, context)
        self._choice_var.set("")  # reset
        self.wait_variable(self._choice_var)
        return self._choice_var.get()

    # ----- Folder management -----

    def add_folder(self):
        p = filedialog.askdirectory(title="Select folder to scan")
        if not p:
            return
        pth = Path(p).resolve()
        if not pth.exists() or not pth.is_dir():
            messagebox.showerror("Invalid folder", "Selected path is not a folder.")
            return
        if pth in self.folders:
            messagebox.showinfo("Already added", "Folder is already in the list.")
            return
        self.folders.append(pth)
        self.folders_list.insert(tk.END, str(pth))
        self._log(f"Added folder: {pth}")

    def remove_selected_folder(self):
        sel = list(self.folders_list.curselection())
        sel.reverse()
        for idx in sel:
            self._log(f"Removed folder: {self.folders[idx]}")
            del self.folders[idx]
            self.folders_list.delete(idx)

    def clear_folders(self):
        self.folders.clear()
        self.folders_list.delete(0, tk.END)
        self._log("Cleared folder list.")

    # ----- Dictionary management -----

    def refresh_dict_view(self):
        for i in self.dict_tree.get_children():
            self.dict_tree.delete(i)
        for token, is_red in sorted(self.rdict.items()):
            self.dict_tree.insert("", tk.END, values=(token, "Yes" if is_red else "No"))

    def toggle_selected_dict_entry(self):
        sel = self.dict_tree.selection()
        if not sel:
            return
        for item in sel:
            token, cur = self.dict_tree.item(item, "values")
            new_val = (cur != "Yes")
            self.rdict.set(token, new_val)
        self.refresh_dict_view()
        self._log("Toggled selected dictionary entries (remember to Save INI).")

    def add_dict_entry_dialog(self):
        token = simpledialog.askstring("Add Dictionary Entry", "Token to add (will be normalized to lowercase):",
                                       parent=self)
        if not token:
            return
        token_norm = normalize_token(token)
        choice = messagebox.askyesno("Mark redactable?",
                                     f"Mark '{token_norm}' as REDACTABLE?\nYes = redactable, No = not redactable.")
        self.rdict.set(token_norm, choice)
        self.refresh_dict_view()
        self._log(f"Added '{token_norm}' to dictionary (redactable={choice}).")

    def remove_selected_dict_entry(self):
        sel = self.dict_tree.selection()
        if not sel:
            return
        for item in sel:
            token, _ = self.dict_tree.item(item, "values")
            self.rdict.remove(token)
        self.refresh_dict_view()
        self._log("Removed selected dictionary entries (remember to Save INI).")

    def load_ini_dialog(self):
        p = filedialog.askopenfilename(title="Open dictionary INI",
                                       filetypes=[("INI files", "*.ini"), ("All files", "*.*")])
        if not p:
            return
        self.ini_path = Path(p).resolve()
        self.rdict = RedactionDictionary(self.ini_path)
        self.rdict.load()
        self.refresh_dict_view()
        self._log(f"Loaded dictionary from: {self.ini_path}")

    def save_ini(self):
        # Offer save-as if path doesn't exist yet
        if not self.ini_path.exists():
            p = filedialog.asksaveasfilename(title="Save dictionary INI as...",
                                             defaultextension=".ini",
                                             initialfile=DEFAULT_INI_NAME,
                                             filetypes=[("INI files", "*.ini"), ("All files", "*.*")])
            if not p:
                return
            self.ini_path = Path(p).resolve()
            self.rdict.ini_path = self.ini_path

        self.rdict.save()
        self._log(f"Saved dictionary to: {self.ini_path}")
        messagebox.showinfo("Saved", f"Dictionary saved to:\n{self.ini_path}")

    # ----- Scanning -----

    def scan_folders(self):
        if not self.folders:
            messagebox.showinfo("No folders", "Please add at least one folder to scan.")
            return
        if self.scan_thread and self.scan_thread.is_alive():
            messagebox.showinfo("Busy", "A scan is already running.")
            return

        # Clear preview
        self.preview_text.delete("1.0", tk.END) if hasattr(self, "preview_text") else None
        self.preview_text2.delete("1.0", tk.END)
        self.current_file_var.set("No file preview")

        # Launch worker
        self.scan_thread = threading.Thread(target=self._scan_worker, daemon=True)
        self.scan_thread.start()
        self.after(150, self._poll_scan_queue)  # start polling queue

    def _poll_scan_queue(self):
        try:
            while True:
                kind, payload = self.scan_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "preview":
                    path, content = payload
                    self.current_file_var.set(f"Preview: {path}")
                    self.preview_text2.delete("1.0", tk.END)
                    self.preview_text2.insert("1.0", content)
                elif kind == "error":
                    self._log(payload)
                elif kind == "done":
                    self._log("Scan complete.")
        except queue.Empty:
            pass

        # Keep polling if thread alive
        if self.scan_thread and self.scan_thread.is_alive():
            self.after(150, self._poll_scan_queue)

    def _scan_worker(self):
        try:
            for folder in list(self.folders):
                for root, dirs, files in os.walk(folder):
                    for name in files:
                        fpath = Path(root) / name
                        if fpath.suffix.lower() == ".tsv":
                            self._process_tsv(fpath)
                        elif fpath.suffix.lower() == ".json":
                            self._process_json(fpath)
            self.scan_queue.put(("done", None))
        except Exception as e:
            tb = traceback.format_exc()
            self.scan_queue.put(("error", f"ERROR during scan: {e}\n{tb}"))

    def _process_tsv(self, path: Path):
        """
        Read TSV, build redacted content (line-by-line).
        For newly encountered tokens, present in Review tab and update dictionary/session,
        then re-run the line redaction with the updated decision.
        """
        self.scan_queue.put(("log", f"Processing TSV: {path}"))
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception as e:
            self.scan_queue.put(("error", f"Failed to read {path}: {e}"))
            return

        redacted_lines = []
        for line in lines:
            red_line, unknown = redact_string_using_dict(line, self.rdict, self)
            if unknown:
                # Prompt per token in Review tab; collect answers then apply
                for token_norm in sorted(unknown):
                    ctx = line.strip()
                    choice = self._get_choice_from_review(token_norm, ctx)
                    if choice == "yes":
                        self.rdict.set(token_norm, True)
                    elif choice == "no":
                        self.rdict.set(token_norm, False)
                    elif choice == "once":
                        self.session_redact_once.add(token_norm)
                    elif choice == "skip":
                        self.session_skip_once.add(token_norm)
                # Re-apply redaction for this line with updated decisions
                red_line, _ = redact_string_using_dict(line, self.rdict, self)
            redacted_lines.append(red_line)

        redacted_content = "".join(redacted_lines)
        # Show preview of the last processed file
        self.scan_queue.put(("preview", (str(path), redacted_content)))

    def _process_json(self, path: Path):
        """
        Read JSON, traverse, redact strings. Prompt for new tokens as needed in Review tab,
        then re-run until no unknowns remain (or loop bound).
        """
        self.scan_queue.put(("log", f"Processing JSON: {path}"))
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except Exception as e:
            self.scan_queue.put(("error", f"Failed to read JSON {path}: {e}"))
            return

        # First pass
        redacted_data, unknown = traverse_and_redact_json(data, self.rdict, self)

        # If unknown tokens exist, prompt and re-apply until no unknowns remain
        max_loops = 5
        loops = 0
        while unknown and loops < max_loops:
            for token_norm in sorted(unknown):
                try:
                    context = json.dumps(data, ensure_ascii=False)[:1000]
                except Exception:
                    context = "<context unavailable>"
                choice = self._get_choice_from_review(token_norm, context)
                if choice == "yes":
                    self.rdict.set(token_norm, True)
                elif choice == "no":
                    self.rdict.set(token_norm, False)
                elif choice == "once":
                    self.session_redact_once.add(token_norm)
                elif choice == "skip":
                    self.session_skip_once.add(token_norm)
            redacted_data, unknown = traverse_and_redact_json(data, self.rdict, self)
            loops += 1

        try:
            redacted_content = json.dumps(redacted_data, ensure_ascii=False, indent=2)
        except Exception as e:
            self.scan_queue.put(("error", f"Failed to serialize redacted JSON {path}: {e}"))
            return

        self.scan_queue.put(("preview", (str(path), redacted_content)))

    # ----- Preview saving -----

    def save_current_preview_copy(self):
        content = self.preview_text2.get("1.0", tk.END)
        label = self.current_file_var.get()
        if not content.strip() or not label.startswith("Preview: "):
            messagebox.showinfo("Nothing to save", "No previewed content to save.")
            return
        orig_path = Path(label.replace("Preview: ", "", 1))
        if not orig_path.exists():
            messagebox.showerror("File not found", f"Original file no longer exists:\n{orig_path}")
            return

        # Build output path: <name>.redacted<ext>
        out_path = orig_path.with_name(f"{orig_path.stem}.redacted{orig_path.suffix}")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
            self._log(f"Saved redacted copy: {out_path}")
            messagebox.showinfo("Saved", f"Redacted copy saved:\n{out_path}")
        except Exception as e:
            messagebox.showerror("Save failed", f"Could not save redacted copy:\n{e}")

    # ----- Logging -----

    def _log(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.configure(state="disabled")
        self.log_text.see(tk.END)

# ---------- Main ----------

def main():
    app = RedactionApp()
    app.mainloop()

if __name__ == "__main__":
    main()
