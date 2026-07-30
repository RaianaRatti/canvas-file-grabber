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