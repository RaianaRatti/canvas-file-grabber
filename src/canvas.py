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