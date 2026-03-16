import os
import shutil
import zipfile
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime

EDF_EXT = {".edf_pass", ".edf_fail"}
ARCHIVE_EXT = {".zip", ".gz", ".rar", ".7z"}
LOG_EXT = {".log", ".txt"}


def find_files(root):
    files = []
    for path, dirs, filenames in os.walk(root):
        for f in filenames:
            full = os.path.join(path, f)
            files.append(full)
    return files


def make_zip_name(base_name, use_timestamp):
    if use_timestamp:
        stamp = datetime.now().strftime("%Y_%m_%d__%H_%M_%S")
        return f"{base_name}_{stamp}.zip"
    return f"{base_name}.zip"


def zip_and_move(files, zip_path):
    if not files:
        return

    with zipfile.ZipFile(zip_path, "a", compression=zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, os.path.basename(f))
            os.remove(f)


def move_archives(files, dest):
    if not files:
        return

    if not os.path.exists(dest):
        os.makedirs(dest)

    for f in files:
        name = os.path.basename(f)
        target = os.path.join(dest, name)

        if os.path.exists(target):
            base, ext = os.path.splitext(name)
            counter = 1
            while True:
                candidate = os.path.join(dest, f"{base}_{counter}{ext}")
                if not os.path.exists(candidate):
                    target = candidate
                    break
                counter += 1

        shutil.move(f, target)


def run_process(src, dst, use_timestamp):
    if not os.path.exists(src):
        messagebox.showerror("Error", "Source folder does not exist.")
        return

    if not os.path.exists(dst):
        os.makedirs(dst)

    all_files = find_files(src)

    edf_files = []
    archive_files = []
    log_files = []
    unknown = []

    for f in all_files:
        ext = os.path.splitext(f)[1].lower()

        if ext in EDF_EXT:
            edf_files.append(f)
        elif ext in ARCHIVE_EXT:
            archive_files.append(f)
        elif ext in LOG_EXT:
            log_files.append(f)
        else:
            unknown.append(f)

    if unknown:
        preview = "\n".join(unknown[:20])
        extra = ""
        if len(unknown) > 20:
            extra = f"\n... and {len(unknown) - 20} more"
        messagebox.showerror(
            "Unknown file types remain",
            "Unexpected files detected:\n\n" + preview + extra
        )
        return

    # Step EDF Compatibility Checks
    edf_zip_name = make_zip_name("Step_EDFCompCheck", use_timestamp)
    edf_zip_path = os.path.join(dst, edf_zip_name)
    zip_and_move(edf_files, edf_zip_path)

    # Step A Archives
    archive_dir = os.path.join(dst, "StepA_Natus")
    move_archives(archive_files, archive_dir)

    # Step BC
    bc_zip_name = make_zip_name("StepBC", use_timestamp)
    bc_zip_path = os.path.join(dst, bc_zip_name)
    zip_and_move(log_files, bc_zip_path)

    messagebox.showinfo(
        "Done",
        "Backup completed successfully.\n\n"
        f"EDF ZIP: {edf_zip_path}\n"
        f"Archives Folder: {archive_dir}\n"
        f"Logs ZIP: {bc_zip_path}"
    )


class App:
    def __init__(self, root):
        self.root = root
        root.title("EDF Backup Utility")
        root.geometry("620x260")

        self.src = tk.StringVar()
        self.dst = tk.StringVar()
        self.use_timestamp = tk.BooleanVar(value=True)

        tk.Label(root, text="Source Folder").pack(pady=(10, 5))
        tk.Entry(root, textvariable=self.src, width=75).pack()

        tk.Button(root, text="Browse Source", command=self.pick_src).pack(pady=5)

        tk.Label(root, text="Destination Folder").pack(pady=(10, 5))
        tk.Entry(root, textvariable=self.dst, width=75).pack()

        tk.Button(root, text="Browse Destination", command=self.pick_dst).pack(pady=5)

        tk.Checkbutton(
            root,
            text="Append timestamp to ZIP filenames",
            variable=self.use_timestamp
        ).pack(pady=(10, 5))

        tk.Button(
            root,
            text="Run Backup",
            command=self.run,
            bg="green",
            fg="white",
            width=20
        ).pack(pady=15)

    def pick_src(self):
        folder = filedialog.askdirectory()
        if folder:
            self.src.set(folder)

    def pick_dst(self):
        folder = filedialog.askdirectory()
        if folder:
            self.dst.set(folder)

    def run(self):
        src = self.src.get().strip()
        dst = self.dst.get().strip()

        if not src or not dst:
            messagebox.showerror("Error", "Select source and destination folders.")
            return

        run_process(src, dst, self.use_timestamp.get())


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()