import json
import os
import sys


def app_dir():
    """Folder for files that must persist between runs (config.json,
    storage_state.json). When bundled by PyInstaller this is the folder
    next to the executable, not the temporary extraction folder, so
    saved data survives between launches."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path=None):
    if path is None:
        path = os.path.join(app_dir(), "config.json")

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} not found. Copy config.example.json to config.json and edit it."
        )
    with open(path) as f:
        cfg = json.load(f)

    base_url = cfg.get("base_url", "").rstrip("/")
    if not base_url.startswith("http"):
        raise ValueError("base_url must start with http or https")

    cfg["base_url"] = base_url
    cfg.setdefault("output_dir", os.path.join(app_dir(), "downloads"))
    cfg.setdefault("storage_path", os.path.join(app_dir(), "storage_state.json"))
    return cfg