import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.core.config import AppConfig
from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.core.log_setup import get_logger
from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.utils.bids import list_bids_subjects
from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.utils.file_ops import ensure_dir
from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.features.participants.participants_feature import ParticipantsTSVFeature, ParticipantsFeatureSettings


class AppState:
    def __init__(self) -> None:
        self.config = AppConfig.load_or_create()
        self.logger = get_logger(self.config)
        self.subjects_cached: list[str] = []


class LabeledEntry(ttk.Frame):
    def __init__(self, parent, label: str, width: int = 60):
        super().__init__(parent)
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text=label).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.grid(row=0, column=1, sticky="ew")

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(value or "")


class BrowseRow(ttk.Frame):
    def __init__(self, parent, label: str, browse_kind: str, initial: str = ""):
        super().__init__(parent)
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text=label).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.var = tk.StringVar(value=initial)
        self.entry = ttk.Entry(self, textvariable=self.var, width=70)
        self.entry.grid(row=0, column=1, sticky="ew")

        def on_browse():
            if browse_kind == "dir":
                path = filedialog.askdirectory()
            elif browse_kind == "file_excel":
                path = filedialog.askopenfilename(
                    title="Select Excel file",
                    filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")],
                )
            else:
                path = filedialog.askopenfilename()

            if path:
                self.var.set(path)

        ttk.Button(self, text="Browse...", command=on_browse).grid(row=0, column=2, padx=(8, 0))

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(value or "")


class StatusBox(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        ttk.Label(self, text="Status / Log").pack(anchor="w")
        self.text = tk.Text(self, height=10, wrap="word")
        self.text.pack(fill="both", expand=True)
        self.text.configure(state="disabled")

    def write(self, msg: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", msg + "\n")
        self.text.see("end")
        self.text.configure(state="disabled")


def run_app() -> None:
    state = AppState()

    root = tk.Tk()
    root.title("BIDS Augmentor")
    root.geometry("1000x720")

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    main = ttk.Frame(root, padding=12)
    main.pack(fill="both", expand=True)

    notebook = ttk.Notebook(main)
    notebook.pack(fill="both", expand=True)

    status = StatusBox(main)
    status.pack(fill="both", expand=False, pady=(10, 0))

    # -------------------------
    # General tab
    # -------------------------
    tab_general = ttk.Frame(notebook, padding=12)
    notebook.add(tab_general, text="General")

    src_row = BrowseRow(tab_general, "Source BIDS folder:", "dir", state.config.general.source_bids_dir)
    src_row.pack(fill="x", pady=6)

    aug_row = BrowseRow(tab_general, "Augmented output folder:", "dir", state.config.general.augmented_dir)
    aug_row.pack(fill="x", pady=6)

    feature_copy_existing_var = tk.BooleanVar(value=state.config.general.copy_existing_files)
    chk_copy = ttk.Checkbutton(
        tab_general,
        text="If augmented is missing participants.tsv, allow copying from source participants.tsv (optional).",
        variable=feature_copy_existing_var,
    )
    chk_copy.pack(anchor="w", pady=(6, 6))

    subjects_label = ttk.Label(tab_general, text="Subjects detected: (not scanned yet)")
    subjects_label.pack(anchor="w", pady=(10, 4))

    def scan_subjects() -> None:
        src = src_row.get()
        if not src or not os.path.isdir(src):
            messagebox.showerror("Invalid source", "Please select a valid source BIDS folder.")
            return
        try:
            subs = list_bids_subjects(src)
            state.subjects_cached = subs
            subjects_label.config(
                text=f"Subjects detected: {len(subs)} (e.g., {', '.join(subs[:8])}{'...' if len(subs) > 8 else ''})"
            )
            status.write(f"[General] Found {len(subs)} subject folders in source BIDS.")
            state.logger.info("Scanned subjects in %s: %d", src, len(subs))
        except Exception as e:
            state.logger.exception("Failed to scan subjects")
            messagebox.showerror("Scan failed", str(e))

    ttk.Button(tab_general, text="Scan subjects", command=scan_subjects).pack(anchor="w", pady=6)

    # -------------------------
    # Participants tab
    # -------------------------
    tab_part = ttk.Frame(notebook, padding=12)
    notebook.add(tab_part, text="participants.tsv")

    excel_row = BrowseRow(tab_part, "Demographics Excel file:", "file_excel", state.config.participants.excel_path)
    excel_row.pack(fill="x", pady=6)

    sheet_entry = LabeledEntry(tab_part, "Sheet name (blank = first sheet):")
    sheet_entry.set(state.config.participants.sheet_name)
    sheet_entry.pack(fill="x", pady=6)

    id_col = LabeledEntry(tab_part, "Excel column for subject id:")
    id_col.set(state.config.participants.col_participant_id or "subject")
    id_col.pack(fill="x", pady=6)

    age_col = LabeledEntry(tab_part, "Excel column for age:")
    age_col.set(state.config.participants.col_age or "age")
    age_col.pack(fill="x", pady=6)

    sex_col = LabeledEntry(tab_part, "Excel column for sex:")
    sex_col.set(state.config.participants.col_sex or "sex")
    sex_col.pack(fill="x", pady=6)

    group_col = LabeledEntry(tab_part, "Excel column for group (optional; leave blank if none):")
    group_col.set(state.config.participants.col_group or "")
    group_col.pack(fill="x", pady=6)

    default_group = LabeledEntry(tab_part, "Default group if group column missing/blank:")
    default_group.set(state.config.participants.default_group)
    default_group.pack(fill="x", pady=6)

    # Requirement: fixed ON
    include_only_bids_subjects_var = tk.BooleanVar(value=True)
    chk_only_bids = ttk.Checkbutton(
        tab_part,
        text="Include ONLY subjects that exist in the source BIDS folder (required)",
        variable=include_only_bids_subjects_var,
        state="disabled",
    )
    chk_only_bids.pack(anchor="w", pady=(6, 2))

    duplicate_policy_var = tk.StringVar(value=state.config.participants.duplicate_policy or "last")
    dup_frame = ttk.Frame(tab_part)
    dup_frame.pack(fill="x", pady=6)
    ttk.Label(dup_frame, text="Duplicate subject policy (Excel):").pack(side="left", padx=(0, 10))
    ttk.Radiobutton(dup_frame, text="keep first", variable=duplicate_policy_var, value="first").pack(side="left")
    ttk.Radiobutton(dup_frame, text="keep last", variable=duplicate_policy_var, value="last").pack(side="left")
    ttk.Radiobutton(dup_frame, text="error", variable=duplicate_policy_var, value="error").pack(side="left")

    overwrite_var = tk.BooleanVar(value=state.config.participants.overwrite_in_augmented)
    chk_overwrite = ttk.Checkbutton(
        tab_part,
        text="Overwrite participants.tsv in augmented if it already exists",
        variable=overwrite_var,
    )
    chk_overwrite.pack(anchor="w", pady=(6, 10))

    # Buttons
    btns = ttk.Frame(tab_part)
    btns.pack(fill="x", pady=8)

    def save_config_from_ui() -> None:
        state.config.general.source_bids_dir = src_row.get()
        state.config.general.augmented_dir = aug_row.get()
        state.config.general.copy_existing_files = bool(feature_copy_existing_var.get())

        state.config.participants.excel_path = excel_row.get()
        state.config.participants.sheet_name = sheet_entry.get()
        state.config.participants.col_participant_id = id_col.get() or "subject"
        state.config.participants.col_age = age_col.get() or "age"
        state.config.participants.col_sex = sex_col.get() or "sex"
        state.config.participants.col_group = group_col.get()  # may be blank
        state.config.participants.default_group = default_group.get() or "patient"

        # Enforced requirement
        state.config.participants.include_only_bids_subjects = True

        state.config.participants.duplicate_policy = (duplicate_policy_var.get().strip() or "last")
        state.config.participants.overwrite_in_augmented = bool(overwrite_var.get())

        state.config.save()
        status.write("[Config] Saved config.ini")
        state.logger.info("Saved config.ini")

    ttk.Button(btns, text="Save settings", command=save_config_from_ui).pack(side="left")

    def validate_paths_or_raise():
        src = src_row.get()
        aug = aug_row.get()
        if not src or not os.path.isdir(src):
            raise ValueError("Source BIDS folder is invalid or not selected.")
        if not aug:
            raise ValueError("Augmented output folder is not selected.")
        return src, aug

    def check_participants():
        try:
            save_config_from_ui()
            src, aug = validate_paths_or_raise()
            ensure_dir(aug)

            feature = ParticipantsTSVFeature(logger=state.logger)
            msg = feature.check_status(source_bids_dir=src, augmented_dir=aug)
            status.write(msg)
        except Exception as e:
            state.logger.exception("Check failed")
            messagebox.showerror("Check failed", str(e))

    ttk.Button(btns, text="Check", command=check_participants).pack(side="left", padx=(8, 0))

    def run_participants():
        def _worker():
            try:
                save_config_from_ui()
                src, aug = validate_paths_or_raise()
                ensure_dir(aug)

                # Requirement: always use BIDS subjects from source folder
                subs = list_bids_subjects(src)

                settings = ParticipantsFeatureSettings(
                    excel_path=excel_row.get(),
                    sheet_name=sheet_entry.get(),
                    col_participant_id=id_col.get() or "subject",
                    col_age=age_col.get() or "age",
                    col_sex=sex_col.get() or "sex",
                    col_group=group_col.get(),  # can be blank
                    default_group=default_group.get() or "patient",
                    include_only_bids_subjects=True,
                    bids_subjects=subs,
                    duplicate_policy=duplicate_policy_var.get() or "last",
                    overwrite_in_augmented=bool(overwrite_var.get()),
                    copy_existing_from_source_if_present=bool(feature_copy_existing_var.get()),
                )

                feature = ParticipantsTSVFeature(logger=state.logger)

                status.write("[Run] participants.tsv feature started...")
                result = feature.apply(source_bids_dir=src, augmented_dir=aug, settings=settings)

                status.write(result)
                status.write("[Run] Done.")
            except Exception as e:
                state.logger.exception("Run failed")
                status.write(f"[Run] FAILED: {e}")
                messagebox.showerror("Run failed", str(e))

        threading.Thread(target=_worker, daemon=True).start()

    ttk.Button(btns, text="Run", command=run_participants).pack(side="left", padx=(8, 0))

    ttk.Separator(tab_part).pack(fill="x", pady=12)
    help_txt = (
        "Notes:\n"
        "- Writes ONLY to the augmented folder.\n"
        "- If participants.tsv exists in augmented and overwrite is off, source participants.tsv is not consulted.\n"
        "- Output includes ONLY BIDS subjects (sub-*) found in the source BIDS directory, sorted alphabetically.\n"
        "- If a BIDS subject is missing in Excel, it is still included with blank age/sex.\n"
        "- Sex is normalized to 'm'/'f' when possible.\n"
    )
    ttk.Label(tab_part, text=help_txt, justify="left").pack(anchor="w")

    root.mainloop()
