import os
import sys

import webview


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

# NOTES ---------------
#   1. getattr(object, attribute, default) -> gets object.attribute (if existing), else object.default
#   2. os.path.abspath(__file__) -> gets abs path of file
#   3. os.path.dirname(__file__) -> gets path to directory in which file sits
#   4. When Pyinstaller creates a .exe, it unpacks bundled files into temporary folder 
#           - whose path is stored in sys._MEIPASS
#   5. os.path.join(base, rel) -> joins base path with relative path to file (given)
#   6. base becomes path to temporary extracted folder or folder where app file lives
#           - we return complete path to file

# SUMMARY: Returns abs path to .exe file

sys.path.insert(0, resource_path("src"))
from api import Api  # noqa: E402

# NOTES ---------------
#   1. sys.path -> list of directories that Python searches when you do an import
#   2. .insert(0, resource_path("src")) -> inserts path to src/ at index 0
#   3. src contains api.py so now Python can find api and import Api from it

# SUMMARY: Adds src/ to sys so Python can find api and import Api from it

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

# NOTES ---------------
#   1. webview.create_window -> accepts [title, url of file to load, Python object whose methods you want to expose to JS]
#   2. The latter is a cool feature as normally, JS cannot directly call Python functions

# SUMMARY: Runs main function


if __name__ == "__main__":
    main()