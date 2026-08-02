# Architecture

Canvas File Grabber is a desktop app built on [pywebview](https://pywebview.flowrl.com/):
a native window that renders local HTML/CSS/JS and exposes a Python object as a
JS-callable API. There is no server and no build step for the frontend — it's
plain HTML/CSS/JS loaded from disk.

```
run.py                     window bootstrap (pywebview entry point)
  └── src/api.py            Api class — the js_api bridge, one method per UI action
        ├── src/auth.py     Playwright: real-browser login, saves session cookies
        ├── src/canvas.py   requests-based Canvas REST API client
        ├── src/downloader.py   extension filtering + streamed file download
        └── src/config.py   config.json loading, persistent-path resolution
  └── web/                  frontend: index.html + app.js + styles.css
```

## Process model

`run.py` creates one `pywebview` window and passes an `Api` instance as `js_api`.
pywebview auto-generates a JS-side proxy so the frontend can call
`window.pywebview.api.<method>(...)` and get a Promise back. Every `Api` method in
[src/api.py](../src/api.py) is directly callable from [web/app.js](../web/app.js) this way —
that's the entire frontend/backend contract; there's no HTTP layer between them.

Long-running work (login, downloads) is kicked off on a daemon `threading.Thread`
so the call returns immediately and doesn't block the webview's UI thread. Progress
is polled from JS (`get_progress`), except for login state, which is pushed from
Python instead (see below).

## Login flow

Login is deliberately done in a **real, visible browser window** via Playwright
([src/auth.py](../src/auth.py)), not scripted against Canvas's login form. School SSO
flows (Duo, OTP, redirects) vary too much to automate reliably, and the app never
wants to see the user's password.

1. `Api.start_login()` spawns a background thread running `_do_login`.
2. `auth.login_and_save()` launches a browser (prefers an installed Chrome/Edge via
   `channel=`, falls back to Playwright's bundled Chromium, downloading it once if
   necessary) and navigates to `base_url`.
3. It polls `GET {base_url}/api/v1/users/self` *through the browser's own cookies*
   every 2s until it returns 200 — this is how it detects "the user finished
   logging in" without needing `input()` (which has no stdin in a windowed app).
4. On success, `context.storage_state(path=storage_path)` dumps the browser's
   cookies to `storage_state.json`, and the browser closes.
5. Back in `Api`, `canvas.session_from_storage()` turns those cookies into a plain
   `requests.Session()` — Playwright is only needed for the interactive login;
   every API call afterward is a fast, headless HTTP request via `requests`.

### Why login state is *pushed*, not polled

While the user is in the separate SSO browser window, the pywebview window is
backgrounded. WKWebView/App Nap (and equivalents) can throttle or suspend a
page's own `setTimeout` polling loop while backgrounded, so a JS-side poll could
silently miss the moment login finishes. Instead, `Api._set_login_state()` calls
`window.evaluate_js(...)` directly from Python — a direct call into the webview,
not a JS timer — so `window.onLoginStateChange` in [web/app.js](../web/app.js) fires
even while the window doesn't have focus. See `_set_login_state` in
[src/api.py](../src/api.py) for the full rationale.

Login state machine: `idle → waiting_for_browser → validating → done`.
`validating` re-checks the session with a bare `requests.Session` (the
`context.storage_state()` cookies can transiently look invalid right after an SSO
redirect even though they're good), retrying up to 5 times before giving up.

## Canvas API client

[src/canvas.py](../src/canvas.py) is a thin, paginated REST client over the plain
`requests.Session` produced from `storage_state.json`. Nothing here is
Canvas-account-specific beyond `base_url` — it just walks `Link: rel="next"`
headers. `list_courses()` fetches `completed` and `active` enrollments
concurrently (two independent paginated requests) since Canvas has no single
endpoint for "all courses regardless of state."

## Downloads

[src/downloader.py](../src/downloader.py) filters by extension, sanitizes filenames,
dedupes existing files (`unique_path` appends ` (1)`, ` (2)`, ...), and streams each
file to disk in chunks. `Api._run_download()` builds the job list from the user's
selection (whole course / specific folders / specific files, deduped by file id)
before starting.

## Persistent files

Four things need to survive between runs and must **not** end up inside a
PyInstaller temp extraction directory that gets wiped on every launch:

| File/dir            | Purpose                                   |
|----------------------|--------------------------------------------|
| `config.json`         | `base_url`, `output_dir`, `storage_path`  |
| `storage_state.json`  | Playwright session cookies (sensitive — never share) |
| `downloads/`           | default download destination              |
| `browsers/`            | persistent Chromium download, if no system Chrome/Edge is found |

All of these are resolved relative to **`app_dir()`** in [src/config.py](../src/config.py),
which returns the folder containing the executable (or, on macOS, the folder
*containing* the `.app` bundle) when frozen, and the repo root otherwise. All four
are gitignored. See [dev-vs-deployment.md](dev-vs-deployment.md) for the ways this
resolution differs between `python run.py` and a packaged build, and a bug that
currently falls out of that difference.

## Packaging

Built with PyInstaller in `--onefile --windowed` mode (see
[.github/workflows/build.yml](../.github/workflows/build.yml), which builds Windows/macOS/Linux
artifacts on each GitHub release). `--collect-all playwright --collect-all webview`
bundles both packages' non-Python assets (Playwright's Node driver, webview's
native bits); `--add-data` bundles `web/` and `config.example.json` into the
executable's resources. Frozen-app code paths are gated on `sys.frozen` and
`sys._MEIPASS` throughout `src/config.py` and `src/auth.py`.
