# -*- coding: utf-8 -*-

import os

def load_env_file(path):
    """
    Load a simple .env-style file into a dict.
    Supports lines like KEY=VALUE, ignores blank lines and comments (# ...).
    Does not modify os.environ unless you choose to.
    """
    env = {}
    if not os.path.exists(path):
        return env

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")  # remove optional quotes
            env[key] = value

    return env