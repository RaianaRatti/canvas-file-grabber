import json
import os
import sys


def app_dir():
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        if exe_dir.endswith(".app/Contents/MacOS"):
            os.path.dirname(os.path.dirname(exe_dir))
        return exe_dir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# NOTES ---------------
#   1. getattr(sys, "frozen", False) -> returns attribute sys.frozen or False (if DNE)
#           - "if" -> essentially makes this a check for whether sys has attribute "frozen"
#           - if "if" == False -> return project root (structure: canvas-file-grabber/src/__file__)
#   2. exe_dir -> becomes directory of .exe file
#   3. On macOS, .exe files live in CanvasFileGrabber.app/Contents/MacOS -> we check if that is true
#           - If it is -> return folder containing .app (so files end up next to .app)
#           - If it is not (using some other OS) -> return folder containg .exe


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