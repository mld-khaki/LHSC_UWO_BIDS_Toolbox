# -*- coding: utf-8 -*-
"""
settings_panel.py
Tkinter replacement for the Qt-Designer-generated settings_panel UI.
All widget attribute names match what data2bids_main.py expects.
"""
import tkinter as tk
from tkinter import ttk


# ── Proxy classes ──────────────────────────────────────────────────────────────

class _EntryProxy:
    """Mimics QLineEdit."""
    def __init__(self, var):
        self._var = var
    def text(self):        return self._var.get()
    def setText(self, t):  self._var.set(t)
    def clear(self):       self._var.set('')


class _CheckProxy:
    """Mimics QCheckBox."""
    def __init__(self, var, widget):
        self._var = var
        self._wgt = widget
        self._clicked_cbs  = []
        self._changed_cbs  = []
        self._var.trace_add('write', self._on_change)
        widget.configure(command=self._on_click)

    def _on_change(self, *_):
        for cb in self._changed_cbs: cb()

    def _on_click(self):
        for cb in self._clicked_cbs: cb()

    def isChecked(self):       return bool(self._var.get())
    def setChecked(self, v):   self._var.set(bool(v))

    class _Sig:
        def __init__(self, lst): self._lst = lst
        def connect(self, cb):   self._lst.append(cb)

    @property
    def clicked(self):       return self._Sig(self._clicked_cbs)
    @property
    def stateChanged(self):  return self._Sig(self._changed_cbs)


class _ButtonBoxProxy:
    """Mimics QDialogButtonBox with accepted/rejected signals."""
    def __init__(self):
        self._accepted = []
        self._rejected = []

    class _Sig:
        def __init__(self, lst): self._lst = lst
        def connect(self, cb):   self._lst.append(cb)

    @property
    def accepted(self): return self._Sig(self._accepted)
    @property
    def rejected(self): return self._Sig(self._rejected)

    def fire_accepted(self):
        for cb in self._accepted: cb()

    def fire_rejected(self):
        for cb in self._rejected: cb()


# ── Ui_Dialog ──────────────────────────────────────────────────────────────────

class Ui_Dialog:
    """Tkinter equivalent of settings_panel.Ui_Dialog."""

    def setupUi(self, Dialog):
        Dialog.title("Settings")
        Dialog.resizable(True, False)

        nb = ttk.Notebook(Dialog)
        nb.pack(fill='both', expand=True, padx=8, pady=8)

        # ── Tab 1: General ────────────────────────────────────────────
        gen_frame = ttk.Frame(nb, padding=8)
        nb.add(gen_frame, text="General")

        self._check_updates_var = tk.BooleanVar(value=True)
        chk = ttk.Checkbutton(gen_frame, text="Check for updates on startup",
                              variable=self._check_updates_var)
        chk.grid(row=0, column=0, columnspan=2, sticky='w', pady=2)
        self.checkUpdates = _CheckProxy(self._check_updates_var, chk)

        ttk.Label(gen_frame, text="Recording labels (comma separated):") \
            .grid(row=1, column=0, sticky='w', pady=2)
        self._rec_labels_var = tk.StringVar()
        rec_entry = ttk.Entry(gen_frame, textvariable=self._rec_labels_var, width=40)
        rec_entry.grid(row=1, column=1, sticky='ew', pady=2)
        self.recordingLabels = _EntryProxy(self._rec_labels_var)

        gen_frame.columnconfigure(1, weight=1)

        # ── Tab 2: Study Metadata ──────────────────────────────────────
        meta_frame = ttk.Frame(nb, padding=8)
        nb.add(meta_frame, text="Study Metadata")

        meta_fields = [
            ("Dataset Name:",          '_ds_name_var',          'textboxDatasetName'),
            ("Experimenter:",          '_experimenter_var',      'textboxExperimenter'),
            ("Lab:",                   '_lab_var',               'textboxLab'),
            ("Institution Name:",      '_inst_name_var',         'textboxInstitutionName'),
            ("Institution Address:",   '_inst_addr_var',         'textboxInstitutionAddress'),
        ]
        for row_idx, (label, varname, attrname) in enumerate(meta_fields):
            ttk.Label(meta_frame, text=label).grid(row=row_idx, column=0, sticky='w', pady=2, padx=4)
            var = tk.StringVar()
            setattr(self, varname, var)
            entry = ttk.Entry(meta_frame, textvariable=var, width=50)
            entry.grid(row=row_idx, column=1, sticky='ew', pady=2, padx=4)
            setattr(self, attrname, _EntryProxy(var))
        meta_frame.columnconfigure(1, weight=1)

        # ── Tab 3: iEEG Electrode Info ────────────────────────────────
        ieeg_frame = ttk.Frame(nb, padding=8)
        nb.add(ieeg_frame, text="iEEG Electrodes")

        ieeg_fields = [
            ("Manufacturer:",  '_ieeg_manuf_var',    'textboxIEEGManufacturer'),
            ("Type:",          '_ieeg_type_var',     'textboxIEEGType'),
            ("Material:",      '_ieeg_mat_var',      'textboxIEEGMaterial'),
            ("Diameter (mm):", '_ieeg_diam_var',     'textboxIEEGDiameter'),
        ]
        for row_idx, (label, varname, attrname) in enumerate(ieeg_fields):
            ttk.Label(ieeg_frame, text=label).grid(row=row_idx, column=0, sticky='w', pady=2, padx=4)
            var = tk.StringVar()
            setattr(self, varname, var)
            entry = ttk.Entry(ieeg_frame, textvariable=var, width=30)
            entry.grid(row=row_idx, column=1, sticky='ew', pady=2, padx=4)
            setattr(self, attrname, _EntryProxy(var))
        ieeg_frame.columnconfigure(1, weight=1)

        # ── Tab 4: EEG Electrode Info ─────────────────────────────────
        eeg_frame = ttk.Frame(nb, padding=8)
        nb.add(eeg_frame, text="EEG Electrodes")

        eeg_fields = [
            ("Manufacturer:",  '_eeg_manuf_var',  'textboxEEGManufacturer'),
            ("Type:",          '_eeg_type_var',   'textboxEEGType'),
            ("Material:",      '_eeg_mat_var',    'textboxEEGMaterial'),
            ("Diameter (mm):", '_eeg_diam_var',   'textboxEEGDiameter'),
        ]
        for row_idx, (label, varname, attrname) in enumerate(eeg_fields):
            ttk.Label(eeg_frame, text=label).grid(row=row_idx, column=0, sticky='w', pady=2, padx=4)
            var = tk.StringVar()
            setattr(self, varname, var)
            entry = ttk.Entry(eeg_frame, textvariable=var, width=30)
            entry.grid(row=row_idx, column=1, sticky='ew', pady=2, padx=4)
            setattr(self, attrname, _EntryProxy(var))
        eeg_frame.columnconfigure(1, weight=1)

        # ── OK / Cancel buttons ───────────────────────────────────────
        btn_frame = ttk.Frame(Dialog)
        btn_frame.pack(fill='x', padx=8, pady=(0, 8))

        self.buttonBoxJson = _ButtonBoxProxy()

        ok_btn     = ttk.Button(btn_frame, text="OK",
                                command=self.buttonBoxJson.fire_accepted)
        cancel_btn = ttk.Button(btn_frame, text="Cancel",
                                command=self.buttonBoxJson.fire_rejected)
        ok_btn.pack(side='right', padx=4)
        cancel_btn.pack(side='right', padx=4)

    def retranslateUi(self, Dialog):
        pass


# ── SettingsDialog ──────────────────────────────────────────────────────────────

class SettingsDialog:
    """
    Full settings dialog (replaces SettingsDialog in data2bids_main.py).
    """

    def __init__(self, parent=None):
        self._parent = parent
        self._win    = None
        self._ui     = Ui_Dialog()
        self._build()

    def _build(self):
        self._win = tk.Toplevel(self._parent)
        self._win.withdraw()
        self._win.protocol("WM_DELETE_WINDOW", self.close)
        self._ui.setupUi(self._win)

        # Wire OK/Cancel to close the window
        self._ui.buttonBoxJson.accepted.connect(self.close)
        self._ui.buttonBoxJson.rejected.connect(self.close)

        # Expose all proxy attributes at top level
        for attr in [
            'checkUpdates', 'recordingLabels',
            'textboxDatasetName', 'textboxExperimenter', 'textboxLab',
            'textboxInstitutionName', 'textboxInstitutionAddress',
            'textboxIEEGManufacturer', 'textboxIEEGType',
            'textboxIEEGMaterial', 'textboxIEEGDiameter',
            'textboxEEGManufacturer', 'textboxEEGType',
            'textboxEEGMaterial', 'textboxEEGDiameter',
            'buttonBoxJson',
        ]:
            setattr(self, attr, getattr(self._ui, attr))

    def exec(self):
        self._build()
        self._win.deiconify()
        self._win.grab_set()
        self._win.wait_window()

    def close(self):
        if self._win and self._win.winfo_exists():
            self._win.destroy()
        self._win = None
