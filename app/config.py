from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    # Allow env overrides
    if os.environ.get("WINDOW_DAYS"):
        cfg["providers"]["arxiv"]["window_days"] = int(os.environ["WINDOW_DAYS"])
    if os.environ.get("TOP_K"):
        cfg["ranking"]["top_k"] = int(os.environ["TOP_K"])
    if os.environ.get("KEYWORDS"):
        cfg["keywords"] = [k.strip() for k in os.environ["KEYWORDS"].split(",")]

    return cfg
