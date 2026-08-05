import os
import subprocess
import time

from config import app_dir

# OVERALL NOTES
#   - Playwright: Python library that can control a real web browser
#   - Chromium: Open-source web browser that Google Chrome is built on
#   - When Playwright launches Chromium, it is launching a real browser engine 
#   - Normally, Playwright downloads Chromium to a location manages. However, when app is packaged with PyInstaller, PyInstaller Playwright hook may set PLAYWRIGHT_BROWSERS_PATH=0 which tells Playwright to use a temporary folder inside bundled app
#   - Issue: Launch app -> Temp folder created -> Chromium downloaded -> Close app -> Temp folder deleted
#           - Chromium browser will have to be downloaded again
#           - This issue is resolved by _set_browsers_path()


def _browsers_dir():
    path = os.path.join(app_dir(), "browsers")
    os.makedirs(path, exist_ok=True)
    return path

# NOTES ---------------
# SUMMARY: Folder where downloaded browsers live, must persist between runs so it goes next to config.json rather than inside the bundle


def _set_browsers_path():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browsers_dir()

# NOTES ---------------
# SUMMARY: PyInstaller's Playwright hook sets PLAYWRIGHT_BROWSERS_PATH to "0" which points to a temp folder inside the bundle that is wiped on every launch. Override it


def _download_chromium():
    from playwright._impl._driver import compute_driver_executable, get_driver_env

    node, cli = compute_driver_executable()
    env = get_driver_env()
    env["PLAYWRIGHT_BROWSERS_PATH"] = _browsers_dir()
    subprocess.run([str(node), str(cli), "install", "chromium"], env=env, check=True)

# NOTES ---------------
#   1. compute_driver_executable -> tells Playwright where its Node.js executable + CLI program is
#   2. get_driver_env -> tells Playwright what env variables it normally uses
#   3. node, cli = compute_driver_executable -> finds the Playwright executables
#           - node = /.../node
#           - cli = /.../cli.js
#   4. env = get_driver_env -> creates env variables Playwright expects
#   5. env["PLAYWRIGHT_BROWSERS_PATH"] = _browsers_dir() -> overwrites browsers/ path (so it is not in temp folder)
#   6. subprocess.run(...) -> launches a separate process, downloads Chromium and installs it in folder specified by PLAYWRIGHT_BROWSERS_PATH
#           - equivalent to running playwright install chromium OR (more specifically) node cli.js install chromium

# SUMMARY: Downloads Chromium browser that Playwright needs, and installs it into your persistent browsers/ folder

def _launch(p):
    for channel in ("chrome", "msedge"):
        try:
            return p.chromium.launch(headless=False, channel=channel)
        except Exception:
            pass

    try:
        return p.chromium.launch(headless=False)
    except Exception:
        _download_chromium()
        return p.chromium.launch(headless=False)

# NOTES ---------------
#   1. Loop over channels "chrome" and "msedge" and launch the installed Chrome (or Edge) browser
#   2. If success, return said channel immediately
#   3. If none succeed, launch Playwright's own Chromium browser
#           - If downloaded, return it
#           - If not downloaded (and error thrown), download it and then return it

# SUMMARY: Prefer browser already installed on machine and fallback to downloaded Chromium (download if not present on machine)


def _wait_for_login(page, base_url, timeout_s=600):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = page.request.get(f"{base_url}/api/v1/users/self")
            if r.status == 200:
                return True
        except Exception:
            pass
        page.wait_for_timeout(2000)
    return False

# NOTES ---------------
#   1. Send requests (r) to page and exit if successful
#   2. page.wait_for_timeout(2000) -> wait 2s between each reqeust to avoid sending continuous requests
#   3. Return false if r is never successful until deadline hit (600 seconds)

# SUMMARY: Poll Canvas API through browser's own cookies until session works (or deadline of 600 seconds hit)

def login_and_save(base_url, storage_path):
    _set_browsers_path()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(base_url)

            ok = _wait_for_login(page, base_url)
            if ok:
                os.makedirs(os.path.dirname(storage_path), exist_ok=True)
                context.storage_state(path=storage_path)
            return ok
        finally:
            browser.close()

# NOTES ---------------
#   1. with sync_playwright as p -> starts Playwright engine
#   2. browser = _launch(p) -> Laucnhes Chrome, Edge, or Chromium
#   3. context = browser.new_context(), page = context.new_page() -> uses fresh browser profile (cookies, localStorage) + browser tab
#   4. page.goto(base_url) -> Navigates to login page
#   5. ok = _wait_for_login(page, base_url) -> Boolean based on whether login successful
#   6. os.makedirs(os.path.dirname(storage_path), exist_ok=True) -> Makes folder for storage_path exists (if existing, nothing happens)
#   7. context.storage_state(path=storage_path) -> Saves browser data (cookies and localStorage) to storage_path (allow caching)
#   8. return ok -> return Boolean that shows whether login successful or not
#   9. finally: browser.close() -> Always close browser regardless of "ok" (login successful or not)