import os
import re
import sys
import csv
import threading
import configparser
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------------------------------------------
# BIDS iEEG Structure Validator (GUI)
# ---------------------------------------------
# Validates folder layout like:
# sub-### / ses-### / ieeg / <files>
#
# Requirements per session:
#   • Exactly one  sub-XXX_ses-YYY_electrodes.tsv
# For each run present (task-*_run-##):
#   • Exactly one annotations.tsv
#   • Exactly one channels.tsv
#   • Exactly one ieeg.json
#   • Data container: EITHER raw .edf OR ONE archive (.edf.rar/.zip/.7z/.gz)
#   • Matching md5:  ieeg.edf.md5  OR ieeg.edf.<archive-ext>.md5
#
# You can bypass each check via checkboxes (persisted in an INI file).
# Accurate scan progress is shown.
# ---------------------------------------------

SUB_RE = re.compile(r"^sub-(?P<sub>\d{3})$")
SES_RE = re.compile(r"^ses-(?P<ses>\d{3})$")

ELECTRODES_RE = re.compile(
    r"^sub-(?P<sub>\d{3})_ses-(?P<ses>\d{3})_electrodes\.tsv$",
    re.IGNORECASE,
)
RUN_BASE_RE = re.compile(
    r"^sub-(?P<sub>\d{3})_ses-(?P<ses>\d{3})_task-(?P<task>[^_]+)_run-(?P<run>\d{2})_",
    re.IGNORECASE,
)

SUFFIX_ANNOT = ["annotations.tsv", "events.tsv"]
SUFFIX_CHAN = "channels.tsv"
SUFFIX_JSON = "ieeg.json"
SUFFIX_EDF = "ieeg.edf"
SUFFIX_EDF_MD5 = "ieeg.edf.md5"

# Archive extensions that come *after* "ieeg.edf"
# e.g., filename is ..._ieeg.edf.rar / ..._ieeg.edf.gz
ARCHIVE_EXTS = [
    ".rar",
    ".zip",
    ".7z",
    ".gz",
]
# For an archive ext like ".edf.gz", expect md5 suffix ".edf.gz.md5"
ARCHIVE_MD5_SUFFIXES = [ext + ".md5" for ext in ARCHIVE_EXTS]

# ---------------- Settings (persisted) -----------------
DEFAULT_SETTINGS = {
    "check_electrodes": True,
    "check_annotations": True,
    "check_channels": True,
    "check_json": True,
    "check_container": True,      # require either EDF or ONE archive
    "check_md5": True,            # require md5 for whichever container exists
    "flag_both_container": True,  # flag when BOTH .edf and any archive exist
    "flag_duplicates": True,      # flag duplicates of the same type
}

INI_PATH = Path.home() / ".bids_ieeg_validator.ini"

# ---------------- Data model -----------------
class SessionReport:
    def __init__(self, sub_id: str, ses_id: str, path: Path):
        self.sub_id = sub_id
        self.ses_id = ses_id
        self.path = path
        self.issues = []
        self.status = "OK"

    def add_issue(self, msg: str):
        self.issues.append(msg)
        self.status = "ISSUE"

    def to_row(self):
        return [self.sub_id, self.ses_id, self.status, "; ".join(self.issues), str(self.path)]

# ---------------- Validator -----------------
class BIDSValidator:
    def __init__(self, root_dir: Path, settings: dict, log_cb=None, set_total_cb=None, progress_cb=None):
        self.root_dir = root_dir
        self.settings = settings
        self.reports = []
        self.log = log_cb or (lambda msg: None)
        self.set_total = set_total_cb or (lambda total: None)
        self.progress = progress_cb or (lambda cur: None)

    def scan(self):
        # Discover sessions first to compute total
        subs = [d for d in self.root_dir.iterdir() if d.is_dir() and SUB_RE.match(d.name)]
        sessions = []
        for sub_dir in subs:
            for ses_dir in sub_dir.iterdir():
                if ses_dir.is_dir() and SES_RE.match(ses_dir.name):
                    sessions.append((sub_dir, ses_dir))
        self.set_total(len(sessions))

        done = 0
        for sub_dir, ses_dir in sessions:
            sub_id = SUB_RE.match(sub_dir.name).group("sub")
            ses_id = SES_RE.match(ses_dir.name).group("ses")
            ieeg_dir = ses_dir / "ieeg"
            rep = SessionReport(sub_id, ses_id, ses_dir)
            if not ieeg_dir.is_dir():
                rep.add_issue("Missing ieeg folder")
            else:
                self._validate_session(rep, ieeg_dir)
            self.reports.append(rep)
            done += 1
            self.progress(done)
        return self.reports

    def _validate_session(self, rep: SessionReport, ieeg_dir: Path):
        files = [f.name for f in ieeg_dir.iterdir() if f.is_file()]
        # Case-insensitive view (Windows-safe); keep originals for reporting
        files_lc = [s.lower() for s in files]
        files_lc_set = set(files_lc)

        # electrodes
        if self.settings["check_electrodes"]:
            electrodes = [f for f in files if ELECTRODES_RE.match(f)]
            if len(electrodes) == 0:
                rep.add_issue("Missing electrodes.tsv")
            elif self.settings["flag_duplicates"] and len(electrodes) > 1:
                rep.add_issue(f"Multiple electrodes.tsv ({len(electrodes)})")

        # runs present
        run_keys = set()
        for fname in files:
            m = RUN_BASE_RE.match(fname)
            if m:
                run_keys.add((m.group("task"), m.group("run")))
        if not run_keys:
            rep.add_issue("No runs detected in session")
            return

        for task, run in sorted(run_keys, key=lambda x: (x[0], x[1])):
            base = f"sub-{rep.sub_id}_ses-{rep.ses_id}_task-{task}_run-{run}_"

            # annotations
            if self.settings["check_annotations"]:
                count = 0
                for suf_annot in SUFFIX_ANNOT:
                    count += files.count(base + suf_annot)
                    
                if count == 0:
                    rep.add_issue(f"[{task} run-{run}] Missing annotations.tsv")
                elif self.settings["flag_duplicates"] and count > 1:
                    rep.add_issue(f"[{task} run-{run}] Multiple annotations.tsv ({count})")

            # channels
            if self.settings["check_channels"]:
                count = files.count(base + SUFFIX_CHAN)
                if count == 0:
                    rep.add_issue(f"[{task} run-{run}] Missing channels.tsv")
                elif self.settings["flag_duplicates"] and count > 1:
                    rep.add_issue(f"[{task} run-{run}] Multiple channels.tsv ({count})")

            # json
            if self.settings["check_json"]:
                count = files.count(base + SUFFIX_JSON)
                if count == 0:
                    rep.add_issue(f"[{task} run-{run}] Missing ieeg.json")
                elif self.settings["flag_duplicates"] and count > 1:
                    rep.add_issue(f"[{task} run-{run}] Multiple ieeg.json ({count})")

            # containers (case-insensitive)
            base_lc = base.lower()
            stem = base_lc + "ieeg.edf"
            edf_present = (stem) in files_lc_set
            archive_kinds = [ext for ext in ARCHIVE_EXTS if (stem + ext) in files_lc_set]
            num_archives = len(archive_kinds)
            # debug log of detected containers
            self.log(f"[sub-{rep.sub_id} ses-{rep.ses_id} {task} run-{run}] containers: edf={edf_present}, archives={archive_kinds}")

            # Container policy: EITHER raw EDF OR exactly one archive is OK. EDF is NOT required if an archive exists.
            if self.settings["check_container"]:
                if not edf_present and num_archives == 0:
                    rep.add_issue(f"[{task} run-{run}] Missing data container (.edf or archive)")
                # duplicates
                if self.settings["flag_duplicates"] and edf_present and files.count(base + SUFFIX_EDF) > 1:
                    rep.add_issue(f"[{task} run-{run}] Multiple .edf files")
                if self.settings["flag_duplicates"] and num_archives > 1:
                    rep.add_issue(f"[{task} run-{run}] Multiple archives ({', '.join(archive_kinds)})")
                # Both present (allowed? default: flag)
                if self.settings["flag_both_container"] and edf_present and num_archives >= 1:
                    rep.add_issue(f"[{task} run-{run}] Both .edf and archive present ({', '.join(archive_kinds)})")

            # md5 for whichever container exists
            if self.settings["check_md5"]:
                # edf md5 (case-insensitive)
                if edf_present and (stem + ".md5") not in files_lc_set and num_archives == 0:
                    rep.add_issue(f"[{task} run-{run}] Missing ieeg.edf.md5 for existing .edf")
                # archive md5s (require matching {ext}.md5 for each present archive)
                if num_archives >= 1:
                    for ext in archive_kinds:
                        if (stem + ext + ".md5") not in files_lc_set:
                            rep.add_issue(f"[{task} run-{run}] Missing md5 for archive ({ext}.md5)")

# ---------------- GUI -----------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BIDS iEEG Structure Validator")
        self.geometry("1180x720")
        self.minsize(980, 620)

        self.root_dir = tk.StringVar()
        self.status_var = tk.StringVar(value="Select a root folder and click Scan")

        # settings state
        self.settings_vars = {k: tk.BooleanVar(value=v) for k, v in DEFAULT_SETTINGS.items()}
        self._load_settings()

        self._build_ui()
        self.validator = None
        self.total_sessions = 0

    # ---------- Settings persistence ----------
    def _load_settings(self):
        if INI_PATH.exists():
            cfg = configparser.ConfigParser()
            try:
                cfg.read(INI_PATH)
                sec = cfg["checks"] if "checks" in cfg else {}
                for k in DEFAULT_SETTINGS.keys():
                    if k in sec:
                        self.settings_vars[k].set(cfg.getboolean("checks", k, fallback=DEFAULT_SETTINGS[k]))
            except Exception:
                pass

    def _save_settings(self):
        cfg = configparser.ConfigParser()
        cfg["checks"] = {k: str(var.get()) for k, var in self.settings_vars.items()}
        try:
            with open(INI_PATH, "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception:
            pass

    # ---------- UI ----------
    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(top, text="Root folder:").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.root_dir).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(top, text="Browse…", command=self.browse_root).pack(side=tk.LEFT)
        ttk.Button(top, text="Scan", command=self.start_scan).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Save CSV Report", command=self.save_report).pack(side=tk.LEFT)

        # Settings panel
        settings = ttk.LabelFrame(self, text="Checks (uncheck to bypass)")
        settings.pack(fill=tk.X, padx=10, pady=(0,10))
        row1 = ttk.Frame(settings); row1.pack(fill=tk.X, padx=6, pady=4)
        row2 = ttk.Frame(settings); row2.pack(fill=tk.X, padx=6, pady=4)
        c = self.settings_vars
        ttk.Checkbutton(row1, text="Electrodes", variable=c["check_electrodes"], command=self._save_settings).pack(side=tk.LEFT)
        ttk.Checkbutton(row1, text="Annotations", variable=c["check_annotations"], command=self._save_settings).pack(side=tk.LEFT, padx=(12,0))
        ttk.Checkbutton(row1, text="Channels", variable=c["check_channels"], command=self._save_settings).pack(side=tk.LEFT, padx=(12,0))
        ttk.Checkbutton(row1, text="JSON", variable=c["check_json"], command=self._save_settings).pack(side=tk.LEFT, padx=(12,0))
        ttk.Checkbutton(row1, text="Data container present", variable=c["check_container"], command=self._save_settings).pack(side=tk.LEFT, padx=(12,0))
        ttk.Checkbutton(row1, text="MD5 required", variable=c["check_md5"], command=self._save_settings).pack(side=tk.LEFT, padx=(12,0))
        ttk.Checkbutton(row2, text="Flag both EDF+archive", variable=c["flag_both_container"], command=self._save_settings).pack(side=tk.LEFT)
        ttk.Checkbutton(row2, text="Flag duplicates", variable=c["flag_duplicates"], command=self._save_settings).pack(side=tk.LEFT, padx=(12,0))

        # Summary
        self.summary = ttk.Label(self, textvariable=self.status_var, anchor="w")
        self.summary.pack(fill=tk.X, padx=10)
        """
        # Treeview
        cols = ("status", "issues", "path")
        self.tree = ttk.Treeview(self, columns=cols, show="tree headings")
        self.tree.heading("status", text="Status")
        self.tree.heading("issues", text="Issues (if any)")
        self.tree.heading("path", text="Path")
        self.tree.column("status", width=90, anchor="center")
        self.tree.column("issues", width=650)
        self.tree.column("path", width=320)
        self.tree.tag_configure("ok", foreground="#111")
        self.tree.tag_configure("issue", foreground="#b00020")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10) """

        # Frame for tree + scrollbar
        treeframe = ttk.Frame(self)
        treeframe.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.tree = ttk.Treeview(
            treeframe,
            columns=("status", "issues", "path"),
            show="tree headings"
        )
        self.tree.heading("status", text="Status")
        self.tree.heading("issues", text="Issues")
        self.tree.heading("path", text="Path")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Scrollbar
        ysb = ttk.Scrollbar(treeframe, orient="vertical", command=self.tree.yview)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=ysb.set)


        # Log + Progress
        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.BOTH, expand=False, padx=10, pady=(0,10))

        log_frame = ttk.LabelFrame(bottom, text="Log")
        log_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_frame, height=8)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        pb_frame = ttk.Frame(bottom)
        pb_frame.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=(10,0))
        ttk.Label(pb_frame, text="Scan Progress").pack(anchor="w")
        self.pb = ttk.Progressbar(pb_frame, orient="horizontal", mode="determinate", length=240, maximum=1, value=0)
        self.pb.pack(fill=tk.X)
        self.pb_label = ttk.Label(pb_frame, text="0 / 0")
        self.pb_label.pack(anchor="e")

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        self._save_settings()
        self.destroy()

    def browse_root(self):
        d = filedialog.askdirectory(title="Select BIDS root (contains sub-### folders)")
        if d:
            self.root_dir.set(d)

    def start_scan(self):
        root = self.root_dir.get().strip()
        if not root:
            messagebox.showwarning("Select folder", "Please select a root folder first.")
            return
        path = Path(root)
        if not path.exists() or not path.is_dir():
            messagebox.showerror("Invalid folder", "The selected path is not a directory.")
            return

        # clear previous results
        for item in self.tree.get_children(""):
            self.tree.delete(item)
        self.status_var.set("Scanning…")
        self.pb.configure(value=0)
        self.pb_label.configure(text="0 / 0")
        self.log_text.delete("1.0", tk.END)

        # snapshot settings
        settings = {k: var.get() for k, var in self.settings_vars.items()}
        self._save_settings()

        def run_scan():
            def log_cb(msg):
                # marshal to main thread
                self.after(0, lambda: (self.log_text.insert(tk.END, msg + "\n"), self.log_text.see(tk.END)))
            def set_total_cb(total):
                self.after(0, lambda: (self.pb.configure(maximum=max(1, total), value=0), self.pb_label.configure(text=f"0 / {max(1,total)}")))
            def prog_cb(cur):
                self.after(0, lambda: (self.pb.configure(value=cur), self.pb_label.configure(text=f"{cur} / {int(self.pb['maximum'])}"), self.status_var.set(f"Scanning sessions: {cur}/{int(self.pb['maximum'])}")))

            self.validator = BIDSValidator(path, settings, log_cb, set_total_cb, prog_cb)
            reports = self.validator.scan()
            self.after(0, lambda: self.populate_tree(reports))

        threading.Thread(target=run_scan, daemon=True).start()

    def populate_tree(self, reports):
        # Group by subject
        by_sub = {}
        for rep in reports:
            by_sub.setdefault(rep.sub_id, []).append(rep)
        total = len(reports)
        issues = sum(1 for r in reports if r.status != "OK")
        self.status_var.set(f"Scan complete: {total} session(s), {issues} with issues")
        # Insert subjects
        for sub_id in sorted(by_sub.keys()):
            subsessions = by_sub[sub_id]
            sub_tag = "ok" if all(r.status=="OK" for r in subsessions) else "issue"
            sub_node = self.tree.insert("", "end", text=f"sub-{sub_id}", values=("OK" if sub_tag=="ok" else "ISSUE", "", ""), tags=(sub_tag,))
            for rep in sorted(subsessions, key=lambda r: r.ses_id):
                tag = "ok" if rep.status == "OK" else "issue"
                self.tree.insert(
                    sub_node, "end",
                    text=f"ses-{rep.ses_id}",
                    values=(rep.status, "; ".join(rep.issues) or "—", str(rep.path)),
                    tags=(tag,)
                )
        # expand top-level subjects
        for item in self.tree.get_children(""):
            self.tree.item(item, open=True)

    def save_report(self):
        if not self.validator or not self.validator.reports:
            messagebox.showinfo("No data", "Please run a scan first.")
            return
        fp = filedialog.asksaveasfilename(
            title="Save CSV Report",
            defaultextension=".csv",
            filetypes=[("CSV files","*.csv"), ("All files","*.*")],
            initialfile="bids_ieeg_validation_report.csv"
        )
        if not fp:
            return
        with open(fp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["subject", "session", "status", "issues", "path"])
            for rep in self.validator.reports:
                w.writerow(rep.to_row())
        messagebox.showinfo("Saved", f"Report saved to:\n{fp}")

if __name__ == "__main__":
    app = App()
    # try nicer theme
    try:
        style = ttk.Style()
        if sys.platform.startswith("win"):
            style.theme_use("vista")
        else:
            style.theme_use("clam")
    except Exception:
        pass
    app.mainloop()
