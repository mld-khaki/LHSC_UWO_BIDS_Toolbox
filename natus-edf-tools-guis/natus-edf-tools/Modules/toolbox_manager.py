#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Python Tool Launcher — Tkinter GUI

Features implemented per spec:
- Tkinter GUI (plain theme) that recursively scans a chosen scan root for *.py files (tools).
- Excludes folders: venv/, .venv/, .git/, __pycache__/, build/, dist/, .ipynb_checkpoints/ .
- Treats every *.py as a tool (including __init__.py). Keys are RELATIVE PATHS from scan_root.
- INI file sits next to this GUI script (tools_catalog.ini). Per-tool metadata is persisted.
- Table with columns: Tool (relative path), Step, Sub-step, Revision, Inp Step, Out Step, Category, Tag.
  * Inline-editable cells (double-click to edit, press Enter or click Save to commit).
  * Sortable columns, quick filter box.
- Description panel with Apply / Cancel.
- Working directory field per tool (uses app main working dir if empty). Placeholders supported:
  {tool_dir}, {scan_root}, {app_dir}
- Args (kept for future), Env (semicolon-separated KEY=VALUE;KEY2=VALUE2), Open in external console toggle.
- Run button launches tool via subprocess.Popen, non-blocking.
- Close / Force close / Kill buttons:
  * Close → send CTRL_BREAK_EVENT to the process only (Windows), requires CREATE_NEW_PROCESS_GROUP.
  * Force close → proc.terminate() (no child handling).
  * Kill → taskkill /PID {pid} /T /F (kills whole tree).
- Live log viewer with timestamps and toolname; logs also saved to ./logs/<toolname>/<YYYYmmdd_HHMMSS>.log
- Running jobs pane: Tool, PID, Status, Start time, Elapsed, Working Dir, Exit code (when done).
  Clicking a job focuses its live log.
- Last run status/time/exit code persisted in INI.
- Rescan Tools, Save Metadata Now; rescan adds new tools, preserves metadata; missing tools kept in INI but not listed.
- Unlimited concurrency by default, with optional global throttle (0 = unlimited). Simple queued start if throttled.
- Status bar with Running/Idle counts; CPU/RAM summary if psutil available, else N/A.
- README viewer: looks for sibling README.md or <toolname>.md and shows in a popup (raw text).
- Run presets: per-tool named presets storing args/env/working_dir/open_in_console. Default preset "Main".
- Keyboard shortcuts: F5 (Rescan), Enter (Run), Ctrl+. (Close), Ctrl+Shift+. (Force), Ctrl+Alt+. (Kill), Ctrl+S (Save).

Notes:
- This script targets Windows behavior for signals. On non-Windows, Close maps to SIGTERM, Force to SIGKILL.
- Icons: Treeview images are only loaded if a sibling PNG named <toolname>.png exists (Tkinter supports PNG). .ico not used here.

"""

import configparser
import os
import sys
import threading
import queue
import subprocess
import time
import datetime
import traceback
import re
import signal
import platform
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

try:
    import psutil  # optional
except Exception:  # pragma: no cover
    psutil = None

# -------------------- Constants & Utilities --------------------
EXCLUDED_DIRS = {"venv", ".venv", ".git", "__pycache__", "build", "dist", ".ipynb_checkpoints"}
APP_DIR = os.path.dirname(os.path.abspath(__file__))
INI_PATH = os.path.join(APP_DIR, "tools_catalog.ini")
LOGS_DIR = os.path.join(APP_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

IS_WIN = os.name == "nt"
if IS_WIN:
    CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
else:
    CREATE_NEW_PROCESS_GROUP = 0
    CREATE_NEW_CONSOLE = 0

# columns in main table
TABLE_COLUMNS = [
    ("tool", "Tool"),
    ("step", "Step"),
    ("sub_step", "s-step"),
    ("revision", "Rev"),
    ("input_step", "Inp.St"),
    ("output_step", "Out.St"),
    ("category", "Cat."),
    ("tag", "Tag"),
]

# -------------------- Data Classes --------------------
@dataclass
class ToolPreset:
    name: str
    working_dir: str = ""
    args: str = ""
    env: str = ""
    open_in_console: bool = False

@dataclass
class ToolEntry:
    rel_path: str
    step: str = ""
    sub_step: str = ""
    revision: str = ""
    input_step: str = ""
    output_step: str = ""
    category: str = ""
    tag: str = ""
    description: str = ""
    working_dir: str = ""
    args: str = ""
    env: str = ""
    pinned: bool = False
    open_in_console: bool = False
    last_run_status: str = "never"  # success|failed|never
    last_run_time: str = ""
    last_exit_code: str = ""
    excluded: bool = False
    # Presets by name
    presets: Dict[str, ToolPreset] = field(default_factory=dict)

    def display_name(self) -> str:
        return self.rel_path.replace("/", os.sep)

    def tool_dir(self, scan_root: str) -> str:
        return os.path.dirname(os.path.join(scan_root, self.rel_path))

    def tool_name(self) -> str:
        return os.path.splitext(os.path.basename(self.rel_path))[0]

# -------------------- Config Manager --------------------
class Catalog:
    def __init__(self, ini_path: str, scan_root: str = ""):
        self.ini_path = ini_path
        self.scan_root = scan_root
        self.config = configparser.ConfigParser()
        self.tools: Dict[str, ToolEntry] = {}
        self.global_settings = {
            "scan_root": scan_root or "",
            "main_working_dir": os.getcwd(),
            "concurrency_limit": "0",  # 0 = unlimited
        }
        self.load()

    def load(self):
        self.config.read(self.ini_path, encoding="utf-8")
        # Load app settings
        if "app" in self.config:
            appsec = self.config["app"]
            for k in self.global_settings:
                if k in appsec:
                    self.global_settings[k] = appsec.get(k, self.global_settings[k])
        self.scan_root = self.global_settings.get("scan_root", self.scan_root)
        # Load tools
        for section in self.config.sections():
            if section == "app":
                continue
            if section.startswith("preset:"):
                # handled below when attaching to tool
                continue
            ent = self._entry_from_section(section)
            self.tools[section] = ent
        # Load presets
        for section in self.config.sections():
            if not section.startswith("preset:"):
                continue
            # section name format: preset:<rel_path>:<preset_name>
            _, rel_path, preset_name = section.split(":", 2)
            if rel_path in self.tools:
                psec = self.config[section]
                preset = ToolPreset(
                    name=preset_name,
                    working_dir=psec.get("working_dir", ""),
                    args=psec.get("args", ""),
                    env=psec.get("env", ""),
                    open_in_console=psec.getboolean("open_in_console", False),
                )
                self.tools[rel_path].presets[preset_name] = preset

    def _entry_from_section(self, section: str) -> ToolEntry:
        sec = self.config[section]
        return ToolEntry(
            rel_path=section,
            step=sec.get("step", ""),
            sub_step=sec.get("sub_step", ""),
            revision=sec.get("revision", ""),
            input_step=sec.get("input_step", ""),
            output_step=sec.get("output_step", ""),
            category=sec.get("category", ""),
            tag=sec.get("tag", ""),
            description=sec.get("description", ""),
            working_dir=sec.get("working_dir", ""),
            args=sec.get("args", ""),
            env=sec.get("env", ""),
            pinned=sec.getboolean("pinned", False),
            open_in_console=sec.getboolean("open_in_console", False),
            last_run_status=sec.get("last_run_status", "never"),
            last_run_time=sec.get("last_run_time", ""),
            last_exit_code=sec.get("last_exit_code", ""),
            excluded=sec.getboolean("excluded", False),
        )

    def save(self):
        # rebuild config fresh
        cfg = configparser.ConfigParser()
        cfg["app"] = {
            "scan_root": self.scan_root or self.global_settings.get("scan_root", ""),
            "main_working_dir": self.global_settings.get("main_working_dir", os.getcwd()),
            "concurrency_limit": self.global_settings.get("concurrency_limit", "0"),
        }
        # tool sections
        for rel_path, ent in sorted(self.tools.items()):
            sec = {
                "step": ent.step,
                "sub_step": ent.sub_step,
                "revision": ent.revision,
                "input_step": ent.input_step,
                "output_step": ent.output_step,
                "category": ent.category,
                "tag": ent.tag,
                "description": ent.description,
                "working_dir": ent.working_dir,
                "args": ent.args,
                "env": ent.env,
                "pinned": str(ent.pinned).lower(),
                "open_in_console": str(ent.open_in_console).lower(),
                "last_run_status": ent.last_run_status,
                "last_run_time": ent.last_run_time,
                "last_exit_code": ent.last_exit_code,
                "excluded": str(ent.excluded).lower(),
            }
            cfg[rel_path] = sec
            # presets
            for pname, p in ent.presets.items():
                psection = f"preset:{rel_path}:{pname}"
                cfg[psection] = {
                    "working_dir": p.working_dir,
                    "args": p.args,
                    "env": p.env,
                    "open_in_console": str(p.open_in_console).lower(),
                }
        with open(self.ini_path, "w", encoding="utf-8") as f:
            cfg.write(f)
        self.config = cfg

    def rescan(self, scan_root: Optional[str] = None) -> List[str]:
        """Scan for *.py under scan_root (or existing). Update internal map; return list of newly discovered rel_paths."""
        if scan_root is not None:
            self.scan_root = scan_root
            self.global_settings["scan_root"] = scan_root
        root = self.scan_root
        if not root or not os.path.isdir(root):
            return []
        new_rel_paths: List[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            # prune excluded dirs
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                rel = rel.replace(os.sep, "/")  # normalize key
                if rel not in self.tools:
                    self.tools[rel] = ToolEntry(rel_path=rel)
                    new_rel_paths.append(rel)
                
        # Do not delete missing entries; they remain in INI but are not listed in UI
        return new_rel_paths

# -------------------- Job Management --------------------
class Job:
    def __init__(self, tool: ToolEntry, cmd: List[str], cwd: str, env: Dict[str, str], log_path: str, open_in_console: bool):
        self.tool = tool
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self.log_path = log_path
        self.open_in_console = open_in_console
        self.proc: Optional[subprocess.Popen] = None
        self.stdout_thread: Optional[threading.Thread] = None
        self.queue: queue.Queue[str] = queue.Queue()
        self.start_time = time.time()
        self.exit_code: Optional[int] = None
        self.status: str = "starting"  # running|exited|starting
        self._stop_event = threading.Event()
        self._log_file = open(log_path, "a", encoding="utf-8", buffering=1)

    def start(self):
        flags = CREATE_NEW_PROCESS_GROUP
        if self.open_in_console and IS_WIN:
            flags |= CREATE_NEW_CONSOLE
        stdout = None if self.open_in_console else subprocess.PIPE
        stderr = None if self.open_in_console else subprocess.STDOUT
        try:
            self.proc = subprocess.Popen(
                self.cmd,
                cwd=self.cwd or None,
                env=self.env or None,
                stdout=stdout,
                stderr=stderr,
                stdin=None,
                bufsize=1,
                universal_newlines=True,
                creationflags=flags,
                shell=False,
            )
            self.status = "running"
            if not self.open_in_console:
                self.stdout_thread = threading.Thread(target=self._reader, name=f"stdout-{self.proc.pid}", daemon=True)
                self.stdout_thread.start()
        except Exception as e:
            self.status = "exited"
            self.exit_code = -1
            self._write_log(f"[ERROR] Failed to start: {e}\n{traceback.format_exc()}")

    def _timestamp(self) -> str:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def _write_log(self, line: str):
        try:
            self._log_file.write(line)
            self._log_file.flush()
        except Exception:
            pass

    def _reader(self):
        assert self.proc is not None
        toolname = self.tool.tool_name()
        for raw in iter(self.proc.stdout.readline, ''):
            ts = self._timestamp()
            line = f"[{ts}] [{toolname}] {raw}"
            self.queue.put(line)
            self._write_log(line)
        # drain any remaining
        remainder = self.proc.stdout.read()
        if remainder:
            ts = self._timestamp()
            for raw in remainder.splitlines(True):
                line = f"[{ts}] [{toolname}] {raw}"
                self.queue.put(line)
                self._write_log(line)
        self.proc.stdout.close()

    def poll(self):
        if self.proc is None:
            return
        code = self.proc.poll()
        if code is not None and self.exit_code is None:
            self.exit_code = code
            self.status = "exited"
            ts = self._timestamp()
            self._write_log(f"[{ts}] [system] Process exited with code {code}\n")
            try:
                self._log_file.close()
            except Exception:
                pass

    def close_soft(self) -> Tuple[bool, str]:
        if self.proc is None:
            return False, "Not started"
        try:
            if IS_WIN:
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.proc.terminate()
            return True, "Close signal sent"
        except Exception as e:
            return False, str(e)

    def force_close(self) -> Tuple[bool, str]:
        if self.proc is None:
            return False, "Not started"
        try:
            self.proc.terminate()
            return True, "Terminate sent"
        except Exception as e:
            return False, str(e)

    def kill_tree(self) -> Tuple[bool, str]:
        if self.proc is None:
            return False, "Not started"
        if IS_WIN:
            try:
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
                return True, "Taskkill /T /F sent"
            except Exception as e:
                return False, str(e)
        else:
            try:
                self.proc.kill()
                return True, "SIGKILL sent"
            except Exception as e:
                return False, str(e)

# -------------------- GUI --------------------
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Python Tool Launcher")
        self.geometry("1200x800")
        self.minsize(1000, 700)

        if IS_WIN:
            pass  # leave default icon

        self.catalog = Catalog(INI_PATH)

        # --- Initialize state first ---
        self.selected_tool_id: Optional[str] = None
        self.filtered_tool_ids: List[str] = []
        self.jobs: Dict[int, Job] = {}
        self.pending_jobs: List[Tuple[ToolEntry, Dict]] = []
        self._log_buffers: Dict[int, List[str]] = {}

        # --- Now build UI ---
        self._build_ui()
        self._install_shortcuts()

        # --- Scan root handling ---
        if not self.catalog.scan_root or not os.path.isdir(self.catalog.scan_root):
            self.prompt_scan_root()
        else:
            self.catalog.rescan()
            self.catalog.save()

        # --- Populate UI and start poller ---
        self._populate_table()
        self.after(200, self._ui_poller)



    # ---------- UI Building ----------
    def _build_ui(self):
        # Top controls: scan root, main working dir, throttle
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=6, pady=6)

        ttk.Label(top, text="Scan root:").pack(side=tk.LEFT)
        self.scan_root_var = tk.StringVar(value=self.catalog.scan_root)
        self.scan_root_entry = ttk.Entry(top, textvariable=self.scan_root_var, width=60)
        self.scan_root_entry.pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Browse…", command=self._choose_scan_root).pack(side=tk.LEFT)
        ttk.Button(top, text="Rescan (F5)", command=self.on_rescan).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Exclude Tool", command=self.on_exclude_tool).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Include Tool", command=self.on_include_tool).pack(side=tk.LEFT, padx=6)        
        

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Label(top, text="Main working dir:").pack(side=tk.LEFT)
        self.main_wd_var = tk.StringVar(value=self.catalog.global_settings.get("main_working_dir", os.getcwd()))
        self.main_wd_entry = ttk.Entry(top, textvariable=self.main_wd_var, width=50)
        self.main_wd_entry.pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Browse…", command=self._choose_main_wd).pack(side=tk.LEFT)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Label(top, text="Throttle (0=∞):").pack(side=tk.LEFT)
        self.throttle_var = tk.IntVar(value=int(self.catalog.global_settings.get("concurrency_limit", "0") or 0))
        self.throttle_spin = ttk.Spinbox(top, from_=0, to=64, width=4, textvariable=self.throttle_var, command=self._update_throttle)
        self.throttle_spin.pack(side=tk.LEFT)

        ttk.Button(top, text="Save INI (Ctrl+S)", command=self.on_save).pack(side=tk.RIGHT)

        # Filter box
        filt_fr = ttk.Frame(self)
        filt_fr.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(0,6))
        ttk.Label(filt_fr, text="Filter:").pack(side=tk.LEFT)
        self.filter_var = tk.StringVar()
        ent = ttk.Entry(filt_fr, textvariable=self.filter_var)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ent.bind("<KeyRelease>", lambda e: self._populate_table())

        # Main split: left (table) and right (detail)
        main_split = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main_split.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main_split)
        right = ttk.Frame(main_split)
        main_split.add(left, weight=3)
        main_split.add(right, weight=2)

        # Table
        self.tree = ttk.Treeview(left, columns=[c for c,_ in TABLE_COLUMNS], show='headings', selectmode='browse')
        for key, label in TABLE_COLUMNS:
            self.tree.heading(key, text=label, command=lambda k=key: self._sort_by(k, False))
            self.tree.column(key, width=150 if key!="tool" else 300, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select_tool)
        self.tree.bind("<Double-1>", self.on_table_double_click)

        # Right panel: description, working dir, args/env, presets, run/stop, README, log
        # --- Meta frame ---
        meta = ttk.LabelFrame(right, text="Tool metadata")
        meta.pack(fill=tk.X, padx=6, pady=6)

        # Working dir
        wd_fr = ttk.Frame(meta)
        wd_fr.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(wd_fr, text="Working dir (empty → Main):").pack(side=tk.LEFT)
        self.tool_wd_var = tk.StringVar()
        self.tool_wd_entry = ttk.Entry(wd_fr, textvariable=self.tool_wd_var)
        self.tool_wd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(wd_fr, text="Browse…", command=self._choose_tool_wd).pack(side=tk.LEFT)

        # Args + Env
        ae_fr = ttk.Frame(meta)
        ae_fr.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(ae_fr, text="Args:").pack(side=tk.LEFT)
        self.args_var = tk.StringVar()
        ttk.Entry(ae_fr, textvariable=self.args_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        ttk.Label(ae_fr, text="Env (KEY=VAL;…):").pack(side=tk.LEFT)
        self.env_var = tk.StringVar()
        ttk.Entry(ae_fr, textvariable=self.env_var, width=40).pack(side=tk.LEFT, padx=4)

        self.open_console_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(meta, text="Open in external console window", variable=self.open_console_var).pack(anchor=tk.W, padx=6)

        # Presets
        pr_fr = ttk.Frame(meta)
        pr_fr.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(pr_fr, text="Preset:").pack(side=tk.LEFT)
        self.preset_var = tk.StringVar(value="Main")
        self.preset_combo = ttk.Combobox(pr_fr, textvariable=self.preset_var, state="readonly", values=["Main"])
        self.preset_combo.pack(side=tk.LEFT)
        self.preset_combo.bind("<<ComboboxSelected>>", self.on_preset_selected)
        ttk.Button(pr_fr, text="Save as preset…", command=self.on_save_preset).pack(side=tk.LEFT, padx=4)
        ttk.Button(pr_fr, text="Delete preset", command=self.on_delete_preset).pack(side=tk.LEFT)

        # Description
        desc_fr = ttk.LabelFrame(right, text="Description")
        desc_fr.pack(fill=tk.BOTH, expand=False, padx=6, pady=6)
        self.desc_text = tk.Text(desc_fr, height=6, wrap=tk.WORD)
        self.desc_text.pack(fill=tk.BOTH, expand=True)
        desc_btns = ttk.Frame(desc_fr)
        desc_btns.pack(fill=tk.X)
        ttk.Button(desc_btns, text="Apply", command=self.on_apply_desc).pack(side=tk.LEFT)
        ttk.Button(desc_btns, text="Cancel", command=self.on_cancel_desc).pack(side=tk.LEFT, padx=4)

        # Run/Stop buttons
        run_fr = ttk.Frame(right)
        run_fr.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(run_fr, text="Run (Enter)", command=self.on_run).pack(side=tk.LEFT)
        ttk.Button(run_fr, text="Close (Ctrl+.)", command=self.on_close_soft).pack(side=tk.LEFT, padx=4)
        ttk.Button(run_fr, text="Force (Ctrl+Shift+.)", command=self.on_force_close).pack(side=tk.LEFT, padx=4)
        ttk.Button(run_fr, text="Kill (Ctrl+Alt+.)", command=self.on_kill).pack(side=tk.LEFT, padx=4)
        ttk.Button(run_fr, text="Open README", command=self.on_open_readme).pack(side=tk.RIGHT)

        # Running jobs pane
        jobs_fr = ttk.LabelFrame(right, text="Running jobs")
        jobs_fr.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        cols = ("tool","pid","status","start","elapsed","cwd","exit")
        self.jobs_tree = ttk.Treeview(jobs_fr, columns=cols, show='headings', height=6)
        for c in cols:
            self.jobs_tree.heading(c, text=c.title())
            self.jobs_tree.column(c, width=100 if c!="tool" and c!="cwd" else 200, anchor=tk.W)
        self.jobs_tree.pack(fill=tk.BOTH, expand=False)
        self.jobs_tree.bind("<<TreeviewSelect>>", self.on_select_job)

        # Log viewer
        log_fr = ttk.LabelFrame(right, text="Live log")
        log_fr.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.log_text = tk.Text(log_fr, height=10, wrap=tk.NONE)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        yscroll = ttk.Scrollbar(log_fr, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status = ttk.Label(self, textvariable=self.status_var, anchor=tk.W)
        status.pack(side=tk.BOTTOM, fill=tk.X)

    def _install_shortcuts(self):
        self.bind("<F5>", lambda e: self.on_rescan())
        self.bind("<Return>", lambda e: self.on_run())
        self.bind("<Control-period>", lambda e: self.on_close_soft())
        self.bind("<Control-Shift-period>", lambda e: self.on_force_close())
        self.bind("<Control-Alt-period>", lambda e: self.on_kill())
        self.bind("<Control-s>", lambda e: self.on_save())

    # ---------- Helpers ----------
    def prompt_scan_root(self):
        messagebox.showinfo("Scan Root", "Please choose the folder to scan for Python tools.")
        self._choose_scan_root()

    def _choose_scan_root(self):
        d = filedialog.askdirectory(title="Select scan root")
        if not d:
            return
        self.scan_root_var.set(d)
        self.catalog.rescan(d)
        self.catalog.save()
        self._populate_table()

    def _choose_main_wd(self):
        d = filedialog.askdirectory(title="Select main working directory")
        if not d:
            return
        self.main_wd_var.set(d)
        self.catalog.global_settings["main_working_dir"] = d
        self.catalog.save()

    def _choose_tool_wd(self):
        d = filedialog.askdirectory(title="Select tool working directory")
        if not d:
            return
        if not self.selected_tool_id:
            return
        ent = self.catalog.tools[self.selected_tool_id]
        ent.working_dir = d
        self.tool_wd_var.set(d)

    def _update_throttle(self):
        self.catalog.global_settings["concurrency_limit"] = str(self.throttle_var.get())
        self.catalog.save()

    def _sort_by(self, col_key: str, descending: bool):
        data = []
        for iid in self.filtered_tool_ids:
            ent = self.catalog.tools[iid]
            val = getattr(ent, col_key)
            data.append((val.lower() if isinstance(val, str) else str(val), iid))
        data.sort(reverse=descending)
        self.tree.delete(*self.tree.get_children())
        for _, iid in data:
            self._insert_row(iid)
        # next click should reverse
        self.tree.heading(col_key, command=lambda k=col_key: self._sort_by(k, not descending))

    def _populate_table(self):
        filt = (self.filter_var.get() or "").strip().lower()
        self.tree.delete(*self.tree.get_children())
        self.filtered_tool_ids.clear()

        for rel, ent in sorted(self.catalog.tools.items()):
            full = os.path.join(self.catalog.scan_root or "", rel)
            if not os.path.isfile(full):
                continue
            if ent.excluded:
                continue  # skip excluded tools
            if not filt or self._match_filter(ent, filt):
                self.filtered_tool_ids.append(rel)
                self._insert_row(rel)

        self.status_var.set(f"Loaded {len(self.filtered_tool_ids)} tools.")


    def _match_filter(self, ent: ToolEntry, filt: str) -> bool:
        hay = " ".join([
            ent.rel_path, ent.step, ent.sub_step, ent.revision,
            ent.input_step, ent.output_step, ent.category, ent.tag
        ]).lower()
        return all(tok in hay for tok in filt.split())

    def _insert_row(self, rel: str):
        ent = self.catalog.tools[rel]
        vals = [
            ent.display_name(), ent.step, ent.sub_step, ent.revision,
            ent.input_step, ent.output_step, ent.category, ent.tag
        ]
        self.tree.insert('', tk.END, iid=rel, values=vals)

    def on_exclude_tool(self):
        if not self.selected_tool_id:
            return
        ent = self.catalog.tools[self.selected_tool_id]
        ent.excluded = True
        self.catalog.save()
        self._populate_table()

    def on_include_tool(self):
        # Show dialog of excluded tools
        excluded = [rel for rel, ent in self.catalog.tools.items() if ent.excluded]
        if not excluded:
            messagebox.showinfo("Include Tool", "No excluded tools to add back.")
            return
        choice = simple_input(self, "Include Tool", f"Enter relative path to include:\n{excluded}")
        if not choice or choice not in self.catalog.tools:
            return
        self.catalog.tools[choice].excluded = False
        self.catalog.save()
        self._populate_table()


    def on_select_tool(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        self.selected_tool_id = iid
        ent = self.catalog.tools[iid]
        # update detail fields
        self.tool_wd_var.set(ent.working_dir)
        self.args_var.set(ent.args)
        self.env_var.set(ent.env)
        self.open_console_var.set(ent.open_in_console)
        # description
        self.desc_text.delete('1.0', tk.END)
        self.desc_text.insert('1.0', ent.description or "")
        # presets
        names = ["Main"] + sorted([n for n in ent.presets.keys() if n != "Main"])
        if "Main" not in ent.presets:
            ent.presets["Main"] = ToolPreset("Main", ent.working_dir, ent.args, ent.env, ent.open_in_console)
        self.preset_combo["values"] = names
        self.preset_var.set("Main")

    def on_table_double_click(self, event):
        # Inline edit the clicked cell (except tool path)
        item = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not item or not column:
            return
        col_index = int(column.replace('#','')) - 1
        key = TABLE_COLUMNS[col_index][0]
        if key == "tool":
            return
        x, y, w, h = self.tree.bbox(item, column)
        old = self.tree.set(item, column)
        entry = ttk.Entry(self.tree)
        entry.insert(0, old)
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()

        def commit(event=None):
            new = entry.get()
            entry.destroy()
            self.tree.set(item, column, new)
            # write back to catalog
            ent = self.catalog.tools[item]
            setattr(ent, key, new)

        def cancel(event=None):
            entry.destroy()

        entry.bind('<Return>', commit)
        entry.bind('<Escape>', cancel)
        entry.bind('<FocusOut>', commit)

    def on_apply_desc(self):
        if not self.selected_tool_id:
            return
        txt = self.desc_text.get('1.0', tk.END).rstrip()
        ent = self.catalog.tools[self.selected_tool_id]
        ent.description = txt
        self.status_var.set("Description applied.")

    def on_cancel_desc(self):
        if not self.selected_tool_id:
            return
        ent = self.catalog.tools[self.selected_tool_id]
        self.desc_text.delete('1.0', tk.END)
        self.desc_text.insert('1.0', ent.description or "")

    def on_save(self):
        # push current detail edits
        if self.selected_tool_id and self.selected_tool_id in self.catalog.tools:
            ent = self.catalog.tools[self.selected_tool_id]
            ent.working_dir = self.tool_wd_var.get()
            ent.args = self.args_var.get()
            ent.env = self.env_var.get()
            ent.open_in_console = bool(self.open_console_var.get())
            # also refresh Main preset
            if "Main" in ent.presets:
                ent.presets["Main"].working_dir = ent.working_dir
                ent.presets["Main"].args = ent.args
                ent.presets["Main"].env = ent.env
                ent.presets["Main"].open_in_console = ent.open_in_console
        # save app settings
        self.catalog.global_settings["scan_root"] = self.scan_root_var.get()
        self.catalog.global_settings["main_working_dir"] = self.main_wd_var.get()
        self.catalog.global_settings["concurrency_limit"] = str(self.throttle_var.get())
        self.catalog.save()
        self.status_var.set(f"Saved INI → {INI_PATH}")

    def on_rescan(self):
        root = self.scan_root_var.get()
        if not root:
            messagebox.showerror("Rescan", "Scan root is empty.")
            return
        new = self.catalog.rescan(root)
        self.catalog.save()
        self._populate_table()
        self.status_var.set(f"Rescan complete. New tools: {len(new)}")

    def on_run(self):
        if not self.selected_tool_id:
            messagebox.showwarning("Run", "Select a tool first.")
            return
        ent = self.catalog.tools[self.selected_tool_id]
        full_path = os.path.join(self.catalog.scan_root or "", ent.rel_path)
        if not os.path.isfile(full_path):
            messagebox.showerror("Run", "Tool file no longer exists on disk (kept in INI).")
            return
        # build working dir
        wd = ent.working_dir.strip() or self.main_wd_var.get().strip()
        wd = self._expand_placeholders(wd, ent)
        if wd and not os.path.isdir(wd):
            if messagebox.askyesno("Working dir", f"Create missing working dir?\n{wd}"):
                try:
                    os.makedirs(wd, exist_ok=True)
                except Exception as e:
                    messagebox.showerror("Working dir", f"Failed to create: {e}")
                    return
            else:
                return
        # args and env
        args = self._expand_placeholders(ent.args or "", ent)
        arg_list = [a for a in self._shell_split(args)] if args else []
        env = os.environ.copy()
        env_updates = self._parse_env(self._expand_placeholders(ent.env or "", ent))
        env.update(env_updates)
        # command
        python_exe = sys.executable
        cmd = [python_exe, "-u", full_path] + arg_list
        # logs
        toolname = ent.tool_name()
        tstamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        tool_log_dir = os.path.join(LOGS_DIR, toolname)
        os.makedirs(tool_log_dir, exist_ok=True)
        log_path = os.path.join(tool_log_dir, f"{toolname}_{tstamp}.log")
        # throttle
        limit = int(self.catalog.global_settings.get("concurrency_limit", "0") or 0)
        running = len([j for j in self.jobs.values() if j.status == "running"]) if limit else 0
        if limit and running >= limit:
            self.pending_jobs.append((ent, {"cmd": cmd, "wd": wd, "env": env, "log": log_path, "open": ent.open_in_console}))
            self.status_var.set("Queued (throttle reached)")
            return
        job = Job(ent, cmd, wd, env, log_path, ent.open_in_console)
        job.start()
        if job.proc is None:
            messagebox.showerror("Run", "Failed to start process. See log pane for details.")
            return
        pid = job.proc.pid
        self.jobs[pid] = job
        self._log_buffers[pid] = []
        self._add_job_row(job)
        ent.last_run_time = datetime.datetime.now().isoformat(timespec='seconds')
        ent.last_run_status = "running"
        ent.last_exit_code = ""
        self._update_status_bar()

    def _add_job_row(self, job: Job):
        pid = job.proc.pid if job.proc else 0
        start = datetime.datetime.fromtimestamp(job.start_time).strftime('%H:%M:%S')
        self.jobs_tree.insert('', tk.END, iid=str(pid), values=(
            job.tool.display_name(), pid, job.status, start, "0:00", job.cwd, ""
        ))

    def on_select_job(self, event=None):
        sel = self.jobs_tree.selection()
        if not sel:
            return
        pid = int(sel[0])
        self._display_log_buffer(pid)

    def on_close_soft(self):
        job = self._selected_job()
        if not job:
            return
        ok, msg = job.close_soft()
        self.status_var.set(f"Close: {msg}")

    def on_force_close(self):
        job = self._selected_job()
        if not job:
            return
        ok, msg = job.force_close()
        self.status_var.set(f"Force: {msg}")

    def on_kill(self):
        job = self._selected_job()
        if not job:
            return
        ok, msg = job.kill_tree()
        self.status_var.set(f"Kill: {msg}")

    def on_open_readme(self):
        if not self.selected_tool_id:
            return
        ent = self.catalog.tools[self.selected_tool_id]
        full = os.path.join(self.catalog.scan_root or "", ent.rel_path)
        d = os.path.dirname(full)
        candidates = [os.path.join(d, "README.md"), os.path.join(d, f"{ent.tool_name()}.md")]
        path = next((p for p in candidates if os.path.isfile(p)), None)
        if not path:
            messagebox.showinfo("README", "No README.md or <toolname>.md found next to the script.")
            return
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        win = tk.Toplevel(self)
        win.title(f"README — {os.path.basename(path)}")
        txt = tk.Text(win, wrap=tk.WORD)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert('1.0', content)
        txt.configure(state=tk.DISABLED)
        win.geometry("700x600")

    def on_preset_selected(self, event=None):
        if not self.selected_tool_id:
            return
        ent = self.catalog.tools[self.selected_tool_id]
        name = self.preset_var.get()
        if name == "Main":
            # load from current main fields
            self.tool_wd_var.set(ent.working_dir)
            self.args_var.set(ent.args)
            self.env_var.set(ent.env)
            self.open_console_var.set(ent.open_in_console)
            return
        p = ent.presets.get(name)
        if not p:
            return
        self.tool_wd_var.set(p.working_dir)
        self.args_var.set(p.args)
        self.env_var.set(p.env)
        self.open_console_var.set(p.open_in_console)

    def on_save_preset(self):
        if not self.selected_tool_id:
            return
        name = simple_input(self, "Preset name", "Enter new preset name:")
        if not name:
            return
        ent = self.catalog.tools[self.selected_tool_id]
        ent.presets[name] = ToolPreset(
            name=name,
            working_dir=self.tool_wd_var.get(),
            args=self.args_var.get(),
            env=self.env_var.get(),
            open_in_console=bool(self.open_console_var.get()),
        )
        names = ["Main"] + sorted([n for n in ent.presets.keys() if n != "Main"]) 
        self.preset_combo["values"] = names
        self.preset_var.set(name)
        self.status_var.set(f"Preset saved: {name}")

    def on_delete_preset(self):
        if not self.selected_tool_id:
            return
        name = self.preset_var.get()
        if name in (None, "", "Main"):
            return
        ent = self.catalog.tools[self.selected_tool_id]
        if name in ent.presets:
            del ent.presets[name]
            names = ["Main"] + sorted([n for n in ent.presets.keys() if n != "Main"]) 
            self.preset_combo["values"] = names
            self.preset_var.set("Main")
            self.status_var.set(f"Preset deleted: {name}")

    # ---------- Poller ----------
    def _ui_poller(self):
        # process job queues and status
        to_remove = []
        for pid, job in list(self.jobs.items()):
            job.poll()
            # drain queue
            drained = False
            while True:
                try:
                    line = job.queue.get_nowait()
                except queue.Empty:
                    break
                drained = True
                self._log_buffers[pid].append(line)
                # trim buffer
                if len(self._log_buffers[pid]) > 1000:
                    self._log_buffers[pid] = self._log_buffers[pid][-1000:]
                # if this job is selected, append to text
                sel = self.jobs_tree.selection()
                if sel and sel[0] == str(pid):
                    self.log_text.insert(tk.END, line)
                    self.log_text.see(tk.END)
            # update elapsed & status
            start_dt = datetime.datetime.fromtimestamp(job.start_time)
            elapsed = datetime.datetime.now() - start_dt
            elapsed_str = str(elapsed).split('.')[0]
            vals = self.jobs_tree.item(str(pid), 'values') if self.jobs_tree.exists(str(pid)) else None
            if vals:
                new_vals = list(vals)
                new_vals[2] = job.status
                new_vals[4] = elapsed_str
                new_vals[6] = "" if job.exit_code is None else str(job.exit_code)
                self.jobs_tree.item(str(pid), values=new_vals)
            if job.status == "exited":
                # persist last run status
                ent = job.tool
                ent.last_run_status = "success" if (job.exit_code == 0) else "failed"
                ent.last_exit_code = str(job.exit_code)
                ent.last_run_time = datetime.datetime.now().isoformat(timespec='seconds')
                to_remove.append(pid)
        # remove finished jobs from dict (leave row for historical view for this session)
        for pid in to_remove:
            # keep the row; just remove job handle
            del self.jobs[pid]
        # start queued if throttled
        self._maybe_start_queued()
        self._update_status_bar()
        self.after(200, self._ui_poller)

    def _maybe_start_queued(self):
        limit = int(self.catalog.global_settings.get("concurrency_limit", "0") or 0)
        if not limit:
            return
        running = len([1 for j in self.jobs.values() if j.status == "running"]) if self.jobs else 0
        while self.pending_jobs and running < limit:
            ent, d = self.pending_jobs.pop(0)
            job = Job(ent, d["cmd"], d["wd"], d["env"], d["log"], d["open"])
            job.start()
            if job.proc:
                pid = job.proc.pid
                self.jobs[pid] = job
                self._log_buffers[pid] = []
                self._add_job_row(job)
                running += 1

    def _update_status_bar(self):
        running = len([1 for j in self.jobs.values() if j.status == "running"]) if self.jobs else 0
        idle = len(self.jobs) - running
        sysinfo = "N/A"
        if psutil:
            try:
                cpu = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory().percent
                sysinfo = f"CPU {cpu:.0f}% | RAM {mem:.0f}%"
            except Exception:
                sysinfo = "N/A"
        self.status_var.set(f"Running {running} | Idle {idle} | {sysinfo}")

    def _selected_job(self) -> Optional[Job]:
        sel = self.jobs_tree.selection()
        if not sel:
            return None
        pid = int(sel[0])
        return self.jobs.get(pid)

    def _display_log_buffer(self, pid: int):
        self.log_text.delete('1.0', tk.END)
        for line in self._log_buffers.get(pid, []):
            self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)

    # ---------- Parsing & Expansion ----------
    def _expand_placeholders(self, s: str, ent: ToolEntry) -> str:
        if not s:
            return s
        mapping = {
            "{tool_dir}": ent.tool_dir(self.catalog.scan_root or ""),
            "{scan_root}": self.catalog.scan_root or "",
            "{app_dir}": APP_DIR,
        }
        for k, v in mapping.items():
            s = s.replace(k, v)
        return s

    def _parse_env(self, s: str) -> Dict[str, str]:
        env = {}
        if not s:
            return env
        for part in s.split(';'):
            part = part.strip()
            if not part:
                continue
            if '=' in part:
                k, v = part.split('=', 1)
                env[k.strip()] = v.strip()
        return env

    def _shell_split(self, s: str) -> List[str]:
        # simple splitter honoring quotes
        return re.findall(r'\"([^\"]*)\"|\'([^\']*)\'|([^\s]+)', s)

# Simple input dialog
class SimpleInputDialog(tk.Toplevel):
    def __init__(self, master, title, prompt):
        super().__init__(master)
        self.title(title)
        self.result = None
        ttk.Label(self, text=prompt).pack(padx=10, pady=10)
        self.var = tk.StringVar()
        ent = ttk.Entry(self, textvariable=self.var, width=40)
        ent.pack(padx=10, pady=(0,10))
        btns = ttk.Frame(self)
        btns.pack(pady=10)
        ttk.Button(btns, text="OK", command=self._ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btns, text="Cancel", command=self._cancel).pack(side=tk.LEFT, padx=5)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.grab_set()
        ent.focus_set()
        self.geometry("400x140")

    def _ok(self):
        self.result = self.var.get().strip()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def simple_input(master, title, prompt) -> Optional[str]:
    dlg = SimpleInputDialog(master, title, prompt)
    master.wait_window(dlg)
    return dlg.result


if __name__ == "__main__":
    app = App()
    app.mainloop()
