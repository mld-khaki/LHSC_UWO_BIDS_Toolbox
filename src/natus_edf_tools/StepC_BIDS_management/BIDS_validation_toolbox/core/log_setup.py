from __future__ import annotations

import logging
import os
from datetime import datetime

from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.core.config import AppConfig
from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.utils.env_paths import get_log_root_dir
from natus_edf_tools.StepC_BIDS_management.BIDS_validation_toolbox.utils.file_ops import ensure_dir


def get_logger(app_config: AppConfig) -> logging.Logger:
    logger = logging.getLogger("bids_augmentor")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(ch)

    # File handler
    log_root = get_log_root_dir()
    tool_dir = os.path.join(log_root, "bids_augmentor")
    ensure_dir(tool_dir)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(tool_dir, f"bids_augmentor_{ts}.log")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
    logger.addHandler(fh)

    logger.info("Logging to %s", log_file)
    return logger
