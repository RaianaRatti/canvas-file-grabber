import os
import sys

import webview

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from api import Api  # noqa: E402

def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

def main():
    api = Api()
    webview.create_window(
        "Canvas File Grabber",
        resource_path("web/index.html"),
        js_api=api,
        width=920,
        height=700,
        min_size=(760, 580),
    )
    webview.start()


if __name__ == "__main__":
    main()