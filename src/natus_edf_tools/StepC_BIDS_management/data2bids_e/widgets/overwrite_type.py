# -*- coding: utf-8 -*-
"""
overwrite_type.py
Tkinter replacement for the Qt-generated overwrite_type UI.
Provides OverwriteTypeDialog (replaces Ui_Dialog + QDialog mixin).
"""
import tkinter as tk
from tkinter import ttk, filedialog


class _EntryProxy:
    """Mimics QLineEdit: .text() / .setText() / .clear()"""
    def __init__(self, var):
        self._var = var
    def text(self):
        return self._var.get()
    def setText(self, t):
        self._var.set(t)
    def clear(self):
        self._var.set('')


class _ButtonProxy:
    """Mimics QPushButton: .clicked.connect()"""
    def __init__(self, btn):
        self._btn = btn
        self._cbs = []
        btn.configure(command=self._fire)
    def _fire(self):
        for cb in self._cbs: cb()
    class _Sig:
        def __init__(self, owner): self._o = owner
        def connect(self, cb): self._o._cbs.append(cb)
    @property
    def clicked(self): return self._Sig(self)


class _RadioGroupProxy:
    """Mimics QButtonGroup for the two radio buttons."""
    def __init__(self, var): self._var = var
    def setExclusive(self, v): pass  # radios are exclusive by default


class _RadioProxy:
    """Mimics QRadioButton: .isChecked() / .setChecked() / .objectName()"""
    def __init__(self, name, var, value):
        self._name  = name
        self._var   = var
        self._value = value
    def isChecked(self):  return self._var.get() == self._value
    def setChecked(self, v):
        if v: self._var.set(self._value)
        else:
            if self._var.get() == self._value: self._var.set('')
    def objectName(self): return self._name


class _ContainerProxy:
    """Mimics a QWidget container that has .children() returning radio proxies."""
    def __init__(self, radios): self._radios = radios
    def children(self): return self._radios


class Ui_Dialog:
    """
    Tkinter equivalent of the Qt-Designer-generated overwrite_type.Ui_Dialog.
    Call setupUi(dialog_instance) to build the widgets onto a Toplevel.
    Widget attributes mirror the original names used in data2bids_main.py.
    """

    def setupUi(self, Dialog):
        Dialog.title("Convert EDF Type")
        Dialog.resizable(False, False)

        # ── File path row ───────────────────────────────────────────
        row0 = ttk.Frame(Dialog)
        row0.pack(fill='x', padx=10, pady=(10, 0))

        ttk.Label(row0, text="Input file").pack(side='left')

        self._filePath_var = tk.StringVar()
        self._fp_entry = ttk.Entry(row0, textvariable=self._filePath_var, width=60)
        self._fp_entry.pack(side='left', padx=5)

        self._selBtn = ttk.Button(row0, text="Select file...")
        self._selBtn.pack(side='left')

        # ── Radio buttons row ────────────────────────────────────────
        row1 = ttk.LabelFrame(Dialog, text="Convert to EDF type:")
        row1.pack(padx=10, pady=8)

        self._edf_var = tk.StringVar()
        rb_d = ttk.Radiobutton(row1, text="EDF+D", variable=self._edf_var, value="edfD")
        rb_c = ttk.Radiobutton(row1, text="EDF+C", variable=self._edf_var, value="edfC")
        rb_d.pack(side='left', padx=10, pady=4)
        rb_c.pack(side='left', padx=10, pady=4)

        # ── Convert button ───────────────────────────────────────────
        self._convBtn = ttk.Button(Dialog, text="Convert")
        self._convBtn.pack(pady=(0, 10))

        # ── Public proxy attributes (same names as original Qt code) ─
        self.filePath          = _EntryProxy(self._filePath_var)
        self.selectFileButton  = _ButtonProxy(self._selBtn)
        self.convertButton     = _ButtonProxy(self._convBtn)
        self.edfD              = _RadioProxy("edfD", self._edf_var, "edfD")
        self.edfC              = _RadioProxy("edfC", self._edf_var, "edfC")
        self.edfTypeButtonGroup = _RadioGroupProxy(self._edf_var)
        self.edfTypeWig        = _ContainerProxy([self.edfD, self.edfC])

    def retranslateUi(self, Dialog):
        pass  # text already set in setupUi


class OverwriteTypeDialog:
    """
    Full dialog object (replaces overwriteTypeDialog in data2bids_main.py).
    Usage: dlg = OverwriteTypeDialog(parent)  →  dlg.exec()
    """

    def __init__(self, parent=None):
        self._parent = parent
        self._win    = None
        self._ui     = Ui_Dialog()
        self._build()

    def _build(self):
        self._win = tk.Toplevel(self._parent)
        self._win.withdraw()
        self._win.protocol("WM_DELETE_WINDOW", self._on_close)
        self._ui.setupUi(self._win)

        # Expose proxy attributes at top level (data2bids_main accesses them
        # via self.overwriteTypePanel.filePath etc.)
        self.filePath           = self._ui.filePath
        self.selectFileButton   = self._ui.selectFileButton
        self.convertButton      = self._ui.convertButton
        self.edfD               = self._ui.edfD
        self.edfC               = self._ui.edfC
        self.edfTypeButtonGroup = self._ui.edfTypeButtonGroup
        self.edfTypeWig         = self._ui.edfTypeWig

    def _on_close(self):
        # Reset radio buttons and clear path (mirrors original closeEvent)
        self._ui._edf_var.set('')
        self._ui._filePath_var.set('')
        if self._win and self._win.winfo_exists():
            self._win.destroy()
        self._win = None

    def exec(self):
        self._build()
        self._win.deiconify()
        self._win.grab_set()
        self._win.wait_window()

    def close(self):
        self._on_close()
