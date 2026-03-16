class MergeEngine:

    def build(self, source_lines, target_lines, decisions, blocks):

        result = []

        src_ptr = 0

        for idx, block in enumerate(blocks):

            result.extend(source_lines[src_ptr:block["src_start"]])

            decision = decisions.get(idx, "discard")

            if decision == "accept":

                result.extend(target_lines[block["tgt_start"]:block["tgt_end"]])

            else:

                result.extend(source_lines[block["src_start"]:block["src_end"]])

            src_ptr = block["src_end"]

        result.extend(source_lines[src_ptr:])

        return result