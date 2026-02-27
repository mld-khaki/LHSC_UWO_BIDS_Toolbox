#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tkinter GUI wrapper / generic file explorer for StepX tools.

Here it integrates TSV Coverage Mapper as a tool:
- Left pane: generic file explorer for the current folder
- Right pane: coverage PNG preview (when TSV Coverage Mapper runs)
- Menu: Tools -> TSV Coverage Mapper (runs CLI on selected TSV file)
"""

from __future__ import annotations

import os
import sys
import tempfile
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

# Import TSV coverage main functionality (for INI helpers and paths)
import natus_edf_tools.StepC_BIDS_management.BIDS_Verification.Coverage_Mapper as mapper


class CoverageMapperGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("StepX GUI – TSV Coverage Mapper")
        self.geometry("1100x700")

        # INI is fully owned by the mapper module; we just use it.
        self.ini_path = mapper._get_ini_path(mapper.__file__)
        self.cfg = mapper._ensure_ini(self.ini_path)

        # State
        self.current_folder = self.cfg.get("General", "last_folder", fallback="").strip()
        if self.current_folder and not os.path.isdir(self.current_folder):
            self.current_folder = ""

        self.current_png_path = ""
        self._imgtk = None  # keep reference for Tk
        self._file_paths = []  # full paths of items in the current folder

        self._build_menu()
        self._build_layout()

        # Initial folder load
        if not self.current_folder:
            self.current_folder = os.getcwd()
        self._load_folder(self.current_folder)

        # If last TSV exists, select it (no auto-run)
        last_tsv = self.cfg.get("General", "last_tsv", fallback="").strip()
        if last_tsv and os.path.isfile(last_tsv):
            self._select_file_in_list(last_tsv)

    # -----------------------------
    # Menu
    # -----------------------------
    def _build_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        tools_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        # Run TSV Coverage Mapper via CLI on the current selection
        tools_menu.add_command(
            label="TSV Coverage Mapper",
            command=self._run_tsv_coverage_mapper,
        )

        help_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self._about)

    def _about(self):
        messagebox.showinfo(
            "About",
            (
                "StepX GUI – TSV Coverage Mapper\n\n"
                "Use the left pane as a generic file explorer.\n"
                "Select a TSV file, then choose Tools → TSV Coverage Mapper\n"
                "to generate a coverage Gantt chart PNG and preview it on the right."
            ),
        )

    # -----------------------------
    # Layout
    # -----------------------------
    def _build_layout(self):
        # Top controls
        top = ttk.Frame(self, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        self.folder_var = tk.StringVar(value=self.current_folder)
        ttk.Label(top, text="Folder:").pack(side=tk.LEFT)
        self.folder_entry = ttk.Entry(top, textvariable=self.folder_var, width=80)
        self.folder_entry.pack(side=tk.LEFT, padx=(6, 6), fill=tk.X, expand=True)
        ttk.Button(top, text="Browse...", command=self._browse_folder).pack(side=tk.LEFT, padx=(6, 0))

        # Main split
        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Left pane: file list + actions
        left = ttk.Frame(main, padding=8)
        main.add(left, weight=1)

        # Renamed: generic explorer
        ttk.Label(left, text="Current folder:").pack(anchor="w")

        self.files_list = tk.Listbox(left, height=18)
        self.files_list.pack(fill=tk.BOTH, expand=True, pady=(6, 6))
        self.files_list.bind("<<ListboxSelect>>", self._on_file_select)
        self.files_list.bind("<Double-Button-1>", self._on_file_double_click)

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X)

        # Explicit run button (same behavior as Tools → TSV Coverage Mapper)
        ttk.Button(
            btn_row,
            text="Run TSV Coverage Mapper",
            command=self._run_tsv_coverage_mapper,
        ).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Refresh", command=self._refresh_files).pack(side=tk.LEFT, padx=(8, 0))

        # Status
        self.status_var = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.status_var, foreground="gray").pack(anchor="w", pady=(10, 0))

        # Right pane: image viewer
        right = ttk.Frame(main, padding=8)
        main.add(right, weight=3)

        ttk.Label(right, text="Coverage PNG preview:").pack(anchor="w")

        self.canvas = tk.Canvas(right, bg="white")
        self.canvas.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        # Make canvas resize update
        self.canvas.bind("<Configure>", lambda e: self._redraw_image())

    # -----------------------------
    # Folder / file handling
    # -----------------------------
    def _browse_folder(self):
        initial = self.folder_var.get().strip() or os.getcwd()
        folder = filedialog.askdirectory(initialdir=initial, title="Select folder")
        if not folder:
            return
        self.folder_var.set(folder)
        self._load_folder(folder)

    def _load_folder(self, folder: str):
        folder = os.path.abspath(folder)
        if not os.path.isdir(folder):
            messagebox.showerror("Error", f"Not a folder:\n{folder}")
            return

        self.current_folder = folder
        self.cfg.set("General", "last_folder", folder)
        mapper._save_cfg(self.cfg, self.ini_path)

        self._refresh_files()
        self.status_var.set(f"Loaded folder: {folder}")

    def _refresh_files(self):
        folder = self.current_folder
        if not folder or not os.path.isdir(folder):
            return

        entries = []
        try:
            for name in os.listdir(folder):
                full_path = os.path.join(folder, name)
                entries.append(full_path)
        except OSError as e:
            messagebox.showerror("Error", f"Failed to list folder:\n{folder}\n\n{e}")
            return

        # Sort by name
        entries.sort(key=lambda p: os.path.basename(p).lower())

        self.files_list.delete(0, tk.END)
        self._file_paths = entries

        for p in entries:
            name = os.path.basename(p)
            # Add a trailing slash for directories for clarity
            if os.path.isdir(p):
                display = f"{name}/"
            else:
                display = name
            self.files_list.insert(tk.END, display)

        if not entries:
            self.status_var.set("Folder is empty.")

    def _select_file_in_list(self, full_path: str):
        full_path = os.path.abspath(full_path)
        if not self._file_paths:
            return
        for i, p in enumerate(self._file_paths):
            if os.path.abspath(p) == full_path:
                self.files_list.selection_clear(0, tk.END)
                self.files_list.selection_set(i)
                self.files_list.see(i)
                # No auto-run; just selection
                self.status_var.set(f"File selected: {full_path}")
                return

    def _on_file_select(self, event=None):
        """
        Selection handler: only updates status, does NOT auto-generate output.
        """
        if not self._file_paths:
            return
        sel = self.files_list.curselection()
        if not sel:
            return
        idx = int(sel[0])
        path = self._file_paths[idx]
        if os.path.isdir(path):
            self.status_var.set(f"Folder selected: {path}")
        else:
            self.status_var.set(f"File selected: {path}")

    def _on_file_double_click(self, event=None):
        """
        Double-click: if a folder is selected, navigate into it.
        """
        if not self._file_paths:
            return
        sel = self.files_list.curselection()
        if not sel:
            return
        idx = int(sel[0])
        path = self._file_paths[idx]
        if os.path.isdir(path):
            self.folder_var.set(path)
            self._load_folder(path)

    # -----------------------------
    # Tool: TSV Coverage Mapper (CLI)
    # -----------------------------
    def _get_selected_file(self) -> Optional[str]:
        if not self._file_paths:
            return None
        sel = self.files_list.curselection()
        if not sel:
            return None
        idx = int(sel[0])
        path = self._file_paths[idx]
        if os.path.isdir(path):
            return None
        return path

    def _run_tsv_coverage_mapper(self):
        """
        Run StepX_Coverage_Mapper.py as a CLI tool via subprocess,
        using the currently selected TSV file.
        """
        tsv_path = self._get_selected_file()
        if not tsv_path:
            messagebox.showerror(
                "No TSV selected",
                "Please select a TSV file in the 'Current folder' pane first.",
            )
            return

        if not tsv_path.lower().endswith(".tsv"):
            messagebox.showerror(
                "Invalid selection",
                "TSV Coverage Mapper only supports files with the .tsv extension.",
            )
            return

        # Ensure INI exists and is clean (tool owns INI semantics)
        self.cfg = mapper._ensure_ini(self.ini_path)

        # Decide output directory:
        # - If output_dir is set in INI, use it
        # - Else: use folder of the TSV
        output_dir = self.cfg.get("General", "output_dir", fallback="").strip()
        if not output_dir:
            output_dir = os.path.dirname(os.path.abspath(tsv_path))
        os.makedirs(output_dir, exist_ok=True)

        base = os.path.splitext(os.path.basename(tsv_path))[0]
        out_png = os.path.join(output_dir, f"{base}_coverage.png")

        # Build CLI command
        python_exe = sys.executable or "python"
        script_path = os.path.abspath(mapper.__file__)

        cmd = [
            python_exe,
            script_path,
            "--tsv",
            tsv_path,
            "--out",
            out_png,
            "--ini",
            self.ini_path,
        ]

        try:
            self.status_var.set("Running TSV Coverage Mapper...")
            self.update_idletasks()

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )
        except Exception as e:
            messagebox.showerror(
                "Execution failed",
                f"Failed to run TSV Coverage Mapper via CLI.\n\n{e}",
            )
            self.status_var.set("TSV Coverage Mapper failed to start.")
            return

        if result.returncode != 0:
            msg = f"TSV Coverage Mapper failed (exit code {result.returncode})."
            if result.stderr:
                msg += f"\n\nStderr:\n{result.stderr.strip()}"
            messagebox.showerror("TSV Coverage Mapper", msg)
            self.status_var.set("TSV Coverage Mapper failed.")
            return

        # Success: update PNG preview
        self.current_png_path = out_png
        self.status_var.set(f"Generated: {out_png}")
        self._redraw_image()

    # -----------------------------
    # Image preview
    # -----------------------------
    def _redraw_image(self):
        if not self.current_png_path or not os.path.isfile(self.current_png_path):
            self.canvas.delete("all")
            return

        try:
            img = Image.open(self.current_png_path)

            # Fit to canvas
            cw = max(1, self.canvas.winfo_width())
            ch = max(1, self.canvas.winfo_height())

            iw, ih = img.size
            scale = min(cw / iw, ch / ih)
            nw = max(1, int(iw * scale))
            nh = max(1, int(ih * scale))

            img_resized = img.resize((nw, nh), Image.LANCZOS)
            self._imgtk = ImageTk.PhotoImage(img_resized)

            self.canvas.delete("all")
            x = (cw - nw) // 2
            y = (ch - nh) // 2
            self.canvas.create_image(x, y, anchor="nw", image=self._imgtk)

        except Exception as e:
            self.canvas.delete("all")
            self.canvas.create_text(
                10,
                10,
                anchor="nw",
                text=f"Failed to render image:\n{e}",
            )


def main():
    # Ensure PIL is available; otherwise tell user
    try:
        _ = Image
    except Exception:
        messagebox.showerror(
            "Missing dependency",
            "Pillow is required for image display.\nInstall: pip install pillow",
        )
        return 1

    app = CoverageMapperGUI()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
