import os
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import datetime
import csv

class SessionManagerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Session Shifter & TSV Sync Tool")
        self.root.geometry("1200x700")

        self.tsv_path = None
        self.root_dir = None
        self.tsv_data = []
        self.log_path = None
        self.dry_run = tk.BooleanVar(value=True)
        self.sort_enabled = tk.BooleanVar(value=False)

        self.create_widgets()

    def create_widgets(self):
        # Top buttons frame
        top_frame = tk.Frame(self.root)
        top_frame.pack(fill="x", pady=5)

        tk.Button(top_frame, text="Load Root Folder", command=self.load_root).pack(side="left", padx=5)
        tk.Button(top_frame, text="Load TSV File", command=self.load_tsv).pack(side="left", padx=5)
        tk.Checkbutton(top_frame, text="Dry Run", variable=self.dry_run).pack(side="left", padx=5)
        tk.Checkbutton(top_frame, text="Enable Sorting", variable=self.sort_enabled, command=self.toggle_sort).pack(side="left", padx=5)

        tk.Button(top_frame, text="Check TSV vs Folders", command=self.check_consistency).pack(side="left", padx=5)
        tk.Button(top_frame, text="Apply Changes", command=self.apply_changes).pack(side="right", padx=5)

        # Treeview
        self.tree = ttk.Treeview(self.root, columns=("Folder", "Filename", "Acq Time", "Duration", "EDF Type"), show="headings")
        self.tree.heading("Folder", text="Folder")
        self.tree.heading("Filename", text="Filename")
        self.tree.heading("Acq Time", text="Acq Time")
        self.tree.heading("Duration", text="Duration")
        self.tree.heading("EDF Type", text="EDF Type")

        self.tree.pack(fill="both", expand=True)

        # Auto resize columns
        self.tree.bind("<Configure>", self.resize_columns)

        # Bottom frame for shift controls
        bottom_frame = tk.Frame(self.root)
        bottom_frame.pack(fill="x", pady=5)

        tk.Label(bottom_frame, text="Shift Range:").pack(side="left", padx=5)
        self.range_start = tk.Entry(bottom_frame, width=5)
        self.range_start.pack(side="left")
        self.range_end = tk.Entry(bottom_frame, width=5)
        self.range_end.pack(side="left")

        tk.Label(bottom_frame, text="→ Shift by:").pack(side="left", padx=5)
        self.shift_amount = tk.Entry(bottom_frame, width=5)
        self.shift_amount.pack(side="left")

        tk.Button(bottom_frame, text="Shift", command=self.shift_range).pack(side="left", padx=5)

    def load_root(self):
        path = filedialog.askdirectory(title="Select Root Folder")
        if path:
            self.root_dir = path
            self.log_path = os.path.join(self.root_dir, f"session_shift_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
            self.log(f"Loaded root folder: {path}")

    def load_tsv(self):
        path = filedialog.askopenfilename(filetypes=[("TSV Files", "*.tsv")])
        if path:
            self.tsv_path = path
            self.load_tsv_data()
            self.log(f"Loaded TSV file: {path}")

    def load_tsv_data(self):
        self.tsv_data.clear()
        with open(self.tsv_path, "r", newline="") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                if len(row) >= 4:
                    self.tsv_data.append(row)
        self.populate_tree()

    def populate_tree(self, highlight_missing_extra=False):
        self.tree.delete(*self.tree.get_children())
        for row in self.tsv_data:
            folder = row[0].split("/")[0]
            filename = os.path.basename(row[0])
            self.tree.insert("", "end", values=(folder, filename, row[1], row[2], row[3]))

        if highlight_missing_extra:
            # Highlight missing and extra sessions
            existing_folders = {row[0].split("/")[0] for row in self.tsv_data}
            found_folders = self.find_session_folders()
            missing = existing_folders - found_folders
            extra = found_folders - existing_folders

            for folder in missing:
                self.tree.insert("", "end", values=(folder, "", "N/A", "N/A", "N/A"), tags=("missing",))
            for folder in extra:
                self.tree.insert("", "end", values=(folder, "", "N/A", "N/A", "N/A"), tags=("extra",))

            self.tree.tag_configure("missing", background="red", foreground="white")
            self.tree.tag_configure("extra", background="orange", foreground="black")

    def find_session_folders(self):
        folders = set()
        if not self.root_dir:
            return folders
        for root, dirs, files in os.walk(self.root_dir):
            for d in dirs:
                if d.startswith("ses-"):
                    folders.add(d)
        return folders

    def check_consistency(self):
        if not self.tsv_path or not self.root_dir:
            messagebox.showerror("Error", "Load both root folder and TSV first")
            return
        self.populate_tree(highlight_missing_extra=True)
        self.log("Checked TSV vs folder structure.")

    def toggle_sort(self):
        if self.sort_enabled.get():
            for col in self.tree["columns"]:
                self.tree.heading(col, command=lambda _col=col: self.sort_column(_col, False))
        else:
            for col in self.tree["columns"]:
                self.tree.heading(col, command="")

    def sort_column(self, col, reverse):
        data = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        data.sort(reverse=reverse)
        for index, (_, k) in enumerate(data):
            self.tree.move(k, "", index)
        self.tree.heading(col, command=lambda: self.sort_column(col, not reverse))

    def shift_range(self):
        try:
            start = int(self.range_start.get())
            end = int(self.range_end.get())
            shift = int(self.shift_amount.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid range or shift amount")
            return

        self.log(f"Shifting sessions {start} to {end} by {shift}")

        for row in self.tsv_data:
            folder = row[0].split("/")[0]
            try:
                num = int(folder.split("-")[1])
            except ValueError:
                continue
            if start <= num <= end:
                new_num = num + shift
                new_folder = f"ses-{new_num:03d}"
                row[0] = row[0].replace(folder, new_folder)

        self.populate_tree()

    def apply_changes(self):
        if self.dry_run.get():
            self.log("Dry run: No changes applied.")
            return
        if not self.tsv_path:
            return
        backup_path = self.tsv_path + ".bak"
        shutil.copy2(self.tsv_path, backup_path)
        self.log(f"Backup created: {backup_path}")

        with open(self.tsv_path, "w", newline="") as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            for row in self.tsv_data:
                writer.writerow(row)

        self.log("TSV updated.")

    def resize_columns(self, event):
        tree_width = event.width
        col_count = len(self.tree["columns"])
        col_width = max(100, int(tree_width / col_count) - 1)
        for col in self.tree["columns"]:
            self.tree.column(col, width=col_width)

    def log(self, message):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {message}\n"
        print(line.strip())
        if self.log_path:
            with open(self.log_path, "a") as logf:
                logf.write(line)

if __name__ == "__main__":
    root = tk.Tk()
    app = SessionManagerGUI(root)
    root.mainloop()
