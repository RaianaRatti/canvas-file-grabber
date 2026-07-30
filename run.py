import os
import sys

import webview

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from api import Api  # noqa: E402


def main():
    api = Api()
    web_dir = os.path.join(os.path.dirname(__file__), "web")
    webview.create_window(
        "Canvas File Grabber",
        os.path.join(web_dir, "index.html"),
        js_api=api,
        width=920,
        height=700,
        min_size=(760, 580),
    )
    webview.start()


if __name__ == "__main__":
    main()