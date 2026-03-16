import difflib
import natus_edf_tools.StepC_BIDS_management.Redaction_TSV.diff_review_tool.modules.config as config

class DiffEngine:

    def compute(self, source_lines, target_lines):

        matcher = difflib.SequenceMatcher(None, source_lines, target_lines)

        blocks = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():

            if tag == "equal":
                continue

            start = max(0, i1 - config.CONTEXT_LINES)
            end = min(len(source_lines), i2 + config.CONTEXT_LINES)

            blocks.append({
                "tag": tag,
                "src_start": i1,
                "src_end": i2,
                "tgt_start": j1,
                "tgt_end": j2,
                "context_start": start,
                "context_end": end
            })

        return blocks