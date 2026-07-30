# PLAN.md

## Summary

**canvas-file-grabber** is a small desktop app that logs into any Canvas instance as the user, shows all of their courses (current and past) in a window, lets them browse into course folders like a file explorer, pick whole courses, specific folders, or individual files, and downloads the matching files into a folder they choose.

**Goal:** Open a native window that lists your Canvas courses. Click the dropdown caret on a course to open a folder browser. Folders appear as folder icons you can click into, nested folders open the same way, and files appear as file icons with their names. Tick a folder to grab everything in it, click a file to grab just that file, or tick the course itself to grab everything. Type the file endings to keep (for example `pdf, pptx, docx`), pick an output folder, and download. It works on school hosted Canvas instances, including ones behind SSO and multi factor authentication (OTP), and it includes past courses.

**How auth works:** The user logs in through a real browser window that the tool controls. They type their own email, password, and OTP into the genuine Canvas login page. The app never sees or stores the raw password. After a successful login the session cookies are saved locally and reused, so the browser only appears once. All course listing and downloading then happens over plain HTTP using those cookies.

**How the UI works:** A Python backend exposes a small set of methods. A native window built with **pywebview** loads a local HTML/CSS/JS frontend. The frontend calls the backend methods directly through `window.pywebview.api`, so there is no separate web server, no ports, and no CORS setup. The folder tree is built on the frontend from a single flat list of folders, so drilling into nested folders is instant.

---

## Repo structure

```
canvas-file-grabber/
├── README.md
├── PLAN.md
├── requirements.txt
├── config.example.json
├── .gitignore
├── run.py                # entry point: opens the window and wires up the backend
├── src/
│   ├── __init__.py
│   ├── config.py         # load and validate config.json
│   ├── auth.py           # Playwright login and session persistence
│   ├── canvas.py         # Canvas API client (courses incl. past, folders, files)
│   ├── downloader.py     # extension filtering and file writing
│   └── api.py            # the Api class the frontend calls into
├── web/
│   ├── index.html        # frontend markup
│   ├── styles.css        # frontend styling
│   └── app.js            # frontend logic
└── downloads/            # default output folder (gitignored)
```

Files that hold sensitive or generated data (`config.json`, `storage_state.json`, `downloads/`) are never committed.

---

## Dependencies

`requirements.txt`:

```
playwright==1.44.0
requests==2.32.3
pywebview==5.1
```

Install and set up the browser Playwright uses for login:

```
pip install -r requirements.txt
playwright install chromium
```

On Linux, pywebview needs a system webview backend. Install GTK or Qt bindings, for example:

```
sudo apt install python3-gi gir1.2-webkit2-4.1
```

macOS and Windows use their built in webview and need nothing extra.

---

## Backend

### Step 1: Config

`config.example.json`:

```json
{
  "base_url": "https://canvas.youruniversity.edu",
  "output_dir": "downloads",
  "storage_path": "storage_state.json"
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
    return cfg
```

### Step 2: Login and session capture

The tool opens a real Chromium window at the user's Canvas URL. The user completes the whole login themselves, including SSO and OTP. When they confirm they are on their dashboard, the session state is saved. Waiting for the user to confirm instead of trying to auto detect a login is deliberate, because login flows differ too much between schools for any single detector to work everywhere.

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
```

### Step 3: Canvas API client

This module turns the saved cookies into a normal HTTP session and reads courses, folders, and files. Canvas returns long lists across pages using a `Link` header, so pagination follows the `rel="next"` link until it runs out.

**Past courses** are handled by asking Canvas twice, once for active enrollments and once for completed ones, then merging the two lists. Active is processed last so a course you are still in is never mislabeled as past.

The folders endpoint returns every folder in the course as a flat list, each with a `parent_folder_id`. That single list is enough for the frontend to build the whole folder tree, so nested folders need no extra requests. `get_file` re-fetches a single file at download time to get a fresh, non expired download URL.

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
    """Active and past courses, merged and deduped by id."""
    seen = {}
    for state in ("completed", "active"):
        url = f"{base_url}/api/v1/courses"
        params = {"enrollment_state": state, "per_page": 100, "include[]": "term"}
        try:
            page = _get_paginated(session, url, params=params)
        except requests.HTTPError:
            page = []
        for c in page:
            cid = c.get("id")
            if cid is None:
                continue
            c["is_past"] = (state == "completed")
            seen[cid] = c  # active is processed last and wins
    return list(seen.values())


def list_folders(session, base_url, course_id):
    """Flat list of every folder in the course, with parent_folder_id."""
    url = f"{base_url}/api/v1/courses/{course_id}/folders"
    try:
        return _get_paginated(session, url, params={"per_page": 100})
    except requests.HTTPError:
        return []


def list_folder_files(session, base_url, folder_id):
    url = f"{base_url}/api/v1/folders/{folder_id}/files"
    try:
        return _get_paginated(session, url, params={"per_page": 100})
    except requests.HTTPError:
        return []


def list_course_files(session, base_url, course_id):
    url = f"{base_url}/api/v1/courses/{course_id}/files"
    try:
        return _get_paginated(session, url, params={"per_page": 100})
    except requests.HTTPError:
        return []


def get_file(session, base_url, file_id):
    r = session.get(f"{base_url}/api/v1/files/{file_id}", timeout=30)
    r.raise_for_status()
    return r.json()
```

### Step 4: Downloader

`src/downloader.py`:

```python
import os
import re


def matches_extension(filename, extensions):
    if not extensions:
        return True
    lower = filename.lower()
    return any(lower.endswith("." + e.lower().lstrip(".")) for e in extensions)


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name or "").strip() or "untitled"


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

### Step 5: The Api bridge

This is the object the frontend talks to. Every public method becomes callable from JavaScript as `window.pywebview.api.method_name(...)` and returns a promise.

`get_folders` returns the flat folder list with `parent_id` so the frontend can build the tree. `get_files` returns the files inside one folder for display. A selection can mix three things per course: the whole course, specific folders, and specific files. At download time the backend fetches fresh file lists and fresh single file URLs, then dedupes by file id so nothing downloads twice.

`src/api.py`:

```python
import os
import threading

import webview

from config import load_config
from auth import login_and_save
import canvas
from downloader import matches_extension, safe_name, download_file


class Api:
    def __init__(self, config_path="config.json"):
        self.cfg = load_config(config_path)
        self.session = None
        self.progress = {
            "running": False, "done": 0, "total": 0,
            "current": "", "finished": False,
        }

    def status(self):
        path = self.cfg["storage_path"]
        if os.path.exists(path):
            s = canvas.session_from_storage(path)
            if canvas.session_is_valid(s, self.cfg["base_url"]):
                self.session = s
                return {"logged_in": True, "output_dir": self.cfg["output_dir"]}
        return {"logged_in": False, "output_dir": self.cfg["output_dir"]}

    def login(self):
        login_and_save(self.cfg["base_url"], self.cfg["storage_path"])
        s = canvas.session_from_storage(self.cfg["storage_path"])
        ok = canvas.session_is_valid(s, self.cfg["base_url"])
        if ok:
            self.session = s
        return {"logged_in": ok}

    def get_courses(self):
        courses = canvas.list_courses(self.session, self.cfg["base_url"])
        out = []
        for c in courses:
            term = (c.get("term") or {}).get("name", "")
            out.append({
                "id": c["id"],
                "name": c.get("name") or f"Course {c['id']}",
                "term": term,
                "is_past": c.get("is_past", False),
            })
        return out

    def get_folders(self, course_id):
        folders = canvas.list_folders(self.session, self.cfg["base_url"], course_id)
        return [{
            "id": f["id"],
            "name": f.get("name"),
            "parent_id": f.get("parent_folder_id"),
            "files_count": f.get("files_count", 0),
            "folders_count": f.get("folders_count", 0),
        } for f in folders]

    def get_files(self, folder_id):
        files = canvas.list_folder_files(self.session, self.cfg["base_url"], folder_id)
        return [{
            "id": f["id"],
            "name": f.get("display_name") or f.get("filename"),
            "size": f.get("size", 0),
        } for f in files]

    def choose_output_dir(self):
        window = webview.windows[0]
        result = window.create_file_dialog(webview.FOLDER_DIALOG)
        if result:
            self.cfg["output_dir"] = result[0]
        return {"path": self.cfg["output_dir"]}

    def start_download(self, selections, extensions, output_dir):
        if self.progress["running"]:
            return {"started": False}
        t = threading.Thread(
            target=self._run_download,
            args=(selections, extensions, output_dir),
            daemon=True,
        )
        t.start()
        return {"started": True}

    def get_progress(self):
        return self.progress

    def _run_download(self, selections, extensions, output_dir):
        base_url = self.cfg["base_url"]
        exts = [e.strip() for e in extensions if e.strip()]

        jobs = []          # (course_name, file_obj)
        seen = set()       # file ids already queued

        def add(course_name, f):
            fid = f.get("id")
            if fid in seen:
                return
            seen.add(fid)
            name = f.get("display_name") or f.get("filename", "")
            if matches_extension(name, exts):
                jobs.append((course_name, f))

        for sel in selections:
            course_id = sel["course_id"]
            course_name = safe_name(sel.get("course_name") or f"course_{course_id}")

            if sel.get("whole"):
                for f in canvas.list_course_files(self.session, base_url, course_id):
                    add(course_name, f)

            for fid in sel.get("folder_ids", []):
                for f in canvas.list_folder_files(self.session, base_url, fid):
                    add(course_name, f)

            for file_id in sel.get("file_ids", []):
                try:
                    add(course_name, canvas.get_file(self.session, base_url, file_id))
                except Exception:
                    pass

        self.progress = {
            "running": True, "done": 0, "total": len(jobs),
            "current": "", "finished": False,
        }

        for course_name, f in jobs:
            self.progress["current"] = f.get("display_name") or f.get("filename", "")
            dest = os.path.join(output_dir, course_name)
            try:
                download_file(self.session, f, dest)
            except Exception:
                pass
            self.progress["done"] += 1

        self.progress["running"] = False
        self.progress["finished"] = True
```

### Step 6: Entry point

`run.py`:

```python
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
```

Run the app with:

```
python run.py
```

---

## Frontend

Three files in `web/`. The design uses a deep ink background with a warm amber accent, Space Grotesk for headings and Inter for body text. Each course row has a dropdown caret on the right. Opening it reveals a folder browser: folders are folder shaped tiles you click into, a breadcrumb bar tracks how deep you are, and files are file shaped tiles with their names.

### web/index.html

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Canvas File Grabber</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <!-- Login view -->
  <section id="login-view" class="view">
    <div class="login-card">
      <div class="lamp"></div>
      <h1>Canvas File Grabber</h1>
      <p class="subtitle">Log in to load your courses. Your password is typed into Canvas, never into this app.</p>
      <button id="login-btn" class="primary">Log in to Canvas</button>
      <p id="login-status" class="status"></p>
    </div>
  </section>

  <!-- Main view -->
  <section id="main-view" class="view hidden">
    <header class="topbar">
      <div>
        <span class="eyebrow">Canvas File Grabber</span>
        <h1>Your courses</h1>
      </div>
      <label class="toggle">
        <input type="checkbox" id="show-past" checked>
        <span>Show past courses</span>
      </label>
    </header>

    <div id="course-list" class="course-list"></div>

    <footer class="actionbar">
      <div class="field">
        <label for="ext-input">File endings</label>
        <input type="text" id="ext-input" placeholder="pdf, pptx, docx">
      </div>
      <div class="field">
        <label>Save to</label>
        <div class="folder-pick">
          <button id="folder-btn" class="ghost">Choose folder</button>
          <span id="folder-path" class="path">downloads</span>
        </div>
      </div>
      <button id="download-btn" class="primary" disabled>Download selected</button>
    </footer>

    <div id="progress" class="progress hidden">
      <div class="bar"><div id="bar-fill" class="bar-fill"></div></div>
      <p id="progress-text" class="status"></p>
    </div>
  </section>

  <script src="app.js"></script>
</body>
</html>
```

### web/styles.css

```css
:root {
  --ink: #12141c;
  --surface: #1b1e2a;
  --surface-hi: #232735;
  --border: #2c3142;
  --text: #e8eaf0;
  --muted: #8b90a3;
  --accent: #f5b544;
  --accent-deep: #e09b2d;
  --accent-soft: rgba(245, 181, 68, 0.12);
  --radius: 14px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: "Inter", system-ui, sans-serif;
  background: var(--ink);
  color: var(--text);
  height: 100vh;
  overflow: hidden;
}

h1 { font-family: "Space Grotesk", sans-serif; font-weight: 700; letter-spacing: -0.02em; }

.hidden { display: none !important; }
.view { height: 100vh; display: flex; flex-direction: column; }
.muted { color: var(--muted); font-size: 13px; }
.pad { padding: 14px 4px; }

/* Login */
#login-view { align-items: center; justify-content: center; }
.login-card {
  position: relative; width: 380px; padding: 40px 34px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); text-align: center; overflow: hidden;
}
.lamp {
  position: absolute; top: -80px; left: 50%;
  width: 220px; height: 220px; transform: translateX(-50%);
  background: radial-gradient(circle, var(--accent-soft), transparent 70%);
  pointer-events: none;
}
.login-card h1 { font-size: 24px; margin-bottom: 10px; }
.subtitle { color: var(--muted); font-size: 14px; line-height: 1.5; margin-bottom: 24px; }

/* Buttons */
.primary {
  font: inherit; font-weight: 600; background: var(--accent);
  color: #191308; border: none; padding: 11px 20px; border-radius: 10px;
  cursor: pointer; transition: background 0.15s, transform 0.05s;
}
.primary:hover:not(:disabled) { background: var(--accent-deep); }
.primary:active:not(:disabled) { transform: translateY(1px); }
.primary:disabled { opacity: 0.4; cursor: default; }

.ghost {
  font: inherit; font-weight: 500; background: transparent; color: var(--text);
  border: 1px solid var(--border); padding: 9px 14px; border-radius: 10px; cursor: pointer;
}
.ghost:hover { border-color: var(--accent); }

.status { color: var(--muted); font-size: 13px; margin-top: 14px; min-height: 18px; }

/* Topbar */
.topbar {
  display: flex; align-items: flex-end; justify-content: space-between;
  padding: 26px 30px 18px; border-bottom: 1px solid var(--border);
}
.eyebrow { text-transform: uppercase; letter-spacing: 0.14em; font-size: 11px; color: var(--accent); font-weight: 600; }
.topbar h1 { font-size: 26px; margin-top: 4px; }
.toggle { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 13px; cursor: pointer; }
.toggle input { accent-color: var(--accent); width: 16px; height: 16px; }

/* Course list */
.course-list { flex: 1; overflow-y: auto; padding: 18px 30px; }

.course-card {
  border: 1px solid var(--border); border-left: 3px solid var(--border);
  border-radius: var(--radius); background: var(--surface);
  margin-bottom: 12px; transition: border-color 0.15s;
}
.course-card.selected { border-left-color: var(--accent); box-shadow: 0 0 0 1px var(--accent-soft); }

.course-head { display: flex; align-items: center; gap: 14px; padding: 16px 18px; }
.course-head > input[type="checkbox"] { accent-color: var(--accent); width: 18px; height: 18px; }

.course-title { flex: 1; display: flex; align-items: center; gap: 10px; }
.course-title span.name { font-weight: 600; font-size: 15px; }
.course-title small { color: var(--muted); font-size: 12px; }

.tag {
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); border: 1px solid var(--border); padding: 2px 7px; border-radius: 20px;
}

/* Dropdown caret */
.caret {
  background: transparent; border: 1px solid var(--border); color: var(--muted);
  border-radius: 8px; width: 32px; height: 32px; display: grid; place-items: center;
  cursor: pointer; transition: transform 0.2s, border-color 0.15s, color 0.15s;
}
.caret:hover { border-color: var(--accent); color: var(--accent); }
.caret.open { transform: rotate(180deg); }

/* Folder browser */
.browser { border-top: 1px solid var(--border); padding: 14px 18px 18px; }

.crumb { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; font-size: 13px; }
.crumb-link { background: none; border: none; color: var(--accent); font: inherit; cursor: pointer; padding: 0; }
.crumb-link:hover { text-decoration: underline; }
.crumb-sep { color: var(--muted); }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 10px; }

.tile {
  position: relative; display: flex; flex-direction: column; align-items: center;
  gap: 6px; padding: 14px 8px 12px; border: 1px solid transparent; border-radius: 12px;
  cursor: pointer; text-align: center; transition: background 0.12s, border-color 0.12s;
}
.tile:hover { background: var(--surface-hi); }
.tile.selected { border-color: var(--accent); background: var(--accent-soft); }

.tile-icon { width: 46px; height: 42px; display: grid; place-items: center; }
.tile-icon svg { width: 100%; height: 100%; }
.icon-folder { fill: #f2b64e; }
.icon-file .body { fill: #cbd0e0; }
.icon-file .fold { fill: #9aa0b4; }

.tile-label {
  font-size: 12px; color: var(--text); line-height: 1.3; word-break: break-word;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.tile-sub { font-size: 11px; color: var(--muted); }
.tile-check { position: absolute; top: 8px; right: 8px; accent-color: var(--accent); width: 15px; height: 15px; cursor: pointer; }

/* Action bar */
.actionbar {
  display: flex; align-items: flex-end; gap: 22px; padding: 18px 30px;
  border-top: 1px solid var(--border); background: var(--surface-hi);
}
.field { display: flex; flex-direction: column; gap: 6px; }
.field label { font-size: 12px; color: var(--muted); }
.field:first-child { flex: 1; }

#ext-input {
  font: inherit; background: var(--ink); color: var(--text);
  border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px;
}
#ext-input:focus { outline: none; border-color: var(--accent); }

.folder-pick { display: flex; align-items: center; gap: 10px; }
.path { color: var(--muted); font-size: 12px; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Progress */
.progress { padding: 14px 30px 22px; }
.bar { height: 6px; background: var(--border); border-radius: 6px; overflow: hidden; }
.bar-fill { height: 100%; width: 0; background: var(--accent); transition: width 0.3s; }

/* Scrollbar */
.course-list::-webkit-scrollbar { width: 10px; }
.course-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 6px; }

@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
```

### web/app.js

```javascript
const state = {
  courses: [],
  nav: {},      // course_id -> { path: [{id,name}], childrenOf: {} }
  files: {},    // folder_id -> [files]
  selected: {}, // course_id -> { course_name, whole, folder_ids:Set, file_ids:Set }
  outputDir: "downloads",
};

const api = () => window.pywebview.api;
const el = (id) => document.getElementById(id);

const CARET_SVG =
  '<svg viewBox="0 0 16 16" width="16" height="16"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const FOLDER_SVG =
  '<svg class="icon-folder" viewBox="0 0 48 38" xmlns="http://www.w3.org/2000/svg"><path d="M3 6a3 3 0 0 1 3-3h11l4 5h21a3 3 0 0 1 3 3v20a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3z"/></svg>';
const FILE_SVG =
  '<svg class="icon-file" viewBox="0 0 36 46" xmlns="http://www.w3.org/2000/svg"><path class="body" d="M5 4a3 3 0 0 1 3-3h14l11 11v30a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3z"/><path class="fold" d="M22 1l11 11h-8a3 3 0 0 1-3-3z"/></svg>';

/* selection helpers */
function entryFor(course) {
  return (state.selected[course.id] = state.selected[course.id] || {
    course_name: course.name, whole: false,
    folder_ids: new Set(), file_ids: new Set(),
  });
}
const isWhole = (cid) => !!(state.selected[cid] && state.selected[cid].whole);
const isFolderSelected = (cid, fid) => !!(state.selected[cid] && state.selected[cid].folder_ids.has(fid));
const isFileSelected = (cid, fid) => !!(state.selected[cid] && state.selected[cid].file_ids.has(fid));

function cleanup(cid) {
  const e = state.selected[cid];
  if (e && !e.whole && e.folder_ids.size === 0 && e.file_ids.size === 0) delete state.selected[cid];
}
function courseHasSelection(cid) {
  const e = state.selected[cid];
  return !!(e && (e.whole || e.folder_ids.size || e.file_ids.size));
}
function setWhole(course, v) { entryFor(course).whole = v; cleanup(course.id); updateDownloadButton(); }
function toggleFolder(course, fid, v) { const e = entryFor(course); v ? e.folder_ids.add(fid) : e.folder_ids.delete(fid); cleanup(course.id); updateDownloadButton(); }
function toggleFile(course, fid, v) { const e = entryFor(course); v ? e.file_ids.add(fid) : e.file_ids.delete(fid); cleanup(course.id); updateDownloadButton(); }

function refreshCard(node) {
  const card = node.closest(".course-card");
  if (!card) return;
  const cid = Number(card.dataset.courseId);
  card.classList.toggle("selected", courseHasSelection(cid));
  const cb = card.querySelector(".course-head > input[type=checkbox]");
  if (cb) cb.checked = isWhole(cid);
}

/* init */
async function init() {
  const s = await api().status();
  state.outputDir = s.output_dir;
  el("folder-path").textContent = s.output_dir;
  if (s.logged_in) showMain();
  else el("login-view").classList.remove("hidden");

  el("login-btn").addEventListener("click", onLogin);
  el("show-past").addEventListener("change", renderCourses);
  el("folder-btn").addEventListener("click", onChooseFolder);
  el("download-btn").addEventListener("click", onDownload);
}

async function onLogin() {
  el("login-status").textContent = "A browser window opened. Finish logging in there.";
  el("login-btn").disabled = true;
  const res = await api().login();
  if (res.logged_in) showMain();
  else { el("login-status").textContent = "Login did not complete. Try again."; el("login-btn").disabled = false; }
}

async function showMain() {
  el("login-view").classList.add("hidden");
  el("main-view").classList.remove("hidden");
  el("course-list").innerHTML = "<p class='muted pad'>Loading courses...</p>";
  state.courses = await api().get_courses();
  renderCourses();
}

function renderCourses() {
  const showPast = el("show-past").checked;
  const list = el("course-list");
  list.innerHTML = "";
  const courses = state.courses.filter((c) => showPast || !c.is_past);
  if (courses.length === 0) { list.innerHTML = "<p class='muted pad'>No courses found.</p>"; return; }
  courses.forEach((c) => list.appendChild(courseCard(c)));
  updateDownloadButton();
}

function courseCard(course) {
  const card = document.createElement("div");
  card.className = "course-card";
  card.dataset.courseId = course.id;
  if (courseHasSelection(course.id)) card.classList.add("selected");

  const head = document.createElement("div");
  head.className = "course-head";

  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.title = "Select the whole course";
  cb.checked = isWhole(course.id);
  cb.addEventListener("change", () => { setWhole(course, cb.checked); refreshCard(cb); });

  const title = document.createElement("div");
  title.className = "course-title";
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = course.name;
  title.appendChild(name);
  if (course.term) { const t = document.createElement("small"); t.textContent = course.term; title.appendChild(t); }
  if (course.is_past) { const tag = document.createElement("span"); tag.className = "tag"; tag.textContent = "past"; title.appendChild(tag); }

  const caret = document.createElement("button");
  caret.className = "caret";
  caret.setAttribute("aria-label", "Show folders");
  caret.innerHTML = CARET_SVG;

  const browser = document.createElement("div");
  browser.className = "browser hidden";

  caret.addEventListener("click", () => {
    const open = !browser.classList.toggle("hidden");
    caret.classList.toggle("open", open);
    if (open) openBrowser(course, browser);
  });

  head.append(cb, title, caret);
  card.append(head, browser);
  return card;
}

async function openBrowser(course, browser) {
  if (!state.nav[course.id]) {
    browser.innerHTML = "<p class='muted pad'>Loading folders...</p>";
    const folders = await api().get_folders(course.id);
    const childrenOf = {};
    folders.forEach((f) => {
      const key = f.parent_id === null ? "root" : String(f.parent_id);
      (childrenOf[key] = childrenOf[key] || []).push(f);
    });
    Object.values(childrenOf).forEach((a) => a.sort((x, y) => x.name.localeCompare(y.name)));
    state.nav[course.id] = { path: [], childrenOf };
  }
  renderBrowser(course, browser);
}

function buildCrumb(course, browser) {
  const nav = state.nav[course.id];
  const crumb = document.createElement("div");
  crumb.className = "crumb";
  const root = document.createElement("button");
  root.className = "crumb-link";
  root.textContent = course.name;
  root.addEventListener("click", () => { nav.path = []; renderBrowser(course, browser); });
  crumb.appendChild(root);
  nav.path.forEach((p, i) => {
    const sep = document.createElement("span"); sep.className = "crumb-sep"; sep.textContent = "/";
    const link = document.createElement("button"); link.className = "crumb-link"; link.textContent = p.name;
    link.addEventListener("click", () => { nav.path = nav.path.slice(0, i + 1); renderBrowser(course, browser); });
    crumb.append(sep, link);
  });
  return crumb;
}

async function renderBrowser(course, browser) {
  const nav = state.nav[course.id];
  const inside = nav.path.length > 0;
  const currentId = inside ? nav.path[nav.path.length - 1].id : null;
  const key = inside ? String(currentId) : "root";
  const folders = nav.childrenOf[key] || [];

  let files = [];
  if (inside) {
    if (!state.files[currentId]) {
      browser.innerHTML = "<p class='muted pad'>Loading...</p>";
      state.files[currentId] = await api().get_files(currentId);
    }
    files = state.files[currentId];
  }

  browser.innerHTML = "";
  browser.appendChild(buildCrumb(course, browser));

  const grid = document.createElement("div");
  grid.className = "grid";
  folders.forEach((f) => grid.appendChild(folderTile(course, f, browser)));
  files.forEach((f) => grid.appendChild(fileTile(course, f)));
  if (folders.length === 0 && files.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted pad";
    empty.textContent = "This folder is empty.";
    grid.appendChild(empty);
  }
  browser.appendChild(grid);
}

function folderTile(course, folder, browser) {
  const tile = document.createElement("div");
  tile.className = "tile folder-tile";
  if (isFolderSelected(course.id, folder.id)) tile.classList.add("selected");

  const check = document.createElement("input");
  check.type = "checkbox";
  check.className = "tile-check";
  check.checked = isFolderSelected(course.id, folder.id);
  check.addEventListener("click", (e) => e.stopPropagation());
  check.addEventListener("change", () => {
    toggleFolder(course, folder.id, check.checked);
    tile.classList.toggle("selected", check.checked);
    refreshCard(tile);
  });

  const icon = document.createElement("div");
  icon.className = "tile-icon";
  icon.innerHTML = FOLDER_SVG;

  const label = document.createElement("div");
  label.className = "tile-label";
  label.textContent = folder.name;

  const sub = document.createElement("div");
  sub.className = "tile-sub";
  sub.textContent = folder.files_count + " files";

  tile.append(check, icon, label, sub);
  tile.addEventListener("click", () => {
    state.nav[course.id].path.push({ id: folder.id, name: folder.name });
    renderBrowser(course, browser);
  });
  return tile;
}

function fileTile(course, file) {
  const tile = document.createElement("div");
  tile.className = "tile file-tile";
  if (isFileSelected(course.id, file.id)) tile.classList.add("selected");

  const icon = document.createElement("div");
  icon.className = "tile-icon";
  icon.innerHTML = FILE_SVG;

  const label = document.createElement("div");
  label.className = "tile-label";
  label.textContent = file.name;

  tile.append(icon, label);
  tile.addEventListener("click", () => {
    const now = !isFileSelected(course.id, file.id);
    toggleFile(course, file.id, now);
    tile.classList.toggle("selected", now);
    refreshCard(tile);
  });
  return tile;
}

async function onChooseFolder() {
  const res = await api().choose_output_dir();
  state.outputDir = res.path;
  el("folder-path").textContent = res.path;
}

function updateDownloadButton() {
  el("download-btn").disabled = Object.keys(state.selected).length === 0;
}

async function onDownload() {
  const extensions = el("ext-input").value.split(",").map((s) => s.trim()).filter(Boolean);
  const selections = Object.entries(state.selected).map(([cid, v]) => ({
    course_id: Number(cid),
    course_name: v.course_name,
    whole: v.whole,
    folder_ids: Array.from(v.folder_ids),
    file_ids: Array.from(v.file_ids),
  }));
  el("download-btn").disabled = true;
  el("progress").classList.remove("hidden");
  await api().start_download(selections, extensions, state.outputDir);
  pollProgress();
}

async function pollProgress() {
  const p = await api().get_progress();
  const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
  el("bar-fill").style.width = pct + "%";
  el("progress-text").textContent = p.finished
    ? "Done. Downloaded " + p.done + " of " + p.total + " files into your folder."
    : "Downloading " + p.done + " of " + p.total + ": " + p.current;
  if (!p.finished) setTimeout(pollProgress, 500);
  else updateDownloadButton();
}

window.addEventListener("pywebviewready", init);
```

---

## How browsing and selection work

**Building the tree.** When a course is expanded, the frontend fetches its folders once as a flat list and groups them by `parent_id` into a lookup map. Folders with no parent are the top level. Because the whole tree comes from that one request, clicking into nested folders is instant and needs no more folder requests.

**Navigating.** A breadcrumb tracks the path from the course name down to the current folder. Clicking a folder tile pushes it onto the path and shows its subfolders and files. Clicking any breadcrumb segment jumps back to that level. Files for a folder are fetched the first time you open it and then cached.

**Selecting.** There are three ways to pick what to download, and they combine. The course checkbox selects the whole course. The checkbox on a folder tile selects that folder. Clicking a file tile selects that single file. A course row shows the amber highlight whenever any of its folders, files, or the course itself is selected.

**Downloading.** The backend gathers files from the whole course, from each selected folder, and from each selected file, fetching fresh lists and fresh single file URLs so links do not expire. It dedupes by file id, so a file counted twice (once by folder, once on its own) downloads only once. The file endings box filters every download, and an empty box keeps all files. Files land in `output_dir/course_name/`, one subfolder per course, with duplicate names getting a numbered suffix.

---

## .gitignore

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

**Terms of service.** Automating login to a school Canvas instance may conflict with the school's or Canvas's acceptable use policy, even when you only access your own account and files. Check your institution's rules before using this. This is the main non technical risk.

**Login is not headless.** The first login needs a visible browser so the user can complete SSO and OTP. The app cannot silently log in from a stored email and password, and that is on purpose, because programmatic password and OTP handling breaks on SSO schools and is fragile. The tradeoff is one manual login, after which the saved session is reused.

**Past courses depend on the school's settings.** Past courses show up only if the school leaves concluded courses and their files visible to students. Some schools lock past courses after a term ends, and Canvas will not return those. This is a server side policy the app cannot change.

**The stored session file is sensitive.** `storage_state.json` holds live session cookies. Anyone who copies that file could act as the user until the session expires. It is gitignored, but a hardened version would store it in the OS keychain instead of a plain file.

**Folder and file listing can be restricted.** Some courses disable the folders or files endpoint. Those return empty, so the browser simply shows nothing for that course. A later version could fall back to scanning modules and pages for file links.

**Folder file counts.** The count shown on a folder tile is the count Canvas reports for that folder only, not including its subfolders. Selecting a folder downloads the files directly in it. To also grab a subfolder, open it and select it too.

**Rate limits.** Canvas throttles heavy API use. For accounts with many large courses, add a short delay between requests if you start seeing HTTP 403 or 429 responses.

**Linux setup.** pywebview needs a system webview backend on Linux (GTK or Qt). macOS and Windows work out of the box.
```