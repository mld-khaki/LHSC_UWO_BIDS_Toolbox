"""
Dual-Folder File Comparator
Finds files with similar sizes across two folders and compares them.
Settings (folder paths, extension filter) are persisted in folder_compare.ini
beside this script.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import hashlib
import threading
import configparser
from pathlib import Path


# ─────────────────────────────────────────────
# Settings (INI)
# ─────────────────────────────────────────────

INI_PATH = Path(__file__).with_name("folder_compare.ini")
INI_SECTION = "Settings"
INI_DEFAULTS = {
    "folder_a":  "",
    "folder_b":  "",
    "extension": ".edf",
}


def load_settings():
    cfg = configparser.ConfigParser()
    if INI_PATH.exists():
        cfg.read(INI_PATH, encoding="utf-8")
    if not cfg.has_section(INI_SECTION):
        cfg.add_section(INI_SECTION)
    result = {}
    for key, default in INI_DEFAULTS.items():
        result[key] = cfg.get(INI_SECTION, key, fallback=default)
    return result


def save_settings(**kwargs):
    cfg = configparser.ConfigParser()
    # Preserve any existing keys we don't touch
    if INI_PATH.exists():
        cfg.read(INI_PATH, encoding="utf-8")
    if not cfg.has_section(INI_SECTION):
        cfg.add_section(INI_SECTION)
    for key, val in kwargs.items():
        cfg.set(INI_SECTION, key, val)
    with open(INI_PATH, "w", encoding="utf-8") as fh:
        cfg.write(fh)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files(root, ext_filter=None):
    """
    Return list of (abs_path, size) for every file under root.
    If ext_filter is a non-empty string, only files whose extension matches
    (case-insensitive) are included.  Examples: '.edf', 'edf', '.EDF'.
    """
    if ext_filter:
        # Normalise: ensure leading dot, lowercase
        ext_filter = ext_filter.strip()
        if ext_filter and not ext_filter.startswith("."):
            ext_filter = "." + ext_filter
        ext_filter = ext_filter.lower()

    files = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if ext_filter and Path(fn).suffix.lower() != ext_filter:
                continue
            fp = os.path.join(dirpath, fn)
            try:
                sz = os.path.getsize(fp)
                files.append((fp, sz))
            except OSError:
                pass
    return files


def find_size_matches(files_a, files_b):
    """
    Return list of (path_a, path_b, size) where size matches exactly.
    Groups by size; pairs every file on side A with every same-size file on side B.
    """
    size_map_b = {}
    for fp, sz in files_b:
        size_map_b.setdefault(sz, []).append(fp)

    matches = []
    for fp, sz in files_a:
        if sz in size_map_b:
            for fp_b in size_map_b[sz]:
                matches.append((fp, fp_b, sz))
    return matches


# ─────────────────────────────────────────────
# Compare logic
# ─────────────────────────────────────────────

MB = 1024 * 1024


def compare_bytes_full(path_a, path_b, progress_cb=None):
    """Full byte-by-byte comparison. Returns (equal, detail_msg)."""
    size_a = os.path.getsize(path_a)
    size_b = os.path.getsize(path_b)
    if size_a != size_b:
        return False, f"Size mismatch: {human_size(size_a)} vs {human_size(size_b)}"
    read = 0
    CHUNK = 65536
    with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
        while True:
            ba = fa.read(CHUNK)
            bb = fb.read(CHUNK)
            if ba != bb:
                for i, (x, y) in enumerate(zip(ba, bb)):
                    if x != y:
                        return False, f"First difference at byte offset {read + i}"
                return False, f"Files differ in length during read at offset {read}"
            read += len(ba)
            if not ba:
                break
            if progress_cb:
                progress_cb(read, size_a)
    return True, "Files are identical (byte-for-byte)"


def compare_partial(path_a, path_b, part="first"):
    """Compare first or last 1 MB."""
    sz_a = os.path.getsize(path_a)
    sz_b = os.path.getsize(path_b)
    limit = MB
    with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
        if part == "first":
            ba = fa.read(limit)
            bb = fb.read(limit)
            label = "First 1 MB"
        else:
            seek_a = max(0, sz_a - limit)
            seek_b = max(0, sz_b - limit)
            fa.seek(seek_a)
            fb.seek(seek_b)
            ba = fa.read(limit)
            bb = fb.read(limit)
            label = "Last 1 MB"
    equal = ba == bb
    detail = f"{label}: {'identical' if equal else 'DIFFERENT'}"
    if not equal:
        for i, (x, y) in enumerate(zip(ba, bb)):
            if x != y:
                detail += f" (first diff at relative byte {i})"
                break
    return equal, detail


def compare_checksum(path_a, path_b, progress_cb=None):
    h_a = sha256_file(path_a)
    h_b = sha256_file(path_b)
    equal = h_a == h_b
    detail = (
        f"SHA-256 match ✓\n  {h_a}"
        if equal
        else f"SHA-256 MISMATCH ✗\n  A: {h_a}\n  B: {h_b}"
    )
    return equal, detail


# ─────────────────────────────────────────────
# Large-file dialog
# ─────────────────────────────────────────────

class LargeFileDialog(tk.Toplevel):
    def __init__(self, parent, path_a, path_b, size):
        super().__init__(parent)
        self.title("Large File – Choose Compare Method")
        self.resizable(False, False)
        self.grab_set()
        self.result = None
        self.path_a = path_a
        self.path_b = path_b

        tk.Label(
            self,
            text=f"File size: {human_size(size)}\nChoose a comparison method:",
            padx=16, pady=10, justify="left"
        ).pack(anchor="w")

        btn_frame = tk.Frame(self, padx=16, pady=6)
        btn_frame.pack(fill="x")

        methods = [
            ("Check first 1 MB",         "first_mb"),
            ("Check last 1 MB",          "last_mb"),
            ("SHA-256 checksum",         "checksum"),
            ("Deep compare (full file)", "deep"),
        ]
        for label, key in methods:
            tk.Button(
                btn_frame, text=label, width=28,
                command=lambda k=key: self._pick(k)
            ).pack(pady=3)

        tk.Button(self, text="Cancel", command=self.destroy, padx=10).pack(pady=(0, 10))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _pick(self, key):
        self.result = key
        self.destroy()


# ─────────────────────────────────────────────
# Progress dialog
# ─────────────────────────────────────────────

class ProgressDialog(tk.Toplevel):
    def __init__(self, parent, title="Working…"):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self._label = tk.StringVar(value="Please wait…")
        tk.Label(self, textvariable=self._label, padx=20, pady=10).pack()
        self._bar = ttk.Progressbar(self, length=320, mode="determinate")
        self._bar.pack(padx=20, pady=(0, 16))

    def update_progress(self, done, total):
        pct = (done / total * 100) if total else 0
        self._bar["value"] = pct
        self._label.set(f"Compared {human_size(done)} / {human_size(total)}  ({pct:.1f}%)")
        self.update_idletasks()

    def close(self):
        self.grab_release()
        self.destroy()


# ─────────────────────────────────────────────
# Main application
# ─────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Dual-Folder File Comparator")
        self.geometry("1100x720")
        self.minsize(800, 520)
        self._matches = []          # list of (path_a, path_b, size)
        self._settings = load_settings()
        self._build_ui()
        self._apply_loaded_settings()

    # ── UI construction ──────────────────────

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Match.Treeview", rowheight=22, font=("Helvetica", 10))
        style.configure("Match.Treeview.Heading", font=("Helvetica", 10, "bold"))
        style.map("Match.Treeview", background=[("selected", "#3a7ebf")])

        # ── Folder selection rows ──
        top = tk.Frame(self, pady=8, padx=10)
        top.pack(fill="x")

        self._var_a = tk.StringVar()
        self._var_b = tk.StringVar()

        for row_idx, (label, var, cmd) in enumerate([
            ("Folder A:", self._var_a, self._browse_a),
            ("Folder B:", self._var_b, self._browse_b),
        ]):
            tk.Label(top, text=label, font=("Helvetica", 10, "bold")).grid(
                row=row_idx, column=0, sticky="w", padx=(0, 4), pady=2)
            tk.Entry(top, textvariable=var, width=80).grid(
                row=row_idx, column=1, sticky="ew", padx=2, pady=2)
            tk.Button(top, text="Browse…", command=cmd).grid(
                row=row_idx, column=2, padx=(4, 0), pady=2)

        top.columnconfigure(1, weight=1)

        # ── Extension filter row ──
        ext_row = tk.Frame(self, padx=10, pady=2)
        ext_row.pack(fill="x")

        tk.Label(
            ext_row,
            text="Extension filter:",
            font=("Helvetica", 10, "bold")
        ).pack(side="left")

        self._var_ext = tk.StringVar()
        ext_entry = tk.Entry(
            ext_row,
            textvariable=self._var_ext,
            width=12,
            font=("Helvetica", 10),
        )
        ext_entry.pack(side="left", padx=(4, 0))

        tk.Label(
            ext_row,
            text="(e.g. .edf  — leave blank to include all files)",
            fg="#666",
            font=("Helvetica", 9),
        ).pack(side="left", padx=(6, 0))

        # ── Scan button + status ──
        mid = tk.Frame(self, pady=6)
        mid.pack(fill="x", padx=10)
        self._scan_btn = tk.Button(
            mid, text="🔍  Scan for Size Matches",
            font=("Helvetica", 11, "bold"),
            bg="#2e7d32", fg="white", activebackground="#1b5e20",
            padx=12, pady=4, command=self._scan
        )
        self._scan_btn.pack(side="left")
        self._status = tk.StringVar(value="Select two folders and click Scan.")
        tk.Label(mid, textvariable=self._status, fg="#555").pack(side="left", padx=16)

        # ── Two-pane list area ──
        panes = tk.Frame(self, padx=10)
        panes.pack(fill="both", expand=True)
        panes.columnconfigure(0, weight=1)
        panes.columnconfigure(2, weight=1)

        self._tree_a = self._make_tree(panes, "Folder A – Matched Files", 0)
        tk.Frame(panes, width=6).grid(row=0, column=1, rowspan=2)  # spacer
        self._tree_b = self._make_tree(panes, "Folder B – Matched Files", 2)

        # Keep the two trees in sync on selection
        self._tree_a.bind("<<TreeviewSelect>>", lambda e: self._sync_select("a"))
        self._tree_b.bind("<<TreeviewSelect>>", lambda e: self._sync_select("b"))
        self._syncing = False

        # ── Bottom button bar ──
        bot = tk.Frame(self, pady=8, padx=10)
        bot.pack(fill="x")
        bot.columnconfigure(1, weight=1)

        self._del_a_btn = tk.Button(
            bot, text="🗑  Delete selected (A)",
            bg="#b71c1c", fg="white", activebackground="#7f0000",
            padx=8, pady=4,
            command=lambda: self._delete("a")
        )
        self._del_a_btn.grid(row=0, column=0, sticky="w")

        self._cmp_btn = tk.Button(
            bot, text="⚖  Compare Selected Pair",
            font=("Helvetica", 11, "bold"),
            bg="#1565c0", fg="white", activebackground="#0d47a1",
            padx=12, pady=4,
            command=self._compare
        )
        self._cmp_btn.grid(row=0, column=1)

        self._del_b_btn = tk.Button(
            bot, text="🗑  Delete selected (B)",
            bg="#b71c1c", fg="white", activebackground="#7f0000",
            padx=8, pady=4,
            command=lambda: self._delete("b")
        )
        self._del_b_btn.grid(row=0, column=2, sticky="e")

    def _make_tree(self, parent, heading, col):
        frame = tk.LabelFrame(parent, text=heading,
                              font=("Helvetica", 10, "bold"), padx=4, pady=4)
        frame.grid(row=0, column=col, sticky="nsew", pady=4)
        parent.rowconfigure(0, weight=1)

        cols = ("name", "size", "path")
        tree = ttk.Treeview(frame, columns=cols, show="headings",
                             selectmode="browse", style="Match.Treeview")
        tree.heading("name", text="File Name")
        tree.heading("size", text="Size")
        tree.heading("path", text="Full Path")
        tree.column("name", width=160, minwidth=100)
        tree.column("size", width=80,  minwidth=60, anchor="e")
        tree.column("path", width=260, minwidth=140)

        vsb = ttk.Scrollbar(frame, orient="vertical",   command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        # Alternating row colours
        tree.tag_configure("even", background="#f5f9ff")
        tree.tag_configure("odd",  background="#ffffff")
        return tree

    # ── Settings persistence ──────────────────

    def _apply_loaded_settings(self):
        self._var_a.set(self._settings.get("folder_a", ""))
        self._var_b.set(self._settings.get("folder_b", ""))
        self._var_ext.set(self._settings.get("extension", ".edf"))

    def _persist_settings(self):
        save_settings(
            folder_a=self._var_a.get().strip(),
            folder_b=self._var_b.get().strip(),
            extension=self._var_ext.get().strip(),
        )

    # ── Browse ────────────────────────────────

    def _browse_a(self):
        d = filedialog.askdirectory(title="Select Folder A")
        if d:
            self._var_a.set(d)

    def _browse_b(self):
        d = filedialog.askdirectory(title="Select Folder B")
        if d:
            self._var_b.set(d)

    # ── Scan ─────────────────────────────────

    def _scan(self):
        folder_a = self._var_a.get().strip()
        folder_b = self._var_b.get().strip()
        if not folder_a or not os.path.isdir(folder_a):
            messagebox.showerror("Error", "Please select a valid Folder A.")
            return
        if not folder_b or not os.path.isdir(folder_b):
            messagebox.showerror("Error", "Please select a valid Folder B.")
            return

        ext = self._var_ext.get().strip()

        # Persist settings before starting the scan
        self._persist_settings()

        self._status.set("Scanning…")
        self._scan_btn.config(state="disabled")
        self._clear_trees()

        def worker():
            try:
                files_a = collect_files(folder_a, ext_filter=ext)
                files_b = collect_files(folder_b, ext_filter=ext)
                matches = find_size_matches(files_a, files_b)
                # Sort by size desc, then name
                matches.sort(key=lambda x: (-x[2], os.path.basename(x[0]).lower()))
                self._matches = matches
                self.after(0, self._populate_trees)
            except Exception as exc:
                self.after(0, lambda: self._scan_error(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_error(self, exc):
        self._status.set(f"Scan error: {exc}")
        self._scan_btn.config(state="normal")
        messagebox.showerror("Scan Error", str(exc))

    def _clear_trees(self):
        for t in (self._tree_a, self._tree_b):
            t.delete(*t.get_children())

    def _populate_trees(self):
        self._clear_trees()
        for i, (pa, pb, sz) in enumerate(self._matches):
            tag = "even" if i % 2 == 0 else "odd"
            iid = str(i)
            self._tree_a.insert("", "end", iid=iid,
                                 values=(os.path.basename(pa), human_size(sz), pa), tags=(tag,))
            self._tree_b.insert("", "end", iid=iid,
                                 values=(os.path.basename(pb), human_size(sz), pb), tags=(tag,))
        n = len(self._matches)
        ext = self._var_ext.get().strip()
        ext_note = f" [{ext}]" if ext else " [all files]"
        self._status.set(
            f"Found {n} size-matched pair{'s' if n != 1 else ''}{ext_note}."
            if n else f"No size-matched files found{ext_note}."
        )
        self._scan_btn.config(state="normal")

    # ── Sync selection ────────────────────────

    def _sync_select(self, source):
        if self._syncing:
            return
        self._syncing = True
        src = self._tree_a if source == "a" else self._tree_b
        dst = self._tree_b if source == "a" else self._tree_a
        sel = src.selection()
        if sel:
            dst.selection_set(sel)
            dst.see(sel[0])
        self._syncing = False

    # ── Compare ───────────────────────────────

    def _get_selected_pair(self):
        sel = self._tree_a.selection()
        if not sel:
            messagebox.showinfo("Nothing selected", "Please select a pair from the lists.")
            return None, None, None
        idx = int(sel[0])
        pa, pb, sz = self._matches[idx]
        return pa, pb, sz

    def _compare(self):
        pa, pb, sz = self._get_selected_pair()
        if pa is None:
            return

        if sz <= MB:
            self._run_compare_task("deep", pa, pb, sz)
        else:
            dlg = LargeFileDialog(self, pa, pb, sz)
            if dlg.result:
                self._run_compare_task(dlg.result, pa, pb, sz)

    def _run_compare_task(self, method, pa, pb, sz):
        prog = None
        if method == "deep" and sz > MB:
            prog = ProgressDialog(self, "Deep Compare")

        def worker():
            try:
                if method == "first_mb":
                    equal, detail = compare_partial(pa, pb, "first")
                elif method == "last_mb":
                    equal, detail = compare_partial(pa, pb, "last")
                elif method == "checksum":
                    equal, detail = compare_checksum(pa, pb)
                else:  # deep / full
                    cb = prog.update_progress if prog else None
                    equal, detail = compare_bytes_full(pa, pb, progress_cb=cb)
            except Exception as exc:
                equal, detail = False, f"Error: {exc}"
            finally:
                # Always close the progress dialog even if an unexpected error occurs
                if prog:
                    try:
                        self.after(0, prog.close)
                    except Exception:
                        pass
            self.after(0, lambda: self._show_result(equal, detail, pa, pb, None))

        threading.Thread(target=worker, daemon=True).start()

    def _show_result(self, equal, detail, pa, pb, prog):
        # prog is passed for legacy compatibility but is always closed by the worker
        if prog:
            try:
                prog.close()
            except Exception:
                pass
        icon = "✅  IDENTICAL" if equal else "❌  DIFFERENT"
        title = "Comparison Result"
        msg = (
            f"{icon}\n\n"
            f"A: {pa}\n"
            f"B: {pb}\n\n"
            f"{detail}"
        )
        if equal:
            messagebox.showinfo(title, msg)
        else:
            messagebox.showwarning(title, msg)

    # ── Delete ────────────────────────────────

    def _delete(self, side):
        pa, pb, sz = self._get_selected_pair()
        if pa is None:
            return
        path = pa if side == "a" else pb
        ans = messagebox.askyesno(
            "Confirm Deletion",
            f"Permanently delete this file?\n\n{path}",
            icon="warning"
        )
        if not ans:
            return
        try:
            os.remove(path)
        except OSError as e:
            messagebox.showerror("Delete Failed", str(e))
            return

        # Remove the pair from the list and refresh
        sel = self._tree_a.selection()
        if sel:
            idx = int(sel[0])
            del self._matches[idx]
            self._populate_trees()
        self._status.set(f"Deleted: {os.path.basename(path)}")


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
