# -*- coding: utf-8 -*-
"""
gui_layout.py
Tkinter replacement for the Qt-Designer-generated gui_layout.Ui_MainWindow.

Key design notes
----------------
* QTreeWidget with embedded combobox widgets (setItemWidget / itemWidget) is
  replaced by a TkTreeWidget wrapper. Combobox values are stored per-cell in
  a dict; clicking a cell column that has a combo pops up a small overlay
  Combobox for editing.
* All public attribute names (treeViewLoad, convertButton, etc.) are preserved
  so that data2bids_main.py requires minimal changes.
"""

import tkinter as tk
from tkinter import ttk


# ══════════════════════════════════════════════════════════════════════════════
# Lightweight proxy classes that mimic Qt widget APIs
# ══════════════════════════════════════════════════════════════════════════════

class _ClickSignal:
    """Mimics QPushButton.clicked / QPushButton.pressed."""
    def __init__(self): self._cbs = []
    def connect(self, cb):
        if cb not in self._cbs: self._cbs.append(cb)
    def fire(self):
        for cb in self._cbs: cb()


class _ButtonProxy:
    """Wraps a ttk.Button and exposes .clicked, .setEnabled(), .setStyleSheet()."""

    _COLOR_MAP = {
        'rgb(255,0,0)':       '#ff0000',
        'rgb(173, 127, 168)': '#ad7fa8',
        'rgb(0, 85, 255)':    '#0055ff',
        'rgb(79, 232, 109)':  '#4fe86d',
        'rgb(160, 160, 160)': '#a0a0a0',
    }

    def __init__(self, btn):
        self._btn  = btn
        self.clicked  = _ClickSignal()
        self.pressed  = _ClickSignal()
        btn.configure(command=self._on_click)

    def _on_click(self):
        self.clicked.fire()
        self.pressed.fire()

    def setEnabled(self, v):
        self._btn.configure(state='normal' if v else 'disabled')

    def isEnabled(self):
        return self._btn.cget('state') == 'normal'

    def setStyleSheet(self, css):
        bg = None
        for k, v in self._COLOR_MAP.items():
            if k in css:
                bg = v
                break
        if bg:
            try: self._btn.configure(style='')
            except: pass
            try: self._btn.configure(bg=bg)
            except: pass

    def setText(self, t):
        self._btn.configure(text=t)


class _CheckProxy:
    """Wraps a ttk.Checkbutton + tk.BooleanVar."""
    def __init__(self, var, widget):
        self._var = var
        self._wgt = widget
        self._changed_cbs = []
        self._var.trace_add('write', self._on_change)

    def _on_change(self, *_):
        for cb in self._changed_cbs: cb()

    def isChecked(self):      return bool(self._var.get())
    def setChecked(self, v):  self._var.set(bool(v))

    class _Sig:
        def __init__(self, lst): self._lst = lst
        def connect(self, cb):   self._lst.append(cb)

    @property
    def stateChanged(self): return self._Sig(self._changed_cbs)


class _TextProxy:
    """Wraps a tk.Text widget; mimics QPlainTextEdit."""
    def __init__(self, widget):
        self._w = widget

    def appendPlainText(self, t):
        self._w.configure(state='normal')
        self._w.insert('end', t + '\n')
        self._w.see('end')
        self._w.configure(state='normal')

    def insertPlainText(self, t):
        self._w.configure(state='normal')
        self._w.insert('end', t)
        self._w.see('end')

    def moveCursor(self, _cursor):
        self._w.see('end')

    def clear(self):
        self._w.configure(state='normal')
        self._w.delete('1.0', 'end')

    def setReadOnly(self, v): pass  # Text is writable by default in this proxy


class _StatusBar:
    """Wraps a ttk.Label at the bottom of the window; mimics QStatusBar."""
    def __init__(self, widget):
        self._lbl = widget

    def showMessage(self, msg, _timeout=0):
        self._lbl.configure(text=msg)


class _LabelProxy:
    """Wraps ttk.Label; mimics QLabel with .setVisible()."""
    def __init__(self, lbl, pack_kwargs=None):
        self._lbl  = lbl
        self._pkw  = pack_kwargs or {}
        self._vis  = True

    def setVisible(self, v):
        if v and not self._vis:
            self._lbl.pack(**self._pkw) if self._pkw else self._lbl.grid()
            self._vis = True
        elif not v and self._vis:
            self._lbl.pack_forget()
            self._vis = False

    def setText(self, t):
        self._lbl.configure(text=t)


# ══════════════════════════════════════════════════════════════════════════════
# CellComboProxy  –  replaces a QComboBox embedded inside a tree row
# ══════════════════════════════════════════════════════════════════════════════

class CellComboProxy:
    """
    Stores the (items, current_value) for one combobox-cell in the tree.
    The TkTreeWidget displays the current value as text and creates an
    overlay Combobox for editing on click.
    """
    def __init__(self, tree_ref, iid, col_tag, items, current):
        self._tree    = tree_ref   # TkTreeWidget instance
        self._iid     = iid
        self._col_tag = col_tag
        self.items    = list(items)
        self._current = current

    def currentText(self):
        return self._current

    def setCurrentText(self, t):
        self._current = t
        # Refresh display in the treeview cell
        try:
            self._tree._tree.set(self._iid, self._col_tag, f'[{t}]')
        except Exception:
            pass

    def addItems(self, items):
        self.items = list(items)


# ══════════════════════════════════════════════════════════════════════════════
# TreeWidgetItem  –  proxy for a single row/item in the tree
# ══════════════════════════════════════════════════════════════════════════════

# Qt flag constants (values don't matter, just used for comparison)
_Qt_Checked            = 2
_Qt_Unchecked          = 0
_Qt_ItemIsSelectable   = 1
_Qt_ItemIsUserCheckable = 4


class TreeWidgetItem:
    """
    Proxy for one row in a TkTreeWidget.  Mimics QTreeWidgetItem.
    """

    def __init__(self, tree_ref, iid, parent_iid=''):
        self._tree       = tree_ref   # TkTreeWidget instance
        self.iid         = iid
        self._parent_iid = parent_iid
        self._flags      = 0
        self._check_states = {}       # col → True/False

    # ── text ────────────────────────────────────────────────────────
    def setText(self, col, text):
        col_tag = self._tree._col_tag(col)
        self._tree._tree.set(self.iid, col_tag, str(text))

    def text(self, col):
        col_tag = self._tree._col_tag(col)
        try:
            return self._tree._tree.set(self.iid, col_tag)
        except Exception:
            return ''

    def setTextAlignment(self, col, alignment):
        pass  # ttk.Treeview doesn't support per-cell alignment

    # ── flags ───────────────────────────────────────────────────────
    def flags(self):
        return self._flags

    def setFlags(self, f):
        self._flags = f

    # ── check state ─────────────────────────────────────────────────
    def setCheckState(self, col, state):
        checked = (state == _Qt_Checked)
        self._check_states[col] = checked
        mark = '☑' if checked else '☐'
        col_tag = self._tree._col_tag(col)
        current = self._tree._tree.set(self.iid, col_tag)
        # Prepend checkbox symbol to column 0 text
        if col == 0:
            base = current.lstrip('☑☐ ')
            self._tree._tree.set(self.iid, col_tag, f'{mark} {base}')

    def checkState(self, col):
        return _Qt_Checked if self._check_states.get(col, False) else _Qt_Unchecked

    # ── children ────────────────────────────────────────────────────
    def childCount(self):
        return len(self._tree._tree.get_children(self.iid))

    def child(self, i):
        children = self._tree._tree.get_children(self.iid)
        if i < len(children):
            return self._tree._item_map.get(children[i])
        return None


# ══════════════════════════════════════════════════════════════════════════════
# TkTreeWidget  –  wraps ttk.Treeview with a Qt-compatible API
# ══════════════════════════════════════════════════════════════════════════════

class _HeaderProxy:
    """Mimics QHeaderView."""
    def __init__(self, tree_widget):
        self._tw = tree_widget

    def setDefaultAlignment(self, _): pass
    def setStretchLastSection(self, _): pass
    def setFont(self, _): pass

    def count(self):
        return len(self._tw._columns)

    def setSectionResizeMode(self, col, mode): pass  # handled by auto-width

    def sectionSize(self, col):
        col_tag = self._tw._col_tag(col)
        try:
            return self._tw._tree.column(col_tag, 'width')
        except Exception:
            return 100

    def resizeSection(self, col, width):
        col_tag = self._tw._col_tag(col)
        try:
            self._tw._tree.column(col_tag, width=max(width, 40))
        except Exception:
            pass

    def setVisible(self, v): pass


class _DoubleClickSignal:
    """Mimics tree itemDoubleClicked signal."""
    def __init__(self): self._cbs = []
    def connect(self, cb):
        if cb not in self._cbs: self._cbs.append(cb)
    def fire(self, item, col):
        for cb in self._cbs: cb(item, col)


class TkTreeWidget:
    """
    Wraps ttk.Treeview and provides a QTreeWidget-compatible API.

    Combobox columns
    ----------------
    Columns whose index appears in _combo_cols receive special treatment:
    - Their cell value is displayed as [value].
    - A single click on that cell pops up an overlay ttk.Combobox for editing.
    """

    def __init__(self, parent, combo_cols=None):
        self._parent     = parent
        self._combo_cols = set(combo_cols or [])
        self._columns    = []          # list of column IDs (col0, col1, …)
        self._col_names  = []          # human-readable header names
        self._item_map   = {}          # iid → TreeWidgetItem
        self._cell_combos = {}         # (iid, col) → CellComboProxy
        self._overlay    = None        # active overlay Combobox

        # outer frame (holds tree + scrollbars)
        self._frame = ttk.Frame(parent)
        self._tree  = None             # created in _init_tree()

        self.itemDoubleClicked = _DoubleClickSignal()
        self.header_proxy      = _HeaderProxy(self)

    # ── geometry ──────────────────────────────────────────────────────
    def pack(self, **kw):   self._frame.pack(**kw)
    def grid(self, **kw):   self._frame.grid(**kw)

    # ── column helpers ────────────────────────────────────────────────
    def _col_tag(self, col):
        """Return the column identifier string for index col."""
        return f'col{col}'

    def _col_index(self, col_tag):
        try:
            return int(col_tag.replace('col', ''))
        except Exception:
            return -1

    # ── header / columns ─────────────────────────────────────────────
    def setHeaderItem(self, item_or_texts):
        """
        Mimics QTreeWidget.setHeaderItem(QTreeWidgetItem([col0, col1, …])).
        item_or_texts may be a TreeWidgetItem or a plain list of strings.
        """
        if isinstance(item_or_texts, TreeWidgetItem):
            texts = [item_or_texts.text(i)
                     for i in range(self._col_count_from_item(item_or_texts))]
        else:
            texts = list(item_or_texts)

        self._col_names = texts
        self._columns   = [f'col{i}' for i in range(len(texts))]
        self._init_tree()

    def _col_count_from_item(self, item):
        # TreeWidgetItem stores text by column in the tree; count them
        n = 0
        while True:
            tag = f'col{n}'
            try:
                _ = self._tree.set(item.iid, tag)
                n += 1
            except Exception:
                break
        return max(n, len(self._col_names))

    def _init_tree(self):
        """(Re-)create the underlying ttk.Treeview with current columns."""
        if self._tree is not None:
            self._tree.destroy()
            for w in self._frame.winfo_children():
                w.destroy()

        cols = self._columns
        self._tree = ttk.Treeview(self._frame, columns=cols,
                                  show='tree headings', selectmode='none')

        # Column 0 ("tree" column) is the expand-arrow column;
        # hide its heading and map our col0 to the #0 column.
        self._tree.heading('#0', text=self._col_names[0] if self._col_names else '')
        self._tree.column('#0', width=220, stretch=False)

        for i, (col, name) in enumerate(zip(cols, self._col_names)):
            if i == 0:
                continue  # col0 handled as #0 above
            self._tree.heading(col, text=name, anchor='center')
            w = 80 if len(name) < 10 else max(len(name) * 8, 80)
            self._tree.column(col, width=w, minwidth=40, stretch=(i == 0),
                               anchor='center')

        # Scrollbars
        vsb = ttk.Scrollbar(self._frame, orient='vertical',
                            command=self._tree.yview)
        hsb = ttk.Scrollbar(self._frame, orient='horizontal',
                            command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        self._frame.rowconfigure(0, weight=1)
        self._frame.columnconfigure(0, weight=1)

        # Bind events
        self._tree.bind('<Double-Button-1>', self._on_double_click)
        self._tree.bind('<Button-1>',        self._on_single_click)
        self._tree.bind('<FocusOut>',        lambda e: self._dismiss_overlay())

    # ── item creation ─────────────────────────────────────────────────
    def _insert_item(self, parent_iid, texts_dict=None):
        """Insert a row and return a TreeWidgetItem proxy."""
        iid = self._tree.insert(parent_iid, 'end')
        item = TreeWidgetItem(self, iid, parent_iid)
        self._item_map[iid] = item
        return item

    # ── Qt-like item factory ──────────────────────────────────────────
    def new_item(self, parent=None):
        """
        Creates a child item.  parent may be a TreeWidgetItem (child) or
        None (top-level, same as invisibleRootItem()).
        Mimics: item = QtWidgets.QTreeWidgetItem(parent_item_or_tree)
        """
        parent_iid = parent.iid if isinstance(parent, TreeWidgetItem) else ''
        return self._insert_item(parent_iid)

    # ── setItemWidget / itemWidget ────────────────────────────────────
    def setItemWidget(self, item, col, proxy):
        """
        Stores a CellComboProxy for (item, col).
        Displays the current value as [value] in the cell.
        """
        self._cell_combos[(item.iid, col)] = proxy
        col_tag = self._col_tag(col)
        try:
            self._tree.set(item.iid, col_tag, f'[{proxy.currentText()}]')
        except Exception:
            pass

    def itemWidget(self, item, col):
        """Returns the stored CellComboProxy, or None."""
        return self._cell_combos.get((item.iid, col))

    # ── clear / root ──────────────────────────────────────────────────
    def clear(self):
        if self._tree:
            self._tree.delete(*self._tree.get_children())
        self._item_map.clear()
        self._cell_combos.clear()

    def invisibleRootItem(self):
        """Returns a proxy representing the invisible root."""
        root = TreeWidgetItem(self, '', '')
        root._is_root = True
        return root

    # ── Proxy for invisibleRootItem.child() ───────────────────────────
    def _root_child_count(self):
        return len(self._tree.get_children(''))

    def _root_child(self, i):
        children = self._tree.get_children('')
        if i < len(children):
            return self._item_map.get(children[i])
        return None

    # ── header ────────────────────────────────────────────────────────
    def header(self):
        return self.header_proxy

    # ── misc Qt stubs ─────────────────────────────────────────────────
    def setEditTriggers(self, _): pass
    def setFont(self, _):         pass
    def setAlternatingRowColors(self, _): pass
    def setSelectionMode(self, _): pass

    def editItem(self, item, col):
        """Show an overlay entry/combobox for editing (called on double-click)."""
        self._show_overlay(item, col)

    # ── click handlers ────────────────────────────────────────────────
    def _identify_col(self, event):
        """Return (TreeWidgetItem, col_index) for the click, or (None, -1)."""
        iid    = self._tree.identify_row(event.y)
        region = self._tree.identify_region(event.x, event.y)
        col_id = self._tree.identify_column(event.x)  # '#0', '#1', '#2', …
        if not iid or region not in ('tree', 'cell'):
            return None, -1
        item = self._item_map.get(iid)
        if item is None:
            return None, -1
        # '#0' → col 0,  '#1' → col 1,  etc.
        try:
            col_idx = int(col_id.replace('#', '')) - 1
            if col_idx < 0:
                col_idx = 0  # tree column = col 0
        except Exception:
            col_idx = 0
        return item, col_idx

    def _on_single_click(self, event):
        self._dismiss_overlay()
        item, col = self._identify_col(event)
        if item is None:
            return
        if col in self._combo_cols and (item.iid, col) in self._cell_combos:
            self._show_overlay(item, col)

    def _on_double_click(self, event):
        self._dismiss_overlay()
        item, col = self._identify_col(event)
        if item is None:
            return
        self.itemDoubleClicked.fire(item, col)

    # ── overlay combobox ──────────────────────────────────────────────
    def _show_overlay(self, item, col):
        """Display a ttk.Combobox over the clicked cell for value selection."""
        proxy = self._cell_combos.get((item.iid, col))
        if proxy is None:
            return

        self._dismiss_overlay()

        col_tag = self._col_tag(col)
        try:
            bbox = self._tree.bbox(item.iid, col_tag)
        except Exception:
            return
        if not bbox:
            return

        x, y, w, h = bbox
        var = tk.StringVar(value=proxy.currentText())

        cb = ttk.Combobox(self._tree, textvariable=var,
                          values=proxy.items, state='readonly', width=max(w // 8, 8))
        cb.place(x=x, y=y, width=w, height=h)
        cb.focus_set()
        cb.event_generate('<Button-1>')  # open dropdown

        def _commit(*_):
            proxy.setCurrentText(var.get())
            self._dismiss_overlay()

        cb.bind('<<ComboboxSelected>>', _commit)
        cb.bind('<FocusOut>',           lambda e: self._dismiss_overlay())
        cb.bind('<Escape>',             lambda e: self._dismiss_overlay())
        self._overlay = cb

    def _dismiss_overlay(self):
        if self._overlay is not None:
            try:
                self._overlay.destroy()
            except Exception:
                pass
            self._overlay = None


# ══════════════════════════════════════════════════════════════════════════════
# Invisible-root proxy that connects to TkTreeWidget
# ══════════════════════════════════════════════════════════════════════════════

class _RootProxy:
    """Proxy returned by TkTreeWidget.invisibleRootItem()."""
    def __init__(self, tw): self._tw = tw
    def childCount(self):   return self._tw._root_child_count()
    def child(self, i):     return self._tw._root_child(i)


# ══════════════════════════════════════════════════════════════════════════════
# Ui_MainWindow  –  builds the full main window layout
# ══════════════════════════════════════════════════════════════════════════════

class Ui_MainWindow:
    """
    Builds all tkinter widgets onto the window object passed to setupUi().
    Every attribute name matches the original Qt version so that
    data2bids_main.py needs minimal changes.
    """

    def setupUi(self, win):
        """
        win  –  the MainWindow instance (has self.root = tk.Tk()).
        All widgets are attached as attributes of win.
        """
        root = win.root
        root.title("data2bids")
        root.minsize(1200, 700)

        # ── Menu bar ─────────────────────────────────────────────────
        menubar = tk.Menu(root)
        root.configure(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)

        # theme submenu
        theme_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Theme", menu=theme_menu)

        # We expose "action" objects with a .triggered signal
        class _Action:
            def __init__(self): self.triggered = _ClickSignal()
            def setEnabled(self, v): pass

        win.actionLoad_data     = _Action()
        win.actionSettings      = _Action()
        win.actionAbout         = _Action()
        win.actionDarkMode      = _Action()
        win.actionLightMode     = _Action()
        win.actionQuit          = _Action()
        win.actionOverwrite_Type = _Action()

        file_menu.add_command(label="Load data",
                              command=win.actionLoad_data.triggered.fire)
        file_menu.add_command(label="Settings",
                              command=win.actionSettings.triggered.fire)
        file_menu.add_separator()
        file_menu.add_command(label="Quit",
                              command=win.actionQuit.triggered.fire)

        theme_menu.add_command(label="Dark mode",
                               command=win.actionDarkMode.triggered.fire)
        theme_menu.add_command(label="Light mode",
                               command=win.actionLightMode.triggered.fire)
        theme_menu.add_command(label="Overwrite EDF type",
                               command=win.actionOverwrite_Type.triggered.fire)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About",
                              command=win.actionAbout.triggered.fire)

        # ── Main PanedWindow (vertical splitter) ──────────────────────
        main_pane = ttk.PanedWindow(root, orient='vertical')
        main_pane.pack(fill='both', expand=True, padx=4, pady=4)

        # ── Upper half: Load tree ─────────────────────────────────────
        upper_frame = ttk.Frame(main_pane)
        main_pane.add(upper_frame, weight=1)

        btn_frame_top = ttk.Frame(upper_frame, width=180)
        btn_frame_top.pack(side='left', fill='y', padx=4, pady=4)
        btn_frame_top.pack_propagate(False)

        load_btn = ttk.Button(btn_frame_top, text="Load Input Dir")
        load_btn.pack(pady=4, fill='x')
        win.loadDirButton = _ButtonProxy(load_btn)

        # Load tree  (columns 0-12)
        combo_cols_load = {7, 8, 9, 12}   # type, task, retpro, labels
        load_tree = TkTreeWidget(upper_frame, combo_cols=combo_cols_load)
        load_tree.pack(side='left', fill='both', expand=True)
        win.treeViewLoad = load_tree

        # ── Middle half: Output tree ──────────────────────────────────
        mid_frame = ttk.Frame(main_pane)
        main_pane.add(mid_frame, weight=1)

        btn_frame_mid = ttk.Frame(mid_frame, width=180)
        btn_frame_mid.pack(side='left', fill='y', padx=4, pady=4)
        btn_frame_mid.pack_propagate(False)

        out_btn = ttk.Button(btn_frame_mid, text="Load Output Dir")
        out_btn.pack(pady=4, fill='x')
        win.outDirButton = _ButtonProxy(out_btn)

        stext_lbl = ttk.Label(btn_frame_mid, text="★ New sessions detected",
                              foreground='green', wraplength=160)
        stext_lbl.pack(pady=4)
        win.sText = _LabelProxy(stext_lbl)

        combo_cols_out = {6, 7, 8}   # type, task, retpro
        out_tree = TkTreeWidget(mid_frame, combo_cols=combo_cols_out)
        out_tree.pack(side='left', fill='both', expand=True)
        win.treeViewOutput = out_tree

        # ── Lower section: log + buttons + checkboxes ─────────────────
        lower_frame = ttk.Frame(main_pane)
        main_pane.add(lower_frame, weight=0)
        lower_frame.configure(height=200)

        # Conversion log
        log_frame = ttk.Frame(lower_frame)
        log_frame.pack(side='left', fill='both', expand=True, padx=4, pady=4)

        log_txt = tk.Text(log_frame, height=8, state='normal',
                          wrap='word', font=('Courier', 9))
        log_vsb = ttk.Scrollbar(log_frame, orient='vertical',
                                command=log_txt.yview)
        log_txt.configure(yscrollcommand=log_vsb.set)
        log_txt.pack(side='left', fill='both', expand=True)
        log_vsb.pack(side='right', fill='y')
        win.conversionStatus = _TextProxy(log_txt)

        # Right side: action buttons + checkboxes
        right_panel = ttk.Frame(lower_frame)
        right_panel.pack(side='right', fill='y', padx=6, pady=4)

        def _mk_btn(text, bg=None):
            btn = ttk.Button(right_panel, text=text)
            btn.pack(fill='x', pady=2)
            return _ButtonProxy(btn)

        win.convertButton = _mk_btn("Convert")
        win.imagingButton = _mk_btn("Process Imaging")
        win.spredButton   = _mk_btn("Convert to SPReD")
        win.pauseButton   = _mk_btn("Pause")
        win.cancelButton  = _mk_btn("Cancel")

        # Checkboxes
        chk_frame = ttk.LabelFrame(right_panel, text="Options", padding=4)
        chk_frame.pack(fill='x', pady=4)

        def _mk_chk(parent, text):
            var = tk.BooleanVar(value=False)
            chk = ttk.Checkbutton(parent, text=text, variable=var)
            chk.pack(anchor='w')
            return _CheckProxy(var, chk)

        win.deidentifyInputDir = _mk_chk(chk_frame, "De-identify source")
        win.offsetDate         = _mk_chk(chk_frame, "Offset dates")
        win.gzipEDF            = _mk_chk(chk_frame, "Gzip EDF")
        win.dryRun             = _mk_chk(chk_frame, "Dry run")

        # ── Status bar ────────────────────────────────────────────────
        status_lbl = ttk.Label(root, text="Ready", relief='sunken', anchor='w')
        status_lbl.pack(side='bottom', fill='x')
        win.statusbar = _StatusBar(status_lbl)

        # ── Wire Quit action ─────────────────────────────────────────
        win.actionQuit.triggered.connect(root.destroy)

        # ── Patch invisibleRootItem to use _RootProxy ─────────────────
        def _patched_invisible_root_load():
            return _RootProxy(win.treeViewLoad)
        def _patched_invisible_root_out():
            return _RootProxy(win.treeViewOutput)
        win.treeViewLoad.invisibleRootItem  = _patched_invisible_root_load
        win.treeViewOutput.invisibleRootItem = _patched_invisible_root_out
