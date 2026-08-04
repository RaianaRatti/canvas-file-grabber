import json
from concurrent.futures import ThreadPoolExecutor

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

# NOTES ---------------
#   1. Opens file at storage_path + loads JSON object as python dict = saves storage values in state
#   2. s = requests.Session() -> creates persistent HTTP session (useful for staying logged in)
#           - A session remembers cookies, headers, connections
#   3. s.headers.update({"User-Agent": "Mozilla/5.0"}) -> tells server what kind of client is making request
#           - In this case, it is a normal web browser
#           - Our agent is not Mozilla/5.0, we are python-requests/2.23.3 however the latter is often treated as bot requests and may not allow login
#   4. for c in state.get("cookies", []) -> returns & loops through state.cookies or [] (if cookies is None)
#   5. s.cookies.set(...) -> adds one cookie to the session
#           - A cookie has the elements "name", "value", "domain", "path" (use "/" default if path is None)
#   6. Return session

# SUMMARY: Obtains cookies information from storage_state.json, creates a session, sends header as normal user, loops through cookies and sets current session in cookies

def session_is_valid(session, base_url):
    try:
        r = session.get(f"{base_url}/api/v1/users/self", timeout=15)
        return r.status_code == 200
    except requests.RequestException:
        return False

# NOTES ---------------
#   1. Takes session + base_url (e.g. https://umich.instructure.com)
#   2. r = session.get(...) -> sends GET request to base_url+api/v1/users/self
#           - This GET request automatically includes your cookies as we are using session.get()
#   3. Return True or False if cookies were accepted (status_code == 200)
#   4. If error (no internet, timeout, etc.) -> just return status_is_valid = False

# SUMMARY: Returns whether current session is valid with earlier cookies (timeout = 15ms)


def _get_paginated(session, url, params=None):
    results = []
    while url:
        r = session.get(url, params=params, timeout=30)
        params = None
        r.raise_for_status()
        results.extend(r.json())

        url = None
        for part in r.headers.get("Link", "").split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
    return results

# NOTES ---------------
#   1. Takes session, url (your API endpoint), params (optional query parameters e.g. per_page = 100)
#   2. while url (is not None) -> while there is another page
#   3. r = session.get(...) -> GET request to next page
#           - r is a requests.Response object
#   4. params = None -> Canvas includes correct parameter in the url (r) it sends so we do not want to add params in it twice
#           - First request: GET /courses?per_page=100
#           - Canvas response: <https://.../courses?page=2&per_page=100>; rel="next"
#   5. r.raise_for_status() -> raise error if HTTP returns failture status code (4xx)
#   6. results.extend(r.json()) -> adds this page's data to results
#   7. url = None -> Set url to none so, if there is no other page, we break out of while
#   8. Many paginated headers return a link like the following:
#           - Link:
#             <https://.../courses?page=2>; rel="next",
#             <https://.../courses?page=10>; rel="last"
#      for part in r.headers.get("Link", "")split(",") -> Gets Link header, splits into pieces at each comma (so each line is separate)
#   9. if 'rel="next"' in part -> checks whether this piece points to the next page
#   10. url = part.split(";")[0].strip().strip("<>") -> gets just the https://, sets it to url

# SUMMARY: Function repeatedly sends GET reqeusts to every page of a paginated API, combiens all results (https:// URLs) into one list, and returns that list 

def list_courses(session, base_url):
    url = f"{base_url}/api/v1/courses"
    states = ("completed", "active")

    def fetch(state):
        params = {"enrollment_state": state, "per_page": 100, "include[]": "term"}
        try:
            return _get_paginated(session, url, params=params)
        except requests.HTTPError:
            return []

    # NOTES ---------------
    # SUMMARY: Attempts to fetch all documents in a particular enrollment_state at once

    with ThreadPoolExecutor(max_workers=len(states)) as ex:
        pages = list(ex.map(fetch, states))

    seen = {}
    for state, page in zip(states, pages):
        for c in page:
            cid = c.get("id")
            if cid is None:
                continue
            c["is_past"] = (state == "completed")
            seen[cid] = c
    return list(seen.values())

# NOTES ---------------
#   1. map(fetch, states) -> map(function, iterable) calls the function once for every item in the iterable
#   2. ex.map(fetch, states) -> runs fetch for each iterable (state) at the same time
#              - The above returns an iterator to start of a linked list, nodes are classes gotten in each state
#   3. list(ex.map(fetch, states)) -> wraps nodes in linked list returned by ex.map(...) into list
#   4. for state, page in zip(states, pages) -> Loops through all pages in each state and stores them in map ("seen")
#   5. seen[cid] = c -> Appends page by its id ("cid"), if page with that id already existed it is overwritten by new one
#              - This allows "active" courses' pages to be processed last (and thus kept) as states = (completed, active) (order matters here)
#   6. Returns list of pages

# SUMMARY: Returns list of all pages, multithreaded by state (completed + active), overwriting pages that appear twice and preferring active > completed pages to be kept if overwriting

def list_folders(session, base_url, course_id):
    url = f"{base_url}/api/v1/courses/{course_id}/folders"
    try:
        return _get_paginated(session, url, params={"per_page": 100})
    except requests.HTTPError:
        return []

# NOTES ---------------
# SUMMARY: Gets all folders in a course (fetches every page of folders with _get_paginated())

def list_folder_files(session, base_url, folder_id):
    url = f"{base_url}/api/v1/folders/{folder_id}/files"
    try:
        return _get_paginated(session, url, params={"per_page": 100})
    except requests.HTTPError:
        return []

# NOTES ---------------
# SUMMARY: Gets all files in a specific folder (fetches every page of files with _get_paginated())

def list_course_files(session, base_url, course_id):
    url = f"{base_url}/api/v1/courses/{course_id}/files"
    try:
        return _get_paginated(session, url, params={"per_page": 100})
    except requests.HTTPError:
        return []

# NOTES ---------------
# SUMMARY: Gets all files in a specific course (fetche s every page of files with _get_paginated())

def get_file(session, base_url, file_id):
    r = session.get(f"{base_url}/api/v1/files/{file_id}", timeout=30)
    r.raise_for_status()
    return r.json()

# NOTES ---------------
# SUMMARY: Gets all information about / in one specific file (ensures no error code i.e. 4xx)