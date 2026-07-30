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
        return []


def get_file(session, base_url, file_id):
    r = session.get(f"{base_url}/api/v1/files/{file_id}", timeout=30)
    r.raise_for_status()
    return r.json()