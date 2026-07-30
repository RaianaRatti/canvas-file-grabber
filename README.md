# Canvas File Grabber

A small desktop app that logs into your Canvas account, shows your courses (current and past) in a folder browser, and downloads only the file types you choose into a folder on your computer.

## What it does

- Lists all of your Canvas courses, including past ones if your school keeps them visible.
- Lets you browse into course folders the way you would in a file explorer: folders you click into, files shown with their names.
- Lets you select a whole course, specific folders, or individual files.
- Filters everything by file ending, for example `pdf, pptx, docx`.
- Downloads into a folder you pick, organized into one subfolder per course.

## How login works

The app opens a real browser window pointed at your school's Canvas login page. You type your own email, password, and one time code there, the same as you always do. The app never sees or stores your password. Once you are logged in, it saves your session so you do not have to log in again next time, until that session expires.

## Requirements

- Python 3.10 or newer
- Google Chrome or Chromium available for Playwright to drive (installed automatically in setup below)
- On Linux: a system webview backend (GTK or Qt), see setup

## Setup

```
git clone https://github.com/your-username/canvas-file-grabber.git
cd canvas-file-grabber
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp config.example.json config.json
```

Open `config.json` and set `base_url` to your school's Canvas address, for example `https://canvas.youruniversity.edu`.

On Linux, install a webview backend if you do not already have one:

```
sudo apt install python3-gi gir1.2-webkit2-4.1
```

## Running

```
python run.py
```

A window opens. The first time, click **Log in to Canvas** and finish logging in in the browser window that appears, including any school SSO steps and your one time code. Come back to the app and your courses will load.

## Using the app

1. Tick a course's checkbox to grab the whole course, or click the caret on the right to open its folder browser.
2. Click a folder tile to open it. Nested folders open the same way, and a breadcrumb bar at the top tracks where you are.
3. Tick a folder's checkbox to grab everything directly inside it, or click a file tile to grab just that file.
4. Type the file endings you want, separated by commas. Leave it blank to keep every file type.
5. Choose an output folder.
6. Click **Download selected**.

Files are saved as `your-output-folder/Course Name/filename.ext`.

## Project structure

```
canvas-file-grabber/
├── README.md
├── PLAN.md
├── requirements.txt
├── config.example.json
├── run.py
├── src/
│   ├── config.py
│   ├── auth.py
│   ├── canvas.py
│   ├── downloader.py
│   └── api.py
└── web/
    ├── index.html
    ├── styles.css
    └── app.js
```

See `PLAN.md` for the full design and the reasoning behind each part.

## Packaging as a standalone app (PyInstaller)

This turns the project into a single app your users can double click, with no Python install and no terminal required on their end. Full step by step walkthrough is below in the chat response. The short version:

```
pip install pyinstaller
pyinstaller --name CanvasFileGrabber --windowed \
  --collect-all playwright --collect-all webview \
  --add-data "web:web" --add-data "config.example.json:." \
  run.py
```

On Windows, replace the colons in `--add-data` with semicolons. See the walkthrough for the code changes needed first, the two ways to handle Playwright's browser, and the exact commands per operating system.

## Limitations

**Terms of service.** Automating login to a school Canvas instance may conflict with the school's or Canvas's acceptable use policy, even when you only access your own account and files. Check your institution's rules before using this.

**Login is not headless.** The first login needs a visible browser window so you can complete SSO and your one time code. This is intentional, since automating passwords and OTP codes directly breaks on most school SSO setups.

**The saved session file is sensitive.** `storage_state.json` holds live login cookies. Anyone with that file could act as you until the session expires. It is not committed to the repo.

**Selecting a folder does not include its subfolders automatically.** It grabs the files directly inside that folder. Open a subfolder and select it separately if you want its files too.

**Rate limits.** Canvas throttles heavy API use. If you see repeated failures on a very large course, wait a bit and try again.

## License

MIT