import argparse
import os

from config import load_config
from auth import login_and_save
from canvas import (
    session_from_storage,
    session_is_valid,
    list_courses,
    list_course_files,
)
from downloader import matches_extension, safe_name, download_file


def main():
    parser = argparse.ArgumentParser(description="Download Canvas files by extension.")
    parser.add_argument("--ext", help="Comma separated extensions, e.g. pdf,pptx")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--relogin", action="store_true", help="Force a fresh login")
    args = parser.parse_args()

    cfg = load_config(args.config)
    base_url = cfg["base_url"]
    storage_path = cfg["storage_path"]

    # Extensions: command line wins, otherwise ask, otherwise config default.
    if args.ext:
        extensions = [e.strip() for e in args.ext.split(",") if e.strip()]
    elif cfg["extensions"]:
        extensions = cfg["extensions"]
    else:
        raw = input("File endings to download (comma separated): ")
        extensions = [e.strip() for e in raw.split(",") if e.strip()]

    if not extensions:
        print("No extensions given. Nothing to do.")
        return

    # Log in if there is no valid session.
    need_login = args.relogin or not os.path.exists(storage_path)
    if not need_login:
        session = session_from_storage(storage_path)
        if not session_is_valid(session, base_url):
            print("Saved session expired. Logging in again.")
            need_login = True

    if need_login:
        login_and_save(base_url, storage_path)
        session = session_from_storage(storage_path)
        if not session_is_valid(session, base_url):
            print("Login did not produce a valid session. Exiting.")
            return

    print("Fetching courses...")
    courses = list_courses(session, base_url)
    print(f"Found {len(courses)} active courses.")

    total = 0
    for course in courses:
        course_name = safe_name(course.get("name") or f"course_{course['id']}")
        files = list_course_files(session, base_url, course["id"])
        wanted = [f for f in files
                  if matches_extension(f.get("display_name")
                                       or f.get("filename", ""), extensions)]
        if files and not wanted:
            print(f"{course_name}: {len(files)} files found (none match {extensions})")
        if not wanted:
            continue

        dest = os.path.join(cfg["output_dir"], course_name)
        print(f"{course_name}: {len(wanted)} matching files")
        for f in wanted:
            try:
                path = download_file(session, f, dest)
                total += 1
                print(f"  saved {os.path.basename(path)}")
            except Exception as e:
                print(f"  failed {f.get('display_name')}: {e}")

    print(f"\nDone. Downloaded {total} files into {cfg['output_dir']}/")


if __name__ == "__main__":
    main()