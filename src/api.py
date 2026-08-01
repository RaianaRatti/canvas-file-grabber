import json
import os
import threading
import time

import webview

from config import load_config
from auth import login_and_save
import canvas
from downloader import matches_extension, safe_name, download_file


class Api:
    def __init__(self, config_path=None):
        self.cfg = load_config(config_path)
        self.session = None
        self.progress = {
            "running": False, "done": 0, "total": 0,
            "current": "", "finished": False,
        }
        self.login_state = {"stage": "idle", "logged_in": False}

    def status(self):
        path = self.cfg["storage_path"]
        if os.path.exists(path):
            s = canvas.session_from_storage(path)
            if canvas.session_is_valid(s, self.cfg["base_url"]):
                self.session = s
                return {"logged_in": True, "output_dir": self.cfg["output_dir"]}
        return {"logged_in": False, "output_dir": self.cfg["output_dir"]}

    def start_login(self):
        if self.login_state["stage"] in ("waiting_for_browser", "validating"):
            return {"started": False}
        self.login_state = {"stage": "waiting_for_browser", "logged_in": False}
        t = threading.Thread(target=self._do_login, daemon=True)
        t.start()
        return {"started": True}

    def _set_login_state(self, stage, logged_in):
        """Update login_state and push it to the page immediately.

        The window that opens the SSO browser loses OS focus for as long as
        the user is logging in there, and while backgrounded, WKWebView/App
        Nap can throttle or fully suspend the page's own setTimeout polling
        loop. evaluate_js is a direct call into the webview from Python, not
        a JS timer, so it still lands even while the window is backgrounded
        - polling from the JS side alone could silently skip states.
        """
        self.login_state = {"stage": stage, "logged_in": logged_in}
        try:
            window = webview.windows[0]
            window.evaluate_js(
                f"window.onLoginStateChange && window.onLoginStateChange({json.dumps(self.login_state)})"
            )
        except Exception:
            pass

    def _do_login(self):
        ok = login_and_save(self.cfg["base_url"], self.cfg["storage_path"])
        if not ok:
            self._set_login_state("done", False)
            return

        # The Chrome window is closed at this point. login_and_save() already
        # confirmed the session works inside the real browser; this follow-up
        # check re-validates it with a bare requests.Session, which can
        # transiently fail right after an SSO redirect even though the
        # cookies are good. Retry briefly instead of sending the user back
        # to the login screen on a fluke.
        self._set_login_state("validating", False)
        s = canvas.session_from_storage(self.cfg["storage_path"])
        valid = False
        for attempt in range(5):
            if canvas.session_is_valid(s, self.cfg["base_url"]):
                valid = True
                break
            if attempt < 4:
                time.sleep(1)
        if valid:
            self.session = s
        self._set_login_state("done", valid)

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