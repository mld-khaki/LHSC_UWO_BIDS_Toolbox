import os
import threading
from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.core.config import AppConfig
from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.core.log_setup import get_logger
from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.utils.bids import (
    NO_SESSION,
    is_bids_root_dir,
    is_bids_subject_dir,
    list_bids_subjects,
    list_subject_sessions,
    resolve_subject_dir,
    session_has_any_files,
)
from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.utils.file_ops import ensure_dir, safe_copy_tree
from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.features.participants.participants_feature import (
    ParticipantsTSVFeature,
    ParticipantsFeatureSettings,
)


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


class ScrollableFrame(ttk.Frame):
    """A simple scrollable container for many rows."""

    def __init__(self, parent):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)

        self.inner = ttk.Frame(self.canvas)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")

        def _on_inner_config(_event=None):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        def _on_canvas_config(event):
            self.canvas.itemconfig(self.inner_id, width=event.width)

        self.inner.bind("<Configure>", _on_inner_config)
        self.canvas.bind("<Configure>", _on_canvas_config)


@dataclass
class MergeSessionRow:
    session: str
    status: str  # NEW | DUPLICATE
    empty: bool
    action: str  # COPY | MERGE
    selected_var: tk.BooleanVar


def run_app() -> None:
    state = AppState()

    root = tk.Tk()
    root.title("BIDS Augmentor")
    root.geometry("1100x760")

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

    sheet_entry = LabeledEntry(tab_part, "Excel sheet name:", width=30)
    sheet_entry.set(state.config.participants.sheet_name)
    sheet_entry.pack(fill="x", pady=6)

    ttk.Separator(tab_part).pack(fill="x", pady=10)

    ttk.Label(tab_part, text="Excel column mapping", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")

    id_col = LabeledEntry(tab_part, "Participant ID column (required):")
    id_col.set(state.config.participants.col_participant_id)
    id_col.pack(fill="x", pady=4)

    age_col = LabeledEntry(tab_part, "Age column:")
    age_col.set(state.config.participants.col_age)
    age_col.pack(fill="x", pady=4)

    sex_col = LabeledEntry(tab_part, "Sex column:")
    sex_col.set(state.config.participants.col_sex)
    sex_col.pack(fill="x", pady=4)

    group_col = LabeledEntry(tab_part, "Group column (optional):")
    group_col.set(state.config.participants.col_group)
    group_col.pack(fill="x", pady=4)

    default_group = LabeledEntry(tab_part, "Default group value (if group column missing or blank):", width=30)
    default_group.set(state.config.participants.default_group)
    default_group.pack(fill="x", pady=4)

    ttk.Separator(tab_part).pack(fill="x", pady=10)

    overwrite_var = tk.BooleanVar(value=state.config.participants.overwrite_in_augmented)
    ttk.Checkbutton(
        tab_part,
        text="Overwrite participants.tsv in augmented folder (if it already exists)",
        variable=overwrite_var,
    ).pack(anchor="w", pady=(0, 6))

    duplicate_policy_var = tk.StringVar(value=(state.config.participants.duplicate_policy or "last").strip())
    dup_row = ttk.Frame(tab_part)
    dup_row.pack(fill="x", pady=4)
    ttk.Label(dup_row, text="Excel duplicate participant_id policy:").pack(side="left")
    ttk.Combobox(
        dup_row,
        width=12,
        textvariable=duplicate_policy_var,
        values=["first", "last", "error"],
        state="readonly",
    ).pack(side="left", padx=(8, 0))

    btns = ttk.Frame(tab_part)
    btns.pack(anchor="w", pady=(10, 6))

    def save_config_from_ui() -> None:
        # General
        state.config.general.source_bids_dir = src_row.get()
        state.config.general.augmented_dir = aug_row.get()
        state.config.general.copy_existing_files = bool(feature_copy_existing_var.get())

        # Participants
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
            raise ValueError("Please select a valid Source BIDS folder in the General tab.")
        if not aug:
            raise ValueError("Please select an Augmented output folder in the General tab.")
        ensure_dir(aug)
        return src, aug

    def run_participants() -> None:
        def _worker():
            try:
                src, aug = validate_paths_or_raise()

                # Enforce: only BIDS subjects present in BIDS folder
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

    # -------------------------
    # Merge BIDS folders tab
    # -------------------------
    tab_merge = ttk.Frame(notebook, padding=12)
    notebook.add(tab_merge, text="Merge BIDS folders")

    ttk.Label(
        tab_merge,
        text=(
            "Merge two folders containing the SAME subject into one destination.\n"
            "You can select either a BIDS root (contains sub-*) or a direct subject folder (sub-XXX).\n"
            "Dry run will flag duplicates and empty sessions, and you can select sessions individually."
        ),
        justify="left",
    ).pack(anchor="w", pady=(0, 10))

    merge_cfg = state.config.merge

    row_a = BrowseRow(tab_merge, "Folder A (BIDS root or sub-XXX):", "dir", merge_cfg.path_a)
    row_a.pack(fill="x", pady=6)

    subj_a_var = tk.StringVar(value=merge_cfg.subject_a or "")
    subj_a_row = ttk.Frame(tab_merge)
    subj_a_row.pack(fill="x", pady=(0, 6))
    ttk.Label(subj_a_row, text="Subject in Folder A:").pack(side="left")
    subj_a_combo = ttk.Combobox(subj_a_row, textvariable=subj_a_var, width=20, state="readonly")
    subj_a_combo.pack(side="left", padx=(8, 0))

    row_b = BrowseRow(tab_merge, "Folder B (BIDS root or sub-XXX):", "dir", merge_cfg.path_b)
    row_b.pack(fill="x", pady=6)

    subj_b_var = tk.StringVar(value=merge_cfg.subject_b or "")
    subj_b_row = ttk.Frame(tab_merge)
    subj_b_row.pack(fill="x", pady=(0, 6))
    ttk.Label(subj_b_row, text="Subject in Folder B:").pack(side="left")
    subj_b_combo = ttk.Combobox(subj_b_row, textvariable=subj_b_var, width=20, state="readonly")
    subj_b_combo.pack(side="left", padx=(8, 0))

    dest_var = tk.StringVar(value=(merge_cfg.destination or "A").strip().upper()[:1] or "A")
    dest_row = ttk.Frame(tab_merge)
    dest_row.pack(fill="x", pady=(8, 4))
    ttk.Label(dest_row, text="Destination:").pack(side="left")
    ttk.Radiobutton(dest_row, text="Use Folder A as destination", variable=dest_var, value="A").pack(
        side="left", padx=(10, 0)
    )
    ttk.Radiobutton(dest_row, text="Use Folder B as destination", variable=dest_var, value="B").pack(
        side="left", padx=(10, 0)
    )

    overwrite_dup_var = tk.BooleanVar(value=bool(merge_cfg.overwrite_on_duplicates))
    select_dup_default_var = tk.BooleanVar(value=bool(merge_cfg.default_select_duplicates))
    select_empty_default_var = tk.BooleanVar(value=bool(merge_cfg.default_select_empty))

    opts = ttk.Frame(tab_merge)
    opts.pack(fill="x", pady=(8, 8))
    ttk.Checkbutton(
        opts,
        text="Overwrite files when merging duplicates (otherwise keep destination files)",
        variable=overwrite_dup_var,
    ).pack(anchor="w", pady=2)
    ttk.Checkbutton(opts, text="Select duplicates by default", variable=select_dup_default_var).pack(
        anchor="w", pady=2
    )
    ttk.Checkbutton(opts, text="Select empty sessions by default", variable=select_empty_default_var).pack(
        anchor="w", pady=2
    )

    analysis_summary = ttk.Label(tab_merge, text="Dry run summary: (not analyzed yet)")
    analysis_summary.pack(anchor="w", pady=(6, 4))

    list_container = ScrollableFrame(tab_merge)
    list_container.pack(fill="both", expand=True, pady=(6, 6))

    # Header
    hdr = ttk.Frame(list_container.inner)
    hdr.pack(fill="x")
    ttk.Label(hdr, text="Select", width=8).grid(row=0, column=0, sticky="w")
    ttk.Label(hdr, text="Session", width=18).grid(row=0, column=1, sticky="w")
    ttk.Label(hdr, text="Status", width=12).grid(row=0, column=2, sticky="w")
    ttk.Label(hdr, text="Empty?", width=10).grid(row=0, column=3, sticky="w")
    ttk.Label(hdr, text="Action", width=10).grid(row=0, column=4, sticky="w")
    ttk.Separator(list_container.inner).pack(fill="x", pady=(2, 6))

    merge_rows: list[MergeSessionRow] = []

    def _clear_session_rows():
        nonlocal merge_rows
        merge_rows = []
        for child in list_container.inner.winfo_children():
            # keep header rows (hdr + first separator) => they were created before
            # easiest: destroy everything then rebuild header
            pass

        # Destroy all, then rebuild header+separator
        for child in list_container.inner.winfo_children():
            child.destroy()

        hdr2 = ttk.Frame(list_container.inner)
        hdr2.pack(fill="x")
        ttk.Label(hdr2, text="Select", width=8).grid(row=0, column=0, sticky="w")
        ttk.Label(hdr2, text="Session", width=18).grid(row=0, column=1, sticky="w")
        ttk.Label(hdr2, text="Status", width=12).grid(row=0, column=2, sticky="w")
        ttk.Label(hdr2, text="Empty?", width=10).grid(row=0, column=3, sticky="w")
        ttk.Label(hdr2, text="Action", width=10).grid(row=0, column=4, sticky="w")
        ttk.Separator(list_container.inner).pack(fill="x", pady=(2, 6))

    def _populate_subject_combo(bids_path: str, combo: ttk.Combobox, var: tk.StringVar) -> None:
        path = (bids_path or "").strip()
        if not path or not os.path.isdir(path):
            combo["values"] = []
            var.set("")
            combo.configure(state="disabled")
            return

        path = os.path.abspath(path)
        if is_bids_subject_dir(path):
            sid = os.path.basename(path)
            combo["values"] = [sid]
            var.set(sid)
            combo.configure(state="disabled")
            return

        if is_bids_root_dir(path):
            subs = list_bids_subjects(path)
            combo["values"] = subs
            # keep existing if valid
            cur = (var.get() or "").strip()
            if cur and cur in subs:
                var.set(cur)
            else:
                var.set(subs[0] if subs else "")
            combo.configure(state="readonly" if subs else "disabled")
            return

        combo["values"] = []
        var.set("")
        combo.configure(state="disabled")

    def refresh_subjects():
        _populate_subject_combo(row_a.get(), subj_a_combo, subj_a_var)
        _populate_subject_combo(row_b.get(), subj_b_combo, subj_b_var)

    # auto-refresh on path changes (when Browse... sets the var)
    row_a.var.trace_add("write", lambda *_: refresh_subjects())
    row_b.var.trace_add("write", lambda *_: refresh_subjects())

    # initial refresh
    refresh_subjects()

    def save_merge_config_from_ui() -> None:
        state.config.merge.path_a = row_a.get()
        state.config.merge.path_b = row_b.get()
        state.config.merge.subject_a = (subj_a_var.get() or "").strip()
        state.config.merge.subject_b = (subj_b_var.get() or "").strip()
        state.config.merge.destination = (dest_var.get() or "A").strip().upper()[:1] or "A"
        state.config.merge.overwrite_on_duplicates = bool(overwrite_dup_var.get())
        state.config.merge.default_select_duplicates = bool(select_dup_default_var.get())
        state.config.merge.default_select_empty = bool(select_empty_default_var.get())
        state.config.save()
        status.write("[Config] Saved config.ini (merge settings)")
        state.logger.info("Saved config.ini (merge settings)")

    merge_btns = ttk.Frame(tab_merge)
    merge_btns.pack(anchor="w", pady=(6, 0))

    ttk.Button(merge_btns, text="Save merge settings", command=save_merge_config_from_ui).pack(side="left")
    ttk.Button(merge_btns, text="Refresh subject lists", command=refresh_subjects).pack(side="left", padx=(8, 0))

    def _compute_plan() -> tuple[str, str, str, str, str, list[MergeSessionRow]]:
        path_a = row_a.get()
        path_b = row_b.get()
        if not path_a or not os.path.isdir(path_a):
            raise ValueError("Folder A is not a valid directory.")
        if not path_b or not os.path.isdir(path_b):
            raise ValueError("Folder B is not a valid directory.")

        subj_a = (subj_a_var.get() or "").strip()
        subj_b = (subj_b_var.get() or "").strip()

        subj_dir_a, sid_a = resolve_subject_dir(path_a, subj_a if is_bids_root_dir(path_a) else None)
        subj_dir_b, sid_b = resolve_subject_dir(path_b, subj_b if is_bids_root_dir(path_b) else None)

        if sid_a != sid_b:
            raise ValueError(f"Subject mismatch. Folder A is '{sid_a}' but Folder B is '{sid_b}'. Select the SAME subject.")

        dest_side = (dest_var.get() or "A").strip().upper()[:1]
        if dest_side not in ("A", "B"):
            dest_side = "A"

        if dest_side == "A":
            src_subject_dir = subj_dir_b
            dst_subject_dir = subj_dir_a
            src_side = "B"
            dst_side = "A"
        else:
            src_subject_dir = subj_dir_a
            dst_subject_dir = subj_dir_b
            src_side = "A"
            dst_side = "B"

        # Sessions to consider are those present in the SOURCE side.
        src_sessions = list_subject_sessions(src_subject_dir)

        rows: list[MergeSessionRow] = []

        for sess in src_sessions:
            if sess == NO_SESSION:
                dst_has = session_has_any_files(dst_subject_dir, NO_SESSION)
            else:
                dst_has = os.path.isdir(os.path.join(dst_subject_dir, sess))

            status_txt = "DUPLICATE" if dst_has else "NEW"
            empty = not session_has_any_files(src_subject_dir, sess)

            action = "MERGE" if status_txt == "DUPLICATE" else "COPY"
            if sess == NO_SESSION:
                action = "MERGE" if status_txt == "DUPLICATE" else "COPY"

            default_sel = True if status_txt == "NEW" else bool(select_dup_default_var.get())
            if empty and not bool(select_empty_default_var.get()):
                default_sel = False

            rows.append(
                MergeSessionRow(
                    session=sess,
                    status=status_txt,
                    empty=empty,
                    action=action,
                    selected_var=tk.BooleanVar(value=default_sel),
                )
            )

        return src_side, dst_side, src_subject_dir, dst_subject_dir, sid_a, rows

    def analyze_merge():
        try:
            _clear_session_rows()
            src_side, dst_side, src_subject_dir, dst_subject_dir, sid, rows = _compute_plan()

            merge_rows.clear()
            merge_rows.extend(rows)

            # Render
            for i, r in enumerate(merge_rows):
                rowf = ttk.Frame(list_container.inner)
                rowf.pack(fill="x", pady=1)

                ttk.Checkbutton(rowf, variable=r.selected_var).grid(row=0, column=0, sticky="w", padx=(0, 8))
                sess_label = r.session if r.session != NO_SESSION else "(no ses-* folders)"
                ttk.Label(rowf, text=sess_label, width=18).grid(row=0, column=1, sticky="w")
                ttk.Label(rowf, text=r.status, width=12).grid(row=0, column=2, sticky="w")
                ttk.Label(rowf, text="YES" if r.empty else "NO", width=10).grid(row=0, column=3, sticky="w")
                ttk.Label(rowf, text=r.action, width=10).grid(row=0, column=4, sticky="w")

            # Summary
            total = len(merge_rows)
            selected = sum(1 for r in merge_rows if r.selected_var.get())
            dup = sum(1 for r in merge_rows if r.status == "DUPLICATE")
            empty = sum(1 for r in merge_rows if r.empty)
            new = sum(1 for r in merge_rows if r.status == "NEW")
            analysis_summary.config(
                text=(
                    f"Dry run summary: subject={sid} | source={src_side} -> dest={dst_side} | "
                    f"sessions in source={total} (new={new}, duplicates={dup}, empty={empty}) | selected={selected}"
                )
            )

            status.write("[Merge][Dry run] Source subject dir: " + src_subject_dir)
            status.write("[Merge][Dry run] Destination subject dir: " + dst_subject_dir)
            status.write(
                f"[Merge][Dry run] sessions={total} new={new} duplicates={dup} empty={empty} selected={selected}"
            )
        except Exception as e:
            state.logger.exception("Merge dry run failed")
            analysis_summary.config(text=f"Dry run summary: FAILED: {e}")
            messagebox.showerror("Dry run failed", str(e))

    ttk.Button(merge_btns, text="Analyze / Dry run", command=analyze_merge).pack(side="left", padx=(8, 0))

    def _set_selection(filter_fn, value: bool):
        for r in merge_rows:
            if filter_fn(r):
                r.selected_var.set(value)

    sel_btns = ttk.Frame(tab_merge)
    sel_btns.pack(anchor="w", pady=(4, 8))
    ttk.Button(sel_btns, text="Select all", command=lambda: _set_selection(lambda _r: True, True)).pack(side="left")
    ttk.Button(sel_btns, text="Select none", command=lambda: _set_selection(lambda _r: True, False)).pack(
        side="left", padx=(6, 0)
    )
    ttk.Button(sel_btns, text="Select new", command=lambda: _set_selection(lambda r: r.status == "NEW", True)).pack(
        side="left", padx=(6, 0)
    )
    ttk.Button(
        sel_btns,
        text="Select duplicates",
        command=lambda: _set_selection(lambda r: r.status == "DUPLICATE", True),
    ).pack(side="left", padx=(6, 0))
    ttk.Button(sel_btns, text="Unselect empties", command=lambda: _set_selection(lambda r: r.empty, False)).pack(
        side="left", padx=(6, 0)
    )

    def execute_merge():
        def _worker():
            try:
                if not merge_rows:
                    # Force analysis if user forgot
                    analyze_merge()
                if not merge_rows:
                    raise ValueError("No sessions found to merge.")

                src_side, dst_side, src_subject_dir, dst_subject_dir, sid, _rows = _compute_plan()

                selected_rows = [r for r in merge_rows if r.selected_var.get()]
                if not selected_rows:
                    status.write("[Merge] Nothing selected. Aborting.")
                    return

                dup_selected = sum(1 for r in selected_rows if r.status == "DUPLICATE")
                new_selected = sum(1 for r in selected_rows if r.status == "NEW")
                empty_selected = sum(1 for r in selected_rows if r.empty)

                overwrite = bool(overwrite_dup_var.get())

                msg = (
                    f"You are about to merge subject {sid}\n\n"
                    f"Source: {src_side} -> Destination: {dst_side}\n"
                    f"Selected sessions: {len(selected_rows)} (new={new_selected}, duplicates={dup_selected}, empty={empty_selected})\n\n"
                    f"Overwrite on duplicates: {'YES' if overwrite else 'NO'}\n\n"
                    f"Proceed?"
                )

                if not messagebox.askyesno("Confirm merge", msg):
                    status.write("[Merge] Cancelled by user.")
                    return

                status.write(f"[Merge] Starting merge for subject {sid} ({src_side} -> {dst_side})...")
                state.logger.info("Merge start: subject=%s src=%s dst=%s", sid, src_subject_dir, dst_subject_dir)

                def _ignore_no_session(src_root: str, name: str) -> bool:
                    # for NO_SESSION merges: skip ses-* folders entirely
                    return name.startswith("ses-")

                for r in selected_rows:
                    if r.session == NO_SESSION:
                        src_path = src_subject_dir
                        dst_path = dst_subject_dir
                        stats = safe_copy_tree(
                            src_path,
                            dst_path,
                            overwrite=overwrite if r.status == "DUPLICATE" else False,
                            ignore=_ignore_no_session,
                        )
                        status.write(
                            f"[Merge] {r.action} (no sessions): copied={stats.files_copied} overwritten={stats.files_overwritten} skipped={stats.files_skipped_existing}"
                        )
                        continue

                    src_path = os.path.join(src_subject_dir, r.session)
                    dst_path = os.path.join(dst_subject_dir, r.session)

                    stats = safe_copy_tree(
                        src_path,
                        dst_path,
                        overwrite=overwrite if r.status == "DUPLICATE" else False,
                        ignore=None,
                    )

                    status.write(
                        f"[Merge] {r.action} {r.session}: copied={stats.files_copied} overwritten={stats.files_overwritten} skipped={stats.files_skipped_existing}"
                    )

                status.write("[Merge] Done.")
                state.logger.info("Merge done: subject=%s", sid)

            except Exception as e:
                state.logger.exception("Merge failed")
                status.write(f"[Merge] FAILED: {e}")
                messagebox.showerror("Merge failed", str(e))

        threading.Thread(target=_worker, daemon=True).start()

    ttk.Button(merge_btns, text="Execute merge", command=execute_merge).pack(side="left", padx=(8, 0))

    root.mainloop()
