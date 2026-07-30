# PLAN.md

## Summary

**canvas-file-grabber** is a small desktop app that logs into any Canvas instance as the user, shows all of their courses (current and past) in a window, lets them pick whole courses or specific folders, and downloads the matching files into a folder they choose.

**Goal:** Open a native window that lists your Canvas courses. Expand any course to see its folders. Tick the courses or folders you want, type the file endings to keep (for example `pdf, pptx, docx`), pick an output folder, and download. It works on school hosted Canvas instances, including ones behind SSO and multi factor authentication (OTP), and it includes past courses.

**How auth works:** The user logs in through a real browser window that the tool controls. They type their own email, password, and OTP into the genuine Canvas login page. The app never sees or stores the raw password. After a successful login the session cookies are saved locally and reused, so the browser only appears once. All course listing and downloading then happens over plain HTTP using those cookies.

**How the UI works:** A Python backend exposes a small set of methods. A native window built with **pywebview** loads a local HTML/CSS/JS frontend. The frontend calls the backend methods directly through `window.pywebview.api`, so there is no separate web server, no ports, and no CORS setup.

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
│   ├── styles.css         # frontend styling
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

**Past courses** are handled by asking Canvas twice, once for active enrollments and once for completed ones, then merging the two lists. Active is processed last so a course you are still in is never mislabeled as past. Passing `include[]=term` gives each course its term name for display.

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
        return []  # some courses disable the files API
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

This is the object the frontend talks to. Every public method here becomes callable from JavaScript as `window.pywebview.api.method_name(...)` and returns a promise. Downloads run on a background thread so the window stays responsive, and the frontend reads progress by polling `get_progress`.

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
        out = [{
            "id": f["id"],
            "name": f.get("full_name") or f.get("name"),
            "files_count": f.get("files_count", 0),
        } for f in folders]
        out.sort(key=lambda x: x["name"])
        return out

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

        jobs = []  # (course_name, file_obj)
        for sel in selections:
            course_id = sel["course_id"]
            course_name = safe_name(sel.get("course_name") or f"course_{course_id}")
            folder_ids = sel.get("folder_ids") or []

            if folder_ids:
                files = []
                for fid in folder_ids:
                    files.extend(canvas.list_folder_files(self.session, base_url, fid))
            else:
                files = canvas.list_course_files(self.session, base_url, course_id)

            for f in files:
                name = f.get("display_name") or f.get("filename", "")
                if matches_extension(name, exts):
                    jobs.append((course_name, f))

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

Three files in `web/`. The design uses a deep ink background with a warm amber accent, Space Grotesk for headings and Inter for body text, and course cards that behave like file folders that open to reveal their contents.

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

/* Login */
#login-view { align-items: center; justify-content: center; }

.login-card {
  position: relative;
  width: 380px;
  padding: 40px 34px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  text-align: center;
  overflow: hidden;
}

.lamp {
  position: absolute;
  top: -80px; left: 50%;
  width: 220px; height: 220px;
  transform: translateX(-50%);
  background: radial-gradient(circle, var(--accent-soft), transparent 70%);
  pointer-events: none;
}

.login-card h1 { font-size: 24px; margin-bottom: 10px; }
.subtitle { color: var(--muted); font-size: 14px; line-height: 1.5; margin-bottom: 24px; }

/* Buttons */
.primary {
  font: inherit; font-weight: 600;
  background: var(--accent);
  color: #191308;
  border: none;
  padding: 11px 20px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s, transform 0.05s;
}
.primary:hover:not(:disabled) { background: var(--accent-deep); }
.primary:active:not(:disabled) { transform: translateY(1px); }
.primary:disabled { opacity: 0.4; cursor: default; }

.ghost {
  font: inherit; font-weight: 500;
  background: transparent;
  color: var(--text);
  border: 1px solid var(--border);
  padding: 9px 14px;
  border-radius: 10px;
  cursor: pointer;
}
.ghost:hover { border-color: var(--accent); }

.status { color: var(--muted); font-size: 13px; margin-top: 14px; min-height: 18px; }

/* Topbar */
.topbar {
  display: flex; align-items: flex-end; justify-content: space-between;
  padding: 26px 30px 18px;
  border-bottom: 1px solid var(--border);
}
.eyebrow {
  text-transform: uppercase; letter-spacing: 0.14em;
  font-size: 11px; color: var(--accent); font-weight: 600;
}
.topbar h1 { font-size: 26px; margin-top: 4px; }

.toggle { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 13px; cursor: pointer; }
.toggle input { accent-color: var(--accent); width: 16px; height: 16px; }

/* Course list */
.course-list { flex: 1; overflow-y: auto; padding: 18px 30px; }

.course-card {
  border: 1px solid var(--border);
  border-left: 3px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  margin-bottom: 12px;
  transition: border-color 0.15s;
}
.course-card.selected { border-left-color: var(--accent); box-shadow: 0 0 0 1px var(--accent-soft); }

.course-head { display: flex; align-items: center; gap: 14px; padding: 16px 18px; }
.course-head input[type="checkbox"] { accent-color: var(--accent); width: 18px; height: 18px; }

.course-title { flex: 1; display: flex; align-items: center; gap: 10px; }
.course-title span.name { font-weight: 600; font-size: 15px; }
.course-title small { color: var(--muted); font-size: 12px; }

.tag {
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); border: 1px solid var(--border);
  padding: 2px 7px; border-radius: 20px;
}

.expand {
  font: inherit; font-size: 13px; font-weight: 500;
  background: transparent; color: var(--accent);
  border: none; cursor: pointer;
}

.folder-box { padding: 0 18px 14px 46px; }
.folder-row {
  display: flex; align-items: center; gap: 10px;
  padding: 7px 0; color: var(--text); font-size: 13px; cursor: pointer;
}
.folder-row input { accent-color: var(--accent); width: 15px; height: 15px; }
.folder-row:hover { color: var(--accent); }

.muted { color: var(--muted); font-size: 13px; padding: 6px 0; }

/* Action bar */
.actionbar {
  display: flex; align-items: flex-end; gap: 22px;
  padding: 18px 30px;
  border-top: 1px solid var(--border);
  background: var(--surface-hi);
}
.field { display: flex; flex-direction: column; gap: 6px; }
.field label { font-size: 12px; color: var(--muted); }
.field:first-child { flex: 1; }

#ext-input {
  font: inherit;
  background: var(--ink);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
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

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; }
}
```

### web/app.js

```javascript
const state = {
  courses: [],
  folders: {},   // course_id -> [folders]
  selected: {},  // course_id -> { course_name, folder_ids: Set }
  outputDir: "downloads",
};

const api = () => window.pywebview.api;
const el = (id) => document.getElementById(id);

async function init() {
  const s = await api().status();
  state.outputDir = s.output_dir;
  el("folder-path").textContent = s.output_dir;

  if (s.logged_in) {
    showMain();
  } else {
    el("login-view").classList.remove("hidden");
  }

  el("login-btn").addEventListener("click", onLogin);
  el("show-past").addEventListener("change", renderCourses);
  el("folder-btn").addEventListener("click", onChooseFolder);
  el("download-btn").addEventListener("click", onDownload);
}

async function onLogin() {
  el("login-status").textContent = "A browser window opened. Finish logging in there.";
  el("login-btn").disabled = true;
  const res = await api().login();
  if (res.logged_in) {
    showMain();
  } else {
    el("login-status").textContent = "Login did not complete. Try again.";
    el("login-btn").disabled = false;
  }
}

async function showMain() {
  el("login-view").classList.add("hidden");
  el("main-view").classList.remove("hidden");
  el("course-list").innerHTML = "<p class='muted'>Loading courses...</p>";
  state.courses = await api().get_courses();
  renderCourses();
}

function renderCourses() {
  const showPast = el("show-past").checked;
  const list = el("course-list");
  list.innerHTML = "";

  const courses = state.courses.filter((c) => showPast || !c.is_past);
  if (courses.length === 0) {
    list.innerHTML = "<p class='muted'>No courses found.</p>";
    return;
  }
  courses.forEach((c) => list.appendChild(courseCard(c)));
  updateDownloadButton();
}

function courseCard(course) {
  const card = document.createElement("div");
  card.className = "course-card";
  if (state.selected[course.id]) card.classList.add("selected");

  const head = document.createElement("div");
  head.className = "course-head";

  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = !!state.selected[course.id];
  cb.addEventListener("change", () => {
    toggleCourse(course, cb.checked);
    card.classList.toggle("selected", cb.checked);
  });

  const title = document.createElement("div");
  title.className = "course-title";
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = course.name;
  title.appendChild(name);
  if (course.term) {
    const t = document.createElement("small");
    t.textContent = course.term;
    title.appendChild(t);
  }
  if (course.is_past) {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = "past";
    title.appendChild(tag);
  }

  const expand = document.createElement("button");
  expand.className = "expand";
  expand.textContent = "Folders";
  expand.addEventListener("click", () => toggleFolders(course, card));

  head.append(cb, title, expand);
  card.appendChild(head);

  const box = document.createElement("div");
  box.className = "folder-box hidden";
  card.appendChild(box);
  return card;
}

function toggleCourse(course, checked) {
  if (checked) {
    state.selected[course.id] = state.selected[course.id] ||
      { course_name: course.name, folder_ids: new Set() };
  } else {
    delete state.selected[course.id];
  }
  updateDownloadButton();
}

async function toggleFolders(course, card) {
  const box = card.querySelector(".folder-box");
  if (!box.classList.contains("hidden")) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");

  if (!state.folders[course.id]) {
    box.innerHTML = "<p class='muted'>Loading folders...</p>";
    state.folders[course.id] = await api().get_folders(course.id);
  }
  box.innerHTML = "";
  const folders = state.folders[course.id];
  if (folders.length === 0) {
    box.innerHTML = "<p class='muted'>No folders available for this course.</p>";
    return;
  }
  folders.forEach((f) => {
    const row = document.createElement("label");
    row.className = "folder-row";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    const sel = state.selected[course.id];
    cb.checked = sel ? sel.folder_ids.has(f.id) : false;
    cb.addEventListener("change", () => toggleFolder(course, f.id, cb.checked));
    const label = document.createElement("span");
    label.textContent = `${f.name} (${f.files_count})`;
    row.append(cb, label);
    box.appendChild(row);
  });
}

function toggleFolder(course, folderId, checked) {
  const entry = state.selected[course.id] ||
    { course_name: course.name, folder_ids: new Set() };
  if (checked) entry.folder_ids.add(folderId);
  else entry.folder_ids.delete(folderId);
  state.selected[course.id] = entry;
  updateDownloadButton();
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
  const extensions = el("ext-input").value
    .split(",").map((s) => s.trim()).filter(Boolean);

  const selections = Object.entries(state.selected).map(([cid, v]) => ({
    course_id: Number(cid),
    course_name: v.course_name,
    folder_ids: Array.from(v.folder_ids),
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
    ? `Done. Downloaded ${p.done} of ${p.total} files into your folder.`
    : `Downloading ${p.done} of ${p.total}: ${p.current}`;

  if (!p.finished) {
    setTimeout(pollProgress, 500);
  } else {
    updateDownloadButton();
  }
}

window.addEventListener("pywebviewready", init);
```

---

## How selection maps to downloads

A course selection is one object with `course_id`, `course_name`, and `folder_ids`. If `folder_ids` is empty, the backend downloads every file in that course. If it has folder ids, only those folders are downloaded. Ticking a folder without ticking the course still works, because the frontend creates the course entry the moment a folder is picked. The file endings box filters every download, so an empty box means keep everything.

Files land in `output_dir/course_name/`, one subfolder per course, with duplicate names getting a numbered suffix so nothing is overwritten.

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

**Course files API can be restricted.** Some courses disable the files or folders endpoint. Those return empty instead of erroring, so they simply show no folders. A later version could fall back to scanning modules and pages for file links.

**Download URLs are time limited.** Canvas file links expire quickly. The app lists and downloads in one pass, so this only matters for very large batches, where a rerun may be needed.

**Rate limits.** Canvas throttles heavy API use. For accounts with many large courses, add a short delay between requests if you start seeing HTTP 403 or 429 responses.

**Linux setup.** pywebview needs a system webview backend on Linux (GTK or Qt). macOS and Windows work out of the box.
```