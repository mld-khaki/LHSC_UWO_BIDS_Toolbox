import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk
from tkinterdnd2 import TkinterDnD, DND_FILES
import os
import time
import csv
import pyperclip
import json

class FileListApp:
    def __init__(self, root):
        self.root = root
        self.root.title("File List Manager — Compare • Sort • Dedupe • Logging • Sessions")

        # Action log
        self.action_log = []

        # ===== Layout frames =====
        frame_top = tk.Frame(root)
        frame_top.pack(pady=6, fill="x")

        frame_lists = tk.Frame(root)
        frame_lists.pack(pady=6, fill="both", expand=True)

        frame_controls = tk.Frame(root)
        frame_controls.pack(pady=6, fill="x")

        frame_status = tk.Frame(root)
        frame_status.pack(pady=4, fill="x")

        # ===== Left list (with scrollbar) =====
        left_wrap = tk.Frame(frame_lists)
        left_wrap.grid(row=0, column=0, padx=6, sticky="nsew")

        self.listbox_left = tk.Listbox(left_wrap, selectmode=tk.EXTENDED, width=80, height=24)
        self.listbox_left.grid(row=0, column=0, sticky="nsew")
        sb_left = tk.Scrollbar(left_wrap, orient="vertical", command=self.listbox_left.yview)
        sb_left.grid(row=0, column=1, sticky="ns")
        self.listbox_left.config(yscrollcommand=sb_left.set)
        left_wrap.grid_rowconfigure(0, weight=1)
        left_wrap.grid_columnconfigure(0, weight=1)

        # ===== Right list (with scrollbar) =====
        right_wrap = tk.Frame(frame_lists)
        right_wrap.grid(row=0, column=1, padx=6, sticky="nsew")

        self.listbox_right = tk.Listbox(right_wrap, selectmode=tk.EXTENDED, width=80, height=24)
        self.listbox_right.grid(row=0, column=0, sticky="nsew")
        sb_right = tk.Scrollbar(right_wrap, orient="vertical", command=self.listbox_right.yview)
        sb_right.grid(row=0, column=1, sticky="ns")
        self.listbox_right.config(yscrollcommand=sb_right.set)
        right_wrap.grid_rowconfigure(0, weight=1)
        right_wrap.grid_columnconfigure(0, weight=1)

        frame_lists.grid_rowconfigure(0, weight=1)
        frame_lists.grid_columnconfigure(0, weight=1)
        frame_lists.grid_columnconfigure(1, weight=1)

        # ===== Drag & drop enable =====
        self.listbox_left.drop_target_register(DND_FILES)
        self.listbox_left.dnd_bind("<<Drop>>",
                                   lambda e: self.drop_into_list(e, self.listbox_left, "Left"))
        self.listbox_right.drop_target_register(DND_FILES)
        self.listbox_right.dnd_bind("<<Drop>>",
                                    lambda e: self.drop_into_list(e, self.listbox_right, "Right"))

        # ===== Top: load/import/save controls (grouped horizontally) =====
        # Active side selector (one set of buttons drives Left/Right)
        self.side_var = tk.StringVar(value="Left")
        tk.Label(frame_top, text="Active list:").grid(row=0, column=0, padx=(4,0))
        tk.Radiobutton(frame_top, text="Left", variable=self.side_var, value="Left").grid(row=0, column=1, padx=4)
        tk.Radiobutton(frame_top, text="Right", variable=self.side_var, value="Right").grid(row=0, column=2, padx=4)

        # Load buttons
        tk.Button(frame_top, text="Load from Clipboard",
                  command=lambda: self.load_from_clipboard(self.active_listbox(), self.side_var.get())
                  ).grid(row=0, column=3, padx=6)
        tk.Button(frame_top, text="Load TXT",
                  command=lambda: self.load_from_file(self.active_listbox(), self.side_var.get())
                  ).grid(row=0, column=4, padx=6)
        tk.Button(frame_top, text="Load Directory",
                  command=lambda: self.load_from_directory(self.active_listbox(), self.side_var.get())
                  ).grid(row=0, column=5, padx=6)
        tk.Button(frame_top, text="Import Structured",
                  command=self.import_structured_dialog
                  ).grid(row=0, column=6, padx=6)

        # Sessions & Log
        tk.Button(frame_top, text="Save Session", command=self.save_session).grid(row=0, column=7, padx=6)
        tk.Button(frame_top, text="Load Session", command=self.load_session).grid(row=0, column=8, padx=6)
        tk.Button(frame_top, text="Export Log", command=self.export_log).grid(row=0, column=9, padx=6)

        # ===== Controls: sorting / compare / dedupe / find / removal =====
        # Sorting area
        sort_opts = ["Name (A→Z)", "Name (Z→A)", "Size (asc)", "Size (desc)"]
        self.sort_choice = tk.StringVar(value=sort_opts[0])
        tk.Label(frame_controls, text="Sort:").grid(row=0, column=0, padx=(4,0))
        self.sort_box = ttk.Combobox(frame_controls, values=sort_opts, textvariable=self.sort_choice, state="readonly", width=14)
        self.sort_box.grid(row=0, column=1, padx=4)
        self.sort_both = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_controls, text="Apply to both", variable=self.sort_both).grid(row=0, column=2, padx=6)
        tk.Button(frame_controls, text="Apply Sort", command=self.apply_sort_ui).grid(row=0, column=3, padx=6)

        # Compare & partials
        tk.Button(frame_controls, text="Compare (color both)", command=self.compare_lists).grid(row=0, column=4, padx=6)
        tk.Button(frame_controls, text="Find Partials in Other", command=self.find_partials_in_other).grid(row=0, column=5, padx=6)

        # Dedupe & removals
        tk.Button(frame_controls, text="Highlight Duplicates", command=self.highlight_duplicates).grid(row=0, column=6, padx=6)
        tk.Button(frame_controls, text="Remove Duplicates (keep largest)", command=self.remove_duplicates_keep_largest).grid(row=0, column=7, padx=6)
        tk.Button(frame_controls, text="Remove Selected", command=self.remove_selected_in_active).grid(row=0, column=8, padx=6)
        tk.Button(frame_controls, text="Remove Zero-Size", command=self.remove_zero_size_in_active).grid(row=0, column=9, padx=6)

        # Manual size
        tk.Button(frame_controls, text="Set/Edit Size…", command=self.manual_size_active).grid(row=0, column=10, padx=6)

        # Remove overlaps
        tk.Button(frame_controls, text="Remove Left from Right", command=self.remove_left_from_right).grid(row=0, column=11, padx=6)
        tk.Button(frame_controls, text="Remove Right from Left", command=self.remove_right_from_left).grid(row=0, column=12, padx=6)

        # Clear current
        tk.Button(frame_controls, text="Clear Active", command=self.clear_active).grid(row=0, column=13, padx=6)

        # Export CSV (active)
        tk.Button(frame_controls, text="Export Active to CSV", command=self.export_active_csv).grid(row=0, column=14, padx=6)

        # ===== Status labels =====
        self.label_left_status = tk.Label(frame_status, text="Left: 0 items (0 B)")
        self.label_left_status.pack(side="left", padx=12)
        self.label_right_status = tk.Label(frame_status, text="Right: 0 items (0 B)")
        self.label_right_status.pack(side="left", padx=12)

        self.update_status_labels()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        """
        Auto-save session JSON and log text on exit using the following rules:
        - Session: save to last saved/loaded session path if available; otherwise to ./session_autosave.json
        - Log: if user exported or chose a preferred log path, use it;
               else if a session path exists, save beside it as <session_basename>_log.txt;
               else save to ./log_autosave.txt
        """
        try:
            # --- session path ---
            session_path = self.last_session_path
            if not session_path:
                session_path = os.path.join(os.getcwd(), "session_autosave.json")

            session_data = {
                "left": list(self.listbox_left.get(0, tk.END)),
                "right": list(self.listbox_right.get(0, tk.END)),
                "log": self.action_log
            }
            try:
                with open(session_path, "w", encoding="utf-8") as f:
                    json.dump(session_data, f, indent=2)
                self.log_action(f"Auto-saved session on exit to {session_path}")
            except Exception as e:
                messagebox.showerror("Auto Save (Session)", f"Failed to auto-save session: {e}")

            # --- log path ---
            log_path = getattr(self, "log_file_path", None)
            if not log_path:
                if self.last_session_path:
                    base = os.path.splitext(os.path.basename(self.last_session_path))[0]
                    dir_ = os.path.dirname(self.last_session_path)
                    log_path = os.path.join(dir_, f"{base}_log.txt")
                else:
                    log_path = os.path.join(os.getcwd(), "log_autosave.txt")

            try:
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(self.action_log))
            except Exception as e:
                messagebox.showerror("Auto Save (Log)", f"Failed to auto-save log: {e}")

        finally:
            # close the app regardless; we've tried best-effort saves
            self.root.destroy()


    # ---------- Helpers ----------
    def active_listbox(self):
        return self.listbox_left if self.side_var.get() == "Left" else self.listbox_right

    def other_listbox(self):
        return self.listbox_right if self.side_var.get() == "Left" else self.listbox_left

    def log_action(self, action):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.action_log.append(f"[{ts}] {action}")

    def sizeof_fmt(self, num, suffix="B"):
        try:
            n = float(num)
        except:
            n = 0.0
        for unit in ["", "K", "M", "G", "T"]:
            if abs(n) < 1024.0:
                return f"{n:.2f} {unit}{suffix}"
            n /= 1024.0
        return f"{n:.2f} P{suffix}"

    def parse_size_any(self, s):
        """Parse size string like '903 b', '751.9 k', '1.2 mb', '3 GB', returns bytes (int). Case-insensitive."""
        if s is None:
            return None
        s = s.strip().lower()
        # normalize spacing, remove commas
        s = s.replace(",", " ")
        parts = s.split()
        if not parts:
            return None
        # try simple number => bytes
        try:
            val = float(parts[0])
            unit = parts[1] if len(parts) > 1 else "b"
        except ValueError:
            return None
        unit = unit.lower()
        # map units
        if unit in ("b", "byte", "bytes"):
            mult = 1
        elif unit in ("k", "kb", "kib"):
            mult = 1024
        elif unit in ("m", "mb", "mib"):
            mult = 1024**2
        elif unit in ("g", "gb", "gib"):
            mult = 1024**3
        elif unit in ("t", "tb", "tib"):
            mult = 1024**4
        else:
            mult = 1
        return int(val * mult)

    def display_text(self, name, size_bytes):
        return f"{name} ({self.sizeof_fmt(size_bytes)})" if size_bytes is not None else name

    def get_base(self, item_text):
        # everything before the last " (" is the base name
        idx = item_text.rfind(" (")
        return item_text[:idx] if idx != -1 and item_text.endswith(")") else item_text

    def get_size_from_item(self, item_text):
        # expects "... (N UNIT)"
        if not (item_text.endswith(")") and "(" in item_text):
            return None
        size_str = item_text[item_text.rfind("(")+1:-1]
        try:
            num, unit = size_str.split()
            num = float(num)
            unit = unit.lower()
        except Exception:
            return None
        if unit.startswith("k"):
            return int(num * 1024)
        if unit.startswith("m"):
            return int(num * 1024**2)
        if unit.startswith("g"):
            return int(num * 1024**3)
        if unit.startswith("t"):
            return int(num * 1024**4)
        if unit.startswith("p"):
            return int(num * 1024**5)
        # bytes
        return int(num)

    def find_index_by_base(self, listbox, base):
        for i in range(listbox.size()):
            if self.get_base(listbox.get(i)) == base:
                return i
        return None

    def add_item(self, listbox, name, size_bytes=None, side_label=""):
        """Add with dedupe by base name; if exists, keep the larger size."""
        base = name
        idx = self.find_index_by_base(listbox, base)
        if idx is not None:
            existing = listbox.get(idx)
            existing_size = self.get_size_from_item(existing)
            ex = existing_size if existing_size is not None else -1
            nw = size_bytes if size_bytes is not None else -1
            if nw > ex:
                listbox.delete(idx)
                listbox.insert(idx, self.display_text(base, size_bytes))
                self.log_action(f"Updated size for duplicate '{base}' in {side_label} to {self.sizeof_fmt(size_bytes)}")
            else:
                self.log_action(f"Skipped duplicate '{base}' in {side_label}")
            return False
        else:
            listbox.insert(tk.END, self.display_text(base, size_bytes))
            return True

    # ---------- Drops with live progress ----------
    def drop_into_list(self, event, listbox, side):
        raw = event.data.strip()
        # robust parsing for {C:\path with spaces} {D:\other}
        paths = []
        current = ""
        inside_brace = False
        for ch in raw:
            if ch == "{":
                inside_brace = True
                current = ""
            elif ch == "}":
                inside_brace = False
                paths.append(current)
                current = ""
            elif ch == " " and not inside_brace:
                if current:
                    paths.append(current)
                    current = ""
            else:
                current += ch
        if current:
            paths.append(current)

        progress = tk.Toplevel(self.root)
        progress.title("Processing Drops")
        label = tk.Label(progress, text="Starting…", width=100, anchor="w")
        label.pack(padx=18, pady=14)
        self.root.update()

        added, errors = 0, 0
        total = len(paths)

        for idx, p in enumerate(paths, 1):
            try:
                label.config(text=f"Processing {idx}/{total}: {p}")
                self.root.update_idletasks()

                if os.path.isdir(p):
                    size = self.dir_size(p)
                    base = os.path.basename(p)
                    if self.add_item(listbox, base, size, side_label=side):
                        self.log_action(f"Dropped directory {p} into {side}, size {self.sizeof_fmt(size)}")
                        added += 1
                elif os.path.isfile(p):
                    size = os.path.getsize(p)
                    base = os.path.basename(p)
                    if self.add_item(listbox, base, size, side_label=side):
                        self.log_action(f"Dropped file {p} into {side}, size {self.sizeof_fmt(size)}")
                        added += 1
                else:
                    errors += 1
                    self.log_action(f"Ignored invalid drop {p}")
            except Exception as e:
                errors += 1
                self.log_action(f"Error processing {p}: {e}")

        progress.destroy()
        self.update_status_labels()
        messagebox.showinfo("Drop Complete", f"Added {added} items to {side}.\nErrors: {errors}")

    # ---------- Size & totals ----------
    def get_total_size(self, listbox):
        total = 0
        for i in range(listbox.size()):
            sz = self.get_size_from_item(listbox.get(i))
            if sz:
                total += sz
        return total

    def update_status_labels(self):
        lc = self.listbox_left.size()
        rc = self.listbox_right.size()
        ls = self.get_total_size(self.listbox_left)
        rs = self.get_total_size(self.listbox_right)
        self.label_left_status.config(text=f"Left: {lc} items ({self.sizeof_fmt(ls)})")
        self.label_right_status.config(text=f"Right: {rc} items ({self.sizeof_fmt(rs)})")

    # ---------- Loading ----------
    def load_from_clipboard(self, listbox, side):
        try:
            data = pyperclip.paste()
            items = [line.strip() for line in data.splitlines() if line.strip()]
            added = 0
            for item in items:
                # Try to parse "name (size)" if present; otherwise plain name
                base = self.get_base(item)
                size = self.get_size_from_item(item)
                if self.add_item(listbox, base, size, side_label=side):
                    added += 1
            self.log_action(f"Loaded {added}/{len(items)} items into {side} from clipboard (dedup applied)")
            self.update_status_labels()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load from clipboard: {e}")

    def load_from_file(self, listbox, side):
        filename = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if filename:
            try:
                count = 0
                total_lines = 0
                with open(filename, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        total_lines += 1
                        item = line.strip()
                        if not item:
                            continue
                        base = self.get_base(item)
                        size = self.get_size_from_item(item)
                        if self.add_item(listbox, base, size, side_label=side):
                            count += 1
                self.log_action(f"Loaded {count}/{total_lines} items into {side} from file {filename} (dedup applied)")
                self.update_status_labels()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load from file: {e}")

    def dir_size(self, path):
        total = 0
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return total

    def load_from_directory(self, listbox, side):
        dirname = filedialog.askdirectory()
        if dirname:
            try:
                size = self.dir_size(dirname)
                base = os.path.basename(dirname)
                if self.add_item(listbox, base, size, side_label=side):
                    self.log_action(f"Loaded directory {dirname} into {side}, size {self.sizeof_fmt(size)}")
                self.update_status_labels()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load directory: {e}")

    # ---------- Export CSV ----------
    def export_active_csv(self):
        lb = self.active_listbox()
        side = self.side_var.get()
        self.export_to_csv(lb, side)

    def export_to_csv(self, listbox, side):
        filename = filedialog.asksaveasfilename(defaultextension=".csv",
                                                filetypes=[("CSV files", "*.csv")])
        if filename:
            try:
                with open(filename, "w", newline="", encoding="utf-8") as csvfile:
                    writer = csv.writer(csvfile)
                    for item in listbox.get(0, tk.END):
                        writer.writerow([item])
                self.log_action(f"Exported {side} list to {filename}")
                messagebox.showinfo("Export", f"Exported successfully to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export: {e}")

    # ---------- Compare / Partials ----------
    def compare_lists(self):
        left_items = set([self.get_base(self.listbox_left.get(i)) for i in range(self.listbox_left.size())])
        right_items = set([self.get_base(self.listbox_right.get(i)) for i in range(self.listbox_right.size())])

        # Reset colors
        for i in range(self.listbox_left.size()):
            self.listbox_left.itemconfig(i, {'fg': 'black'})
        for i in range(self.listbox_right.size()):
            self.listbox_right.itemconfig(i, {'fg': 'black'})

        # Apply coloring rules
        for i in range(self.listbox_left.size()):
            item = self.get_base(self.listbox_left.get(i))
            if item in right_items:
                self.listbox_left.itemconfig(i, {'fg': 'red'})   # exists in both
            else:
                self.listbox_left.itemconfig(i, {'fg': 'green'}) # only in left

        for i in range(self.listbox_right.size()):
            item = self.get_base(self.listbox_right.get(i))
            if item in left_items:
                self.listbox_right.itemconfig(i, {'fg': 'red'})   # exists in both
            else:
                self.listbox_right.itemconfig(i, {'fg': 'blue'})  # only in right

        self.log_action("Compared Left and Right lists")

    def find_partials_in_other(self):
        src_lb = self.active_listbox()
        dst_lb = self.other_listbox()
        side_src = self.side_var.get()
        side_dst = "Right" if side_src == "Left" else "Left"

        sel = src_lb.curselection()
        if not sel:
            messagebox.showwarning("Find Partials", f"Select an item in {side_src} first.")
            return
        base = self.get_base(src_lb.get(sel[0]))
        # split tokens by _ and -
        tokens = []
        for tok in base.replace("-", "_").split("_"):
            t = tok.strip()
            if len(t) >= 2:
                tokens.append(t.lower())

        # Reset colors on destination before highlighting
        for i in range(dst_lb.size()):
            dst_lb.itemconfig(i, {'fg': 'black'})

        matched_indices = set()
        for i in range(dst_lb.size()):
            name = self.get_base(dst_lb.get(i)).lower()
            if any(t in name for t in tokens):
                matched_indices.add(i)
                dst_lb.itemconfig(i, {'fg': 'magenta'})

        self.log_action(f"Find Partials: selected '{base}' in {side_src}; highlighted {len(matched_indices)} items in {side_dst}")
        if matched_indices:
            messagebox.showinfo("Find Partials", f"Highlighted {len(matched_indices)} matches in {side_dst} (magenta).")
        else:
            messagebox.showinfo("Find Partials", f"No partial matches found in {side_dst}.")

    # ---------- Remove overlaps / clear ----------
    def remove_left_from_right(self):
        left_items = set([self.listbox_left.get(i).split(" (")[0] for i in range(self.listbox_left.size())])
        right_items = [self.listbox_right.get(i) for i in range(self.listbox_right.size())]

        removed_items = []
        kept_items = []
        for item in right_items:
            base = item.split(" (")[0]
            if base not in left_items:
                kept_items.append(item)
            else:
                removed_items.append(item)

        self.listbox_right.delete(0, tk.END)
        for it in kept_items:
            self.listbox_right.insert(tk.END, it)

        self.log_action(f"Removed {len(removed_items)} items from Right that matched Left: {removed_items}")
        self.update_status_labels()


    def remove_right_from_left(self):
        right_items = set([self.listbox_right.get(i).split(" (")[0] for i in range(self.listbox_right.size())])
        left_items = [self.listbox_left.get(i) for i in range(self.listbox_left.size())]

        removed_items = []
        kept_items = []
        for item in left_items:
            base = item.split(" (")[0]
            if base not in right_items:
                kept_items.append(item)
            else:
                removed_items.append(item)

        self.listbox_left.delete(0, tk.END)
        for it in kept_items:
            self.listbox_left.insert(tk.END, it)

        self.log_action(f"Removed {len(removed_items)} items from Left that matched Right: {removed_items}")
        self.update_status_labels()


    def clear_active(self):
        lb = self.active_listbox()
        side = self.side_var.get()
        count = lb.size()
        lb.delete(0, tk.END)
        self.log_action(f"Cleared {side} list ({count} items removed)")
        self.update_status_labels()

    # ---------- Dedupe ----------
    def highlight_duplicates(self):
        lb = self.active_listbox()
        seen = {}
        dup_count = 0
        # reset colors
        for i in range(lb.size()):
            lb.itemconfig(i, {'fg': 'black'})
        for i in range(lb.size()):
            base = self.get_base(lb.get(i))
            if base in seen:
                lb.itemconfig(i, {'fg': 'orange'})
                dup_count += 1
            else:
                seen[base] = i
        self.log_action(f"Highlighted {dup_count} duplicates in {self.side_var.get()} (orange)")
        messagebox.showinfo("Duplicates", f"Highlighted {dup_count} duplicate entries (orange).")

    def remove_duplicates_keep_largest(self):
        lb = self.active_listbox()
        by_base = {}
        # find best (largest size) per base
        for i in range(lb.size()):
            txt = lb.get(i)
            base = self.get_base(txt)
            size = self.get_size_from_item(txt) or -1
            if base not in by_base or size > by_base[base][1]:
                by_base[base] = (i, size)

        # rebuild list keeping only the best
        new_items = []
        kept = set()
        for base, (_, size) in by_base.items():
            # find the original item text to preserve formatting
            # prefer the first matching with that size
            chosen = None
            for i in range(lb.size()):
                txt = lb.get(i)
                if self.get_base(txt) == base:
                    s = self.get_size_from_item(txt) or -1
                    if s == size:
                        chosen = txt
                        break
            if chosen:
                new_items.append(chosen)
                kept.add(base)

        removed = lb.size() - len(new_items)
        lb.delete(0, tk.END)
        for it in sorted(new_items, key=lambda x: self.get_base(x).lower()):
            lb.insert(tk.END, it)
        self.log_action(f"Removed {removed} duplicates in {self.side_var.get()} (kept largest per base)")
        self.update_status_labels()
        messagebox.showinfo("Remove Duplicates", f"Removed {removed} duplicates; kept the largest per name.")

    def remove_selected_in_active(self):
        lb = self.active_listbox()
        sel = list(lb.curselection())
        if not sel:
            messagebox.showwarning("Remove Selected", "No items selected.")
            return
        sel.sort(reverse=True)
        for i in sel:
            lb.delete(i)
        self.log_action(f"Removed {len(sel)} selected items in {self.side_var.get()}")
        self.update_status_labels()

    def remove_zero_size_in_active(self):
        lb = self.active_listbox()
        kept = []
        removed = 0
        for i in range(lb.size()):
            txt = lb.get(i)
            sz = self.get_size_from_item(txt)
            if sz is None or sz > 0:
                kept.append(txt)
            else:
                removed += 1
        lb.delete(0, tk.END)
        for it in kept:
            lb.insert(tk.END, it)
        self.log_action(f"Removed {removed} zero-size items in {self.side_var.get()}")
        self.update_status_labels()
        messagebox.showinfo("Remove Zero-Size", f"Removed {removed} items with size 0.")

    # ---------- Manual size ----------
    def manual_size_active(self):
        lb = self.active_listbox()
        side = self.side_var.get()
        sel = lb.curselection()
        if not sel:
            messagebox.showwarning("Set/Edit Size", "Select at least one item.")
            return
        size_str = simpledialog.askstring("Set/Edit Size", "Enter size (e.g., 903 b, 751.9 kb, 1.2 gb):")
        if size_str is None:
            return
        size_bytes = self.parse_size_any(size_str)
        if size_bytes is None:
            messagebox.showerror("Set/Edit Size", "Could not parse size.")
            return
        for i in sel:
            base = self.get_base(lb.get(i))
            lb.delete(i)
            lb.insert(i, self.display_text(base, size_bytes))
        self.log_action(f"Manually set size for {len(sel)} items in {side} to {self.sizeof_fmt(size_bytes)}")
        self.update_status_labels()

    # ---------- Sorting ----------
    def apply_sort_ui(self):
        both = self.sort_both.get()
        mode = self.sort_choice.get()
        if both:
            self.apply_sort(self.listbox_left, mode)
            self.apply_sort(self.listbox_right, mode)
            self.log_action(f"Sorted both lists by '{mode}'")
        else:
            lb = self.active_listbox()
            self.apply_sort(lb, mode)
            self.log_action(f"Sorted {self.side_var.get()} by '{mode}'")

    def apply_sort(self, lb, mode):
        items = [lb.get(i) for i in range(lb.size())]
        if "Name" in mode:
            rev = "Z→A" in mode
            items.sort(key=lambda x: self.get_base(x).lower(), reverse=rev)
        else:
            # Size sort
            asc = "asc" in mode
            def key_fn(x):
                sz = self.get_size_from_item(x)
                # Treat None as -1 so they go last if ascending, first if descending
                return -1 if sz is None else sz
            items.sort(key=key_fn, reverse=not asc)
        lb.delete(0, tk.END)
        for it in items:
            lb.insert(tk.END, it)

    # ---------- Import structured (clipboard/TXT) ----------
    def import_structured_dialog(self):
        side = self.side_var.get()
        lb = self.active_listbox()
        end_pat = simpledialog.askstring("Import Structured", "End pattern (e.g., .rar):")
        if not end_pat:
            return
        use_clip = messagebox.askyesno("Import Structured", "Use clipboard? (Yes = Clipboard, No = Choose TXT file)")
        lines = []
        src = ""
        try:
            if use_clip:
                src = "clipboard"
                data = pyperclip.paste()
                lines = [ln for ln in data.splitlines() if ln.strip()]
            else:
                filename = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
                if not filename:
                    return
                src = filename
                with open(filename, "r", encoding="utf-8", errors="ignore") as f:
                    lines = [ln for ln in f.read().splitlines() if ln.strip()]
        except Exception as e:
            messagebox.showerror("Import Structured", f"Failed to read source: {e}")
            return

        added = 0
        for ln in lines:
            # Expect tab-separated: name \t size \t date \t flags
            parts = [p for p in ln.split("\t") if p.strip() != ""]
            if not parts:
                continue
            name_col = parts[0]
            # truncate name up to end pattern if present
            lower_name = name_col
            idx = lower_name.lower().find(end_pat.lower())
            base = (lower_name[:idx + len(end_pat)]) if idx != -1 else name_col
            size_col = parts[1] if len(parts) > 1 else ""
            size_bytes = self.parse_size_any(size_col)
            if self.add_item(lb, base, size_bytes, side_label=side):
                added += 1
                self.log_action(f"Structured import: '{base}' size {self.sizeof_fmt(size_bytes) if size_bytes is not None else 'N/A'} from {src}")
        self.update_status_labels()
        messagebox.showinfo("Import Structured", f"Added {added} items to {side} (dedup applied).")

    # ---------- Log / Session ----------
    def export_log(self):
        filename = filedialog.asksaveasfilename(defaultextension=".txt",
                                                filetypes=[("Text files", "*.txt")])
        if filename:
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write("\n".join(self.action_log))
                # remember preferred log path for auto-save-on-exit
                self.log_file_path = filename
                messagebox.showinfo("Export Log", f"Log exported successfully to {filename}")
                self.log_action(f"Exported log to {filename} (and set as preferred auto-save location)")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export log: {e}")


    def save_session(self):
        filename = filedialog.asksaveasfilename(defaultextension=".json",
                                                filetypes=[("JSON files", "*.json")])
        if filename:
            try:
                session_data = {
                    "left": list(self.listbox_left.get(0, tk.END)),
                    "right": list(self.listbox_right.get(0, tk.END)),
                    "log": self.action_log
                }
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(session_data, f, indent=2)

                # remember for auto-save-on-exit
                self.last_session_path = filename

                # propose a default log path beside the session file
                base = os.path.splitext(os.path.basename(filename))[0]
                default_log_path = os.path.join(os.path.dirname(filename), f"{base}_log.txt")

                # ask if user wants to change log location
                use_default = messagebox.askyesno(
                    "Log Location",
                    f"Use this log file path for autosave?\n\n{default_log_path}\n\n"
                    f"Choose 'No' to pick a different path."
                )
                if use_default:
                    self.log_file_path = default_log_path
                else:
                    picked = filedialog.asksaveasfilename(defaultextension=".txt",
                                                          filetypes=[("Text files", "*.txt")])
                    if picked:
                        self.log_file_path = picked
                    else:
                        # if user cancels, fall back to default beside session
                        self.log_file_path = default_log_path

                self.log_action(f"Saved session to {filename}; log autosave path set to {self.log_file_path}")
                messagebox.showinfo("Save Session", f"Session saved successfully to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save session: {e}")


    def load_session(self):
        filename = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if filename:
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    session_data = json.load(f)
                # Restore lists
                self.listbox_left.delete(0, tk.END)
                self.listbox_right.delete(0, tk.END)
                for item in session_data.get("left", []):
                    self.listbox_left.insert(tk.END, item)
                for item in session_data.get("right", []):
                    self.listbox_right.insert(tk.END, item)
                # Restore log
                self.action_log = session_data.get("log", [])
                # remember for auto-save-on-exit
                self.last_session_path = filename

                self.log_action(f"Loaded session from {filename}")
                self.update_status_labels()
                messagebox.showinfo("Load Session", f"Session loaded successfully from {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load session: {e}")



if __name__ == "__main__":
    root = TkinterDnD.Tk()  # must use this, not tk.Tk()
    app = FileListApp(root)
    root.mainloop()
