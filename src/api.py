import os
import threading

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