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
# We append a relative hint (as you shared), but you can adjust/remove if your environment differs.
# Get the absolute path of the directory containing the current script
current_script_dir = os.path.dirname(os.path.abspath(__file__))

# Construct the path to the directory two levels up
# '..' represents one level up, so '../../' represents two levels up
two_levels_up_path = os.path.abspath(os.path.join(current_script_dir, '..', '..'))
EDF_AVAILABLE = True

# Add this path to sys.path
sys.path.append(two_levels_up_path)
from _lhsc_lib.EDF_reader_mld import EDFreader


def iso_fmt(dt):
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
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

        # auto-resize on Configure
        self.tree.bind("<Configure>", self.auto_resize_columns)

    # ---------- HELPERS ----------
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
        # Does not touch TSV; just re-tags extras/missing if desired by re-running the check
        if not self.root_dir:
            messagebox.showinfo("Info","No root folder selected.")
            return
        # No action needed here beyond maybe refreshing the view
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
        """
        Convert self.tsv_rows into rows for the Treeview.
        A row is a tuple: (folder, base_filename, acq_time, duration, edf_type, tags_set)
        """
        rows = []
        for r in self.tsv_rows:
            fn = r.get("filename","")
            acq = r.get("acq_time","")
            dur = r.get("duration","")
            edt = r.get("edf_type","")
            folder = self.current_session_from_filename(fn)
            base = os.path.basename(fn)
            tags = set()
            # mark changed
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
            # apply tags
            tags = tuple(row[5]) if row[5] else ()
            self.tree.insert("", "end", values=row[:5], tags=tags)

    def auto_resize_columns(self, event):
        # Distribute width proportionally
        total = event.width
        widths = [0.12, 0.48, 0.2, 0.12, 0.08]  # sum=1.0
        for (col, frac) in zip(("Folder","Filename","Acq Time","Duration (h)","EDF Type"), widths):
            self.tree.column(col, width=int(total*frac))

    # ---------- SHIFT RANGE ----------
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

        # Shift paths in-memory (non-destructive until Apply)
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

        # Compute mapping of old folder names -> new folder names, from filename paths
        old_to_new = {}
        orig_folders = []
        new_folders = []
        for orig, new in zip(self.original_rows, self.tsv_rows):
            ofn = orig.get("filename","")
            nfn = new.get("filename","")
            of = self.current_session_from_filename(ofn)
            nf = self.current_session_from_filename(nfn)
            if of and nf and of != nf:
                old_to_new[of] = nf
            if of:
                orig_folders.append(of)
            if nf:
                new_folders.append(nf)

        if not old_to_new:
            messagebox.showinfo("Info","No changes to apply.")
            return

        # Show preview
        s_preview = "\n".join([f"{k}  ->  {v}" for k,v in sorted(old_to_new.items(), key=lambda kv: int(kv[0].split('-')[1]))])
        if not messagebox.askyesno("Confirm", f"About to apply the following folder renames and TSV update:\n\n{s_preview}\n\nProceed?"):
            return

        # Begin logging block
        if not self.log_path:
            self.log_path = todays_log_path(self.root_dir)
        log_line(self.log_path, "===== APPLY START =====")
        # Backup TSV (byte-for-byte)
        ts_bak = datetime.now().strftime("%Y_%m_%d__%H_%M_%S")
        tsv_backup = f"{os.path.splitext(self.tsv_path)[0]}_backup_{ts_bak}.tsv"
        try:
            shutil.copy2(self.tsv_path, tsv_backup)
            log_line(self.log_path, f"Backup TSV: {tsv_backup}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to backup TSV:\n{e}")
            log_line(self.log_path, f"ERROR backing up TSV: {e}")
            return

        # Collision-safe two-pass rename of folders and files inside
        # Make a temp name for each target first
        temp_prefix = "__tmp__"
        try:
            if not self.dry_run.get():
                # First pass: rename each old folder to a unique temp
                temp_map = {}
                for old, new in old_to_new.items():
                    old_path = os.path.join(self.root_dir, old)
                    if not os.path.isdir(old_path):
                        log_line(self.log_path, f"WARNING: folder not found: {old_path}")
                        continue
                    temp_name = f"{temp_prefix}{new}"
                    temp_path = os.path.join(self.root_dir, temp_name)
                    # ensure unique temp
                    idx = 0
                    base_temp = temp_path
                    while os.path.exists(temp_path):
                        idx += 1
                        temp_path = base_temp + f"_{idx}"
                    os.rename(old_path, temp_path)
                    log_line(self.log_path, f"RENAMED (temp): {old} -> {os.path.basename(temp_path)}")
                    temp_map[temp_path] = new

                # Second pass: in each temp folder, rename files (filenames) that contain ses-### and then folder to final
                for temp_path, final_folder in temp_map.items():
                    # rename files inside
                    for r, dlist, flist in os.walk(temp_path):
                        for fn in flist:
                            m = re.search(r"ses-(\d{3})", fn)
                            if m:
                                # change just the ses token to the final folder number
                                final_num = final_folder.split("-")[1]
                                new_fn = re.sub(r"ses-\d{3}", f"ses-{final_num}", fn)
                                if new_fn != fn:
                                    os.rename(os.path.join(r, fn), os.path.join(r, new_fn))
                                    log_line(self.log_path, f"RENAMED FILE: {fn} -> {new_fn}")
                    final_path = os.path.join(self.root_dir, final_folder)
                    # ensure final path not colliding
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

        # Update TSV file (clean tab-separated) using current in-memory rows
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
        # Reload baseline for future diffs
        self.original_rows = [dict(r) for r in self.tsv_rows]
        self.refresh_table()

    # ---------- CHECK TSV vs FOLDERS ----------
    def check_tsv_vs_folders(self):
        if not self.root_dir:
            messagebox.showinfo("Info","Select a subject root first.")
            return
        # Build sets
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

        missing = sorted(tsv_sessions - folder_sessions, key=lambda s: int(s.split('-')[1]))
        extra   = sorted(folder_sessions - tsv_sessions, key=lambda s: int(s.split('-')[1]))
        log_line(self.log_path, f"TSV vs Folders — Missing folders: {len(missing)}, Extra folders: {len(extra)}")

        # Repaint table with tags
        self.refresh_table()
        # Mark TSV rows missing their folder
        item_ids = self.tree.get_children("")
        # map item to its folder value
        for iid in item_ids:
            folder_val = self.tree.set(iid, "Folder")
            if folder_val in missing:
                self.tree.item(iid, tags=("missing_folder",) + self.tree.item(iid, "tags"))
        # Insert extra rows
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

        # Use the user's logic (adapted)
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
        # durations already expected in hours
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

        # Missing dates
        missing_dates = set(full_date_range) - set(daily_durations.index)
        if missing_dates:
            log_line(self.log_path, "ERROR: The following dates are completely missing:")
            for missing in sorted(missing_dates):
                log_line(self.log_path, f"  - {missing}")
        else:
            log_line(self.log_path, "Perfect! No missing days found!")

        # Multiple sessions
        multiple_sessions = session_counts[session_counts > 1]
        if not multiple_sessions.empty:
            log_line(self.log_path, "INFO: Days with multiple sessions recorded:")
            for dtv, cnt in multiple_sessions.items():
                log_line(self.log_path, f"  - {dtv}: {cnt} sessions")
                log_line(self.log_path, f"    Files: {', '.join(filenames_by_date[dtv])}")

        # Build coloring map for rows
        # good (green): mid-days >= 23
        # warn (orange): first/last day < 23
        # error (red): mid-days < 23
        # multiple (blue): rows on days with >1 sessions
        day_status = {}  # date -> tag
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
                # Already logged as missing
                pass

        # Repaint table
        self.refresh_table()
        # map file row (acq_time date) to tag
        # Also mark multiple sessions blue
        multi_dates = set(multiple_sessions.index) if not multiple_sessions.empty else set()
        iid_list = self.tree.get_children("")
        # Build a quick index by (filename) to locate rows; simpler: iterate & tag by date
        for iid in iid_list:
            acq = self.tree.set(iid, "Acq Time")
            try:
                dt = datetime.strptime(acq, "%Y-%m-%d %H:%M:%S").date()
            except Exception:
                # skip non-parseable
                continue
            tags = list(self.tree.item(iid, "tags"))
            if dt in day_status:
                tags.append(day_status[dt])
            if dt in multi_dates:
                tags.append("multi_day")
            self.tree.item(iid, tags=tuple(set(tags)))

        log_line(self.log_path, f"Check completed. There are a total of {len(full_date_range)} days in the dataset.")
        log_line(self.log_path, "===== DURATION CHECK END =====")
        messagebox.showinfo("Duration Check", "Completed. See table colors and log for details.")

    # ---------- GENERATE TSV FROM EDFs ----------
    def generate_tsv_from_edfs(self):
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
                        acq_time = iso_fmt(start_dt)
                        dur_hours = round(float(dur_sec) / 3600.0, 2)
                        records.append( (rel, acq_time, dur_hours) )
                    except Exception as e:
                        log_line(self.log_path, f"ERROR reading EDF {full}: {e}")

        # Sort by acq_time
        try:
            records.sort(key=lambda t: datetime.strptime(t[1], "%Y-%m-%d %H:%M:%S"))
        except Exception:
            # fallback, no sort if time parse failed
            pass

        # Write TSV clean
        try:
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter="\t", lineterminator="\n")
                writer.writerow(["filename","acq_time","duration"])
                for rec in records:
                    writer.writerow([rec[0], rec[1], f"{rec[2]:.2f}"])
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
