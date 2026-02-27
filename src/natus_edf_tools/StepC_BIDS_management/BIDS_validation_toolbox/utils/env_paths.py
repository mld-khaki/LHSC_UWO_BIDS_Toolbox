from __future__ import annotations

import os


def _parse_env_file(path: str) -> dict[str, str]:
    """
    Parse a simple .env-like file with KEY=VALUE per line.
    Ignores blank lines and comments starting with # or ;
    """
    out: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for raw in f.readlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#") or line.startswith(";"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = (k or "").strip()
            v = (v or "").strip().strip('"').strip("'")
            if k:
                out[k] = v
    return out


def get_log_root_dir() -> str:
    """
    The user requirement:
      logs stored in a log folder located at $env:LOG_ENV_PATH = "O:\\config\\log_path.env"
    We interpret LOG_ENV_PATH as an env var containing a path to a .env file.
    That .env file should contain LOG_DIR=... (or LOG_ROOT=...).

    Fallback: ./logs (next to current working directory).
    """
    env_path = os.environ.get("LOG_ENV_PATH", "").strip()
    if env_path and os.path.isfile(env_path):
        values = _parse_env_file(env_path)
        for key in ("LOG_DIR", "LOG_ROOT", "LOG_PATH"):
            p = (values.get(key, "") or "").strip()
            if p:
                return os.path.abspath(p)

    # fallback
    return os.path.abspath(os.path.join(os.getcwd(), "logs"))
