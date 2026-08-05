import os
import re

def matches_extension(filename, extensions):
    if not extensions:
        return True
    lower = filename.lower()
    return any(lower.endswith("." + e.lower().lstrip(".")) for e in extensions)

# NOTES ---------------
#   1. lower = filename.lower() -> converts filename (and thus extension) to lowercase (for case insensitivity in extension)
#   2. For all extensions e, lowercase extension name, remove dot (if present), add dot
#               - .PDF -> .pdf -> pdf -> .pdf
#   3. Checks any(lower.endswith(extensions)), any returns true if 1+ extensions match

# SUMMARY: Checks if a file matches the set of valid extensions (if none are provided, all are accepted)


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name or "").strip() or "untitled"

# NOTES ---------------
#   1. re.sub(r'[<>:"/\\|?*]', "_", name or "") -> replaces characters that are invalid in Windows filenames (< > : " / \\ | ? * ") with _
#   2. or "untitled" -> names files with no name (name = None) "untitled"

# SUMMARY: Converts filename into one that is safe to use on the filesystem (no illegal characters or untitled file)

def unique_path(directory, filename):
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base} ({i}){ext}")
        i += 1
    return candidate

# NOTES --------------
#   1. 


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