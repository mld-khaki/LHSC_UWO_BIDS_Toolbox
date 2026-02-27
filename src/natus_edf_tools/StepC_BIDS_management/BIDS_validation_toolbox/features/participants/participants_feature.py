from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import pandas as pd

from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.utils.file_ops import safe_copy_file, ensure_dir
from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.features.participants.excel_reader import read_demographics_excel


@dataclass
class ParticipantsFeatureSettings:
    excel_path: str
    sheet_name: str
    col_participant_id: str
    col_age: str
    col_sex: str
    col_group: str
    default_group: str = "patient"

    # Requirement: only subjects present in BIDS folder
    include_only_bids_subjects: bool = True
    bids_subjects: list[str] = None

    # duplicates exist in Excel; default keep last
    duplicate_policy: str = "last"  # first | last | error

    overwrite_in_augmented: bool = False

    # Optional convenience: if augmented is missing, copy existing participants.tsv from source
    copy_existing_from_source_if_present: bool = False


class ParticipantsTSVFeature:
    """
    Feature: ensure participants.tsv exists in augmented folder root.

    Rule:
      - Augmented folder is authoritative:
          If participants.tsv exists in augmented (and overwrite disabled), do nothing and do NOT check source.
      - If augmented missing:
          Generate from Excel (default), or copy from source if enabled and present.
      - Output includes ONLY subjects present in the source BIDS folder, sorted alphabetically.
      - If a BIDS subject is missing from Excel, it is still included with blanks for age/sex.
    """

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    @staticmethod
    def _participants_paths(source_bids_dir: str, augmented_dir: str) -> tuple[str, str]:
        src = os.path.join(source_bids_dir, "participants.tsv")
        dst = os.path.join(augmented_dir, "participants.tsv")
        return src, dst

    def check_status(self, source_bids_dir: str, augmented_dir: str) -> str:
        _, dst = self._participants_paths(source_bids_dir, augmented_dir)
        dst_exists = os.path.isfile(dst)

        lines = []
        lines.append("[participants.tsv] Status:")
        lines.append(f"  Augmented participants.tsv: {'FOUND' if dst_exists else 'MISSING'}  ({dst})")

        if dst_exists:
            lines.append("  Action: none (augmented is authoritative)")
            return "\n".join(lines)

        # Only if missing in augmented do we *optionally* report source status
        src, _ = self._participants_paths(source_bids_dir, augmented_dir)
        src_exists = os.path.isfile(src)
        lines.append(f"  Source participants.tsv:    {'FOUND' if src_exists else 'MISSING'}  ({src})")
        lines.append("  Action: will generate from Excel (or copy from source if enabled).")
        return "\n".join(lines)

    def apply(self, source_bids_dir: str, augmented_dir: str, settings: ParticipantsFeatureSettings) -> str:
        ensure_dir(augmented_dir)
        src, dst = self._participants_paths(source_bids_dir, augmented_dir)

        if os.path.isfile(dst) and not settings.overwrite_in_augmented:
            self.logger.info("participants.tsv exists in augmented and overwrite is disabled: %s", dst)
            return f"[participants.tsv] Skipped: already exists in augmented (overwrite disabled): {dst}"

        # If augmented missing (or overwrite enabled), optionally copy from source
        if os.path.isfile(src) and settings.copy_existing_from_source_if_present:
            safe_copy_file(src, dst, overwrite=True)
            self.logger.info("Copied participants.tsv from source to augmented: %s -> %s", src, dst)
            return f"[participants.tsv] Copied from source into augmented:\n  {src}\n  -> {dst}"

        # Generate from Excel
        df = read_demographics_excel(
            excel_path=settings.excel_path,
            sheet_name=settings.sheet_name,
            col_participant_id=settings.col_participant_id,
            col_age=settings.col_age,
            col_sex=settings.col_sex,
            col_group=settings.col_group,
            default_group=settings.default_group,
        )

        dup_policy = (settings.duplicate_policy or "last").strip().lower()
        if dup_policy not in ("first", "last", "error"):
            dup_policy = "last"

        dup_mask = df["participant_id"].duplicated(keep=False)
        dup_ids = sorted(df.loc[dup_mask, "participant_id"].unique().tolist())

        if dup_ids:
            self.logger.info("Duplicate participant_id values detected (count=%d). Policy=%s", len(dup_ids), dup_policy)

        if dup_ids and dup_policy == "error":
            raise ValueError(
                "Duplicate participant_id rows found in Excel. "
                f"Set duplicate policy to first/last or fix Excel. Duplicates: {dup_ids[:20]}"
                + (" ..." if len(dup_ids) > 20 else "")
            )

        if dup_ids and dup_policy in ("first", "last"):
            keep = "first" if dup_policy == "first" else "last"
            # Preserve original file order for first/last within each participant_id
            df = df.reset_index(drop=True)
            df = df.drop_duplicates(subset=["participant_id"], keep=keep).copy()

        # Normalize sex to 'm'/'f' where possible
        def norm_sex(s: str) -> str:
            s = (s or "").strip().lower()
            if s in ("m", "male"):
                return "m"
            if s in ("f", "female"):
                return "f"
            return s

        df["sex"] = df["sex"].map(norm_sex)

        # Requirement: only include subjects present in BIDS folder, sorted alphabetically
        bids_subjects = settings.bids_subjects or []
        bids_subjects = sorted(bids_subjects)

        # Build output so ALL BIDS subjects are present (even if missing from Excel)
        base = pd.DataFrame({"participant_id": bids_subjects})
        out = base.merge(df, on="participant_id", how="left")

        # Ensure group is present and defaulted
        if "group" not in out.columns:
            out["group"] = settings.default_group or "patient"
        out["group"] = out["group"].map(lambda x: x if str(x).strip() else (settings.default_group or "patient"))

        # Ensure correct column order
        out = out[["participant_id", "age", "sex", "group"]].copy()
        out = out.sort_values(by=["participant_id"])

        # Stats: missing demographics
        missing_age = int(out["age"].isna().sum())
        missing_sex = int(out["sex"].isna().sum() if out["sex"].dtype != object else (out["sex"].fillna("").astype(str).str.strip() == "").sum())

        out.to_csv(dst, sep="\t", index=False, na_rep="")

        self.logger.info("Generated participants.tsv into augmented: %s (rows=%d)", dst, len(out))
        self.logger.info("Missing demographics: age=%d, sex=%d", missing_age, missing_sex)

        msg = [
            f"[participants.tsv] Generated into augmented:",
            f"  {dst}",
            f"  Rows written: {len(out)}",
        ]
        if dup_ids:
            msg.append(f"  Duplicate subject entries in Excel handled via policy='{dup_policy}' (unique dups={len(dup_ids)}).")
        if missing_age or missing_sex:
            msg.append(f"  Missing demographics among BIDS subjects: age missing={missing_age}, sex missing={missing_sex}.")
        return "\n".join(msg)
