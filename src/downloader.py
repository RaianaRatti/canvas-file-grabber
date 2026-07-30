import os
import re

def matches_extension(filename, extensions):
    lower = filename.lower()
    return any(lower.endswith("." + e.lower().lstrip(".")) for e in extensions)


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


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