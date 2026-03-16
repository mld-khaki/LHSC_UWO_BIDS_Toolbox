# -*- coding: utf-8 -*-
"""
about_panel.py
Tkinter replacement for the Qt-Designer-generated about_panel UI.
Note: SVG icons are not supported by tkinter – a text label is shown instead.
"""
import tkinter as tk
from tkinter import ttk
import webbrowser


class _LabelProxy:
    """Proxy for labels that need .setText() / .setPixmap()."""
    def __init__(self, lbl):
        self._lbl = lbl
    def setText(self, t):
        self._lbl.configure(text=t)
    def setPixmap(self, *_):
        pass  # SVG pixmap not supported in tkinter


class _LinkWidget:
    """Mimics a read-only QTextBrowser used for clickable hyperlinks."""
    def __init__(self, parent):
        self._url  = ''
        self._lbl  = tk.Label(parent, text='', fg='blue', cursor='hand2',
                              font=('Arial', 10, 'underline'))
        self._lbl.bind('<Button-1>', self._open)

    def pack(self, **kw):
        self._lbl.pack(**kw)

    def setHtml(self, html):
        # Extract href and display text from a simple anchor tag
        import re
        m = re.search(r'href=["\']([^"\']+)["\']', html)
        if m:
            self._url = m.group(1)
        m2 = re.search(r'>([^<]+)</span>', html)
        if m2:
            self._lbl.configure(text=m2.group(1))
        elif m:
            self._lbl.configure(text=self._url)

    def viewport(self):
        """Stub – original code calls .viewport().setAutoFillBackground()."""
        return _NoOp()

    def _open(self, _event):
        if self._url:
            webbrowser.open(self._url)


class _EntryProxy:
    def __init__(self, var):
        self._var = var
    def text(self):   return self._var.get()
    def setText(self, t): self._var.set(t)


class _ButtonProxy:
    def __init__(self, btn):
        self._btn = btn
        self._cbs = []
        btn.configure(command=self._fire)
    def _fire(self):
        for cb in self._cbs: cb()
    class _Sig:
        def __init__(self, o): self._o = o
        def connect(self, cb): self._o._cbs.append(cb)
    @property
    def clicked(self): return self._Sig(self)


class _NoOp:
    def __getattr__(self, _): return lambda *a, **kw: None


class Ui_Dialog:
    """Tkinter equivalent of about_panel.Ui_Dialog."""

    def setupUi(self, Dialog):
        Dialog.title("About data2bids")
        Dialog.resizable(False, False)

        frame = ttk.Frame(Dialog, padding=12)
        frame.pack(fill='both', expand=True)

        # Icon placeholder (no SVG support)
        self._icon_lbl = ttk.Label(frame, text="data2bids", font=('Arial', 18, 'bold'))
        self._icon_lbl.pack(pady=(0, 6))

        # Version
        ttk.Label(frame, text="Version:", font=('Arial', 10, 'bold')).pack()
        self._version_var = tk.StringVar()
        self._version_entry = ttk.Entry(frame, textvariable=self._version_var,
                                        state='readonly', width=20)
        self._version_entry.pack(pady=2)

        # Links
        ttk.Label(frame, text="Google Drive folder:", font=('Arial', 10)).pack(pady=(6, 0))
        self._drive_link = _LinkWidget(frame)
        self._drive_link.pack()

        ttk.Label(frame, text="Documentation:", font=('Arial', 10)).pack(pady=(6, 0))
        self._doc_link = _LinkWidget(frame)
        self._doc_link.pack()

        # Close button
        self._close_btn = ttk.Button(frame, text="Close")
        self._close_btn.pack(pady=(12, 0))

        # ── Public proxy attributes ──────────────────────────────────
        self.softwareIcon             = _LabelProxy(self._icon_lbl)
        self.versionDateEdit          = _EntryProxy(self._version_var)
        self.googleDriveLink          = self._drive_link
        self.documentationLink        = self._doc_link
        self.closeAboutWindowButton   = _ButtonProxy(self._close_btn)

    def retranslateUi(self, Dialog):
        pass


class AboutDialog:
    """
    Full dialog (replaces aboutDialog in data2bids_main.py).
    """

    def __init__(self, parent=None, app_info=None):
        self._parent   = parent
        self.app_info  = app_info or {}
        self._win      = None
        self._ui       = Ui_Dialog()
        self._build()

    def _build(self):
        self._win = tk.Toplevel(self._parent)
        self._win.withdraw()
        self._win.protocol("WM_DELETE_WINDOW", self.close)
        self._ui.setupUi(self._win)

        # Populate from app_info
        info = self.app_info
        if info:
            date = info.get('date', '')
            if len(date) >= 8:
                formatted = f"{date[:2]}.{date[2:4]}.{date[4:]}"
            else:
                formatted = date
            self._ui.versionDateEdit.setText(formatted)
            self._ui.googleDriveLink.setHtml(
                f'<a href="{info.get("driveFolder","")}">'
                f'<span style=" text-decoration: underline; color:#0000ff;">link to folder</span></a>'
            )
            self._ui.documentationLink.setHtml(
                f'<a href="{info.get("website","")}">'
                f'<span style=" text-decoration: underline; color:#0000ff;">link to website</span></a>'
            )

        # Expose proxies at top level
        self.softwareIcon           = self._ui.softwareIcon
        self.versionDateEdit        = self._ui.versionDateEdit
        self.googleDriveLink        = self._ui.googleDriveLink
        self.documentationLink      = self._ui.documentationLink
        self.closeAboutWindowButton = self._ui.closeAboutWindowButton

    def exec(self):
        self._build()
        self._win.deiconify()
        self._win.grab_set()
        self._win.wait_window()   # returns when _win is destroyed

    def close(self):
        if self._win and self._win.winfo_exists():
            self._win.destroy()
        self._win = None
