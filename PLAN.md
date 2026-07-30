# PLAN.md

## Summary

**canvas-file-grabber** is a lightweight command line tool that logs into any Canvas instance as the user, scans the user's active courses, and downloads every file matching a set of file extensions into a folder the user chooses.

**Goal:** Let a user type a list of file endings (for example `pdf, pptx, docx`), point at an output folder, and have the tool pull all matching course files from their own Canvas account. It must work on school hosted Canvas instances, including ones behind SSO and multi factor authentication (OTP).

**Core design decision:** The user logs in through a real browser window that the tool controls. The user types their own email, password, and OTP into the genuine Canvas login page. The tool never sees or stores the raw password. After a successful login, the tool saves the browser session (cookies) to a local file and reuses it for all future runs. All file listing and downloading then happens over plain HTTP using those cookies, so the browser only appears once during initial login.

This keeps the tool lightweight, avoids credential handling, and works across native Canvas login and third party SSO without special cases.

---

## File structure

```
canvas-file-grabber/
├── README.md
├── PLAN.md
├── requirements.txt
├── config.example.json
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── main.py          # CLI entry point and top level flow
│   ├── config.py        # load and validate config.json
│   ├── auth.py          # Playwright login and session persistence
│   ├── canvas.py        # Canvas API client (courses, files, pagination)
│   └── downloader.py    # extension filtering and file writing
└── downloads/           # default output folder (gitignored)
```

Files that hold sensitive or generated data (`config.json`, `storage_state.json`, `downloads/`) are never committed.

---

## Dependencies

`requirements.txt`:

```
playwright==1.44.0
requests==2.32.3
```

After install, Playwright needs its browser binary:

```
pip install -r requirements.txt
playwright install chromium
```

---

## Step 1: Config

The user sets four things: their school Canvas base URL, the output folder, where to store the session file, and a default extension list. Everything can also be overridden from the command line.

`config.example.json`:

```json
{
  "base_url": "https://canvas.youruniversity.edu",
  "output_dir": "downloads",
  "storage_path": "storage_state.json",
  "extensions": ["pdf", "pptx", "docx"]
}
```

`src/config.py`:

```python
import json
import os


def load_config(path="config.json"):
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
    cfg.setdefault("output_dir", "downloads")
    cfg.setdefault("storage_path", "storage_state.json")
    cfg.setdefault("extensions", [])
    return cfg
```

---

## Step 2: Login and session capture

The tool opens a real Chromium window at the user's Canvas URL. The user completes the entire login themselves, including SSO redirects and OTP. When they confirm they are on their dashboard, the tool saves the session state to disk.

Using a confirmation prompt instead of trying to auto detect a successful login is deliberate. Login flows differ wildly between schools, so waiting for the user to press Enter is the one signal that works everywhere.

`src/auth.py`:

```python
from playwright.sync_api import sync_playwright


def login_and_save(base_url, storage_path):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(base_url)

        print("\nA browser window has opened.")
        print("Log in to Canvas there. Complete any SSO and OTP steps.")
        input("Once you can see your Canvas dashboard, press Enter here...")

        context.storage_state(path=storage_path)
        browser.close()
        print(f"Session saved to {storage_path}")
```

---

## Step 3: Build an HTTP session from the saved cookies

The saved `storage_state.json` contains the session cookies. Loading them into a `requests` session lets the tool call the Canvas API without opening a browser again.

`src/canvas.py`:

```python
import json
import requests


def session_from_storage(storage_path):
    with open(storage_path) as f:
        state = json.load(f)

    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    for c in state.get("cookies", []):
        s.cookies.set(
            c["name"], c["value"],
            domain=c["domain"], path=c.get("path", "/"),
        )
    return s


def session_is_valid(session, base_url):
    try:
        r = session.get(f"{base_url}/api/v1/users/self", timeout=15)
        return r.status_code == 200
    except requests.RequestException:
        return False
```

---

## Step 4: List courses and files

Canvas returns large lists across multiple pages using a `Link` header. The helper below follows the `rel="next"` link until there are no more pages.

Add to `src/canvas.py`:

```python
def _get_paginated(session, url, params=None):
    results = []
    while url:
        r = session.get(url, params=params, timeout=30)
        params = None  # next page links already carry their own params
        r.raise_for_status()
        results.extend(r.json())

        url = None
        for part in r.headers.get("Link", "").split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
    return results


def list_courses(session, base_url):
    url = f"{base_url}/api/v1/courses"
    return _get_paginated(
        session, url,
        params={"enrollment_state": "active", "per_page": 100},
    )


def list_course_files(session, base_url, course_id):
    url = f"{base_url}/api/v1/courses/{course_id}/files"
    try:
        return _get_paginated(session, url, params={"per_page": 100})
    except requests.HTTPError:
        # Some courses disable the files API. Skip those instead of crashing.
        return []
```

Each file object includes fields like `display_name`, `filename`, and `url`. The `url` field is a direct, time limited download link.

---

## Step 5: Filter by extension and download

Filenames are sanitized and grouped by course. Duplicate names get a numeric suffix so nothing is overwritten.

`src/downloader.py`:

```python
import os
import re


def matches_extension(filename, extensions):
    lower = filename.lower()
    return any(lower.endswith("." + e.lower().lstrip(".")) for e in extensions)


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


def unique_path(directory, filename):
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base} ({i}){ext}")
        i += 1
    return candidate


def download_file(session, file_obj, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    name = safe_name(file_obj.get("display_name") or file_obj.get("filename"))
    path = unique_path(dest_dir, name)

    with session.get(file_obj["url"], stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
    return path
```

---

## Step 6: Tie it together in the CLI

`src/main.py`:

```python
import argparse
import os

from config import load_config
from auth import login_and_save
from canvas import (
    session_from_storage,
    session_is_valid,
    list_courses,
    list_course_files,
)
from downloader import matches_extension, safe_name, download_file


def main():
    parser = argparse.ArgumentParser(description="Download Canvas files by extension.")
    parser.add_argument("--ext", help="Comma separated extensions, e.g. pdf,pptx")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--relogin", action="store_true", help="Force a fresh login")
    args = parser.parse_args()

    cfg = load_config(args.config)
    base_url = cfg["base_url"]
    storage_path = cfg["storage_path"]

    # Extensions: command line wins, otherwise ask, otherwise config default.
    if args.ext:
        extensions = [e.strip() for e in args.ext.split(",") if e.strip()]
    elif cfg["extensions"]:
        extensions = cfg["extensions"]
    else:
        raw = input("File endings to download (comma separated): ")
        extensions = [e.strip() for e in raw.split(",") if e.strip()]

    if not extensions:
        print("No extensions given. Nothing to do.")
        return

    # Log in if there is no valid session.
    need_login = args.relogin or not os.path.exists(storage_path)
    if not need_login:
        session = session_from_storage(storage_path)
        if not session_is_valid(session, base_url):
            print("Saved session expired. Logging in again.")
            need_login = True

    if need_login:
        login_and_save(base_url, storage_path)
        session = session_from_storage(storage_path)
        if not session_is_valid(session, base_url):
            print("Login did not produce a valid session. Exiting.")
            return

    print("Fetching courses...")
    courses = list_courses(session, base_url)
    print(f"Found {len(courses)} active courses.")

    total = 0
    for course in courses:
        course_name = safe_name(course.get("name") or f"course_{course['id']}")
        files = list_course_files(session, base_url, course["id"])
        wanted = [f for f in files
                  if matches_extension(f.get("display_name")
                                       or f.get("filename", ""), extensions)]
        if not wanted:
            continue

        dest = os.path.join(cfg["output_dir"], course_name)
        print(f"{course_name}: {len(wanted)} matching files")
        for f in wanted:
            try:
                path = download_file(session, f, dest)
                total += 1
                print(f"  saved {os.path.basename(path)}")
            except Exception as e:
                print(f"  failed {f.get('display_name')}: {e}")

    print(f"\nDone. Downloaded {total} files into {cfg['output_dir']}/")


if __name__ == "__main__":
    main()
```

Run it with:

```
python src/main.py --ext pdf,pptx
```

---

## Step 7: .gitignore

`.gitignore`:

```
config.json
storage_state.json
downloads/
__pycache__/
*.pyc
.venv/
venv/
```

---

## Limitations

**Terms of service.** Automating login to a school Canvas instance may conflict with the school's or Canvas's acceptable use policies, even when you are only accessing your own account and files. Check your institution's rules before using this. This is the main non technical risk.

**Login is not fully headless.** The tool needs a visible browser for the first login so the user can complete SSO and OTP. It cannot silently log in with just a stored email and password, and that is intentional: programmatic password and OTP handling breaks on SSO schools and is fragile. The tradeoff is one manual login step, after which the saved session is reused.

**Session expiry.** Canvas sessions expire. When that happens the tool detects the invalid session and prompts for a fresh login. There is no way around periodic re logins.

**The stored session file is sensitive.** `storage_state.json` holds live session cookies. Anyone who copies that file could act as the user until the session expires. It is gitignored, but for a hardened version you would store it in the OS keychain instead of a plain file.

**Course files API can be restricted.** Some courses disable the files endpoint. Those courses are skipped rather than erroring. A future version could fall back to scanning modules and pages for file links.

**Download URLs are time limited.** The `url` field from Canvas points at a signed link that expires quickly. The tool downloads immediately after listing, so this is only an issue for very large batches, where you may hit rate limits or expired links and need to rerun.

**Rate limits.** Canvas throttles heavy API use. For accounts with many large courses, add short delays between requests if you start seeing HTTP 403 or 429 responses.