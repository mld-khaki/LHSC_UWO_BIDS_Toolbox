import os
import re
import sys
import csv
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime
from collections import defaultdict

# Optional: pandas is used for "Check Durations" only
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except Exception:
    PANDAS_AVAILABLE = False

# ---- EDF reader (user-provided) ----
# Expecting _lhsc_lib.EDF_reader_mld import path to be resolvable from current working directory
# We append a relative hint based on this script's location (two levels up).
current_script_dir = os.path.dirname(os.path.abspath(__file__))
two_levels_up_path = os.path.abspath(os.path.join(current_script_dir, '..', '..'))
EDF_AVAILABLE = True
sys.path.append(two_levels_up_path)
from _lhsc_lib.EDF_reader_mld import EDFreader


def iso_fmt_T(dt):
    """Return ISO-8601 string with 'T' separator."""
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    return str(dt)


def todays_log_path(root_dir):
    return os.path.join(root_dir, f"BIDS_Shifter_log_{datetime.now().strftime('%Y-%m-%d')}.txt")


def log_line(log_path, msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    if log_path:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


class BIDSShifterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("BIDS Session Shifter & TSV Tools")
        self.root.geometry("1300x800")

        self.root_dir = ""          # subject root (sub-###)
        self.tsv_path = ""          # sub-###_scans.tsv
        self.tsv_header = []        # list of column names
        self.tsv_rows = []          # list of dict rows with keys from header
        self.original_rows = []     # deep copy for comparison
        self.dry_run = tk.BooleanVar(value=True)
        self.sort_sessions = tk.BooleanVar(value=False)

        self.log_path = None

        # UI
        self._build_ui()

    # ---------- UI BUILD ----------
    def _build_ui(self):
        top = tk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=6)

        tk.Button(top, text="Select Subject Root (sub-###)", command=self.select_root).pack(side="left", padx=4)
        tk.Button(top, text="Load TSV", command=self.load_tsv_dialog).pack(side="left", padx=4)
        tk.Button(top, text="Refresh Folder", command=self.refresh_folder).pack(side="left", padx=4)
        tk.Button(top, text="Refresh TSV", command=self.refresh_tsv).pack(side="left", padx=4)
        tk.Button(top, text="Generate TSV (from EDFs)", command=self.generate_tsv_from_edfs).pack(side="left", padx=4)
        tk.Button(top, text="Check TSV vs Folders", command=self.check_tsv_vs_folders).pack(side="left", padx=10)
        tk.Button(top, text="Check Durations", command=self.check_durations).pack(side="left", padx=4)
        tk.Button(top, text="Find Duplicates", command=self.find_duplicates).pack(side="left", padx=4)
        tk.Button(top, text="Normalize Sessions to 1..N", command=self.normalize_sessions_to_sequence).pack(side="left", padx=4)



        tk.Checkbutton(top, text="Dry Run", variable=self.dry_run).pack(side="right", padx=4)
        tk.Checkbutton(top, text="Sort by Session #", variable=self.sort_sessions, command=self.refresh_table).pack(side="right", padx=4)

        # Range shift controls
        shift = tk.Frame(self.root)
        shift.pack(fill="x", padx=8, pady=4)
        tk.Label(shift, text="Shift range  ses-").pack(side="left")
        self.ent_start = tk.Entry(shift, width=5)
        self.ent_start.pack(side="left"); tk.Label(shift, text=" to ").pack(side="left")
        self.ent_end = tk.Entry(shift, width=5)
        self.ent_end.pack(side="left")
        tk.Label(shift, text="  by ").pack(side="left")
        self.ent_delta = tk.Entry(shift, width=5)
        self.ent_delta.insert(0, "1")
        self.ent_delta.pack(side="left")
        tk.Button(shift, text="Shift", command=self.shift_range).pack(side="left", padx=6)
        tk.Button(shift, text="Apply Changes", command=self.apply_changes).pack(side="right", padx=6)
        tk.Button(shift, text="Move Session Up", command=self.move_session_up).pack(side="left", padx=6)
        tk.Button(shift, text="Move Session Down", command=self.move_session_down).pack(side="left", padx=6)

        # Table
        self.tree = ttk.Treeview(self.root, columns=("Folder","Filename","Acq Time","Duration (h)","EDF Type"), show="headings")
        for col, w in [("Folder",120),("Filename",520),("Acq Time",200),("Duration (h)",120),("EDF Type",100)]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=6)

        # color tags
        self.tree.tag_configure("changed", foreground="red")           # user-shifted rows
        self.tree.tag_configure("missing_folder", background="red", foreground="white")  # TSV references missing folder
        self.tree.tag_configure("extra_folder", background="orange", foreground="black") # folder exists not in TSV
        self.tree.tag_configure("good_day", background="#c3f7c3")      # green
        self.tree.tag_configure("warn_day", background="#ffd59c")      # orange
        self.tree.tag_configure("err_day", background="#ff9c9c")       # red
        self.tree.tag_configure("multi_day", background="#b3ccff")     # blue
        self.tree.tag_configure("dup_row", background="#e5b3e6", foreground="black")  # purple for duplicates


        # auto-resize on Configure
        self.tree.bind("<Configure>", self.auto_resize_columns)

    # ---------- HELPERS ----------
    def _sessions_in_view_order(self):
        """
        Return unique session IDs (e.g., 'ses-110') in the exact order
        they currently appear in the Treeview (i.e., the user's current sort).
        """
        seen = set()
        ordered = []
        for iid in self.tree.get_children(""):
            s = self.tree.set(iid, "Folder")
            if s and s not in seen:
                seen.add(s)
                ordered.append(s)
        return ordered
    
    def _ordered_unique_sessions(self):
        """Return unique session folders (e.g., 'ses-110') present in TSV, sorted by number."""
        ses = []
        seen = set()
        for row in self.tsv_rows:
            fn = row.get("filename", "")
            s = self.current_session_from_filename(fn)
            if s and s not in seen:
                seen.add(s)
                ses.append(s)
        # sort by numeric part
        def keyfn(x):
            try:
                return int(x.split("-")[1])
            except Exception:
                return 0
        ses.sort(key=keyfn)
        return ses

    def _swap_session_numbers_in_rows(self, ses_a, ses_b):
        """
        Swap ses-XXX tokens in-memory across TSV rows (collision-safe via temp token).
        Example: swap 'ses-110' with 'ses-111' in all filenames.
        """
        if not ses_a or not ses_b or ses_a == ses_b:
            return
        tmp = "__SES_SWAP_TMP__"

        # pass 1: a -> tmp
        for row in self.tsv_rows:
            fn = row.get("filename", "")
            if ses_a in fn:
                row["filename"] = fn.replace(ses_a, tmp)

        # pass 2: b -> a
        for row in self.tsv_rows:
            fn = row.get("filename", "")
            if ses_b in fn:
                row["filename"] = fn.replace(ses_b, ses_a)

        # pass 3: tmp -> b
        for row in self.tsv_rows:
            fn = row.get("filename", "")
            if tmp in fn:
                row["filename"] = fn.replace(tmp, ses_b)

        log_line(self.log_path, f"Swapped sessions in preview: {ses_a} <-> {ses_b}")

    def select_root(self):
        path = filedialog.askdirectory(title="Select sub-### root folder")
        if not path:
            return
        self.root_dir = path
        self.log_path = todays_log_path(self.root_dir)
        log_line(self.log_path, f"Selected root: {self.root_dir}")

        # Default TSV path derived from folder name
        base = os.path.basename(os.path.normpath(self.root_dir))
        guess = os.path.join(self.root_dir, f"{base}_scans.tsv")
        if os.path.exists(guess):
            self.tsv_path = guess
            self.load_tsv(self.tsv_path)
        else:
            self.tsv_path = guess
            self.tsv_header = []
            self.tsv_rows = []
            self.original_rows = []
            self.refresh_table()

    def load_tsv_dialog(self):
        path = filedialog.askopenfilename(title="Select sub-###_scans.tsv", filetypes=[("TSV files","*.tsv")])
        if not path:
            return
        self.tsv_path = path
        self.load_tsv(self.tsv_path)

    def load_tsv(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                self.tsv_header = reader.fieldnames if reader.fieldnames else []
                self.tsv_rows = [row for row in reader]
                self.original_rows = [dict(r) for r in self.tsv_rows]
            log_line(self.log_path, f"Loaded TSV: {path}")
            self.refresh_table()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load TSV:\n{e}")

    def refresh_tsv(self):
        if not self.tsv_path:
            messagebox.showinfo("Info","No TSV selected.")
            return
        self.load_tsv(self.tsv_path)

    def refresh_folder(self):
        if not self.root_dir:
            messagebox.showinfo("Info","No root folder selected.")
            return
        self.refresh_table()

    def current_session_from_filename(self, filename_value):
        # filename value like "ses-110/ieeg/sub-xxx_ses-110_....edf"
        try:
            seg = filename_value.split("/")[0]
            if seg.startswith("ses-") and len(seg) == 7 and seg[4:].isdigit():
                return seg
        except Exception:
            pass
        return ""

    def get_tree_rows(self):
        rows = []
        for r in self.tsv_rows:
            fn = r.get("filename","")
            acq = r.get("acq_time","")
            dur = r.get("duration","")
            edt = r.get("edf_type","")
            folder = self.current_session_from_filename(fn)
            base = os.path.basename(fn)
            tags = set()
            orig = self.original_rows[self.tsv_rows.index(r)] if self.original_rows and len(self.original_rows)==len(self.tsv_rows) else None
            if orig and orig.get("filename","") != fn:
                tags.add("changed")
            rows.append( (folder, base, acq, str(dur), edt, tags) )
        return rows

    def refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        rows = self.get_tree_rows()
        if self.sort_sessions.get():
            def sess_key(row):
                f = row[0]
                try:
                    return int(f.split("-")[1])
                except Exception:
                    return 0
            rows.sort(key=sess_key)
        for row in rows:
            tags = tuple(row[5]) if row[5] else ()
            self.tree.insert("", "end", values=row[:5], tags=tags)

    def auto_resize_columns(self, event):
        total = event.width
        widths = [0.12, 0.48, 0.2, 0.12, 0.08]  # sum=1.0
        for (col, frac) in zip(("Folder","Filename","Acq Time","Duration (h)","EDF Type"), widths):
            self.tree.column(col, width=int(total*frac))

    # ---------- SHIFT RANGE ----------
    def normalize_sessions_to_sequence(self):
        """
        Renumber all sessions to ses-001..ses-N according to the *current table order*.
        This updates TSV rows in-memory (preview). Use 'Apply Changes' to commit to disk.
        """
        if not self.tsv_rows:
            messagebox.showinfo("Info", "Load a TSV first.")
            return

        # Build ordered sessions based on what the user currently sees
        view_sessions = self._sessions_in_view_order()
        if not view_sessions:
            messagebox.showinfo("Info", "No sessions found in the current view.")
            return

        # Map current -> target ses-001..ses-N
        target_map = {}
        for idx, ses in enumerate(view_sessions, start=1):
            target_map[ses] = f"ses-{idx:03d}"

        # If nothing would change, bail early
        if all(k == v for k, v in target_map.items()):
            messagebox.showinfo("Info", "Sessions are already normalized to 1..N.")
            return

        # Preview
        preview_lines = [f"{old} -> {new}" for old, new in target_map.items() if old != new]
        if not messagebox.askyesno("Confirm Normalize",
                                   "This will remap sessions in preview (TSV only) to:\n\n"
                                   + "\n".join(preview_lines)
                                   + "\n\nProceed?"):
            return

        # Log start
        if not self.log_path:
            self.log_path = todays_log_path(self.root_dir)
        log_line(self.log_path, "===== NORMALIZE (preview) START =====")
        for old, new in target_map.items():
            if old != new:
                log_line(self.log_path, f"Map: {old} -> {new}")

        # Perform in-memory remap using ORIGINAL rows as source,
        # so detection is stable and collision-free
        for i, (orig, cur) in enumerate(zip(self.original_rows, self.tsv_rows)):
            orig_fn = orig.get("filename", "")
            old_ses = self.current_session_from_filename(orig_fn)
            if not old_ses:
                continue
            new_ses = target_map.get(old_ses)
            if not new_ses or new_ses == old_ses:
                continue
            # Replace only occurrences of the *old* session token
            cur["filename"] = orig_fn.replace(old_ses, new_ses)

        log_line(self.log_path, "===== NORMALIZE (preview) END =====")

        # Refresh the table to show the new numbering (in preview)
        self.refresh_table()
        messagebox.showinfo("Normalize", "Sessions renumbered in preview to 1..N.\nUse 'Apply Changes' to commit.")
    
    def _selected_session_from_tree(self):
        """Get the session (Folder column) from the first selected row in the tree."""
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.set(sel[0], "Folder") or None

    def move_session_up(self):
        """Swap the selected session with the previous session (by number) in preview."""
        cur = self._selected_session_from_tree()
        if not cur:
            messagebox.showinfo("Info", "Select a row belonging to the session you want to move up.")
            return
        sessions = self._ordered_unique_sessions()
        if cur not in sessions:
            messagebox.showinfo("Info", f"{cur} not found among TSV sessions.")
            return
        idx = sessions.index(cur)
        if idx == 0:
            messagebox.showinfo("Info", f"{cur} is already the first session.")
            return
        prev_ses = sessions[idx - 1]
        self._swap_session_numbers_in_rows(cur, prev_ses)
        self.refresh_table()

    def move_session_down(self):
        """Swap the selected session with the next session (by number) in preview."""
        cur = self._selected_session_from_tree()
        if not cur:
            messagebox.showinfo("Info", "Select a row belonging to the session you want to move down.")
            return
        sessions = self._ordered_unique_sessions()
        if cur not in sessions:
            messagebox.showinfo("Info", f"{cur} not found among TSV sessions.")
            return
        idx = sessions.index(cur)
        if idx == len(sessions) - 1:
            messagebox.showinfo("Info", f"{cur} is already the last session.")
            return
        next_ses = sessions[idx + 1]
        self._swap_session_numbers_in_rows(cur, next_ses)
        self.refresh_table()
    
    def shift_range(self):
        if not self.tsv_rows:
            messagebox.showinfo("Info","Load a TSV first.")
            return
        try:
            start = int(self.ent_start.get())
            end = int(self.ent_end.get())
            delta = int(self.ent_delta.get())
        except Exception:
            messagebox.showerror("Error","Enter valid integers for start, end, and shift.")
            return
        if start > end:
            messagebox.showerror("Error","Start must be <= end.")
            return

        for row in self.tsv_rows:
            fn = row.get("filename","")
            folder = self.current_session_from_filename(fn)
            if not folder:
                continue
            try:
                num = int(folder.split("-")[1])
            except Exception:
                continue
            if start <= num <= end:
                new_num = num + delta
                new_folder = f"ses-{new_num:03d}"
                row["filename"] = fn.replace(folder, new_folder)

        log_line(self.log_path, f"Shifted sessions {start}-{end} by {delta} (in preview).")
        self.refresh_table()

    # ---------- APPLY CHANGES ----------
    def apply_changes(self):
        if not self.tsv_rows or not self.root_dir or not self.tsv_path:
            messagebox.showinfo("Info","Need root folder and TSV loaded first.")
            return

        old_to_new = {}
        for orig, new in zip(self.original_rows, self.tsv_rows):
            ofn = orig.get("filename","")
            nfn = new.get("filename","")
            of = self.current_session_from_filename(ofn)
            nf = self.current_session_from_filename(nfn)
            if of and nf and of != nf:
                old_to_new[of] = nf

        if not old_to_new:
            messagebox.showinfo("Info","No changes to apply.")
            return

        s_preview = "\n".join([f"{k}  ->  {v}" for k,v in sorted(old_to_new.items(), key=lambda kv: int(kv[0].split('-')[1]))])
        if not messagebox.askyesno("Confirm", f"About to apply the following folder renames and TSV update:\n\n{s_preview}\n\nProceed?"):
            return

        if not self.log_path:
            self.log_path = todays_log_path(self.root_dir)
        log_line(self.log_path, "===== APPLY START =====")

        ts_bak = datetime.now().strftime("%Y_%m_%d__%H_%M_%S")
        tsv_backup = f"{os.path.splitext(self.tsv_path)[0]}_backup_{ts_bak}.tsv"
        try:
            shutil.copy2(self.tsv_path, tsv_backup)
            log_line(self.log_path, f"Backup TSV: {tsv_backup}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to backup TSV:\n{e}")
            log_line(self.log_path, f"ERROR backing up TSV: {e}")
            return

        temp_prefix = "__tmp__"
        try:
            if not self.dry_run.get():
                temp_map = {}
                for old, new in old_to_new.items():
                    old_path = os.path.join(self.root_dir, old)
                    if not os.path.isdir(old_path):
                        log_line(self.log_path, f"WARNING: folder not found: {old_path}")
                        continue
                    temp_name = f"{temp_prefix}{new}"
                    temp_path = os.path.join(self.root_dir, temp_name)
                    idx = 0
                    base_temp = temp_path
                    while os.path.exists(temp_path):
                        idx += 1
                        temp_path = base_temp + f"_{idx}"
                    os.rename(old_path, temp_path)
                    log_line(self.log_path, f"RENAMED (temp): {old} -> {os.path.basename(temp_path)}")
                    temp_map[temp_path] = new

                for temp_path, final_folder in temp_map.items():
                    for r, dlist, flist in os.walk(temp_path):
                        for fn in flist:
                            m = re.search(r"ses-(\d{3})", fn)
                            if m:
                                final_num = final_folder.split("-")[1]
                                new_fn = re.sub(r"ses-\d{3}", f"ses-{final_num}", fn)
                                if new_fn != fn:
                                    os.rename(os.path.join(r, fn), os.path.join(r, new_fn))
                                    log_line(self.log_path, f"RENAMED FILE: {fn} -> {new_fn}")
                    final_path = os.path.join(self.root_dir, final_folder)
                    if os.path.exists(final_path):
                        log_line(self.log_path, f"WARNING: final folder exists, choosing suffix: {final_folder}")
                        idx = 1
                        base = final_path
                        while os.path.exists(final_path):
                            final_path = base + f"_{idx}"
                            idx += 1
                        final_folder = os.path.basename(final_path)
                    os.rename(temp_path, final_path)
                    log_line(self.log_path, f"RENAMED (final): {os.path.basename(temp_path)} -> {final_folder}")
            else:
                log_line(self.log_path, "DRY RUN: Skipping filesystem renames.")
                for old, new in old_to_new.items():
                    log_line(self.log_path, f"[DRY] Would rename {old} -> {new}")
        except Exception as e:
            messagebox.showerror("Error", f"Filesystem rename error:\n{e}")
            log_line(self.log_path, f"ERROR filesystem rename: {e}")
            return

        try:
            if not self.dry_run.get():
                with open(self.tsv_path, "w", encoding="utf-8", newline="") as f:
                    header = self.tsv_header if self.tsv_header else ["filename","acq_time","duration","edf_type"]
                    writer = csv.DictWriter(f, fieldnames=header, delimiter="\t", lineterminator="\n", extrasaction="ignore")
                    writer.writeheader()
                    for row in self.tsv_rows:
                        writer.writerow(row)
                log_line(self.log_path, f"TSV updated: {self.tsv_path}")
            else:
                log_line(self.log_path, "DRY RUN: Skipping TSV write.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to write TSV:\n{e}")
            log_line(self.log_path, f"ERROR writing TSV: {e}")
            return

        log_line(self.log_path, "===== APPLY END =====")
        messagebox.showinfo("Done", "Dry run complete." if self.dry_run.get() else "Apply complete.")
        self.original_rows = [dict(r) for r in self.tsv_rows]
        self.refresh_table()

    # ---------- CHECK TSV vs FOLDERS ----------
    def check_tsv_vs_folders(self):
        if not self.root_dir:
            messagebox.showinfo("Info","Select a subject root first.")
            return
        tsv_sessions = set()
        for r in self.tsv_rows:
            f = r.get("filename","")
            sess = self.current_session_from_filename(f)
            if sess:
                tsv_sessions.add(sess)

        folder_sessions = set()
        for r, d, f in os.walk(self.root_dir):
            for dd in d:
                if re.fullmatch(r"ses-\d{3}", dd):
                    folder_sessions.add(dd)

        missing = sorted(tsv_sessions - folder_sessions, key=lambda s: int(s.split('-')[1])) if tsv_sessions else []
        extra   = sorted(folder_sessions - tsv_sessions, key=lambda s: int(s.split('-')[1]))
        log_line(self.log_path, f"TSV vs Folders — Missing folders: {len(missing)}, Extra folders: {len(extra)}")

        self.refresh_table()
        item_ids = self.tree.get_children("")
        for iid in item_ids:
            folder_val = self.tree.set(iid, "Folder")
            if folder_val in missing:
                self.tree.item(iid, tags=("missing_folder",) + self.tree.item(iid, "tags"))
        for ex in extra:
            self.tree.insert("", "end", values=(ex, "N/A", "N/A", "N/A", "N/A"), tags=("extra_folder",))

        msg = f"Missing in folders: {len(missing)}\nMissing in TSV: {len(extra)}"
        messagebox.showinfo("Check TSV vs Folders", msg)

    # ---------- CHECK DURATIONS (PANDAS) ----------
    def check_durations(self):
        if not self.tsv_path:
            messagebox.showinfo("Info","Load a TSV file first.")
            return
        if not PANDAS_AVAILABLE:
            messagebox.showerror("Error","pandas is not installed. Install pandas to use duration checks.")
            return

        try:
            df = pd.read_csv(self.tsv_path, sep="\t")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read TSV with pandas:\n{e}")
            return

        if "acq_time" not in df.columns or "duration" not in df.columns or "filename" not in df.columns:
            messagebox.showerror("Error","TSV must include 'filename', 'acq_time', 'duration' columns.")
            return

        try:
            df["acq_time"] = pd.to_datetime(df["acq_time"])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse acq_time as datetime:\n{e}")
            return

        df["date"] = df["acq_time"].dt.date
        try:
            df["duration"] = df["duration"].astype(float)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse duration as float (hours):\n{e}")
            return

        filenames_by_date = df.groupby("date")["filename"].apply(list)
        session_counts = df.groupby("date")["filename"].count()
        daily_durations = df.groupby("date")["duration"].sum()

        if daily_durations.empty:
            messagebox.showinfo("Info","No rows to evaluate.")
            return

        first_day, last_day = daily_durations.index[0], daily_durations.index[-1]
        full_date_range = pd.date_range(start=first_day, end=last_day).date

        log_line(self.log_path, f"===== DURATION CHECK START ({self.tsv_path}) =====")
        log_line(self.log_path, f"Checking data from {first_day} to {last_day}...")

        missing_dates = set(full_date_range) - set(daily_durations.index)
        if missing_dates:
            log_line(self.log_path, "ERROR: The following dates are completely missing:")
            for missing in sorted(missing_dates):
                log_line(self.log_path, f"  - {missing}")
        else:
            log_line(self.log_path, "Perfect! No missing days found!")

        multiple_sessions = session_counts[session_counts > 1]
        if not multiple_sessions.empty:
            log_line(self.log_path, "INFO: Days with multiple sessions recorded:")
            for dtv, cnt in multiple_sessions.items():
                log_line(self.log_path, f"  - {dtv}: {cnt} sessions")
                log_line(self.log_path, f"    Files: {', '.join(filenames_by_date[dtv])}")

        day_status = {}
        for date in full_date_range:
            if date in daily_durations:
                total = daily_durations[date]
                if date == first_day or date == last_day:
                    if total < 23:
                        day_status[date] = "warn_day"
                        log_line(self.log_path, f"WARNING: First/Last day {date} has only {total:.2f} hours recorded.")
                        if date in filenames_by_date:
                            log_line(self.log_path, f"    Files: {', '.join(filenames_by_date[date])}")
                else:
                    if total >= 23:
                        day_status[date] = "good_day"
                        log_line(self.log_path, f"All good for Day {date}!!!")
                        if date in filenames_by_date:
                            log_line(self.log_path, f"    Files: {', '.join(filenames_by_date[date])}")
                    else:
                        day_status[date] = "err_day"
                        log_line(self.log_path, f"ERROR: Day {date} has only {total:.2f} hours recorded.")
                        if date in filenames_by_date:
                            log_line(self.log_path, f"    Files: {', '.join(filenames_by_date[date])}")
            else:
                pass

        self.refresh_table()
        multi_dates = set(multiple_sessions.index) if not multiple_sessions.empty else set()
        for iid in self.tree.get_children(""):
            acq = self.tree.set(iid, "Acq Time")
            try:
                dtv = datetime.strptime(acq, "%Y-%m-%d %H:%M:%S").date()
            except Exception:
                continue
            tags = list(self.tree.item(iid, "tags"))
            if dtv in day_status:
                tags.append(day_status[dtv])
            if dtv in multi_dates:
                tags.append("multi_day")
            self.tree.item(iid, tags=tuple(set(tags)))

        log_line(self.log_path, f"Check completed. There are a total of {len(full_date_range)} days in the dataset.")
        log_line(self.log_path, "===== DURATION CHECK END =====")
        messagebox.showinfo("Duration Check", "Completed. See table colors and log for details.")
        
    def find_duplicates(self):
        """
        Detect duplicates where (date extracted from acq_time, duration) are the same.
        - Date is acq_time split at 'T' (or space) -> YYYY-MM-DD
        - Duration is compared at 3 decimal places (to match your TSV generation)
        Highlights duplicate rows in the table (purple) and logs a summary.
        """
        if not self.tsv_rows:
            messagebox.showinfo("Info", "Load a TSV first.")
            return

        # Build groups by (date, duration_3dp)
        from collections import defaultdict
        groups = defaultdict(list)  # key -> list of row dicts

        def normalize_date(acq_time):
            if not acq_time:
                return ""
            # accept "YYYY-MM-DDTHH:MM:SS" or "YYYY-MM-DD HH:MM:SS"
            if "T" in acq_time:
                return acq_time.split("T", 1)[0]
            return acq_time.split(" ", 1)[0]

        for row in self.tsv_rows:
            acq = row.get("acq_time", "")
            dur_s = row.get("duration", "")
            date_part = normalize_date(acq)
            try:
                # compare using 3 decimal places to match your generator
                dur_key = f"{float(dur_s):.3f}"
            except Exception:
                dur_key = dur_s.strip()  # fall back to raw string if not float
            key = (date_part, dur_key)
            groups[key].append(row)

        # Extract only keys with duplicates
        dup_map = {k: v for k, v in groups.items() if len(v) > 1}

        # Refresh table so we tag the current view
        self.refresh_table()

        if not dup_map:
            messagebox.showinfo("Find Duplicates", "No duplicates found for (date, duration).")
            log_line(self.log_path, "Duplicate check: none found.")
            return

        # Tag duplicates in the tree (match by Acq Time date + Duration)
        # We'll compare using displayed values: date from "Acq Time", duration from "Duration (h)"
        tagged_count = 0
        tree_items = self.tree.get_children("")
        for iid in tree_items:
            acq_display = self.tree.set(iid, "Acq Time")  # e.g., "2025-03-11 07:58:18" or "2025-03-11T07:58:18"
            # normalize to date
            date_disp = acq_display.split("T", 1)[0].split(" ", 1)[0] if acq_display else ""
            dur_display = self.tree.set(iid, "Duration (h)")  # e.g., "22.727"
            try:
                dur_disp_key = f"{float(dur_display):.3f}"
            except Exception:
                dur_disp_key = dur_display.strip()
            if (date_disp, dur_disp_key) in dup_map:
                # add duplicate tag
                cur_tags = set(self.tree.item(iid, "tags"))
                cur_tags.add("dup_row")
                self.tree.item(iid, tags=tuple(cur_tags))
                tagged_count += 1

        # Build and show summary; also log filenames for each dup key
        lines = [f"Found {len(dup_map)} duplicate (date, duration) groups; tagged {tagged_count} rows."]
        for (d, dur), rows in sorted(dup_map.items()):
            files = [r.get("filename", "") for r in rows]
            lines.append(f"- {d} | {dur} h  -> {len(rows)} rows")
            for f in files:
                lines.append(f"    {f}")

        summary = "\n".join(lines)
        messagebox.showinfo("Find Duplicates (date, duration)", summary)
        log_line(self.log_path, "Duplicate check summary:\n" + summary)
        

    # ---------- GENERATE TSV FROM EDFs (UPDATED FORMAT) ----------
    def generate_tsv_from_edfs(self):
        """
        Generate TSV exactly like:
        filename\tacq_time\tduration\tedf_type
        ses-005/ieeg/sub-167_ses-005_task-full_run-01_ieeg.edf\t2025-03-11T07:58:18\t22.727\tEDF+C
        ...
        """
        if not EDF_AVAILABLE:
            messagebox.showerror("Error","EDFreader not available. Ensure _lhsc_lib.EDF_reader_mld.EDFreader is importable.")
            return
        if not self.root_dir:
            messagebox.showinfo("Info","Select a subject root first.")
            return

        base = os.path.basename(os.path.normpath(self.root_dir))
        out_path = os.path.join(self.root_dir, f"{base}_scans.tsv")

        # Backup if exists
        if os.path.exists(out_path):
            ts = datetime.now().strftime("%Y_%m_%d__%H_%M_%S")
            bak = os.path.join(self.root_dir, f"{base}_scans_backup_{ts}.tsv")
            try:
                shutil.copy2(out_path, bak)
                log_line(self.log_path, f"Backup TSV created: {bak}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to backup existing TSV:\n{e}")
                log_line(self.log_path, f"ERROR backing up existing TSV: {e}")
                return

        records = []
        # Scan recursively for .edf
        for r, d, f in os.walk(self.root_dir):
            for fn in f:
                if fn.lower().endswith(".edf"):
                    full = os.path.join(r, fn)
                    rel = os.path.relpath(full, self.root_dir).replace("\\","/")
                    try:
                        reader = EDFreader(full, read_annotations=False)
                        start_dt = reader.getStartDateTime()
                        dur_sec = reader.getFileDuration()
                        reader.close()
                        acq_time = iso_fmt_T(start_dt)            # with 'T'
                        dur_hours = float(dur_sec) / (3600.0*1e7)
                        # EXACT output format requirements:
                        records.append( (rel, acq_time, f"{dur_hours:.3f}", "EDF+C") )
                    except Exception as e:
                        log_line(self.log_path, f"ERROR reading EDF {full}: {e}")

        # Sort by acq_time text (ISO 8601 sortable)
        records.sort(key=lambda t: t[1])

        # Write TSV with the exact columns and header
        try:
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter="\t", lineterminator="\n")
                writer.writerow(["filename","acq_time","duration","edf_type"])
                for rec in records:
                    writer.writerow(list(rec))
            log_line(self.log_path, f"Generated TSV: {out_path}")
            messagebox.showinfo("Generate TSV", f"Generated TSV at:\n{out_path}\n(Use Refresh TSV to load it.)")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to write TSV:\n{e}")
            log_line(self.log_path, f"ERROR writing generated TSV: {e}")


# ---------- main ----------
if __name__ == "__main__":
    root = tk.Tk()
    app = BIDSShifterGUI(root)
    root.mainloop()
