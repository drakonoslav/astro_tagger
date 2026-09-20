"""Every filesystem location the tool uses, in one place.

Home directory, in order of precedence:
  1. $ASTRO_TAGGER_HOME
  2. the repository root, when running from a source checkout (pyproject.toml present)
  3. ~/.astro_tagger

Inside the home directory:
  config/config.json   your site (not committed)
  config/agents.json   agent registry
  kernels/             *.bsp ephemeris files + index.json
  logs/                states-YYYY-MM-DD.jsonl
"""
import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
_CHECKOUT_ROOT = PACKAGE_DIR.parent


def home() -> Path:
    env = os.environ.get("ASTRO_TAGGER_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if (_CHECKOUT_ROOT / "pyproject.toml").is_file():
        return _CHECKOUT_ROOT
    return Path.home() / ".astro_tagger"


def config_dir() -> Path:
    return home() / "config"


def config_path() -> Path:
    return config_dir() / "config.json"


def config_example_path() -> Path:
    return config_dir() / "config.example.json"


def agents_path() -> Path:
    return config_dir() / "agents.json"


def kernels_dir() -> Path:
    return home() / "kernels"


def kernel_index_path() -> Path:
    return kernels_dir() / "index.json"


def logs_dir() -> Path:
    return home() / "logs"
