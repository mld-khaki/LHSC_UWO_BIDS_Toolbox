import sys

from PySide6.QtWidgets import QApplication

import natus_edf_tools.StepC_BIDS_management.Redaction_TSV.diff_review_tool.modules.config as config
from natus_edf_tools.StepC_BIDS_management.Redaction_TSV.diff_review_tool.modules.csv_manager import CSVManager
from natus_edf_tools.StepC_BIDS_management.Redaction_TSV.diff_review_tool.modules.file_manager import FileManager
from natus_edf_tools.StepC_BIDS_management.Redaction_TSV.diff_review_tool.modules.diff_engine import DiffEngine
from natus_edf_tools.StepC_BIDS_management.Redaction_TSV.diff_review_tool.modules.merge_engine import MergeEngine
from natus_edf_tools.StepC_BIDS_management.Redaction_TSV.diff_review_tool.modules.progress_manager import ProgressManager

from natus_edf_tools.StepC_BIDS_management.Redaction_TSV.diff_review_tool.gui.main_window import MainWindow
from natus_edf_tools.StepC_BIDS_management.Redaction_TSV.diff_review_tool.gui.keyboard import register


class Controller:

    def __init__(self):

        self.csv = CSVManager(config.CSV_FILE)
        self.files = self.csv.get_files()

        self.file_index = 0
        self.diff_index = 0

        self.decisions = {}

        self.fm = FileManager()
        self.diff_engine = DiffEngine()
        self.merge = MergeEngine()

        self.window = MainWindow(self)

        register(self.window,self)

        self.load_file()

    def load_file(self):

        if self.file_index >= len(self.files):

            print("Done")

            sys.exit()

        row = self.files[self.file_index]

        rel = row["rel_path"]

        with open(self.fm.source(rel)) as f:
            self.src_lines = f.readlines()

        with open(self.fm.target(rel)) as f:
            self.tgt_lines = f.readlines()

        self.blocks = self.diff_engine.compute(self.src_lines,self.tgt_lines)

        if not self.blocks:

            out = self.fm.output(rel)

            self.fm.ensure_output(out)

            with open(out,"w") as f:

                f.writelines(self.tgt_lines)

            row["review_status"]="completed"

            self.csv.save()

            self.file_index += 1

            self.load_file()

            return

        self.diff_index = 0

        self.show_diff()

    def show_diff(self):

        block = self.blocks[self.diff_index]

        src = "".join(self.src_lines[block["context_start"]:block["context_end"]])
        tgt = "".join(self.tgt_lines[block["context_start"]:block["context_end"]])

        self.window.left.display(src, tgt, "left")
        self.window.right.display(src, tgt, "right")

        self.window.status.setText(
            f"File {self.file_index+1}/{len(self.files)} | Diff {self.diff_index+1}/{len(self.blocks)}"
        )

    def accept(self):

        self.decisions[self.diff_index]="accept"

        self.next()

    def discard(self):

        self.decisions[self.diff_index]="discard"

        self.next()

    def next(self):

        self.diff_index += 1

        if self.diff_index >= len(self.blocks):

            self.finish_file()

        else:

            self.show_diff()

    def previous(self):

        if self.diff_index>0:

            self.diff_index -= 1

            self.show_diff()

    def skip_file(self):

        row = self.files[self.file_index]

        row["review_status"]="skipped"

        self.csv.save()

        self.file_index += 1

        self.load_file()

    def finish_file(self):

        row = self.files[self.file_index]

        rel = row["rel_path"]

        merged = self.merge.build(
            self.src_lines,
            self.tgt_lines,
            self.decisions,
            self.blocks
        )

        out = self.fm.output(rel)

        self.fm.ensure_output(out)

        with open(out,"w") as f:

            f.writelines(merged)

        row["review_status"]="completed"

        row["diffs_total"]=len(self.blocks)
        row["accepted"]=list(self.decisions.values()).count("accept")
        row["discarded"]=list(self.decisions.values()).count("discard")
        row["output_path"]=str(out)

        self.csv.save()

        self.file_index += 1

        self.decisions={}

        self.load_file()

    def save(self):

        self.csv.save()

    def quit(self):

        sys.exit()


app = QApplication(sys.argv)

controller = Controller()

controller.window.show()

sys.exit(app.exec())