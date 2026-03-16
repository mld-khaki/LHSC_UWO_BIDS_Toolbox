import json
import natus_edf_tools.StepC_BIDS_management.Redaction_TSV.diff_review_tool.modules.config as config

class ProgressManager:

    def save(self, data):

        with open(config.PROGRESS_FILE,"w") as f:

            json.dump(data,f,indent=2)

    def load(self):

        try:

            with open(config.PROGRESS_FILE) as f:

                return json.load(f)

        except:

            return {}