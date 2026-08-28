import os
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
MODEL = os.getenv("EVAL_MODEL", "gemini-3.6-flash")


def load_yaml(name):
    import yaml

    with open(CONFIG_DIR / name) as f:
        return yaml.safe_load(f)
