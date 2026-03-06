from __future__ import annotations

import configparser
import os
from dataclasses import dataclass

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.ini")
DEFAULT_CONFIG_PATH = os.path.abspath(DEFAULT_CONFIG_PATH)


@dataclass
class GeneralConfig:
    source_bids_dir: str = ""
    augmented_dir: str = ""
    # Default OFF now: if augmented is missing, generate from Excel (unless user enables copying)
    copy_existing_files: bool = False


@dataclass
class ParticipantsConfig:
    excel_path: str = ""
    sheet_name: str = ""

    # Your Excel columns:
    col_participant_id: str = "subject"
    col_age: str = "age"
    col_sex: str = "sex"

    # Not present in your Excel, so blank is allowed
    col_group: str = ""

    default_group: str = "patient"

    # Requirement: only include subjects present in BIDS folder (kept as a setting but enforced in GUI)
    include_only_bids_subjects: bool = True

    # Duplicates exist in Excel (e.g., sub-056). Default to keeping LAST occurrence.
    duplicate_policy: str = "last"  # first | last | error

    overwrite_in_augmented: bool = False


@dataclass
class MergeConfig:
    path_a: str = ""
    path_b: str = ""
    subject_a: str = ""
    subject_b: str = ""
    destination: str = "A"  # A or B

    # Behavior defaults for the merge UI
    overwrite_on_duplicates: bool = False
    default_select_duplicates: bool = False
    default_select_empty: bool = False


@dataclass
class AppConfig:
    general: GeneralConfig
    participants: ParticipantsConfig
    merge: MergeConfig
    config_path: str = DEFAULT_CONFIG_PATH

    @staticmethod
    def _bool_get(cfg: configparser.ConfigParser, section: str, key: str, default: bool) -> bool:
        try:
            return cfg.getboolean(section, key)
        except Exception:
            return default

    @staticmethod
    def _str_get(cfg: configparser.ConfigParser, section: str, key: str, default: str) -> str:
        try:
            v = cfg.get(section, key, fallback=default)
            return (v or "").strip()
        except Exception:
            return default

    @classmethod
    def load_or_create(cls, path: str | None = None) -> "AppConfig":
        config_path = os.path.abspath(path or DEFAULT_CONFIG_PATH)
        cfg = configparser.ConfigParser()

        created = False
        if os.path.isfile(config_path):
            cfg.read(config_path, encoding="utf-8")
        else:
            created = True

        if "general" not in cfg:
            cfg["general"] = {}
        if "participants" not in cfg:
            cfg["participants"] = {}
        if "merge" not in cfg:
            cfg["merge"] = {}

        general = GeneralConfig(
            source_bids_dir=cls._str_get(cfg, "general", "source_bids_dir", ""),
            augmented_dir=cls._str_get(cfg, "general", "augmented_dir", ""),
            copy_existing_files=cls._bool_get(cfg, "general", "copy_existing_files", False),
        )

        participants = ParticipantsConfig(
            excel_path=cls._str_get(cfg, "participants", "excel_path", ""),
            sheet_name=cls._str_get(cfg, "participants", "sheet_name", ""),
            col_participant_id=cls._str_get(cfg, "participants", "col_participant_id", "subject"),
            col_age=cls._str_get(cfg, "participants", "col_age", "age"),
            col_sex=cls._str_get(cfg, "participants", "col_sex", "sex"),
            col_group=cls._str_get(cfg, "participants", "col_group", ""),
            default_group=cls._str_get(cfg, "participants", "default_group", "patient"),
            include_only_bids_subjects=cls._bool_get(cfg, "participants", "include_only_bids_subjects", True),
            duplicate_policy=cls._str_get(cfg, "participants", "duplicate_policy", "last"),
            overwrite_in_augmented=cls._bool_get(cfg, "participants", "overwrite_in_augmented", False),
        )

        merge = MergeConfig(
            path_a=cls._str_get(cfg, "merge", "path_a", ""),
            path_b=cls._str_get(cfg, "merge", "path_b", ""),
            subject_a=cls._str_get(cfg, "merge", "subject_a", ""),
            subject_b=cls._str_get(cfg, "merge", "subject_b", ""),
            destination=(cls._str_get(cfg, "merge", "destination", "A") or "A").strip().upper()[:1] or "A",
            overwrite_on_duplicates=cls._bool_get(cfg, "merge", "overwrite_on_duplicates", False),
            default_select_duplicates=cls._bool_get(cfg, "merge", "default_select_duplicates", False),
            default_select_empty=cls._bool_get(cfg, "merge", "default_select_empty", False),
        )

        if merge.destination not in ("A", "B"):
            merge.destination = "A"

        app_cfg = cls(general=general, participants=participants, merge=merge, config_path=config_path)

        # Always write a complete config.ini (create if missing, fill defaults if incomplete)
        app_cfg.save()

        if created:
            pass

        return app_cfg

    def save(self) -> None:
        cfg = configparser.ConfigParser()

        cfg["general"] = {
            "source_bids_dir": self.general.source_bids_dir or "",
            "augmented_dir": self.general.augmented_dir or "",
            "copy_existing_files": "true" if self.general.copy_existing_files else "false",
        }

        cfg["participants"] = {
            "excel_path": self.participants.excel_path or "",
            "sheet_name": self.participants.sheet_name or "",
            "col_participant_id": (self.participants.col_participant_id or "subject").strip(),
            "col_age": (self.participants.col_age or "age").strip(),
            "col_sex": (self.participants.col_sex or "sex").strip(),
            # IMPORTANT: allow blank group column (do NOT coerce to "group")
            "col_group": (self.participants.col_group or "").strip(),
            "default_group": (self.participants.default_group or "patient").strip(),
            "include_only_bids_subjects": "true" if self.participants.include_only_bids_subjects else "false",
            "duplicate_policy": (self.participants.duplicate_policy or "last").strip(),
            "overwrite_in_augmented": "true" if self.participants.overwrite_in_augmented else "false",
        }

        cfg["merge"] = {
            "path_a": (self.merge.path_a or "").strip(),
            "path_b": (self.merge.path_b or "").strip(),
            "subject_a": (self.merge.subject_a or "").strip(),
            "subject_b": (self.merge.subject_b or "").strip(),
            "destination": (self.merge.destination or "A").strip().upper()[:1] or "A",
            "overwrite_on_duplicates": "true" if self.merge.overwrite_on_duplicates else "false",
            "default_select_duplicates": "true" if self.merge.default_select_duplicates else "false",
            "default_select_empty": "true" if self.merge.default_select_empty else "false",
        }

        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            cfg.write(f)
