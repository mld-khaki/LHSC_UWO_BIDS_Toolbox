import os
import shutil
import csv
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
from tkinter import simpledialog



LOG_FILE = None
DELETE_REASONS = ["clip", "empty", "converted", "unparsable", "others"]


# ============================================================
# Utility functions
# ============================================================


def folder_stats(folder_path):
    total_size = 0
    file_count = 0
    mtimes = []
    extensions = set()

    for root, _, files in os.walk(folder_path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            total_size += st.st_size
            file_count += 1
            mtimes.append(st.st_mtime)
            ext = os.path.splitext(f)[1].lower()
            if ext:
                extensions.add(ext)

    if mtimes:
        date_min = datetime.fromtimestamp(min(mtimes)).isoformat(timespec="seconds")
        date_max = datetime.fromtimestamp(max(mtimes)).isoformat(timespec="seconds")
    else:
        date_min = ""
        date_max = ""

    return {
        "size_bytes": total_size,
        "file_count": file_count,
        "date_min": date_min,
        "date_max": date_max,
        "extensions": ";".join(sorted(extensions))
    }


def ensure_log_header():
    if LOG_FILE is None:
        raise RuntimeError("LOG_FILE is not set")

    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp",
                "delete_reason",
                "folder_name",
                "folder_path",
                "size_bytes",
                "file_count",
                "date_min",
                "date_max",
                "extensions"
            ])




def log_deletion(reason, folder_path, stats):
    if LOG_FILE is None:
        raise RuntimeError("LOG_FILE is not set")

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().isoformat(timespec="seconds"),
            reason,
            os.path.basename(folder_path),
            folder_path,
            stats["size_bytes"],
            stats["file_count"],
            stats["date_min"],
            stats["date_max"],
            stats["extensions"]
        ])

# ============================================================
# GUI
# ============================================================

class FolderCleanerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Folder Cleaner with Deletion Log")
        self.geometry("1100x650")

        self.root_dir = None
        self.selected_folder = None

        self._build_gui()

    def select_log_file(self):
        global LOG_FILE

        path = filedialog.askopenfilename(
            parent=self,
            title="Select deletion log file (or cancel to create new)",
            filetypes=[("CSV files", "*.csv")]
        )

        if not path:
            path = filedialog.asksaveasfilename(
                parent=self,
                title="Create new deletion log file",
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv")]
            )
            if not path:
                return

        LOG_FILE = path
        ensure_log_header()

        messagebox.showinfo(
            "Log file set",
            f"Deletion log:\n{LOG_FILE}"
        )


    # --------------------------------------------------------
    def add_log_button(self, parent_frame):
        ttk.Button(
            parent_frame,
            text="Select Log File",
            command=self.select_log_file
        ).pack(side="left", padx=5)

    # =========================================================
    # Tree refresh with state preservation
    # =========================================================

    def refresh_tree(self):
        if not self.root_dir:
            return

        expanded_paths = set()
        for node in self.tree.get_children():
            self._collect_expanded(node, expanded_paths)

        selected_path = self.selected_folder

        self.tree.delete(*self.tree.get_children())
        self.insert_tree_node("", self.root_dir)

        for node in self.tree.get_children():
            self._restore_expanded(node, expanded_paths)

        if selected_path:
            self._restore_selection(selected_path)


    def _tree_node_path(self, node):
        parts = []
        while node:
            parts.append(self.tree.item(node, "text"))
            node = self.tree.parent(node)
        parts.reverse()
        return os.path.join(self.root_dir, *parts[1:])


    def _collect_expanded(self, node, expanded_paths):
        if self.tree.item(node, "open"):
            expanded_paths.add(self._tree_node_path(node))
        for child in self.tree.get_children(node):
            self._collect_expanded(child, expanded_paths)


    def _restore_expanded(self, node, expanded_paths):
        path = self._tree_node_path(node)
        if path in expanded_paths:
            self.tree.item(node, open=True)
        for child in self.tree.get_children(node):
            self._restore_expanded(child, expanded_paths)


    def _restore_selection(self, target_path):
        for node in self.tree.get_children():
            if self._find_and_select(node, target_path):
                return


    def _find_and_select(self, node, target_path):
        path = self._tree_node_path(node)
        if path == target_path:
            self.tree.selection_set(node)
            self.tree.see(node)
            self.populate_file_list(target_path)
            self.selected_folder = target_path
            return True

        for child in self.tree.get_children(node):
            if self._find_and_select(child, target_path):
                return True
        return False

    def _build_gui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=5, pady=5)

        ttk.Button(top, text="Select Root Folder", command=self.select_root).pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh_tree).pack(side="left", padx=5)
        ttk.Button(top, text="Select Log File", command=self.select_log_file).pack(side="left", padx=5)

        ttk.Label(top, text="Delete reason:").pack(side="left", padx=(20, 5))

        self.reason_var = tk.StringVar(value=DELETE_REASONS[0])
        ttk.Combobox(
            top,
            textvariable=self.reason_var,
            values=DELETE_REASONS,
            state="readonly",
            width=15
        ).pack(side="left")

        ttk.Button(
            top,
            text="DELETE SELECTED FOLDER",
            command=self.delete_selected
        ).pack(side="right", padx=5)

        main = ttk.PanedWindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=5, pady=5)

        # Folder tree
        left = ttk.Frame(main)
        self.tree = ttk.Treeview(left)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")

        main.add(left, weight=1)

        # File list (FIXED: includes filename)
        right = ttk.Frame(main)
        self.file_list = ttk.Treeview(
            right,
            columns=("name", "size", "mtime"),
            show="headings"
        )
        self.file_list.heading("name", text="File")
        self.file_list.heading("size", text="Size (KB)")
        self.file_list.heading("mtime", text="Modified")

        self.file_list.column("name", width=350, anchor="w")
        self.file_list.column("size", width=100, anchor="e")
        self.file_list.column("mtime", width=160, anchor="center")

        self.file_list.pack(fill="both", expand=True)

        main.add(right, weight=2)

    # --------------------------------------------------------
    def select_root(self):
        path = filedialog.askdirectory(title="Select root folder")
        if not path:
            return

        self.root_dir = path
        self.tree.delete(*self.tree.get_children())
        self.insert_tree_node("", path)

    # --------------------------------------------------------
    def insert_tree_node(self, parent, path):
        node = self.tree.insert(parent, "end", text=os.path.basename(path), values=(path,))
        try:
            for name in sorted(os.listdir(path)):
                full = os.path.join(path, name)
                if os.path.isdir(full):
                    self.insert_tree_node(node, full)
        except PermissionError:
            pass

    # --------------------------------------------------------
    def on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return

        node = sel[0]
        path = self._node_path(node)
        self.selected_folder = path
        self.populate_file_list(path)

    # --------------------------------------------------------
    def _node_path(self, node):
        parts = []
        while node:
            parts.append(self.tree.item(node, "text"))
            node = self.tree.parent(node)
        parts.reverse()
        return os.path.join(self.root_dir, *parts[1:])

    # --------------------------------------------------------
    def populate_file_list(self, folder):
        self.file_list.delete(*self.file_list.get_children())
        try:
            for f in sorted(os.listdir(folder)):
                fp = os.path.join(folder, f)
                if os.path.isfile(fp):
                    st = os.stat(fp)
                    self.file_list.insert(
                        "",
                        "end",
                        values=(
                            f,
                            f"{st.st_size / 1024:.1f}",
                            datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                        )
                    )
        except PermissionError:
            pass


    # --------------------------------------------------------
    def delete_selected(self):
        global LOG_FILE

        if LOG_FILE is None:
            messagebox.showerror(
                "No log file",
                "Please select a log file before deleting."
            )
            return

        if not self.selected_folder:
            messagebox.showwarning("No selection", "No folder selected.")
            return

        reason = self.reason_var.get()
        if not reason:
            messagebox.showwarning("Reason missing", "Select a delete reason.")
            return

        # --- ask for description if reason == others ---
        if reason == "others":
            desc = simpledialog.askstring(
                "Delete reason",
                "Please describe the delete reason:"
            )
            if not desc:
                messagebox.showwarning(
                    "Description required",
                    "Deletion cancelled: description is required for 'others'."
                )
                return
            reason = f"others: {desc.strip()}"

        stats = folder_stats(self.selected_folder)

        size_gb = stats["size_bytes"] / (1024 ** 3)

        confirm = messagebox.askyesno(
            "Confirm deletion",
            (
                f"DELETE THIS FOLDER?\n\n"
                f"Path:\n{self.selected_folder}\n\n"
                f"Total size: {size_gb:.2f} GB\n"
                f"Files: {stats['file_count']}\n\n"
                f"This cannot be undone."
            )
        )

        if not confirm:
            return

        try:
            shutil.rmtree(self.selected_folder)
        except Exception as e:
            messagebox.showerror("Delete failed", str(e))
            return

        log_deletion(reason, self.selected_folder, stats)

        messagebox.showinfo(
            "Deleted",
            f"Folder deleted and logged.\n\nSize freed: {size_gb:.2f} GB"
        )

        self.refresh_tree()




# ============================================================
# Run
# ============================================================

if __name__ == "__main__":
    app = FolderCleanerGUI()
    app.mainloop()
