import os
import sys

import webview


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


sys.path.insert(0, resource_path("src"))
from api import Api  # noqa: E402


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