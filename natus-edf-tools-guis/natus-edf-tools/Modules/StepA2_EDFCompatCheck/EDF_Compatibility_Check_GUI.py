import os
import time
import re
import threading
import queue
import configparser
import math
from datetime import datetime, timedelta
from tkinter import Tk, StringVar, IntVar, BooleanVar, filedialog, ttk, messagebox, N, S, E, W

# === Your existing checker ===
# Expecting: check_edf_compatibility(edfbrowser_path: str, edf_path: str) -> None
from EDF_Compatibility_Check_tool import check_edf_compatibility

# ---------- Defaults ----------
DEFAULT_SCAN_INTERVAL_SEC = 10
DEFAULT_SUBDIR_REGEX = r"sub-\d+"               # make this looser if you want (e.g., r"sub-[A-Za-z0-9]+")
DEFAULT_PRUNE_TOPLEVEL = True                   # only descend into top-level subject folders
FILE_STABILITY_AGE_SEC = 20                     # if mtime newer than this, consider "still being written"
INI_NAME = "edf_checker.ini"

# ---------- Config handling ----------
def get_ini_path():
    here = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(here, INI_NAME)

def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(get_ini_path())
    if "main" not in cfg:
        cfg["main"] = {}
    return cfg

def save_config(cfg):
    with open(get_ini_path(), "w") as f:
        cfg.write(f)

# ---------- File stability / lock checks ----------
def is_file_locked_via_rename(filepath: str) -> bool:
    base, ext = os.path.splitext(filepath)
    tmp = f"{base}.__lockcheck__{ext}"
    try:
        os.replace(filepath, tmp)
        os.replace(tmp, filepath)
        return False
    except Exception:
        # best effort revert if first rename succeeded but second failed
        if os.path.exists(tmp) and not os.path.exists(filepath):
            try:
                os.replace(tmp, filepath)
            except Exception:
                pass
        return True

def is_file_stable_by_age(filepath: str, min_age_sec: int = FILE_STABILITY_AGE_SEC) -> bool:
    try:
        st = os.stat(filepath)
    except FileNotFoundError:
        return False
    # Stable if it's not *too* new and is readable
    now = time.time()
    age = now - st.st_mtime
    if age < min_age_sec:
        return False
    # Try opening read-only
    try:
        with open(filepath, "rb"):
            return True
    except Exception:
        return False

def is_file_ready(filepath: str) -> bool:
    # Prefer rename check; if it fails (common on some shares), fall back to stability check.
    if not os.path.exists(filepath):
        return False
    if not is_file_locked_via_rename(filepath):
        return True
    return is_file_stable_by_age(filepath)

# ---------- Discovery ----------
def should_prune_to_subjects(root: str, main_folder: str) -> bool:
    # normalize to avoid trailing slash issues
    return os.path.normcase(os.path.normpath(root)) == os.path.normcase(os.path.normpath(main_folder))

def discover_edfs(main_folder: str, subdir_regex: re.Pattern, prune_top: bool) -> list[str]:
    edfs = []
    for root, dirs, files in os.walk(main_folder, topdown=True):
        if prune_top and should_prune_to_subjects(root, main_folder):
            if subdir_regex == None:
                pass
            else:
                dirs[:] = [d for d in dirs if subdir_regex.fullmatch(d)]
        for name in files:
            if name.lower().endswith(".edf"):
                edfs.append(os.path.join(root, name))
    return edfs

def has_marker_files(edf_path: str) -> bool:
    base, _ = os.path.splitext(edf_path)
    return os.path.exists(base + ".edf_pass") or os.path.exists(base + ".edf_fail")

# ---------- Formatting ----------
def fmt_bytes(n: int) -> str:
    if n is None:
        return "0 B"
    units = ["B","KB","MB","GB","TB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units)-1:
        f /= 1024.0
        i += 1
    return f"{f:.1f} {units[i]}"

def fmt_secs(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

# ---------- Worker ----------
class CheckerWorker(threading.Thread):
    def __init__(self, state, ui_queue):
        super().__init__(daemon=True)
        self.state = state
        self.ui_queue = ui_queue
        self.stop_ev = threading.Event()
        self.processed_this_session = set()

    def stop(self):
        self.stop_ev.set()

    def _post(self, **kwargs):
        self.ui_queue.put(kwargs)

    def run(self):
        last_discovery = 0.0
        pending = []
        while not self.stop_ev.is_set():
            now = time.time()
            # Rediscover periodically (scan interval)
            if now - last_discovery >= self.state.scan_interval():
                last_discovery = now
                try:
                    subre = re.compile(self.state.subdir_regex.get(), re.IGNORECASE)
                except re.error as e:
                    self._post(status=f"[Regex error] {e}. Using default {DEFAULT_SUBDIR_REGEX}")
                    subre = re.compile(DEFAULT_SUBDIR_REGEX, re.IGNORECASE)
                    subre = None

                all_edfs = discover_edfs(self.state.main_folder.get(), subre, self.state.prune_top.get())
                # filter out already marked pass/fail and already processed in this session
                candidates = [p for p in all_edfs if not has_marker_files(p) and p not in self.processed_this_session]
                # keep only those that look ready
                ready = [p for p in candidates if is_file_ready(p)]

                # record sizes for ETA
                sizes = {}
                for p in ready:
                    try:
                        sizes[p] = os.path.getsize(p)
                    except Exception:
                        sizes[p] = 0

                pending = ready
                self.state.set_total_detected(len(all_edfs))
                self.state.set_total_target(len(ready))
                self.state.set_total_bytes(sum(sizes.values()))
                self._post(status=f"Discovered {len(all_edfs)} EDFs | {len(ready)} pending")

            # Process queue one-by-one
            if pending:
                edf_path = pending.pop(0)
                self._post(current_file=edf_path)

                sz = 0
                try:
                    sz = os.path.getsize(edf_path)
                except Exception:
                    pass

                t0 = time.time()
                try:
                    check_edf_compatibility(self.state.edfbrowser_path.get(), edf_path)
                    ok = True
                    err = ""
                except Exception as e:
                    ok = False
                    err = str(e)

                dt = max(1e-6, time.time() - t0)
                self.state.bytes_done += sz
                self.state.files_done += 1
                self.processed_this_session.add(edf_path)

                # running throughput (ema-ish)
                speed = self.state.bytes_done / max(1e-6, (time.time() - self.state.start_time))
                remaining_bytes = max(0, self.state.total_bytes - self.state.bytes_done)
                eta_sec = remaining_bytes / speed if speed > 0 else 0

                self._post(
                    last_result=("PASS" if ok else "FAIL"),
                    last_error=err,
                    files_done=self.state.files_done,
                    bytes_done=self.state.bytes_done,
                    speed=speed,
                    eta_sec=eta_sec,
                )
            else:
                # nothing to do; nap a bit
                for _ in range(10):
                    if self.stop_ev.is_set():
                        break
                    time.sleep(0.1)

# ---------- GUI State ----------
class AppState:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()

        self.main_folder = StringVar(value=self.cfg["main"].get("main_folder", ""))
        self.edfbrowser_path = StringVar(value=self.cfg["main"].get("edfbrowser_path", ""))
        self.scan_interval_sec = IntVar(value=int(self.cfg["main"].get("scan_interval_sec", DEFAULT_SCAN_INTERVAL_SEC)))
        self.subdir_regex = StringVar(value=self.cfg["main"].get("subdir_regex", DEFAULT_SUBDIR_REGEX))
        self.prune_top = BooleanVar(value=self.cfg["main"].getboolean("prune_top", DEFAULT_PRUNE_TOPLEVEL))

        # Progress-related
        self.current_file = StringVar(value="—")
        self.status = StringVar(value="Idle")
        self.last_result = StringVar(value="—")
        self.last_error = StringVar(value="")
        self.detected_count = IntVar(value=0)
        self.target_count = IntVar(value=0)
        self.files_done = 0
        self.total_bytes = 0
        self.bytes_done = 0
        self.start_time = time.time()

        self.worker = None
        self.ui_queue = queue.Queue()

    def scan_interval(self) -> int:
        try:
            v = int(self.scan_interval_sec.get())
            return max(2, v)
        except Exception:
            return DEFAULT_SCAN_INTERVAL_SEC

    def set_total_detected(self, n: int):
        self.detected_count.set(int(n))

    def set_total_target(self, n: int):
        self.target_count.set(int(n))

    def set_total_bytes(self, n: int):
        self.total_bytes = int(n)

    def reset_progress(self):
        self.files_done = 0
        self.bytes_done = 0
        self.total_bytes = 0
        self.start_time = time.time()
        self.last_result.set("—")
        self.last_error.set("")
        self.current_file.set("—")

    def start(self):
        if not os.path.isdir(self.main_folder.get()):
            messagebox.showerror("Folder missing", "Please choose a valid MAIN folder.")
            return
        if not os.path.isfile(self.edfbrowser_path.get()):
            messagebox.showwarning("EDFbrowser path", "EDFbrowser executable not found. The tool may fail to run.")
        self.reset_progress()
        self.worker = CheckerWorker(self, self.ui_queue)
        self.worker.start()
        self.status.set("Monitoring…")

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.worker = None
            self.status.set("Stopped")

    def persist(self):
        self.cfg["main"]["main_folder"] = self.main_folder.get()
        self.cfg["main"]["edfbrowser_path"] = self.edfbrowser_path.get()
        self.cfg["main"]["scan_interval_sec"] = str(self.scan_interval())
        self.cfg["main"]["subdir_regex"] = self.subdir_regex.get()
        self.cfg["main"]["prune_top"] = "true" if self.prune_top.get() else "false"
        save_config(self.cfg)

# ---------- GUI ----------
class AppGUI:
    def __init__(self, root):
        self.state = AppState(root)
        root.title("EDF Compatibility Checker")
        root.geometry("880x520")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        pad = {"padx": 8, "pady": 6}

        frm = ttk.Frame(root)
        frm.grid(row=0, column=0, sticky=N+S+E+W)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        for i in range(6):
            frm.columnconfigure(i, weight=1)

        # Row 0: Folder & exe pickers
        ttk.Label(frm, text="Main folder:").grid(row=0, column=0, sticky=E, **pad)
        self.ent_folder = ttk.Entry(frm, textvariable=self.state.main_folder)
        self.ent_folder.grid(row=0, column=1, columnspan=4, sticky=E+W, **pad)
        ttk.Button(frm, text="Browse…", command=self.pick_folder).grid(row=0, column=5, sticky=W, **pad)

        ttk.Label(frm, text="EDFbrowser.exe:").grid(row=1, column=0, sticky=E, **pad)
        self.ent_exe = ttk.Entry(frm, textvariable=self.state.edfbrowser_path)
        self.ent_exe.grid(row=1, column=1, columnspan=4, sticky=E+W, **pad)
        ttk.Button(frm, text="Browse…", command=self.pick_exe).grid(row=1, column=5, sticky=W, **pad)

        # Row 2: Options
        ttk.Label(frm, text="Scan interval (s):").grid(row=2, column=0, sticky=E, **pad)
        ttk.Entry(frm, width=8, textvariable=self.state.scan_interval_sec).grid(row=2, column=1, sticky=W, **pad)

        self.chk_prune = ttk.Checkbutton(frm, text="Only top-level subject folders", variable=self.state.prune_top)
        self.chk_prune.grid(row=2, column=2, sticky=W, **pad)

        ttk.Label(frm, text="Subject regex:").grid(row=2, column=3, sticky=E, **pad)
        ttk.Entry(frm, textvariable=self.state.subdir_regex).grid(row=2, column=4, sticky=E+W, **pad)

        # Row 3: Controls
        ttk.Button(frm, text="Start", command=self.start).grid(row=3, column=0, sticky=E+W, **pad)
        ttk.Button(frm, text="Stop", command=self.stop).grid(row=3, column=1, sticky=E+W, **pad)
        ttk.Button(frm, text="Save Settings", command=self.save_settings).grid(row=3, column=2, sticky=E+W, **pad)

        ttk.Label(frm, text="Status:").grid(row=3, column=3, sticky=E, **pad)
        self.lbl_status = ttk.Label(frm, textvariable=self.state.status)
        self.lbl_status.grid(row=3, column=4, columnspan=2, sticky=W, **pad)

        # Row 4: Current file
        ttk.Label(frm, text="Current file:").grid(row=4, column=0, sticky=E, **pad)
        self.lbl_cur = ttk.Label(frm, textvariable=self.state.current_file)
        self.lbl_cur.grid(row=4, column=1, columnspan=5, sticky=E+W, **pad)

        # Row 5: Progress bar
        self.pb = ttk.Progressbar(frm, orient="horizontal", mode="determinate")
        self.pb.grid(row=5, column=0, columnspan=6, sticky=E+W, **pad)

        # Row 6: Counters
        self.vars = {
            "Detected": self.state.detected_count,
            "Pending": self.state.target_count,
        }
        self.lbl_detected = ttk.Label(frm, text="Detected (all EDFs):")
        self.lbl_detected.grid(row=6, column=0, sticky=E, **pad)
        ttk.Label(frm, textvariable=self.state.detected_count).grid(row=6, column=1, sticky=W, **pad)

        ttk.Label(frm, text="Checked:").grid(row=6, column=2, sticky=E, **pad)
        self.lbl_checked = ttk.Label(frm, text="0")
        self.lbl_checked.grid(row=6, column=3, sticky=W, **pad)

        ttk.Label(frm, text="Remaining:").grid(row=6, column=4, sticky=E, **pad)
        self.lbl_remaining = ttk.Label(frm, text="0")
        self.lbl_remaining.grid(row=6, column=5, sticky=W, **pad)

        # Row 7: Bytes & speed
        ttk.Label(frm, text="Bytes done / total:").grid(row=7, column=0, sticky=E, **pad)
        self.lbl_bytes = ttk.Label(frm, text="0 / 0")
        self.lbl_bytes.grid(row=7, column=1, sticky=W, **pad)

        ttk.Label(frm, text="Throughput:").grid(row=7, column=2, sticky=E, **pad)
        self.lbl_speed = ttk.Label(frm, text="—")
        self.lbl_speed.grid(row=7, column=3, sticky=W, **pad)

        ttk.Label(frm, text="ETA:").grid(row=7, column=4, sticky=E, **pad)
        self.lbl_eta = ttk.Label(frm, text="—")
        self.lbl_eta.grid(row=7, column=5, sticky=W, **pad)

        # Row 8: Last result/error
        ttk.Label(frm, text="Last result:").grid(row=8, column=0, sticky=E, **pad)
        ttk.Label(frm, textvariable=self.state.last_result).grid(row=8, column=1, sticky=W, **pad)

        ttk.Label(frm, text="Last error:").grid(row=8, column=2, sticky=E, **pad)
        self.lbl_err = ttk.Label(frm, textvariable=self.state.last_error, wraplength=500, foreground="#a00")
        self.lbl_err.grid(row=8, column=3, columnspan=3, sticky=E+W, **pad)

        # Pump UI updates
        self.root = root
        self.root.after(100, self.on_tick)

    def pick_folder(self):
        path = filedialog.askdirectory(title="Select main folder")
        if path:
            self.state.main_folder.set(path)

    def pick_exe(self):
        path = filedialog.askopenfilename(
            title="Select EDFbrowser executable",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")]
        )
        if path:
            self.state.edfbrowser_path.set(path)

    def save_settings(self):
        self.state.persist()
        messagebox.showinfo("Saved", "Settings saved to INI.")

    def start(self):
        self.state.persist()
        self.state.start()

    def stop(self):
        self.state.stop()

    def on_close(self):
        self.stop()
        self.state.persist()
        self.root.destroy()

    def on_tick(self):
        # Drain UI queue
        try:
            while True:
                msg = self.state.ui_queue.get_nowait()
                if "status" in msg:
                    self.state.status.set(msg["status"])
                if "current_file" in msg:
                    self.state.current_file.set(msg["current_file"])
                if "last_result" in msg:
                    self.state.last_result.set(msg["last_result"])
                if "last_error" in msg:
                    self.state.last_error.set(msg["last_error"])
                if "files_done" in msg:
                    self.state.files_done = int(msg["files_done"])
                if "bytes_done" in msg:
                    self.state.bytes_done = int(msg["bytes_done"])
                if "speed" in msg:
                    sp = msg["speed"]
                    self.lbl_speed.config(text=f"{fmt_bytes(sp)}/s")
                if "eta_sec" in msg:
                    eta = msg["eta_sec"]
                    self.lbl_eta.config(text=fmt_secs(eta))
        except queue.Empty:
            pass

        # Update counters/progress
        done = self.state.files_done
        total = self.state.target_count.get()
        remaining = max(0, total - done)
        self.lbl_checked.config(text=str(done))
        self.lbl_remaining.config(text=str(remaining))

        self.pb["maximum"] = max(1, total)
        self.pb["value"] = min(done, total)

        self.lbl_bytes.config(text=f"{fmt_bytes(self.state.bytes_done)} / {fmt_bytes(self.state.total_bytes)}")

        # schedule next tick
        self.root.after(200, self.on_tick)

def main():
    root = Tk()
    # Use ttk styles for nicer progress bar
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    AppGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
