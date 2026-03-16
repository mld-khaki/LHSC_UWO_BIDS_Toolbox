from pathlib import Path
import natus_edf_tools.StepC_BIDS_management.Redaction_TSV.diff_review_tool.modules.config as config

class FileManager:

    def source(self, rel_path):

        return config.INPUT_FOLDER / rel_path

    def target(self, rel_path):

        return config.TARGET_FOLDER / rel_path

    def output(self, rel_path):

        return config.OUTPUT_FOLDER / rel_path

    def ensure_output(self, path):

        path.parent.mkdir(parents=True, exist_ok=True)