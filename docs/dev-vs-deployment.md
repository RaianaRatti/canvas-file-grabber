# `python run.py` vs. the packaged app

The app runs identically in both modes on paper, but a handful of environment
facts differ, and the current codebase has one latent bug that only surfaces in
the packaged mode. This doc covers both.

## What differs

| | `python run.py` (dev) | Packaged build (PyInstaller `--onefile --windowed`) |
|---|---|---|
| `sys.frozen` | not set | `True` |
| Code/assets location | read straight from the repo tree | extracted at launch to a temp dir (`sys._MEIPASS`), wiped every run |
| `app_dir()` (`src/config.py`) | repo root (`dirname(dirname(config.py))`) | folder containing the executable; on macOS, the folder *containing* `CanvasFileGrabber.app` (three levels up from `Contents/MacOS/`) |
| **Current working directory** | wherever the user's shell `cd`'d to before running the command — normally the repo root, since the README's dev instructions run it from there | **not guaranteed to be the app's folder.** Double-clicking a `.app` on macOS launches it via LaunchServices/Finder, which typically sets cwd to `/` or the user's home directory, not the bundle's location. Windows Explorer double-click behavior and Linux file managers vary too. |
| stdout/stderr | visible in the terminal | **not visible.** `--windowed` means there's no console; an uncaught exception on a background thread just disappears |
| `config.json` source | `cp config.example.json config.json`, edited by hand per the README | must exist next to the executable; typically also started from `config.example.json` (bundled into the build via `--add-data`) |
| Chromium for login | usually finds a system Chrome/Edge install, so Playwright's bundled Chromium is rarely needed | same lookup, but `PLAYWRIGHT_BROWSERS_PATH` is redirected to `app_dir()/browsers` (`src/auth.py:_set_browsers_path`) so a downloaded Chromium persists between launches instead of living in the wiped `_MEIPASS` temp dir |

The two facts that matter most for debugging "works locally, silently does
nothing when packaged" symptoms are **cwd is not the app's folder** and
**exceptions on background threads are invisible**. Both are in play in the bug
below.

## Known issue: login silently never completes in packaged builds

**Symptom:** the SSO browser opens, the user logs in, the tab closes itself —
and then nothing happens. The app stays on the login screen. `storage_state.json`
is never created (or updated). This does not happen with `python run.py`.

**Root cause:** `config.example.json` ships:

```json
{
  "base_url": "https://canvas.youruniversity.edu",
  "output_dir": "downloads/",
  "storage_path": "storage_state.json"
}
```

`storage_path` and `output_dir` here are **bare relative paths**. But
[src/config.py](../src/config.py) has since been hardened to prefer an absolute,
frozen-safe default:

```python
cfg.setdefault("output_dir", os.path.join(app_dir(), "downloads"))
cfg.setdefault("storage_path", os.path.join(app_dir(), "storage_state.json"))
```

`setdefault` only fires when the key is *absent*. Because `config.example.json`
(and therefore every `config.json` copied from it) already sets `storage_path`
explicitly, the safe default never applies — the app uses the bare
`"storage_state.json"` string as-is. Two failures follow from that:

1. `os.path.dirname("storage_state.json")` is `""` (no directory component).
   [src/auth.py:77](../src/auth.py#L77) then runs
   `os.makedirs(os.path.dirname(storage_path), exist_ok=True)`, i.e.
   `os.makedirs("", exist_ok=True)` — which raises `FileNotFoundError`
   unconditionally, in any environment. (Verified directly: `os.makedirs("",
   exist_ok=True)` always raises.)
2. Even a relative path *with* a directory component would resolve against the
   process's **current working directory**, which — per the table above — is not
   reliably the app's own folder in a packaged, GUI-launched build.

That exception happens inside `Api._do_login`
([src/api.py:60-64](../src/api.py#L60-L64)), which runs on a bare
`threading.Thread` with no `try/except`. An uncaught exception there kills the
thread silently:

- there's no console in a `--windowed` build to print the traceback to, so it's
  invisible;
- `_set_login_state("done", ...)` is never reached, so `login_state` stays
  frozen at `"waiting_for_browser"`;
- the frontend's `window.onLoginStateChange` ([web/app.js:149](../web/app.js#L149))
  never fires again, so the UI never leaves the login screen.

The Chrome/SSO tab still closes on its own, because `browser.close()` sits in a
`finally` block in `auth.login_and_save` — that part runs regardless of the
exception. That's why the visible symptom is "tab closes, then nothing," not an
obvious crash.

**Why local dev doesn't show it:** once a valid `storage_state.json` exists in
the repo root (from any earlier successful login, e.g. before
`config.example.json` had `storage_path` set to a value, or from directly
constructing one), `Api.status()` finds it valid and reports `logged_in: true`
without ever calling `login_and_save()` again. Deleting the local
`storage_state.json` and re-running `python run.py` from a *fresh* clone with
the current `config.example.json` reproduces the same `FileNotFoundError` even
outside a packaged build — the packaging isn't the cause, it just removes the
console output and the pre-existing session file that were both masking it
locally.

**Fix applied:**
- `output_dir` / `storage_path` were removed from `config.example.json` (and the
  local `config.json`), so `config.py`'s `app_dir()`-based defaults take over
  again — `storage_path` now always resolves to an absolute path next to the
  app, regardless of the process's cwd.
- `Api._do_login` ([src/api.py](../src/api.py)) now wraps `login_and_save()` in
  `try/except`, prints the traceback, and pushes `"done", False` on failure
  instead of letting the thread die silently. A future regression here will
  kick the user back to the login screen with "Login did not complete. Try
  again." instead of hanging forever — still not a visible error message, but
  no longer an infinite hang.
