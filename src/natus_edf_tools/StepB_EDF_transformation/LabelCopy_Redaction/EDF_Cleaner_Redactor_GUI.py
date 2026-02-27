#!/usr/bin/env python3
"""
EDF Cleaner / Redactor GUI (Updated)

This GUI can:
  - Blank all EDF+ embedded annotations ("EDF Annotations"/"BDF Annotations" channels)
  - Selectively anonymize EDF+ header sub-fields (patient + recording fields)
  - Copy signal labels (electrode names) from a REFERENCE EDF to a TARGET EDF (1-to-1 mapping)

Output naming (default):
  targetname__redacted__labelsFromRef.edf   (same folder as target)

Requires:
  - tkinter (standard library)
  - numpy, tqdm
  - (optional) edflibpy for thorough verification
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os
import sys
import threading
import queue
import logging
from datetime import datetime

# Import updated processing module
try:
    from natus_edf_tools.StepB_EDF_transformation.LabelCopy_Redaction.aux_EDF_Cleaner_Redactor import (
        anonymize_edf_complete,
        validate_anonymized_file,
        run_verification,
        compare_edf_signal_labels,
        build_default_output_path,
    )
except ImportError:
    print("Error: Could not import aux_EDF_Cleaner_Redactor.py")
    print("Make sure the file is in the same directory as this GUI (or update the import).")
    sys.exit(1)


class TextHandler(logging.Handler):
    """Custom logging handler that writes to a tkinter Text widget"""

    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.queue = queue.Queue()

    def emit(self, record):
        msg = self.format(record)
        self.queue.put(msg)


class EDFRedactorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("EDF Cleaner / Redactor Tool")
        self.root.geometry("980x820")

        # ==========================
        # Variables
        # ==========================
        self.ref_path = tk.StringVar()
        self.target_path = tk.StringVar()
        self.output_path = tk.StringVar()

        self.buffer_size = tk.IntVar(value=64)

        # Core operations
        self.copy_labels = tk.BooleanVar(value=True)
        self.blank_annotations = tk.BooleanVar(value=True)

        # Selective header anonymization (defaults chosen to match old behavior for patient field)
        self.anon_patientname = tk.BooleanVar(value=True)
        self.anon_patientcode = tk.BooleanVar(value=True)
        self.anon_birthdate = tk.BooleanVar(value=True)
        self.anon_gender = tk.BooleanVar(value=True)

        self.anon_recording_additional = tk.BooleanVar(value=False)
        self.anon_admincode = tk.BooleanVar(value=False)
        self.anon_technician = tk.BooleanVar(value=False)
        self.anon_equipment = tk.BooleanVar(value=False)

        # Verification
        self.verify_enabled = tk.BooleanVar(value=True)
        self.verify_level = tk.StringVar(value="thorough")

        # Logging
        self.log_dir = tk.StringVar(value="logs")
        self.log_level = tk.StringVar(value="INFO")

        # Processing state
        self.is_processing = False
        self.processing_thread = None

        # Build UI
        self.create_widgets()
        self.root.minsize(900, 500)

        # Start log queue polling
        self.root.after(100, self.poll_log_queue)

    # ==========================
    # UI construction
    # ==========================
    def create_widgets(self):
        main = ttk.Frame(self.root, padding=8)
        main.grid(row=0, column=0, sticky="nsew")

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(6, weight=1)

        # ===== Title =====
        ttk.Label(
            main,
            text="EDF Cleaner / Redactor Tool",
            font=("Helvetica", 14, "bold")
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        # ======================================================
        # Files (compact 3-row grid)
        # ======================================================
        files = ttk.LabelFrame(main, text="Files", padding=6)
        files.grid(row=1, column=0, columnspan=3, sticky="ew", pady=4)
        files.columnconfigure(1, weight=1)

        def _row(r, label, var, browse_cb):
            ttk.Label(files, text=label).grid(row=r, column=0, sticky="w", padx=4)
            ttk.Entry(files, textvariable=var).grid(row=r, column=1, sticky="ew", padx=4)
            ttk.Button(files, text="Browse", command=browse_cb).grid(row=r, column=2, padx=4)

        _row(0, "Reference EDF", self.ref_path, self.browse_ref)
        _row(1, "Target EDF", self.target_path, self.browse_target)
        _row(2, "Output EDF", self.output_path, self.browse_output)

        # ======================================================
        # Processing options (single compact frame)
        # ======================================================
        opts = ttk.LabelFrame(main, text="Processing", padding=6)
        opts.grid(row=2, column=0, columnspan=3, sticky="ew", pady=4)
        opts.columnconfigure(6, weight=1)

        ttk.Label(opts, text="Buffer (MB)").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(opts, from_=16, to=512, width=6, textvariable=self.buffer_size)\
            .grid(row=0, column=1, sticky="w", padx=(2, 10))

        ttk.Checkbutton(
            opts,
            text="Copy labels (ref → target)",
            variable=self.copy_labels
        ).grid(row=0, column=2, sticky="w", padx=5)

        ttk.Checkbutton(
            opts,
            text="Blank EDF+ annotations",
            variable=self.blank_annotations
        ).grid(row=0, column=3, sticky="w", padx=5)

        # ======================================================
        # Header anonymization (tight 2×4 grid)
        # ======================================================
        anon = ttk.LabelFrame(main, text="Header anonymization (EDF+)", padding=6)
        anon.grid(row=3, column=0, columnspan=3, sticky="ew", pady=4)
        anon.columnconfigure((0,1,2,3), weight=1)

        checks = [
            ("patientname", self.anon_patientname),
            ("patientcode", self.anon_patientcode),
            ("birthdate", self.anon_birthdate),
            ("gender", self.anon_gender),
            ("recording_additional", self.anon_recording_additional),
            ("admincode", self.anon_admincode),
            ("technician", self.anon_technician),
            ("equipment", self.anon_equipment),
        ]

        for i, (label, var) in enumerate(checks):
            ttk.Checkbutton(
                anon,
                text=label,
                variable=var
            ).grid(row=i//4, column=i%4, sticky="w", padx=6, pady=2)

        # ======================================================
        # Logging + Verification (single row)
        # ======================================================
        lv = ttk.LabelFrame(main, text="Logging / Verification", padding=6)
        lv.grid(row=4, column=0, columnspan=3, sticky="ew", pady=4)
        lv.columnconfigure(1, weight=1)

        ttk.Label(lv, text="Log dir").grid(row=0, column=0, sticky="w")
        ttk.Entry(lv, textvariable=self.log_dir, width=25)\
            .grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(lv, text="Browse", command=self.browse_log_dir)\
            .grid(row=0, column=2, padx=4)

        ttk.Label(lv, text="Level").grid(row=0, column=3, sticky="w", padx=(10,2))
        ttk.Combobox(
            lv,
            textvariable=self.log_level,
            values=["DEBUG", "INFO", "WARNING", "ERROR"],
            width=8,
            state="readonly"
        ).grid(row=0, column=4, sticky="w")

        ttk.Checkbutton(
            lv,
            text="Verify",
            variable=self.verify_enabled
        ).grid(row=0, column=5, sticky="w", padx=(12,4))

        ttk.Radiobutton(lv, text="Basic", variable=self.verify_level, value="basic")\
            .grid(row=0, column=6, sticky="w")
        ttk.Radiobutton(lv, text="Full", variable=self.verify_level, value="thorough")\
            .grid(row=0, column=7, sticky="w")

        # ======================================================
        # Progress + log
        # ======================================================
        prog = ttk.LabelFrame(main, text="Progress", padding=6)
        prog.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=4)
        prog.columnconfigure(0, weight=1)
        prog.rowconfigure(2, weight=1)

        btns = ttk.Frame(prog)
        btns.grid(row=0, column=0, sticky="w")

        self.start_button = ttk.Button(btns, text="Run", command=self.start_processing)
        self.start_button.grid(row=0, column=0, padx=4)

        self.stop_button = ttk.Button(btns, text="Stop", command=self.stop_processing, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=4)

        self.progress_bar = ttk.Progressbar(prog, mode="indeterminate")
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=4)

        self.log_text = scrolledtext.ScrolledText(prog, height=14, wrap=tk.WORD)
        self.log_text.grid(row=2, column=0, sticky="nsew")

        self.setup_logging_to_gui()


    # ==========================
    # File browsing helpers
    # ==========================
    def browse_ref(self):
        path = filedialog.askopenfilename(
            title="Select Reference EDF",
            filetypes=[("EDF files", "*.edf"), ("All files", "*.*")]
        )
        if path:
            self.ref_path.set(path)

    def browse_target(self):
        path = filedialog.askopenfilename(
            title="Select Target EDF",
            filetypes=[("EDF files", "*.edf"), ("All files", "*.*")]
        )
        if path:
            self.target_path.set(path)
            self._set_default_output()

    def browse_output(self):
        default = self.output_path.get() or ""
        folder = os.path.dirname(default) if default else os.getcwd()
        initial = os.path.basename(default) if default else "output.edf"
        path = filedialog.asksaveasfilename(
            title="Save Output EDF As",
            initialdir=folder,
            initialfile=initial,
            defaultextension=".edf",
            filetypes=[("EDF files", "*.edf"), ("All files", "*.*")]
        )
        if path:
            self.output_path.set(path)

    def browse_log_dir(self):
        path = filedialog.askdirectory(title="Select Log Directory")
        if path:
            self.log_dir.set(path)

    def _set_default_output(self):
        tgt = self.target_path.get()
        if not tgt:
            return
        self.output_path.set(build_default_output_path(tgt))

    def _on_copy_labels_toggle(self):
        # If user disables copy, reference EDF becomes optional
        pass

    # ==========================
    # Logging to GUI
    # ==========================
    def setup_logging_to_gui(self):
        self.text_handler = TextHandler(self.log_text)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        self.text_handler.setFormatter(formatter)

        self.gui_logger = logging.getLogger("gui")
        self.gui_logger.setLevel(logging.DEBUG)

        for h in list(self.gui_logger.handlers):
            self.gui_logger.removeHandler(h)

        self.gui_logger.addHandler(self.text_handler)

        # Also ensure root logger logs into GUI (handy for module logging)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(self.text_handler)

    def poll_log_queue(self):
        try:
            while True:
                msg = self.text_handler.queue.get_nowait()
                self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_log_queue)

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)

    def log_message(self, message, level="INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {level}: {message}\n")
        self.log_text.see(tk.END)

    # ==========================
    # Validation + Preflight
    # ==========================
    def validate_inputs(self):
        if not self.target_path.get():
            messagebox.showerror("Error", "Please select a TARGET EDF file.")
            return False
        if not os.path.exists(self.target_path.get()):
            messagebox.showerror("Error", "Target EDF file does not exist.")
            return False

        if self.copy_labels.get():
            if not self.ref_path.get():
                messagebox.showerror("Error", "Copy labels is enabled. Please select a REFERENCE EDF file.")
                return False
            if not os.path.exists(self.ref_path.get()):
                messagebox.showerror("Error", "Reference EDF file does not exist.")
                return False

        if not self.output_path.get():
            self._set_default_output()

        out = self.output_path.get()
        if not out:
            messagebox.showerror("Error", "Please specify an output file path.")
            return False

        out_dir = os.path.dirname(out)
        if out_dir and not os.path.exists(out_dir):
            create = messagebox.askyesno(
                "Create Directory?",
                f"Output directory does not exist:\n{out_dir}\n\nCreate it?"
            )
            if create:
                try:
                    os.makedirs(out_dir, exist_ok=True)
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to create directory:\n{e}")
                    return False
            else:
                return False

        # Overwrite check
        if os.path.exists(out):
            overwrite = messagebox.askyesno(
                "Overwrite Output?",
                f"Output file already exists:\n{out}\n\nOverwrite?"
            )
            if not overwrite:
                return False

        return True

    def _build_anonymize_options(self):
        return {
            "patientname": bool(self.anon_patientname.get()),
            "patientcode": bool(self.anon_patientcode.get()),
            "birthdate": bool(self.anon_birthdate.get()),
            "gender": bool(self.anon_gender.get()),
            "recording_additional": bool(self.anon_recording_additional.get()),
            "admincode": bool(self.anon_admincode.get()),
            "technician": bool(self.anon_technician.get()),
            "equipment": bool(self.anon_equipment.get()),
        }

    def show_preflight_dialog(self, stats: dict):
        dlg = tk.Toplevel(self.root)
        dlg.title("Preflight: label similarity & confirmation")
        dlg.geometry("900x600")
        dlg.transient(self.root)
        dlg.grab_set()

        ok_var = tk.BooleanVar(value=False)

        info = []
        info.append("=== Preflight: Signal label comparison (excluding annotation channels) ===")
        info.append("=== Preflight: Signal label comparison (differences will be fixed if you proceed) ===")

        info.append(f"Reference: {stats['ref_path']}")
        info.append(f"Target   : {stats['target_path']}")
        info.append(f"Signals  : {stats['num_signals']}  (non-annot={stats['num_non_annot']}, annot_idx={stats['annot_channels']})")
        info.append(f"Matches  : {stats['num_matches']}")
        info.append(f"Mismatches: {stats['num_mismatches']}")
        info.append("")
        info.append("Matching channels (requested list):")
        info.extend(["  " + s for s in stats["matches"]])

        if stats["mismatches"]:
            info.append("")
            info.append("Mismatching channels (for your reference):")
            info.extend(["  " + s for s in stats["mismatches"]])

        txt = scrolledtext.ScrolledText(dlg, wrap=tk.WORD)
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        txt.insert(tk.END, "\n".join(info))
        txt.configure(state="disabled")

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        def proceed():
            ok_var.set(True)
            dlg.destroy()

        def cancel():
            ok_var.set(False)
            dlg.destroy()

        ttk.Button(btn_frame, text="Cancel", command=cancel).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Proceed", command=proceed).pack(side=tk.RIGHT, padx=5)

        self.root.wait_window(dlg)
        return bool(ok_var.get())

    # ==========================
    # Processing
    # ==========================
    def start_processing(self):
        if not self.validate_inputs():
            return

        # Preflight stats + confirmation (required before proceeding)
        if self.ref_path.get():
            try:
                stats = compare_edf_signal_labels(self.ref_path.get(), self.target_path.get(), require_strict_structure_match=False)
            except Exception as e:
                messagebox.showerror("Preflight Error", f"Cannot proceed due to EDF structure mismatch or read error:\n\n{e}")
                return

            proceed = self.show_preflight_dialog(stats)
            if not proceed:
                self.log_message("Canceled by user at preflight confirmation.", "INFO")
                return
        else:
            # If no ref, user still wants to proceed (copy_labels disabled)
            proceed = messagebox.askyesno(
                "Confirm",
                "No reference EDF selected.\n\nProceed without label mapping?"
            )
            if not proceed:
                return

        # Disable/enable UI
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.is_processing = True

        # Start progress indicator
        self.progress_bar.start(10)

        # Clear log
        self.clear_log()
        self.log_message("Starting processing...", "INFO")

        # Start worker thread
        self.processing_thread = threading.Thread(target=self.process_file, daemon=True)
        self.processing_thread.start()

        self.root.after(200, self.check_processing)

    def stop_processing(self):
        # For safety, we only allow the UI to "stop" future work; the worker thread
        # cannot be forcibly killed safely. This will stop post-processing actions.
        self.is_processing = False
        self.log_message("Stop requested. Waiting for current operation to finish safely...", "WARNING")
        self.stop_button.configure(state="disabled")

    def check_processing(self):
        if self.processing_thread and self.processing_thread.is_alive():
            self.root.after(200, self.check_processing)
            return

        # Thread finished
        self.progress_bar.stop()
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.is_processing = False

    def process_file(self):
        try:
            log_dir = self.log_dir.get().strip() or "logs"
            os.makedirs(log_dir, exist_ok=True)

            # Set up logging level
            lvl = getattr(logging, self.log_level.get(), logging.INFO)
            logging.getLogger().setLevel(lvl)

            anonymize_options = self._build_anonymize_options()

            ok = anonymize_edf_complete(
                self.target_path.get(),
                self.output_path.get(),
                buffer_size_mb=int(self.buffer_size.get()),
                log_dir=log_dir,
                blank_annotations=bool(self.blank_annotations.get()),
                anonymize_options=anonymize_options,
                ref_edf_path=self.ref_path.get() if self.copy_labels.get() else None,
                copy_signal_labels=bool(self.copy_labels.get()),
                require_strict_structure_match=False,
            )

            if not ok:
                self.root.after(0, lambda: self.log_message("✗ Processing FAILED (see logs).", "ERROR"))
                self.root.after(0, lambda: messagebox.showerror("Error", "Processing failed. See log output for details."))
                return

            self.root.after(0, lambda: self.log_message("✓ Processing completed.", "SUCCESS"))

            if self.verify_enabled.get():
                self.root.after(0, lambda: self.log_message("Running verification...", "INFO"))
                if self.verify_level.get() == "basic":
                    verify_ok = validate_anonymized_file(self.target_path.get(), self.output_path.get())
                else:
                    verify_ok = run_verification(self.target_path.get(), self.output_path.get())

                if verify_ok:
                    self.root.after(0, lambda: self.log_message("✓ Verification PASSED", "SUCCESS"))
                else:
                    self.root.after(0, lambda: self.log_message("✗ Verification FAILED (see logs).", "ERROR"))

            self.root.after(0, lambda: self.log_message(f"Output EDF:\n{self.output_path.get()}", "INFO"))
            self.root.after(0, lambda: messagebox.showinfo("Done", "Processing completed successfully."))

        except Exception as e:
            self.root.after(0, lambda: self.log_message(f"Exception: {e}", "ERROR"))
            self.root.after(0, lambda: messagebox.showerror("Error", f"Unexpected error:\n\n{e}"))


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    app = EDFRedactorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
