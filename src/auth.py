import os
import subprocess
import time

from config import app_dir


def _browsers_dir():
    """Folder where downloaded browsers live. Must persist between runs,
    so it goes next to config.json rather than inside the bundle."""
    path = os.path.join(app_dir(), "browsers")
    os.makedirs(path, exist_ok=True)
    return path


def _set_browsers_path():
    """PyInstaller's Playwright hook sets PLAYWRIGHT_BROWSERS_PATH to "0",
    which points at a temp folder inside the bundle that is wiped on every
    launch. Override it before the driver subprocess starts."""
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browsers_dir()


def _download_chromium():
    """One-time Chromium download into the persistent browsers folder."""
    from playwright._impl._driver import compute_driver_executable, get_driver_env

    node, cli = compute_driver_executable()
    env = get_driver_env()
    env["PLAYWRIGHT_BROWSERS_PATH"] = _browsers_dir()
    subprocess.run([str(node), str(cli), "install", "chromium"], env=env, check=True)


def _launch(p):
    """Prefer a browser already installed on the machine. Fall back to a
    downloaded Chromium, fetching it once if it is not there yet."""
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


def _wait_for_login(page, base_url, timeout_s=600):
    """Poll the Canvas API through the browser's own cookies until the
    session works. Replaces input(), which has no stdin in a windowed app."""
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


def login_and_save(base_url, storage_path):
    _set_browsers_path()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _launch(p)
        context = browser.new_context()
        page = context.new_page()
        page.goto(base_url)

        ok = _wait_for_login(page, base_url)
        if ok:
            context.storage_state(path=storage_path)

        browser.close()
        return ok